# Watson — thin wrappers around uv. Run `uv sync` once to create .venv.

.PHONY: all
all: check

.PHONY: check
check:
	uv run ruff check watson/ tests/ scripts/
	uv run pytest

.PHONY: build
build:
	uv build

.PHONY: docs
docs:
	uv run --group docs scripts/gen-cli-docs.py
	uv run --group docs mkdocs build

.PHONY: completion-scripts
completion-scripts:
	uv run scripts/create-completion-script.sh bash
	uv run scripts/create-completion-script.sh zsh

.PHONY: clean
clean:
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d | xargs rm -fr
	rm -rf dist/ site/
