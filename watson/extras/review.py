"""Pending reviews of flagged frames.

The ``prompt`` policy handler flags a frame. At the next ``watson start``
the pending reviews are listed and the user either resolves them (stop a
still-running frame at the right time, or correct an auto-stopped frame's
stop time) or defers them all to ``watson review``.
"""

from __future__ import annotations

import re
import sys

import arrow
import click

from ..timezone import local_tz_info
from ..utils import style
from ..watson import WatsonError
from .store import Store


def _ts(moment) -> int:
    return int(moment.timestamp())


def _local(ts: int) -> arrow.Arrow:
    return arrow.get(ts).to(local_tz_info())


def _fmt(ts: int) -> str:
    return _local(ts).format("ddd YYYY-MM-DD HH:mm")


def add_review(state, *, project, frame_start, policy, suggested_stop, stopped, now):
    """Record (or update) the review for a frame. One review per frame."""
    key = _ts(frame_start)
    for item in state["reviews"]:
        if item["frame_start"] == key:
            if policy not in item["policies"]:
                item["policies"].append(policy)
            item["suggested_stop"] = min(item["suggested_stop"], _ts(suggested_stop))
            if stopped is not None:
                item["frame_id"] = stopped.id
                item["autostopped"] = True
            return item
    item = {
        "frame_start": key,
        "project": project,
        "frame_id": stopped.id if stopped is not None else None,
        "policies": [policy],
        "suggested_stop": _ts(suggested_stop),
        "autostopped": stopped is not None,
        "deferred": False,
        "created": _ts(now),
    }
    state["reviews"].append(item)
    return item


def _find_frame(watson, frame_start: int):
    for frame in watson.frames:
        if _ts(frame.start) == frame_start:
            return frame
    return None


def reconcile(watson, reviews: list[dict]) -> list[dict]:
    """Drop reviews whose frame is gone; attach ids to frames stopped since."""
    current = watson.current
    out = []
    for item in reviews:
        if item.get("frame_id"):
            try:
                watson.frames[item["frame_id"]]
            except KeyError:
                continue  # frame deleted
            out.append(item)
        elif current and _ts(current["start"]) == item["frame_start"]:
            out.append(item)  # still running
        else:
            frame = _find_frame(watson, item["frame_start"])
            if frame is None:
                continue  # cancelled
            out.append({**item, "frame_id": frame.id})
    return out


def is_running(watson, item: dict) -> bool:
    current = watson.current
    return bool(
        not item.get("frame_id")
        and current
        and _ts(current["start"]) == item["frame_start"]
    )


def describe(watson, item: dict) -> str:
    flagged = ", ".join(item["policies"])
    project = style("project", item["project"])
    if is_running(watson, item):
        return (
            f"{project} running since {_fmt(item['frame_start'])} — flagged {flagged} "
            f"(suggested stop {_fmt(item['suggested_stop'])})"
        )
    frame = watson.frames[item["frame_id"]]
    verb = "auto-stopped" if item.get("autostopped") else "stopped"
    return f"{project} {verb} at {_fmt(_ts(frame.stop))} — flagged {flagged}"


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def parse_when(value: str, reference: arrow.Arrow) -> arrow.Arrow:
    """Parse a stop time. A bare HH:MM is taken on ``reference``'s date."""
    value = value.strip()
    tz = local_tz_info()
    if _TIME_RE.match(value):
        parts = [int(p) for p in value.split(":")]
        hour, minute, second = (parts + [0])[:3]
        try:
            return reference.to(tz).replace(
                hour=hour, minute=minute, second=second, microsecond=0
            )
        except ValueError:
            raise click.BadParameter(f"'{value}' is not a valid time") from None
    try:
        return arrow.get(value).replace(tzinfo=tz)
    except (arrow.parser.ParserError, ValueError):
        raise click.BadParameter(
            f"'{value}' is not a time (HH:MM) or date (YYYY-MM-DD HH:MM)"
        ) from None


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _remove(store: Store, keys: set[int]):
    with store.transaction() as state:
        state["reviews"] = [r for r in state["reviews"] if r["frame_start"] not in keys]


def _set_deferred(store: Store, keys: set[int]):
    with store.transaction() as state:
        for item in state["reviews"]:
            if item["frame_start"] in keys:
                item["deferred"] = True


def load(watson, store: Store | None = None) -> tuple[Store, list[dict]]:
    store = store or Store(watson.config_dir)
    state = store.read()
    reviews = reconcile(watson, state["reviews"])
    if reviews != state["reviews"]:
        with store.transaction() as fresh:
            fresh["reviews"] = reconcile(watson, fresh["reviews"])
            reviews = fresh["reviews"]
    return store, reviews


