[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
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

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    $templateLines = [IO.File]::ReadAllLines($templatePath)
    $runtimeLines = Set-EnvironmentValue -Lines $templateLines `
        -Key "POSTGRES_PASSWORD" -Value (New-RandomPassword)
    $runtimePath = Write-EnvironmentCase -Name "valid-runtime" -Lines $runtimeLines

    $runningBefore = Get-RunningContainerSet

    $collisionProjectName = "me-collision-$PID-$([guid]::NewGuid().ToString('N'))"
    $collisionVolumeName = "$collisionProjectName-sentinel"
    $collisionVolumeCreated = $false
    try {
        $null = & docker volume create `
            --label "com.docker.compose.project=$collisionProjectName" `
            $collisionVolumeName 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create the disposable collision-test volume."
        }
        $collisionVolumeCreated = $true

        $environmentBeforeCollision = @{}
        foreach ($key in $requiredKeys) {
            $environmentBeforeCollision[$key] = [Environment]::GetEnvironmentVariable(
                $key,
                "Process"
            )
        }

        $collisionRejected = $false
        try {
            $null = & $smokeTest -ProjectName $collisionProjectName 2>&1
        }
        catch {
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

        foreach ($key in $requiredKeys) {
            $environmentAfterCollision = [Environment]::GetEnvironmentVariable($key, "Process")
            if ($environmentAfterCollision -cne $environmentBeforeCollision[$key]) {
                throw "The collision path did not restore process environment variable $key."
            }
        }
        $results.Add("PASS collision-resource-survived-no-startup-environment-restored")
    }
    finally {
        if ($collisionVolumeCreated) {
            $null = & docker volume rm $collisionVolumeName 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to remove the disposable collision-test volume."
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

    $baseCompose = [IO.File]::ReadAllText($composePath).Replace("`r`n", "`n")
    $postgresPortMarker = '      - "127.0.0.1:${POSTGRES_PORT:?POSTGRES_PORT is required}:5432"'
    $qdrantHttpPortMarker = '      - "127.0.0.1:${QDRANT_HTTP_PORT:?QDRANT_HTTP_PORT is required}:6333"'
    $qdrantGrpcPortMarker = '      - "127.0.0.1:${QDRANT_GRPC_PORT:?QDRANT_GRPC_PORT is required}:6334"'
    $postgresMarker = "    volumes:`n      - postgres_data:/var/lib/postgresql"
    $qdrantMarker = "    volumes:`n      - qdrant_data:/qdrant/storage"
    $requiredMarkers = @(
        $postgresPortMarker,
        $qdrantHttpPortMarker,
        $qdrantGrpcPortMarker,
        $postgresMarker,
        $qdrantMarker
    )
    if (@($requiredMarkers | Where-Object { -not $baseCompose.Contains($_) }).Count -ne 0) {
        throw "The Compose fixture markers do not match docker-compose.yml."
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
