# Work hours, reminders and forgotten timers

This fork of Watson can:

- remind you, with a desktop notification, when no timer is running during
  your work hours;
- detect a timer you forgot to stop, warn you, stop it at the right time and
  ask you to confirm the stop time the next time you run `watson start`;
- use a temporary alternate schedule (a vacation, a shifted week);
- run on Windows and WSL against one shared data directory, with the checks
  running from Windows even while WSL is shut down.

The checks run in `watson watch`, a short command that Windows Task Scheduler
runs every few minutes. The CLI does the rest: prompts at `watson start`,
notices in `watson status`, and `watson review`.

## Setup on Windows + WSL

Both sides use the **same data directory on the Windows disk**, so the
Windows watcher keeps working while WSL is off.

1. **Windows**: install [uv](https://docs.astral.sh/uv/) (`winget install
   astral-sh.uv`), then install this fork as a tool:

        PS> uv tool install <git-url-of-this-fork>
        PS> # or, once, while WSL is running:
        PS> uv tool install \\wsl.localhost\<distro>\home\<you>\watson

    This puts `watson.exe` and `watson-watch.exe` (no console window) in
    `%USERPROFILE%\.local\bin`. Windows Watson uses `%APPDATA%\watson` as its
    data directory.

    Behind a TLS-intercepting proxy, add `--system-certs` so uv trusts the
    Windows certificate store.

2. **WSL**: point Watson at the same directory, in `~/.zshrc` (or `~/.bashrc`):

        export WATSON_DIR=/mnt/c/Users/<windows-user>/AppData/Roaming/watson

    and install the fork, editable so local changes apply right away:

        $ uv tool install -e ~/watson

3. **Check**, from either side:

        $ watson extras doctor
        $ watson extras test-toast

    `doctor` checks that the data directory is shared and writable, that the
    WSL and Windows time zones match, the notifier, the schedule, the
    policies and the scheduled task.

4. **Register the watcher**, from **Windows** (PowerShell or cmd):

        PS> watson extras install-task          # every 5 minutes and at logon
        PS> watson extras install-task --interval 2m

    The task runs only while you're logged on (notifications need your
    session). Runs missed while the PC slept happen on wake, and the
    catch-up rules below prevent a burst of stale notifications.
    `watson extras uninstall-task` removes it.

Timestamps are stored in UTC. Both sides must agree on the local time zone,
which `doctor` checks.

## Work schedule

```ini
[schedule]
workdays = mon tue wed thu fri       ; default
hours = 09:00-12:00 12:30-17:00      ; default 09:00-17:00; breaks are off-hours
holidays = 2026-12-25 2027-01-01
```

Ranges can't cross midnight; split them, e.g. `20:00-24:00 00:00-02:00`.

### Alternate schedule

One alternate schedule can override the standard one for a date range. It
lives at a fixed path, `<WATSON_DIR>/schedule-alternate.ini`:

```ini
[schedule]
start = 2026-12-21        ; inclusive, required
end = 2026-12-31          ; inclusive, required
workdays =                ; empty: no work days (vacation)
hours = 10:00-15:00
```

- For dates from `start` to `end`, it replaces the standard schedule. Keys it
  leaves out are inherited from the standard schedule.
- Outside that range it has no effect, so an expired file can stay in place.
- An `end` before `start` makes Watson warn and ignore the file.
- A missing or invalid `start`/`end`, or an unreadable file, is an error. The
  watcher then shows an error notification (at most hourly) and skips the
  schedule-dependent checks; `elapsed` policies still run.

```
$ watson schedule alternate 2026-12-21 2026-12-31 --copy-standard --edit
$ watson schedule status [--date 2026-12-24]
$ watson schedule clear
```

## No-timer reminder

```ini
[reminder]
enabled = true     ; default
grace = 10m        ; default: quiet for the first 10m of each work period
                   ; and for 10m after you stop a frame
repeat = 30m       ; default: at most one reminder every 30m
```

`watson snooze 1h`, `watson snooze today` (until midnight) and
`watson snooze off` pause and resume it.

## Forgotten-timer policies

A policy is a `[policy:NAME]` section with one **trigger** and one or more
**handlers**:

```ini
[policy:after-hours]
trigger = offhours        ; fires after `after` of consecutive off-hours time
after = 1h
stop_at = onset           ; default for offhours: stop when the off-hours run began
handlers = toast@-15m toast autostop prompt

[policy:long-task]
trigger = elapsed         ; fires when the frame is `after` old, schedule or not
after = 10h
handlers = toast@-30m autostop prompt
```

Triggers:

- `elapsed`: fires at frame start + `after`.
- `offhours`: each stretch outside work hours (an evening, a lunch break, a
  whole weekend) counts on its own. The policy fires when a single stretch
  reaches `after`; returning to work hours resets the count.

Handlers fire at the trigger's fire time plus an optional offset:

| Handler | What it does |
|---|---|
| `toast` | A notification, e.g. "'proj' has been running outside work hours since Mon 17:00. It will be stopped in 15m." |
| `autostop` | Stops the frame and tags it `auto-stopped`. Stops at the fire time, or with `stop_at = onset` (offhours only) when the off-hours run began, e.g. 17:00. A frame that itself started off-hours is stopped at the fire time, so it isn't erased. |
| `prompt` | Flags the frame for review at the next `watson start` (below). |

`toast@-15m` fires 15 minutes before the trigger, and `autostop@+10m` 10
minutes after it.

Delivery and catch-up rules:

- Each handler fires once per frame (and per off-hours stretch).
- If the PC slept through several due handlers, only the earliest `autostop`
  runs, and its own notification replaces the warnings.
- Toasts more than two polling intervals late (`[extras] poll_interval`,
  default `5m`) are dropped.
- Prompts are never dropped.

`watson watch --dry-run` shows what would happen right now without changing
anything. `watson watch` runs one real pass.

## Reviews

When a policy with `prompt` fires, the next `watson start` (in a terminal)
first lists the flagged frames and asks once:

```
1 pending timer review(s):
  1. apollo auto-stopped at Mon 2026-11-16 17:00 — flagged after-hours
Resolve now, or defer to `watson review`? (r, d) [r]:
```

- **Resolve**: for each frame, either stop a still-running frame at the
  suggested time or one you type (`HH:MM` is on the frame's day), or keep it
  running. For an auto-stopped frame, accept or correct its stop time. This
  happens before `stop_on_start` could stop a forgotten frame at "now".
- **Defer**: `watson start` won't ask about those frames again. It only
  prints a one-line notice, which `[review] remind_deferred = false` turns
  off. Resolve them later with `watson review` (`--list` only shows them).

`watson status` also mentions pending reviews and schedule problems.

## Files and troubleshooting

All of these live in the data directory, next to `frames` and `state`:

| File | Contents |
|---|---|
| `config` | Watson's config, including the sections above |
| `schedule-alternate.ini` | the alternate schedule, if any |
| `extras_state.json` | delivered notifications, pending reviews, snooze |
| `extras.lock` | held briefly during updates; treated as stale after 30s |
| `extras.log` | the watcher's log (it has no console) |

Writes are atomic (temp file + rename in the same directory), so the
Windows watcher and the WSL CLI never see a half-written file.

`[extras] notifier = auto | powershell | notify-send | stdout` picks how
notifications are shown. `auto` uses PowerShell's WinRT toasts on Windows
and WSL, `notify-send` on Linux desktops, and stdout otherwise.
