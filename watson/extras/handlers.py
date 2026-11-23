"""What policy handlers do: toast, autostop, prompt."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

import arrow

from ..timezone import local_tz_info
from ..watson import ConflictError, Watson, WatsonError
from . import review
from .policies import Action, RunningFrame
from .settings import format_duration

log = logging.getLogger(__name__)

AUTOSTOP_TAG = "auto-stopped"


@dataclass
class Outcome:
    toasts: list[str] = field(default_factory=list)
    stopped: object = None  # the Frame an autostop created, if any
    lines: list[str] = field(default_factory=list)


def _fmt(moment: datetime.datetime) -> str:
    # Policy times are in UTC; show them in local time. (Not arrow's
    # "local": since arrow 1.4 that's a fixed offset, see watson.timezone.)
    return arrow.get(moment).to(local_tz_info()).format("ddd HH:mm")


def _between(start: datetime.datetime, end: datetime.datetime) -> datetime.timedelta:
    """Real time between two aware datetimes (not wall clock, across DST)."""
    return datetime.timedelta(seconds=end.timestamp() - start.timestamp())


def describe(action: Action, frame: RunningFrame, now: datetime.datetime) -> str:
    """Human description of a due action (for logs and --dry-run)."""
    what = {
        "toast": "warn",
        "autostop": f"stop it at {_fmt(action.stop_at)}",
        "prompt": "flag it for review",
    }[action.kind]
    return (
        f"policy '{action.policy.name}': {what} "
        f"('{frame.project}' since {_fmt(frame.start)}; due {_fmt(action.due_at)})"
    )


def toast_text(action: Action, frame: RunningFrame, now: datetime.datetime) -> str:
    if action.policy.trigger == "offhours":
        text = (
            f"'{frame.project}' has been running outside work hours since "
            f"{_fmt(action.onset)}."
        )
    elif action.policy.trigger == "idle":
        text = (
            f"No keyboard or mouse activity since {_fmt(action.onset)}; "
            f"'{frame.project}' is still running."
        )
    else:
        text = f"'{frame.project}' has been running for {format_duration(_between(frame.start, now))}."
    if action.autostop_at is not None and action.autostop_at > now:
        text += f" It will be stopped in {format_duration(_between(now, action.autostop_at))}."
    return text


def autostop(config_dir: str, action: Action, frame: RunningFrame):
    """Stop the frame, provided it's still the one that triggered the policy.

    The caller holds the store lock. The CLI doesn't take that lock, so
    reload Watson's state right before writing (compare-and-swap on the
    frame start) to avoid acting on a frame the user already changed. If a
    CLI command saves in between, the save raises ConflictError: reload and
    check again.
    """
    for attempt in range(3):
        watson = Watson(config_dir=config_dir)
        current = watson.current
        if not current or int(current["start"].timestamp()) != int(
            frame.start.timestamp()
        ):
            log.info("autostop skipped: '%s' is no longer running", frame.project)
            return None
        tags = list(current["tags"])
        if AUTOSTOP_TAG not in tags:
            tags.append(AUTOSTOP_TAG)
        watson.current = {**current, "tags": tags}
        try:
            stopped = watson.stop(stop_at=arrow.get(action.stop_at))
            watson.save()
        except ConflictError as e:
            if attempt < 2:
                log.info("autostop retrying: %s", e)
                continue
            log.error("autostop failed: %s", e)
            return None
        except WatsonError as e:
            log.error("autostop failed: %s", e)
            return None
        log.info(
            "auto-stopped '%s' at %s (%s)",
            frame.project,
            action.stop_at,
            action.policy.name,
        )
        return stopped
    return None


def execute(
    actions: list[Action],
    frame: RunningFrame,
    state: dict,
    config_dir: str,
    now: datetime.datetime,
) -> Outcome:
    """Run the planned actions. ``state`` is the open store transaction."""
    out = Outcome()
    for action in actions:
        out.lines.append(describe(action, frame, now))
        if action.kind == "autostop":
            stopped = autostop(config_dir, action, frame)
            if stopped is not None:
                out.stopped = stopped
                note = f"Stopped '{frame.project}' at {_fmt(action.stop_at)}"
                note += f" (policy '{action.policy.name}')."
                if any(h.name == "prompt" for h in action.policy.handlers):
                    note += " You'll be asked to confirm it at the next `watson start`."
                out.toasts.append(note)
        elif action.kind == "prompt":
            review.add_review(
                state,
                project=frame.project,
                frame_start=frame.start,
                policy=action.policy.name,
                suggested_stop=action.stop_at,
                stopped=out.stopped,
                now=now,
            )
        elif action.kind == "toast":
            out.toasts.append(toast_text(action, frame, now))
    return out
