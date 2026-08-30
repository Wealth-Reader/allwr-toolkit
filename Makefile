PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup format lint type-check test security docs build check clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e '.[dev,mcp]'
	$(BIN)/pre-commit install

format:
	$(BIN)/ruff format src tests scripts
	$(BIN)/ruff check --fix src tests scripts

lint:
	$(BIN)/ruff format --check src tests scripts
	$(BIN)/ruff check src tests scripts
	$(BIN)/python scripts/validate_repository_language.py

type-check:
	$(BIN)/mypy

test:
	$(BIN)/pytest

security:
	$(BIN)/bandit -c pyproject.toml -r src scripts
	$(BIN)/python scripts/audit_publication.py

docs:
	$(BIN)/mkdocs build --strict

build:
	rm -rf dist
	$(BIN)/python -m build
	$(BIN)/twine check dist/*

check: lint type-check test security docs build
	@echo "All checks passed."

clean:
	rm -rf dist build site .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml
