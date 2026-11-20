import datetime

import pytest

from watson.extras.schedule import Schedule, Schedules
from watson.timezone import local_tz_info


@pytest.fixture(autouse=True)
def new_york(monkeypatch):
    """Deterministic local time zone (with DST) for every extras test."""
    monkeypatch.setenv("TZ", "America/New_York")


def at(*args):
    """Aware local datetime."""
    return datetime.datetime(*args, tzinfo=local_tz_info())


def hm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def make_schedules(
    hours=("09:00-17:00",), workdays=range(5), holidays=(), alternate=None
):
    ranges = tuple((hm(a), hm(b)) for a, b in (r.split("-") for r in hours))
    standard = Schedule(
        workdays=frozenset(workdays), hours=ranges, holidays=frozenset(holidays)
    )
    return Schedules(standard=standard, alternate=alternate)
