"""OS idle-time query: how long since the last keyboard/mouse input.

The watcher is a stateless one-shot pass, so instead of tracking activity
itself it asks the OS each time. Only Windows is implemented. To add a
platform, write a ``() -> timedelta | None`` function and register it in
``get_idle_provider`` (macOS: ``ioreg -c IOHIDSystem`` ``HIDIdleTime``;
Linux: ``xprintidle`` or ``loginctl`` ``IdleSinceHint``).
"""

from __future__ import annotations

import datetime
import sys
from collections.abc import Callable

IdleProvider = Callable[[], "datetime.timedelta | None"]


def unsupported_idle() -> datetime.timedelta | None:
    """Placeholder for platforms without an implementation."""
    return None


def windows_idle() -> datetime.timedelta | None:
    """Time since the last input event in the current session (Win32)."""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    windll = ctypes.windll  # type: ignore[attr-defined]
    if not windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    # Both values are 32-bit millisecond tick counts that wrap every ~49 days.
    elapsed = (windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return datetime.timedelta(milliseconds=elapsed)


def get_idle_provider(platform: str | None = None) -> IdleProvider:
    platform = platform or sys.platform
    if platform == "win32":
        return windows_idle
    return unsupported_idle


def is_supported(platform: str | None = None) -> bool:
    return get_idle_provider(platform) is not unsupported_idle
