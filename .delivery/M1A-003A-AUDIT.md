# M1A-003A Delivery Audit

- Work item: `M1A-003A`
- Branch: `feat/m1a-003a-snapshot-manifests`
- Baseline: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Status: **CYCLE-4 LOCAL VALIDATION PASS; INDEPENDENT REVIEW, COMMIT, PUSH, AND HOSTED CI RERUN PENDING**
- Implementation candidate identity:
  `sha256:8df53196ccd2eb5f377eb42b0625269e925644385c02cd9cb72a6664ce419627`
  (2,235 bytes; 21 files)
- Implementation commit: `c3d724b2097c8df1249b217f610a78291039edbb`
- Implementation parent: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Evidence-record commit: `94e3d96f33e0752b34e6a016d19b9d1b7577f3f6`
- Pull request: `#4`

## Candidate scope

The candidate is limited to the Owner-authorized M1A-003A allowlist. It adds
typed journal contracts, namespaced identities, exact-byte PubMed raw-body
storage, canonical manifests, replay checks, and offline synthetic tests.
Connector changes expose body, safe headers, and observation time without an
ingestion import.

## Evidence state

The first independent review returned FAIL with five P1 and two P2 findings
covering positive complete evidence, fabricated empty raw responses, end-to-end
lock/capacity enforcement, leaf reparse containment, executable handoff/replay
binding, canonical journal parsing, and terminal-state invariants.

Fresh remediation-cycle-1 implementer evidence:

- focused ingestion and PubMed connector selection: 112 passed;
- full unit/contract offline suite: 382 passed, one expected
  `pytest-socket` warning, 86% aggregate coverage;
- repository-wide Ruff check: passed;
- repository-wide Ruff format check: passed for 32 files;
- MyPy `src`: passed for 17 source files.

Cycle 1 re-review returned FAIL with four P1 findings: retry history was
over-restricted, capture wrote fragments before validation, 4xx/5xx responses
could establish complete coverage, and partial matches did not require retained
evidence. The reviewer-provided abbreviated candidate label `ca9799...` is
historical after remediation edits.

Fresh remediation-cycle-2 evidence:

- focused ingestion and PubMed connector selection: 120 passed;
- full unit/contract offline suite: 390 passed, one expected
  `pytest-socket` warning, 86% aggregate coverage;
- repository-wide Ruff check: passed;
- repository-wide Ruff format check: passed for 32 files;
- MyPy `src`: passed for 17 source files;
- `git diff --check`: passed; and
- exact scope: all 21 authorized paths, zero missing, zero unexpected.

At the cycle-2 evidence point, independent re-review, terminal evidence audit,
commit, push, PR, hosted CI, merge, and integration had not occurred.

Cycle 2 re-review returned FAIL with one P1 and one P2 finding: partial
`matches` did not require usable nonempty 2xx evidence, and immutable journal
filenames were not bound to exact concrete record types before publication.
The reviewer-provided abbreviated label `4a7b...` is historical after cycle-3
edits.

Fresh remediation-cycle-3 evidence:

- focused ingestion and PubMed connector selection: 154 passed;
- full unit/contract offline suite: 424 passed, one expected
  `pytest-socket` warning, 86% aggregate coverage;
- repository-wide Ruff check: passed;
- repository-wide Ruff format check: passed for 32 files;
- MyPy `src`: passed for 17 source files;
- `git diff --check`: passed; and
- exact scope: all 21 authorized paths, zero missing, zero unexpected.

The terminal independent implementation reviewer returned PASS with no P0-P2
findings. It reported 35 targeted assertions passing; the exact selector was
not supplied and is not invented here. The independently reproduced broad
focused selection passed 197 tests, and the full offline unit/contract suite
passed 424 tests.

The terminal pre-commit evidence audit returned PASS for candidate
`sha256:8df53196ccd2eb5f377eb42b0625269e925644385c02cd9cb72a6664ce419627`
(2,235 bytes; 21 files). All three historical FAIL decisions and remediation
cycles remain preserved in the independent-review record.

Post-commit verification recorded exact implementation commit
`c3d724b2097c8df1249b217f610a78291039edbb`, parent
`a3fd66477046c9e026d7b2222e882cd94a84d535`, tree
`bf85382096c5b511b091cc43c0e3fc236605ee57`, exactly 21 committed paths, zero
path/content mismatches, and a clean worktree. Ruff, format, MyPy, focused 197,
and full 424/86% gates passed with the expected socket-block warning.

At the post-implementation verification point, no medical-source or other
network request, dependency operation, container, or database activity had
occurred. The only Git write at that point was the authorized local
implementation commit; the remote lifecycle had not yet begun.

## Hosted CI and cycle-4 remediation

The evidence record was subsequently committed at
`94e3d96f33e0752b34e6a016d19b9d1b7577f3f6`, pushed on the feature branch,
and opened as PR `#4`. Hosted run `31146015339` reported:

- `compose-config`: PASS;
- Windows Ruff check, Ruff format check, and MyPy: PASS; and
- Windows unit/contract tests: FAIL, with 422 passed and 2 failed.

