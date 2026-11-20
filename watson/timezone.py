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
