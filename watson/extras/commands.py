"""CLI commands for the extras: watch, review, snooze, schedule, extras."""

from __future__ import annotations

import datetime

import click

from ..utils import style


def _catch(func):
    """Turn extras errors into clean CLI errors."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from ..watson import WatsonError
        from .schedule import ScheduleError
        from .settings import SettingsError
        from .store import LockTimeout

        try:
            return func(*args, **kwargs)
        except (click.exceptions.Abort, click.ClickException):
            raise  # click's own (Abort is a RuntimeError subclass)
        except (
            ScheduleError,
            SettingsError,
            LockTimeout,
            WatsonError,
            RuntimeError,
        ) as e:
            raise click.ClickException(style("error", str(e))) from None

    return wrapper


@click.command()
@click.option(
    "--once/--loop", default=True, help="Run one pass (default) or keep running."
)
@click.option(
    "--interval",
    default=None,
    help="With --loop: time between passes, e.g. 1m (default: [extras] poll_interval).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would happen without stopping frames or recording anything.",
)
@click.pass_obj
@_catch
def watch(watson, once, interval, dry_run):
    """
    Check the no-timer reminder and the forgotten-timer policies.

    On Windows, `watson extras install-task` runs this every few minutes
    through Task Scheduler. Run it by hand with `--dry-run` to see what the
    policies would do right now.
    """
    from .settings import parse_duration, poll_interval
    from .watch import run_once, setup_file_logging, watch_loop

    setup_file_logging(watson.config_dir)
    if once:
        lines = run_once(config_dir=watson.config_dir, dry_run=dry_run)
        for line in lines:
            click.echo(line)
        if not lines:
            click.echo("Nothing to do.")
        return
    seconds = (
        parse_duration(interval) if interval else poll_interval(watson.config)
    ).total_seconds()
    watch_loop(watson.config_dir, seconds, dry_run)


@click.command()
@click.option(
    "--list", "list_only", is_flag=True, help="Only list the pending reviews."
)
@click.pass_obj
@_catch
def review(watson, list_only):
    """
    Review frames flagged by forgotten-timer policies.

    Lists every pending review, including the ones deferred at `watson
    start`, and lets you stop a still-running frame at the right time or
    correct an auto-stopped frame's stop time.
    """
    from .review import review_command

    review_command(watson, list_only)


@click.command()
@click.argument("duration", required=False)
@click.pass_obj
@_catch
def snooze(watson, duration):
    """
    Pause the "no timer running" reminder.

    DURATION is e.g. `1h`, `90m`, `today` (until midnight) or `off`. Without
    it, show the current snooze.
    """
    from .store import Store
    from .watch import snooze_until

    store = Store(watson.config_dir)
    if duration is None:
        until = store.read().get("snooze_until")
        now = datetime.datetime.now().timestamp()
        if until and until > now:
            click.echo(f"Reminders snoozed until {_fmt_ts(until)}.")
        else:
            click.echo("Reminders are not snoozed.")
        return
    until = snooze_until(duration)
    with store.transaction() as state:
        state["snooze_until"] = until
    if until is None:
        click.echo("Reminders resumed.")
    else:
        click.echo(f"Reminders snoozed until {_fmt_ts(until)}.")


def _fmt_ts(ts: int) -> str:
    import arrow

    from ..timezone import local_tz_info

    return arrow.get(ts).to(local_tz_info()).format("ddd YYYY-MM-DD HH:mm")


@click.group()
def schedule():
    """Show the work schedule, or set a temporary alternate one."""


@schedule.command(name="status")
@click.option(
    "--date",
    "day",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="The day to explain (default: today).",
)
@click.pass_obj
@_catch
def schedule_status(watson, day):
    """Show which schedule applies, and why."""
    import os

    from .schedule import alternate_path, load_schedules

    schedules = load_schedules(watson)
    for warning in schedules.warnings:
        click.echo(style("error", f"warning: {warning}"), err=True)
    day = day.date() if day else datetime.date.today()
    click.echo(schedules.explain(day))
    click.echo(f"standard: {schedules.standard.describe()}")
    if schedules.alternate:
        alt = schedules.alternate
        click.echo(f"alternate: {alt.start} to {alt.end}: {alt.schedule.describe()}")
    elif not os.path.exists(alternate_path(watson.config_dir)):
        click.echo("alternate: none")


@schedule.command(name="alternate")
@click.argument("start", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("end", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option(
    "--copy-standard",
    is_flag=True,
    help="Start from the standard schedule's values (else keys are inherited).",
)
@click.option(
    "--edit", "edit_", is_flag=True, help="Open the file in $EDITOR afterwards."
)
@click.option("--force", is_flag=True, help="Replace an existing alternate schedule.")
@click.pass_obj
@_catch
def schedule_alternate(watson, start, end, copy_standard, edit_, force):
    """
    Set an alternate schedule from START to END (YYYY-MM-DD, inclusive).

    It replaces the standard schedule on those days. Edit the file it writes
    (shown below) to change the days or hours; an empty `workdays =` means
    no work days at all, e.g. for a vacation.
    """
    import os

    from .schedule import alternate_path, load_schedules, write_alternate

    if end < start:
        raise click.BadParameter("END is before START", param_hint="END")
    path = alternate_path(watson.config_dir)
    if os.path.exists(path) and not force:
        raise click.ClickException(
            f"{path} already exists; use --force to replace it or "
            "`watson schedule clear` first"
        )
    standard = load_schedules(watson).standard if copy_standard else None
    path = write_alternate(watson.config_dir, start.date(), end.date(), standard)
    if edit_:
        click.edit(filename=path)
    click.echo(f"Alternate schedule written to {path}")
    click.echo(load_schedules(watson).explain(datetime.date.today()))


@schedule.command(name="clear")
@click.pass_obj
@_catch
def schedule_clear(watson):
    """Remove the alternate schedule."""
    import os

    from .schedule import alternate_path

    path = alternate_path(watson.config_dir)
    if not os.path.exists(path):
        click.echo("No alternate schedule.")
        return
    os.remove(path)
    click.echo(f"Removed {path}")


@click.group()
def extras():
    """Set up and check reminders and forgotten-timer policies."""


@extras.command(name="install-task")
@click.option(
    "--interval", default="5m", show_default=True, help="How often the watcher runs."
)
@_catch
def install_task(interval):
    """Register the watcher with Windows Task Scheduler (run on Windows)."""
    from .settings import parse_duration
    from .winsetup import install_task as install

    minutes = max(1, int(parse_duration(interval).total_seconds() // 60))
    click.echo(install(minutes))


@extras.command(name="uninstall-task")
@_catch
def uninstall_task():
    """Remove the watcher from Windows Task Scheduler (run on Windows)."""
    from .winsetup import uninstall_task as uninstall

    click.echo(uninstall())


@extras.command(name="test-toast")
@click.argument("message", required=False, default="Toasts are working.")
@click.pass_obj
@_catch
def test_toast(watson, message):
    """Show a test notification with the configured notifier."""
    from .notify import get_notifier
    from .settings import notifier_name

    notifier = get_notifier(notifier_name(watson.config))
    if notifier.notify(message):
        click.echo(f"Sent with {notifier.name}.")
    else:
        raise click.ClickException(
            f"{notifier.name} failed; see {watson.config_dir}/extras.log"
        )


@extras.command()
@click.pass_obj
@_catch
def doctor(watson):
    """Check the data directory, time zone, notifier, schedule and task."""
    from .doctor import FAIL, OK, checks

    colors = {OK: "green", FAIL: "red"}
    failed = False
    for level, message in checks(watson):
        failed |= level == FAIL
        label = click.style(f"[{level:>4}]", fg=colors.get(level, "yellow"))
        click.echo(f"{label} {message}")
    if failed:
        raise SystemExit(1)


def register(cli):
    for command in (watch, review, snooze, schedule, extras):
        cli.add_command(command)
