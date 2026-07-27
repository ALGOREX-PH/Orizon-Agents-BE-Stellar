# Local dev loop — mirrors what CI runs. `make check` before pushing.
PY := .venv/bin/python

.PHONY: lint format type test cov check

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff format .

type:
	.venv/bin/mypy

test:
	$(PY) -m pytest -q

cov:
	$(PY) -m pytest -q --cov

check: lint type cov
	.venv/bin/ruff format --check .
