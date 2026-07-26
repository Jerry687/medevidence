[CmdletBinding()]
param(
    [string]$EnvFile = ".env",
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$Template
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

    $unitFactors = @{
        "ns" = [decimal]1
        "us" = [decimal]1000
        "µs" = [decimal]1000
        "μs" = [decimal]1000
        "ms" = [decimal]1000000
        "s" = [decimal]1000000000
        "m" = [decimal]60000000000
        "h" = [decimal]3600000000000
    }
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

    $allowedProperties = @("name", "driver", "driver_opts", "external")
    $unexpectedProperties = @(
        $definition.PSObject.Properties.Name | Where-Object {
            $_ -cnotin $allowedProperties
        }
    )
    Assert-Contract (
        $unexpectedProperties.Count -eq 0
    ) "Compose volume $Key contains an unexpected definition property."

    $nameProperty = Get-OptionalProperty -Object $definition -Name "name"
    Assert-Contract (
        $null -ne $nameProperty -and
        [string]$nameProperty.Value -ceq "${ProjectName}_$Key"
    ) "Compose volume $Key must use its project-scoped generated name."

    $externalProperty = Get-OptionalProperty -Object $definition -Name "external"
    Assert-Contract (
        $null -eq $externalProperty -or -not [bool]$externalProperty.Value
    ) "Compose volume $Key must not be external."

    $driverProperty = Get-OptionalProperty -Object $definition -Name "driver"
    Assert-Contract (
        $null -eq $driverProperty -or
        [string]::IsNullOrWhiteSpace([string]$driverProperty.Value) -or
        [string]$driverProperty.Value -ceq "local"
    ) "Compose volume $Key must use the default local driver."

    $driverOptionsProperty = Get-OptionalProperty -Object $definition -Name "driver_opts"
    if ($null -ne $driverOptionsProperty -and $null -ne $driverOptionsProperty.Value) {
        $driverOptions = @($driverOptionsProperty.Value.PSObject.Properties)
        Assert-Contract (
            $driverOptions.Count -eq 0
        ) "Compose volume $Key must not define driver options."
    }
}

function Assert-ExactHealthCheck {
    param(
        [object]$HealthCheck,
        [string[]]$ExpectedTest,
        [string]$ServiceName
    )

    Assert-Contract ($null -ne $HealthCheck) "$ServiceName health check is missing."
    $allowedProperties = @(
        "test",
        "interval",
        "timeout",
        "retries",
        "start_period",
        "disable"
    )
    $unexpectedProperties = @(
        $HealthCheck.PSObject.Properties.Name | Where-Object {
            $_ -cnotin $allowedProperties
        }
    )
    Assert-Contract (
        $unexpectedProperties.Count -eq 0
    ) "$ServiceName health check contains an unexpected property."

    $actualTest = @($HealthCheck.test)
    Assert-Contract (
        $actualTest.Count -eq $ExpectedTest.Count -and
        (($actualTest | ForEach-Object { [string]$_ }) -join "`n") -ceq
            ($ExpectedTest -join "`n")
    ) "$ServiceName health check command does not match the approved contract."

    $disabledProperty = Get-OptionalProperty -Object $HealthCheck -Name "disable"
    Assert-Contract (
        $null -eq $disabledProperty -or -not [bool]$disabledProperty.Value
    ) "$ServiceName health check must not be disabled."

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

$resolvedEnvFile = Resolve-RepositoryPath -Path $EnvFile
$resolvedComposePath = Resolve-RepositoryPath -Path $ComposeFile
$validatorArguments = @{ EnvFile = $resolvedEnvFile }
if ($Template) {
    $validatorArguments["Template"] = $true
}
& $environmentValidator @validatorArguments | Out-Null
$expected = Read-ValidatedEnvironment -Path $resolvedEnvFile

$dockerCommand = Get-Command docker -ErrorAction Stop
$validationProjectName = "medevidence-validation-" + [guid]::NewGuid().ToString("N")
$savedEnvironment = @{}
foreach ($key in $environmentKeys) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    [Environment]::SetEnvironmentVariable($key, $null, "Process")
}

try {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $composeOutput = @(
            & $dockerCommand.Source compose `
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
    foreach ($key in $environmentKeys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], "Process")
    }
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
Assert-Contract (
    ($serviceNames.Count -eq 2) -and
    (($serviceNames -join ",") -ceq "postgres,qdrant")
) "Compose must contain exactly the postgres and qdrant services."

$volumeNames = @($configuration.volumes.PSObject.Properties.Name | Sort-Object)
Assert-Contract (
    ($volumeNames.Count -eq 2) -and
    (($volumeNames -join ",") -ceq "postgres_data,qdrant_data")
) "Compose must contain exactly the postgres_data and qdrant_data volumes."
$sourceVolumeNames = @(Get-SourceTopLevelVolumeKeys -Path $resolvedComposePath | Sort-Object)
Assert-Contract (
    ($sourceVolumeNames.Count -eq 2) -and
    (($sourceVolumeNames -join ",") -ceq "postgres_data,qdrant_data")
) "Compose source must contain exactly the postgres_data and qdrant_data volume keys."

$projectNameProperty = Get-OptionalProperty -Object $configuration -Name "name"
Assert-Contract (
    $null -ne $projectNameProperty -and
    [string]$projectNameProperty.Value -ceq $validationProjectName
) "Rendered Compose project name does not match the isolated validation project."
$projectName = [string]$projectNameProperty.Value
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
