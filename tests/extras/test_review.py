import arrow
import pytest

from watson import Watson, cli
from watson.extras import review
from watson.extras.store import Store
from watson.timezone import local_tz_info

REVIEW = cli.cli.commands["review"]


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr(review, "_is_interactive", lambda: True)


def flag(watson, frame_start, suggested_stop, stopped=None, deferred=False):
    with Store(watson.config_dir).transaction() as state:
        item = review.add_review(
            state,
            project="forgot",
            frame_start=frame_start,
            policy="after-hours",
            suggested_stop=suggested_stop,
            stopped=stopped,
            now=arrow.now(),
        )
        item["deferred"] = deferred


def running_forgotten(watson, hours=3):
    start = arrow.now(local_tz_info()).shift(hours=-hours).floor("minute")
    watson.start("forgot", start_at=start)
    watson.save()
    flag(watson, start, start.shift(hours=1))
    return start


def test_start_shows_pending_then_defers(runner, watson, interactive):
    watson.config.set("options", "stop_on_start", "true")
    running_forgotten(watson)
    result = runner.invoke(cli.start, ["next"], obj=watson, input="d\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.index("1 pending timer review") < out.index("Resolve now, or defer")
    assert "Deferred" in out
    (item,) = Store(watson.config_dir).read()["reviews"]
    assert item["deferred"]

    # Deferred reviews are not prompted again; only a one-line notice
    runner.invoke(cli.stop, [], obj=watson)
    result = runner.invoke(cli.start, ["third"], obj=watson, input="")
    assert result.exit_code == 0, result.output
    assert "Resolve now" not in result.output
    assert "1 deferred timer review" in result.output


def test_start_resolves_running_frame_before_stop_on_start(runner, watson, interactive):
    watson.config.set("options", "stop_on_start", "true")
    start = running_forgotten(watson)
    result = runner.invoke(cli.start, ["next"], obj=watson, input="r\n\n")
    assert result.exit_code == 0, result.output

    fresh = Watson(config_dir=watson.config_dir)
    forgot = next(f for f in fresh.frames if f.project == "forgot")
    assert forgot.stop == start.shift(hours=1)  # the suggested stop, not "now"
    assert fresh.current["project"] == "next"
    assert Store(watson.config_dir).read()["reviews"] == []


def test_resolve_can_keep_running(runner, watson, interactive):
    running_forgotten(watson)
    result = runner.invoke(cli.start, ["next"], obj=watson, input="r\nk\n")
    # Kept running; start then refuses as usual (stop_on_start is off)
    assert "already started" in result.output
    assert Store(watson.config_dir).read()["reviews"] == []


def test_review_corrects_auto_stopped_frame(runner, watson):
    start = arrow.now(local_tz_info()).shift(hours=-5).floor("minute")
    stopped = watson.frames.add(
        "forgot", start, start.shift(hours=2), tags=["auto-stopped"]
    )
    watson.save()
    flag(watson, start, start.shift(hours=2), stopped=stopped, deferred=True)

    new_stop = start.shift(hours=1, minutes=30).format("YYYY-MM-DD HH:mm")
    result = runner.invoke(REVIEW, [], obj=watson, input=f"{new_stop}\n")
    assert result.exit_code == 0, result.output
    assert "(deferred)" in result.output
    frame = Watson(config_dir=watson.config_dir).frames[stopped.id]
    assert frame.stop == start.shift(hours=1, minutes=30)
    assert Store(watson.config_dir).read()["reviews"] == []


def test_review_rejects_stop_before_start(runner, watson):
    start = arrow.now(local_tz_info()).shift(hours=-5).floor("minute")
    stopped = watson.frames.add("forgot", start, start.shift(hours=2))
    watson.save()
    flag(watson, start, start.shift(hours=2), stopped=stopped)
    early = start.shift(hours=-1).format("YYYY-MM-DD HH:mm")
    result = runner.invoke(REVIEW, [], obj=watson, input=f"{early}\n\n")
    assert "must be after the start" in result.output
    frame = Watson(config_dir=watson.config_dir).frames[stopped.id]
    assert frame.stop == start.shift(hours=2)


def test_stop_attaches_frame_id(runner, watson):
    start = running_forgotten(watson)
    result = runner.invoke(cli.stop, [], obj=watson)
    assert result.exit_code == 0, result.output
    (item,) = Store(watson.config_dir).read()["reviews"]
    assert item["frame_id"] == Watson(config_dir=watson.config_dir).frames[-1].id
    assert item["frame_start"] == int(start.timestamp())


def test_reconcile_drops_cancelled_and_deleted(watson):
    running_forgotten(watson)
    watson.cancel()
    watson.save()
    _, reviews = review.load(Watson(config_dir=watson.config_dir))
    assert reviews == []


def test_status_shows_pending_reviews(runner, watson):
    running_forgotten(watson)
    result = runner.invoke(cli.status, [], obj=watson)
    assert "1 pending timer review(s); run `watson review`." in result.output


def test_non_interactive_start_never_prompts(runner, watson):
    running_forgotten(watson)
    result = runner.invoke(cli.start, ["next"], obj=watson, input="")
    assert "Resolve now" not in result.output


def test_broken_review_never_blocks_start(runner, watson, interactive, mocker):
    mocker.patch.object(review, "load", side_effect=ValueError("boom"))
    result = runner.invoke(cli.start, ["next"], obj=watson)
    assert result.exit_code == 0, result.output
    assert "timer review on_start failed: boom" in result.output
    assert Watson(config_dir=watson.config_dir).current["project"] == "next"


def test_parse_when_uses_reference_date():
    ref = arrow.get("2018-12-03T18:00:00-05:00")
    assert (
        review.parse_when("17:15", ref).format("YYYY-MM-DD HH:mm") == "2018-12-03 17:15"
    )
    assert (
        review.parse_when("2018-12-04 08:00", ref).format("YYYY-MM-DD HH:mm")
        == "2018-12-04 08:00"
    )
