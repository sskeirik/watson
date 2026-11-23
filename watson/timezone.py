"""Local time zone handling.

arrow >= 1.4 parses the string ``'local'`` into a *fixed* UTC offset (the
offset in effect right now), so ``some_date.to('local')`` shows dates on the
other side of a DST change one hour off. Always convert with
``local_tz_info()`` instead, which returns a DST-aware zone.
"""

import datetime
import functools
import os

import click
from dateutil import tz


@functools.lru_cache(maxsize=8)
def _tz_for(name):
    # If name is None or an empty string, gettz returns the local time zone
    return tz.gettz(name)


def local_tz_info() -> datetime.tzinfo:
    """Get the local time zone object, respects the TZ env variable."""
    timezone = os.environ.get("TZ", None)
    tzinfo = _tz_for(timezone)
    # gettz returns None if the timezone passed to gettz is invalid
    if tzinfo is None:
        raise click.ClickException(
            f"Invalid timezone {timezone} specified, "
            "please set the TZ environment variable with"
            " a valid timezone."
        )
    return tzinfo


# Aware datetimes (and arrow.Arrow objects) that share a tzinfo subtract and
# compare by wall clock, ignoring the UTC offset, and every Watson time is in
# the same local zone. So `stop - start` is an hour off when a DST change
# falls in between; these helpers measure real elapsed time instead.


def duration(start, stop) -> datetime.timedelta:
    """Real time from ``start`` to ``stop`` (datetimes or arrow objects)."""
    return datetime.timedelta(seconds=stop.timestamp() - start.timestamp())


def humanize(moment, other=None) -> str:
    """``moment.humanize(other)`` for an arrow object, correct across DST.

    arrow converts ``other`` (default: now) into ``moment``'s own zone before
    subtracting, so convert both to UTC first.
    """
    return moment.to("utc").humanize(None if other is None else other.to("utc"))
