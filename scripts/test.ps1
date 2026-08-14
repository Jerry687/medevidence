[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1") -Quiet

$repositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repositoryRoot
try {
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
