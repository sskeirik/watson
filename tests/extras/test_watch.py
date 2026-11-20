import datetime

import arrow

from watson import Watson
from watson.extras.notify import StdoutNotifier
from watson.extras.store import Store
from watson.extras.watch import run_once, snooze_until
from watson.timezone import local_tz_info

from .conftest import at

td = datetime.timedelta


def configure(watson, **values):
    for key, value in values.items():
        section, option = key.split("__")
        watson.config.set(section.replace("_", ":"), option, value)
    watson.config = watson.config  # mark the config as changed so save() writes it
    watson.save()


def notifier():
    return StdoutNotifier(echo=lambda text: None)


def now_local():
    return datetime.datetime.now(local_tz_info())


def test_autostop_and_review(watson):
    configure(
        watson,
        reminder__enabled="false",
        policy_test__trigger="elapsed",
        policy_test__after="1h",
        policy_test__handlers="toast@-10m autostop prompt",
    )
    watson.start("forgot", ["x"], start_at=arrow.now().shift(hours=-2))
    watson.save()

    n = notifier()
    lines = run_once(config_dir=watson.config_dir, notifier=n)
    assert any("stop it at" in line for line in lines)
    assert len(n.sent) == 1 and "Stopped 'forgot'" in n.sent[0][1]

    fresh = Watson(config_dir=watson.config_dir)
    assert not fresh.is_started
    frame = fresh.frames[-1]
    assert frame.project == "forgot"
    assert frame.tags == ["x", "auto-stopped"]
    assert round((frame.stop - frame.start).total_seconds()) == 3600

    (review,) = Store(watson.config_dir).read()["reviews"]
    assert review["frame_id"] == frame.id and review["autostopped"]

    # Nothing left to do on the next pass
    n2 = notifier()
    assert run_once(config_dir=watson.config_dir, notifier=n2) == []
    assert n2.sent == []


def test_dry_run_changes_nothing(watson):
    configure(
        watson,
        policy_test__trigger="elapsed",
        policy_test__after="1h",
        policy_test__handlers="autostop prompt",
    )
    watson.start("forgot", start_at=arrow.now().shift(hours=-2))
    watson.save()

    lines = run_once(config_dir=watson.config_dir, dry_run=True, notifier=notifier())
    assert any(line.startswith("would policy 'test': stop it") for line in lines)
    assert Watson(config_dir=watson.config_dir).is_started
    assert Store(watson.config_dir).read()["reviews"] == []


def test_autostop_skips_a_frame_changed_since_planning(watson, mocker):
    configure(
        watson,
        policy_test__trigger="elapsed",
        policy_test__after="1h",
        policy_test__handlers="autostop",
    )
    watson.start("old", start_at=arrow.now().shift(hours=-2))
    watson.save()

    # Between planning and the autostop, the user restarts on another project
    from watson.extras import handlers

    real = handlers.autostop

    def user_switches_first(config_dir, action, frame):
        w = Watson(config_dir=config_dir)
        w.stop()
        w.start("new")
        w.save()
        return real(config_dir, action, frame)

    mocker.patch.object(handlers, "autostop", side_effect=user_switches_first)
    run_once(config_dir=watson.config_dir, notifier=notifier())
    fresh = Watson(config_dir=watson.config_dir)
    assert fresh.current["project"] == "new"
    assert "auto-stopped" not in fresh.frames[-1].tags


def test_reminder_during_work_hours(watson):
    configure(
        watson,
        schedule__workdays="mon tue wed thu fri sat sun",
        schedule__hours="09:00-17:00",
    )
    noon = at(2018, 12, 3, 12)

    n = notifier()
    run_once(config_dir=watson.config_dir, now=noon, notifier=n)
    assert len(n.sent) == 1 and "No timer is running" in n.sent[0][1]

    # Throttled by `repeat` (30m)
    n = notifier()
    run_once(config_dir=watson.config_dir, now=noon + td(minutes=20), notifier=n)
    assert n.sent == []
    run_once(config_dir=watson.config_dir, now=noon + td(minutes=31), notifier=n)
    assert len(n.sent) == 1


def test_reminder_respects_grace_off_hours_and_snooze(watson):
    configure(
        watson,
        schedule__workdays="mon tue wed thu fri sat sun",
        schedule__hours="09:00-17:00",
    )
    store = Store(watson.config_dir)

    n = notifier()
    run_once(config_dir=watson.config_dir, now=at(2018, 12, 3, 9, 5), notifier=n)
    run_once(config_dir=watson.config_dir, now=at(2018, 12, 3, 18), notifier=n)
    assert n.sent == []  # within the start-of-day grace; off hours

    with store.transaction() as state:
        state["snooze_until"] = snooze_until("2h", now=at(2018, 12, 3, 12))
    run_once(config_dir=watson.config_dir, now=at(2018, 12, 3, 13), notifier=n)
    assert n.sent == []
    run_once(config_dir=watson.config_dir, now=at(2018, 12, 3, 14, 1), notifier=n)
    assert len(n.sent) == 1


def test_reminder_grace_after_last_stop(watson):
    configure(
        watson,
        schedule__workdays="mon tue wed thu fri sat sun",
        schedule__hours="00:00-24:00",
    )
    now = now_local()
    watson.frames.add(
        "p", arrow.get(now).shift(hours=-1), arrow.get(now).shift(minutes=-5)
    )
    watson.save()
    n = notifier()
    run_once(config_dir=watson.config_dir, now=now, notifier=n)
    assert n.sent == []


def test_bad_schedule_toasts_hourly_but_elapsed_policies_run(watson):
    configure(
        watson,
        schedule__hours="17:00-09:00",
        policy_test__trigger="elapsed",
        policy_test__after="1h",
        policy_test__handlers="autostop",
    )
    watson.start("forgot", start_at=arrow.now().shift(hours=-2))
    watson.save()
    n = notifier()
    lines = run_once(config_dir=watson.config_dir, notifier=n)
    assert any("Schedule error" in line for line in lines)
    assert any("Schedule error" in body for _, body in n.sent)
    assert not Watson(config_dir=watson.config_dir).is_started

    n = notifier()
    run_once(config_dir=watson.config_dir, notifier=n)
    assert n.sent == []  # error toast throttled


def test_snooze_until():
    noon = at(2018, 12, 3, 12)
    assert snooze_until("90m", now=noon) == int((noon + td(minutes=90)).timestamp())
    assert snooze_until("today", now=noon) == int(at(2018, 12, 4).timestamp())
    assert snooze_until("off", now=noon) is None
