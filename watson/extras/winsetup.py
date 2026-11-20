"""Register the watcher with Windows Task Scheduler.

The task runs ``watson-watch --once`` every few minutes and at logon, only
while the user is logged on (toasts need the interactive session). With
``StartWhenAvailable``, a run missed during sleep happens on wake.
"""

from __future__ import annotations

import os
import shutil
import sys

from .notify import find_powershell, is_wsl, run_powershell

TASK_NAME = "Watson Watch"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def watch_command() -> tuple[str, str]:
    """(executable, arguments) that run one watcher pass without a console."""
    scripts_dir = os.path.dirname(sys.executable)
    candidates = [
        os.path.join(scripts_dir, "watson-watch.exe"),
        os.path.join(scripts_dir, "Scripts", "watson-watch.exe"),
        shutil.which("watson-watch") or "",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path, "--once"
    pythonw = os.path.join(scripts_dir, "pythonw.exe")
    if os.path.exists(pythonw):
        return pythonw, "-m watson.extras.watch --once"
    raise RuntimeError(
        "can't find watson-watch.exe or pythonw.exe; is Watson installed on "
        "the Windows side (e.g. `uv tool install`)?"
    )


def require_windows():
    if sys.platform != "win32":
        where = "WSL" if is_wsl() else sys.platform
        raise RuntimeError(
            f"run this from Windows, not {where}: the task must run Windows' "
            "own Watson so it works while WSL is shut down"
        )


def install_task(interval_minutes: int = 5) -> str:
    require_windows()
    exe, args = watch_command()
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps_quote(exe)} -Argument {_ps_quote(args)}
$every = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)})
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Action $action `
    -Trigger $every, $logon -Settings $settings -Force `
    -Description 'Watson: work-hours reminders and forgotten-timer policies' | Out-Null
"""
    result = run_powershell(script, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return f"Registered '{TASK_NAME}': {exe} {args}, every {interval_minutes} min and at logon."


def uninstall_task() -> str:
    require_windows()
    script = f"""
$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -Confirm:$false
"""
    result = run_powershell(script, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return f"Removed '{TASK_NAME}'."


def task_status() -> str | None:
    """One line about the task, or None if it isn't registered.

    Works from Windows and from WSL (through powershell.exe).
    """
    if find_powershell() is None:
        raise RuntimeError("powershell.exe not found")
    script = f"""
$t = Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} -ErrorAction SilentlyContinue
if ($null -eq $t) {{ exit 3 }}
$i = $t | Get-ScheduledTaskInfo
'{{0}}; last run {{1}} (result {{2}}); next run {{3}}' -f $t.State, $i.LastRunTime, $i.LastTaskResult, $i.NextRunTime
"""
    result = run_powershell(script)
    if result.returncode == 3:
        return None
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()
