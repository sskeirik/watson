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


def test_lock_is_reentrant(config_dir):
    lock = StoreLock(os.path.join(config_dir, "lock"))
    with lock, lock:
        assert os.path.exists(lock.path)
    assert not os.path.exists(lock.path)
