import datetime
import json
import operator
import os
from configparser import Error as CFGParserError
from functools import reduce
from typing import Any

import arrow
import click

from .config import ConfigParser
from .frames import Frames
from .lock import FileLock, LockTimeout
from .timezone import duration, local_tz_info
from .utils import deduplicate, make_json_writer, safe_save, sorted_groupby
from .version import version as __version__  # noqa


class WatsonError(RuntimeError):
    pass


class ConfigurationError(CFGParserError, WatsonError):
    pass


class ConflictError(WatsonError):
    """Another process changed the data files after this one read them."""


DATA_LOCK_FILENAME = "data.lock"


def _fingerprint(path):
    """Identity of a file's current version, or None if it doesn't exist.

    Saves replace files (a new inode each time), so the inode alone tells
    versions apart; mtime and size cover filesystems without stable inodes.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


class Watson:
    def __init__(self, **kwargs):
        """
        :param frames: If given, should be a list representing the
                        frames.
                        If not given, the value is extracted
                        from the frames file.
        :type frames: list

        :param current: If given, should be a dict representing the
                        current frame.
                        If not given, the value is extracted
                        from the state file.
        :type current: dict

        :param config_dir: If given, the directory where the configuration
                           files will be
        """
        self._current: dict[str, Any] | None = None
        self._old_state: dict[str, Any] | None = None
        self._frames: Frames | None = None
        self._config: ConfigParser | None = None
        self._config_changed = False
        # Fingerprints of the data files as read, checked again before saving
        self._fingerprints: dict[str, Any] = {}

        self._dir = kwargs.pop("config_dir", None) or click.get_app_dir("watson")

        self.config_file = os.path.join(self._dir, "config")
        self.frames_file = os.path.join(self._dir, "frames")
        self.state_file = os.path.join(self._dir, "state")

        if "frames" in kwargs:
            self.frames = kwargs["frames"]

        if "current" in kwargs:
            self.current = kwargs["current"]

    @property
    def config_dir(self):
        """The data directory holding the config, frames and state files."""
        return self._dir

    def _load_json_file(self, filename, type: Any = dict) -> Any:
        """
        Return the content of the the given JSON file.
        If the file doesn't exist, return an empty instance of the
        given type.
        """
        # Stat before reading: if the file is replaced in between, the save
        # check sees a spurious conflict rather than missing a real one.
        self._fingerprints[filename] = _fingerprint(filename)
        try:
            with open(filename, encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            return type()
        except ValueError as e:
            # If we get an error because the file is empty, we ignore
            # it and return an empty dict. Otherwise, we raise
            # an exception in order to avoid corrupting the file.
            if os.path.getsize(filename) == 0:
                return type()
            else:
                raise WatsonError(f"Invalid JSON file {filename}: {e}") from e
        except Exception as e:
            raise WatsonError(
                f"Unexpected error while loading JSON file {filename}: {e}"
            ) from e

    def _parse_date(self, date):
        """Returns Arrow object from timestamp."""
        return arrow.Arrow.utcfromtimestamp(date).to(local_tz_info())

    def _format_date(self, date):
        """Returns timestamp from string timestamp or Arrow object."""
        if not isinstance(date, arrow.Arrow):
            date = arrow.get(date)

        return date.int_timestamp

    @property
    def config(self):
        """
        Return Watson's config as a ConfigParser object.
        """
        if not self._config:
            try:
                config = ConfigParser()
                config.read(self.config_file, encoding="utf-8")
            except CFGParserError as e:
                raise ConfigurationError(f"Cannot parse config file: {e}") from e

            self._config = config

        return self._config

    @config.setter
    def config(self, value):
        """
        Set a ConfigParser object as the current configuration.
        """
        self._config = value
        self._config_changed = True

    def save(self):
        """
        Save the state in the appropriate files. Create them if necessary.

        Several processes may share the data directory (e.g. the CLI and the
        forgotten-timer watcher), and each one rewrites whole files. So that
        one doesn't silently undo another's changes, nothing is saved, and
        ConflictError is raised, if a frames or state file this instance read
        was changed by another process since.
        """
        writes = []
        current = None
        if self._current is not None and self._old_state != self._current:
            if self.is_started:
                current = {
                    "project": self.current["project"],
                    "start": self._format_date(self.current["start"]),
                    "tags": self.current["tags"],
                }
            else:
                current = {}
            writes.append((self.state_file, make_json_writer(lambda: current)))
        if self._frames is not None and self._frames.changed:
            writes.append((self.frames_file, make_json_writer(self.frames.dump)))
        if self._config_changed:
            writes.append((self.config_file, self.config.write))
        if not writes:
            return

        try:
            if not os.path.isdir(self._dir):
                os.makedirs(self._dir)

            with FileLock(os.path.join(self._dir, DATA_LOCK_FILENAME)):
                self._check_unchanged()
                for path, content in writes:
                    safe_save(path, content)
                    if path in (self.state_file, self.frames_file):
                        self._fingerprints[path] = _fingerprint(path)
                if current is not None:
                    self._old_state = current

        except LockTimeout as e:
            raise WatsonError(str(e)) from e
        except OSError as e:
            raise WatsonError(f"Impossible to write {e.filename}: {e}") from e

    def _check_unchanged(self):
        changed = [
            os.path.basename(path)
            for path, seen in self._fingerprints.items()
            if _fingerprint(path) != seen
        ]
        if changed:
            raise ConflictError(
                "{} changed since this command read {}, probably by another "
                "Watson process (e.g. the watcher stopping a forgotten "
                "timer). Nothing was saved; run the command again.".format(
                    " and ".join(f"'{name}'" for name in sorted(changed)),
                    "it" if len(changed) == 1 else "them",
                )
            )

    @property
    def frames(self):
        if self._frames is None:
            self.frames = self._load_json_file(self.frames_file, type=list)

        assert self._frames is not None
        return self._frames

    @frames.setter
    def frames(self, frames):
        self._frames = Frames(frames)

    @property
    def current(self):
        if self._current is None:
            self.current = self._load_json_file(self.state_file)

        if self._old_state is None:
            self._old_state = self._current

        assert self._current is not None
        return dict(self._current)

    @current.setter
    def current(self, value):
        if not value or "project" not in value:
            self._current = {}

            if self._old_state is None:
                self._old_state = {}

            return

        start = value.get("start", arrow.now())

        if not isinstance(start, arrow.Arrow):
            start = self._parse_date(start)

        self._current = {
            "project": value["project"],
            "start": start,
            "tags": value.get("tags") or [],
        }

        if self._old_state is None:
            self._old_state = self._current

    @property
    def is_started(self):
        return bool(self.current)

    def add(self, project, from_date, to_date, tags):
        if not project:
            raise WatsonError("No project given.")
        if arrow.get(from_date).timestamp() > arrow.get(to_date).timestamp():
            raise WatsonError("Task cannot end before it starts.")

        default_tags = self.config.getlist("default_tags", project)
        tags = (tags or []) + default_tags

        frame = self.frames.add(project, from_date, to_date, tags=tags)
        return frame

    def start(self, project, tags=None, restart=False, start_at=None, gap=True):
        if self.is_started:
            raise WatsonError(
                "Project {} is already started.".format(self.current["project"])
            )

        default_tags = self.config.getlist("default_tags", project)
        if not restart:
            tags = (tags or []) + default_tags

        if start_at is None:
            start_at = arrow.now()
        elif self.frames:
            # Only perform this check if an explicit start time was given
            # and previous frames exist
            stop_of_prev_frame = self.frames[-1].stop
            if start_at.timestamp() < stop_of_prev_frame.timestamp():
                raise WatsonError("Task cannot start before the previous task ends.")
        if start_at.timestamp() > arrow.now().timestamp():
            raise WatsonError("Task cannot start in the future.")

        new_frame = {"project": project, "tags": deduplicate(tags)}
        new_frame["start"] = start_at
        if not gap:
            stop_of_prev_frame = self.frames[-1].stop
            new_frame["start"] = stop_of_prev_frame
        self.current = new_frame
        return self.current

    def stop(self, stop_at=None):
        if not self.is_started:
            raise WatsonError("No project started.")

        old = self.current

        if stop_at is None:
            # One cannot use `arrow.now()` as default argument. Default
            # arguments are evaluated when a function is defined, not when its
            # called. Since there might be huge delays between defining this
            # stop function and calling it, the value of `stop_at` could be
            # outdated if defined using a default argument.
            stop_at = arrow.now()
        if old["start"].timestamp() > stop_at.timestamp():
            raise WatsonError("Task cannot end before it starts.")
        if stop_at.timestamp() > arrow.now().timestamp():
            raise WatsonError("Task cannot end in the future.")

        frame = self.frames.add(old["project"], old["start"], stop_at, tags=old["tags"])
        self.current = None

        return frame

    def cancel(self):
        if not self.is_started:
            raise WatsonError("No project started.")

        old_current = self.current
        self.current = None
        return old_current

    @property
    def projects(self):
        """
        Return the list of all the existing projects, sorted by name.
        """
        return sorted(set(self.frames["project"]))

    @property
    def tags(self):
        """
        Return the list of the tags, sorted by name.
        """
        return sorted(set(tag for tags in self.frames["tags"] for tag in tags))

    def merge_report(self, frames_with_conflict):
        conflict_file_frames = Frames(
            self._load_json_file(frames_with_conflict, type=list)
        )
        conflicting = []
        merging = []

        for conflict_frame in conflict_file_frames:
            try:
                original_frame = self.frames[conflict_frame.id]

                if original_frame != conflict_frame:
                    # frame from conflict frames file conflicts with frame
                    # from original frames file
                    conflicting.append(conflict_frame)

            except KeyError:
                # conflicting frame doesn't exist in original frame
                merging.append(conflict_frame)

        return conflicting, merging

    def _validate_report_options(self, filtrate, ignored):
        return not bool(
            filtrate and ignored and set(filtrate).intersection(set(ignored))
        )

    def report(
        self,
        from_,
        to,
        current=None,
        projects=None,
        tags=None,
        ignore_projects=None,
        ignore_tags=None,
        include_partial_frames=False,
    ):
        if not self._validate_report_options(projects, ignore_projects):
            raise WatsonError("given projects can't be ignored at the same time")

        if not self._validate_report_options(tags, ignore_tags):
            raise WatsonError("given tags can't be ignored at the same time")

        if from_.timestamp() > to.timestamp():
            raise WatsonError("'from' must be anterior to 'to'")

        if current is None:
            current = self.config.getboolean("options", "report_current")

        if self.current and current:
            cur = self.current
            self.frames.add(
                cur["project"], cur["start"], arrow.utcnow(), cur["tags"], id="current"
            )

        span = self.frames.span(from_, to)

        frames_by_project = sorted_groupby(
            self.frames.filter(
                projects=projects or None,
                tags=tags or None,
                ignore_projects=ignore_projects or None,
                ignore_tags=ignore_tags or None,
                span=span,
                include_partial_frames=include_partial_frames,
            ),
            operator.attrgetter("project"),
        )

        if self.current and current:
            del self.frames["current"]

        total = datetime.timedelta()

        report = {
            "timespan": {
                "from": span.start,
                "to": span.stop,
            },
            "projects": [],
        }

        for project, frames in frames_by_project:
            frames = tuple(frames)
            delta = reduce(
                operator.add,
                (duration(f.start, f.stop) for f in frames),
                datetime.timedelta(),
            )
            total += delta

            project_report = {
                "name": project,
                "time": delta.total_seconds(),
                "tags": [],
            }

            if tags is None:
                tags = []

            tags_to_print = sorted(
                set(
                    tag
                    for frame in frames
                    for tag in frame.tags
                    if tag in tags or not tags
                )
            )

            for tag in tags_to_print:
                delta = reduce(
                    operator.add,
                    (duration(f.start, f.stop) for f in frames if tag in f.tags),
                    datetime.timedelta(),
                )

                project_report["tags"].append(
                    {"name": tag, "time": delta.total_seconds()}
                )

            report["projects"].append(project_report)

        report["time"] = total.total_seconds()
        return report

    def rename_project(self, old_project, new_project):
        """Rename a project in all affected frames."""
        if old_project not in self.projects:
            raise WatsonError(f'Project "{old_project}" does not exist')

        updated_at = arrow.utcnow()
        # rename project
        for frame in self.frames:
            if frame.project == old_project:
                self.frames[frame.id] = frame._replace(
                    project=new_project, updated_at=updated_at
                )

        self.frames.changed = True
        self.save()

    def rename_tag(self, old_tag, new_tag):
        """Rename a tag in all affected frames."""
        if old_tag not in self.tags:
            raise WatsonError(f'Tag "{old_tag}" does not exist')

        updated_at = arrow.utcnow()
        # rename tag
        for frame in self.frames:
            if old_tag in frame.tags:
                self.frames[frame.id] = frame._replace(
                    tags=[new_tag if t == old_tag else t for t in frame.tags],
                    updated_at=updated_at,
                )

        self.frames.changed = True
        self.save()