def resolve(watson, store: Store, items: list[dict]):
    """Interactively resolve each item; resolved items leave the store."""
    for item in items:
        click.echo(f"\n{describe(watson, item)}")
        if is_running(watson, item):
            suggested = _local(item["suggested_stop"])
            while True:
                answer = click.prompt(
                    "Stop it at (HH:MM or YYYY-MM-DD HH:MM; 'k' keeps it running)",
                    default=suggested.format("HH:mm"),
                )
                if answer.strip().lower() in ("k", "keep"):
                    break
                try:
                    stopped = watson.stop(stop_at=parse_when(answer, suggested))
                except (click.BadParameter, WatsonError) as e:
                    click.echo(style("error", str(e)))
                    continue
                watson.save()
                click.echo(
                    f"Stopped {style('project', stopped.project)} at "
                    f"{stopped.stop.format('ddd HH:mm')}."
                )
                break
        else:
            frame = watson.frames[item["frame_id"]]
            while True:
                answer = click.prompt(
                    "Correct stop time (HH:MM or YYYY-MM-DD HH:MM; Enter keeps "
                    f"{frame.stop.format('HH:mm')})",
                    default="",
                    show_default=False,
                )
                if not answer.strip():
                    break
                try:
                    new_stop = parse_when(answer, frame.stop)
                    if new_stop <= frame.start:
                        raise WatsonError("The stop time must be after the start.")
                    if new_stop > arrow.now():
                        raise WatsonError("The stop time can't be in the future.")
                except (click.BadParameter, WatsonError) as e:
                    click.echo(style("error", str(e)))
                    continue
                watson.frames[frame.id] = (
                    frame.project,
                    frame.start,
                    new_stop,
                    frame.tags,
                )
                watson.save()
                click.echo(f"Stop time set to {new_stop.format('ddd HH:mm')}.")
                break
        _remove(store, {item["frame_start"]})


def on_start(ctx, watson):
    """Called by `watson start` before it checks for a running frame."""
    if not _is_interactive():
        return
    store, reviews = load(watson)
    pending = [r for r in reviews if not r.get("deferred")]
    deferred = len(reviews) - len(pending)
    if not pending:
        if deferred and _remind_deferred(watson):
            click.echo(
                style(
                    "time", f"{deferred} deferred timer review(s); run `watson review`."
                )
            )
        return

    click.echo(f"{len(pending)} pending timer review(s):")
    for index, item in enumerate(pending, 1):
        click.echo(f"  {index}. {describe(watson, item)}")
    choice = click.prompt(
        "Resolve now, or defer to `watson review`?",
        type=click.Choice(["r", "d"], case_sensitive=False),
        default="r",
    )
    if choice.lower() == "d":
        _set_deferred(store, {r["frame_start"] for r in pending})
        click.echo("Deferred; run `watson review` when you're ready.")
        return
    resolve(watson, store, pending)
    click.echo("")


def _remind_deferred(watson) -> bool:
    from .settings import remind_deferred

    return remind_deferred(watson.config)


def on_stop(watson, frame):
    """Called by `watson stop`: attach the new frame id to its review."""
    store = Store(watson.config_dir)
    key = _ts(frame.start)
    if not any(
        r["frame_start"] == key and not r.get("frame_id")
        for r in store.read()["reviews"]
    ):
        return
    with store.transaction() as state:
        for item in state["reviews"]:
            if item["frame_start"] == key and not item.get("frame_id"):
                item["frame_id"] = frame.id


def status_lines(watson) -> list[str]:
    """Notices for `watson status`: pending reviews, schedule problems."""
    lines = []
    _, reviews = load(watson)
    if reviews:
        deferred = sum(1 for r in reviews if r.get("deferred"))
        text = f"{len(reviews)} pending timer review(s)"
        if deferred:
            text += f" ({deferred} deferred)"
        lines.append(f"{text}; run `watson review`.")

    from .schedule import ScheduleError, load_schedules

    try:
        lines.extend(load_schedules(watson).warnings)
    except ScheduleError as e:
        lines.append(f"Schedule error: {e}")
    return lines


def review_command(watson, list_only: bool):
    store, reviews = load(watson)
    if not reviews:
        click.echo("No pending timer reviews.")
        return
    click.echo(f"{len(reviews)} pending timer review(s):")
    for index, item in enumerate(reviews, 1):
        note = " (deferred)" if item.get("deferred") else ""
        click.echo(f"  {index}. {describe(watson, item)}{note}")
    if list_only:
        return
    resolve(watson, store, reviews)


__all__ = [
    "add_review",
    "describe",
    "load",
    "on_start",
    "on_stop",
    "parse_when",
    "reconcile",
    "resolve",
    "review_command",
    "status_lines",
]
