"""Forgotten-timer policy engine. Pure: no I/O, the clock is a parameter.

A policy has one trigger and one or more handlers:

- ``elapsed``: fires when the running frame is ``after`` old.
- ``offhours``: fires when the frame has run ``after`` consecutively outside
  work hours. Each off-hours run (e.g. Fri 17:00 -> Mon 09:00) is judged on
  its own; returning to work hours resets the count.
- ``idle``: fires when the system has had no input for ``after``. The caller
  measures the idle episode's start (``idle_since``); activity starts a new one.

Each handler (``toast``, ``autostop``, ``prompt``) fires at the trigger's
fire time plus its own offset (``toast@-15m`` warns 15 minutes early). A
handler is identified by a key, so it is delivered exactly once.

All arithmetic is done in UTC: aware datetimes that share a ``tzinfo`` add
and subtract by wall clock, which is an hour off across a DST change. The
times in an ``Action`` are in UTC; convert them to local time for display.
"""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass

from .settings import HandlerSpec, Policy

UTC = datetime.UTC


def _utc(moment: datetime.datetime) -> datetime.datetime:
    return moment.astimezone(UTC)


def _utc_frame(frame: RunningFrame) -> RunningFrame:
    return dataclasses.replace(frame, start=_utc(frame.start))


@dataclass(frozen=True)
class RunningFrame:
    project: str
    start: datetime.datetime  # aware
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return str(int(self.start.timestamp()))


@dataclass(frozen=True)
class Action:
    policy: Policy
    handler: HandlerSpec
    onset: datetime.datetime  # start of the counted span
    fire_at: datetime.datetime  # onset + policy.after
    due_at: datetime.datetime  # fire_at + handler.offset
    key: str
    stop_at: datetime.datetime  # where an autostop would end the frame
    autostop_at: datetime.datetime | None  # this policy's autostop time, if any

    @property
    def kind(self) -> str:
        return self.handler.name


@dataclass
class Plan:
    actions: list[Action]  # to run now: autostop first, then prompts, toasts
    skipped: list[Action]  # superseded or stale; record as delivered


def firings(
    policy: Policy, frame: RunningFrame, schedules, horizon, idle_since=None
) -> list[tuple]:
    """``(onset, fire_at)`` pairs for ``policy`` with fire times up to ``horizon``."""
    frame = _utc_frame(frame)
    horizon = _utc(horizon)
    idle_since = None if idle_since is None else _utc(idle_since)
    if policy.trigger == "elapsed":
        fire_at = frame.start + policy.after
        return [(frame.start, fire_at)] if fire_at <= horizon else []

    if policy.trigger == "idle":
        if idle_since is None:
            return []
        fire_at = idle_since + policy.after
        return [(idle_since, fire_at)] if fire_at <= horizon else []

    out = []
    for run_start, run_end in schedules.offhours_runs(frame.start, horizon):
        # run_end is clipped at horizon; a run clipped there lasts at least
        # until horizon, so fire_at <= run_end proves the run reaches fire_at.
        fire_at = run_start + policy.after
        if fire_at <= run_end:
            out.append((run_start, fire_at))
    return out


def _stop_time(policy, frame, onset, fire_at, now):
    # Stopping at the onset of the off-hours run (e.g. 17:00) is what you
    # want when you forgot to stop on your way out. If the frame itself
    # started off-hours, onset == start and that would erase the frame, so
    # fall back to the fire time.
    if policy.stop_at == "onset" and onset > frame.start:
        when = onset
    else:
        when = fire_at
    return min(when, now)


def event_key(frame: RunningFrame, policy: Policy, handler: HandlerSpec, onset) -> str:
    return f"{frame.key}:{policy.name}:{handler.index}:{int(onset.timestamp())}"


def plan(
    frame: RunningFrame,
    policies: list[Policy],
    schedules,
    now: datetime.datetime,
    delivered: set[str],
    poll_interval: datetime.timedelta,
    idle_since: datetime.datetime | None = None,
) -> Plan:
    """Decide which handlers to run now.

    ``schedules`` may be None (schedule configuration broken): ``offhours``
    policies are then skipped while ``elapsed`` ones still run. ``idle_since``
    is the start of the current idle episode (None: unknown, ``idle`` policies
    are skipped); it should already be clamped to the frame's start.

    Catch-up rules (e.g. after the PC slept through several due handlers):

    - Of all due autostops, only the one with the earliest stop time runs.
    - A due toast is skipped when an autostop runs (its own notice replaces
      the warning), when a later toast of the same firing is also due, or
      when it is more than two poll intervals late.
    - Prompts always run; reviews are deduplicated per frame.
    """
    frame = _utc_frame(frame)
    now = _utc(now)
    idle_since = None if idle_since is None else _utc(idle_since)
    candidates: list[Action] = []
    for policy in policies:
        if policy.trigger == "offhours" and schedules is None:
            continue
        lead = max([-h.offset for h in policy.handlers] + [datetime.timedelta()])
        autostops = [h for h in policy.handlers if h.name == "autostop"]
        for onset, fire_at in firings(policy, frame, schedules, now + lead, idle_since):
            autostop_at = min((fire_at + h.offset for h in autostops), default=None)
            for handler in policy.handlers:
                due_at = fire_at + handler.offset
                key = event_key(frame, policy, handler, onset)
                if due_at > now or key in delivered:
                    continue
                candidates.append(
                    Action(
                        policy=policy,
                        handler=handler,
                        onset=onset,
                        fire_at=fire_at,
                        due_at=due_at,
                        key=key,
                        stop_at=_stop_time(policy, frame, onset, fire_at, now),
                        autostop_at=autostop_at,
                    )
                )

    autostops = [a for a in candidates if a.kind == "autostop"]
    winner = min(autostops, key=lambda a: (a.stop_at, a.due_at)) if autostops else None
    stale = 2 * poll_interval

    keep, skipped = [], []
    for action in candidates:
        if action.kind == "autostop":
            (keep if action is winner else skipped).append(action)
        elif action.kind == "toast":
            superseded = any(
                other.kind == "toast"
                and other.policy is action.policy
                and other.onset == action.onset
                and other.due_at > action.due_at
                for other in candidates
            )
            if winner is not None or superseded or now - action.due_at > stale:
                skipped.append(action)
            else:
                keep.append(action)
        else:
            keep.append(action)

    order = {"autostop": 0, "prompt": 1, "toast": 2}
    keep.sort(key=lambda a: (order[a.kind], a.due_at))
    return Plan(actions=keep, skipped=skipped)
