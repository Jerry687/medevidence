[CmdletBinding()]
param(
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$Template,
    [switch]$SourceOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$environmentValidator = Join-Path $PSScriptRoot "validate-environment.ps1"
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

function Resolve-RepositoryPath {
    param([string]$Path)

    $candidate = $Path
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $repositoryRoot $candidate
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Required file does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $candidate).ProviderPath
}

function Read-ValidatedEnvironment {
    param([string]$Path)

    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($line -match "^([^=]+)=(.*)$") {
            $values[$Matches[1].Trim()] = $Matches[2]
        }
    }
    return $values
}

function Get-SourceTopLevelVolumeKeys {
    param([string]$Path)

    $keys = [Collections.Generic.List[string]]::new()
    $inVolumes = $false
    $foundVolumes = $false
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if (-not $inVolumes) {
            if ($line -cmatch "^volumes:\s*(?:#.*)?$") {
                $inVolumes = $true
                $foundVolumes = $true
            }
            continue
        }

        if ($line -cmatch "^\S") {
            break
        }
        if ($line -cmatch "^  (?<key>[A-Za-z0-9._-]+):") {
            $keys.Add($Matches["key"])
        }
    }
    Assert-Contract $foundVolumes "Compose must define a top-level volumes block."
    return @($keys)
}

function Get-SourceTopLevelKeys {
    param([string]$Path)

    $keys = [Collections.Generic.List[string]]::new()
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line.Trim().Length -eq 0 -or $line.TrimStart().StartsWith("#")) {
            continue
        }
        if ($line -cmatch "^\s") {
            continue
        }
        if ($line -cmatch "^(?<key>[A-Za-z0-9._-]+):") {
            $keys.Add($Matches["key"])
            continue
        }
        throw "Compose source contains an unsupported top-level construct."
    }
    return @($keys)
}

