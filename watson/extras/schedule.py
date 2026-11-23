"""Work schedules: the standard ``[schedule]`` and an optional alternate.

The alternate lives at a fixed path, ``<WATSON_DIR>/schedule-alternate.ini``.
For the dates in its inclusive ``[start, end]`` range it replaces the
standard schedule; keys it leaves out are inherited from the standard one.
"""

from __future__ import annotations

import configparser
import datetime
import os
from dataclasses import dataclass, field

from ..timezone import local_tz_info

UTC = datetime.UTC

ALTERNATE_FILENAME = "schedule-alternate.ini"

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_ALIASES = {
    **{d: i for i, d in enumerate(WEEKDAYS)},
    **{
        name: i
        for i, name in enumerate(
            (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            )
        )
    },
}

DEFAULT_WORKDAYS = "mon tue wed thu fri"
DEFAULT_HOURS = "09:00-17:00"


class ScheduleError(Exception):
    """The schedule configuration can't be used (hard error)."""


@dataclass(frozen=True)
class Schedule:
    """Work days and hours, in local wall-clock time."""

    workdays: frozenset[int]  # 0 = Monday
    hours: tuple[tuple[int, int], ...]  # (start, end) minutes since midnight
    holidays: frozenset[datetime.date]
    source: str = "standard"

    def is_work_day(self, day: datetime.date) -> bool:
        return day.weekday() in self.workdays and day not in self.holidays

    def work_intervals(self, day: datetime.date) -> list[tuple]:
        """Aware (start, end) datetimes of the work hours on ``day``."""
        if not self.is_work_day(day):
            return []
        tz = local_tz_info()
        midnight = datetime.datetime.combine(day, datetime.time(), tzinfo=tz)
        out = []
        for start, end in self.hours:
            out.append((_wall(midnight, start), _wall(midnight, end)))
        return out

    def describe(self) -> str:
        days = " ".join(WEEKDAYS[d] for d in sorted(self.workdays)) or "(none)"
        hours = " ".join(f"{_hhmm(s)}-{_hhmm(e)}" for s, e in self.hours)
        return f"{days} {hours}"


