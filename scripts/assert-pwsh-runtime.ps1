[CmdletBinding()]
param([switch]$Quiet)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-MedEvidencePowerShellRuntime {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Edition,

        [Parameter(Mandatory = $true)]
        [System.Management.Automation.SemanticVersion]$Version,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ExecutablePath
    )

    if ($Edition -cne "Core") {
        throw "MedEvidence requires PowerShell Core; found PSEdition '$Edition'."
    }
    if (-not [string]::IsNullOrEmpty($Version.PreReleaseLabel)) {
        throw (
            "MedEvidence requires a stable PowerShell release; " +
            "found $Version."
        )
    }
    if (
        $Version.Major -ne 7 -or
        $Version.Minor -ne 6 -or
        $Version.Patch -lt 4
    ) {
        throw (
            "MedEvidence requires PowerShell >= 7.6.4 and < 7.7.0; " +
            "found $Version."
        )
    }

    $executableName = [IO.Path]::GetFileName($ExecutablePath)
    if (
        $executableName -ine "pwsh" -and
        $executableName -ine "pwsh.exe"
    ) {
        throw (
            "MedEvidence requires the pwsh executable; found " +
            "'$executableName'."
        )
    }
}

$actualEdition = [string]$PSVersionTable.PSEdition
$actualVersion = $PSVersionTable.PSVersion
$actualExecutablePath = [string][Environment]::ProcessPath

Assert-MedEvidencePowerShellRuntime `
    -Edition $actualEdition `
    -Version $actualVersion `
    -ExecutablePath $actualExecutablePath

if (-not $Quiet) {
    $actualExecutableName = [IO.Path]::GetFileName($actualExecutablePath)
    Write-Output (
        "PowerShell runtime preflight: PASS " +
        "(PSEdition=$actualEdition; version=$actualVersion; " +
        "executable=$actualExecutableName; path=$actualExecutablePath)"
    )
}
