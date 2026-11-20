<img src="docs/img/logo-watson-600px.png" alt="Watson" width="300">

# Watson (fork)

**This is a fork of [Watson](https://github.com/TailorDev/Watson) by
[TailorDev](https://github.com/TailorDev) and its contributors**, a wonderful
CLI to track your time. All credit for the original tool goes to them; it is
released under the MIT License (see [LICENSE](LICENSE)).

This fork is maintained for personal use. It requires Python 3.12+ and adds:

- work-hours reminders and forgotten-timer policies (toast, auto-stop,
  review prompts)
- a temporary alternate work schedule
- `-q/--quarter`, `--prev` and `--range` report periods
- Windows and WSL support with a shared data directory

See [Work hours & forgotten timers](docs/user-guide/work-hours.md) for details.

Watson helps you manage your time: how much time are you spending on your
projects? Need a report for a client? Watson is here for you.

[![Watson screenshot](docs/img/watson-demo.gif)](https://asciinema.org/a/35918)

## Installation

Install with [uv](https://docs.astral.sh/uv/):

```bash
$ uv tool install git+https://github.com/sskeirik/watson
```

or, from a local checkout, editable:

```bash
$ git clone https://github.com/sskeirik/watson
$ uv tool install -e ./watson
```

More details, including shell completion, are in the
[documentation](docs/index.md).

## Usage

Start tracking your activity via:

```bash
$ watson start world-domination +cats
```

With this command, you have started a new **frame** for the *world-domination*
project with the *cats* tag. That's it.

Now stop tracking your world domination plan via:

```bash
$ watson stop
Project world-domination [cats] started 8 minutes ago (2016.01.27 13:00:28+0100)
```

You can log your latest working sessions (aka **frames**) with the `log`
command:

```bash
$ watson log
Tuesday 26 January 2016 (8m 32s)
      ffb2a4c  13:00 to 13:08      08m 32s   world-domination  [cats]
```

Like [`report`](docs/user-guide/commands.md#report), `log` comes with
project, tag and date filtering. To list all available commands, read the
[commands reference](docs/user-guide/commands.md) or use:

```bash
$ watson help
```

## Development

```bash
$ uv sync            # create .venv with the dev tools
$ make check         # ruff + pytest
$ make docs          # regenerate docs/user-guide/commands.md and build the site
```

Set `WATSON_DIR` to a scratch folder to avoid touching your real data.

## License

Watson is released under the MIT License. See the bundled [LICENSE](LICENSE)
file for details.
