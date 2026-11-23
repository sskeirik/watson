import os
import time

import pytest

from watson.extras.store import LockTimeout, Store, StoreLock


def test_transaction_round_trip(config_dir):
    store = Store(config_dir)
    assert store.read()["reviews"] == []
    with store.transaction() as state:
        state["snooze_until"] = 123
    assert store.read()["snooze_until"] == 123
    assert not os.path.exists(store.lock.path)


def test_transaction_does_not_save_on_error(config_dir):
    store = Store(config_dir)
    with pytest.raises(RuntimeError), store.transaction() as state:
        state["snooze_until"] = 1
        raise RuntimeError
    assert store.read()["snooze_until"] is None
    assert not os.path.exists(store.lock.path)


def test_corrupt_state_is_set_aside(config_dir):
    store = Store(config_dir)
    with open(store.path, "w") as f:
        f.write("{not json")
    assert store.read()["reviews"] == []
    assert os.path.exists(store.path + ".corrupt")


def test_lock_times_out_while_held(config_dir):
    path = os.path.join(config_dir, "lock")
    held = StoreLock(path)
    held.acquire()
    with pytest.raises(LockTimeout):
        StoreLock(path, timeout=0.2).acquire()
    held.release()
    StoreLock(path, timeout=0.2).acquire()


def test_stale_lock_is_broken(config_dir):
    path = os.path.join(config_dir, "lock")
    with open(path, "w") as f:
        f.write("ghost 1\n")
    old = time.time() - 120
    os.utime(path, (old, old))
    lock = StoreLock(path, stale=30, timeout=0.2)
    lock.acquire()
    lock.release()
    assert not os.path.exists(path)


def _age(path, seconds=120):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_slow_holder_does_not_delete_its_successors_lock(config_dir):
    path = os.path.join(config_dir, "lock")
    slow = StoreLock(path, stale=30)
    slow.acquire()
    _age(path)  # `slow` overran the stale timeout...
    successor = StoreLock(path, stale=30, timeout=0.2)
    successor.acquire()  # ...so its lock is broken
    assert not slow.is_held()
    slow.release()
    assert os.path.exists(path)
    assert successor.is_held()
    successor.release()
    assert not os.path.exists(path)


def test_break_spares_a_lock_that_is_no_longer_stale(config_dir):
    # A waiter saw a stale lock, but another waiter broke it and took a fresh
    # one before this waiter got to break it.
    path = os.path.join(config_dir, "lock")
    fresh = StoreLock(path, stale=30)
    fresh.acquire()
    StoreLock(path, stale=30)._break_if_stale()
    assert fresh.is_held()
    fresh.release()


def test_break_waits_for_a_concurrent_breaker(config_dir):
    path = os.path.join(config_dir, "lock")
    with open(path, "w") as f:
        f.write("ghost 1 x\n")
    _age(path)
    with open(path + ".break", "w"):
        pass  # someone else is breaking it right now
    StoreLock(path, stale=30)._break_if_stale()
    assert os.path.exists(path)


def test_abandoned_breaker_is_cleaned_up(config_dir):
    path = os.path.join(config_dir, "lock")
    with open(path, "w") as f:
        f.write("ghost 1 x\n")
    _age(path)
    with open(path + ".break", "w"):
        pass
    _age(path + ".break")
    lock = StoreLock(path, stale=30, timeout=1)
    lock.acquire()
    assert lock.is_held()
    assert not os.path.exists(path + ".break")
    lock.release()


def test_transaction_is_not_saved_if_its_lock_was_broken(config_dir):
    store = Store(config_dir)
    with pytest.raises(LockTimeout), store.transaction() as state:
        state["snooze_until"] = 1
        _age(store.lock.path)
        StoreLock(store.lock.path, timeout=0.2).acquire()  # breaks ours
    assert store.read()["snooze_until"] is None


def test_lock_is_reentrant(config_dir):
    lock = StoreLock(os.path.join(config_dir, "lock"))
    with lock, lock:
        assert os.path.exists(lock.path)
    assert not os.path.exists(lock.path)
