# M1B-CADEC-001 delivery record

- Status: `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`
- Branch: `feat/m1b-cadec-001-asset-freeze`
- Baseline: `46c799368e9cd1ed3f2a2c956931d921999044e1`
- Candidate commit: none
- Review 001: `FAIL` — `P0 0 / P1 5 / P2 0`
- Closure attempt residual: `P0 0 / P1 1 / P2 0`
- Terminal Review 001 closure: `PASS` — `P0 0 / P1 0 / P2 0`
- Remediation: final cycle 3 of 3 complete; all original and residual findings closed

## Behavior

Adds exact metadata-only CADEC asset, split, encoding, visible limitation,
vocabulary-reference, document, provider-gold annotation, provenance, span,
and auxiliary locator contracts. Public request/report execution is unchanged:
no CADEC request element, report section, API/OpenAPI, loader, persistence,
search, index, training, or M2 work.

Review remediation closes annotation/locator accepted-instance validation,
expands the exact prohibited tuple to all 13 frozen safety contexts, binds
children to the exact release/manifest/audit/split and parent lineage, rejects
unsafe/excluded document labels, and closes licence and vocabulary metadata.
EvidenceClaim support remains unchanged.
Final remediation makes annotation vocabulary references an exact function of
layer: none for `original`, exactly MedDRA for `meddra`, and exactly SNOMED CT
for `sct`; wrong, empty, extra, and cross-layer references reject.

## Evidence

- Final-remediation focused run: `pytest tests/unit/domain/test_source_outcomes.py tests/unit/domain/test_scope.py
  tests/unit/domain/test_reports.py tests/unit/domain/test_provenance.py
  --disable-socket -q`: `401 passed in 0.74s`.
- Ruff format check on the eight changed Python/test files: `8 files already
  formatted`.
- Ruff check on the eight changed Python/test files: `All checks passed!`.
- `mypy src/medevidence/domain`: `Success: no issues found in 7 source files`.
- Full Ruff check: `All checks passed!`; full format check: `99 files already
  formatted`; `mypy src`: `Success: no issues found in 46 source files`.
- `pytest tests/contract/api/test_openapi.py --disable-socket -q`: `11 passed
  in 1.85s`, confirming the protected generated OpenAPI fixture remains
  compatible without a CADEC route or request/report execution surface.
- Independent reviewer focused plus protected OpenAPI validation: `412 passed`
  (`401` focused plus `11` OpenAPI).
- Integrating root full offline suite: `1,546 passed`, `81%` coverage, and two
  expected warnings.
- Integrating root rerun: `401` focused tests and `11` protected OpenAPI tests;
  Ruff check, Ruff format check, and MyPy all green.
- Scope audit: exactly 17 authorized K.7 paths, with no unauthorized path.

The first candidate's mechanical cycle corrected required freeze-field
presence, a missing type import, and one negative-test assertion. Review 001's
five P1 findings and the later one-P1 residual are closed after remediation
cycle 3 of 3.

The exact 17 paths are:

- `.delivery/M1B-CADEC-001.md`;
- `docs/ARCHITECTURE.md`, `docs/DATA_SOURCES.md`, `docs/EVALUATION_PLAN.md`,
  `docs/PRD.md`, `docs/SECURITY.md`, and `docs/TRACEABILITY_MATRIX.md`;
- `docs/decisions/ADR-013-m1b-cadec-asset-contract.md`;
- `docs/reviews/M1B-CADEC-001-LICENCE-PROVENANCE-REVIEW-001.md`;
- `src/medevidence/domain/__init__.py`,
  `src/medevidence/domain/claims.py`,
  `src/medevidence/domain/identifiers.py`, and
  `src/medevidence/domain/sources.py`; and
- `tests/unit/domain/test_provenance.py`,
  `tests/unit/domain/test_reports.py`, `tests/unit/domain/test_scope.py`, and
  `tests/unit/domain/test_source_outcomes.py`.

## Network, data, and Git

- Medical-source requests: zero; all other network requests: zero.
- Corpus/archive access/download: zero; real derived fixtures: zero.
- Restricted terminology payload: zero.
- No stage, commit, push, pull/fetch, merge, rebase, reset, clean, branch
  deletion, history rewrite, or remote mutation.

## Remaining risk and verification

Terminal evidence audit and any authorized commit remain pending.
Contracts were not exercised against real corpus bytes or a loader. Confirm the
recorded OpenAPI compatibility, full-suite evidence, and exact K.7 scope during
the terminal evidence audit. This record claims neither PASS for the terminal
audit nor completion.

## Owner interview questions

1. Why are the 91 limitations distinct from the five malformed rows?
2. How does Option-A ownership prevent cross-release or cross-split drift?
3. Why does CADEC-001 leave request/report/OpenAPI execution unchanged?
