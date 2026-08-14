[CmdletBinding()]
param([switch]$RuntimePreflightOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1") -Quiet

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimePreflight = Join-Path $PSScriptRoot "assert-pwsh-runtime.ps1"
$templatePath = Join-Path $repositoryRoot ".env.example"
$composePath = Join-Path $repositoryRoot "docker-compose.yml"
$environmentValidator = Join-Path $PSScriptRoot "validate-environment.ps1"
$composeValidator = Join-Path $PSScriptRoot "validate-compose.ps1"
$smokeTest = Join-Path $PSScriptRoot "smoke-compose.ps1"
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
$portKeys = @("POSTGRES_PORT", "QDRANT_HTTP_PORT", "QDRANT_GRPC_PORT")
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryRoot = Join-Path $temporaryBase (
    "medevidence-infrastructure-contract-" + [guid]::NewGuid().ToString("N")
)
$dockerUnavailablePath = Join-Path $temporaryRoot "docker-unavailable-path"
$utf8NoBom = New-Object Text.UTF8Encoding($false)
$results = [Collections.Generic.List[string]]::new()

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

function Resolve-ApprovedPowerShellExecutable {
    try {
        $pwshCommand = Get-Command pwsh `
            -CommandType Application `
            -ErrorAction Stop |
                Select-Object -First 1
    }
    catch {
        throw "The required pwsh executable is unavailable."
    }

    $pwshExecutable = [string]$pwshCommand.Source
    if (
        -not [IO.Path]::IsPathRooted($pwshExecutable) -or
        -not (Test-Path -LiteralPath $pwshExecutable -PathType Leaf)
    ) {
        throw "The required pwsh executable is unavailable."
    }

    $resolvedExecutable = (Resolve-Path -LiteralPath $pwshExecutable).ProviderPath
    $preflightOutput = @(
        & $resolvedExecutable `
            -NoLogo `
            -NoProfile `
            -File $runtimePreflight 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw (
            "The resolved pwsh executable failed the MedEvidence runtime " +
            "preflight: $($preflightOutput -join ' ')"
        )
    }
    return $resolvedExecutable
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
    param(
        [Collections.Generic.Dictionary[string, object]]$Snapshot,
        [string]$Context
    )

    foreach ($name in $Snapshot.Keys) {
        $original = $Snapshot[$name]
        $actual = Get-ProcessEnvironmentEntry -Name $name
        if ($actual.Exists -ne [bool]$original.Exists) {
            throw "$Context did not restore process environment variable $name existence."
        }
        if ($actual.Exists -and [string]$actual.Value -cne [string]$original.Value) {
            throw "$Context did not restore process environment variable $name value."
        }
    }
}

function Set-EnvironmentValue {
    param(
        [string[]]$Lines,
        [string]$Key,
        [string]$Value
    )

    return @(
        $Lines | ForEach-Object {
            if ($_ -match ("^" + [regex]::Escape($Key) + "=")) {
                "$Key=$Value"
            }
            else {
                $_
            }
        }
    )
}

function Remove-EnvironmentKey {
    param(
        [string[]]$Lines,
        [string]$Key
    )

    return @($Lines | Where-Object { $_ -notmatch ("^" + [regex]::Escape($Key) + "=") })
}

function Write-EnvironmentCase {
    param(
        [string]$Name,
        [string[]]$Lines
    )

    $path = Join-Path $temporaryRoot "$Name.env"
    [IO.File]::WriteAllLines($path, $Lines, $utf8NoBom)
    return $path
}

function Write-ComposeCase {
    param(
        [string]$Name,
        [string]$Content
    )

    $path = Join-Path $temporaryRoot "$Name.yml"
    [IO.File]::WriteAllText($path, $Content, $utf8NoBom)
    return $path
}

function Assert-Pass {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    try {
        $null = & $Action 2>&1
    }
    catch {
        throw "Infrastructure contract case '$Name' unexpectedly failed."
    }
    $results.Add("PASS $Name")
}

function Assert-Fail {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    $failed = $false
    try {
        $null = & $Action 2>&1
    }
    catch {
        $failed = $true
    }
    if (-not $failed) {
        throw "Infrastructure contract case '$Name' unexpectedly passed."
    }
    $results.Add("PASS $Name (rejected)")
}

function Get-RunningContainerSet {
    $output = @(& docker ps --quiet --no-trunc 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the running-container set."
    }
    return (@($output | ForEach-Object { $_.ToString() } | Sort-Object) -join "`n")
}

function Get-ContainerSet {
    $output = @(& docker ps --all --quiet --no-trunc 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the complete container set."
    }
    return (@($output | ForEach-Object { $_.ToString() } | Sort-Object) -join "`n")
}

function Get-ImageSet {
    $output = @(
        & docker image ls `
            --no-trunc `
            --format "{{.ID}}|{{.Repository}}:{{.Tag}}|{{.Digest}}" 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the image set."
    }
    return (@($output | ForEach-Object { $_.ToString() } | Sort-Object) -join "`n")
}

function Get-NetworkSet {
    $output = @(
        & docker network ls `
            --no-trunc `
            --format "{{.ID}}|{{.Name}}" 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the network set."
    }
    return (@($output | ForEach-Object { $_.ToString() } | Sort-Object) -join "`n")
}

function Get-VolumeSet {
    $output = @(& docker volume ls --format "{{.Name}}" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the volume set."
    }
    return (@($output | ForEach-Object { $_.ToString() } | Sort-Object) -join "`n")
}

function Invoke-ChildPowerShellWithoutDocker {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    $pathEntries = @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).GetEnumerator() | Where-Object {
            [string]$_.Key -ieq "PATH"
        }
    )
    if ($pathEntries.Count -ne 1) {
        throw "Unable to identify the process PATH variable."
    }
    $pathEnvironmentName = [string]$pathEntries[0].Key
    $pathSnapshot = Get-ProcessEnvironmentSnapshot -Names @($pathEnvironmentName)
    try {
        Set-ProcessEnvironmentValue `
            -Name $pathEnvironmentName `
            -Value $dockerUnavailablePath
        $previousErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $output = @(
                & $powerShellExecutable `
                    -NoProfile `
                    -ExecutionPolicy Bypass `
                    -File $ScriptPath `
                    @Arguments 2>&1
            )
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorPreference
        }
    }
    finally {
        Restore-ProcessEnvironment -Snapshot $pathSnapshot
        Assert-ProcessEnvironmentMatchesSnapshot `
            -Snapshot $pathSnapshot `
            -Context "Docker-unavailable child process"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output | ForEach-Object { $_.ToString() })
    }
}

function Invoke-ValidatorWithoutDocker {
    param([string]$ComposeFile)

    return Invoke-ChildPowerShellWithoutDocker `
        -ScriptPath $composeValidator `
        -Arguments @(
            "-EnvFile",
            $templatePath,
            "-ComposeFile",
            $ComposeFile,
            "-Template"
        )
}

