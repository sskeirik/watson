import datetime

import pytest

from watson.config import ConfigParser
from watson.extras.settings import (
    SettingsError,
    format_duration,
    load_policies,
    parse_duration,
    reminder_settings,
)

td = datetime.timedelta


@pytest.mark.parametrize(
    "text, expected",
    [
        ("90m", td(minutes=90)),
        ("1h30m", td(hours=1, minutes=30)),
        ("10h", td(hours=10)),
        ("2d", td(days=2)),
        ("45s", td(seconds=45)),
        (" 1H ", td(hours=1)),
    ],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


def test_parse_signed_duration():
    assert parse_duration("-15m", signed=True) == td(minutes=-15)
    assert parse_duration("+5m", signed=True) == td(minutes=5)


@pytest.mark.parametrize("text", ["", "15", "m", "1x", "-15m", "1h 30m"])
def test_parse_duration_invalid(text):
    with pytest.raises(SettingsError):
        parse_duration(text)


def test_format_duration():
    assert format_duration(td(hours=9, minutes=30)) == "9h30m"
    assert format_duration(td(hours=2)) == "2h"
    assert format_duration(td(minutes=5)) == "5m"


def config(**sections):
    c = ConfigParser()
    for section, values in sections.items():
        c.add_section(section.replace("_", ":"))
        for key, value in values.items():
            c.set(section.replace("_", ":"), key, value)
    return c


def test_reminder_defaults():
    r = reminder_settings(ConfigParser())
    assert (r.enabled, r.grace, r.repeat) == (True, td(minutes=10), td(minutes=30))


def test_load_policies():
    c = config(
        policy_late={
            "trigger": "offhours",
            "after": "1h",
            "handlers": "toast@-15m toast autostop prompt",
        },
        policy_long={"trigger": "elapsed", "after": "10h", "handlers": "autostop"},
        options={"stop_on_start": "true"},
    )
    late, long = sorted(load_policies(c), key=lambda p: p.name)
    assert late.name == "late"
    assert late.stop_at == "onset"  # offhours default
    assert [(h.name, h.offset) for h in late.handlers] == [
        ("toast", td(minutes=-15)),
        ("toast", td()),
        ("autostop", td()),
        ("prompt", td()),
    ]
    assert long.stop_at == "fire"  # elapsed default


@pytest.mark.parametrize(
    "values, message",
    [
        ({"trigger": "sometimes", "after": "1h", "handlers": "toast"}, "trigger"),
        ({"trigger": "elapsed", "handlers": "toast"}, "after"),
        ({"trigger": "elapsed", "after": "1h", "handlers": "beep"}, "unknown handler"),
        ({"trigger": "elapsed", "after": "1h", "handlers": ""}, "at least one"),
        (
            {"trigger": "elapsed", "after": "1h", "handlers": "toast@soon"},
            "invalid duration",
        ),
        (
            {
                "trigger": "elapsed",
                "after": "1h",
                "handlers": "autostop",
                "stop_at": "onset",
            },
            "erase the whole frame",
        ),
    ],
)
def test_load_policies_errors(values, message):
    with pytest.raises(SettingsError, match=message):
        load_policies(config(policy_bad=values))
