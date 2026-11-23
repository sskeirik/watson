"""Unit tests for the main 'watson' module."""

import json
import os

import arrow
import pytest
from click import get_app_dir

from watson import ConflictError, Watson, WatsonError
from watson.frames import Frame
from watson.watson import ConfigParser, ConfigurationError

from . import TEST_FIXTURE_DIR, mock_read


@pytest.fixture
def json_mock(mocker):
    return mocker.patch.object(json, "dumps", side_effect=json.dumps, autospec=True)


# NOTE: All timestamps need to be > 3600 to avoid breaking the tests on
# Windows.

# current


def test_current(mocker, watson):
    content = json.dumps({"project": "foo", "start": 4000, "tags": ["A", "B"]})

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert watson.current["project"] == "foo"
    assert watson.current["start"] == arrow.get(4000)
    assert watson.current["tags"] == ["A", "B"]


def test_current_with_empty_file(mocker, watson):
    mocker.patch("builtins.open", mocker.mock_open(read_data=""))
    mocker.patch("os.path.getsize", return_value=0)
    assert watson.current == {}


def test_current_with_nonexistent_file(mocker, watson):
    mocker.patch("builtins.open", side_effect=IOError)
    assert watson.current == {}


def test_current_watson_non_valid_json(mocker, watson):
    content = "{'foo': bar}"

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    mocker.patch("os.path.getsize", return_value=len(content))
    with pytest.raises(WatsonError):
        watson.current


def test_current_with_given_state(config_dir, mocker):
    content = json.dumps({"project": "foo", "start": 4000})
    watson = Watson(current={"project": "bar", "start": 4000}, config_dir=config_dir)

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert watson.current["project"] == "bar"


def test_current_with_empty_given_state(config_dir, mocker):
    content = json.dumps({"project": "foo", "start": 4000})
    watson = Watson(current=[], config_dir=config_dir)

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert watson.current == {}


def test_current_as_running_frame(watson):
    """
    Ensures frame can be created without a stop date.
    Catches #417: editing task in progress throws an exception
    """
    watson.start("foo", tags=["A", "B"])

    cur = watson.current
    frame = Frame(cur["start"], None, cur["project"], None, cur["tags"])

    assert frame.stop is None
    assert frame.project == "foo"
    assert frame.tags == ["A", "B"]


# frames


def test_frames(mocker, watson):
    content = json.dumps([[4000, 4010, "foo", None, ["A", "B", "C"]]])

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert len(watson.frames) == 1
    assert watson.frames[0].project == "foo"
    assert watson.frames[0].start == arrow.get(4000)
    assert watson.frames[0].stop == arrow.get(4010)
    assert watson.frames[0].tags == ["A", "B", "C"]


def test_frames_without_tags(mocker, watson):
    content = json.dumps([[4000, 4010, "foo", None]])

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert len(watson.frames) == 1
    assert watson.frames[0].project == "foo"
    assert watson.frames[0].start == arrow.get(4000)
    assert watson.frames[0].stop == arrow.get(4010)
    assert watson.frames[0].tags == []


def test_frames_with_empty_file(mocker, watson):
    mocker.patch("builtins.open", mocker.mock_open(read_data=""))
    mocker.patch("os.path.getsize", return_value=0)
    assert len(watson.frames) == 0


def test_frames_with_nonexistent_file(mocker, watson):
    mocker.patch("builtins.open", side_effect=IOError)
    assert len(watson.frames) == 0


def test_frames_watson_non_valid_json(mocker, watson):
    content = "{'foo': bar}"

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    mocker.patch("os.path.getsize", return_value=len(content))
    with pytest.raises(WatsonError):
        watson.frames


def test_given_frames(config_dir, mocker):
    content = json.dumps([[4000, 4010, "foo", None, ["A"]]])
    watson = Watson(
        frames=[[4000, 4010, "bar", None, ["A", "B"]]], config_dir=config_dir
    )

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert len(watson.frames) == 1
    assert watson.frames[0].project == "bar"
    assert watson.frames[0].tags == ["A", "B"]