function Invoke-SmokeWithoutDocker {
    param([string]$ComposeFile)

    $projectName = "me-source-order-$PID-$([guid]::NewGuid().ToString('N'))"
    return Invoke-ChildPowerShellWithoutDocker `
        -ScriptPath $smokeTest `
        -Arguments @(
            "-ComposeFile",
            $ComposeFile,
            "-ProjectName",
            $projectName
        )
}

function ConvertTo-NormalizedChildOutput {
    param([object[]]$Output)

    $ansiEscapePattern = ([string][char]27) + "\[[0-?]*[ -/]*[@-~]"
    $plainLines = @(
        foreach ($line in $Output) {
            $plainLine = [regex]::Replace(
                [string]$line,
                $ansiEscapePattern,
                ""
            )
            $plainLine -replace "^\s*\|\s?", ""
        }
    )
    return ((($plainLines -join " ") -replace "\s+", " ").Trim())
}

function Assert-ValidatorOutputIsSafe {
    param(
        [object]$Result,
        [string]$Context,
        [string]$Password
    )

    $text = (@($Result.Output) -join [Environment]::NewLine)
    if (-not [string]::IsNullOrEmpty($Password) -and $text.Contains($Password)) {
        throw "$Context printed the PostgreSQL password."
    }
    if ($text -cmatch '"services"\s*:') {
        throw "$Context printed rendered Compose JSON."
    }
}

