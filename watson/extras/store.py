"""``extras_state.json``: state shared by the watcher and the CLI.

It holds delivered policy events, pending reviews, the reminder snooze and
throttling timestamps. Every read-modify-write runs under ``StoreLock``, a
lock file created with ``O_CREAT | O_EXCL``. That works on Windows and on
WSL's ``/mnt/c`` (drvfs), where ``fcntl`` locks aren't shared with Windows
processes.
"""

from __future__ import annotations

import contextlib
import json
import os

from ..lock import FileLock as StoreLock
from ..lock import LockTimeout
from ..utils import safe_save

__all__ = ["LockTimeout", "Store", "StoreLock"]

STATE_FILENAME = "extras_state.json"
LOCK_FILENAME = "extras.lock"


def _empty_state() -> dict:
    return {
        "version": 1,
        "delivered": [],
        "reviews": [],
        "snooze_until": None,
        "last_reminder": None,
        "last_error_toast": None,
        "idle_since": None,
    }


class Store:
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.path = os.path.join(config_dir, STATE_FILENAME)
        self.lock = StoreLock(os.path.join(config_dir, LOCK_FILENAME))

    def read(self) -> dict:
        state = _empty_state()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return state
        except (OSError, ValueError):
            # A corrupt state file only loses throttling/delivery history;
            # don't let it break the CLI. Keep a copy for inspection.
            with contextlib.suppress(OSError):
                os.replace(self.path, self.path + ".corrupt")
            return state
        if isinstance(data, dict):
            state.update(data)
        return state

    def write(self, state: dict) -> None:
        os.makedirs(self.config_dir, exist_ok=True)
        safe_save(self.path, json.dumps(state, indent=1, ensure_ascii=False))

    @contextlib.contextmanager
    def transaction(self):
        """Lock, load, yield the state for changes, then save it."""
        with self.lock:
            state = self.read()
            yield state
            if not self.lock.is_held():
                raise LockTimeout(
                    f"{self.lock.path} was broken as stale while this update "
                    "ran; it was not saved"
                )
            self.write(state)
