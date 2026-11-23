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
import socket
import time

from ..utils import safe_save

STATE_FILENAME = "extras_state.json"
LOCK_FILENAME = "extras.lock"


class LockTimeout(Exception):
    pass


class StoreLock:
    def __init__(self, path: str, stale: float = 30.0, timeout: float = 10.0):
        self.path = path
        self.stale = stale
        self.timeout = timeout
        self._held = 0

    def acquire(self):
        if self._held:  # re-entrant within one process
            self._held += 1
            return
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    continue  # just released; retry right away
                if age > self.stale:
                    with contextlib.suppress(OSError):
                        os.unlink(self.path)
                    continue
                if time.monotonic() > deadline:
                    raise LockTimeout(
                        f"{self.path} is held by another process; delete it "
                        "if no Watson process is running"
                    ) from None
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w") as f:
                f.write(f"{socket.gethostname()} {os.getpid()}\n")
            self._held = 1
            return

    def release(self):
        if not self._held:
            return
        self._held -= 1
        if not self._held:
            with contextlib.suppress(OSError):
                os.unlink(self.path)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


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
            self.write(state)
