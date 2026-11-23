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
import uuid

from ..utils import safe_save

STATE_FILENAME = "extras_state.json"
LOCK_FILENAME = "extras.lock"


class LockTimeout(Exception):
    pass


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


class StoreLock:
    """A lock file, safe across processes, Windows and WSL.

    The file holds a token unique to this acquisition. A lock older than
    ``stale`` seconds is presumed abandoned by a crashed process and broken.
    Breaking happens under a short-lived second lock file (``<path>.break``)
    and re-checks the age there, so two waiters can't both break the same
    lock, nor break the fresh lock one of them has just taken. Release only
    removes the file if it still holds our token: a holder that was too slow
    and got its lock broken doesn't delete its successor's lock.
    """

    def __init__(self, path: str, stale: float = 30.0, timeout: float = 10.0):
        self.path = path
        self.stale = stale
        self.timeout = timeout
        self._held = 0
        self._token: str | None = None

    def _age(self, path: str) -> float | None:
        try:
            return time.time() - os.path.getmtime(path)
        except OSError:
            return None

    def _break_if_stale(self) -> None:
        breaker = self.path + ".break"
        try:
            fd = os.open(breaker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # Another process is breaking it, which takes milliseconds. A
            # breaker this old was left by a process that died mid-break.
            age = self._age(breaker)
            if age is not None and age > self.stale:
                with contextlib.suppress(OSError):
                    os.unlink(breaker)
            return
        except OSError:
            return
        os.close(fd)
        try:
            age = self._age(self.path)  # re-check: it may have been replaced
            if age is not None and age > self.stale:
                with contextlib.suppress(OSError):
                    os.unlink(self.path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(breaker)

    def acquire(self):
        if self._held:  # re-entrant within one process
            self._held += 1
            return
        token = f"{socket.gethostname()} {os.getpid()} {uuid.uuid4().hex}\n"
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = self._age(self.path)
                if age is None:
                    continue  # just released; retry right away
                if age > self.stale:
                    self._break_if_stale()
                    if self._age(self.path) is None:
                        continue
                if time.monotonic() > deadline:
                    raise LockTimeout(
                        f"{self.path} is held by another process; delete it "
                        "if no Watson process is running"
                    ) from None
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
            self._token = token
            self._held = 1
            return

    def is_held(self) -> bool:
        """True while the lock file is still ours (it wasn't broken as stale)."""
        return bool(self._held) and _read_text(self.path) == self._token

    def release(self):
        if not self._held:
            return
        self._held -= 1
        if not self._held:
            if _read_text(self.path) == self._token:
                with contextlib.suppress(OSError):
                    os.unlink(self.path)
            self._token = None

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
            if not self.lock.is_held():
                raise LockTimeout(
                    f"{self.lock.path} was broken as stale while this update "
                    "ran; it was not saved"
                )
            self.write(state)
