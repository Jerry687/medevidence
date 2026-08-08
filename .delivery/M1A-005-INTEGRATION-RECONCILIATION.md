# M1A-005 integration reconciliation

Updated: `2026-08-08`

Status: **CANDIDATE - offline validation and independent review passed; terminal audit pending**

Branch at reconciliation: `docs/m1a-offline-integration-live-readiness`

## Exact scope

This reconciliation is limited to the authorized delivery and readiness
records, the current-state portions of the repository documentation, and the
conditional mechanical correction in
`tests/e2e/test_live_pubmed.py`. No production source, dependency, schema,
public interface, workflow, or historical ADR was changed.

## Immutable post-merge facts

| Check | Evidence |
|---|---|
| Required baseline | Local `main`, cached `origin/main`, and live `origin/main` resolved to `47504a4016f968ed0a0dd10e4280b1a957c15461` at preflight |
| Current branch base | `docs/m1a-offline-integration-live-readiness` was created from that exact clean baseline |
| PR #7 | GitHub reports PR #7 closed, merged, non-draft, with merge commit `47504a4016f968ed0a0dd10e4280b1a957c15461` |
| Merge semantics | The merge commit subject and PR metadata record Create-a-merge-commit semantics |
| M1A-005 implementation | `5a75b96a034abbaf4769f9dfde93ea3bb154567e` is an ancestor of the merged baseline |
| M1A-005 evidence | `d70b3121634ba2cd1ca89d7c935c6ec470a9a988`, `b603a2df6a1c1c16f5dd80cbd801d425aa6aed23`, and `affc019c74058879a682094bd508ed93f68ed631` are ancestors of the merged baseline |
| M1A-005 review/audit | The historical implementation review and terminal audit each record `PASS — P0 0 / P1 0 / P2 0` for the reviewed candidate |
| Hosted checks | Historical hosted `compose-config`, `dependency-audit`, and `windows-quality` results are recorded as PASS |
| Current phase | `M1A_OFFLINE_INTEGRATED`; the live acceptance gate is `LIVE_GATE_NOT_RUN`; M1B has not begun |

The earlier `14a38d4...` identity is retained only as the historical M1A-004
approved baseline recorded by the M1A-005 pre-merge evidence. It is not the
current approved `main` identity.

## Historical evidence handling

`.delivery/M1A-005-AUDIT.md` and
`docs/reviews/M1A-005-INDEPENDENT-REVIEW-001.md` remain historical records of
the pre-merge candidate, including their earlier FAIL findings and candidate
identities. The audit now carries a prominent supersession notice; its
original evidence is not rewritten as though it knew the later merge result.
The current integration fact is recorded separately in
`docs/reviews/M1A-005-OWNER-INTEGRATION-APPROVAL-001.md`.

No future reconciliation commit, PR-head SHA, merge SHA, hosted result, or
post-commit cleanliness claim is included in this record.

## Live-gate boundary

The live gate remains separately Owner-authorized and unexecuted. The
readiness record proves only that the disabled test can construct the required
redacted evidence shape from the existing connector, snapshot, manifest, and
journal contracts. Raw responses and manifests are written only beneath an
Owner-supplied root outside Git during a later authorized run. Raw artifact
identities remain distinct from canonical manifest identities; the current
contract records snapshot and manifest identity as the same manifest identity
where applicable.

## Validation and evidence boundary

The candidate validation commands completed with these results:

```powershell
uv run --locked --no-sync pytest tests/e2e/test_live_pubmed.py `
  tests/e2e/test_m1a_pubmed.py `
  tests/contract/ingestion/test_snapshot_store.py `
  tests/unit/ingestion/test_manifest_contracts.py `
  --disable-socket
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket `
  --cov=medevidence --cov-report=term-missing --cov-report=xml
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
git diff --check
```

- Focused no-live checks: `43 passed, 1 skipped` (the live test skipped because
  explicit Owner opt-in was absent).
- Full offline unit/contract checks: `713 passed`; coverage report generated
  at 79%.
- Ruff, format, MyPy, lock, diff-check, exact baseline/ancestor, and
  authorized-path checks: passed.
- The live environment variable was absent and no medical-source request was
  made.

The live test itself must remain unexecuted. The final handoff must record
fresh results for each command, exact changed paths, and the independent
review and terminal evidence decisions. The independent review returned
`PASS` with P0 0 / P1 0 / P2 0; the terminal evidence audit remains pending.

## Network and Git boundary

- No PubMed, NCBI, DailyMed, FAERS, or other medical-source request occurred.
- GitHub metadata and live-remote baseline verification were authorized by this
  work item; no medical-source network access was used.
- No commit, push, PR mutation, merge, fetch, rebase, reset, clean, or history
  rewrite is represented by this candidate record.

## Remaining risks

- Live NCBI/TLS behavior remains unverified until the Project Owner separately
  authorizes the exact query, email, execution time, command, and root.
- This candidate must not be called ready until focused/offline validation,
  independent review, and terminal evidence audit all pass for the same exact
  candidate.
- M1B remains outside this work item and has not begun.
