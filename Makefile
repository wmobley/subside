# SUBSIDE dev tasks. Lint parity across both stacks:
#   make lint      -> Python service + automation + analysis (ruff; config in pyproject.toml)
#   make lint-ui   -> React UI (eslint; config in ui/eslint.config.js)
#   make lint-all  -> both
#
# Python tooling lives in the local venv by default; override with e.g.
#   make lint RUFF=ruff      (when ruff is already on PATH / in the active env, e.g. CI)
RUFF ?= .venv/bin/ruff

.PHONY: lint lint-ui lint-all

lint:
	$(RUFF) check api tapis analysis

lint-ui:
	cd ui && npm run lint

lint-all: lint lint-ui
