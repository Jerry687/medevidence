# ME-INFRA-PS7-002 delivery record

## Candidate

- Work item: `ME-INFRA-PS7-002`
- Baseline: `c226a632753e6fc65e8c84c74ec568d994612b7d`
- Branch: `codex/me-infra-ps7-002`
- Status: narrow SemanticVersion remediation, fresh local validation, and
  fresh independent review complete; terminal audit pending
- Superseded candidate: `ME-INFRA-PS7-001_STOPPED_SCOPE_CONTAMINATED`

## Frozen runtime

- Supported executable: `pwsh`
- Required edition: `Core`
- Required version: `>= 7.6.4` and `< 7.7.0`
- Unsupported: `powershell.exe`, Windows PowerShell 5.1, and versions outside
  the frozen interval
- Fallback: none

Every repository PowerShell entrypoint dot-sources
`scripts/assert-pwsh-runtime.ps1` before its work. GitHub Actions installs the
approved runtime before any PowerShell step and verifies it with the same
preflight.

## Official CI asset provenance

The release metadata was independently queried from the official
`PowerShell/PowerShell` GitHub repository with:

```text
gh api repos/PowerShell/PowerShell/releases/tags/v7.6.4
```

The returned asset digest fields bind the two CI downloads:

| Runner | Official asset | SHA-256 |
|---|---|---|
| Linux x64 | `powershell-7.6.4-linux-x64.tar.gz` | `4471b5a36bfe86ec7af8525d36bb1cacba0128e7aac22d05cc064bc00e604721` |
| Windows x64 | `PowerShell-7.6.4-win-x64.zip` | `80832551c52809301e6071c8bac977beb5a2f1ec953eb4db9f94deb953333793` |

`scripts/setup-pwsh-ci.sh` downloads only those release assets, verifies the
applicable digest before extraction, publishes the extracted directory to the
GitHub Actions path, and runs the shared runtime preflight.

## Scope boundary and review classification

This candidate changes runtime invocation and directly required tests only.
It does not redesign Windows path identity, DOS 8.3 behavior, reparse-point or
junction policy, dependency-audit trust boundaries, STOP evidence semantics,
or evidence-directory architecture.

Independent review must classify findings as follows:

- `A`: introduced or materially worsened by PS7-002; blocks this work item;
- `B`: reproducible on baseline `main`; record as pre-existing, non-blocking;
- `C`: unrelated hardening opportunity; record as follow-up, non-blocking.

Windows path identity, DOS 8.3, and reparse-point hardening observations belong
to the proposed successor `ME-SEC-WINPATH-001`; they are not authorized for
implementation here.

## Validation ledger

Implementation-node validation on 2026-08-13 used:

- `pwsh -NoLogo -NoProfile -File .\scripts\assert-pwsh-runtime.ps1` — PASS;
  `PSEdition=Core`, version `7.6.4`, executable `pwsh.exe`, process path
  `C:\Users\BoqiNiu\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe`;
- `pwsh -NoLogo -NoProfile -File
  .\scripts\test-infrastructure-contract.ps1 -RuntimePreflightOnly` — PASS,
  seven executable positive/rejection cases;
- PowerShell parser API over all nine `scripts/*.ps1` files — PASS, nine of
  nine;
- `pwsh -NoLogo -NoProfile -File .\scripts\validate-compose.ps1 -EnvFile
  .\.env.example -Template -SourceOnly` — PASS without container startup or
  pull;
- `bash -n scripts/setup-pwsh-ci.sh` — PASS;
- `uv run --locked --no-sync ruff check
  tests/unit/test_dependency_boundaries.py` — PASS;
- `uv run --locked --no-sync ruff format --check
  tests/unit/test_dependency_boundaries.py` — PASS;
- `uv run --locked --no-sync pytest
  tests/unit/test_dependency_boundaries.py --disable-socket -k 'powershell or
  retrieval_group_is_explicit' -q` — PASS, four passed and 34 deselected;
- `git diff --check` — PASS.

The single authorized batched remediation corrected the candidate-introduced
README structural assertion exposed by authoritative focused validation. The
test now normalizes whitespace before checking the unsupported Windows
PowerShell 5.1 statement, so Markdown line wrapping cannot change its meaning.
The focused Ruff and format checks passed, and
`test_active_repository_commands_use_only_pwsh` passed (`1 passed in 0.03s`).
No runtime behavior or scope expansion resulted.

