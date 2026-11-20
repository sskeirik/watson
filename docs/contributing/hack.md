# Hack

Ready to contribute? Here's how to set up *Watson* for local development.

## Requirements

* [uv](https://docs.astral.sh/uv/). It installs a suitable Python (3.12+)
  itself if needed.

## Get started!

1. Clone the repository and create the development environment:

        $ git clone <repository-url> watson
        $ cd watson
        $ uv sync

    `uv sync` creates `.venv` with Watson installed in editable mode plus the
    `dev` dependency group (pytest, ruff).

2. Run your working copy without touching your real data:

        $ export WATSON_DIR="$PWD/data"
        $ uv run watson projects

3. Create a branch, make your changes, then check them:

        $ make check            # ruff check + pytest

    To test another Python version: `uv run --python 3.14 pytest`.

4. If you added a command or changed docstrings, regenerate the docs:

        $ make docs

## Run the tests

    $ uv run pytest                 # all tests
    $ uv run pytest tests/extras    # one directory
    $ uv run ruff check watson/ tests/ scripts/
    $ uv run ruff format watson/ tests/ scripts/

Formatting commits are listed in `.git-blame-ignore-revs`; enable that with
`git config blame.ignoreRevsFile .git-blame-ignore-revs`.
