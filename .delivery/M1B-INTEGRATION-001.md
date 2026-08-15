# M1B-INTEGRATION-001 delivery record

- Status: `M1B-INTEGRATION-001_COMPLETE`; `READY_FOR_M1B-ACCEPTANCE-001`
- Branch: `feat/m1b-integration-001`
- Baseline: `07c548737ec351c5a2a0669078f559700ac8b9b8`
- Feature commit: `e346b70949bdeb015d5e49f4fbf383bc7642e7e5`
- Pull request: #23 merged
- Merge commit: `fd6e5f62713f9fe611c9b3062aa0246937da0e84`
- Independent review: `PASS` - `P0 0 / P1 0 / P2 0`
- Terminal Evidence Audit001: `PASS` - `P0 0 / P1 0 / P2 0`
- Completion: integrated

## Objective and exact reconciliation

Integrate the completed DailyMed, FAERS, and CADEC M1B vertical-slice
boundaries without adding source semantics or executable behavior. The Owner's
repository-level visibility decision governs CADEC:

- repository governance records CADEC as an explicitly known M1B source with
  `planning_status=skipped_by_policy` and
  `reason_code=source_execution_not_authorized`;
- each `M1BResearchReportV1.source_plan` remains exactly its runtime request's
  `scope.selected_sources`;
- DailyMed-only and FAERS-only runtime plans remain source-only;
- CADEC is not added to `requested_sources`; and
- `cadec_query_requests` stays empty, with no CADEC execution, `SourceOutcome`,
  report section, API/OpenAPI surface, persistence, search, indexing, or
  retrieval.

No global runtime plan object is introduced for repository governance.

## Integrated CADEC authority

CADEC-003 feature commit `83617405e58bcec657bdaa84aceb8d2460d46fb1` was
integrated by merge `c226a632753e6fc65e8c84c74ec568d994612b7d` through PR
#21. Its fresh independent review and terminal evidence audit each passed at
`P0 0 / P1 0 / P2 0`, establishing
`M1B-CADEC_VERTICAL_SLICE_COMPLETE`. Immutable historical Review001 and
closure-review failure records remain unchanged.

## Authorized scope and finding classification

The implementation node is limited to five current-state CADEC governance
documents plus this delivery record and the pending independent-review record.
No runtime code, test, OpenAPI, dependency, database, loader, retrieval, M2, or
UI path is authorized.

Findings are classified as:

- A: a real M1B integration contradiction introduced or exposed by the
  combined runtime; blocking;
- B: a pre-existing unrelated defect; backlog and non-blocking; or
- C: a future M2, M3, or product concern; deferred and non-blocking.

The Owner resolved the discovered CADEC planning-language contradiction as a
governance/runtime distinction. No executable contradiction requiring a code
change was found by the documentation node.

## Fresh validation evidence

The candidate worktree has no local `.venv`. Validation therefore used the
exact locked coordination environment through
`uv run --locked --no-sync --project D:\Projects\medevidence`, with the
candidate worktree as the command working directory and its `src` directory
supplied through `PYTHONPATH`. This executed candidate code without dependency
sync or network access.

- The focused cross-source run covered scope and report contracts, research,
  DailyMed and FAERS report tools, API routes, protected OpenAPI, offline and
  dependency boundaries, and DailyMed/FAERS integration tests. Result:
  `406 passed`, two expected warnings, `8.75s`, sockets disabled.
- The injected-port PubMed integration run targeted
  `tests/integration/tools/test_pubmed_research.py`. Result: `1 passed` in
  `0.24s`, sockets disabled.
- Ruff check passed with `All checks passed!`.
- Ruff format check passed for 118 files.
- MyPy passed for 52 source files.
- The full unit and contract run passed: `1730 passed`, two expected warnings,
  `41.58s`, 79% coverage, sockets disabled.
- `git diff --check`, the exact seven-path allowlist, UTF-8 without BOM,
  LF-only endings, final newlines, local Markdown links/headings, trailing-
  whitespace, immutable Review001, semantic consistency, and no executable or
  test diff all passed.

The exact executable validation commands were:

