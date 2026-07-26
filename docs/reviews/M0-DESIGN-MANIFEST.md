# M0 Design Manifest

- Manifest version: 1
- Hash algorithm: SHA-256
- Generation timestamp (UTC): `2026-07-25T23:28:51Z`
- Included file count: `29`
- Entry file: `docs/reviews/M0-DESIGN-MANIFEST.sha256`
- Manifest file SHA-256: `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`

## Frozen corpus

The entry file freezes the raw bytes of the normative M0 design,
repository-level and nested instructions, architecture decisions, and
executable-configuration policy. Entries use repository-relative POSIX paths,
are sorted by ordinal path order, and have exactly two spaces between the
lowercase SHA-256 and path.

Included categories:

- root `AGENTS.md`, `README.md`, `.env.example`, `docker-compose.yml`,
  `Makefile`, `pyproject.toml`, and `.gitignore`;
- every file under `.github/workflows/`;
- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DATA_SOURCES.md`,
  `docs/EVALUATION_PLAN.md`, `docs/SECURITY.md`, and
  `docs/TRACEABILITY_MATRIX.md`;
- every ADR and the decisions index under `docs/decisions/`;
- every nested `AGENTS.md` under `src/`, `frontend/`, and `evaluation/`.

Excluded categories:

- approval, audit, and re-review records under `docs/reviews/`;
- both M0 design manifest files;
- non-normative interview notes;
- generated/raw/normalized data, vector indexes, database state, caches, logs,
  evaluation runs/results, reports, and exports;
- empty directory placeholders outside `.github/workflows/`;
- business implementation files, of which none exist at this freeze.

Any raw-byte modification to an included file invalidates this manifest,
conditional owner approval, and any review tied to its hash.

## Exact generation command

Run from the repository root in PowerShell:

```powershell
$fixed = @(
  ".env.example", ".gitignore", "AGENTS.md", "Makefile", "README.md",
  "docker-compose.yml", "pyproject.toml",
  "docs/ARCHITECTURE.md", "docs/DATA_SOURCES.md",
  "docs/EVALUATION_PLAN.md", "docs/PRD.md", "docs/SECURITY.md",
  "docs/TRACEABILITY_MATRIX.md"
)
$rootPath = (Get-Location).Path.TrimEnd("\")
$dynamic = @(
  Get-ChildItem -LiteralPath ".github/workflows" -Recurse -File
  Get-ChildItem -LiteralPath "docs/decisions" -File
  Get-ChildItem -LiteralPath "src","frontend","evaluation" -Recurse -File |
    Where-Object Name -eq "AGENTS.md"
) | ForEach-Object {
  $_.FullName.Substring($rootPath.Length + 1).Replace("\", "/")
}
$paths = [string[]]@($fixed + $dynamic | Sort-Object -Unique)
[Array]::Sort($paths, [StringComparer]::Ordinal)
$sha = [Security.Cryptography.SHA256]::Create()
$lines = foreach ($path in $paths) {
  $digest = $sha.ComputeHash([IO.File]::ReadAllBytes((Join-Path (Get-Location) $path)))
  "$((([BitConverter]::ToString($digest)) -replace "-", "").ToLowerInvariant())  $path"
}
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  (Join-Path (Get-Location) "docs/reviews/M0-DESIGN-MANIFEST.sha256"),
  (($lines -join "`n") + "`n"),
  $utf8NoBom
)
```

## Exact verification command

Run from the repository root in PowerShell:

```powershell
$manifestPath = "docs/reviews/M0-DESIGN-MANIFEST.sha256"
$lines = [IO.File]::ReadAllLines((Join-Path (Get-Location) $manifestPath))
$paths = [Collections.Generic.List[string]]::new()
$sha = [Security.Cryptography.SHA256]::Create()
foreach ($line in $lines) {
  if ($line -notmatch "^([0-9a-f]{64})  (.+)$") {
    throw "Invalid manifest line: $line"
  }
  $expected, $path = $Matches[1], $Matches[2]
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Missing manifested file: $path"
  }
  $actualBytes = $sha.ComputeHash(
    [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path))
  )
  $actual = (([BitConverter]::ToString($actualBytes)) -replace "-", "").ToLowerInvariant()
  if ($actual -ne $expected) {
    throw "Hash mismatch: $path"
  }
  $paths.Add($path)
}
$sorted = [string[]]$paths.ToArray()
[Array]::Sort($sorted, [StringComparer]::Ordinal)
if (($paths -join "`n") -cne ($sorted -join "`n")) {
  throw "Manifest paths are not ordinal-sorted"
}
$manifestHashBytes = $sha.ComputeHash(
  [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $manifestPath))
)
$actualManifestHash = (
  ([BitConverter]::ToString($manifestHashBytes)) -replace "-", ""
).ToLowerInvariant()
$metadata = [IO.File]::ReadAllText(
  (Resolve-Path -LiteralPath "docs/reviews/M0-DESIGN-MANIFEST.md")
)
if ($metadata -notmatch 'Manifest file SHA-256: `([0-9a-f]{64})`') {
  throw "Recorded manifest hash is missing"
}
if ($actualManifestHash -ne $Matches[1]) {
  throw "Overall manifest hash mismatch"
}
"Verified $($paths.Count) files; manifest SHA-256 $actualManifestHash"
```