function Assert-DockerComposeRenders {
    param([string]$ComposeFile)

    $savedEnvironment = Get-ProcessEnvironmentSnapshot -Names $requiredKeys
    try {
        foreach ($key in $requiredKeys) {
            Remove-ProcessEnvironmentVariable -Name $key
        }
        $projectName = "medevidence-fixture-" + [guid]::NewGuid().ToString("N")
        $previousErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $renderedOutput = @(
                & docker compose `
                    --project-name $projectName `
                    --env-file $templatePath `
                    --file $ComposeFile `
                    config `
                    --format json 2>&1
            )
            $composeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorPreference
        }
    }
    finally {
        Restore-ProcessEnvironment -Snapshot $savedEnvironment
        Assert-ProcessEnvironmentMatchesSnapshot `
            -Snapshot $savedEnvironment `
            -Context "Compose fixture rendering"
    }

    if ($composeExitCode -ne 0) {
        throw "A semantic regression fixture is not accepted by Docker Compose."
    }
    $renderedJson = ($renderedOutput | ForEach-Object { $_.ToString() }) -join (
        [Environment]::NewLine
    )
    try {
        $null = $renderedJson | ConvertFrom-Json
    }
    catch {
        throw "A semantic regression fixture did not render valid JSON."
    }
    finally {
        $renderedJson = $null
        $renderedOutput = $null
    }
}

$powerShellExecutable = Resolve-ApprovedPowerShellExecutable
if (
    -not [IO.Path]::IsPathRooted($powerShellExecutable) -or
    -not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)
) {
    throw "The approved pwsh executable path is invalid."
}
$results.Add(
    "PASS pwsh-runtime-resolved " +
    "(PSEdition=$($PSVersionTable.PSEdition); " +
    "version=$($PSVersionTable.PSVersion); path=$powerShellExecutable)"
)

Assert-Pass "runtime-core-7.6.4-lower-bound" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.6.4")) `
        -ExecutablePath "pwsh"
}
Assert-Pass "runtime-core-7.6.5-stable" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.6.5")) `
        -ExecutablePath "pwsh.exe"
}
Assert-Fail "runtime-rejects-preview-release" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.6.4-preview.1")) `
        -ExecutablePath "pwsh"
}
Assert-Fail "runtime-rejects-release-candidate" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.6.4-rc.1")) `
        -ExecutablePath "pwsh"
}
Assert-Fail "runtime-rejects-windows-powershell-edition" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Desktop" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("5.1.0")) `
        -ExecutablePath "powershell.exe"
}
Assert-Fail "runtime-rejects-version-before-7.6.4" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.5.9")) `
        -ExecutablePath "pwsh"
}
Assert-Fail "runtime-rejects-version-7.7.0" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.7.0")) `
        -ExecutablePath "pwsh"
}
Assert-Fail "runtime-rejects-unsupported-executable" {
    Assert-MedEvidencePowerShellRuntime `
        -Edition "Core" `
        -Version ([System.Management.Automation.SemanticVersion]::Parse("7.6.4")) `
        -ExecutablePath "powershell.exe"
}

if ($RuntimePreflightOnly) {
    $results
    Write-Output "PowerShell runtime contract: $($results.Count) cases passed."
    return
}

$validatorSource = [IO.File]::ReadAllText($composeValidator)
if (
    $validatorSource.Contains("Get-Command docker.exe") -or
    -not $validatorSource.Contains("Get-Command docker ")
) {
    throw "Compose validation does not use cross-platform Docker command resolution."
}
$results.Add("PASS docker-command-resolution-uses-cross-platform-name")

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
New-Item -ItemType Directory -Path $dockerUnavailablePath | Out-Null
try {
    $templateLines = [IO.File]::ReadAllLines($templatePath)
    $runtimeLines = Set-EnvironmentValue -Lines $templateLines `
        -Key "POSTGRES_PASSWORD" -Value (New-RandomPassword)
    $runtimePath = Write-EnvironmentCase -Name "valid-runtime" -Lines $runtimeLines

    Assert-Pass "compose-source-only-canonical-without-environment" {
        & $composeValidator `
            -EnvFile (Join-Path $temporaryRoot "intentionally-missing.env") `
            -ComposeFile $composePath `
            -SourceOnly
    }

    $runningBefore = Get-RunningContainerSet

    $collisionProjectName = "me-collision-$PID-$([guid]::NewGuid().ToString('N'))"
    $collisionVolumeName = "$collisionProjectName-sentinel"
    $collisionVolumeCreated = $false
    $unrelatedEnvironmentKey = "MEDEVIDENCE_INFRASTRUCTURE_CONTRACT_UNRELATED"
    $collisionHarnessEnvironment = Get-ProcessEnvironmentSnapshot -Names $requiredKeys
    $unrelatedHarnessEnvironment = Get-ProcessEnvironmentSnapshot -Names @(
        $unrelatedEnvironmentKey
    )
    try {
        Set-ProcessEnvironmentValue `
            -Name $unrelatedEnvironmentKey `
            -Value "medevidence-unrelated-environment-sentinel"
        $collisionSnapshotKeys = @($requiredKeys + $unrelatedEnvironmentKey)
        $null = & docker volume create `
            --label "com.docker.compose.project=$collisionProjectName" `
            $collisionVolumeName 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create the disposable collision-test volume."
        }
        $collisionVolumeCreated = $true

        $collisionCases = @(
            @{
                Name = "collision-resource-survived-no-startup-environment-restored"
                Variable = $null
                State = "inherited"
                Value = $null
            },
            @{
                Name = "collision-postgres-image-absent-restored"
                Variable = "POSTGRES_IMAGE"
                State = "absent"
                Value = $null
            },
            @{
                Name = "collision-postgres-image-sentinel-restored"
                Variable = "POSTGRES_IMAGE"
                State = "sentinel"
                Value = "medevidence-postgres-image-sentinel"
            },
            @{
                Name = "collision-postgres-port-absent-restored"
                Variable = "POSTGRES_PORT"
                State = "absent"
                Value = $null
            },
            @{
                Name = "collision-qdrant-http-port-sentinel-restored"
                Variable = "QDRANT_HTTP_PORT"
                State = "sentinel"
                Value = "medevidence-qdrant-http-port-sentinel"
            },
            @{
                Name = "collision-postgres-user-empty-restored"
                Variable = "POSTGRES_USER"
                State = "empty"
                Value = ""
            },
            @{
                Name = "collision-postgres-user-absent-restored"
                Variable = "POSTGRES_USER"
                State = "absent"
                Value = $null
            },
            @{
                Name = "collision-postgres-user-sentinel-restored"
                Variable = "POSTGRES_USER"
                State = "sentinel"
                Value = "medevidence-postgres-user-sentinel"
            },
            @{
                Name = "collision-qdrant-image-empty-restored"
                Variable = "QDRANT_IMAGE"
                State = "empty"
                Value = ""
            },
            @{
                Name = "collision-qdrant-grpc-port-absent-restored"
                Variable = "QDRANT_GRPC_PORT"
                State = "absent"
                Value = $null
            },
            @{
                Name = "collision-postgres-password-sentinel-restored"
                Variable = "POSTGRES_PASSWORD"
                State = "sentinel"
                Value = "medevidence-postgres-password-sentinel"
            }
        )
        foreach ($collisionCase in $collisionCases) {
            Restore-ProcessEnvironment -Snapshot $collisionHarnessEnvironment
            if ($collisionCase.State -ceq "absent") {
                Remove-ProcessEnvironmentVariable -Name $collisionCase.Variable
            }
            elseif (@("empty", "sentinel") -ccontains $collisionCase.State) {
                Set-ProcessEnvironmentValue `
                    -Name $collisionCase.Variable `
                    -Value $collisionCase.Value
            }

            $environmentBeforeCollision = Get-ProcessEnvironmentSnapshot `
                -Names $collisionSnapshotKeys
            if (
                $collisionCase.State -ceq "absent" -and
                $environmentBeforeCollision[$collisionCase.Variable].Exists
            ) {
                throw "The absent-state collision precondition was not established."
            }
            if (
                @("empty", "sentinel") -ccontains $collisionCase.State -and
                (
                    -not $environmentBeforeCollision[$collisionCase.Variable].Exists -or
                    [string]$environmentBeforeCollision[$collisionCase.Variable].Value -cne
                        [string]$collisionCase.Value
                )
            ) {
                throw "The sentinel-state collision precondition was not established."
            }

            $collisionRejected = $false
            try {
                $null = & $smokeTest -ProjectName $collisionProjectName 2>&1
            }
            catch {
                if (
                    $_.Exception.Message -cne
                    "The isolated Compose project name unexpectedly already exists."
                ) {
                    throw "The smoke test failed before reaching the intended collision check."
                }
                $collisionRejected = $true
            }
            if (-not $collisionRejected) {
                throw "The smoke test did not reject the colliding project name."
            }

            $null = & docker volume inspect $collisionVolumeName 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "The smoke test removed the pre-existing collision-test volume."
            }

            $collisionLabel = "label=com.docker.compose.project=$collisionProjectName"
            $collisionContainers = @(& docker ps --all --quiet --filter $collisionLabel 2>&1)
            if ($LASTEXITCODE -ne 0 -or $collisionContainers.Count -ne 0) {
                throw "The collision regression unexpectedly created a container."
            }
            $collisionNetworks = @(& docker network ls --quiet --filter $collisionLabel 2>&1)
            if ($LASTEXITCODE -ne 0 -or $collisionNetworks.Count -ne 0) {
                throw "The collision regression unexpectedly created a network."
            }
            $collisionVolumes = @(& docker volume ls --quiet --filter $collisionLabel 2>&1)
            if (
                $LASTEXITCODE -ne 0 -or
                $collisionVolumes.Count -ne 1 -or
                [string]$collisionVolumes[0] -cne $collisionVolumeName
            ) {
                throw "The collision-test volume identity changed unexpectedly."
            }

            Assert-ProcessEnvironmentMatchesSnapshot `
                -Snapshot $environmentBeforeCollision `
                -Context $collisionCase.Name
            $results.Add("PASS $($collisionCase.Name)")
        }
        $results.Add("PASS collision-all-eight-and-unrelated-environment-restored")
    }
    finally {
        try {
            if ($collisionVolumeCreated) {
                $null = & docker volume rm $collisionVolumeName 2>&1
                if ($LASTEXITCODE -ne 0) {
                    throw "Unable to remove the disposable collision-test volume."
                }
            }
        }
        finally {
            try {
                Restore-ProcessEnvironment -Snapshot $collisionHarnessEnvironment
                Assert-ProcessEnvironmentMatchesSnapshot `
                    -Snapshot $collisionHarnessEnvironment `
                    -Context "Collision regression harness"
            }
            finally {
                Restore-ProcessEnvironment -Snapshot $unrelatedHarnessEnvironment
                Assert-ProcessEnvironmentMatchesSnapshot `
                    -Snapshot $unrelatedHarnessEnvironment `
                    -Context "Unrelated environment regression harness"
            }
        }
    }

    Assert-Pass "template-explicit" {
        & $environmentValidator -EnvFile $templatePath -Template
    }
    Assert-Fail "template-strict-runtime" {
        & $environmentValidator -EnvFile $templatePath
    }
    Assert-Fail "runtime-template-mode" {
        & $environmentValidator -EnvFile $runtimePath -Template
    }

    foreach ($key in $requiredKeys) {
        $caseKey = $key.ToLowerInvariant().Replace("_", "-")
        $missingPath = Write-EnvironmentCase -Name "missing-$caseKey" -Lines (
            Remove-EnvironmentKey -Lines $runtimeLines -Key $key
        )
        Assert-Fail "missing-$key" {
            & $environmentValidator -EnvFile $missingPath
        }

        $blankPath = Write-EnvironmentCase -Name "blank-$caseKey" -Lines (
            Set-EnvironmentValue -Lines $runtimeLines -Key $key -Value ""
        )
        Assert-Fail "blank-$key" {
            & $environmentValidator -EnvFile $blankPath
        }
    }

    $duplicatePath = Write-EnvironmentCase -Name "duplicate-key" -Lines (
        @($runtimeLines) + "POSTGRES_PORT=15432"
    )
    Assert-Fail "duplicate-key" {
        & $environmentValidator -EnvFile $duplicatePath
    }

    $unknownPath = Write-EnvironmentCase -Name "unknown-key" -Lines (
        @($runtimeLines) + "UNAPPROVED_SETTING=value"
    )
    Assert-Fail "unknown-key" {
        & $environmentValidator -EnvFile $unknownPath
    }

    $placeholderPath = Write-EnvironmentCase -Name "placeholder-password" -Lines $templateLines
    Assert-Fail "placeholder-runtime-password" {
        & $environmentValidator -EnvFile $placeholderPath
    }

    foreach ($key in $portKeys) {
        $caseKey = $key.ToLowerInvariant().Replace("_", "-")
        $invalidPortPath = Write-EnvironmentCase -Name "invalid-$caseKey" -Lines (
            Set-EnvironmentValue -Lines $runtimeLines -Key $key -Value "not-a-port"
        )
        Assert-Fail "invalid-$key" {
            & $environmentValidator -EnvFile $invalidPortPath
        }
    }
    $outOfRangePortPath = Write-EnvironmentCase -Name "out-of-range-port" -Lines (
        Set-EnvironmentValue -Lines $runtimeLines -Key "POSTGRES_PORT" -Value "70000"
    )
    Assert-Fail "out-of-range-POSTGRES_PORT" {
        & $environmentValidator -EnvFile $outOfRangePortPath
    }

    $duplicatePortPath = Write-EnvironmentCase -Name "duplicate-port" -Lines (
        Set-EnvironmentValue -Lines $runtimeLines -Key "QDRANT_HTTP_PORT" -Value "5432"
    )
    Assert-Fail "duplicate-port" {
        & $environmentValidator -EnvFile $duplicatePortPath
    }

    $unapprovedPostgresImagePath = Write-EnvironmentCase `
        -Name "unapproved-postgres-image" -Lines (
        Set-EnvironmentValue -Lines $runtimeLines `
            -Key "POSTGRES_IMAGE" -Value "docker.io/library/postgres:latest"
    )
    Assert-Fail "unapproved-POSTGRES_IMAGE" {
        & $environmentValidator -EnvFile $unapprovedPostgresImagePath
    }
    $unapprovedQdrantImagePath = Write-EnvironmentCase `
        -Name "unapproved-qdrant-image" -Lines (
        Set-EnvironmentValue -Lines $runtimeLines `
            -Key "QDRANT_IMAGE" -Value "docker.io/qdrant/qdrant:latest"
    )
    Assert-Fail "unapproved-QDRANT_IMAGE" {
        & $environmentValidator -EnvFile $unapprovedQdrantImagePath
    }

    Assert-Pass "valid-generated-runtime" {
        & $environmentValidator -EnvFile $runtimePath
    }
    Assert-Pass "compose-template-configuration-only" {
        & $composeValidator -EnvFile $templatePath -Template
    }
    Assert-Pass "compose-runtime-configuration-only" {
        & $composeValidator -EnvFile $runtimePath
    }

    $composeEnvironmentHarness = Get-ProcessEnvironmentSnapshot -Names $requiredKeys
    try {
        $composeEnvironmentCases = @(
            @{
                Name = "compose-postgres-image-absent-restored"
                Variable = "POSTGRES_IMAGE"
                State = "absent"
                Value = $null
            },
            @{
                Name = "compose-postgres-image-sentinel-restored"
                Variable = "POSTGRES_IMAGE"
                State = "sentinel"
                Value = "medevidence-compose-postgres-image-sentinel"
            },
            @{
                Name = "compose-postgres-port-absent-restored"
                Variable = "POSTGRES_PORT"
                State = "absent"
                Value = $null
            },
            @{
                Name = "compose-qdrant-http-port-sentinel-restored"
                Variable = "QDRANT_HTTP_PORT"
                State = "sentinel"
                Value = "medevidence-compose-qdrant-http-port-sentinel"
            },
            @{
                Name = "compose-qdrant-grpc-port-empty-restored"
                Variable = "QDRANT_GRPC_PORT"
                State = "empty"
                Value = ""
            }
        )
        foreach ($composeEnvironmentCase in $composeEnvironmentCases) {
            Restore-ProcessEnvironment -Snapshot $composeEnvironmentHarness
            if ($composeEnvironmentCase.State -ceq "absent") {
                Remove-ProcessEnvironmentVariable -Name $composeEnvironmentCase.Variable
            }
            else {
                Set-ProcessEnvironmentValue `
                    -Name $composeEnvironmentCase.Variable `
                    -Value $composeEnvironmentCase.Value
            }

            $environmentBeforeCompose = Get-ProcessEnvironmentSnapshot -Names $requiredKeys
            if (
                $composeEnvironmentCase.State -ceq "absent" -and
                $environmentBeforeCompose[$composeEnvironmentCase.Variable].Exists
            ) {
                throw "The absent-state Compose precondition was not established."
            }
            if (
                $composeEnvironmentCase.State -cne "absent" -and
                (
                    -not $environmentBeforeCompose[$composeEnvironmentCase.Variable].Exists -or
                    [string]$environmentBeforeCompose[$composeEnvironmentCase.Variable].Value -cne
                        [string]$composeEnvironmentCase.Value
                )
            ) {
                throw "The present-state Compose precondition was not established."
            }

            try {
                $null = & $composeValidator -EnvFile $templatePath -Template 2>&1
            }
            catch {
                throw "Compose environment restoration case unexpectedly failed."
            }
            Assert-ProcessEnvironmentMatchesSnapshot `
                -Snapshot $environmentBeforeCompose `
                -Context $composeEnvironmentCase.Name
            $results.Add("PASS $($composeEnvironmentCase.Name)")
        }

        Restore-ProcessEnvironment -Snapshot $composeEnvironmentHarness
        Remove-ProcessEnvironmentVariable -Name "POSTGRES_IMAGE"
        Set-ProcessEnvironmentValue `
            -Name "POSTGRES_DB" `
            -Value "medevidence-compose-failure-sentinel"
        Set-ProcessEnvironmentValue -Name "POSTGRES_USER" -Value ""
        Set-ProcessEnvironmentValue `
            -Name "QDRANT_GRPC_PORT" `
            -Value "medevidence-compose-failure-port-sentinel"
        $environmentBeforeForcedFailure = Get-ProcessEnvironmentSnapshot -Names $requiredKeys
        $forcedFailurePath = Write-ComposeCase `
            -Name "compose-forced-render-failure" `
            -Content "services:`n  postgres: ["
        $forcedFailureRejected = $false
        try {
            $null = & $composeValidator `
                -EnvFile $templatePath `
                -ComposeFile $forcedFailurePath `
                -Template 2>&1
        }
        catch {
            $forcedFailureRejected = $true
        }
        if (-not $forcedFailureRejected) {
            throw "The forced Compose failure unexpectedly passed."
        }
        Assert-ProcessEnvironmentMatchesSnapshot `
            -Snapshot $environmentBeforeForcedFailure `
            -Context "compose-forced-failure-environment-restored"
        $results.Add("PASS compose-forced-failure-environment-restored")
    }
    finally {
        Restore-ProcessEnvironment -Snapshot $composeEnvironmentHarness
        Assert-ProcessEnvironmentMatchesSnapshot `
            -Snapshot $composeEnvironmentHarness `
            -Context "Compose environment regression harness"
    }

    $baseCompose = [IO.File]::ReadAllText($composePath).Replace("`r`n", "`n")
    $templatePasswordLines = @(
        $templateLines | Where-Object { $_ -cmatch "^POSTGRES_PASSWORD=" }
    )
    if ($templatePasswordLines.Count -ne 1) {
        throw "The Compose ordering fixture cannot identify the template password."
    }
    $templatePassword = $templatePasswordLines[0].Substring(
        "POSTGRES_PASSWORD=".Length
    )
    $postgresPortMarker = '      - "127.0.0.1:${POSTGRES_PORT:?POSTGRES_PORT is required}:5432"'
    $qdrantHttpPortMarker = '      - "127.0.0.1:${QDRANT_HTTP_PORT:?QDRANT_HTTP_PORT is required}:6333"'
    $qdrantGrpcPortMarker = '      - "127.0.0.1:${QDRANT_GRPC_PORT:?QDRANT_GRPC_PORT is required}:6334"'
    $postgresServiceMarker = "  postgres:`n    image:"
    $qdrantServiceMarker = "  qdrant:`n    image:"
    $postgresEnvironmentMarker = (
        '      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"'
    )
    $postgresMarker = "    volumes:`n      - postgres_data:/var/lib/postgresql"
    $qdrantMarker = "    volumes:`n      - qdrant_data:/qdrant/storage"
    $requiredMarkers = @(
        $postgresPortMarker,
        $qdrantHttpPortMarker,
        $qdrantGrpcPortMarker,
        $postgresServiceMarker,
        $qdrantServiceMarker,
        $postgresEnvironmentMarker,
        $postgresMarker,
        $qdrantMarker
    )
    if (@($requiredMarkers | Where-Object { -not $baseCompose.Contains($_) }).Count -ne 0) {
        throw "The Compose fixture markers do not match docker-compose.yml."
    }

    if (@(Get-ChildItem -LiteralPath $dockerUnavailablePath -Force).Count -ne 0) {
        throw "The Docker-unavailable PATH fixture must be empty."
    }
    $sourceGateError = (
        "Compose source must contain exactly the name, services, and volumes root " +
        "properties."
    )
    $missingIncludePath = Join-Path $temporaryRoot "missing-include.yml"
    $missingSecretPath = Join-Path $temporaryRoot "missing-secret.txt"
    $missingConfigPath = Join-Path $temporaryRoot "missing-config.txt"
    $sourceOrderingCases = @(
        @{
            Name = "missing-include"
            Content = $baseCompose +
                "`ninclude:`n  - $([IO.Path]::GetFileName($missingIncludePath))"
            ReferencedPath = $missingIncludePath
        },
        @{
            Name = "unreferenced-secrets"
            Content = $baseCompose +
                "`nsecrets:`n  audit_secret:`n" +
                "    file: $([IO.Path]::GetFileName($missingSecretPath))"
            ReferencedPath = $missingSecretPath
        },
        @{
            Name = "unreferenced-configs"
            Content = $baseCompose +
                "`nconfigs:`n  audit_config:`n" +
                "    file: $([IO.Path]::GetFileName($missingConfigPath))"
            ReferencedPath = $missingConfigPath
        },
        @{
            Name = "root-extension"
            Content = $baseCompose + "`nx-extra:`n  enabled: true"
            ReferencedPath = $null
        },
        @{
            Name = "root-version"
            Content = $baseCompose + "`nversion: `"3.9`""
            ReferencedPath = $null
        }
    )
    foreach ($sourceOrderingCase in $sourceOrderingCases) {
        if (
            $null -ne $sourceOrderingCase.ReferencedPath -and
            (Test-Path -LiteralPath $sourceOrderingCase.ReferencedPath)
        ) {
            throw "A source-order external-file precondition was not established."
        }
        $sourceOrderingPath = Write-ComposeCase `
            -Name "source-order-$($sourceOrderingCase.Name)" `
            -Content $sourceOrderingCase.Content
        $containersBeforeSourceGate = Get-ContainerSet
        $imagesBeforeSourceGate = Get-ImageSet
        $networksBeforeSourceGate = Get-NetworkSet
        $volumesBeforeSourceGate = Get-VolumeSet
        $sourceOrderingResult = Invoke-ValidatorWithoutDocker `
            -ComposeFile $sourceOrderingPath
        $sourceOrderingOutput = ConvertTo-NormalizedChildOutput `
            -Output $sourceOrderingResult.Output
        if ($sourceOrderingResult.ExitCode -eq 0) {
            throw "A source-invalid Compose ordering fixture unexpectedly passed."
        }
        if (-not $sourceOrderingOutput.Contains($sourceGateError)) {
            throw "A source-invalid Compose fixture did not return the source-gate error."
        }
        if ($sourceOrderingOutput.Contains("Docker command is unavailable.")) {
            throw "A source-invalid Compose fixture reached Docker command resolution."
        }
        if ($sourceOrderingOutput.Contains("CommandNotFoundException")) {
            throw "A source-invalid Compose fixture attempted unresolved command execution."
        }
        Assert-ValidatorOutputIsSafe `
            -Result $sourceOrderingResult `
            -Context "source-order-$($sourceOrderingCase.Name)" `
            -Password $templatePassword
        if ((Get-ContainerSet) -cne $containersBeforeSourceGate) {
            throw "A source-invalid Compose fixture changed the container set."
        }
        if ((Get-ImageSet) -cne $imagesBeforeSourceGate) {
            throw "A source-invalid Compose fixture changed the image set."
        }
        if ((Get-NetworkSet) -cne $networksBeforeSourceGate) {
            throw "A source-invalid Compose fixture changed the network set."
        }
        if ((Get-VolumeSet) -cne $volumesBeforeSourceGate) {
            throw "A source-invalid Compose fixture changed the volume set."
        }
        if (
            $null -ne $sourceOrderingCase.ReferencedPath -and
            (Test-Path -LiteralPath $sourceOrderingCase.ReferencedPath)
        ) {
            throw "A forbidden source declaration created or imported its external file."
        }
        $results.Add(
            "PASS source-order-$($sourceOrderingCase.Name) (rejected before Docker)"
        )
    }

    $containersBeforeCanonicalControl = Get-ContainerSet
    $imagesBeforeCanonicalControl = Get-ImageSet
    $networksBeforeCanonicalControl = Get-NetworkSet
    $volumesBeforeCanonicalControl = Get-VolumeSet
    $canonicalWithoutDocker = Invoke-ValidatorWithoutDocker -ComposeFile $composePath
    $canonicalControlOutput = ConvertTo-NormalizedChildOutput `
        -Output $canonicalWithoutDocker.Output
    if ($canonicalWithoutDocker.ExitCode -eq 0) {
        throw "Canonical Compose unexpectedly passed without Docker."
    }
    if ($canonicalControlOutput.Contains($sourceGateError)) {
        throw "Canonical Compose unexpectedly failed the source gate."
    }
    if (-not $canonicalControlOutput.Contains("Docker command is unavailable.")) {
        throw "Canonical Compose did not reach Docker command resolution."
    }
    if ($canonicalControlOutput.Contains("CommandNotFoundException")) {
        throw "Canonical Compose used unresolved Docker command execution."
    }
    Assert-ValidatorOutputIsSafe `
        -Result $canonicalWithoutDocker `
        -Context "source-order-canonical-docker-unavailable-control" `
        -Password $templatePassword
    if ((Get-ContainerSet) -cne $containersBeforeCanonicalControl) {
        throw "The canonical Docker-unavailable control changed the container set."
    }
    if ((Get-ImageSet) -cne $imagesBeforeCanonicalControl) {
        throw "The canonical Docker-unavailable control changed the image set."
    }
    if ((Get-NetworkSet) -cne $networksBeforeCanonicalControl) {
        throw "The canonical Docker-unavailable control changed the network set."
    }
    if ((Get-VolumeSet) -cne $volumesBeforeCanonicalControl) {
        throw "The canonical Docker-unavailable control changed the volume set."
    }
    $results.Add("PASS source-order-canonical-docker-unavailable-control")

    foreach ($sourceOrderingCase in $sourceOrderingCases) {
        if (
            $null -ne $sourceOrderingCase.ReferencedPath -and
            (Test-Path -LiteralPath $sourceOrderingCase.ReferencedPath)
        ) {
            throw "A smoke source-order external-file precondition was not established."
        }
        $smokeSourceOrderingPath = Write-ComposeCase `
            -Name "smoke-source-order-$($sourceOrderingCase.Name)" `
            -Content $sourceOrderingCase.Content
        $containersBeforeSmokeSourceGate = Get-ContainerSet
        $imagesBeforeSmokeSourceGate = Get-ImageSet
        $networksBeforeSmokeSourceGate = Get-NetworkSet
        $volumesBeforeSmokeSourceGate = Get-VolumeSet
        $smokeSourceOrderingResult = Invoke-SmokeWithoutDocker `
            -ComposeFile $smokeSourceOrderingPath
        $smokeSourceOrderingOutput = ConvertTo-NormalizedChildOutput `
            -Output $smokeSourceOrderingResult.Output
        if ($smokeSourceOrderingResult.ExitCode -eq 0) {
            throw "A source-invalid smoke ordering fixture unexpectedly passed."
        }
        if (-not $smokeSourceOrderingOutput.Contains($sourceGateError)) {
            throw "A source-invalid smoke fixture did not return the source-gate error."
        }
        if ($smokeSourceOrderingOutput.Contains("Docker command is unavailable.")) {
            throw "A source-invalid smoke fixture reached Docker command resolution."
        }
        if ($smokeSourceOrderingOutput.Contains("CommandNotFoundException")) {
            throw "A source-invalid smoke fixture attempted unresolved command execution."
        }
        Assert-ValidatorOutputIsSafe `
            -Result $smokeSourceOrderingResult `
            -Context "smoke-source-order-$($sourceOrderingCase.Name)" `
            -Password $templatePassword
        if ((Get-ContainerSet) -cne $containersBeforeSmokeSourceGate) {
            throw "A source-invalid smoke fixture changed the container set."
        }
        if ((Get-ImageSet) -cne $imagesBeforeSmokeSourceGate) {
            throw "A source-invalid smoke fixture changed the image set."
        }
        if ((Get-NetworkSet) -cne $networksBeforeSmokeSourceGate) {
            throw "A source-invalid smoke fixture changed the network set."
        }
        if ((Get-VolumeSet) -cne $volumesBeforeSmokeSourceGate) {
            throw "A source-invalid smoke fixture changed the volume set."
        }
        if (
            $null -ne $sourceOrderingCase.ReferencedPath -and
            (Test-Path -LiteralPath $sourceOrderingCase.ReferencedPath)
        ) {
            throw "A forbidden smoke source declaration accessed its external file."
        }
        $results.Add(
            "PASS smoke-source-order-$($sourceOrderingCase.Name) " +
            "(rejected before Docker)"
        )
    }

    $containersBeforeCanonicalSmokeControl = Get-ContainerSet
    $imagesBeforeCanonicalSmokeControl = Get-ImageSet
    $networksBeforeCanonicalSmokeControl = Get-NetworkSet
    $volumesBeforeCanonicalSmokeControl = Get-VolumeSet
    $canonicalSmokeWithoutDocker = Invoke-SmokeWithoutDocker -ComposeFile $composePath
    $canonicalSmokeControlOutput = ConvertTo-NormalizedChildOutput `
        -Output $canonicalSmokeWithoutDocker.Output
    if ($canonicalSmokeWithoutDocker.ExitCode -eq 0) {
        throw "Canonical smoke unexpectedly passed without Docker."
    }
    if ($canonicalSmokeControlOutput.Contains($sourceGateError)) {
        throw "Canonical smoke unexpectedly failed the source gate."
    }
    if (-not $canonicalSmokeControlOutput.Contains("Docker command is unavailable.")) {
        throw "Canonical smoke did not reach Docker command resolution."
    }
    if ($canonicalSmokeControlOutput.Contains("CommandNotFoundException")) {
        throw "Canonical smoke used unresolved Docker command execution."
    }
    Assert-ValidatorOutputIsSafe `
        -Result $canonicalSmokeWithoutDocker `
        -Context "smoke-source-order-canonical-docker-unavailable-control" `
        -Password $templatePassword
    if ((Get-ContainerSet) -cne $containersBeforeCanonicalSmokeControl) {
        throw "The canonical Docker-unavailable smoke control changed the container set."
    }
    if ((Get-ImageSet) -cne $imagesBeforeCanonicalSmokeControl) {
        throw "The canonical Docker-unavailable smoke control changed the image set."
    }
    if ((Get-NetworkSet) -cne $networksBeforeCanonicalSmokeControl) {
        throw "The canonical Docker-unavailable smoke control changed the network set."
    }
    if ((Get-VolumeSet) -cne $volumesBeforeCanonicalSmokeControl) {
        throw "The canonical Docker-unavailable smoke control changed the volume set."
    }
    $results.Add("PASS smoke-source-order-canonical-docker-unavailable-control")

    $serviceSemanticCases = @(
        @{
            Name = "compose-qdrant-restart"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    restart: always`n    image:"
            )
        },
        @{
            Name = "compose-postgres-command"
            Content = $baseCompose.Replace(
                $postgresServiceMarker,
                '  postgres:' + "`n" + '    command: ["postgres", "--help"]' + "`n" +
                    "    image:"
            )
        },
        @{
            Name = "compose-qdrant-entrypoint"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                '  qdrant:' + "`n" + '    entrypoint: ["/bin/sh", "-c"]' + "`n" +
                    "    image:"
            )
        },
        @{
            Name = "compose-postgres-cap-add"
            Content = $baseCompose.Replace(
                $postgresServiceMarker,
                "  postgres:`n    cap_add: [NET_ADMIN]`n    image:"
            )
        },
        @{
            Name = "compose-qdrant-cap-drop"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    cap_drop: [ALL]`n    image:"
            )
        },
        @{
            Name = "compose-postgres-user"
            Content = $baseCompose.Replace(
                $postgresServiceMarker,
                '  postgres:' + "`n" + '    user: "1000:1000"' + "`n" + "    image:"
            )
        },
        @{
            Name = "compose-qdrant-security-opt"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    security_opt: [no-new-privileges:true]`n    image:"
            )
        },
        @{
            Name = "compose-postgres-extra-environment"
            Content = $baseCompose.Replace(
                $postgresEnvironmentMarker,
                $postgresEnvironmentMarker + "`n      PGDATA: /unexpected-postgres-data"
            )
        },
        @{
            Name = "compose-qdrant-environment"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    environment:`n      QDRANT__LOG_LEVEL: INFO`n    image:"
            )
        },
        @{
            Name = "compose-qdrant-labels"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    labels:`n      medevidence.audit: `"true`"`n    image:"
            )
        },
        @{
            Name = "compose-qdrant-depends-on"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    depends_on: [postgres]`n    image:"
            )
        },
        @{
            Name = "compose-qdrant-profiles"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    profiles: [audit]`n    image:"
            )
        },
        @{
            Name = "compose-qdrant-additional-network"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    networks: [default, audit_extra]`n    image:"
            ) + "`nnetworks:`n  audit_extra:"
        },
        @{
            Name = "compose-additional-root-configs"
            Content = $baseCompose.Replace(
                $qdrantServiceMarker,
                "  qdrant:`n    configs: [audit_config]`n    image:"
            ) + "`nconfigs:`n  audit_config:`n    content: audit"
        },
        @{
            Name = "compose-additional-root-secrets"
            Content = $baseCompose +
                "`nsecrets:`n  audit_secret:`n    external: true"
        }
    )
    foreach ($serviceSemanticCase in $serviceSemanticCases) {
        $serviceSemanticCasePath = Write-ComposeCase `
            -Name $serviceSemanticCase.Name `
            -Content $serviceSemanticCase.Content
        Assert-DockerComposeRenders -ComposeFile $serviceSemanticCasePath
        Assert-Fail $serviceSemanticCase.Name {
            & $composeValidator `
                -EnvFile $templatePath `
                -ComposeFile $serviceSemanticCasePath `
                -Template
        }
    }

    $portAndMountCases = @(
        @{
            Name = "compose-postgres-port-mode-host"
            Content = $baseCompose.Replace(
                $postgresPortMarker,
                @(
                    "      - target: 5432",
                    '        published: "${POSTGRES_PORT:?POSTGRES_PORT is required}"',
                    "        host_ip: 127.0.0.1",
                    "        protocol: tcp",
                    "        mode: host"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-postgres-port-ipv4-wildcard"
            Content = $baseCompose.Replace(
                $postgresPortMarker,
                @(
                    "      - target: 5432",
                    '        published: "${POSTGRES_PORT:?POSTGRES_PORT is required}"',
                    "        host_ip: 0.0.0.0",
                    "        protocol: tcp",
                    "        mode: ingress"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-http-port-ipv6-wildcard"
            Content = $baseCompose.Replace(
                $qdrantHttpPortMarker,
                @(
                    "      - target: 6333",
                    '        published: "${QDRANT_HTTP_PORT:?QDRANT_HTTP_PORT is required}"',
                    '        host_ip: "::"',
                    "        protocol: tcp",
                    "        mode: ingress"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-grpc-port-protocol-udp"
            Content = $baseCompose.Replace(
                $qdrantGrpcPortMarker,
                @(
                    "      - target: 6334",
                    '        published: "${QDRANT_GRPC_PORT:?QDRANT_GRPC_PORT is required}"',
                    "        host_ip: 127.0.0.1",
                    "        protocol: udp",
                    "        mode: ingress"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-http-port-app-protocol"
            Content = $baseCompose.Replace(
                $qdrantHttpPortMarker,
                @(
                    "      - target: 6333",
                    '        published: "${QDRANT_HTTP_PORT:?QDRANT_HTTP_PORT is required}"',
                    "        host_ip: 127.0.0.1",
                    "        protocol: tcp",
                    "        mode: ingress",
                    "        app_protocol: http"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-grpc-port-name"
            Content = $baseCompose.Replace(
                $qdrantGrpcPortMarker,
                @(
                    "      - target: 6334",
                    '        published: "${QDRANT_GRPC_PORT:?QDRANT_GRPC_PORT is required}"',
                    "        host_ip: 127.0.0.1",
                    "        protocol: tcp",
                    "        mode: ingress",
                    "        name: qdrant-grpc"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-additional-service-port"
            Content = $baseCompose.Replace(
                $qdrantGrpcPortMarker,
                $qdrantGrpcPortMarker + "`n      - `"127.0.0.1:65432:65432`""
            )
        },
        @{
            Name = "compose-postgres-volume-nocopy-true"
            Content = $baseCompose.Replace(
                $postgresMarker,
                @(
                    "    volumes:",
                    "      - type: volume",
                    "        source: postgres_data",
                    "        target: /var/lib/postgresql",
                    "        volume:",
                    "          nocopy: true"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-volume-nocopy-true"
            Content = $baseCompose.Replace(
                $qdrantMarker,
                @(
                    "    volumes:",
                    "      - type: volume",
                    "        source: qdrant_data",
                    "        target: /qdrant/storage",
                    "        volume:",
                    "          nocopy: true"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-postgres-volume-subpath"
            Content = $baseCompose.Replace(
                $postgresMarker,
                @(
                    "    volumes:",
                    "      - type: volume",
                    "        source: postgres_data",
                    "        target: /var/lib/postgresql",
                    "        volume:",
                    "          subpath: database"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-volume-non-default-consistency"
            Content = $baseCompose.Replace(
                $qdrantMarker,
                @(
                    "    volumes:",
                    "      - type: volume",
                    "        source: qdrant_data",
                    "        target: /qdrant/storage",
                    "        consistency: cached"
                ) -join "`n"
            )
        }
    )
    foreach ($portAndMountCase in $portAndMountCases) {
        $portAndMountCasePath = Write-ComposeCase `
            -Name $portAndMountCase.Name `
            -Content $portAndMountCase.Content
        Assert-Fail $portAndMountCase.Name {
            & $composeValidator `
                -EnvFile $templatePath `
                -ComposeFile $portAndMountCasePath `
                -Template
        }
    }

    $postgresBindCompose = $baseCompose.Replace(
        $postgresMarker,
        $postgresMarker + "`n      - type: bind`n        source: .`n" +
            "        target: /unexpected-postgres-bind"
    )
    $postgresBindPath = Write-ComposeCase `
        -Name "postgres-additional-bind" -Content $postgresBindCompose
    Assert-Fail "compose-postgres-additional-bind" {
        & $composeValidator `
            -EnvFile $templatePath `
            -ComposeFile $postgresBindPath `
            -Template
    }

    $postgresNamedCompose = $baseCompose.Replace(
        $postgresMarker,
        $postgresMarker + "`n      - postgres_extra:/unexpected-postgres-named"
    ).Replace(
        "  qdrant_data:`n",
        "  qdrant_data:`n  postgres_extra:`n"
    )
    $postgresNamedPath = Write-ComposeCase `
        -Name "postgres-additional-named" -Content $postgresNamedCompose
    Assert-Fail "compose-postgres-additional-named" {
        & $composeValidator `
            -EnvFile $templatePath `
            -ComposeFile $postgresNamedPath `
            -Template
    }

    $qdrantBindCompose = $baseCompose.Replace(
        $qdrantMarker,
        $qdrantMarker + "`n      - type: bind`n        source: .`n" +
            "        target: /unexpected-qdrant-bind"
    )
    $qdrantBindPath = Write-ComposeCase `
        -Name "qdrant-additional-bind" -Content $qdrantBindCompose
    Assert-Fail "compose-qdrant-additional-bind" {
        & $composeValidator `
            -EnvFile $templatePath `
            -ComposeFile $qdrantBindPath `
            -Template
    }

    $qdrantNamedCompose = $baseCompose.Replace(
        $qdrantMarker,
        $qdrantMarker + "`n      - qdrant_extra:/unexpected-qdrant-named"
    ).Replace(
        "  qdrant_data:`n",
        "  qdrant_data:`n  qdrant_extra:`n"
    )
    $qdrantNamedPath = Write-ComposeCase `
        -Name "qdrant-additional-named" -Content $qdrantNamedCompose
    Assert-Fail "compose-qdrant-additional-named" {
        & $composeValidator `
            -EnvFile $templatePath `
            -ComposeFile $qdrantNamedPath `
            -Template
    }

    $postgresHealthMarker = @(
        "    healthcheck:",
        '      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]',
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 20",
        "      start_period: 10s"
    ) -join "`n"
    $qdrantHealthMarker = @(
        "    healthcheck:",
        '      test: ["CMD", "bash", "-c", ":> /dev/tcp/127.0.0.1/6333"]',
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 20",
        "      start_period: 10s"
    ) -join "`n"
    $volumeDefinitionsMarker = @(
        "volumes:",
        "  postgres_data:",
        "  qdrant_data:"
    ) -join "`n"
    foreach ($marker in @($postgresHealthMarker, $qdrantHealthMarker, $volumeDefinitionsMarker)) {
        if (-not $baseCompose.Contains($marker)) {
            throw "A Compose definition fixture marker does not match docker-compose.yml."
        }
    }

    $definitionCases = @(
        @{
            Name = "compose-postgres-health-interval-6s"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                $postgresHealthMarker.Replace("      interval: 5s", "      interval: 6s")
            )
        },
        @{
            Name = "compose-postgres-health-timeout-6s"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                $postgresHealthMarker.Replace("      timeout: 5s", "      timeout: 6s")
            )
        },
        @{
            Name = "compose-postgres-health-retries-changed"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                $postgresHealthMarker.Replace("      retries: 20", "      retries: 19")
            )
        },
        @{
            Name = "compose-postgres-health-start-period-changed"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                $postgresHealthMarker.Replace(
                    "      start_period: 10s",
                    "      start_period: 11s"
                )
            )
        },
        @{
            Name = "compose-qdrant-health-interval-6s"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                $qdrantHealthMarker.Replace("      interval: 5s", "      interval: 6s")
            )
        },
        @{
            Name = "compose-qdrant-health-timeout-6s"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                $qdrantHealthMarker.Replace("      timeout: 5s", "      timeout: 6s")
            )
        },
        @{
            Name = "compose-qdrant-health-retries-changed"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                $qdrantHealthMarker.Replace("      retries: 20", "      retries: 21")
            )
        },
        @{
            Name = "compose-qdrant-health-start-period-changed"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                $qdrantHealthMarker.Replace(
                    "      start_period: 10s",
                    "      start_period: 9s"
                )
            )
        },
        @{
            Name = "compose-postgres-health-disabled"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                "    healthcheck:`n      disable: true"
            )
        },
        @{
            Name = "compose-qdrant-health-disabled"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                "    healthcheck:`n      disable: true"
            )
        },
        @{
            Name = "compose-postgres-health-command-changed"
            Content = $baseCompose.Replace(
                $postgresHealthMarker,
                $postgresHealthMarker.Replace(
                    'pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}',
                    'pg_isready -h 127.0.0.1 -U $${POSTGRES_USER} -d $${POSTGRES_DB}'
                )
            )
        },
        @{
            Name = "compose-qdrant-health-command-changed"
            Content = $baseCompose.Replace(
                $qdrantHealthMarker,
                $qdrantHealthMarker.Replace(
                    ":> /dev/tcp/127.0.0.1/6333",
                    ":> /dev/tcp/127.0.0.1/6334"
                )
            )
        },
        @{
            Name = "compose-postgres-volume-external"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                @(
                    "volumes:",
                    "  postgres_data:",
                    "    external: true",
                    "  qdrant_data:"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-qdrant-volume-external"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                @(
                    "volumes:",
                    "  postgres_data:",
                    "  qdrant_data:",
                    "    external: true"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-volume-fixed-custom-name"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                @(
                    "volumes:",
                    "  postgres_data:",
                    "    name: medevidence_postgres_data",
                    "  qdrant_data:"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-volume-non-local-driver"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                @(
                    "volumes:",
                    "  postgres_data:",
                    "    driver: nfs",
                    "  qdrant_data:"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-volume-non-empty-driver-options"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                @(
                    "volumes:",
                    "  postgres_data:",
                    "    driver_opts:",
                    "      type: none",
                    "  qdrant_data:"
                ) -join "`n"
            )
        },
        @{
            Name = "compose-additional-top-level-volume"
            Content = $baseCompose.Replace(
                $volumeDefinitionsMarker,
                $volumeDefinitionsMarker + "`n  unexpected_data:`n    driver: local"
            )
        }
    )
    foreach ($definitionCase in $definitionCases) {
        $definitionCasePath = Write-ComposeCase `
            -Name $definitionCase.Name `
            -Content $definitionCase.Content
        Assert-Fail $definitionCase.Name {
            & $composeValidator `
                -EnvFile $templatePath `
                -ComposeFile $definitionCasePath `
                -Template
        }
    }

    $runningAfter = Get-RunningContainerSet
    if ($runningAfter -cne $runningBefore) {
        throw "Configuration validation changed the running-container set."
    }
    $results.Add("PASS running-container-set-unchanged")

    $results
    Write-Output "Infrastructure contract: $($results.Count) cases passed."
}
finally {
    $resolvedTemporaryRoot = [IO.Path]::GetFullPath($temporaryRoot)
    if (-not $resolvedTemporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unexpected temporary path."
    }
    if (Test-Path -LiteralPath $resolvedTemporaryRoot) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