Both test failures came from deterministic checkout portability:
`tests/fixtures/snapshots/manifest-v1.json` was checked out with CRLF on
Windows, while its canonical contract requires terminal LF bytes. The Project
Owner authorized cycle 4 solely to create root `.gitattributes` with:

```text
/tests/fixtures/snapshots/manifest-v1.json text eol=lf
```

This remediation changes checkout normalization only; it does not change
source, tests, dependencies, workflows, interfaces, database behavior, or
medical-source behavior. At this initial mechanical-node checkpoint, fresh
validation, independent review, a remediation commit, push, and hosted CI
rerun remained pending; no new PASS had yet been claimed.

Cycle-4 mechanical-node checks executed:

```text
git diff --check
[IO.File]::ReadAllBytes((Resolve-Path .gitattributes))
git status --porcelain=v1 --untracked-files=all
```

The attributes file was exactly 55 bytes, with one LF, zero CR bytes, and an
exact byte match to the Owner-required line. `git diff --check` passed, and the
worktree contained exactly the seven authorized cycle-4 paths with zero
missing or unexpected paths. These initial structural checks preceded the
fresh application validation below.

## Fresh cycle-4 local validation

Fresh local validation executed after the LF rule was added:

- `.gitattributes`: exactly 55 bytes, one LF, zero CR bytes;
- `git check-attr`: `text: set` and `eol: lf` for the manifest fixture;
- checked-out manifest fixture: 1,155 bytes, terminal LF, zero CR bytes;
- `git diff --check`: PASS;
- Ruff check: PASS;
- Ruff format check: PASS for 32 files;
- MyPy: PASS for 17 source files;
- broad focused selector: 197 passed; and
- full sockets-disabled unit/contract suite: 424 passed, one expected
  socket-block warning, 86% aggregate coverage.

These results establish fresh local cycle-4 validation only. Independent
cycle-4 review, the remediation commit, push, and hosted-CI rerun remain
pending. Hosted CI PASS is not claimed.

## Exact validation commands

The following exact commands were executed by the recorded implementation and
post-commit verification gates. They are preserved as evidence and are not
claimed as rerun by this evidence-only documentation node:

```text
uv run --locked --no-sync pytest tests/unit/ingestion tests/contract/ingestion tests/unit/domain/test_publications.py tests/contract/connectors/test_pubmed_connector.py tests/unit/test_dependency_boundaries.py --disable-socket
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
git diff --check
git status --porcelain=v1 --untracked-files=all
```

The independent reviewer's 35 targeted assertions are intentionally not
assigned a command here because its exact selector was not supplied.

## Historical evidence-finalization node validation

This evidence-only node did not rerun application tests or static-analysis
gates and does not claim that it did. It executed read-only identity,
structural, scope, and preservation checks after editing the six authorized
evidence paths:

```text
git rev-parse HEAD
git rev-parse "HEAD^"
git rev-parse "HEAD^{tree}"
git diff-tree --no-commit-id --name-only -r c3d724b2097c8df1249b217f610a78291039edbb
git diff --exit-code c3d724b2097c8df1249b217f610a78291039edbb -- src tests
git ls-tree -r c3d724b2097c8df1249b217f610a78291039edbb -- src tests
git hash-object -- <each tracked src/tests path>
git diff --check
git diff --name-only c3d724b2097c8df1249b217f610a78291039edbb
git status --porcelain=v1 --untracked-files=all
```

Observed results:

- HEAD, parent, and tree exactly matched the implementation identities above;
- the implementation commit contained exactly 21 paths;
- all 48 tracked `src` and `tests` worktree blobs matched their committed blob
  identities, with zero mismatches;
- structural UTF-8 readback checked all six documents, ten required status or
  identity assertions, and four obsolete/forbidden phrases with zero
  mismatches;
- `git diff --check` passed; and
- the worktree contained exactly six changed paths, all authorized for this
  evidence-only node, with zero missing, unexpected, or outside-scope paths.

## Remaining risk and manual verification

Independent cycle-4 review must inspect the current seven-path diff, confirm
that `.gitattributes` contains exactly
`/tests/fixtures/snapshots/manifest-v1.json text eol=lf` followed by one LF,
and verify that no source, test, dependency, workflow, interface, database, or
medical-source behavior changed.

Fresh full sockets-disabled offline validation has passed. Independent
cycle-4 review, the remediation commit, push, and hosted-CI rerun all remain
pending. No hosted CI PASS is claimed.

Manual verification: reproduce the LF attribute and fixture byte checks,
review the fresh local gate evidence, compare the worktree against the
seven-path cycle-4 allowlist, and confirm the future hosted rerun replaces
rather than obscures run `31146015339`.

The Owner should be able to answer:

1. Why does a complete acquisition require a completed page and retained
   complete response bytes?
2. How do the root writer lock, on-disk ledger, and atomic no-clobber publish
   primitive jointly protect raw, journal, and manifest files?
3. Why does replay require the expected manifest ID, ordered artifact links,
   and independently validated result count?
