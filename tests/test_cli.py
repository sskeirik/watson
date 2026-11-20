import re
from datetime import datetime, timedelta
from itertools import combinations

import arrow
import pytest

from watson import cli
from watson.cli import local_tz_info

# Not all ISO-8601 compliant strings are recognized by arrow.get(str)
VALID_DATES_DATA = [
    ("2018", "2018-01-01 00:00:00"),  # years
    ("2018-04", "2018-04-01 00:00:00"),  # calendar dates
    ("2018-04-10", "2018-04-10 00:00:00"),
    ("2018/04/10", "2018-04-10 00:00:00"),
    ("2018.04.10", "2018-04-10 00:00:00"),
    ("2018-4-10", "2018-04-10 00:00:00"),
    ("2018/4/10", "2018-04-10 00:00:00"),
    ("2018.4.10", "2018-04-10 00:00:00"),
    ("20180410", "2018-04-10 00:00:00"),
    ("2018-123", "2018-05-03 00:00:00"),  # ordinal dates
    ("2018-04-10 12:30:43", "2018-04-10 12:30:43"),
    ("2018-04-10T12:30:43", "2018-04-10 12:30:43"),
    ("2018-04-10 12:30:43Z", "2018-04-10 12:30:43"),
    ("2018-04-10 12:30:43.1233", "2018-04-10 12:30:43"),
    ("2018-04-10 12:30:43+03:00", "2018-04-10 12:30:43"),
    ("2018-04-10 12:30:43-07:00", "2018-04-10 12:30:43"),
    ("2018-04-10T12:30:43-07:00", "2018-04-10 12:30:43"),
    ("2018-04-10 12:30", "2018-04-10 12:30:00"),
    ("2018-04-10T12:30", "2018-04-10 12:30:00"),
    ("2018-04-10 12", "2018-04-10 12:00:00"),
    ("2018-04-10T12", "2018-04-10 12:00:00"),
    (
        "14:05:12",
        arrow.now().replace(hour=14, minute=5, second=12).format("YYYY-MM-DD HH:mm:ss"),
    ),
    (
        "14:05",
        arrow.now().replace(hour=14, minute=5, second=0).format("YYYY-MM-DD HH:mm:ss"),
    ),
    ("2018-W08", "2018-02-19 00:00:00"),  # week dates
    ("2018W08", "2018-02-19 00:00:00"),
    ("2018-W08-2", "2018-02-20 00:00:00"),
    ("2018W082", "2018-02-20 00:00:00"),
]

INVALID_DATES_DATA = [
    (" 2018"),
    ("2018 "),
    ("201804"),
    ("18-04-10"),
    ("180410"),  # truncated representation not allowed
    ("hello 2018"),
    ("yesterday"),
    ("tomorrow"),
    ("14:05:12.000"),  # Times alone are not allowed
    ("140512.000"),
    ("140512"),
    ("14.05"),
    ("2018-04-10T"),
    ("2018-04-10T12:30:43."),
]

VALID_TIMES_DATA = [
    ("14:12"),
    ("14:12:43"),
    ("2019-04-10T14:12"),
    ("2019-04-10T14:12:43"),
]


class OutputParser:
    FRAME_ID_PATTERN = re.compile(r"id: (?P<frame_id>[0-9a-f]+)")

    @staticmethod
    def get_frame_id(output):
        match = OutputParser.FRAME_ID_PATTERN.search(output)
        assert match is not None
        return match.group("frame_id")

    @staticmethod
    def get_start_date(watson, output):
        frame_id = OutputParser.get_frame_id(output)
        return watson.frames[frame_id].start.format("YYYY-MM-DD HH:mm:ss")


# watson add


@pytest.mark.parametrize("test_dt,expected", VALID_DATES_DATA)
def test_add_valid_date(runner, watson, test_dt, expected):
    result = runner.invoke(
        cli.add, ["-f", test_dt, "-t", test_dt, "project-name"], obj=watson
    )
    assert result.exit_code == 0
    assert OutputParser.get_start_date(watson, result.output) == expected


@pytest.mark.parametrize("test_dt", INVALID_DATES_DATA)
def test_add_invalid_date(runner, watson, test_dt):
    result = runner.invoke(
        cli.add, ["-f", test_dt, "-t", test_dt, "project-name"], obj=watson
    )
    assert result.exit_code != 0


# watson aggregate