def test_frames_with_empty_given_state(config_dir, mocker):
    content = json.dumps([[0, 10, "foo", None, ["A"]]])
    watson = Watson(frames=[], config_dir=config_dir)

    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    assert len(watson.frames) == 0


# config


def test_empty_config_dir():
    watson = Watson()
    assert watson._dir == get_app_dir("watson")


def test_wrong_config(mocker, watson):
    content = """
toto
    """
    mocker.patch.object(ConfigParser, "read", mock_read(content))
    with pytest.raises(ConfigurationError):
        watson.config


def test_empty_config(mocker, watson):
    mocker.patch.object(ConfigParser, "read", mock_read(""))
    assert len(watson.config.sections()) == 0


# start


def test_start_new_project(watson):
    watson.start("foo", ["A", "B"])

    assert watson.current != {}
    assert watson.is_started is True
    assert watson.current.get("project") == "foo"
    assert isinstance(watson.current.get("start"), arrow.Arrow)
    assert watson.current.get("tags") == ["A", "B"]


def test_start_new_project_without_tags(watson):
    watson.start("foo")

    assert watson.current != {}
    assert watson.is_started is True
    assert watson.current.get("project") == "foo"
    assert isinstance(watson.current.get("start"), arrow.Arrow)
    assert watson.current.get("tags") == []


def test_start_two_projects(watson):
    watson.start("foo")

    with pytest.raises(WatsonError):
        watson.start("bar")

    assert watson.current != {}
    assert watson.current["project"] == "foo"
    assert watson.is_started is True


def test_start_default_tags(mocker, watson):
    content = """
[default_tags]
my project = A B
    """

    mocker.patch.object(ConfigParser, "read", mock_read(content))
    watson.start("my project")
    assert watson.current["tags"] == ["A", "B"]


def test_start_default_tags_with_supplementary_input_tags(mocker, watson):
    content = """
[default_tags]
my project = A B
    """

    mocker.patch.object(ConfigParser, "read", mock_read(content))
    watson.start("my project", tags=["C", "D"])
    assert watson.current["tags"] == ["C", "D", "A", "B"]


def test_start_nogap(watson):

    watson.start("foo")
    watson.stop()
    watson.start("bar", gap=False)

    assert watson.frames[-1].stop == watson.current["start"]


def test_start_project_at(watson):
    now = arrow.now()
    watson.start("foo", start_at=now)
    watson.stop()

    # Task can't start before the previous task ends
    with pytest.raises(WatsonError):
        time_str = "1970-01-01T00:00"
        time_obj = arrow.get(time_str)
        watson.start("foo", start_at=time_obj)

    # Task can't start in the future
    with pytest.raises(WatsonError):
        time_str = "2999-12-31T23:59"
        time_obj = arrow.get(time_str)
        watson.start("foo", start_at=time_obj)

    assert watson.frames[-1].start == now


# stop


def test_stop_started_project(watson):
    watson.start("foo", tags=["A", "B"])
    watson.stop()

    assert watson.current == {}
    assert watson.is_started is False
    assert len(watson.frames) == 1
    assert watson.frames[0].project == "foo"
    assert isinstance(watson.frames[0].start, arrow.Arrow)
    assert isinstance(watson.frames[0].stop, arrow.Arrow)
    assert watson.frames[0].tags == ["A", "B"]


def test_stop_started_project_without_tags(watson):
    watson.start("foo")
    watson.stop()

    assert watson.current == {}
    assert watson.is_started is False
    assert len(watson.frames) == 1
    assert watson.frames[0].project == "foo"
    assert isinstance(watson.frames[0].start, arrow.Arrow)
    assert isinstance(watson.frames[0].stop, arrow.Arrow)
    assert watson.frames[0].tags == []


def test_stop_no_project(watson):
    with pytest.raises(WatsonError):
        watson.stop()


