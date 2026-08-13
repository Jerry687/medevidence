[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Inventory", "Audit")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [switch]$ReconcileOnly,

    [string]$PreservedAuditEvidencePath,

    [string]$AcquisitionRecordPath,

    [string]$LogicalBranch,

    [string]$ExpectedCommit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$expectedUvVersion = "0.11.32"
$expectedPythonVersion = "3.12.13"
$expectedPipAuditVersion = "2.10.1"
$repositoryRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
$repositoryPrefix = $repositoryRoot.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
$usingPreservedAuditEvidence = (
    -not [string]::IsNullOrWhiteSpace($PreservedAuditEvidencePath)
)
$hasAcquisitionRecord = (
    -not [string]::IsNullOrWhiteSpace($AcquisitionRecordPath)
)
$candidatePaths = @(
    ".delivery/M2-001-RETRIEVAL-HARNESS.md",
    ".github/workflows/quality.yml",
    ".gitignore",
    ".gitattributes",
    ".delivery/M1A-005-AUDIT.md",
    "alembic.ini",
    "alembic/env.py",
    "alembic/script.py.mako",
    "alembic/versions/20260806_01_m1a_003b_snapshot_metadata.py",
    ".github/workflows/dependency-audit.yml",
    "pyproject.toml",
    "README.md",
    "scripts/dependency-audit.ps1",
    "docs/INTERVIEW_NOTES.md",
    "docs/TRACEABILITY_MATRIX.md",
    "docs/reviews/M1A-005-INDEPENDENT-REVIEW-001.md",
    "docs/reviews/M2-001-REAL-BENCHMARK-INDEPENDENT-REVIEW-001.md",
    "evaluation/datasets.py",
    "evaluation/harness.py",
    "evaluation/README.md",
    "evaluation/run_evaluation.py",
    "scripts/bootstrap.ps1",
    "src/medevidence/retrieval/core.py",
    "src/medevidence/api/__init__.py",
    "src/medevidence/api/app.py",
    "src/medevidence/api/contracts.py",
    "src/medevidence/api/errors.py",
    "src/medevidence/api/routes.py",
    "src/medevidence/catalog.py",
    "src/medevidence/composition.py",
    "src/medevidence/connectors/__init__.py",
    "src/medevidence/connectors/pubmed/__init__.py",
    "src/medevidence/connectors/pubmed/client.py",
    "src/medevidence/connectors/pubmed/parsing.py",
    "src/medevidence/connectors/pubmed/policy.py",
    "src/medevidence/domain/__init__.py",
    "src/medevidence/domain/claims.py",
    "src/medevidence/domain/identifiers.py",
    "src/medevidence/domain/publications.py",
    "src/medevidence/domain/reports.py",
    "src/medevidence/domain/scope.py",
    "src/medevidence/domain/sources.py",
    "src/medevidence/persistence/__init__.py",
    "src/medevidence/persistence/config.py",
    "src/medevidence/persistence/models.py",
    "src/medevidence/persistence/repositories.py",
    "src/medevidence/persistence/session.py",
    "tests/unit/domain/test_provenance.py",
    "tests/unit/domain/test_publications.py",
    "tests/unit/domain/test_reports.py",
    "tests/unit/domain/test_scope.py",
    "tests/unit/domain/test_source_outcomes.py",
    "tests/unit/connectors/test_pubmed_parsing.py",
    "tests/unit/connectors/test_pubmed_policy.py",
    "tests/unit/test_dependency_boundaries.py",
    "tests/unit/evaluation/test_datasets.py",
    "tests/unit/retrieval/test_core.py",
    "tests/contract/evaluation/test_harness.py",
    "tests/unit/api/test_contracts.py",
    "tests/unit/api/test_errors.py",
    "tests/unit/api/test_routes.py",
    "tests/unit/persistence/test_config.py",
    "tests/unit/persistence/test_metadata.py",
    "tests/integration/persistence/test_migrations.py",
    "tests/integration/persistence/test_snapshot_metadata.py",
    "tests/integration/api/test_research_pubmed.py",
    "tests/contract/connectors/test_pubmed_connector.py",
    "tests/contract/test_offline_network.py",
    "tests/contract/api/test_openapi.py",
    "tests/e2e/test_live_pubmed.py",
    "tests/e2e/test_m1a_pubmed.py",
    "tests/fixtures/api/openapi-v1.json",
    "tests/fixtures/pubmed/valid_fetch.xml",
    "tests/fixtures/pubmed/valid_search.xml",
    "uv.lock"
)

if ($usingPreservedAuditEvidence -ne $hasAcquisitionRecord) {
    throw (
        "Preserved Audit evidence and its acquisition record must be " +
        "provided together."
    )
}
if (
    $usingPreservedAuditEvidence -and
    ($Mode -ne "Audit" -or $ReconcileOnly)
) {
    throw (
        "Preserved Audit evidence is supported only for fresh Audit " +
        "packaging."
    )
}

if (
    $resolvedOutput.Equals(
        $repositoryRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or
    $resolvedOutput.StartsWith(
        $repositoryPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Dependency-audit evidence must be written outside the Git repository."
}

$resolvedPreservedAuditEvidencePath = $null
$resolvedAcquisitionRecordPath = $null
if ($usingPreservedAuditEvidence) {
    $resolvedPreservedAuditEvidencePath = [System.IO.Path]::GetFullPath(
        $PreservedAuditEvidencePath
    )
    $resolvedAcquisitionRecordPath = [System.IO.Path]::GetFullPath(
        $AcquisitionRecordPath
    )
    foreach (
        $sourcePath in @(
            $resolvedPreservedAuditEvidencePath,
            $resolvedAcquisitionRecordPath
        )
    ) {
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Preserved Audit provenance input is missing: $sourcePath"
        }
        if (
            $sourcePath.Equals(
                $repositoryRoot,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            $sourcePath.StartsWith(
                $repositoryPrefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "Preserved Audit provenance inputs must remain outside Git."
        }
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $captured = & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw (
            "'$Command $($Arguments -join ' ')' failed with exit code " +
            "$LASTEXITCODE.`n$($captured -join "`n")"
        )
    }
}

function Invoke-CheckedCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $captured = & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw (
            "'$Command $($Arguments -join ' ')' failed with exit code " +
            "$LASTEXITCODE.`n$($captured -join "`n")"
        )
    }
    return ($captured -join "`n")
}

function Get-TextSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Content)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash($bytes)
    }
    finally {
        $sha256.Dispose()
    }
    return (
        "sha256:" +
        (($hashBytes | ForEach-Object { $_.ToString("x2") }) -join "")
    )
}

function Assert-ValidLogicalBranch {
    param(
        [AllowNull()]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Dependency evidence requires a named Git branch."
    }
    if ($Value -cne $Value.Trim()) {
        throw "Dependency evidence branch must not contain surrounding whitespace."
    }
    foreach ($character in $Value.ToCharArray()) {
        if ([char]::IsControl($character)) {
            throw "Dependency evidence branch must not contain control characters."
        }
    }
    if ([regex]::IsMatch($Value, "^[0-9a-fA-F]{40}$")) {
        throw "Dependency evidence branch must not be a commit SHA."
    }
    if (
        [regex]::IsMatch(
            $Value,
            "^(?i:(?:refs/)?pull/[1-9][0-9]*/(?:merge|head)|" +
            "[1-9][0-9]*/(?:merge|head))$"
        )
    ) {
        throw "Dependency evidence branch must not be a synthetic pull-request ref."
    }
    if ([regex]::IsMatch($Value, "^(?i:HEAD|detached|unknown)$")) {
        throw "Dependency evidence branch uses a reserved identity."
    }
    if ([regex]::IsMatch($Value, "^(?i:refs/)")) {
        throw "Dependency evidence branch must be a short branch name, not a full ref."
    }
    try {
        Invoke-CheckedCapture -Command "git" -Arguments @(
            "-C", $repositoryRoot, "check-ref-format", "--branch", $Value
        ) | Out-Null
    }
    catch {
        throw "Dependency evidence branch is not a valid Git branch name."
    }
    return $Value
}

function Get-CanonicalWindowsPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).Replace(
        [System.IO.Path]::AltDirectorySeparatorChar,
        [System.IO.Path]::DirectorySeparatorChar
    )
    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.Length -gt $pathRoot.Length) {
        return $fullPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    }
    return $fullPath
}

