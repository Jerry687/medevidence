[CmdletBinding()]
param(
    # Intended for deterministic safety tests. Normal invocations omit this value.
    [ValidatePattern("^[a-z0-9][a-z0-9_-]{0,62}$")]
    [string]$ProjectName,
    [string]$ComposeFile = "docker-compose.yml"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1") -Quiet

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeCandidate = $ComposeFile
if (-not [IO.Path]::IsPathRooted($composeCandidate)) {
    $composeCandidate = Join-Path $repositoryRoot $composeCandidate
}
if (-not (Test-Path -LiteralPath $composeCandidate -PathType Leaf)) {
    throw "Required file does not exist: $ComposeFile"
}
$composePath = (Resolve-Path -LiteralPath $composeCandidate).ProviderPath
$composeValidator = Join-Path $PSScriptRoot "validate-compose.ps1"
& $composeValidator -ComposeFile $composePath -SourceOnly | Out-Null
try {
    $dockerCommand = Get-Command docker `
        -CommandType Application `
        -ErrorAction Stop |
            Select-Object -First 1
}
catch {
    throw "Docker command is unavailable."
}
$dockerExecutable = [string]$dockerCommand.Source
if (
    -not [IO.Path]::IsPathRooted($dockerExecutable) -or
    -not (Test-Path -LiteralPath $dockerExecutable -PathType Leaf)
) {
    throw "Docker command is unavailable."
}

$templatePath = Join-Path $repositoryRoot ".env.example"
$approvedPostgresImage = "docker.io/library/postgres:18.4-bookworm@" +
    "sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296"
$approvedQdrantImage = "docker.io/qdrant/qdrant:v1.18.3-unprivileged@" +
    "sha256:affb67e1d6f2f93d7d20b90d238a7d4b974d36351c162e73bda794e4b2e03483"
$environmentKeys = @(
    "POSTGRES_IMAGE",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "QDRANT_IMAGE",
    "QDRANT_HTTP_PORT",
    "QDRANT_GRPC_PORT"
)
$composeProjectName = $ProjectName
if ([string]::IsNullOrWhiteSpace($composeProjectName)) {
    $composeProjectName = "medevidence-smoke-$PID-$([guid]::NewGuid().ToString('N'))"
}
$savedEnvironment = $null
$cleanupError = $null
$cleanupAuthorized = $false
$started = $false

function New-RandomPassword {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

if (-not ("MedEvidenceProcessEnvironmentNative" -as [type])) {
    $null = Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;

public static class MedEvidenceProcessEnvironmentNative
{
    [DllImport(
        "kernel32.dll",
        CharSet = CharSet.Unicode,
        EntryPoint = "SetEnvironmentVariableW",
        SetLastError = true
    )]
    public static extern bool SetWindowsVariable(string name, string value);

    [DllImport("libc", EntryPoint = "setenv", SetLastError = true)]
    public static extern int SetUnixVariable(string name, string value, int overwrite);
}
'@
}

function Get-ProcessEnvironmentEntry {
    param([string]$Name)

    $processEnvironment = [Environment]::GetEnvironmentVariables(
        [EnvironmentVariableTarget]::Process
    )
    foreach ($entry in $processEnvironment.GetEnumerator()) {
        if ([string]$entry.Key -ceq $Name) {
            return [pscustomobject]@{
                Exists = $true
                Value = [string]$entry.Value
            }
        }
    }
    return [pscustomobject]@{
        Exists = $false
        Value = $null
    }
}

function Get-ProcessEnvironmentSnapshot {
    param([string[]]$Names)

    $snapshot = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($name in $Names) {
        $snapshot.Add($name, (Get-ProcessEnvironmentEntry -Name $name))
    }
    return ,$snapshot
}

function Remove-ProcessEnvironmentVariable {
    param([string]$Name)

    Remove-Item -LiteralPath "Env:$Name" -Force -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable(
        $Name,
        [NullString]::Value,
        [EnvironmentVariableTarget]::Process
    )
    $actual = Get-ProcessEnvironmentEntry -Name $Name
    if ($actual.Exists) {
        throw "Unable to remove process environment variable $Name."
    }
}

function Set-ProcessEnvironmentValue {
    param(
        [string]$Name,
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        [EnvironmentVariableTarget]::Process
    )
    $actual = Get-ProcessEnvironmentEntry -Name $Name
    if (
        $Value.Length -eq 0 -and
        (-not $actual.Exists -or [string]$actual.Value -cne "")
    ) {
        $succeeded = if (
            [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
        ) {
            [MedEvidenceProcessEnvironmentNative]::SetWindowsVariable($Name, "")
        }
        else {
            [MedEvidenceProcessEnvironmentNative]::SetUnixVariable($Name, "", 1) -eq 0
        }
        if (-not $succeeded) {
            throw "Unable to set an empty process environment variable $Name."
        }
        $actual = Get-ProcessEnvironmentEntry -Name $Name
    }
    if (-not $actual.Exists -or [string]$actual.Value -cne $Value) {
        throw "Unable to restore process environment variable $Name."
    }
}

function Restore-ProcessEnvironment {
    param([Collections.Generic.Dictionary[string, object]]$Snapshot)

    foreach ($name in $Snapshot.Keys) {
        $original = $Snapshot[$name]
        if ($original.Exists) {
            Set-ProcessEnvironmentValue -Name $name -Value ([string]$original.Value)
        }
        else {
            Remove-ProcessEnvironmentVariable -Name $name
        }
    }
}

function Assert-ProcessEnvironmentMatchesSnapshot {
    param([Collections.Generic.Dictionary[string, object]]$Snapshot)

    foreach ($name in $Snapshot.Keys) {
        $original = $Snapshot[$name]
        $actual = Get-ProcessEnvironmentEntry -Name $name
        if ($actual.Exists -ne [bool]$original.Exists) {
            throw "Process environment variable $name existence was not restored."
        }
        if ($actual.Exists -and [string]$actual.Value -cne [string]$original.Value) {
            throw "Process environment variable $name value was not restored."
        }
    }
}

function Set-RuntimeEnvironment {
    param([hashtable]$Values)

    foreach ($key in $environmentKeys) {
        Set-ProcessEnvironmentValue `
            -Name $key `
            -Value ([string]$Values[$key])
    }
}

function Assert-RuntimeEnvironmentContainsExactKeys {
    $processEnvironment = [Environment]::GetEnvironmentVariables(
        [EnvironmentVariableTarget]::Process
    )
    $actualKeys = @(
        $processEnvironment.Keys |
            ForEach-Object { [string]$_ } |
            Where-Object { $_ -cin $environmentKeys } |
            Sort-Object
    )
    $expectedKeys = @($environmentKeys | Sort-Object)
    if (
        $actualKeys.Count -ne $expectedKeys.Count -or
        ($actualKeys -join "`n") -cne ($expectedKeys -join "`n")
    ) {
        throw "Runtime infrastructure environment does not contain the exact approved keys."
    }
}

function Get-AvailableLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Get-DistinctLoopbackPorts {
    $ports = [Collections.Generic.HashSet[int]]::new()
    while ($ports.Count -lt 3) {
        $null = $ports.Add((Get-AvailableLoopbackPort))
    }
    return @($ports)
}

function Invoke-Compose {
    param(
        [string[]]$Arguments,
        [switch]$Capture
    )

    $baseArguments = @(
        "compose",
        "--project-name", $composeProjectName,
        "--env-file", $templatePath,
        "--file", $composePath
    )
    if ($Capture) {
        $output = @(& $dockerExecutable @baseArguments @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose command failed."
        }
        return @($output | ForEach-Object { $_.ToString() })
    }

    & $dockerExecutable @baseArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed."
    }
}

function Get-ProjectResources {
    param([ValidateSet("container", "network", "volume")][string]$Type)

    $label = "label=com.docker.compose.project=$composeProjectName"
    switch ($Type) {
        "container" {
            $output = @(& $dockerExecutable ps --all --quiet --filter $label 2>&1)
        }
        "network" {
            $output = @(& $dockerExecutable network ls --quiet --filter $label 2>&1)
        }
        "volume" {
            $output = @(& $dockerExecutable volume ls --quiet --filter $label 2>&1)
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect project-labelled $Type resources."
    }
    return @($output | ForEach-Object { $_.ToString() } | Where-Object { $_.Length -gt 0 })
}

function Remove-ProjectResources {
    $containers = @(Get-ProjectResources -Type container)
    if ($containers.Count -gt 0) {
        $null = & $dockerExecutable rm --force @containers 2>&1
    }
    $networks = @(Get-ProjectResources -Type network)
    if ($networks.Count -gt 0) {
        $null = & $dockerExecutable network rm @networks 2>&1
    }
    $volumes = @(Get-ProjectResources -Type volume)
    if ($volumes.Count -gt 0) {
        $null = & $dockerExecutable volume rm --force @volumes 2>&1
    }
}

function Get-ServiceContainerId {
    param([string]$Service)

    $output = @(Invoke-Compose -Arguments @("ps", "--quiet", $Service) -Capture)
    if ($output.Count -ne 1 -or [string]::IsNullOrWhiteSpace($output[0])) {
        throw "Expected exactly one running $Service container."
    }
    return $output[0]
}

function Assert-ContainerImage {
    param(
        [string]$ContainerId,
        [string]$ExpectedImage,
        [string]$Service
    )

    $configuredImage = @(
        & $dockerExecutable inspect --format "{{.Config.Image}}" $ContainerId 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or $configuredImage.Count -ne 1) {
        throw "Unable to inspect the $Service container image."
    }
    if ([string]$configuredImage[0] -cne $ExpectedImage) {
        throw "The $Service container does not use the approved image digest."
    }

    $imageId = @(& $dockerExecutable inspect --format "{{.Image}}" $ContainerId 2>&1)
    if ($LASTEXITCODE -ne 0 -or $imageId.Count -ne 1) {
        throw "Unable to inspect the $Service container image identity."
    }
    $repoDigestOutput = @(
        & $dockerExecutable image inspect `
            --format "{{json .RepoDigests}}" $imageId[0] 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or $repoDigestOutput.Count -ne 1) {
        throw "Unable to inspect the $Service repository digests."
    }
    $repoDigests = @(([string]$repoDigestOutput[0]) | ConvertFrom-Json)
    $expectedDigest = $ExpectedImage.Substring($ExpectedImage.IndexOf("@") + 1)
    $digestMatches = @($repoDigests | Where-Object { $_.EndsWith("@$expectedDigest") })
    if ($digestMatches.Count -eq 0) {
        throw "The $Service image content does not expose the approved repository digest."
    }
}

function Assert-PortBindings {
    param(
        [string]$ContainerId,
        [hashtable]$Expected
    )

    $output = @(
        & $dockerExecutable inspect `
            --format "{{json .NetworkSettings.Ports}}" $ContainerId 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or $output.Count -ne 1) {
        throw "Unable to inspect container port bindings."
    }
    $bindings = ([string]$output[0]) | ConvertFrom-Json
    $actualKeys = @($bindings.PSObject.Properties.Name | Sort-Object)
    $expectedKeys = @($Expected.Keys | Sort-Object)
    if (($actualKeys -join ",") -cne ($expectedKeys -join ",")) {
        throw "Container port bindings do not match the approved contract."
    }
    foreach ($containerPort in $expectedKeys) {
        $entries = @($bindings.PSObject.Properties[$containerPort].Value)
        if (
            $entries.Count -ne 1 -or
            [string]$entries[0].HostIp -cne "127.0.0.1" -or
            [int]$entries[0].HostPort -ne [int]$Expected[$containerPort]
        ) {
            throw "Container port $containerPort is not bound to the expected loopback port."
        }
    }
}

$ports = @(Get-DistinctLoopbackPorts)
$runtimeEnvironment = @{
    POSTGRES_IMAGE = $approvedPostgresImage
    POSTGRES_DB = "medevidence"
    POSTGRES_USER = "medevidence"
    POSTGRES_PASSWORD = New-RandomPassword
    POSTGRES_PORT = [string]$ports[0]
    QDRANT_IMAGE = $approvedQdrantImage
    QDRANT_HTTP_PORT = [string]$ports[1]
    QDRANT_GRPC_PORT = [string]$ports[2]
}

$savedEnvironment = Get-ProcessEnvironmentSnapshot -Names $environmentKeys

try {
    $preExistingContainers = @(Get-ProjectResources -Type container)
    $preExistingNetworks = @(Get-ProjectResources -Type network)
    $preExistingVolumes = @(Get-ProjectResources -Type volume)
    if (
        $preExistingContainers.Count -ne 0 -or
        $preExistingNetworks.Count -ne 0 -or
        $preExistingVolumes.Count -ne 0
    ) {
        throw "The isolated Compose project name unexpectedly already exists."
    }

    $cleanupAuthorized = $true
    Set-RuntimeEnvironment -Values $runtimeEnvironment
    Assert-RuntimeEnvironmentContainsExactKeys

    & $composeValidator `
        -EnvFile $templatePath `
        -ComposeFile $composePath `
        -Template | Out-Null

    Write-Output "Validating isolated Compose runtime configuration."
    Invoke-Compose -Arguments @("config", "--quiet")

    Write-Output "Starting isolated Compose project $composeProjectName."
    Invoke-Compose -Arguments @("up", "-d", "--wait", "--wait-timeout", "180")
    $started = $true

    $postgresContainer = Get-ServiceContainerId -Service "postgres"
    $qdrantContainer = Get-ServiceContainerId -Service "qdrant"
    Assert-ContainerImage -ContainerId $postgresContainer `
        -ExpectedImage $approvedPostgresImage -Service "postgres"
    Assert-ContainerImage -ContainerId $qdrantContainer `
        -ExpectedImage $approvedQdrantImage -Service "qdrant"

    $bashCheck = @(
        Invoke-Compose -Arguments @(
            "exec", "-T", "qdrant", "bash", "-c", "command -v bash >/dev/null"
        ) -Capture
    )
    $qdrantHealth = @(
        & $dockerExecutable inspect `
            --format "{{.State.Health.Status}}" $qdrantContainer 2>&1
    )
    if ($LASTEXITCODE -ne 0 -or $qdrantHealth.Count -ne 1 -or $qdrantHealth[0] -cne "healthy") {
        throw "The required Qdrant Bash health check did not succeed."
    }
    Write-Output "Qdrant Bash health check verified."

    $postgresVersionOutput = @(
        Invoke-Compose -Arguments @(
            "exec", "-T", "postgres", "psql",
            "--username", "medevidence",
            "--dbname", "medevidence",
            "--tuples-only", "--no-align",
            "--command", "SHOW server_version;"
        ) -Capture
    )
    $postgresVersion = ($postgresVersionOutput -join "").Trim()
    if ($postgresVersion -notmatch "^18\.4(?:\s|$)") {
        throw "PostgreSQL did not report the approved 18.4 version."
    }

    $qdrantResponse = $null
    for ($attempt = 1; $attempt -le 30 -and $null -eq $qdrantResponse; $attempt++) {
        try {
            $qdrantResponse = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$($runtimeEnvironment['QDRANT_HTTP_PORT'])/" `
                -Method Get `
                -TimeoutSec 5
        }
        catch {
            if ($attempt -eq 30) {
                throw "Qdrant API did not become available."
            }
            Start-Sleep -Seconds 1
        }
    }
    $qdrantVersion = [string]$qdrantResponse.version
    if ($qdrantVersion -cne "1.18.3") {
        throw "Qdrant did not report the approved 1.18.3 version."
    }

    Assert-PortBindings -ContainerId $postgresContainer -Expected @{
        "5432/tcp" = [int]$runtimeEnvironment["POSTGRES_PORT"]
    }
    Assert-PortBindings -ContainerId $qdrantContainer -Expected @{
        "6333/tcp" = [int]$runtimeEnvironment["QDRANT_HTTP_PORT"]
        "6334/tcp" = [int]$runtimeEnvironment["QDRANT_GRPC_PORT"]
    }

    Write-Output "PostgreSQL version: $postgresVersion"
    Write-Output "Qdrant version: $qdrantVersion"
    Write-Output "Published bindings verified as 127.0.0.1 only."
    Write-Output "Approved image digests verified on both containers."
}
finally {
    try {
        if ($cleanupAuthorized) {
            Write-Output "Cleaning isolated Compose project $composeProjectName."
            $previousErrorPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                & $dockerExecutable compose `
                    --project-name $composeProjectName `
                    --env-file $templatePath `
                    --file $composePath `
                    down --volumes --remove-orphans
            }
            finally {
                $ErrorActionPreference = $previousErrorPreference
            }

            Remove-ProjectResources
            $remainingContainers = @(Get-ProjectResources -Type container)
            $remainingNetworks = @(Get-ProjectResources -Type network)
            $remainingVolumes = @(Get-ProjectResources -Type volume)
            if (
                $remainingContainers.Count -ne 0 -or
                $remainingNetworks.Count -ne 0 -or
                $remainingVolumes.Count -ne 0
            ) {
                $cleanupError = "Project-labelled Docker resources remain after cleanup."
            }
            else {
                Write-Output "Cleanup verified: containers=0, networks=0, volumes=0."
            }
        }
    }
    catch {
        $cleanupError = "Unable to complete or verify isolated Docker cleanup."
    }
    finally {
        Restore-ProcessEnvironment -Snapshot $savedEnvironment
        Assert-ProcessEnvironmentMatchesSnapshot -Snapshot $savedEnvironment
    }

    if ($null -ne $cleanupError) {
        throw $cleanupError
    }
}

if (-not $started) {
    throw "The isolated Compose services did not start."
}
Write-Output "Compose smoke test passed."
