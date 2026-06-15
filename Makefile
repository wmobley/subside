# SUBSIDE dev tasks. Lint parity across both stacks:
#   make lint      -> Python service + automation + analysis (ruff; config in pyproject.toml)
#   make lint-ui   -> React UI (eslint; config in ui/eslint.config.js)
#   make lint-all  -> both
#   make test      -> FAST unit tests (analysis/tests), the GitHub Actions gate
#   make test-ls6  -> whole-flow tests needing real data/compute (ls6 idev only)
#
# Python tooling lives in the local venv by default; override with e.g.
#   make lint RUFF=ruff      (when ruff is already on PATH / in the active env, e.g. CI)
RUFF ?= .venv/bin/ruff
PYTEST ?= .venv/bin/pytest

.PHONY: lint lint-ui lint-all test test-ls6

lint:
	$(RUFF) check api tapis analysis

lint-ui:
	cd ui && npm run lint

lint-all: lint lint-ui

# Fast, hermetic unit tests on synthetic data — no network/data/compute.
test:
	$(PYTEST) -m "not ls6 and not integration"

# Whole-flow tests (real OPERA products, full pipeline). Run on ls6 via ./test.sh.
test-ls6:
	$(PYTEST) -m ls6