def _wall(midnight: datetime.datetime, minutes: int) -> datetime.datetime:
    """Local wall-clock time ``minutes`` after ``midnight`` (DST-safe)."""
    day = midnight.date() + datetime.timedelta(days=minutes // 1440)
    minutes %= 1440
    return datetime.datetime.combine(
        day, datetime.time(minutes // 60, minutes % 60), tzinfo=midnight.tzinfo
    )


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Alternate:
    start: datetime.date
    end: datetime.date
    schedule: Schedule
    path: str


@dataclass
class Schedules:
    """Resolves the schedule in effect for any date."""

    standard: Schedule
    alternate: Alternate | None = None
    warnings: list[str] = field(default_factory=list)

    def for_date(self, day: datetime.date) -> Schedule:
        alt = self.alternate
        if alt is not None and alt.start <= day <= alt.end:
            return alt.schedule
        return self.standard

    def work_intervals(self, start, end) -> list[tuple]:
        """Merged work intervals overlapping ``[start, end]``, clipped to it.

        The intervals are in UTC. Datetimes sharing a ``tzinfo`` compare and
        subtract by wall clock, which is off by an hour across a DST change,
        so everything here is compared, and handed out, in UTC.
        """
        tz = local_tz_info()
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        out = []
        # The day before: ranges ending at 24:00 belong to the previous day
        day = start.astimezone(tz).date() - datetime.timedelta(days=1)
        while day <= end.astimezone(tz).date():
            for s, e in self.for_date(day).work_intervals(day):
                s, e = max(s.astimezone(UTC), start), min(e.astimezone(UTC), end)
                if s < e:
                    if out and s <= out[-1][1]:
                        out[-1] = (out[-1][0], max(out[-1][1], e))
                    else:
                        out.append((s, e))
            day += datetime.timedelta(days=1)
        return out

    def offhours_runs(self, start, end) -> list[tuple]:
        """Consecutive off-hours intervals within ``[start, end]``, in UTC."""
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        runs = []
        cursor = start
        for s, e in self.work_intervals(start, end):
            if cursor < s:
                runs.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < end:
            runs.append((cursor, end))
        return runs

    def is_work_time(self, moment) -> bool:
        return self.current_work_interval(moment) is not None

    def current_work_interval(self, moment):
        """The work interval containing ``moment`` (in UTC), or None."""
        day = moment.astimezone(local_tz_info()).date()
        moment = moment.astimezone(UTC)
        for s, e in self.for_date(day).work_intervals(day):
            s, e = s.astimezone(UTC), e.astimezone(UTC)
            if s <= moment < e:
                return s, e
        return None

    def explain(self, day: datetime.date) -> str:
        sched = self.for_date(day)
        if sched.source == "alternate":
            alt = self.alternate
            assert alt is not None
            what = f"alternate schedule ({alt.start} to {alt.end}, {alt.path})"
        else:
            what = "standard schedule"
        if not sched.is_work_day(day):
            reason = "holiday" if day in sched.holidays else "not a work day"
            return f"{day}: {reason} under the {what}"
        return f"{day}: {sched.describe()} under the {what}"


def parse_workdays(raw: str, where: str) -> frozenset[int]:
    days = set()
    for token in raw.replace(",", " ").split():
        key = token.strip().lower()
        if key not in _WEEKDAY_ALIASES:
            raise ScheduleError(f"{where} workdays: unknown day '{token}'")
        days.add(_WEEKDAY_ALIASES[key])
    return frozenset(days)


def _parse_clock(text: str, where: str) -> int:
    try:
        hours, minutes = text.split(":")
        hours, minutes = int(hours), int(minutes)
    except ValueError:
        raise ScheduleError(f"{where} hours: '{text}' is not HH:MM") from None
    if not (0 <= minutes < 60 and (0 <= hours < 24 or (hours, minutes) == (24, 0))):
        raise ScheduleError(f"{where} hours: '{text}' is not a valid time")
    return hours * 60 + minutes


def parse_hours(raw: str, where: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    for token in raw.replace(",", " ").split():
        start, sep, end = token.partition("-")
        if not sep:
            raise ScheduleError(f"{where} hours: '{token}' is not HH:MM-HH:MM")
        s, e = _parse_clock(start, where), _parse_clock(end, where)
        if e <= s:
            raise ScheduleError(
                f"{where} hours: '{token}' ends before it starts "
                "(ranges can't cross midnight; split them at 24:00)"
            )
        ranges.append((s, e))
    ranges.sort()
    for (_, e1), (s2, _) in zip(ranges, ranges[1:], strict=False):
        if s2 < e1:
            raise ScheduleError(f"{where} hours: ranges overlap")
    return tuple(ranges)


def parse_date(raw: str, where: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(raw.strip())
    except ValueError:
        raise ScheduleError(f"{where}: '{raw}' is not a YYYY-MM-DD date") from None


def parse_holidays(raw: str, where: str) -> frozenset[datetime.date]:
    return frozenset(
        parse_date(token, f"{where} holidays")
        for token in raw.replace(",", " ").split()
    )


def _schedule_from(get, where: str, base: Schedule | None, source: str) -> Schedule:
    """Build a Schedule from a ``get(key) -> str | None`` lookup.

    Keys that are absent (None) come from ``base``, or the defaults.
    """
    raw_days = get("workdays")
    raw_hours = get("hours")
    raw_holidays = get("holidays")
    return Schedule(
        workdays=(
            parse_workdays(raw_days, where)
            if raw_days is not None
            else (base.workdays if base else parse_workdays(DEFAULT_WORKDAYS, where))
        ),
        hours=(
            parse_hours(raw_hours, where)
            if raw_hours is not None and raw_hours.strip()
            else (base.hours if base else parse_hours(DEFAULT_HOURS, where))
        ),
        holidays=(
            parse_holidays(raw_holidays, where)
            if raw_holidays is not None
            else (base.holidays if base else frozenset())
        ),
        source=source,
    )


def alternate_path(config_dir: str) -> str:
    return os.path.join(config_dir, ALTERNATE_FILENAME)


def load_schedules(watson) -> Schedules:
    """Load the standard schedule and the alternate file (if any).

    Raises ScheduleError for unusable configuration. An alternate whose end
    is before its start is ignored with a warning.
    """
    config = watson.config
    standard = _schedule_from(
        lambda key: config.get("schedule", key), "[schedule]", None, "standard"
    )
    schedules = Schedules(standard=standard)

    path = alternate_path(watson.config_dir)
    if not os.path.exists(path):
        return schedules

    parser = configparser.RawConfigParser()
    try:
        with open(path, encoding="utf-8") as f:
            parser.read_file(f)
    except (OSError, configparser.Error) as e:
        raise ScheduleError(f"{path}: can't be parsed: {e}") from None
    if not parser.has_section("schedule"):
        raise ScheduleError(f"{path}: missing the [schedule] section")

    def get(key):
        return (
            parser.get("schedule", key) if parser.has_option("schedule", key) else None
        )

    where = f"{path} [schedule]"
    raw_dates = {}
    for key in ("start", "end"):
        raw = (get(key) or "").strip()
        if not raw:
            raise ScheduleError(f"{where}: '{key}' (YYYY-MM-DD) is required")
        raw_dates[key] = raw
    start = parse_date(raw_dates["start"], f"{where} start")
    end = parse_date(raw_dates["end"], f"{where} end")
    alt_schedule = _schedule_from(get, where, standard, "alternate")

    if end < start:
        schedules.warnings.append(
            f"{path}: end {end} is before start {start}; the alternate "
            "schedule is ignored"
        )
        return schedules

    schedules.alternate = Alternate(
        start=start, end=end, schedule=alt_schedule, path=path
    )
    return schedules


def write_alternate(
    config_dir: str,
    start: datetime.date,
    end: datetime.date,
    standard: Schedule | None = None,
) -> str:
    """Create the alternate file. With ``standard``, copy its values."""
    path = alternate_path(config_dir)
    lines = [
        "# Alternate work schedule; replaces the standard [schedule] in Watson's",
        "# config for the dates from start to end (both inclusive). Keys left",
        "# out are inherited from the standard schedule. An empty `workdays =`",
        "# means no work days (e.g. vacation).",
        "[schedule]",
        f"start = {start.isoformat()}",
        f"end = {end.isoformat()}",
    ]
    if standard is not None:
        lines += [
            "workdays = " + " ".join(WEEKDAYS[d] for d in sorted(standard.workdays)),
            "hours = " + " ".join(f"{_hhmm(s)}-{_hhmm(e)}" for s, e in standard.hours),
            "holidays = " + " ".join(sorted(d.isoformat() for d in standard.holidays)),
        ]
    else:
        lines += [
            "# workdays = mon tue wed thu fri",
            "# hours = 09:00-17:00",
            "# holidays =",
        ]

    from ..utils import safe_save

    os.makedirs(config_dir, exist_ok=True)
    safe_save(path, "\n".join(lines) + "\n")
    return path