@pytest.mark.parametrize("test_dt,expected", VALID_DATES_DATA)
def test_aggregate_valid_date(runner, watson, test_dt, expected):
    # This is super fast, because no internal 'report' invocations are made
    result = runner.invoke(cli.aggregate, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code == 0


@pytest.mark.parametrize("test_dt", INVALID_DATES_DATA)
def test_aggregate_invalid_date(runner, watson, test_dt):
    # This is super fast, because no internal 'report' invocations are made
    result = runner.invoke(cli.aggregate, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code != 0


# watson log


@pytest.mark.parametrize("cmd", [cli.aggregate, cli.log, cli.report])
def test_incompatible_options(runner, watson, cmd):
    name_interval_options = ["--" + s for s in cli._SHORTCUT_OPTIONS]
    for opt1, opt2 in combinations(name_interval_options, 2):
        result = runner.invoke(cmd, [opt1, opt2], obj=watson)
        assert result.exit_code != 0


@pytest.mark.parametrize("test_dt,expected", VALID_DATES_DATA)
def test_log_valid_date(runner, watson, test_dt, expected):
    result = runner.invoke(cli.log, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code == 0


@pytest.mark.parametrize("test_dt", INVALID_DATES_DATA)
def test_log_invalid_date(runner, watson, test_dt):
    result = runner.invoke(cli.log, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code != 0


# watson report


@pytest.mark.parametrize("test_dt,expected", VALID_DATES_DATA)
def test_report_valid_date(runner, watson, test_dt, expected):
    result = runner.invoke(cli.report, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code == 0


@pytest.mark.parametrize("test_dt", INVALID_DATES_DATA)
def test_report_invalid_date(runner, watson, test_dt):
    result = runner.invoke(cli.report, ["-f", test_dt, "-t", test_dt], obj=watson)
    assert result.exit_code != 0


# watson stop


@pytest.mark.parametrize("at_dt", VALID_TIMES_DATA)
def test_stop_valid_time(runner, watson, mocker, at_dt):
    mock_dt = mocker.patch("arrow.arrow.dt_datetime", wraps=datetime)
    start_dt = datetime(2019, 4, 10, 14, 0, 0, tzinfo=local_tz_info())
    mock_dt.now.return_value = start_dt
    result = runner.invoke(cli.start, ["a-project"], obj=watson)
    assert result.exit_code == 0
    # Simulate one hour has elapsed, so that 'at_dt' is older than now()
    # but newer than the start date.
    mock_dt.now.return_value = start_dt + timedelta(hours=1)
    result = runner.invoke(cli.stop, ["--at", at_dt], obj=watson)
    assert result.exit_code == 0


# watson start


@pytest.mark.parametrize("at_dt", VALID_TIMES_DATA)
def test_start_valid_time(runner, watson, mocker, at_dt):
    # Simulate a start date so that 'at_dt' is older than now().
    mock_dt = mocker.patch("arrow.arrow.dt_datetime", wraps=datetime)
    start_dt = datetime(2019, 4, 10, 14, 0, 0, tzinfo=local_tz_info())
    mock_dt.now.return_value = start_dt + timedelta(hours=1)
    result = runner.invoke(cli.start, ["a-project", "--at", at_dt], obj=watson)
    assert result.exit_code == 0


# watson start new task in past, with existing task


def test_start_existing_frame_stopped(runner, watson, mocker):
    # Simulate a start date so that 'at_dt' is older than now().
    watson.config.set("options", "stop_on_start", "true")
    mock_dt = mocker.patch("arrow.arrow.dt_datetime", wraps=datetime)
    start_dt = datetime(2019, 4, 10, 15, 0, 0, tzinfo=local_tz_info())
    mock_dt.now.return_value = start_dt
    runner.invoke(
        cli.start,
        ["a-project", "--at", "14:10"],
        obj=watson,
    )

    result = runner.invoke(
        cli.start,
        ["b-project", "--at", "14:15"],
        obj=watson,
    )
    assert result.exit_code == 0, result.stdout

    frame_id = OutputParser.get_frame_id(result.output)
    assert watson.frames[frame_id].project == "a-project"
    assert watson.current["project"] == "b-project"


# watson restart


@pytest.mark.parametrize("at_dt", VALID_TIMES_DATA)
def test_restart_valid_time(runner, watson, mocker, at_dt):
    # Create a previous entry the same as in `test_stop_valid_time`
    mock_dt = mocker.patch("arrow.arrow.dt_datetime", wraps=datetime)
    start_dt = datetime(2019, 4, 10, 14, 0, 0, tzinfo=local_tz_info())
    mock_dt.now.return_value = start_dt
    result = runner.invoke(cli.start, ["a-project"], obj=watson)
    # Simulate one hour has elapsed, so that 'at_dt' is older than now()
    # but newer than the start date.
    mock_dt.now.return_value = start_dt + timedelta(hours=1)
    result = runner.invoke(cli.stop, ["--at", at_dt], obj=watson)
    # Test that the last frame can be restarted
    result = runner.invoke(cli.restart, ["--at", at_dt], obj=watson)
    assert result.exit_code == 0


# watson report/log/aggregate: -q/--quarter, --prev, --range


@pytest.fixture
def period_watson(watson, mocker, monkeypatch):
    """A Watson with one frame per week around a fixed "now" of Fri 2018-12-07."""
    monkeypatch.setenv("TZ", "UTC")
    from watson import utils

    real = utils.get_period_range
    now = arrow.Arrow(2018, 12, 7, 15, tzinfo=local_tz_info())
    mocker.patch(
        "watson.cli.get_period_range",
        side_effect=lambda *a, **k: real(*a, now=now, **k),
    )
    for day, project in [
        ("2018-11-13", "three-weeks-ago"),
        ("2018-11-20", "two-weeks-ago"),
        ("2018-11-27", "last-week"),
        ("2018-12-04", "this-week"),
        ("2018-09-12", "last-quarter"),
    ]:
        start = arrow.get(f"{day}T10:00:00+00:00")
        watson.frames.add(project, start, start.shift(hours=1))
    watson.save()
    return watson


def _report_json(runner, watson, args):
    import json

    result = runner.invoke(cli.report, ["--json", *args], obj=watson)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    projects = sorted(p["name"] for p in report["projects"])
    return report["timespan"]["from"][:10], report["timespan"]["to"][:10], projects


@pytest.mark.parametrize(
    "args, expected",
    [
        (["-w", "--prev", "3"], ("2018-11-12", "2018-11-18", ["three-weeks-ago"])),
        (
            ["-w", "--prev", "3-0"],
            (
                "2018-11-12",
                "2018-12-07",
                ["last-week", "this-week", "three-weeks-ago", "two-weeks-ago"],
            ),
        ),
        (
            ["-w", "--range", "1"],
            ("2018-11-26", "2018-12-07", ["last-week", "this-week"]),
        ),
        (
            ["-w", "--range", "3-2"],
            ("2018-11-12", "2018-11-25", ["three-weeks-ago", "two-weeks-ago"]),
        ),
        (["-w", "--prev", "0"], ("2018-12-03", "2018-12-07", ["this-week"])),
        (["-q", "--prev", "1"], ("2018-07-01", "2018-09-30", ["last-quarter"])),
        (
            ["-m", "--prev", "1"],
            (
                "2018-11-01",
                "2018-11-30",
                ["last-week", "three-weeks-ago", "two-weeks-ago"],
            ),
        ),
    ],
)
def test_report_period_offsets(runner, period_watson, args, expected):
    assert _report_json(runner, period_watson, args) == expected


def test_report_quarter_shortcut(runner, watson):
    from watson.utils import get_start_time_for_period

    result = runner.invoke(cli.report, ["--json", "-q"], obj=watson)
    assert result.exit_code == 0, result.output
    expected = get_start_time_for_period("quarter").format("YYYY-MM-DD")
    assert expected in result.output


@pytest.mark.parametrize(
    "args, message",
    [
        (["-w", "--prev", "1-3"], "start offset 1 is less than end offset 3"),
        (["--prev", "2"], "needs exactly one of"),
        (["-a", "--range", "1"], "needs exactly one of"),
        (["-w", "--prev", "1", "--range", "2"], "mutually exclusive"),
        (["--prev", "1", "--from", "2018-01-01"], "can't be combined with --from"),
        (["--range", "1", "--to", "2018-01-01"], "can't be combined with --to"),
        (["-w", "--prev", "x"], "not a valid offset"),
        (["-w", "-q"], "mutually exclusive"),
    ],
)
@pytest.mark.parametrize("command", ["report", "log", "aggregate"])
def test_period_offsets_errors(runner, watson, command, args, message):
    if command == "aggregate" and args[0] == "-a":
        pytest.skip("aggregate has no --all")
    result = runner.invoke(getattr(cli, command), args, obj=watson)
    assert result.exit_code != 0
    assert message in result.output


def test_log_period_offsets(runner, period_watson):
    result = runner.invoke(cli.log, ["--csv", "-w", "--range", "1"], obj=period_watson)
    assert result.exit_code == 0, result.output
    rows = [line for line in result.output.splitlines()[1:] if line]
    projects = sorted(row.split(",")[3] for row in rows)
    assert projects == ["last-week", "this-week"]


def test_aggregate_period_offsets(runner, period_watson):
    result = runner.invoke(
        cli.aggregate, ["--csv", "-w", "--prev", "1"], obj=period_watson
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line]
    assert lines[1].startswith("2018-11-27 00:00:00,2018-11-27 23:59:59,last-week")
    assert len(lines) == 2


def test_aggregate_week_shortcut(runner, watson):
    from watson.utils import get_start_time_for_period

    result = runner.invoke(cli.aggregate, ["--json", "-w"], obj=watson)
    assert result.exit_code == 0, result.output
    expected = get_start_time_for_period("week").format("YYYY-MM-DD")
    assert f'"from": "{expected}' in result.output
