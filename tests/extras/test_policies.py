import datetime

from watson.extras.policies import RunningFrame, plan
from watson.extras.schedule import Alternate, Schedule
from watson.extras.settings import Policy, parse_handlers

from .conftest import at, hm, make_schedules

td = datetime.timedelta
POLL = td(minutes=5)


def policy(name, trigger, after, handlers, stop_at=None):
    return Policy(
        name=name,
        trigger=trigger,
        after=after,
        stop_at=stop_at or ("onset" if trigger == "offhours" else "fire"),
        handlers=parse_handlers(name, handlers),
    )


def kinds(result):
    return [(a.policy.name, a.kind) for a in result.actions]


AFTER_HOURS = policy(
    "after-hours", "offhours", td(hours=1), "toast@-15m toast autostop prompt"
)
LONG_TASK = policy("long-task", "elapsed", td(hours=10), "toast@-30m autostop prompt")


def run(frame, policies, schedules, now, delivered=None):
    return plan(frame, policies, schedules, now, set(delivered or ()), POLL)


def test_elapsed_timeline():
    frame = RunningFrame("p", at(2018, 12, 3, 8))
    s = make_schedules()
    assert run(frame, [LONG_TASK], s, at(2018, 12, 3, 17, 29)).actions == []

    warn = run(frame, [LONG_TASK], s, at(2018, 12, 3, 17, 30))
    assert kinds(warn) == [("long-task", "toast")]
    assert warn.actions[0].autostop_at == at(2018, 12, 3, 18)

    done = run(
        frame, [LONG_TASK], s, at(2018, 12, 3, 18), {a.key for a in warn.actions}
    )
    assert kinds(done) == [("long-task", "autostop"), ("long-task", "prompt")]
    assert done.actions[0].stop_at == at(2018, 12, 3, 18)


def test_offhours_starting_mid_frame_stops_at_onset():
    frame = RunningFrame("p", at(2018, 12, 3, 15))
    s = make_schedules()
    assert run(frame, [AFTER_HOURS], s, at(2018, 12, 3, 17, 44)).actions == []

    warn = run(frame, [AFTER_HOURS], s, at(2018, 12, 3, 17, 45))
    assert kinds(warn) == [("after-hours", "toast")]

    done = run(
        frame, [AFTER_HOURS], s, at(2018, 12, 3, 18), {a.key for a in warn.actions}
    )
    # The 18:00 toast is replaced by the autostop's own notice
    assert kinds(done) == [("after-hours", "autostop"), ("after-hours", "prompt")]
    assert [a.handler.index for a in done.skipped] == [1]
    assert done.actions[0].stop_at == at(2018, 12, 3, 17)


def test_offhours_resets_when_work_hours_resume():
    frame = RunningFrame("p", at(2018, 12, 3, 11))
    s = make_schedules(hours=("09:00-12:00", "12:30-17:00"))
    # The 30 minute lunch break never reaches the 1h threshold
    assert run(frame, [AFTER_HOURS], s, at(2018, 12, 3, 16)).actions == []


def test_frame_started_off_hours_stops_at_fire_time():
    # Started on a Saturday: onset == frame start, so stopping at the onset
    # would erase the frame; stop at the fire time instead.
    frame = RunningFrame("p", at(2018, 12, 8, 10))
    p = policy("late", "offhours", td(hours=3), "autostop")
    result = run(frame, [p], make_schedules(), at(2018, 12, 8, 13, 1))
    assert result.actions[0].stop_at == at(2018, 12, 8, 13)


def test_weekend_is_one_run_and_old_toasts_go_stale():
    frame = RunningFrame("p", at(2018, 12, 7, 16))
    p = policy("late", "offhours", td(hours=2), "toast")
    s = make_schedules()
    assert kinds(run(frame, [p], s, at(2018, 12, 7, 19, 2))) == [("late", "toast")]
    # Checked again only on Monday: the Friday-night toast is stale
    monday = run(frame, [p], s, at(2018, 12, 10, 10))
    assert monday.actions == []
    assert len(monday.skipped) == 1


def test_frame_crossing_alternate_end_uses_each_days_schedule():
    alt = Schedule(
        workdays=frozenset(range(5)),
        hours=((hm("06:00"), hm("14:00")),),
        holidays=frozenset(),
        source="alternate",
    )
    s = make_schedules(
        alternate=Alternate(
            start=datetime.date(2018, 12, 3),
            end=datetime.date(2018, 12, 3),
            schedule=alt,
            path="alt.ini",
        )
    )
    frame = RunningFrame("p", at(2018, 12, 3, 13))
    p = policy("night", "offhours", td(hours=18), "autostop")
    # Off-hours from Mon 14:00 (alternate) to Tue 09:00 (standard) = 19h
    result = run(frame, [p], s, at(2018, 12, 4, 9))
    assert result.actions[0].onset == at(2018, 12, 3, 14)
    assert result.actions[0].fire_at == at(2018, 12, 4, 8)


def test_catch_up_after_sleeping_overnight():
    frame = RunningFrame("p", at(2018, 12, 3, 9))
    s = make_schedules()
    result = run(frame, [AFTER_HOURS, LONG_TASK], s, at(2018, 12, 4, 7))
    # Only the earliest autostop runs; every toast is skipped; prompts stay
    assert kinds(result) == [
        ("after-hours", "autostop"),
        ("after-hours", "prompt"),
        ("long-task", "prompt"),
    ]
    assert result.actions[0].stop_at == at(2018, 12, 3, 17)
    skipped = sorted((a.policy.name, a.kind) for a in result.skipped)
    assert skipped == [
        ("after-hours", "toast"),
        ("after-hours", "toast"),
        ("long-task", "autostop"),
        ("long-task", "toast"),
    ]


def test_exactly_once():
    frame = RunningFrame("p", at(2018, 12, 3, 9))
    s = make_schedules()
    now = at(2018, 12, 4, 7)
    first = run(frame, [AFTER_HOURS, LONG_TASK], s, now)
    delivered = {a.key for a in first.actions + first.skipped}
    again = run(frame, [AFTER_HOURS, LONG_TASK], s, now + td(minutes=5), delivered)
    assert again.actions == [] and again.skipped == []


def test_broken_schedule_skips_offhours_only():
    frame = RunningFrame("p", at(2018, 12, 3, 8))
    result = run(frame, [AFTER_HOURS, LONG_TASK], None, at(2018, 12, 3, 18))
    assert {a.policy.name for a in result.actions} == {"long-task"}


def test_early_autostop_never_stops_in_the_future():
    frame = RunningFrame("p", at(2018, 12, 3, 8))
    p = policy("early", "elapsed", td(hours=2), "autostop@-10m")
    now = at(2018, 12, 3, 9, 55)
    result = run(frame, [p], make_schedules(), now)
    assert result.actions[0].stop_at == now


def test_offhours_warning_ahead_of_fire_time():
    # The warning toast at 17:45 is found before the policy fires at 18:00
    frame = RunningFrame("p", at(2018, 12, 3, 15))
    result = run(frame, [AFTER_HOURS], make_schedules(), at(2018, 12, 3, 17, 50))
    assert [a.due_at for a in result.actions] == [at(2018, 12, 3, 17, 45)]
