.PHONY: help install lint format format-check typecheck quality check test test-unit test-contract infrastructure-contract compose-config compose-smoke compose-up compose-down

help:
	@echo "install         Install development dependencies"
	@echo "lint            Run Ruff checks"
	@echo "format          Format Python files"
	@echo "format-check    Check Python formatting"
	@echo "typecheck       Run strict mypy"
	@echo "quality         Run the authoritative offline quality commands"
	@echo "check           Alias for quality"
	@echo "test            Run offline unit and contract tests"
	@echo "test-unit       Run unit tests with network disabled"
	@echo "test-contract   Run contract tests with network disabled"
	@echo "infrastructure-contract  Test environment and Compose contracts"
	@echo "compose-config  Validate the local infrastructure definition"
	@echo "compose-smoke   Run and clean an isolated infrastructure smoke test"
	@echo "compose-up      Start local infrastructure"
	@echo "compose-down    Stop local infrastructure"

install:
	pwsh -NoLogo -NoProfile -File ./scripts/bootstrap.ps1

lint:
	uv run --locked --no-sync ruff check .

format:
	uv run --locked --no-sync ruff format .

format-check:
	uv run --locked --no-sync ruff format --check .

typecheck:
	uv run --locked --no-sync mypy src

test:
	uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml

test-unit:
	uv run --locked --no-sync pytest tests/unit --disable-socket

test-contract:
	uv run --locked --no-sync pytest tests/contract --disable-socket

quality:
	uv run --locked --no-sync ruff check .
	uv run --locked --no-sync ruff format --check .
	uv run --locked --no-sync mypy src
	uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml

check: quality

infrastructure-contract:
	pwsh -NoLogo -NoProfile -File ./scripts/test-infrastructure-contract.ps1

compose-config:
	pwsh -NoLogo -NoProfile -File ./scripts/validate-compose.ps1 -EnvFile ./.env.example -Template

compose-smoke:
	pwsh -NoLogo -NoProfile -File ./scripts/smoke-compose.ps1

compose-up:
	pwsh -NoLogo -NoProfile -File ./scripts/validate-compose.ps1 -EnvFile ./.env
	docker compose --env-file .env up -d --wait

compose-down:
	docker compose --env-file .env down