function Assert-Contract {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-ServicePorts {
    param([object]$Service)

    return @($Service.ports)
}

function Assert-ExactPropertySet {
    param(
        [object]$Object,
        [string[]]$ExpectedProperties,
        [string]$Context
    )

    Assert-Contract ($null -ne $Object) "$Context is missing."
    $actualProperties = @(
        $Object.PSObject.Properties |
            ForEach-Object { $_.Name } |
            Sort-Object
    )
    $sortedExpectedProperties = @($ExpectedProperties | Sort-Object)
    Assert-Contract (
        $actualProperties.Count -eq $sortedExpectedProperties.Count -and
        ($actualProperties -join "`n") -ceq ($sortedExpectedProperties -join "`n")
    ) "$Context contains an unknown, additional, or missing property."
}

function ConvertTo-NormalizedPortNumber {
    param(
        [object]$Value,
        [string]$Field
    )

    $text = [Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture)
    Assert-Contract (
        $text -cmatch "^[0-9]+$"
    ) "Compose port $Field must use an integer representation."
    $number = 0
    Assert-Contract (
        [int]::TryParse(
            $text,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$number
        ) -and
        $number -ge 1 -and
        $number -le 65535
    ) "Compose port $Field is outside the supported port range."
    return $number
}

function ConvertTo-NormalizedPort {
    param(
        [object]$Port,
        [string]$Context
    )

    Assert-ExactPropertySet `
        -Object $Port `
        -ExpectedProperties @("target", "published", "host_ip", "protocol", "mode") `
        -Context $Context
    return [pscustomobject][ordered]@{
        target = ConvertTo-NormalizedPortNumber -Value $Port.target -Field "$Context target"
        published = ConvertTo-NormalizedPortNumber `
            -Value $Port.published `
            -Field "$Context published"
        host_ip = [string]$Port.host_ip
        protocol = [string]$Port.protocol
        mode = [string]$Port.mode
    }
}

function New-ExpectedPort {
    param(
        [int]$Target,
        [int]$Published
    )

    return [pscustomobject][ordered]@{
        target = $Target
        published = $Published
        host_ip = "127.0.0.1"
        protocol = "tcp"
        mode = "ingress"
    }
}

function Assert-ExactPortSet {
    param(
        [object[]]$Ports,
        [object[]]$Expected,
        [string]$ServiceName
    )

    Assert-Contract (
        $Ports.Count -eq $Expected.Count
    ) "$ServiceName must publish exactly $($Expected.Count) approved port objects."
    $actualCanonical = @(
        for ($index = 0; $index -lt $Ports.Count; $index++) {
            (
                ConvertTo-NormalizedPort `
                    -Port $Ports[$index] `
                    -Context "$ServiceName port object $index"
            ) | ConvertTo-Json -Compress
        }
    ) | Sort-Object
    $expectedCanonical = @(
        $Expected | ForEach-Object { $_ | ConvertTo-Json -Compress }
    ) | Sort-Object
    Assert-Contract (
        ($actualCanonical -join "`n") -ceq ($expectedCanonical -join "`n")
    ) "$ServiceName port objects do not match the complete approved contract."
}

function ConvertTo-NormalizedVolumeMount {
    param(
        [object]$Mount,
        [string]$Context
    )

    $allowedMountProperties = @(
        "type",
        "source",
        "target",
        "read_only",
        "consistency",
        "volume"
    )
    $actualMountProperties = @(
        $Mount.PSObject.Properties | ForEach-Object { $_.Name }
    )
    $unexpectedMountProperties = @(
        $actualMountProperties | Where-Object { $_ -cnotin $allowedMountProperties }
    )
    Assert-Contract (
        $unexpectedMountProperties.Count -eq 0
    ) "$Context contains an unknown or additional mount property."
    foreach ($requiredProperty in @("type", "source", "target", "volume")) {
        Assert-Contract (
            $actualMountProperties -ccontains $requiredProperty
        ) "$Context is missing required property $requiredProperty."
    }

    $readOnly = $false
    $readOnlyProperty = $Mount.PSObject.Properties["read_only"]
    if ($null -ne $readOnlyProperty) {
        Assert-Contract (
            $readOnlyProperty.Value -is [bool]
        ) "$Context read_only must use a Boolean representation."
        $readOnly = [bool]$readOnlyProperty.Value
    }
    Assert-Contract (-not $readOnly) "$Context must not be read-only."

    $consistency = "consistent"
    $consistencyProperty = $Mount.PSObject.Properties["consistency"]
    if ($null -ne $consistencyProperty) {
        $consistency = [string]$consistencyProperty.Value
    }
    Assert-Contract (
        $consistency -ceq "consistent"
    ) "$Context must use the default consistent mount behavior."

    $volumeOptions = $Mount.volume
    Assert-Contract (
        $null -ne $volumeOptions
    ) "$Context must expose the rendered volume options object."
    $allowedVolumeProperties = @("nocopy")
    $actualVolumeProperties = @(
        $volumeOptions.PSObject.Properties | ForEach-Object { $_.Name }
    )
    $unexpectedVolumeProperties = @(
        $actualVolumeProperties | Where-Object { $_ -cnotin $allowedVolumeProperties }
    )
    Assert-Contract (
        $unexpectedVolumeProperties.Count -eq 0
    ) "$Context contains an unknown or additional volume option."

    $noCopy = $false
    $noCopyProperty = $volumeOptions.PSObject.Properties["nocopy"]
    if ($null -ne $noCopyProperty) {
        Assert-Contract (
            $noCopyProperty.Value -is [bool]
        ) "$Context volume.nocopy must use a Boolean representation."
        $noCopy = [bool]$noCopyProperty.Value
    }
    Assert-Contract (-not $noCopy) "$Context volume.nocopy must be false."

    return [pscustomobject][ordered]@{
        type = [string]$Mount.type
        source = [string]$Mount.source
        target = [string]$Mount.target
        read_only = $readOnly
        consistency = $consistency
        volume = [pscustomobject][ordered]@{
            nocopy = $noCopy
        }
    }
}

function New-ExpectedVolumeMount {
    param(
        [string]$Source,
        [string]$Target
    )

    return [pscustomobject][ordered]@{
        type = "volume"
        source = $Source
        target = $Target
        read_only = $false
        consistency = "consistent"
        volume = [pscustomobject][ordered]@{
            nocopy = $false
        }
    }
}

function Assert-ExactVolumeMount {
    param(
        [object]$Service,
        [object]$Expected,
        [string]$ServiceName
    )

    $mounts = @($Service.volumes)
    Assert-Contract (
        $mounts.Count -eq 1
    ) "$ServiceName must define exactly one volume mount object."
    $actualCanonical = (
        ConvertTo-NormalizedVolumeMount `
            -Mount $mounts[0] `
            -Context "$ServiceName volume mount"
    ) | ConvertTo-Json -Compress -Depth 4
    $expectedCanonical = $Expected | ConvertTo-Json -Compress -Depth 4
    Assert-Contract (
        $actualCanonical -ceq $expectedCanonical
    ) "$ServiceName volume mount does not match the complete approved contract."
}

function Get-OptionalProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    return $Object.PSObject.Properties[$Name]
}

function ConvertTo-DurationNanoseconds {
    param(
        [object]$Value,
        [string]$Field
    )

    if (
        $Value -is [byte] -or
        $Value -is [int16] -or
        $Value -is [int32] -or
        $Value -is [int64] -or
        $Value -is [uint16] -or
        $Value -is [uint32]
    ) {
        $numericValue = [int64]$Value
        Assert-Contract ($numericValue -ge 0) "Compose health check $Field must not be negative."
        return $numericValue
    }

    $text = [string]$Value
    Assert-Contract (
        -not [string]::IsNullOrWhiteSpace($text)
    ) "Compose health check $Field is missing."

    if ($text -cmatch "^[0-9]+$") {
        try {
            return [int64]::Parse($text, [Globalization.CultureInfo]::InvariantCulture)
        }
        catch {
            throw "Compose health check $Field is outside the supported duration range."
        }
    }

    $durationPattern = "(?<number>[0-9]+(?:\.[0-9]+)?)(?<unit>ns|us|[µμ]s|ms|s|m|h)"
    $matches = [regex]::Matches($text, $durationPattern)
    Assert-Contract (
        $matches.Count -gt 0 -and
        (($matches | ForEach-Object { $_.Value }) -join "") -ceq $text
    ) "Compose health check $Field has an unsupported duration representation."

    $unitFactors = [Collections.Generic.Dictionary[string, decimal]]::new(
        [StringComparer]::Ordinal
    )
    $unitFactors.Add("ns", [decimal]1)
    $unitFactors.Add("us", [decimal]1000)
    $unitFactors.Add("µs", [decimal]1000)
    $unitFactors.Add("μs", [decimal]1000)
    $unitFactors.Add("ms", [decimal]1000000)
    $unitFactors.Add("s", [decimal]1000000000)
    $unitFactors.Add("m", [decimal]60000000000)
    $unitFactors.Add("h", [decimal]3600000000000)
    [decimal]$total = 0
    foreach ($match in $matches) {
        $number = [decimal]::Parse(
            $match.Groups["number"].Value,
            [Globalization.CultureInfo]::InvariantCulture
        )
        $total += $number * $unitFactors[$match.Groups["unit"].Value]
    }
    Assert-Contract (
        $total -eq [decimal]::Truncate($total) -and
        $total -le [decimal][int64]::MaxValue
    ) "Compose health check $Field is not an exact supported nanosecond duration."
    return [int64]$total
}

function Assert-ExactVolumeDefinition {
    param(
        [object]$Volumes,
        [string]$Key,
        [string]$ProjectName
    )

    $volumeProperty = Get-OptionalProperty -Object $Volumes -Name $Key
    Assert-Contract ($null -ne $volumeProperty) "Compose volume $Key is missing."
    $definition = $volumeProperty.Value
    Assert-Contract ($null -ne $definition) "Compose volume $Key must have a rendered definition."
    Assert-ExactPropertySet `
        -Object $definition `
        -ExpectedProperties @("name") `
        -Context "Compose volume $Key definition"

    $nameProperty = Get-OptionalProperty -Object $definition -Name "name"
    Assert-Contract (
        $null -ne $nameProperty -and
        [string]$nameProperty.Value -ceq "${ProjectName}_$Key"
    ) "Compose volume $Key must use its project-scoped generated name."
}

function Assert-ExactHealthCheck {
    param(
        [object]$HealthCheck,
        [string[]]$ExpectedTest,
        [string]$ServiceName
    )

    Assert-Contract ($null -ne $HealthCheck) "$ServiceName health check is missing."
    Assert-ExactPropertySet `
        -Object $HealthCheck `
        -ExpectedProperties @(
        "test",
        "interval",
        "timeout",
        "retries",
        "start_period"
    ) `
        -Context "$ServiceName health check"

    $actualTest = @($HealthCheck.test)
    Assert-Contract (
        $actualTest.Count -eq $ExpectedTest.Count -and
        (($actualTest | ForEach-Object { [string]$_ }) -join "`n") -ceq
            ($ExpectedTest -join "`n")
    ) "$ServiceName health check command does not match the approved contract."

    foreach ($requiredProperty in @("interval", "timeout", "retries", "start_period")) {
        Assert-Contract (
            $null -ne (Get-OptionalProperty -Object $HealthCheck -Name $requiredProperty)
        ) "$ServiceName health check $requiredProperty is missing."
    }

    Assert-Contract (
        (ConvertTo-DurationNanoseconds -Value $HealthCheck.interval -Field "$ServiceName interval") -eq
            5000000000
    ) "$ServiceName health check interval must be exactly 5 seconds."
    Assert-Contract (
        (ConvertTo-DurationNanoseconds -Value $HealthCheck.timeout -Field "$ServiceName timeout") -eq
            5000000000
    ) "$ServiceName health check timeout must be exactly 5 seconds."
    Assert-Contract (
        [int]$HealthCheck.retries -eq 20
    ) "$ServiceName health check retries must be exactly 20."
    Assert-Contract (
        (
            ConvertTo-DurationNanoseconds `
                -Value $HealthCheck.start_period `
                -Field "$ServiceName start_period"
        ) -eq 10000000000
    ) "$ServiceName health check start_period must be exactly 10 seconds."
}

