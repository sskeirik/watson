"""`watson extras doctor`: check the setup across Windows and WSL."""

from __future__ import annotations

import datetime
import os
import sys
import tempfile

from ..timezone import local_tz_info
from .notify import find_powershell, get_notifier, is_wsl, run_powershell
from .schedule import ScheduleError, load_schedules
from .settings import (
    SettingsError,
    format_duration,
    load_policies,
    notifier_name,
    reminder_settings,
)
from .store import Store

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _windows_utc_offset_minutes() -> int | None:
    result = run_powershell(
        "[int][System.TimeZoneInfo]::Local.GetUtcOffset([DateTime]::UtcNow).TotalMinutes"
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def checks(watson) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    config_dir = watson.config_dir

    # Data directory
    env = os.environ.get("WATSON_DIR")
    where = f"{config_dir}" + (" (from WATSON_DIR)" if env else " (default)")
    try:
        os.makedirs(config_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=config_dir):
            pass
        out.append((OK, f"data directory {where} is writable"))
    except OSError as e:
        out.append((FAIL, f"data directory {where} is not writable: {e}"))

    platform = (
        "Windows" if sys.platform == "win32" else ("WSL" if is_wsl() else sys.platform)
    )
    if platform == "WSL":
        if os.path.realpath(config_dir).startswith("/mnt/"):
            out.append((OK, "WSL: data directory is on the Windows disk (shared)"))
        else:
            out.append(
                (
                    WARN,
                    "WSL: data directory is inside the VM, so Windows can't see it; "
                    "set WATSON_DIR=/mnt/c/Users/<you>/AppData/Roaming/watson",
                )
            )

    # Time zone: the same UTC offset on both sides
    local_offset = datetime.datetime.now(local_tz_info()).utcoffset()
    local_minutes = int(local_offset.total_seconds() // 60)
    if find_powershell() and sys.platform != "win32":
        win_minutes = _windows_utc_offset_minutes()
        if win_minutes is None:
            out.append((WARN, "couldn't read Windows' time zone"))
        elif win_minutes != local_minutes:
            out.append(
                (
                    FAIL,
                    f"time zone mismatch: here UTC{local_minutes / 60:+g}, "
                    f"Windows UTC{win_minutes / 60:+g} (set TZ or fix /etc/localtime)",
                )
            )
        else:
            out.append((OK, f"time zone matches Windows (UTC{local_minutes / 60:+g})"))
    else:
        out.append((OK, f"local time zone UTC{local_minutes / 60:+g}"))

    # Notifier
    try:
        notifier = get_notifier(notifier_name(watson.config))
        level = WARN if notifier.name == "stdout" else OK
        out.append((level, f"notifier: {notifier.name}"))
    except ValueError as e:
        out.append((FAIL, f"notifier: {e}"))

    # Schedule
    try:
        schedules = load_schedules(watson)
        today = datetime.date.today()
        out.append((OK, f"schedule: {schedules.explain(today)}"))
        for warning in schedules.warnings:
            out.append((WARN, warning))
    except ScheduleError as e:
        out.append((FAIL, f"schedule: {e}"))

    # Reminder and policies
    try:
        reminder = reminder_settings(watson.config)
        state = "on" if reminder.enabled else "off"
        out.append(
            (
                OK,
                f"reminder: {state} (grace {format_duration(reminder.grace)}, "
                f"repeat {format_duration(reminder.repeat)})",
            )
        )
        policies = load_policies(watson.config)
        if policies:
            names = ", ".join(
                f"{p.name} ({p.trigger} {format_duration(p.after)})" for p in policies
            )
            out.append((OK, f"policies: {names}"))
        else:
            out.append((WARN, "policies: none configured ([policy:NAME] sections)"))
    except SettingsError as e:
        out.append((FAIL, str(e)))

    # Scheduled task
    if find_powershell():
        from .winsetup import task_status

        try:
            status = task_status()
            if status is None:
                out.append(
                    (
                        WARN,
                        "scheduled task not registered (`watson extras install-task` on Windows)",
                    )
                )
            else:
                out.append((OK, f"scheduled task: {status}"))
        except (OSError, RuntimeError) as e:
            out.append((WARN, f"scheduled task: couldn't query: {e}"))

    # Shared state
    store = Store(config_dir)
    reviews = store.read()["reviews"]
    if reviews:
        out.append((WARN, f"{len(reviews)} pending timer review(s): `watson review`"))
    if os.path.exists(store.lock.path):
        age = datetime.datetime.now().timestamp() - os.path.getmtime(store.lock.path)
        level = WARN if age > store.lock.stale else OK
        out.append((level, f"lock file present ({age:.0f}s old)"))
    return out
