# Local dev loop — mirrors what CI runs. `make check` before pushing.
PY := .venv/bin/python

.PHONY: lint format type test check

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff format .

type:
	.venv/bin/mypy

test:
	$(PY) -m pytest -q

check: lint type test
	.venv/bin/ruff format --check .
