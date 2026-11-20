"""Regression tests for DST-aware local time conversion."""

import datetime

import arrow

from watson.frames import Frame
from watson.timezone import local_tz_info

SUMMER = arrow.get('2018-07-10T16:00:00+00:00')  # EDT, UTC-4
WINTER = arrow.get('2018-01-10T17:00:00+00:00')  # EST, UTC-5


def test_local_tz_info_is_dst_aware(monkeypatch):
    monkeypatch.setenv('TZ', 'America/New_York')
    tzinfo = local_tz_info()
    assert SUMMER.to(tzinfo).utcoffset() == datetime.timedelta(hours=-4)
    assert WINTER.to(tzinfo).utcoffset() == datetime.timedelta(hours=-5)


def test_frame_uses_offset_of_its_own_date(monkeypatch):
    # arrow >= 1.4 turns 'local' into the *current* fixed offset; frames must
    # not depend on when they are displayed.
    monkeypatch.setenv('TZ', 'America/New_York')
    summer = Frame(SUMMER, SUMMER.shift(hours=1), 'p', 'id1')
    winter = Frame(WINTER, WINTER.shift(hours=1), 'p', 'id2')
    assert summer.start.format('HH:mm') == '12:00'
    assert winter.start.format('HH:mm') == '12:00'