function Assert-RepositoryRootBinding {
    param(
        [Parameter(Mandatory = $true)]
        [string]$IntendedRepositoryRoot
    )

    $canonicalIntendedRoot = Get-CanonicalWindowsPath `
        -Path $IntendedRepositoryRoot
    try {
        $reportedTopLevel = (
            Invoke-CheckedCapture -Command "git" -Arguments @(
                "-C", $canonicalIntendedRoot, "rev-parse", "--show-toplevel"
            )
        ).Trim()
    }
    catch {
        throw "The intended repository root is not an active Git worktree."
    }
    $canonicalTopLevel = Get-CanonicalWindowsPath -Path $reportedTopLevel
    if (
        -not $canonicalIntendedRoot.Equals(
            $canonicalTopLevel,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw (
            "Git top-level mismatch: intended repository root " +
            "'$canonicalIntendedRoot' resolved to '$canonicalTopLevel'."
        )
    }
    return $canonicalIntendedRoot
}

function Assert-ValidExpectedCommit {
    param(
        [AllowNull()]
        [string]$Value
    )

    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        -not [regex]::IsMatch($Value, "^[0-9a-fA-F]{40}$")
    ) {
        throw "Expected candidate commit must be exactly 40 hexadecimal characters."
    }
    return $Value.ToLowerInvariant()
}

function Resolve-CandidateGitIdentity {
    param(
        [AllowNull()]
        [string]$ExplicitLogicalBranch,

        [bool]$HasExplicitLogicalBranch,

        [AllowNull()]
        [string]$ExplicitExpectedCommit,

        [bool]$HasExplicitExpectedCommit
    )

    $isGitHubActions = $env:GITHUB_ACTIONS -ceq "true"
    Assert-RepositoryRootBinding `
        -IntendedRepositoryRoot $repositoryRoot | Out-Null

    if ($HasExplicitLogicalBranch) {
        $resolvedLogicalBranch = $ExplicitLogicalBranch
    }
    elseif ($isGitHubActions) {
        $resolvedLogicalBranch = $env:MEDEV_EVIDENCE_BRANCH
    }
    else {
        $resolvedLogicalBranch = (
            Invoke-CheckedCapture -Command "git" -Arguments @(
                "-C", $repositoryRoot, "branch", "--show-current"
            )
        ).Trim()
    }
    $resolvedLogicalBranch = Assert-ValidLogicalBranch `
        -Value $resolvedLogicalBranch

    try {
        $actualHead = (
            Invoke-CheckedCapture -Command "git" -Arguments @(
                "-C", $repositoryRoot, "rev-parse", "HEAD"
            )
        ).Trim()
    }
    catch {
        throw "Candidate commit cannot be resolved from repository HEAD."
    }
    $actualHead = Assert-ValidExpectedCommit -Value $actualHead

    if ($HasExplicitExpectedCommit) {
        $resolvedExpectedCommit = Assert-ValidExpectedCommit `
            -Value $ExplicitExpectedCommit
    }
    elseif ($isGitHubActions) {
        $resolvedExpectedCommit = Assert-ValidExpectedCommit `
            -Value $env:MEDEV_EVIDENCE_COMMIT
    }
    else {
        $resolvedExpectedCommit = $actualHead
    }

    if ($actualHead -cne $resolvedExpectedCommit) {
        throw (
            "Candidate commit mismatch: checked out HEAD $actualHead does not " +
            "equal expected commit $resolvedExpectedCommit."
        )
    }

    return [ordered]@{
        logical_branch = $resolvedLogicalBranch
        candidate_commit = $actualHead
    }
}

$gitIdentity = Resolve-CandidateGitIdentity `
    -ExplicitLogicalBranch $LogicalBranch `
    -HasExplicitLogicalBranch $PSBoundParameters.ContainsKey("LogicalBranch") `
    -ExplicitExpectedCommit $ExpectedCommit `
    -HasExplicitExpectedCommit $PSBoundParameters.ContainsKey("ExpectedCommit")

$priorOffline = $env:UV_OFFLINE
if ($Mode -eq "Inventory" -or $ReconcileOnly -or $usingPreservedAuditEvidence) {
    $env:UV_OFFLINE = "1"
}
else {
    Remove-Item Env:\UV_OFFLINE -ErrorAction SilentlyContinue
}

$treePath = Join-Path $resolvedOutput "resolved-tree.json"
$requirementsPath = Join-Path $resolvedOutput "resolved-requirements.txt"
$sbomPath = Join-Path $resolvedOutput "sbom.cdx.json"
$licensesPath = Join-Path $resolvedOutput "licenses.json"
$auditPath = Join-Path $resolvedOutput "vulnerability-audit.json"
$rawAuditPath = Join-Path $resolvedOutput "vulnerability-audit.raw.json"
$acquisitionRecordOutputPath = Join-Path (
    $resolvedOutput
) "network-acquisition-command-record.json"
$exceptionsPath = Join-Path $resolvedOutput "exceptions.json"
$reconciliationPath = Join-Path $resolvedOutput "package-reconciliation.json"
$nativeInventoryPath = Join-Path $resolvedOutput "psycopg-binary-native-libraries.json"
$manifestPath = Join-Path $resolvedOutput "evidence-manifest.json"
$helperPath = Join-Path $resolvedOutput "dependency-evidence-helper.py"

Push-Location $repositoryRoot
try {
    if (-not $ReconcileOnly -and (Test-Path -LiteralPath $resolvedOutput)) {
        $existingEntries = @(Get-ChildItem -LiteralPath $resolvedOutput -Force)
        if ($existingEntries.Count -ne 0) {
            throw "Fresh dependency evidence requires a new or empty output directory."
        }
    }
    New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

    $helperScript = @'
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import pathlib
import re
import sys
import tomllib
from typing import Any

NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
PIN_PATTERN = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?==([^\s;\\]+)"
    r"(?:\s*;\s*.+)?$"
)
LOCAL_SOURCE_KEYS = {"editable", "path", "virtual", "workspace"}
UNRESOLVED_LICENSE_TERMS = {
    "absent",
    "ambiguous",
    "missing",
    "n_a",
    "needs_review",
    "none",
    "noassertion",
    "unlicensed",
    "unspecified",
    "unknown",
    "unresolved",
    "unreviewed",
}
LICENSE_DOCUMENT_FIELDS = {"packages"}
LICENSE_RECORD_FIELDS = {
    "license_classifiers",
    "license_expression",
    "name",
    "review_status",
    "version",
}
APPROVED_SPDX_LICENSE_IDS = {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "LGPL-3.0-only",
    "MIT",
    "MPL-2.0",
    "PSF-2.0",
}
# Conservative accepted grammar:
# APPROVED_ID (("AND" | "OR") APPROVED_ID)*.
# Parentheses, WITH exceptions, LicenseRef values, aliases, and every
# unlisted SPDX identifier fail closed pending focused review.
SPDX_ID_ALTERNATION = "|".join(
    re.escape(value) for value in sorted(APPROVED_SPDX_LICENSE_IDS)
)
SPDX_EXPRESSION_PATTERN = re.compile(
    rf"^(?:{SPDX_ID_ALTERNATION})"
    rf"(?: (?:AND|OR) (?:{SPDX_ID_ALTERNATION}))*$"
)
APPROVED_PYPI_LICENSE_CLASSIFIERS = {
    "License :: OSI Approved :: Apache Software License",
    "License :: OSI Approved :: BSD License",
    "License :: OSI Approved :: MIT License",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
    "License :: OSI Approved :: Python Software Foundation License",
}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"malformed JSON evidence {path.name}: {error}")


def normalize_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        fail(f"malformed package name: {name!r}")
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_version(version: str) -> str:
    if not isinstance(version, str) or not version or version.strip() != version:
        fail(f"malformed package version: {version!r}")
    if any(character.isspace() for character in version):
        fail(f"malformed package version: {version!r}")
    return version


class PackageSet:
    def __init__(self, representation: str) -> None:
        self.representation = representation
        self.packages: dict[str, str] = {}

    def add(self, name: Any, version: Any) -> None:
        normalized = normalize_name(name)
        exact_version = validate_version(version)
        if normalized in self.packages:
            fail(
                f"{self.representation} contains duplicate normalized package "
                f"name: {normalized}"
            )
        self.packages[normalized] = exact_version

    @property
    def items(self) -> tuple[str, ...]:
        return tuple(
            sorted(f"{name}=={version}" for name, version in self.packages.items())
        )

    @property
    def count(self) -> int:
        return len(self.packages)

    @property
    def set_hash(self) -> str:
        payload = "\n".join(self.items).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()


def is_local_source(name: Any, source: Any, kind: Any) -> bool:
    source_keys = set(source) if isinstance(source, dict) else set()
    if source_keys.intersection(LOCAL_SOURCE_KEYS):
        return True
    if kind == "workspace":
        return True
    return (
        isinstance(name, str)
        and normalize_name(name) == "medevidence"
        and (isinstance(kind, dict) or not source_keys)
    )


def packages_from_lock(path: pathlib.Path) -> PackageSet:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        fail(f"malformed uv.lock: {error}")
    records = data.get("package")
    if not isinstance(records, list) or not records:
        fail("uv.lock package records are missing or empty")
    result = PackageSet("uv.lock")
    for record in records:
        if not isinstance(record, dict):
            fail("uv.lock contains a malformed package record")
        name = record.get("name")
        version = record.get("version")
        source = record.get("source")
        if is_local_source(name, source, None):
            continue
        if not isinstance(source, dict) or "registry" not in source:
            fail(f"uv.lock external package has no registry source: {name!r}")
        result.add(name, version)
    if result.count == 0:
        fail("uv.lock external package set is empty")
    return result


def packages_from_tree(path: pathlib.Path) -> PackageSet:
    data = load_json(path)
    resolution = data.get("resolution") if isinstance(data, dict) else None
    if not isinstance(resolution, dict) or not resolution:
        fail("resolved-tree.json resolution is missing or empty")
    result = PackageSet("resolved-tree.json")
    for record in resolution.values():
        if not isinstance(record, dict):
            fail("resolved-tree.json contains a malformed package record")
        name = record.get("name")
        version = record.get("version")
        source = record.get("source")
        kind = record.get("kind")
        if is_local_source(name, source, kind):
            continue
        if isinstance(kind, dict):
            continue
        if kind != "package":
            fail(f"resolved tree contains an unknown record kind: {kind!r}")
        if not isinstance(source, dict) or "registry" not in source:
            fail(f"resolved tree external package has no registry source: {name!r}")
        result.add(name, version)
    if result.count == 0:
        fail("resolved-tree.json external package set is empty")
    return result


def packages_from_requirements(path: pathlib.Path) -> PackageSet:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        fail(f"malformed requirements evidence: {error}")
    result = PackageSet("resolved-requirements.txt")
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if not line.strip().startswith("--hash=sha256:"):
                fail(f"malformed requirements continuation: {line!r}")
            continue
        candidate = line.rstrip()
        if candidate.endswith("\\"):
            candidate = candidate[:-1].rstrip()
        match = PIN_PATTERN.fullmatch(candidate)
        if match is None:
            fail(f"malformed or unpinned requirement: {line!r}")
        result.add(match.group(1), match.group(2))
    if result.count == 0:
        fail("resolved-requirements.txt package set is empty")
    return result


def packages_from_sbom(path: pathlib.Path) -> PackageSet:
    data = load_json(path)
    records = data.get("components") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        fail("CycloneDX components are missing or empty")
    result = PackageSet("sbom.cdx.json")
    for record in records:
        if not isinstance(record, dict):
            fail("CycloneDX contains a malformed component")
        name = record.get("name")
        if isinstance(name, str) and normalize_name(name) == "medevidence":
            fail("CycloneDX unexpectedly contains the local editable project")
        result.add(name, record.get("version"))
    return result


def license_value_is_unresolved(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    terms = set(filter(None, normalized.split("_")))
    return normalized in UNRESOLVED_LICENSE_TERMS or bool(
        terms.intersection(UNRESOLVED_LICENSE_TERMS)
    )


def validate_license_expression(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        fail("license_expression must be a string or null")
    if not value.strip() or value.strip() != value:
        fail("license_expression must be a nonblank trimmed string or null")
    if license_value_is_unresolved(value):
        fail("license_expression contains an unresolved sentinel")
    if SPDX_EXPRESSION_PATTERN.fullmatch(value) is None:
        fail("license_expression is outside the approved SPDX-expression grammar")
    return value


def validate_license_classifiers(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        fail("license_classifiers must be an array")
    normalized: set[str] = set()
    validated: list[str] = []
    for classifier in value:
        if not isinstance(classifier, str):
            fail("license_classifiers contains a non-string member")
        if not classifier.strip() or classifier.strip() != classifier:
            fail("license_classifiers contains a blank or untrimmed member")
        ordinal_key = classifier.casefold()
        if ordinal_key in normalized:
            fail("license_classifiers contains a duplicate normalized classifier")
        normalized.add(ordinal_key)
        if classifier not in APPROVED_PYPI_LICENSE_CLASSIFIERS:
            fail("license_classifiers contains an unapproved PyPI classifier")
        validated.append(classifier)
    return tuple(validated)


def packages_from_licenses(
    path: pathlib.Path,
) -> tuple[PackageSet, dict[str, int]]:
    data = load_json(path)
    if not isinstance(data, dict) or set(data) != LICENSE_DOCUMENT_FIELDS:
        fail("licenses.json must contain the exact recognized document schema")
    records = data["packages"]
    if not isinstance(records, list) or not records:
        fail("license package records are missing or empty")
    result = PackageSet("licenses.json")
    review_counts = {
        "declared": 0,
        "needs_review": 0,
        "missing_metadata": 0,
    }
    for record in records:
        if not isinstance(record, dict):
            fail("licenses.json contains a malformed package record")
        if set(record) != LICENSE_RECORD_FIELDS:
            fail("license record fields do not match the exact recognized schema")
        review_status = record["review_status"]
        if not isinstance(review_status, str) or review_status != "declared":
            if isinstance(review_status, str) and review_status == "needs_review":
                review_counts["needs_review"] += 1
            fail("license review_status must equal exactly 'declared'")
        license_expression = validate_license_expression(
            record["license_expression"]
        )
        classifiers = validate_license_classifiers(
            record["license_classifiers"]
        )
        if license_expression is None and not classifiers:
            review_counts["missing_metadata"] += 1
            fail("license record has no valid declaration source")
        review_counts["declared"] += 1
        result.add(record["name"], record["version"])
    return result, review_counts


def packages_from_audit(
    path: pathlib.Path,
    mode: str,
) -> tuple[PackageSet | None, int, int]:
    data = load_json(path)
    if mode == "Inventory":
        if data != {"advisory_status": "not_run_offline"}:
            fail("offline vulnerability evidence must be the exact not-run sentinel")
        return None, 0, 0
    if not isinstance(data, dict):
        fail("vulnerability audit evidence is malformed")
    if data.get("audit_status") != "completed":
        fail("Audit reconciliation requires completed vulnerability evidence")
    if data.get("vulnerability_service") != "pypi":
        fail("Audit reconciliation requires the approved PyPI vulnerability service")
    reported_skipped_count = data.get("skipped_package_count")
    reported_vulnerability_count = data.get("vulnerability_count")
    if (
        not isinstance(reported_skipped_count, int)
        or isinstance(reported_skipped_count, bool)
        or reported_skipped_count < 0
    ):
        fail("vulnerability skipped-package summary is missing or malformed")
    if (
        not isinstance(reported_vulnerability_count, int)
        or isinstance(reported_vulnerability_count, bool)
        or reported_vulnerability_count < 0
    ):
        fail("vulnerability count summary is missing or malformed")
    if not isinstance(data.get("fixes"), list):
        fail("vulnerability audit fixes summary is missing or malformed")
    records = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        fail("vulnerability dependency records are missing or empty")
    result = PackageSet("vulnerability-audit.json")
    vulnerability_count = 0
    skipped_package_count = 0
    for record in records:
        if not isinstance(record, dict):
            fail("vulnerability audit contains a malformed dependency record")
        if record.get("skip_reason") not in {None, ""}:
            skipped_package_count += 1
        vulnerabilities = record.get("vulns")
        if not isinstance(vulnerabilities, list):
            fail("vulnerability dependency record has no advisory result")
        vulnerability_count += len(vulnerabilities)
        result.add(record.get("name"), record.get("version"))
    if reported_skipped_count != skipped_package_count:
        fail("vulnerability skipped-package summary disagrees with dependency records")
    if reported_vulnerability_count != vulnerability_count:
        fail("vulnerability count summary disagrees with dependency records")
    if skipped_package_count:
        fail("vulnerability advisory lookup is incomplete because packages were skipped")
    if vulnerability_count:
        fail("known vulnerabilities are present in the completed audit evidence")
    return result, vulnerability_count, skipped_package_count


def exception_count(path: pathlib.Path) -> int:
    data = load_json(path)
    records = data.get("approved_exceptions") if isinstance(data, dict) else None
    if not isinstance(records, list):
        fail("approved exception list is missing or malformed")
    if records:
        fail("dependency exceptions require explicit Owner approval")
    return len(records)


def exact_pins(path: pathlib.Path) -> dict[str, list[str]]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        fail(f"malformed pyproject.toml: {error}")
    production = data.get("project", {}).get("dependencies")
    groups = data.get("dependency-groups", {})
    development = groups.get("dev") if isinstance(groups, dict) else None
    retrieval = groups.get("retrieval") if isinstance(groups, dict) else None
    if not all(
        isinstance(group, list) for group in (production, development, retrieval)
    ):
        fail("direct dependency groups are missing")
    if retrieval != ["numpy==2.5.1", "scikit-learn==1.9.0"]:
        fail("retrieval direct pins differ from the exact Owner-approved pair")
    production_names = {
        PIN_PATTERN.fullmatch(pin).group(1).casefold()
        for pin in production
        if isinstance(pin, str) and PIN_PATTERN.fullmatch(pin) is not None
    }
    if production_names & {"numpy", "scikit-learn"}:
        fail("retrieval-only dependencies leaked into the production default surface")
    for pin in [*production, *development, *retrieval]:
        if not isinstance(pin, str) or PIN_PATTERN.fullmatch(pin) is None:
            fail(f"direct dependency is not an exact pin: {pin!r}")
    return {
        "production": sorted(production, key=str.casefold),
        "development": sorted(development, key=str.casefold),
        "retrieval": sorted(retrieval, key=str.casefold),
    }


def compare(reference: PackageSet, representation: PackageSet) -> None:
    reference_items = set(reference.items)
    representation_items = set(representation.items)
    if reference_items != representation_items:
        missing = sorted(reference_items - representation_items)
        extra = sorted(representation_items - reference_items)
        fail(
            f"{representation.representation} package set mismatch; "
            f"missing={missing}; extra={extra}"
        )


def create_license_inventory(requirements_path: pathlib.Path) -> dict[str, Any]:
    requirements = packages_from_requirements(requirements_path)
    records: list[dict[str, Any]] = []
    for normalized_name, expected_version in sorted(requirements.packages.items()):
        distribution = metadata.distribution(normalized_name)
        license_expression = distribution.metadata.get("License-Expression")
        legacy_license = distribution.metadata.get("License")
        classifiers = sorted(
            value
            for value in distribution.metadata.get_all("Classifier", [])
            if value.startswith("License ::")
        )
        if license_expression is not None:
            license_expression = validate_license_expression(license_expression)
        elif (
            isinstance(legacy_license, str)
            and legacy_license.strip() == legacy_license
            and SPDX_EXPRESSION_PATTERN.fullmatch(legacy_license) is not None
        ):
            license_expression = legacy_license
        validated_classifiers = list(validate_license_classifiers(classifiers))
        records.append(
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
                "license_expression": license_expression,
                "license_classifiers": validated_classifiers,
                "review_status": (
                    "declared"
                    if license_expression or validated_classifiers
                    else "needs_review"
                ),
            }
        )
        if validate_version(distribution.version) != expected_version:
            fail(f"installed metadata version mismatch for {normalized_name}")
    return {"packages": records}


def reconcile(arguments: list[str]) -> dict[str, Any]:
    if len(arguments) != 9:
        fail("reconcile requires mode and eight evidence paths")
    mode = arguments[0]
    if mode not in {"Inventory", "Audit"}:
        fail(f"unsupported reconciliation mode: {mode}")
    paths = [pathlib.Path(value) for value in arguments[1:]]
    lock = packages_from_lock(paths[0])
    tree = packages_from_tree(paths[2])
    requirements = packages_from_requirements(paths[3])
    sbom = packages_from_sbom(paths[4])
    licenses, license_review_counts = packages_from_licenses(paths[5])
    audit, vulnerability_count, skipped_package_count = packages_from_audit(paths[6], mode)
    approved_exception_count = exception_count(paths[7])
    representations = {
        "uv_lock": lock,
        "resolved_tree": tree,
        "resolved_requirements": requirements,
        "cyclonedx_sbom": sbom,
        "licenses": licenses,
    }
    if audit is not None:
        representations["vulnerability_audit"] = audit
    for name, representation in representations.items():
        if name != "uv_lock":
            compare(lock, representation)
    counts = {name: value.count for name, value in representations.items()}
    set_hashes = {name: value.set_hash for name, value in representations.items()}
    if audit is None:
        counts["vulnerability_audit"] = 0
        set_hashes["vulnerability_audit"] = None
    return {
        "schema_version": "1.0",
        "mode": mode,
        "overall_outcome": "pass",
        "canonical_package_set_sha256": lock.set_hash,
        "external_package_count": lock.count,
        "representation_counts": counts,
        "representation_set_sha256": set_hashes,
        "direct_dependency_pins": exact_pins(paths[1]),
        "exception_count": approved_exception_count,
        "vulnerability_count": vulnerability_count,
        "skipped_package_count": skipped_package_count,
        "license_review_counts": license_review_counts,
    }


def main() -> None:
    if len(sys.argv) < 2:
        fail("helper command is required")
    command = sys.argv[1]
    if command == "licenses":
        if len(sys.argv) != 3:
            fail("licenses requires a requirements path")
        output = create_license_inventory(pathlib.Path(sys.argv[2]))
    elif command == "reconcile":
        output = reconcile(sys.argv[2:])
    else:
        fail(f"unknown helper command: {command}")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
'@
    Write-Utf8NoBom -Path $helperPath -Content $helperScript

    $uvCommand = Get-Command uv -ErrorAction Stop
    $uvVersionOutput = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments @(
        "--version"
    )
    $actualUvVersion = ($uvVersionOutput -split "\s+")[1]
    if ($actualUvVersion -ne $expectedUvVersion) {
        throw "uv $expectedUvVersion is required; found $actualUvVersion."
    }

    $pythonVersion = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments @(
        "run", "--locked", "--no-sync", "python", "-c",
        "import platform; print(platform.python_version())"
    )
    if ($pythonVersion.Trim() -ne $expectedPythonVersion) {
        throw "CPython $expectedPythonVersion is required; found $($pythonVersion.Trim())."
    }
    $pipAuditVersionOutput = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments @(
        "run", "--locked", "--no-sync", "pip-audit", "--version"
    )
    $actualPipAuditVersion = ($pipAuditVersionOutput.Trim() -split "\s+")[-1]
    if ($actualPipAuditVersion -ne $expectedPipAuditVersion) {
        throw (
            "pip-audit $expectedPipAuditVersion is required; " +
            "found $actualPipAuditVersion."
        )
    }

    $psycopgBinaryVersion = Invoke-CheckedCapture `
        -Command $uvCommand.Source `
        -Arguments @(
            "run", "--locked", "--no-sync", "python", "-c",
            "import importlib.metadata as m; print(m.version('psycopg-binary'))"
        )
    if ($psycopgBinaryVersion.Trim() -ne "3.3.4") {
        throw "psycopg-binary 3.3.4 is required for native-library inventory."
    }
    $psycopgBinaryLibraryDirectory = Invoke-CheckedCapture `
        -Command $uvCommand.Source `
        -Arguments @(
            "run", "--locked", "--no-sync", "python", "-c",
            (
                "import importlib.metadata as m; " +
                "print(m.distribution('psycopg-binary').locate_file('psycopg_binary.libs'))"
            )
        )
    $psycopgBinaryLibraryDirectory = $psycopgBinaryLibraryDirectory.Trim()
    if (-not (Test-Path -LiteralPath $psycopgBinaryLibraryDirectory -PathType Container)) {
        throw "The psycopg-binary native-library directory is missing."
    }
    $nativeLibraries = @(
        foreach ($libraryName in @("libpq", "libssl", "libcrypto")) {
            $matches = @(
                Get-ChildItem -LiteralPath $psycopgBinaryLibraryDirectory -File |
                Where-Object { $_.Name -match "^$libraryName-.*\.dll$" }
            )
            if ($matches.Count -ne 1) {
                throw "Expected exactly one bundled $libraryName DLL; found $($matches.Count)."
            }
            $library = $matches[0]
            $productVersion = $library.VersionInfo.ProductVersion
            $fileVersion = $library.VersionInfo.FileVersion
            if (
                [string]::IsNullOrWhiteSpace($productVersion) -or
                [string]::IsNullOrWhiteSpace($fileVersion)
            ) {
                throw "Bundled $libraryName DLL does not expose version metadata."
            }
            [ordered]@{
                logical_name = $libraryName
                file_name = $library.Name
                product_version = $productVersion
                file_version = $fileVersion
                sha256 = (
                    Get-FileHash -Algorithm SHA256 -LiteralPath $library.FullName
                ).Hash.ToLowerInvariant()
            }
        }
    )

    $reconcileArguments = @(
        "run", "--locked", "--no-sync", "python", $helperPath,
        "reconcile", $Mode,
        (Join-Path $repositoryRoot "uv.lock"),
        (Join-Path $repositoryRoot "pyproject.toml"),
        $treePath,
        $requirementsPath,
        $sbomPath,
        $licensesPath,
        $auditPath,
        $exceptionsPath
    )
    if ($ReconcileOnly) {
        $reconciliation = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments (
            $reconcileArguments
        )
        $parsedReconciliation = $reconciliation | ConvertFrom-Json
        Write-Output "Package reconciliation: $($parsedReconciliation.overall_outcome)"
        Write-Output (
            "Canonical package set: " +
            "$($parsedReconciliation.canonical_package_set_sha256)"
        )
        return
    }

    Invoke-Checked -Command $uvCommand.Source -Arguments @("lock", "--check")

    $tree = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments @(
        "tree", "--locked", "--all-groups", "--universal", "--format", "json"
    )
    Write-Utf8NoBom -Path $treePath -Content $tree

    Invoke-Checked -Command $uvCommand.Source -Arguments @(
        "export", "--locked", "--all-groups", "--no-emit-project",
        "--no-annotate", "--no-header", "--format", "requirements.txt",
        "--output-file", $requirementsPath
    )
    Invoke-Checked -Command $uvCommand.Source -Arguments @(
        "export", "--locked", "--all-groups", "--no-emit-project",
        "--format", "cyclonedx1.5", "--output-file", $sbomPath
    )

    $licenses = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments @(
        "run", "--locked", "--no-sync", "python", $helperPath,
        "licenses", $requirementsPath
    )
    Write-Utf8NoBom -Path $licensesPath -Content $licenses
    Write-Utf8NoBom -Path $exceptionsPath -Content (
        "{`n  `"approved_exceptions`": []`n}"
    )

    $advisoryStatus = "not_run_offline"
    if ($Mode -eq "Audit") {
        if ($usingPreservedAuditEvidence) {
            Copy-Item -LiteralPath $resolvedPreservedAuditEvidencePath `
                -Destination $auditPath
            Copy-Item -LiteralPath $resolvedAcquisitionRecordPath `
                -Destination $acquisitionRecordOutputPath
        }
        else {
            & $uvCommand.Source run --locked --no-sync pip-audit `
                --requirement $requirementsPath `
                --no-deps `
                --disable-pip `
                --require-hashes `
                --vulnerability-service pypi `
                --format json `
                --output $rawAuditPath
            if ($LASTEXITCODE -ne 0) {
                throw "The networked vulnerability audit failed closed with exit code $LASTEXITCODE."
            }
            if (-not (Test-Path -LiteralPath $rawAuditPath -PathType Leaf)) {
                throw "The vulnerability audit completed without writing evidence."
            }
            $rawAudit = Get-Content -Raw -LiteralPath $rawAuditPath | ConvertFrom-Json
            $auditDependencies = @($rawAudit.dependencies)
            if ($auditDependencies.Count -eq 0) {
                throw "The vulnerability audit returned no dependency records."
            }
            $skippedPackageCount = @(
                $auditDependencies |
                Where-Object {
                    $skipReason = $_.PSObject.Properties["skip_reason"]
                    $null -ne $skipReason -and
                    $skipReason.Value -notin @($null, "")
                }
            ).Count
            $vulnerabilityCount = @(
                $auditDependencies |
                ForEach-Object { @($_.vulns) }
            ).Count
            if ($skippedPackageCount -ne 0) {
                throw "The vulnerability audit skipped one or more locked packages."
            }
            if ($vulnerabilityCount -ne 0) {
                throw "The vulnerability audit found one or more known vulnerabilities."
            }
            $completedAudit = [ordered]@{
                audit_status = "completed"
                vulnerability_service = "pypi"
                skipped_package_count = $skippedPackageCount
                vulnerability_count = $vulnerabilityCount
                dependencies = $auditDependencies
                fixes = @($rawAudit.fixes)
            }
            Write-Utf8NoBom -Path $auditPath -Content (
                $completedAudit | ConvertTo-Json -Depth 20
            )
            Remove-Item -LiteralPath $rawAuditPath -Force
        }
        $advisoryStatus = "passed_no_known_vulnerabilities"
    }
    else {
        Write-Utf8NoBom -Path $auditPath -Content (
            "{`n  `"advisory_status`": `"not_run_offline`"`n}"
        )
    }

    $nativeInventory = [ordered]@{
        schema_version = "1.0"
        distribution = "psycopg-binary"
        distribution_version = $psycopgBinaryVersion.Trim()
        platform = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        process_architecture = (
            [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
        )
        dependency_roles = [ordered]@{
            fastapi = "production versioned HTTP transport adapter"
            starlette = "transitive ASGI routing and in-process transport foundation"
            annotated_doc = "transitive FastAPI annotation metadata"
            sqlalchemy = "production runtime persistence library"
            alembic = "production schema-migration tooling"
            psycopg_binary = "production PostgreSQL runtime driver and bundled native libraries"
        }
        advisory_status = $advisoryStatus
        advisory_monitoring_owner = "MedEvidence Project Owner"
        patch_decision_owner = "MedEvidence Project Owner"
        libraries = $nativeLibraries
    }
    Write-Utf8NoBom -Path $nativeInventoryPath -Content (
        $nativeInventory | ConvertTo-Json -Depth 10
    )

    $reconciliation = Invoke-CheckedCapture -Command $uvCommand.Source -Arguments (
        $reconcileArguments
    )
    Write-Utf8NoBom -Path $reconciliationPath -Content $reconciliation
    $parsedReconciliation = $reconciliation | ConvertFrom-Json

    $evidenceFiles = @(
        $treePath,
        $requirementsPath,
        $sbomPath,
        $licensesPath,
        $auditPath,
        $exceptionsPath,
        $reconciliationPath,
        $nativeInventoryPath
    )
    if ($usingPreservedAuditEvidence) {
        $evidenceFiles += $acquisitionRecordOutputPath
    }
    foreach ($evidenceFile in $evidenceFiles) {
        if (
            -not (Test-Path -LiteralPath $evidenceFile -PathType Leaf) -or
            (Get-Item -LiteralPath $evidenceFile).Length -eq 0
        ) {
            throw "Dependency-audit evidence is missing or empty: $evidenceFile"
        }
    }

    $candidateFileHashes = @(
        foreach ($candidatePath in ($candidatePaths | Sort-Object)) {
            $absolutePath = Join-Path $repositoryRoot (
                $candidatePath.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
            )
            if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
                throw "Candidate repository file is missing: $candidatePath"
            }
            $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $absolutePath
            [ordered]@{
                path = $candidatePath
                sha256 = $hash.Hash.ToLowerInvariant()
            }
        }
    )
    $candidateIdentityPayload = (
        $candidateFileHashes |
        ForEach-Object { "$($_.path)`t$($_.sha256)" }
    ) -join "`n"
    $candidateFileSetIdentity = Get-TextSha256 -Content $candidateIdentityPayload
    $dependencyAuditScriptSha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath
    ).Hash.ToLowerInvariant()

    $acquisitionProvenance = $null
    if ($usingPreservedAuditEvidence) {
        $acquisitionRecord = (
            Get-Content -Raw -LiteralPath $acquisitionRecordOutputPath |
            ConvertFrom-Json
        )
        $requiredAcquisitionFields = @(
            "schema_version",
            "acquisition_method",
            "vulnerability_service",
            "external_request_count",
            "original_network_acquired_at_utc",
            "original_network_result_identity",
            "original_network_result_identity_basis_canonical_json",
            "original_queried_package_set_identity",
            "original_package_count",
            "cache_replay_performed",
            "cache_replay_packaged_at_utc",
            "cache_replay_reason",
            "cache_replay_network_disabled",
            "cache_replay_network_control",
            "dependency_input_sha256",
            "pyproject_sha256",
            "uv_lock_sha256",
            "preserved_cache_replay_audit_sha256",
            "source_precommit_v3_audit_manifest_sha256",
            "source_precommit_v3_inventory_manifest_sha256",
            "second_live_request_performed",
            "source_records"
        )
        $actualAcquisitionFields = @(
            $acquisitionRecord.PSObject.Properties.Name | Sort-Object
        )
        $expectedAcquisitionFields = @(
            $requiredAcquisitionFields | Sort-Object
        )
        if (
            (Compare-Object $expectedAcquisitionFields $actualAcquisitionFields)
        ) {
            throw "The acquisition command record has an unexpected schema."
        }
        if (
            $acquisitionRecord.schema_version -ne "1.0" -or
            $acquisitionRecord.acquisition_method -ne "network_then_cache_replay" -or
            $acquisitionRecord.vulnerability_service -ne "pypi" -or
            $acquisitionRecord.external_request_count -ne 1 -or
            $acquisitionRecord.original_package_count -ne 46 -or
            $acquisitionRecord.cache_replay_performed -ne $true -or
            $acquisitionRecord.cache_replay_network_disabled -ne $true -or
            $acquisitionRecord.second_live_request_performed -ne $false
        ) {
            throw "The acquisition command record violates the approved sequence."
        }
        $expectedReplayReason = (
            "evidence wrapping was repeated after correction of the optional " +
            "skip_reason StrictMode handling defect"
        )
        $expectedNetworkControl = (
            "HTTP(S) proxy variables directed to closed loopback 127.0.0.1:9"
        )
        if (
            $acquisitionRecord.cache_replay_reason -cne $expectedReplayReason -or
            $acquisitionRecord.cache_replay_network_control -cne $expectedNetworkControl
        ) {
            throw "The acquisition command record does not describe the preserved replay."
        }
        foreach (
            $timestampValue in @(
                $acquisitionRecord.original_network_acquired_at_utc,
                $acquisitionRecord.cache_replay_packaged_at_utc
            )
        ) {
            $parsedTimestamp = [DateTimeOffset]::MinValue
            if (
                -not [DateTimeOffset]::TryParse(
                    $timestampValue,
                    [ref]$parsedTimestamp
                )
            ) {
                throw "The acquisition command record contains an invalid timestamp."
            }
        }
        $calculatedResultIdentity = Get-TextSha256 -Content (
            $acquisitionRecord.original_network_result_identity_basis_canonical_json
        )
        if (
            $acquisitionRecord.original_network_result_identity -cne (
                $calculatedResultIdentity
            )
        ) {
            throw "The original network result identity cannot be reproduced."
        }
        $requirementsSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $requirementsPath
        ).Hash.ToLowerInvariant()
        $pyprojectSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath (
                Join-Path $repositoryRoot "pyproject.toml"
            )
        ).Hash.ToLowerInvariant()
        $uvLockSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath (
                Join-Path $repositoryRoot "uv.lock"
            )
        ).Hash.ToLowerInvariant()
        $preservedAuditSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $auditPath
        ).Hash.ToLowerInvariant()
        if (
            $acquisitionRecord.dependency_input_sha256 -cne $requirementsSha256 -or
            $acquisitionRecord.pyproject_sha256 -cne $pyprojectSha256 -or
            $acquisitionRecord.uv_lock_sha256 -cne $uvLockSha256 -or
            $acquisitionRecord.preserved_cache_replay_audit_sha256 -cne (
                $preservedAuditSha256
            ) -or
            $acquisitionRecord.original_queried_package_set_identity -cne (
                $parsedReconciliation.canonical_package_set_sha256
            )
        ) {
            throw "Dependency inputs or preserved evidence changed after acquisition."
        }
        $acquisitionRecordHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath (
                $acquisitionRecordOutputPath
            )
        ).Hash.ToLowerInvariant()
        $acquisitionProvenance = [ordered]@{
            acquisition_method = "network_then_cache_replay"
            vulnerability_service = "pypi"
            external_request_count = 1
            original_network_acquired_at_utc = (
                $acquisitionRecord.original_network_acquired_at_utc
            )
            original_network_result_identity = (
                $acquisitionRecord.original_network_result_identity
            )
            original_queried_package_set_identity = (
                $acquisitionRecord.original_queried_package_set_identity
            )
            original_package_count = 46
            cache_replay_performed = $true
            cache_replay_packaged_at_utc = (
                [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            )
            cache_replay_reason = $expectedReplayReason
            cache_replay_network_disabled = $true
            cache_replay_network_control = $expectedNetworkControl
            final_package_set_identity = (
                $parsedReconciliation.canonical_package_set_sha256
            )
            final_candidate_identity = $candidateFileSetIdentity
            final_dependency_script_sha256 = $dependencyAuditScriptSha256
            dependency_input_changed_between_acquisition_and_packaging = $false
            pyproject_changed_between_acquisition_and_packaging = $false
            uv_lock_changed_between_acquisition_and_packaging = $false
            second_live_request_performed = $false
            provenance_evidence_files = @(
                [ordered]@{
                    file = "network-acquisition-command-record.json"
                    sha256 = $acquisitionRecordHash
                },
                [ordered]@{
                    file = "vulnerability-audit.json"
                    sha256 = $preservedAuditSha256
                }
            )
        }
    }

    $evidenceFileHashes = @(
        foreach ($evidenceFile in $evidenceFiles) {
            $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $evidenceFile
            [ordered]@{
                file = [System.IO.Path]::GetFileName($evidenceFile)
                sha256 = $hash.Hash.ToLowerInvariant()
            }
        }
    )
    $manifest = [ordered]@{
        schema_version = "3.0"
        mode = $Mode
        overall_outcome = "pass"
        advisory_status = $advisoryStatus
        logical_branch = $gitIdentity.logical_branch
        candidate_commit = $gitIdentity.candidate_commit
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString(
            "yyyy-MM-ddTHH:mm:ss.fffZ"
        )
        uv_version = $actualUvVersion
        python_version = $pythonVersion.Trim()
        pip_audit_version = $actualPipAuditVersion
        output_directory = $resolvedOutput
        dependency_audit_script_sha256 = $dependencyAuditScriptSha256
        candidate_file_count = $candidateFileHashes.Count
        candidate_file_set_identity = $candidateFileSetIdentity
        candidate_files = $candidateFileHashes
        direct_dependency_pins = $parsedReconciliation.direct_dependency_pins
        external_package_count = $parsedReconciliation.external_package_count
        representation_counts = $parsedReconciliation.representation_counts
        representation_set_sha256 = (
            $parsedReconciliation.representation_set_sha256
        )
        canonical_package_set_sha256 = (
            $parsedReconciliation.canonical_package_set_sha256
        )
        exception_count = $parsedReconciliation.exception_count
        vulnerability_count = $parsedReconciliation.vulnerability_count
        skipped_package_count = $parsedReconciliation.skipped_package_count
        license_review_counts = $parsedReconciliation.license_review_counts
        dependency_roles = $nativeInventory.dependency_roles
        native_library_advisory_monitoring_owner = (
            $nativeInventory.advisory_monitoring_owner
        )
        native_library_patch_decision_owner = $nativeInventory.patch_decision_owner
        evidence_files = $evidenceFileHashes
    }
    if ($usingPreservedAuditEvidence) {
        $manifest.acquisition_provenance = $acquisitionProvenance
    }
    Write-Utf8NoBom -Path $manifestPath -Content (
        $manifest | ConvertTo-Json -Depth 10
    )

    $manifestHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath
    ).Hash.ToLowerInvariant()
    if ($env:GITHUB_STEP_SUMMARY) {
        $summary = @(
            "## MedEvidence dependency audit",
            "",
            "- Mode: ``$Mode``",
            "- Result: ``pass``",
            "- Advisory status: ``$advisoryStatus``",
            "- uv: ``$actualUvVersion``",
            "- Python: ``$($pythonVersion.Trim())``",
            "- pip-audit: ``$actualPipAuditVersion``",
            "- Logical branch: ``$($gitIdentity.logical_branch)``",
            "- Candidate commit: ``$($gitIdentity.candidate_commit)``",
            "- Candidate file set: ``$candidateFileSetIdentity``",
            "- Evidence manifest SHA-256: ``$manifestHash``"
        ) -join "`n"
        Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $summary
    }

    Write-Output "Dependency evidence: $resolvedOutput"
    Write-Output "Advisory status: $advisoryStatus"
    Write-Output (
        "External package count: $($parsedReconciliation.external_package_count)"
    )
    Write-Output "Candidate file set: $candidateFileSetIdentity"
    Write-Output "Evidence manifest SHA-256: $manifestHash"
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $helperPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $rawAuditPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $priorOffline) {
        Remove-Item Env:\UV_OFFLINE -ErrorAction SilentlyContinue
    }
    else {
        $env:UV_OFFLINE = $priorOffline
    }
}
