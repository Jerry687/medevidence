[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$expectedUvVersion = "0.11.32"
$expectedPythonVersion = "3.12.13"
$repositoryRoot = Split-Path -Parent $PSScriptRoot

$uvCommand = Get-Command uv -ErrorAction Stop
$uvVersionOutput = & $uvCommand.Source --version
if ($LASTEXITCODE -ne 0) {
    throw "Unable to determine the installed uv version."
}

$actualUvVersion = ($uvVersionOutput -split "\s+")[1]
if ($actualUvVersion -ne $expectedUvVersion) {
    throw "uv $expectedUvVersion is required; found $actualUvVersion."
}

Push-Location $repositoryRoot
try {
    & $uvCommand.Source python install $expectedPythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not install CPython $expectedPythonVersion."
    }

    & $uvCommand.Source sync --locked --group dev
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed."
    }

    $virtualEnvironmentPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $virtualEnvironmentPython -PathType Leaf)) {
        throw "The repository-local virtual environment was not created."
    }

    $actualPythonVersion = & $virtualEnvironmentPython -c (
        "import platform; print(platform.python_version())"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to determine the repository Python version."
    }
    if ($actualPythonVersion -ne $expectedPythonVersion) {
        throw "CPython $expectedPythonVersion is required; found $actualPythonVersion."
    }

    Write-Output "Bootstrap complete: uv $actualUvVersion, CPython $actualPythonVersion."
}
finally {
    Pop-Location
}
