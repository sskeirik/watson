"""One evaluation pass of the reminder and the forgotten-timer policies.

Meant to be run every few minutes by the OS scheduler (``watson extras
install-task`` on Windows). ``main`` is the ``watson-watch`` gui-script
entry point: on Windows it runs without a console window.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import logging.handlers
import os
import sys
import time

import arrow
import click

from ..timezone import local_tz_info
from ..utils import create_watson
from ..watson import Watson
from . import handlers
from .notify import get_notifier
from .policies import RunningFrame, plan
from .schedule import ScheduleError, load_schedules
from .settings import (
    SettingsError,
    load_policies,
    notifier_name,
    poll_interval,
    reminder_settings,
)
from .store import LockTimeout, Store

log = logging.getLogger("watson.extras")

LOG_FILENAME = "extras.log"
ERROR_TOAST_EVERY = datetime.timedelta(hours=1)


def _ts(moment) -> int:
    return int(moment.timestamp())


def setup_file_logging(config_dir: str):
    """Log to ``<WATSON_DIR>/extras.log`` (the watcher has no console)."""
    if any(getattr(h, "_watson_extras", False) for h in log.handlers):
        return
    os.makedirs(config_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(config_dir, LOG_FILENAME),
        maxBytes=256 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    handler._watson_extras = True  # type: ignore[attr-defined]
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(process)d %(levelname)s %(message)s")
    )
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _last_stop(watson: Watson):
    stops = watson.frames["stop"]
    return max(stops).datetime if stops else None


def _reminder_due(watson, schedules, settings, state, now) -> bool:
    if not settings.enabled or schedules is None or watson.is_started:
        return False
    interval = schedules.current_work_interval(now)
    if interval is None or now - interval[0] < settings.grace:
        return False
    if state.get("snooze_until") and _ts(now) < state["snooze_until"]:
        return False
    last_stop = _last_stop(watson)
    if last_stop is not None and now - last_stop < settings.grace:
        return False
    last = state.get("last_reminder")
    return not (last and _ts(now) - last < settings.repeat.total_seconds())


def run_once(
    config_dir: str | None = None,
    now: datetime.datetime | None = None,
    dry_run: bool = False,
    notifier=None,
) -> list[str]:
    """Evaluate everything once. Returns a list of human-readable lines."""
    now = now or datetime.datetime.now(local_tz_info())
    watson = Watson(config_dir=config_dir) if config_dir else create_watson()
    store = Store(watson.config_dir)
    lines: list[str] = []
    toasts: list[str] = []
    errors: list[str] = []

    config = watson.config
    if notifier is None:
        try:
            notifier = get_notifier(notifier_name(config))
        except ValueError as e:
            errors.append(f"[extras] notifier: {e}")
            notifier = get_notifier("auto")
    try:
        policies = load_policies(config)
        interval = poll_interval(config)
        reminder = reminder_settings(config)
    except SettingsError as e:
        errors.append(f"Config error: {e}")
        policies, interval, reminder = [], datetime.timedelta(minutes=5), None
    try:
        schedules = load_schedules(watson)
        for warning in schedules.warnings:
            log.warning(warning)
    except ScheduleError as e:
        errors.append(f"Schedule error: {e}")
        schedules = None

    txn = contextlib.nullcontext(store.read()) if dry_run else store.transaction()
    with txn as state:
        if errors:
            for error in errors:
                log.error(error)
                lines.append(error)
            last = state.get("last_error_toast")
            if not last or _ts(now) - last >= ERROR_TOAST_EVERY.total_seconds():
                toasts.append(errors[0] + " (see `watson extras doctor`)")
                state["last_error_toast"] = _ts(now)

        delivered = set(state.get("delivered") or [])
        if watson.is_started:
            current = watson.current
            frame = RunningFrame(
                project=current["project"],
                start=current["start"].datetime,
                tags=tuple(current["tags"]),
            )
            result = plan(frame, policies, schedules, now, delivered, interval)
            if dry_run:
                for action in result.actions:
                    lines.append("would " + handlers.describe(action, frame, now))
                    if action.kind == "toast":
                        toasts.append(handlers.toast_text(action, frame, now))
                for action in result.skipped:
                    lines.append("would skip " + handlers.describe(action, frame, now))
            else:
                outcome = handlers.execute(
                    result.actions, frame, state, watson.config_dir, now
                )
                lines.extend(outcome.lines)
                toasts.extend(outcome.toasts)
                delivered |= {a.key for a in result.actions + result.skipped}
            # Only the running frame's events matter; forget older frames'.
            delivered = {k for k in delivered if k.startswith(frame.key + ":")}
        else:
            delivered = set()
            if reminder is not None and _reminder_due(
                watson, schedules, reminder, state, now
            ):
                toasts.append(
                    "No timer is running. Start one with `watson start <project>`."
                )
                lines.append("reminder: no timer running during work hours")
                state["last_reminder"] = _ts(now)
        state["delivered"] = sorted(delivered)

    for text in toasts:
        log.info("toast: %s", text)
        if not dry_run or notifier.name == "stdout":
            notifier.notify(text)
        else:
            lines.append(f"would toast: {text}")
    for line in lines:
        log.info(line)
    return lines


def watch_loop(config_dir, interval_seconds: float, dry_run: bool, echo=click.echo):
    while True:
        try:
            for line in run_once(config_dir=config_dir, dry_run=dry_run):
                echo(line)
        except LockTimeout as e:
            log.warning("skipped a pass: %s", e)
        except Exception:  # keep a long-running watcher alive
            log.exception("watch pass failed")
        time.sleep(interval_seconds)


@click.command(name="watson-watch")
@click.option(
    "--once/--loop", default=True, help="Run one pass (default) or keep running."
)
@click.option(
    "--interval",
    default=None,
    help="With --loop: time between passes, e.g. 1m (default: [extras] poll_interval).",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen; change nothing.")
def main(once, interval, dry_run):
    """Check the reminder and forgotten-timer policies (for Task Scheduler)."""
    if sys.stdout is None:  # pythonw / gui-script: no console
        sys.stdout = open(os.devnull, "w")  # closed at exit
        sys.stderr = sys.stdout
    watson = create_watson()
    setup_file_logging(watson.config_dir)
    try:
        if once:
            for line in run_once(config_dir=watson.config_dir, dry_run=dry_run):
                click.echo(line)
        else:
            from .settings import parse_duration

            seconds = (
                parse_duration(interval) if interval else poll_interval(watson.config)
            ).total_seconds()
            watch_loop(watson.config_dir, seconds, dry_run)
    except LockTimeout as e:
        log.warning("skipped: %s", e)
    except Exception:
        log.exception("watson-watch failed")
        raise


def snooze_until(value: str, now: datetime.datetime | None = None) -> int | None:
    """Parse a `watson snooze` argument into a timestamp (None = off)."""
    from .settings import parse_duration

    now = now or datetime.datetime.now(local_tz_info())
    text = value.strip().lower()
    if text in ("off", "0", "none"):
        return None
    if text == "today":
        tomorrow = arrow.get(now).floor("day").shift(days=1)
        return _ts(tomorrow)
    return _ts(now + parse_duration(text))


if __name__ == "__main__":
    main()
