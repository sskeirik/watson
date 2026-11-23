"""Regression tests for DST-aware local time conversion."""

import datetime

import arrow

from watson import cli
from watson.frames import Frame
from watson.timezone import duration, humanize, local_tz_info

SUMMER = arrow.get("2018-07-10T16:00:00+00:00")  # EDT, UTC-4
WINTER = arrow.get("2018-01-10T17:00:00+00:00")  # EST, UTC-5


def test_local_tz_info_is_dst_aware(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    tzinfo = local_tz_info()
    assert SUMMER.to(tzinfo).utcoffset() == datetime.timedelta(hours=-4)
    assert WINTER.to(tzinfo).utcoffset() == datetime.timedelta(hours=-5)


def test_frame_uses_offset_of_its_own_date(monkeypatch):
    # arrow >= 1.4 turns 'local' into the *current* fixed offset; frames must
    # not depend on when they are displayed.
    monkeypatch.setenv("TZ", "America/New_York")
    summer = Frame(SUMMER, SUMMER.shift(hours=1), "p", "id1")
    winter = Frame(WINTER, WINTER.shift(hours=1), "p", "id2")
    assert summer.start.format("HH:mm") == "12:00"
    assert winter.start.format("HH:mm") == "12:00"


# New York falls back from 02:00 EDT to 01:00 EST on 2025-11-02, so the wall
# clock shows 00:00 -> 03:00 for 4 real hours.
NIGHT_START = arrow.get("2025-11-02T04:00:00+00:00")  # 00:00 EDT
NIGHT_STOP = arrow.get("2025-11-02T08:00:00+00:00")  # 03:00 EST


def _night(monkeypatch, watson):
    monkeypatch.setenv("TZ", "America/New_York")
    watson.add("night", NIGHT_START, NIGHT_STOP, ["shift"])
    watson.save()


def test_duration_is_real_time_across_dst(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    start, stop = NIGHT_START.to(local_tz_info()), NIGHT_STOP.to(local_tz_info())
    assert (stop - start).total_seconds() == 3 * 3600  # wall clock: the bug
    assert duration(start, stop) == datetime.timedelta(hours=4)


def test_humanize_is_real_time_across_dst(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    start = NIGHT_START.to(local_tz_info())
    later = NIGHT_START.shift(hours=4).to(local_tz_info())
    assert humanize(start, later) == "4 hours ago"


def test_report_totals_are_real_time_across_dst(monkeypatch, watson):
    _night(monkeypatch, watson)
    report = watson.report(NIGHT_START.shift(days=-1), NIGHT_STOP.shift(days=1))
    assert report["time"] == 4 * 3600
    (project,) = report["projects"]
    assert project["time"] == 4 * 3600
    assert project["tags"] == [{"name": "shift", "time": 4 * 3600}]


def test_log_durations_are_real_time_across_dst(monkeypatch, watson, runner):
    _night(monkeypatch, watson)
    result = runner.invoke(
        cli.log, ["-f", "2025-11-01", "-t", "2025-11-03", "-G"], obj=watson
    )
    assert result.exit_code == 0, result.output
    assert "(4h 00m 00s)" in result.output  # daily total
    assert "00:00 to 03:00   4h 00m 00s  night" in result.output