$resolvedComposePath = Resolve-RepositoryPath -Path $ComposeFile
$canonicalComposePath = Resolve-RepositoryPath -Path (
    Join-Path $repositoryRoot "docker-compose.yml"
)

$approvedSourceRootKeys = @(
    Get-SourceTopLevelKeys -Path $canonicalComposePath |
        Sort-Object
)
Assert-Contract (
    $approvedSourceRootKeys.Count -eq 3 -and
    ($approvedSourceRootKeys -join ",") -ceq "name,services,volumes"
) (
    "Canonical repository Compose source must contain exactly the name, services, " +
    "and volumes root properties."
)
$sourceRootKeys = @(
    Get-SourceTopLevelKeys -Path $resolvedComposePath |
        Sort-Object
)
Assert-Contract (
    $sourceRootKeys.Count -eq $approvedSourceRootKeys.Count -and
    ($sourceRootKeys -join "`n") -ceq ($approvedSourceRootKeys -join "`n")
) "Compose source must contain exactly the name, services, and volumes root properties."

$approvedSourceVolumeNames = @(
    Get-SourceTopLevelVolumeKeys -Path $canonicalComposePath |
        Sort-Object
)
Assert-Contract (
    $approvedSourceVolumeNames.Count -eq 2 -and
    ($approvedSourceVolumeNames -join ",") -ceq "postgres_data,qdrant_data"
) (
    "Canonical repository Compose source must contain exactly the postgres_data " +
    "and qdrant_data volume keys."
)
$sourceVolumeNames = @(
    Get-SourceTopLevelVolumeKeys -Path $resolvedComposePath |
        Sort-Object
)
Assert-Contract (
    $sourceVolumeNames.Count -eq $approvedSourceVolumeNames.Count -and
    ($sourceVolumeNames -join "`n") -ceq ($approvedSourceVolumeNames -join "`n")
) "Compose source must contain exactly the postgres_data and qdrant_data volume keys."

