.PHONY: help install lint format format-check typecheck check test test-unit test-contract compose-config compose-up compose-down

help:
	@echo "install         Install development dependencies"
	@echo "lint            Run Ruff checks"
	@echo "format          Format Python files"
	@echo "format-check    Check Python formatting"
	@echo "typecheck       Run strict mypy"
	@echo "check           Run the authoritative offline quality commands"
	@echo "test            Run offline unit and contract tests"
	@echo "test-unit       Run unit tests with network disabled"
	@echo "test-contract   Run contract tests with network disabled"
	@echo "compose-config  Validate the local infrastructure definition"
	@echo "compose-up      Start local infrastructure"
	@echo "compose-down    Stop local infrastructure"

install:
	python -c "raise SystemExit('ME-000A BLOCK: dependency installation is not approved')"

lint:
	python -m ruff check .

format:
	python -m ruff format .

format-check:
	python -m ruff format --check .

typecheck:
	python -m mypy src

test:
	python -m pytest tests/unit tests/contract --disable-socket

test-unit:
	python -m pytest tests/unit --disable-socket

test-contract:
	python -m pytest tests/contract --disable-socket

check:
	python -m ruff check .
	python -m ruff format --check .
	python -m mypy src
	python -m pytest tests/unit tests/contract --disable-socket

compose-config:
	docker compose --env-file .env.example config

compose-up:
	docker compose up -d

compose-down:
	docker compose down