Authoritative root validation on 2026-08-13 additionally produced:

- shared runtime preflight — PASS on Core `7.6.4` at the exact process path
  recorded above;
- Docker-free runtime matrix — PASS, seven cases;
- all nine PowerShell parsers — PASS;
- source-only Compose contract — PASS;
- `uv lock --check` — PASS, 68 resolved packages;
- `ruff check .` — PASS;
- `ruff format --check .` — PASS, 118 files already formatted;
- `mypy src` — PASS, 52 source files;
- focused dependency-boundary suite — PASS, 38 tests;
- full offline unit and contract suite with `--disable-socket` — PASS,
  1,730 tests, two known warnings, 79 percent coverage;
- Bash syntax — PASS;
- `git diff --check` — PASS; and
- active automation/configuration invocation scan — PASS. The only retained
  `powershell.exe` references in active candidate surfaces are the README's
  explicit unsupported statement and two negative runtime-test inputs.

The initial authoritative focused run had one failure in the new structural
test because Markdown wrapped `Windows PowerShell 5.1` across a newline. That
candidate-only defect was the work item's single remediation batch and the
entire affected gate was rerun successfully. Two subsequent `rg` audit command
attempts were corrected after, respectively, native-command quoting and an
overbroad allowed-reference selection; neither represented a repository defect
or changed candidate bytes.

The final pre-commit offline dependency Inventory is external to Git at
`D:\ProjectEvidence\medevidence\ME-INFRA-PS7-002\inventory-precommit-20260813-215800`:

- overall outcome: `pass`;
- advisory status: `not_run_offline`;
- external package count: 67;
- candidate commit: `c226a632753e6fc65e8c84c74ec568d994612b7d`;
- manifest SHA-256:
  `6d4557c591a6562b040bdf3f91be8e71fb5d88170339193a01399f4f1b540f99`;
- baseline audit candidate-file identity:
  `sha256:3aed5a4119a5d5821344588ddefff62d9b063fb37cc671119425a908eb43de15`.

## Independent review

Verdict: `FAIL — P0 0 / P1 1 / P2 0`.

The reviewer independently rebound all 16 candidate paths to aggregate
`127ff5e1655364cc6d37cfe591379f8c6195b0ff5e5e253d02a5784e884426c0`
using sorted `path<TAB>sha256` rows with a final LF. The reviewer reproduced an
`A` candidate defect: `assert-pwsh-runtime.ps1` accepts PowerShell semantic
versions such as `7.6.4-preview.1` and `7.6.4-rc.1` because the `[version]`
parameter and cast discard the prerelease label and compare them as stable
`7.6.4`. The executable output was `INPUT=7.6.4-preview.1`, `COERCED=7.6.4`,
`RESULT=ACCEPTED`; the release-candidate form was also accepted.

All other independent checks passed: actual Core `7.6.4` preflight, seven-case
runtime matrix, all nine parsers, Bash syntax, source-only Compose, 38 focused
tests, active invocation scan, workflow/installer inspection, official asset
hash binding, scope audit, and `git diff --check`. The excluded Windows path
hardening remains the non-blocking successor recommendation
`ME-SEC-WINPATH-001`.

The work item authorized only one candidate-introduced remediation batch, which
was already consumed by the README whitespace structural-test correction.
Therefore no prerelease remediation, terminal audit, commit, push, PR, hosted
CI, Ready transition, merge, or integrated verification was performed.

The Owner subsequently authorized one narrowly bounded remediation for this
candidate-introduced runtime-contract defect. The correction preserves
`System.Management.Automation.SemanticVersion`, rejects any non-empty
prerelease label before comparing `Major`, `Minor`, and `Patch`, and adds real
runtime-matrix cases for stable 7.6.4 and 7.6.5 acceptance plus preview, release
candidate, 7.5.9, 7.7.0, Desktop-edition, and unsupported-executable rejection.
No Windows path, reparse-point, dependency-audit, workflow, installer, README,
or Makefile semantics were reopened.

The narrow remediation node then produced fresh offline evidence:

- actual shared preflight — PASS on `PSEdition=Core`, stable version `7.6.4`,
  executable `pwsh.exe`, with the exact process path retained in command output;
