# M1A-003A Delivery Audit

- Work item: `M1A-003A`
- Branch: `feat/m1a-003a-snapshot-manifests`
- Baseline: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Status: **FINAL REMEDIATION CYCLE 3 IMPLEMENTED; RE-REVIEW AND AUDIT PENDING**
- Candidate commit: not created

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

Independent re-review, terminal evidence audit, commit, push, PR, hosted CI,
merge, and integration have not occurred and are not claimed.

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

Independent re-review and terminal evidence audit remain pending. No final
independent PASS is claimed.

No medical-source or other network request occurred. No dependency was
installed or resolved. No container or database was started or contacted. No
Git write was performed.

## Exact validation commands

```text
uv run --locked --no-sync pytest tests/unit/ingestion tests/contract/ingestion tests/contract/connectors/test_pubmed_connector.py --disable-socket -q
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
git diff --check
git status --porcelain=v1 --untracked-files=all
```

## Remaining risk and manual verification

Independent re-review must reproduce the corrected counterexamples and inspect
the actual diff. Terminal evidence audit must then confirm scope, commands,
network state, and candidate identity before any local commit is authorized.

Manual verification: run the commands above from the repository root, confirm
424 offline tests and 86% aggregate coverage, then compare all status paths
against the 21-path Owner allowlist.

The Owner should be able to answer:

1. Why does a complete acquisition require a completed page and retained
   complete response bytes?
2. How do the root writer lock, on-disk ledger, and atomic no-clobber publish
   primitive jointly protect raw, journal, and manifest files?
3. Why does replay require the expected manifest ID, ordered artifact links,
   and independently validated result count?