def test_stop_started_project_at(watson):
    watson.start("foo")
    now = arrow.now()

    # Task can't end before it starts
    with pytest.raises(WatsonError):
        time_str = "1970-01-01T00:00"
        time_obj = arrow.get(time_str)
        watson.stop(stop_at=time_obj)

    # Task can't end in the future
    with pytest.raises(WatsonError):
        time_str = "2999-12-31T23:59"
        time_obj = arrow.get(time_str)
        watson.stop(stop_at=time_obj)

    watson.stop(stop_at=now)
    assert watson.frames[-1].stop == now


# cancel


def test_cancel_started_project(watson):
    watson.start("foo")
    watson.cancel()

    assert watson.current == {}
    assert len(watson.frames) == 0


def test_cancel_no_project(watson):
    with pytest.raises(WatsonError):
        watson.cancel()


# save


def test_save_without_changes(mocker, watson, json_mock):
    watson.save()

    assert not json_mock.called


def test_save_current(mocker, watson, json_mock):
    watson.start("foo", ["A", "B"])

    watson.save()

    assert json_mock.call_count == 1
    result = json_mock.call_args[0][0]
    assert result["project"] == "foo"
    assert isinstance(result["start"], (int, float))
    assert result["tags"] == ["A", "B"]


def test_save_current_without_tags(mocker, watson, json_mock):
    watson.start("foo")

    watson.save()

    assert json_mock.call_count == 1
    result = json_mock.call_args[0][0]
    assert result["project"] == "foo"
    assert isinstance(result["start"], (int, float))
    assert result["tags"] == []

    dump_args = json_mock.call_args[1]
    assert dump_args["ensure_ascii"] is False


def test_save_empty_current(config_dir, mocker, json_mock):
    watson = Watson(current={}, config_dir=config_dir)

    watson.current = {"project": "foo", "start": 4000}
    watson.save()

    assert json_mock.call_count == 1
    result = json_mock.call_args[0][0]
    assert result == {"project": "foo", "start": 4000, "tags": []}

    watson.current = {}
    watson.save()

    assert json_mock.call_count == 2
    result = json_mock.call_args[0][0]
    assert result == {}


def test_save_frames_no_change(config_dir, mocker, json_mock):
    watson = Watson(frames=[[4000, 4010, "foo", None]], config_dir=config_dir)

    watson.save()

    assert not json_mock.called


def test_save_added_frame(config_dir, mocker, json_mock):
    watson = Watson(frames=[[4000, 4010, "foo", None]], config_dir=config_dir)
    watson.frames.add("bar", 4010, 4020, ["A"])

    watson.save()

    assert json_mock.call_count == 1
    result = json_mock.call_args[0][0]
    assert len(result) == 2
    assert result[0][2] == "foo"
    assert result[0][4] == []
    assert result[1][2] == "bar"
    assert result[1][4] == ["A"]


def test_save_changed_frame(config_dir, mocker, json_mock):
    watson = Watson(frames=[[4000, 4010, "foo", None, ["A"]]], config_dir=config_dir)
    watson.frames[0] = ("bar", 4000, 4010, ["A", "B"])

    watson.save()

    assert json_mock.call_count == 1
    result = json_mock.call_args[0][0]
    assert len(result) == 1
    assert result[0][2] == "bar"
    assert result[0][4] == ["A", "B"]

    dump_args = json_mock.call_args[1]
    assert dump_args["ensure_ascii"] is False


def test_save_config_no_changes(mocker, watson):
    write_mock = mocker.patch.object(ConfigParser, "write")
    watson.save()

    assert not write_mock.called


def test_save_config(mocker, watson):
    write_mock = mocker.patch.object(ConfigParser, "write")
    watson.config = ConfigParser()
    watson.save()

    assert write_mock.call_count == 1


def test_watson_save_calls_safe_save(mocker, config_dir, watson):
    frames_file = os.path.join(config_dir, "frames")
    watson.start("foo", tags=["A", "B"])
    watson.stop()

    save_mock = mocker.patch("watson.watson.safe_save")
    watson.save()

    assert watson._frames.changed
    assert save_mock.call_count == 1
    assert len(save_mock.call_args[0]) == 2
    assert save_mock.call_args[0][0] == frames_file


# projects


