[CmdletBinding()]
param(
    [string]$EnvFile = ".env",
    [switch]$Template
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1") -Quiet

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $repositoryRoot ".env.example"
$placeholderPassword = "replace-with-a-strong-local-password"
$approvedPostgresImage = "docker.io/library/postgres:18.4-bookworm@" +
    "sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296"
$approvedQdrantImage = "docker.io/qdrant/qdrant:v1.18.3-unprivileged@" +
    "sha256:affb67e1d6f2f93d7d20b90d238a7d4b974d36351c162e73bda794e4b2e03483"
$requiredKeys = @(
    "POSTGRES_IMAGE",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "QDRANT_IMAGE",
    "QDRANT_HTTP_PORT",
    "QDRANT_GRPC_PORT"
)

function Resolve-InputPath {
    param([string]$Path)

    $candidate = $Path
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $repositoryRoot $candidate
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Environment file does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $candidate).ProviderPath
}

function Test-SamePath {
    param(
        [string]$Left,
        [string]$Right
    )

    $comparison = [StringComparison]::Ordinal
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $comparison = [StringComparison]::OrdinalIgnoreCase
    }
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left),
        [IO.Path]::GetFullPath($Right),
        $comparison
    )
}

function Read-EnvironmentFile {
    param([string]$Path)

    $values = @{}
    $lineNumber = 0
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        $lineNumber += 1
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($line -notmatch "^([^=]+)=(.*)$") {
            throw "Invalid environment assignment at line $lineNumber."
        }

        $key = $Matches[1].Trim()
        $value = $Matches[2]
        if ($key -notmatch "^[A-Z][A-Z0-9_]*$") {
            throw "Invalid environment variable name at line $lineNumber."
        }
        if ($requiredKeys -notcontains $key) {
            throw "Unknown environment variable: $key"
        }
        if ($values.ContainsKey($key)) {
            throw "Duplicate environment variable: $key"
        }
        if ($value -cne $value.Trim()) {
            throw "Environment variable $key has leading or trailing whitespace."
        }
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Environment variable $key is blank."
        }
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            throw "Environment variable $key must use an unquoted value."
        }
        $values[$key] = $value
    }
    return $values
}

function ConvertTo-ValidatedPort {
    param(
        [hashtable]$Values,
        [string]$Key
    )

    $value = $Values[$Key]
    if ($value -notmatch "^[0-9]+$") {
        throw "Environment variable $Key must be a decimal port."
    }
    $port = 0
    if (-not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "Environment variable $Key must be between 1 and 65535."
    }
    return $port
}

$resolvedEnvFile = Resolve-InputPath -Path $EnvFile
$resolvedTemplatePath = (Resolve-Path -LiteralPath $templatePath).ProviderPath
if ($Template -and -not (Test-SamePath -Left $resolvedEnvFile -Right $resolvedTemplatePath)) {
    throw "-Template is valid only for the repository-root .env.example."
}

$environment = Read-EnvironmentFile -Path $resolvedEnvFile
foreach ($key in $requiredKeys) {
    if (-not $environment.ContainsKey($key)) {
        throw "Missing required environment variable: $key"
    }
}

if ($environment["POSTGRES_IMAGE"] -cne $approvedPostgresImage) {
    throw "POSTGRES_IMAGE is not the approved image reference."
}
if ($environment["QDRANT_IMAGE"] -cne $approvedQdrantImage) {
    throw "QDRANT_IMAGE is not the approved image reference."
}
foreach ($key in @("POSTGRES_DB", "POSTGRES_USER")) {
    if ($environment[$key] -notmatch "^[A-Za-z_][A-Za-z0-9_]{0,62}$") {
        throw "Environment variable $key is not a safe PostgreSQL identifier."
    }
}
if (-not $Template -and $environment["POSTGRES_PASSWORD"] -ceq $placeholderPassword) {
    throw "POSTGRES_PASSWORD still uses the committed placeholder."
}

$ports = @(
    ConvertTo-ValidatedPort -Values $environment -Key "POSTGRES_PORT"
    ConvertTo-ValidatedPort -Values $environment -Key "QDRANT_HTTP_PORT"
    ConvertTo-ValidatedPort -Values $environment -Key "QDRANT_GRPC_PORT"
)
if (($ports | Sort-Object -Unique).Count -ne $ports.Count) {
    throw "POSTGRES_PORT, QDRANT_HTTP_PORT, and QDRANT_GRPC_PORT must be distinct."
}

$mode = if ($Template) { "template" } else { "runtime" }
Write-Output "Environment contract valid in $mode mode."
