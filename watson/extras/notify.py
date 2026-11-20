"""Desktop notifications (toasts).

``powershell`` shows a native Windows toast through the WinRT
``ToastNotificationManager``, using PowerShell's own registered app id, so
no module or app registration is needed. It works from Windows and from WSL
(``powershell.exe`` through interop).
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

import click

log = logging.getLogger(__name__)

TITLE = "Watson"
# PowerShell's AppUserModelID; registered on every Windows 10/11 install
POWERSHELL_APP_ID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)
CREATE_NO_WINDOW = 0x08000000

_TOAST_SCRIPT = """\
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{xml}')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)
"""


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def find_powershell() -> str | None:
    if sys.platform == "win32":
        return shutil.which("powershell") or shutil.which("powershell.exe")
    if is_wsl():
        found = shutil.which("powershell.exe")
        if found:
            return found
        default = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        return default if os.path.exists(default) else None
    return None


def encode_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def run_powershell(script: str, timeout: float = 30) -> subprocess.CompletedProcess:
    exe = find_powershell()
    if exe is None:
        raise RuntimeError("powershell.exe not found")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encode_powershell(script),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        **kwargs,
    )


def toast_xml(title: str, body: str) -> str:
    return (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        "</binding></visual></toast>"
    )


class Notifier:
    name = "base"

    def notify(self, body: str, title: str = TITLE) -> bool:
        raise NotImplementedError


class PowerShellNotifier(Notifier):
    name = "powershell"

    def notify(self, body, title=TITLE):
        xml = toast_xml(title, body).replace("'", "''")
        script = _TOAST_SCRIPT.replace("{xml}", xml).replace(
            "{app_id}", POWERSHELL_APP_ID
        )
        try:
            result = run_powershell(script)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            log.error("toast failed: %s", e)
            return False
        if result.returncode != 0:
            log.error("toast failed: %s", (result.stderr or result.stdout).strip())
            return False
        return True


class NotifySendNotifier(Notifier):
    name = "notify-send"

    def notify(self, body, title=TITLE):
        try:
            subprocess.run(["notify-send", title, body], check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            log.error("notify-send failed: %s", e)
            return False
        return True


class StdoutNotifier(Notifier):
    name = "stdout"

    def __init__(self, echo=None):
        self.echo = echo or click.echo
        self.sent: list[tuple[str, str]] = []

    def notify(self, body, title=TITLE):
        self.sent.append((title, body))
        self.echo(f"[toast] {title}: {body}")
        return True


def get_notifier(name: str = "auto") -> Notifier:
    if name == "powershell":
        return PowerShellNotifier()
    if name == "notify-send":
        return NotifySendNotifier()
    if name == "stdout":
        return StdoutNotifier()
    if name != "auto":
        raise ValueError(
            f"unknown notifier '{name}' (expected auto, powershell, notify-send, stdout)"
        )
    if find_powershell():
        return PowerShellNotifier()
    if shutil.which("notify-send"):
        return NotifySendNotifier()
    return StdoutNotifier()