if ($SourceOnly) {
    Write-Output (
        "Compose source contract valid: root=name,services,volumes; " +
        "volumes=postgres_data,qdrant_data."
    )
    return
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

$resolvedEnvFile = Resolve-RepositoryPath -Path $EnvFile
$validatorArguments = @{ EnvFile = $resolvedEnvFile }
if ($Template) {
    $validatorArguments["Template"] = $true
}
& $environmentValidator @validatorArguments | Out-Null
$expected = Read-ValidatedEnvironment -Path $resolvedEnvFile

$savedEnvironment = Get-ProcessEnvironmentSnapshot -Names $environmentKeys
try {
    $validationProjectName = "medevidence-validation-" + [guid]::NewGuid().ToString("N")
    foreach ($key in $environmentKeys) {
        Remove-ProcessEnvironmentVariable -Name $key
    }

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

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $composeOutput = @(
            & $dockerExecutable compose `
                --project-name $validationProjectName `
                --env-file $resolvedEnvFile `
                --file $resolvedComposePath `
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
    Assert-ProcessEnvironmentMatchesSnapshot -Snapshot $savedEnvironment
}

if ($composeExitCode -ne 0) {
    throw "Docker Compose configuration rendering failed."
}
$renderedJson = ($composeOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
try {
    $configuration = $renderedJson | ConvertFrom-Json
}
catch {
    throw "Docker Compose returned invalid JSON configuration."
}
finally {
    $renderedJson = $null
    $composeOutput = $null
}

$serviceNames = @($configuration.services.PSObject.Properties.Name | Sort-Object)
Assert-ExactPropertySet `
    -Object $configuration `
    -ExpectedProperties @("name", "networks", "services", "volumes") `
    -Context "Rendered Compose root"
Assert-ExactPropertySet `
    -Object $configuration.services `
    -ExpectedProperties @("postgres", "qdrant") `
    -Context "Rendered Compose services"
Assert-Contract (
    ($serviceNames.Count -eq 2) -and
    (($serviceNames -join ",") -ceq "postgres,qdrant")
) "Compose must contain exactly the postgres and qdrant services."

$volumeNames = @($configuration.volumes.PSObject.Properties.Name | Sort-Object)
Assert-ExactPropertySet `
    -Object $configuration.volumes `
    -ExpectedProperties @("postgres_data", "qdrant_data") `
    -Context "Rendered Compose volumes"
Assert-Contract (
    ($volumeNames.Count -eq 2) -and
    (($volumeNames -join ",") -ceq "postgres_data,qdrant_data")
) "Compose must contain exactly the postgres_data and qdrant_data volumes."
$projectNameProperty = Get-OptionalProperty -Object $configuration -Name "name"
Assert-Contract (
    $null -ne $projectNameProperty -and
    [string]$projectNameProperty.Value -ceq $validationProjectName
) "Rendered Compose project name does not match the isolated validation project."
$projectName = [string]$projectNameProperty.Value
$networksProperty = Get-OptionalProperty -Object $configuration -Name "networks"
Assert-Contract ($null -ne $networksProperty) "Rendered Compose networks are missing."
Assert-ExactPropertySet `
    -Object $networksProperty.Value `
    -ExpectedProperties @("default") `
    -Context "Rendered Compose networks"
$defaultNetwork = $networksProperty.Value.default
Assert-ExactPropertySet `
    -Object $defaultNetwork `
    -ExpectedProperties @("ipam", "name") `
    -Context "Rendered Compose default network"
Assert-Contract (
    [string]$defaultNetwork.name -ceq "${projectName}_default"
) "Rendered Compose default network must use its project-scoped generated name."
Assert-ExactPropertySet `
    -Object $defaultNetwork.ipam `
    -ExpectedProperties @() `
    -Context "Rendered Compose default network IPAM"
Assert-ExactVolumeDefinition `
    -Volumes $configuration.volumes `
    -Key "postgres_data" `
    -ProjectName $projectName
Assert-ExactVolumeDefinition `
    -Volumes $configuration.volumes `
    -Key "qdrant_data" `
    -ProjectName $projectName

$postgres = $configuration.services.postgres
$qdrant = $configuration.services.qdrant
Assert-ExactPropertySet `
    -Object $postgres `
    -ExpectedProperties @(
        "command",
        "entrypoint",
        "environment",
        "healthcheck",
        "image",
        "networks",
        "ports",
        "volumes"
    ) `
    -Context "Rendered PostgreSQL service"
Assert-ExactPropertySet `
    -Object $qdrant `
    -ExpectedProperties @(
        "command",
        "entrypoint",
        "healthcheck",
        "image",
        "networks",
        "ports",
        "volumes"
    ) `
    -Context "Rendered Qdrant service"
foreach ($serviceEntry in @(
    @{ Name = "PostgreSQL"; Service = $postgres },
    @{ Name = "Qdrant"; Service = $qdrant }
)) {
    Assert-Contract (
        $null -eq $serviceEntry.Service.command
    ) "$($serviceEntry.Name) command must use the approved image default."
    Assert-Contract (
        $null -eq $serviceEntry.Service.entrypoint
    ) "$($serviceEntry.Name) entrypoint must use the approved image default."
    Assert-ExactPropertySet `
        -Object $serviceEntry.Service.networks `
        -ExpectedProperties @("default") `
        -Context "$($serviceEntry.Name) service networks"
    $defaultServiceNetwork = $serviceEntry.Service.networks.PSObject.Properties["default"]
    Assert-Contract (
        $null -ne $defaultServiceNetwork -and
        $null -eq $defaultServiceNetwork.Value
    ) "$($serviceEntry.Name) must use only the unmodified default network."
}
Assert-ExactPropertySet `
    -Object $postgres.environment `
    -ExpectedProperties @("POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_USER") `
    -Context "Rendered PostgreSQL environment"
foreach ($key in @("POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_USER")) {
    Assert-Contract (
        [string]$postgres.environment.PSObject.Properties[$key].Value -ceq $expected[$key]
    ) "Rendered PostgreSQL environment variable $key does not match the validated environment."
}
Assert-Contract (
    [string]$postgres.image -ceq $expected["POSTGRES_IMAGE"]
) "Rendered PostgreSQL image does not match the validated environment."
Assert-Contract (
    [string]$qdrant.image -ceq $expected["QDRANT_IMAGE"]
) "Rendered Qdrant image does not match the validated environment."

foreach ($service in @($postgres, $qdrant)) {
    Assert-Contract ($null -eq $service.PSObject.Properties["build"]) (
        "Compose services must not define build configuration."
    )
    $privilegedProperty = $service.PSObject.Properties["privileged"]
    Assert-Contract (
        $null -eq $privilegedProperty -or -not [bool]$privilegedProperty.Value
    ) "Compose services must not be privileged."
    $networkModeProperty = $service.PSObject.Properties["network_mode"]
    Assert-Contract (
        $null -eq $networkModeProperty -or [string]$networkModeProperty.Value -cne "host"
    ) "Compose services must not use host networking."
}

$expectedPostgresPorts = @(
    New-ExpectedPort `
        -Target 5432 `
        -Published ([int]$expected["POSTGRES_PORT"])
)
$expectedQdrantPorts = @(
    New-ExpectedPort `
        -Target 6333 `
        -Published ([int]$expected["QDRANT_HTTP_PORT"])
    New-ExpectedPort `
        -Target 6334 `
        -Published ([int]$expected["QDRANT_GRPC_PORT"])
)
Assert-ExactPortSet `
    -Ports @(Get-ServicePorts -Service $postgres) `
    -Expected $expectedPostgresPorts `
    -ServiceName "PostgreSQL"
Assert-ExactPortSet `
    -Ports @(Get-ServicePorts -Service $qdrant) `
    -Expected $expectedQdrantPorts `
    -ServiceName "Qdrant"

$expectedPostgresMount = New-ExpectedVolumeMount `
    -Source "postgres_data" `
    -Target "/var/lib/postgresql"
$expectedQdrantMount = New-ExpectedVolumeMount `
    -Source "qdrant_data" `
    -Target "/qdrant/storage"
Assert-ExactVolumeMount `
    -Service $postgres `
    -Expected $expectedPostgresMount `
    -ServiceName "PostgreSQL"
Assert-ExactVolumeMount `
    -Service $qdrant `
    -Expected $expectedQdrantMount `
    -ServiceName "Qdrant"

Assert-ExactHealthCheck `
    -HealthCheck $postgres.healthcheck `
    -ExpectedTest @(
        "CMD-SHELL",
        'pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}'
    ) `
    -ServiceName "PostgreSQL"
Assert-ExactHealthCheck `
    -HealthCheck $qdrant.healthcheck `
    -ExpectedTest @("CMD", "bash", "-c", ":> /dev/tcp/127.0.0.1/6333") `
    -ServiceName "Qdrant"

Write-Output (
    "Compose contract valid: services=postgres,qdrant; ports=localhost-only; " +
    "volumes=postgres_data,qdrant_data."
)
