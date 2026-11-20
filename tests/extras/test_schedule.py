import datetime
import os

import pytest

from watson.extras.schedule import (
    ScheduleError,
    alternate_path,
    load_schedules,
    write_alternate,
)

from .conftest import at, make_schedules

MON = datetime.date(2018, 12, 3)


def test_default_schedule(watson):
    schedules = load_schedules(watson)
    assert schedules.standard.describe() == "mon tue wed thu fri 09:00-17:00"
    assert schedules.alternate is None


def test_configured_schedule(watson):
    watson.config.set("schedule", "workdays", "mon, wednesday sun")
    watson.config.set("schedule", "hours", "13:00-17:00 09:00-12:00")
    watson.config.set("schedule", "holidays", "2018-12-25")
    s = load_schedules(watson).standard
    assert s.describe() == "mon wed sun 09:00-12:00 13:00-17:00"
    assert not s.is_work_day(datetime.date(2018, 12, 25))  # Tuesday holiday anyway
    assert s.is_work_day(datetime.date(2018, 12, 26))  # Wednesday


@pytest.mark.parametrize(
    "key, value, message",
    [
        ("hours", "17:00-09:00", "ends before it starts"),
        ("hours", "09:00-12:00 11:00-13:00", "overlap"),
        ("hours", "9-17", "HH:MM"),
        ("hours", "09:00-25:00", "not a valid time"),
        ("workdays", "mon funday", "unknown day"),
        ("holidays", "12/25", "YYYY-MM-DD"),
    ],
)
def test_schedule_errors(watson, key, value, message):
    watson.config.set("schedule", key, value)
    with pytest.raises(ScheduleError, match=message):
        load_schedules(watson)


def test_hours_until_midnight():
    s = make_schedules(hours=("20:00-24:00",))
    assert s.is_work_time(at(2018, 12, 3, 23, 59))
    assert not s.is_work_time(at(2018, 12, 4, 0, 0))


def test_offhours_runs_across_lunch_and_night():
    s = make_schedules(hours=("09:00-12:00", "12:30-17:00"))
    runs = s.offhours_runs(at(2018, 12, 3, 11), at(2018, 12, 4, 10))
    assert runs == [
        (at(2018, 12, 3, 12), at(2018, 12, 3, 12, 30)),
        (at(2018, 12, 3, 17), at(2018, 12, 4, 9)),
    ]


def test_offhours_runs_over_weekend():
    s = make_schedules()
    runs = s.offhours_runs(at(2018, 12, 7, 16), at(2018, 12, 10, 12))
    assert runs == [(at(2018, 12, 7, 17), at(2018, 12, 10, 9))]


def write(watson, text):
    os.makedirs(watson.config_dir, exist_ok=True)
    with open(alternate_path(watson.config_dir), "w") as f:
        f.write(text)


def test_alternate_applies_inside_its_range_only(watson):
    watson.config.set("schedule", "hours", "09:00-17:00")
    write(
        watson,
        "[schedule]\nstart = 2018-12-03\nend = 2018-12-04\nhours = 07:00-15:00\n",
    )
    s = load_schedules(watson)
    assert s.for_date(datetime.date(2018, 12, 2)).source == "standard"
    assert s.for_date(MON).source == "alternate"
    assert s.for_date(datetime.date(2018, 12, 4)).source == "alternate"
    assert s.for_date(datetime.date(2018, 12, 5)).source == "standard"
    # Inherits workdays from the standard schedule, replaces hours
    assert s.is_work_time(at(2018, 12, 3, 7, 30))
    assert not s.is_work_time(at(2018, 12, 3, 16))


def test_alternate_empty_workdays_is_vacation(watson):
    write(watson, "[schedule]\nstart = 2018-12-03\nend = 2018-12-07\nworkdays =\n")
    s = load_schedules(watson)
    assert not s.is_work_time(at(2018, 12, 4, 11))
    assert s.is_work_time(at(2018, 12, 10, 11))


def test_alternate_end_before_start_is_ignored_with_warning(watson):
    write(watson, "[schedule]\nstart = 2018-12-07\nend = 2018-12-03\n")
    s = load_schedules(watson)
    assert s.alternate is None
    assert "before start" in s.warnings[0]


@pytest.mark.parametrize(
    "text, message",
    [
        ("[schedule]\nstart = 2018-12-03\n", "'end'"),
        ("[schedule]\nend = 2018-12-03\n", "'start'"),
        ("[schedule]\nstart = soon\nend = 2018-12-03\n", "YYYY-MM-DD"),
        ("[other]\nstart = 2018-12-03\n", r"\[schedule\]"),
        ("start = 2018-12-03\n", "can't be parsed"),
    ],
)
def test_alternate_errors(watson, text, message):
    write(watson, text)
    with pytest.raises(ScheduleError, match=message):
        load_schedules(watson)


def test_write_alternate_round_trips(watson):
    watson.config.set("schedule", "hours", "08:00-16:00")
    standard = load_schedules(watson).standard
    write_alternate(watson.config_dir, MON, datetime.date(2018, 12, 9), standard)
    s = load_schedules(watson)
    assert s.alternate.start == MON
    assert s.alternate.schedule.describe() == standard.describe()
