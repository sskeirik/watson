"""A cross-process lock file that works on Windows and WSL's ``/mnt/c``.

It's a file created with ``O_CREAT | O_EXCL``: ``fcntl`` locks on drvfs
aren't shared with Windows processes, and ``msvcrt`` locks don't exist on
Linux, but exclusive file creation works on both sides.
"""

from __future__ import annotations

import contextlib
import os
import socket
import time
import uuid


class LockTimeout(Exception):
    pass


def _read_text(path: str) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        return os.read(fd, 4096).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


class FileLock:
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