- Docker-free runtime matrix — PASS, nine results including runtime resolution,
  stable 7.6.4 and 7.6.5 acceptance, and rejection of 7.6.4-preview.1,
  7.6.4-rc.1, 7.5.9, 7.7.0, Desktop edition, and `powershell.exe`;
- PowerShell parser API over all nine `scripts/*.ps1` files — PASS;
- focused Ruff and format checks for
  `tests/unit/test_dependency_boundaries.py` — PASS;
- focused offline dependency-boundary tests with sockets disabled — PASS,
  four passed and 34 deselected; and
- `git diff --check` — PASS.

This node made no network request, started no Docker workload, and performed no
Git staging, commit, push, PR, Ready, or merge operation. Fresh independent
review and terminal evidence audit remain pending after this remediation.

Authoritative root validation after the SemanticVersion remediation produced:

- actual shared preflight — PASS on Core stable `7.6.4` at the recorded exact
  `pwsh.exe` process path;
- focused executable matrix — PASS, nine outcomes, explicitly accepting stable
  `7.6.4` and `7.6.5` and rejecting `7.6.4-preview.1`, `7.6.4-rc.1`, `7.5.9`,
  `7.7.0`, Desktop edition, and `powershell.exe`;
- all nine PowerShell parsers — PASS;
- source-only Compose validation — PASS;
- `uv lock --check` — PASS, 68 resolved packages;
- `ruff check .` — PASS;
- `ruff format --check .` — PASS, 118 files already formatted;
- `mypy src` — PASS, 52 source files;
- focused dependency-boundary tests — PASS, 38 tests;
- full unit and contract suite with sockets disabled — PASS, 1,730 tests,
  two known warnings, and 79 percent coverage;
- Bash syntax and `git diff --check` — PASS; and
- active command-path scan — PASS, with only the explicitly unsupported README
  statement and negative executable-test inputs retaining `powershell.exe`.

The fresh post-remediation dependency Inventory is external to Git at
`D:\ProjectEvidence\medevidence\ME-INFRA-PS7-002\inventory-semver-final-20260813-221903`:

- overall outcome: `pass`;
- advisory status: `not_run_offline`;
- external package count: 67;
- candidate commit: `c226a632753e6fc65e8c84c74ec568d994612b7d`;
- manifest SHA-256:
  `3e4c31f0fbd6ff43354a30d773d15d4779e866ae1a3fe82d9936a8550fbc7e72`;
- baseline audit candidate-file identity:
  `sha256:384070d46e75aa58338bfdd25cfba17e9a07dd2f6a97048d3c793bb4b9961aea`.

## Fresh independent review after remediation

Verdict: `PASS — P0 0 / P1 0 / P2 0`.

The reviewer independently recomputed the exact 16-path aggregate as
`488efceed4c2f4a4f9ada9209dc2960b62b0ba00db163fe66060a78bec58bd54`
before and after review. Candidate bytes remained unchanged. The reviewer
independently confirmed the real Core `7.6.4` preflight, all nine executable
runtime outcomes, all nine parsers, source-only Compose, Bash syntax, focused
Ruff/format, all 38 focused offline tests, `git diff --check`, the active
invocation scan, both official CI archive hashes, and the final Inventory
manifest hash.

Classification was `A: none`, `B: no baseline defect blocks PS7-002`, and
`C: ME-SEC-WINPATH-001` for the deliberately excluded Windows path and reparse
hardening concerns. Review was offline and read-only, with no file, Git,
container, medical-source, or network mutation.

## Full infrastructure executable gate

The first terminal audit correctly identified that the complete existing
`test-infrastructure-contract.ps1` suite had not yet run; the runtime-only
matrix and source-only Compose checks did not replace that required gate. The
first full-harness attempt failed before creating its disposable volume because
the Docker Desktop daemon was stopped (`Unable to inspect the running-container
set`). Docker Desktop was then started solely for the required test.

`pwsh -NoLogo -NoProfile -File
.\scripts\test-infrastructure-contract.ps1` subsequently passed all 122 cases.
The harness performed Compose rendering and its disposable collision-volume
test without starting or pulling containers. Independent before/after checks
confirmed the container and volume sets were unchanged; the final container
count was zero. Docker Desktop was shut down afterward, restoring the initial
daemon/process state. Candidate implementation bytes did not change during
this gate.

No medical-source or corpus access occurred. Network activity was limited to
the Owner-authorized GitHub main fetch and official PowerShell release metadata
query; local validation and independent review were offline.