def test_projects(watson):
    for name in ("foo", "bar", "bar", "bar", "foo", "lol"):
        watson.frames.add(name, 4000, 4000)

    assert watson.projects == ["bar", "foo", "lol"]


def test_projects_no_frames(watson):
    assert watson.projects == []


# tags


def test_tags(watson):
    samples = (
        ("foo", ("A", "D")),
        ("bar", ("A", "C")),
        ("foo", ("B", "C")),
        ("lol", ()),
        ("bar", ("C")),
    )

    for name, tags in samples:
        watson.frames.add(name, 4000, 4000, tags)

    assert watson.tags == ["A", "B", "C", "D"]


def test_tags_no_frames(watson):
    assert watson.tags == []


# merge


@pytest.mark.datafiles(
    TEST_FIXTURE_DIR / "frames-with-conflict",
)
def test_merge_report(watson, datafiles):
    # Get report
    watson.frames.add("foo", 4000, 4015, id="1", updated_at=4015)
    watson.frames.add("bar", 4020, 4045, id="2", updated_at=4045)

    conflicting, merging = watson.merge_report(str(datafiles) + "/frames-with-conflict")

    assert len(conflicting) == 1
    assert len(merging) == 1

    assert conflicting[0].id == "2"
    assert merging[0].id == "3"


def test_report(watson):
    watson.start("foo", tags=["A", "B"])
    watson.stop()

    report = watson.report(arrow.now(), arrow.now())
    assert "time" in report
    assert "timespan" in report
    assert "from" in report["timespan"]
    assert "to" in report["timespan"]
    assert len(report["projects"]) == 1
    assert report["projects"][0]["name"] == "foo"
    assert len(report["projects"][0]["tags"]) == 2
    assert report["projects"][0]["tags"][0]["name"] == "A"
    assert "time" in report["projects"][0]["tags"][0]
    assert report["projects"][0]["tags"][1]["name"] == "B"
    assert "time" in report["projects"][0]["tags"][1]

    watson.start("bar", tags=["C"])
    watson.stop()

    report = watson.report(arrow.now(), arrow.now())
    assert len(report["projects"]) == 2
    assert report["projects"][0]["name"] == "bar"
    assert report["projects"][1]["name"] == "foo"
    assert len(report["projects"][0]["tags"]) == 1
    assert report["projects"][0]["tags"][0]["name"] == "C"

    report = watson.report(arrow.now(), arrow.now(), projects=["foo"], tags=["B"])
    assert len(report["projects"]) == 1
    assert report["projects"][0]["name"] == "foo"
    assert len(report["projects"][0]["tags"]) == 1
    assert report["projects"][0]["tags"][0]["name"] == "B"

    watson.start("baz", tags=["D"])
    watson.stop()

    report = watson.report(arrow.now(), arrow.now(), projects=["foo"])
    assert len(report["projects"]) == 1

    report = watson.report(arrow.now(), arrow.now(), ignore_projects=["bar"])
    assert len(report["projects"]) == 2

    report = watson.report(arrow.now(), arrow.now(), tags=["A"])
    assert len(report["projects"]) == 1

    report = watson.report(arrow.now(), arrow.now(), ignore_tags=["D"])
    assert len(report["projects"]) == 2

    with pytest.raises(WatsonError):
        watson.report(
            arrow.now(), arrow.now(), projects=["foo"], ignore_projects=["foo"]
        )

    with pytest.raises(WatsonError):
        watson.report(arrow.now(), arrow.now(), tags=["A"], ignore_tags=["A"])


def test_report_current(mocker, config_dir):
    mocker.patch("arrow.utcnow", return_value=arrow.get(5000))

    watson = Watson(current={"project": "foo", "start": 4000}, config_dir=config_dir)

    report = None
    for _ in range(2):
        report = watson.report(
            arrow.utcnow(), arrow.utcnow(), current=True, projects=["foo"]
        )
    assert report is not None
    assert len(report["projects"]) == 1
    assert report["projects"][0]["name"] == "foo"
    assert report["projects"][0]["time"] == pytest.approx(1000)

    report = watson.report(
        arrow.utcnow(), arrow.utcnow(), current=False, projects=["foo"]
    )
    assert len(report["projects"]) == 0

    report = watson.report(arrow.utcnow(), arrow.utcnow(), projects=["foo"])
    assert len(report["projects"]) == 0