```powershell
$env:PYTHONPATH='D:\Projects\medevidence-wt-m1b-integration\src;D:\Projects\medevidence-wt-m1b-integration'
uv run --locked --no-sync --project D:\Projects\medevidence pytest tests/unit/domain/test_scope.py tests/unit/domain/test_reports.py tests/unit/tools/test_research.py tests/unit/tools/test_dailymed_report.py tests/unit/tools/test_faers_report.py tests/unit/api/test_routes.py tests/contract/api/test_openapi.py tests/contract/test_offline_network.py tests/unit/test_dependency_boundaries.py tests/integration/api/test_research_dailymed.py tests/integration/api/test_research_faers.py --disable-socket -p no:cacheprovider

$env:PYTHONPATH='D:\Projects\medevidence-wt-m1b-integration\src;D:\Projects\medevidence-wt-m1b-integration'
uv run --locked --no-sync --project D:\Projects\medevidence pytest tests/integration/tools/test_pubmed_research.py --disable-socket -p no:cacheprovider

$env:PYTHONPATH='D:\Projects\medevidence-wt-m1b-integration\src;D:\Projects\medevidence-wt-m1b-integration'
uv run --locked --no-sync --project D:\Projects\medevidence ruff check .
uv run --locked --no-sync --project D:\Projects\medevidence ruff format --check .
uv run --locked --no-sync --project D:\Projects\medevidence mypy src
uv run --locked --no-sync --project D:\Projects\medevidence pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

Ignored `.coverage`, `coverage.xml`, and cache artifacts may have been refreshed
by validation; they are not candidate paths. No medical-source request,
external CADEC archive access, database operation, M2-worktree access,
dependency sync, or other network access occurred. No stage, commit, push, PR
mutation, merge, rebase, reset, clean, branch deletion, or history rewrite was
performed by this documentation node.

## Integrated current state

Independent review passed at `P0 0 / P1 0 / P2 0` with no A-, B-, or C-class
findings. The review reran the focused cross-source suite (`406 passed`, two
expected warnings), injected-port PubMed integration (`1 passed`), and a direct
protected OpenAPI contract check (`1 passed`). Structural, secret, exact-path,
and local-link checks also passed. No network, medical-source, archive,
database, M2-worktree, or Git mutation occurred during review.

A provisional concern about stale FAERS text was withdrawn after full-context
verification established that the cited passages are explicitly scoped
immutable historical event records. It is not a candidate defect, produced no
A/B/C finding, and consumed no remediation cycle.

## Terminal Evidence Audit001

Terminal Evidence Audit001 returned definitive `PASS` at
`P0 0 / P1 0 / P2 0` with no findings. It audited the pre-finalization
aggregate
`fbc5055d0259d9155afa15ea799e2f25336b2fb99caeb4ea4932ffa48e295f5a`,
computed from canonical ordinal records
`path<TAB>bytes<TAB>sha256<LF>` with a final LF. The audit made no network or
medical-source request, accessed no external archive, database, or M2
worktree, and performed no Git mutation.

The exact-byte rebind passed, and feature commit
`e346b70949bdeb015d5e49f4fbf383bc7642e7e5` was integrated through PR #23 by
merge `fd6e5f62713f9fe611c9b3062aa0246937da0e84`. Hosted PR quality run
`31771556444` passed `compose-config` (job `94678385975`) and
`windows-quality` (job `94678385999`). Post-merge push run `31771699433`
completed successfully on the merge commit. The focused cross-source run
remained `406 passed` with two expected warnings, the injected-port PubMed
integration remained `1 passed`, the full offline suite remained `1730
passed` with two expected warnings and 79% coverage, and Ruff, formatting,
and MyPy remained green.

These current-state facts supersede only the stale pending lifecycle text;
they do not rewrite the candidate validation, review, or terminal-audit event
history above. The GitHub PR/check/run facts were reverified read-only during
M1B acceptance closeout. No medical-source request accompanied that metadata
verification. This establishes `M1B-INTEGRATION-001_COMPLETE` and
`READY_FOR_M1B-ACCEPTANCE-001`.

## Owner interview questions

1. Why is CADEC governance visibility not an entry in every runtime source
   plan?
2. Why must `source_plan == scope.selected_sources` remain unchanged for
   DailyMed-only and FAERS-only requests?
3. Which CADEC boundaries prevent repository governance from authorizing M1B
   execution?
