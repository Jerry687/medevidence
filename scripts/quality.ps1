[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repositoryRoot
try {
    & uv run --locked --no-sync ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff lint failed."
    }

    & uv run --locked --no-sync ruff format --check .
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff format check failed."
    }

    & uv run --locked --no-sync mypy src
    if ($LASTEXITCODE -ne 0) {
        throw "mypy failed."
    }

    & uv run --locked --no-sync pytest `
        tests/unit tests/contract `
        --disable-socket `
        --cov=medevidence `
        --cov-report=term-missing `
        --cov-report=xml
    if ($LASTEXITCODE -ne 0) {
        throw "The offline unit and contract test gate failed."
    }
}
finally {
    Pop-Location
}