@pytest.mark.parametrize(
    "date_as_unixtime,include_partial,sum_",
    (
        (3600 * 24, False, 0.0),
        (3600 * 48, False, 0.0),
        (3600 * 24, True, 7200.0),
        (3600 * 48, True, 3600.0),
    ),
)
def test_report_include_partial_frames(
    mocker, watson, date_as_unixtime, include_partial, sum_
):
    """Test report building with frames that cross report boundaries

    1 event is added that has 2 hours in one day and 1 in the next. The
    parametrization checks that the report for both days is empty with
    `include_partial=False` and report the correct amount of hours with
    `include_partial=False`

    """
    content = json.dumps(
        [
            [
                3600 * 46,
                3600 * 49,
                "programming",
                "3e76c820909840f89cabaf106ab7d12a",
                ["cli"],
                1548797432,
            ]
        ]
    )
    mocker.patch("builtins.open", mocker.mock_open(read_data=content))
    date = arrow.get(date_as_unixtime)
    report = watson.report(
        from_=date,
        to=date,
        include_partial_frames=include_partial,
    )
    assert report["time"] == pytest.approx(sum_, abs=1e-3)


# renaming project updates frame last_updated time
def test_rename_project_with_time(watson):
    """
    Renaming a project should update the "last_updated" time on any frame that
    contains that project.
    """
    watson.frames.add(
        "foo",
        4001,
        4002,
        ["some_tag"],
        id="c76d1ad0282c429595cc566d7098c165",
        updated_at=4005,
    )
    watson.frames.add(
        "bar",
        4010,
        4015,
        ["other_tag"],
        id="eed598ff363d42658a095ae6c3ae1088",
        updated_at=4035,
    )

    watson.rename_project("foo", "baz")

    assert len(watson.frames) == 2

    assert watson.frames[0].id == "c76d1ad0282c429595cc566d7098c165"
    assert watson.frames[0].project == "baz"
    assert watson.frames[0].start.int_timestamp == 4001
    assert watson.frames[0].stop.int_timestamp == 4002
    assert watson.frames[0].tags == ["some_tag"]
    # assert watson.frames[0].updated_at.int_timestamp == 9000
    assert watson.frames[0].updated_at.int_timestamp > 4005

    assert watson.frames[1].id == "eed598ff363d42658a095ae6c3ae1088"
    assert watson.frames[1].project == "bar"
    assert watson.frames[1].start.int_timestamp == 4010
    assert watson.frames[1].stop.int_timestamp == 4015
    assert watson.frames[1].tags == ["other_tag"]
    assert watson.frames[1].updated_at.int_timestamp == 4035


def test_rename_tag_with_time(watson):
    """
    Renaming a tag should update the "last_updated" time on any frame that
    contains that tag.
    """
    watson.frames.add(
        "foo",
        4001,
        4002,
        ["some_tag"],
        id="c76d1ad0282c429595cc566d7098c165",
        updated_at=4005,
    )
    watson.frames.add(
        "bar",
        4010,
        4015,
        ["other_tag"],
        id="eed598ff363d42658a095ae6c3ae1088",
        updated_at=4035,
    )

    watson.rename_tag("other_tag", "baz")

    assert len(watson.frames) == 2

    assert watson.frames[0].id == "c76d1ad0282c429595cc566d7098c165"
    assert watson.frames[0].project == "foo"
    assert watson.frames[0].start.int_timestamp == 4001
    assert watson.frames[0].stop.int_timestamp == 4002
    assert watson.frames[0].tags == ["some_tag"]
    assert watson.frames[0].updated_at.int_timestamp == 4005

    assert watson.frames[1].id == "eed598ff363d42658a095ae6c3ae1088"
    assert watson.frames[1].project == "bar"
    assert watson.frames[1].start.int_timestamp == 4010
    assert watson.frames[1].stop.int_timestamp == 4015
    assert watson.frames[1].tags == ["baz"]
    # assert watson.frames[1].updated_at.int_timestamp == 9000
    assert watson.frames[1].updated_at.int_timestamp > 4035


# add


def test_add_success(watson):
    """
    Adding a new frame outside of live tracking successfully
    """
    watson.add(
        project="test_project", tags=["fuu", "bar"], from_date=6000, to_date=7000
    )

    assert len(watson.frames) == 1
    assert watson.frames[0].project == "test_project"
    assert "fuu" in watson.frames[0].tags


def test_add_failure(watson):
    """
    Adding a new frame outside of live tracking fails when
    to date is before from date
    """
    with pytest.raises(WatsonError):
        watson.add(
            project="test_project", tags=["fuu", "bar"], from_date=7000, to_date=6000
        )


def test_validate_report_options(watson):
    assert watson._validate_report_options(["project_foo"], None)
    assert watson._validate_report_options(None, ["project_foo"])
    assert not watson._validate_report_options(["project_foo"], ["project_foo"])
    assert watson._validate_report_options(["project_foo"], ["project_bar"])
    assert not watson._validate_report_options(
        ["project_foo", "project_bar"], ["project_foo"]
    )
    assert not watson._validate_report_options(
        ["project_foo", "project_bar"], ["project_foo", "project_bar"]
    )
    assert watson._validate_report_options(None, None)


# concurrent saves


def test_save_refuses_to_overwrite_frames_changed_by_another_process(config_dir):
    ours = Watson(config_dir=config_dir)
    assert len(ours.frames) == 0  # read

    theirs = Watson(config_dir=config_dir)
    theirs.add("theirs", 4000, 5000, [])
    theirs.save()

    ours.add("ours", 6000, 7000, [])
    with pytest.raises(ConflictError, match="'frames' changed"):
        ours.save()
    assert [f.project for f in Watson(config_dir=config_dir).frames] == ["theirs"]


def test_save_refuses_to_overwrite_state_changed_by_another_process(config_dir):
    ours = Watson(config_dir=config_dir)
    assert not ours.is_started  # read

    theirs = Watson(config_dir=config_dir)
    theirs.start("theirs")
    theirs.save()

    ours.start("ours")
    with pytest.raises(ConflictError, match="'state' changed"):
        ours.save()
    assert Watson(config_dir=config_dir).current["project"] == "theirs"


def test_save_checks_files_read_even_if_not_written(config_dir):
    # `stop` decides from the state, so a stale state must block the frames
    # write too, even when only the state changed underneath.
    ours = Watson(config_dir=config_dir)
    assert len(ours.frames) == 0 and not ours.is_started

    theirs = Watson(config_dir=config_dir)
    theirs.start("theirs")
    theirs.save()

    ours.add("ours", 4000, 5000, [])
    with pytest.raises(ConflictError):
        ours.save()


def test_successive_saves_by_one_instance_do_not_conflict(config_dir):
    watson = Watson(config_dir=config_dir)
    watson.start("one", start_at=arrow.now().shift(hours=-1))
    watson.save()
    watson.stop()
    watson.save()
    watson.add("two", 4000, 5000, [])
    watson.save()
    fresh = Watson(config_dir=config_dir)
    assert sorted(f.project for f in fresh.frames) == ["one", "two"]
    assert not fresh.is_started


def test_save_after_another_process_is_fine_when_reading_after_it(config_dir):
    theirs = Watson(config_dir=config_dir)
    theirs.add("theirs", 4000, 5000, [])
    theirs.save()

    ours = Watson(config_dir=config_dir)
    ours.add("ours", 6000, 7000, [])
    ours.save()
    assert len(Watson(config_dir=config_dir).frames) == 2


def test_save_leaves_no_lock_file(config_dir):
    watson = Watson(config_dir=config_dir)
    watson.add("p", 4000, 5000, [])
    watson.save()
    assert not os.path.exists(os.path.join(config_dir, "data.lock"))
