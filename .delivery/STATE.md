# Delivery state: M1A PubMed provider-DTD interoperability

Updated: `2026-08-08`
Repository: `D:\Projects\medevidence`
Branch: `fix/m1a-pubmed-provider-dtd-compatibility`
Current status: `M1A_OFFLINE_INTEGRATED`; `M1A_LIVE_RUN_001_EXECUTED`
Live gate: `LIVE_GATE_ACCEPTANCE_UNRESOLVED`; `NO_RERUN_AUTHORIZED`;
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`;
`CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`; `NO_LIVE_PASS`;
`SECOND_RUN_OWNER_CONTROLLED`

## Current M1A-005 state

The current approved `main` identity is
`e8e28ffbde7fa3994ff8aa71dd62a956250147c1`, the merge commit for PR #9.
M1A remains offline-integrated. The separately authorized M1A live command
executed one bounded PubMed search request at PR #8 merge
`09cc42838475a4c1bab62050fbfeac14c5dd6761` and exited `1`.
The connector produced `failed / unavailable / indeterminate` after invalid
XML on the first search response; the immutable manifest/envelope separately
persisted `failed / partial / indeterminate` so received bytes were retained.
The original acceptance record was not written because the redaction harness
raised a numeric response-header substring false positive. No rerun was
performed. Live run 001 is accepted as failed interoperability evidence, not a
live PASS, and M1B has not begun.

Offline reproduction now identifies
`CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`: the exact retained response bytes
were received and contain an official external provider DOCTYPE rejected by
the historical parser. The bounded compatibility candidate parses those exact
2,205 bytes as `PubMedSearchPage` with `count=676` and 100 returned identifiers,
with zero socket and external file-open calls. This was not an NCBI outage. The
historical connector and persisted evidence outcomes remain unchanged. No
rerun occurred; any second live run remains Owner-controlled.

The exceptional Owner-authorized cycle-4 offline privacy correction is
integrated in PR #9. It confines all live inputs, transport/provider
objects, and raw-bearing values to one traceback-hidden executor; the live test
receives only a frozen scalar result. Normalized recursive redaction, fixed-code
chain-suppressed failures, a `-vv --showlocals` child disclosure regression,
and an AST/source gate are covered by fresh sockets-disabled tests.
Reviewer-triggered mechanical rework pass 1 made that source gate derive all
local helpers reachable from the sensitive executor, detect aliased
`pytest.fail`, and infer an omitted new raw-bearing helper. Final authorized
mechanical rework pass 2 rejects every `pytest` module reference or propagated
alias in the executor-reachable closure, including local/module aliases and
`getattr`. Current node-local results are `38 passed, 8 deselected` for the
focused privacy/static selection and `44 passed, 2 skipped` for the full E2E
module; Ruff and format pass on the test file. Reviewer-triggered rework passes
consumed: `2` of maximum `2`.
Independent review and terminal evidence audit for the provider-DTD
interoperability candidate remain pending.

Current integration and readiness records:

- [M1A-005 integration reconciliation](M1A-005-INTEGRATION-RECONCILIATION.md)
- [M1A live-gate readiness](M1A-LIVE-GATE-READINESS.md)
- [M1A live run 001 recovery](M1A-LIVE-RUN-001-RECOVERY.md)
- [M1A PubMed provider-DTD interoperability](M1A-PUBMED-DTD-INTEROPERABILITY.md)
- [M1A-005 Owner integration approval](../docs/reviews/M1A-005-OWNER-INTEGRATION-APPROVAL-001.md)
- [M1A live-gate readiness review](../docs/reviews/M1A-LIVE-GATE-READINESS-001.md)

The earlier M1A-005 audit and independent-review documents remain historical
pre-merge evidence and retain their original candidate identities and findings.

## Historical M1A-002 reconciliation ledger

## Goal

Reconcile the active repository status to the Owner-approved local `main`
baseline containing the verified, bounded M1A-002 PubMed connector while
preserving its historical pre-integration evidence.

## Work items

| ID | Requirement IDs | Work item | Status | Owner | Done when | Evidence | Reviewer |
|---|---|---|---|---|---|---|---|
| P1 | R1-R3 | Remediate `ResearchReport` planning semantics, tests, and stale status text | DONE | main | Focused/full offline gates and independent review pass | Focused 117 passed; full 164 passed | Independent final re-review PASS |
| P2 | R10 | Terminal audit and local M1A-001B commit | DONE | main | Audit PASS, exact commit created, post-commit tree clean | Commit `8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06`; post-commit tree clean | Independent terminal audit PASS |
| P3 | R4-R9 | Add approved dependencies and implement bounded PubMed connector/parser | DONE | main | Full Owner test matrix and terminal security audit pass offline | B-017 reproduction fixed; focused 178 and full 339 pass offline | Independent terminal security re-audit PASS |
| P4 | R10 | Dependency/evidence audit, local implementation commit, and post-commit verification | DONE | main | Required source, security, test, type, lint, dependency, scope, candidate, commit, and post-commit evidence PASS | Implementation committed locally as `02550d7c674540430e1c11edb1edd9c091593f7b`; independently audited committed tree matched staged candidate; post-commit verification PASS | Independent terminal security re-audit PASS; ready for Owner integration review |
| P5 | R10 | Reconcile M1A-002 integration status to the approved local `main` baseline | VERIFYING | main | Independent re-review and terminal audit PASS, followed by the exact authorized four-path local commit and fast-forward-only integration | Candidate records exact ancestry and scope without rewriting historical evidence; at run start local `main` and cached `origin/main` resolved to `4f39ed3d27438e69a4a5a30ff6be499d247541c1` | Independent re-review and terminal audit pending; [reconciliation record](M1A-002-INTEGRATION-RECONCILIATION.md) and [Project Owner integration approval](../docs/reviews/M1A-002-OWNER-INTEGRATION-APPROVAL-001.md) |

Valid statuses: `PENDING`, `IN_PROGRESS`, `VERIFYING`, `FIXING`, `BLOCKED`,
`DONE`.

## Initial repository baseline

```text
Location:           D:\Projects\medevidence
Initial branch:     main
Initial HEAD:       0bf3d58d7411fffa1873a6f2adab8ee73c23ce88
Local main:         0bf3d58d7411fffa1873a6f2adab8ee73c23ce88
Cached origin/main: 0bf3d58d7411fffa1873a6f2adab8ee73c23ce88
Initial status:     clean; zero staged, unstaged, or untracked files
Feature branch:     codex/m1a-001b-remediation-m1a-002
Remote operations: none
```

## Confirmed facts

| Fact | Evidence |
|---|---|
| M1A-001B is merged into current `main` | `git log`; merge commit `0bf3d58` |
| `ResearchReport` currently rejects every non-selected in-scope plan entry | `src/medevidence/domain/reports.py:validate_aggregate`; independent reproduction |
| Plan-set equality and duplicate checks already exist and must remain | Same validator |
| Outcomes are already restricted to selected plan entries | Same validator |
| `SourcePlanEntry` already enforces typed skip reason code and human reason | `src/medevidence/domain/sources.py:SourcePlanEntry.validate_reason` |
| Seven source-outcome triples and bounds are already strict | `SourceOutcome.validate_terminal_contract` |
| README incorrectly says governance merge pending and no domain models exist | `README.md` repository-status sections |
| Current production direct dependency is only Pydantic | `pyproject.toml`; `uv tree --locked` |
| `defusedxml` exists only transitively in the lock; HTTPX and Tenacity are not direct/installed | `uv.lock`, `uv tree --locked`, environment inspection |
| Exact NCBI E-utilities base is first-party documented | NCBI E-utilities Quick Start |
| Baseline unit/contract suite is green | Read-only subagent: 158 passed with sockets disabled; main will rerun authoritative gates |
| No live PubMed/NCBI API call has occurred | All discovery used local files or NCBI documentation pages only |

## Current changes

- `.delivery/SPEC.md` - authoritative requirement/design matrix.
- `.delivery/STATE.md` - authoritative execution/evidence ledger.
- `src/medevidence/domain/reports.py` - accept in-scope
  `selected`/`skipped_by_policy` plans while retaining the plan/outcome
  bijection.
- `tests/unit/domain/test_reports.py` - positive mixed-plan and explicit
  missing/duplicate/fabricated-outcome/policy negatives.
- `README.md` - correct merged M1A-001B and dependency status.
- `docs/INTERVIEW_NOTES.md` - correct the honest current implementation status.
- `pyproject.toml`, `uv.lock`, and dependency-boundary tests - add only the
  M1A-002-required approved direct pins and resolved HTTPX transitives.
- `src/medevidence/connectors/pubmed/` - fixed-host transport policy, hardened
  XML parsing, bounded synchronous client, typed results/failures, deterministic
  source-outcome and publication mapping, per-response provenance time, and
  client-identity redaction.
- `tests/unit/connectors/`, `tests/contract/connectors/`, and
  `tests/fixtures/pubmed/` - synthetic/fixture-backed parser, policy, transport,
  outcome, retry, redirect, lifecycle, provenance, and no-network coverage.
- `scripts/dependency-audit.ps1` - bind the M1A-002 connector candidate files
  into dependency-evidence identity.

## Verification

| Requirement IDs | Command or check | Result |
|---|---|---|
| R1-R3 | Independent mixed-plan reproduction | FAIL at baseline as expected: `scope-selected sources require selected plan entries` |
| R1-R3 | Read-only focused baseline | 110 passed; defect case not covered |
| R1-R3 | Focused post-fix suite | PASS: 117 passed |
| R1-R10 | Refreshed authoritative Ruff lint and format commands | PASS: 16 files formatted |
| R1-R10 | Refreshed authoritative strict mypy command | PASS: 8 source files |
| R1-R10 | Refreshed authoritative full offline unit/contract command | PASS: 164 passed, 87% coverage, sockets disabled |
| R10 | First independent final review | Contract behavior PASS; terminal readiness FAIL because the ledger predated the 164th test and SPEC contained a session-local path |
| R10 | Review remediation | PASS: exact attachment hash substituted, four-command gate rerun against the corrected candidate |
| R10 | First terminal evidence audit | Behavior and validation clean; documentation FAIL because two README dependency-audit statements remained stale |
| R10 | Terminal-audit remediation | Corrected README to describe the implemented, separate path-filtered networked audit workflow |
| R10 | Corrected terminal evidence re-audit | PASS: no blocking findings; focused 124 passed, full 164 passed at 87%, phase audit and diff checks PASS |
| R1-R10 | Initial Git safety checks | PASS; clean `main`, exact local/cached refs |
| R4 | Repository exact-host search | No literal found; resolved through first-party NCBI documentation |
| R9 | Live PubMed/NCBI API access | Not performed |
| R10 | M1A-001B local commit | PASS: `8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06`; immediate post-commit tree clean |
| R4-R9 | M1A-002 dependency inspection and offline lock | Direct additions: `httpx==0.28.1`, `defusedxml==0.7.1`; lock added `anyio==4.14.2`, `h11==0.16.0`, `httpcore==1.0.9`, `httpx==0.28.1`; `defusedxml` was already transitive |
| R4-R9 | Initial M1A-002 focused validation | PASS: 126 tests; focused Ruff, format, and MyPy PASS |
| R4-R10 | Initial M1A-002 full four-command gate | PASS: 287 tests, 85% coverage; Ruff, format, and MyPy PASS |
| R4-R10 | Independent frozen-candidate review | FAIL: six P1 boundary/provenance defects and two P2 architecture/privacy defects |
| R4-R9 | Remediation cycle 1 focused validation | PASS: 139 tests; focused Ruff, format, and MyPy PASS |
| R4-R10 | Remediation cycle 2 | PASS: identity-bearing redirect metadata removed from returned evidence; both PubMed retraction publication-type signals fail closed; independent re-review found no residual from these findings |
| R4-R10 | Remediation cycle 3 | PASS: unsupported XML encodings, duplicate status/evidence containers, invalid-input echo, case-insensitive identity redaction, provider-item/diagnostic bounds, invalid PMID hints, and duplicate whole-record conflicts were corrected; the final operation-wide and warning-semantics re-reviews PASS |
| R4-R10 | Final focused M1A-002 gate | PASS: 176 connector/parser/policy/dependency tests with sockets disabled; independent focused-plus-socket run 177 passed with the expected socket-block warning |
| R4-R10 | Final authoritative four-command gate | PASS: Ruff lint; Ruff format on 24 files; MyPy on 13 source files; 337 unit/contract tests at 87% coverage with sockets disabled |
| R4-R10 | Final independent code review | PASS on exact hashes: `client.py` `02c0918e...`, `parsing.py` `874a065e...`, contract tests `a44a5b71...`, parser tests `de98a57e...`; no P0/P1/P2 blocker |
| R4-R10 | Final independent test-gap review | PASS: Owner-minimum 23 cases, cycle-3 regression selection 49 cases, and full focused selection 176 cases; no remaining test/spec blocker |
| R4-R9 | Final dependency advisory audit | PASS: 50 reconciled external packages, 50 declared licenses, zero known vulnerabilities, zero skipped packages, zero exceptions; manifest `2a880958c87fe7fa7bb140c95cc4d787ba1e9d8b3aff3377e7a81905691ddf6b`; candidate file set `sha256:8a3500fd4f458495f9211e4478e47ad5387d72d6b68eb191903f2177a3a4a65e`; evidence outside Git at `C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a002-final-deps-20260805-185500651` |
| R4,R10 | Independent terminal evidence audit | BLOCK: invalid UTF-8 `%FF` in a redirect query compares equal to valid U+FFFD `%EF%BF%BD` under replacement decoding, so the altered redirect is followed; one offline MockTransport reproduction, no live access |
| R4,R10 | Owner B-017 authorization | PASS: one fourth cycle authorized for strict percent/UTF-8 query decoding, exactly two required regressions, evidence refresh, terminal re-audit, and commit only on PASS |
| R4 | B-017 baseline and corrected reproduction | Baseline followed `%FF`; corrected policy raises `ValueError` before a second request. Manual boundary smoke also rejects `%`, `%G0`, and overlong `%C0%AF`, while valid pair reordering remains accepted |
| R4 | B-017 permanent regressions | PASS: policy `%EF%BF%BD` versus `%FF`; full `MockTransport` returns `REDIRECT_REJECTED` with exactly one request |
| R4-R10 | Fourth-cycle focused and full gates | PASS: focused 178; Ruff lint; Ruff format on 24 files; MyPy on 13 source files; full 339 unit/contract tests at 87% coverage, all with sockets disabled |
| R4-R9 | Refreshed fourth-cycle dependency advisory audit | PASS: 50 reconciled external packages, 50 declared licenses, zero known vulnerabilities, skipped packages, or exceptions; manifest `9895b6c8f7e96fb89452cd459d7a0e13d80eca5a0c8d32325ee1b55a8c943c4c`; candidate file set `sha256:d503b8960603a605ae88ad50465048ee2dfc21cac733530407b8b80872b76e67`; evidence outside Git at `C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a002-b017-final-deps-20260805-192510062` |
| R4-R10 | Repeated independent terminal security audit | PASS: exact hashes and 19-path scope verified; B-017 policy/MockTransport and extended malformed/equivalence matrices pass; focused 178 and full 339 pass; no P0/P1/P2 finding; safe to stage and create the local M1A-002 commit |
| R10 | Final evidence-only terminal rebind | BLOCK: P4 and the latest handoff claimed completion before the exact commit and clean-tree conditions existed; source/test/dependency candidate remains unchanged and technically safe |
| R10 | Owner B-018 evidence-state authorization | PASS: one evidence-only correction authorized for `STATE.md` and `M1A-002-AUDIT.md`, followed by an independent read-only 19-path pre-commit rebind and commit only on PASS |
| R10 | B-018 evidence-state correction | PASS (historical pre-commit state): P4 was limited to the completed pre-commit evidence gate and the handoff was `READY_TO_COMMIT`; it did not then claim a commit, final SHA, clean worktree, full completion, or final handoff |
| R10 | M1A-002 local implementation commit | PASS: `02550d7c674540430e1c11edb1edd9c091593f7b`, parent `8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06` |
| R10 | Staged-to-committed identity and post-commit verification | PASS: independently audited committed tree matched the staged candidate; post-commit verification complete |
| R9 | External-access boundary | No PubMed/NCBI API request made; dependency Audit contacted only the PyPI advisory service |

## Bug queue

| Bug ID | Requirement IDs | Found by | Reproduction | Owner | Status | Retest | Reviewer |
|---|---|---|---|---|---|---|---|
| B-001 | R1-R3 | Owner task + independent analysts | Mixed PubMed selected / CADEC skipped report is rejected by blanket selected-only aggregate check | main | FIXED | Focused and full suites PASS | Independent final re-review PASS |
| B-002 | R5,R7 | Independent code review | Extreme `Retry-After` delta raised `OverflowError` | main | FIXED | Huge-delta regression PASS | Final re-review PASS |
| B-003 | R7,R8 | Independent code review | Oversized ESearch integer escaped typed XML handling | main | FIXED | Oversized-integer regression PASS | Final re-review PASS |
| B-004 | R5,R7 | Independent code review | Fetch identifier count/length and materialization were not fully bounded | main | FIXED | Pre-transport bounded-input regressions PASS | Final re-review PASS |
| B-005 | R5,R6 | Independent code review | Parsing could exceed the operation deadline and still report complete | main | FIXED | Post-parse deadline regression PASS | Final re-review PASS |
| B-006 | R8 | Independent code review | `Retracted Publication` without a resolved notice could map to current | main | FIXED | Fail-closed status-signal regression PASS | Final re-review PASS |
| B-007 | R8 | Independent code review | One pre-request timestamp was reused across later responses/batches | main | FIXED | Per-batch post-response timestamp regression PASS | Final re-review PASS |
| B-008 | R10 | Independent code review | Connector architecture test did not reject outer `medevidence.*` layers | main | FIXED | Explicit API/orchestration/retrieval rejection tests PASS | Final re-review PASS |
| B-009 | R9,R10 | Independent code review | Returned raw-response URLs retained the Owner email | main | FIXED | Outbound-present/result-redacted regression PASS | Final re-review PASS |
| B-010 | R6 | Independent test-gap audit | Connector suite omitted `failed + partial + indeterminate` | main | FIXED | Malformed/unmappable-first-batch then failure regressions PASS | Final re-review PASS |
| B-011 | R8,R9 | Independent re-review | Returned `Location` metadata could retain mixed-case/encoded email identity | main | FIXED | Redirect identity redaction regressions PASS | Final re-review PASS |
| B-012 | R8 | Independent re-review | `Retraction of Publication` could map to current without a resolved notice | main | FIXED | Both publication-type signal regressions PASS | Final re-review PASS |
| B-013 | R7,R8 | Independent test-gap review | Unsupported multibyte XML and duplicate singleton/status containers could be accepted ambiguously | main | FIXED | Encoding and duplicate-container matrices PASS | Final re-review PASS |
| B-014 | R5,R7,R9 | Independent test-gap review | Invalid inputs, provider item counts, diagnostics, and PMID hints needed stronger pre-retention bounds | main | FIXED | Invalid-input/no-echo, provider-overflow, multi-batch amplification, and oversized-hint regressions PASS | Final re-review PASS |
| B-015 | R6,R8 | Independent reviews | Same-response and cross-batch duplicate whole records could let one publication status win by position | main | FIXED | Both status orders now evict the conflicted PMID operation-wide and return partial/indeterminate | Final code and test-gap re-reviews PASS |
| B-016 | R3,R6 | Independent code re-review | Shared duplicate warning falsely claimed provider-record conflict for duplicate caller/search IDs | main | FIXED | Search and fetch-input provenance-message assertions PASS | Final code and test-gap re-reviews PASS |
| B-017 | R4,R10 | Independent terminal evidence audit | Redirect changes valid query value `%EF%BF%BD` to invalid UTF-8 `%FF`; replacement decoding treats them as equal and the connector follows the altered URL | main | FIXED | Strict percent/UTF-8 decoding rejects before a second request; two required regressions and all gates PASS | Independent terminal security re-audit PASS |
| B-018 | R10 | Final evidence-only terminal rebind | P4 and latest handoff marked completion while HEAD remained the M1A-001B commit, 19 paths were dirty, and the Git index was empty | main | FIXED | Pre-commit evidence was correctly rebound before staging; implementation was then committed locally as `02550d7c674540430e1c11edb1edd9c091593f7b` and post-commit verification PASS | Resolved historical fact |

## Decisions and tradeoffs

| Decision | Evidence | Rejected alternative |
|---|---|---|
| Latest Owner task controls the one-branch/two-commit sequence | Explicit task Sections 4, 5, 8, and 10 | Stop after M1A-001B under superseded branch gate |
| Use exact NCBI E-utilities origin and only ESearch/EFetch paths | First-party NCBI documentation plus repository fixed-host requirement | Caller-configurable base URL or wildcard suffix allowlist |
| Use HTTPX + required injected transport and an explicit production factory | Owner dependency/network decision | Default real client with optional mock |
| Use a small explicit retry loop | Deadline, sleeper, jitter, and attempt behavior remain directly testable | Add Tenacity only because it is approved |
| Add direct `defusedxml==0.7.1` | ADR-009 approved hardening; stdlib XML is not sufficient for untrusted source bytes | Standard-library-only XML or a heavy parser |
| Connector cache policy is `none` | Snapshot/cache persistence belongs to M1A-003A | Hidden in-memory cache |

## Failed paths not to repeat

- `uv tree --locked --no-sync` is invalid; `uv tree` has no `--no-sync`
  option. Use `UV_OFFLINE=1; uv tree --locked`.
- PowerShell command arguments containing regex pipe characters were parsed
  incorrectly by the shell wrapper. Use separate fixed patterns or
  `Select-String`.
- Agent-reach Exa invocation was unavailable through the local `mcporter`
  metadata path; the official-source check used the general web-search
  fallback and first-party NCBI results.
- The deterministic final-audit helper cannot use the overall STATE ledger for
  a phase-local audit because future M1A-002 rows are intentionally unresolved.
  Use the frozen `.delivery/M1A-001B-AUDIT.md` phase snapshot for this commit.
- Direct invocation of `dependency-audit.ps1` is blocked by the machine
  execution policy. Use `powershell.exe -NoProfile -ExecutionPolicy Bypass
  -File ...`; the corrected Inventory and Audit invocations passed.

## Unverified risks

- The source-specific `CommentsCorrections` and publication-type mapping is
  deliberately conservative but not a claim that every future PubMed status
  vocabulary value has been catalogued.
- A synchronous deadline bounds connector-controlled waits and real HTTPX
  phases; it cannot preempt a malicious injected transport or parser while that
  callable is blocked, but it rejects completeness immediately after control
  returns.
- At this historical M1A-002 ledger cutoff, live TLS/NCBI behavior was
  intentionally unverified because the exact live query and command remained
  Owner-gated. Live run 001 is recorded separately in the current-state section
  above and does not rewrite this historical evidence boundary.
- The final dependency evidence is an external temporary artifact; its manifest
  and candidate identity are recorded here, but the artifact is not committed.
- M1A-002 is locally integrated into the approved `main` baseline at
  `4f39ed3d27438e69a4a5a30ff6be499d247541c1`; alignment with
  `refs/remotes/origin/main` is based only on the cached tracking ref and is
  not live remote verification.
- The historical evidence-finalization record remains valid for its
  pre-integration state and is superseded only for current-baseline status.
- Engineering harness commits after the evidence-finalization commit are not
  M1A product functionality.
- `M1A-003A` onward remains unimplemented and is not authorized by this
  reconciliation.

## Historical M1A-002 current step

`M1A-002_LOCALLY_INTEGRATED_IN_APPROVED_MAIN remains the confirmed baseline
fact: 02550d7c674540430e1c11edb1edd9c091593f7b and
2918f3ed80336aeb349e82d34f2833367641befd are ancestors of approved local main
4f39ed3d27438e69a4a5a30ff6be499d247541c1. The four-file reconciliation
candidate is VERIFYING; independent re-review and terminal audit are pending,
and no reconciliation commit or fast-forward integration has occurred.`

## Historical M1A-002 next step

Run independent re-review and terminal evidence audit. Only if both return
PASS, stage exactly the four authorized paths, create the already-authorized
local commit with subject
`docs(delivery): reconcile M1A-002 approved baseline`, verify it, confirm local
`main` still equals `4f39ed3d27438e69a4a5a30ff6be499d247541c1`,
switch to `main`, and fast-forward only from
`docs/m1a-002-baseline-reconciliation`. Do not begin `M1A-003A` or later work.

## Historical M1A-002 latest handoff

```text
Task: M1A-002 approved-main baseline reconciliation
Status: RECONCILIATION_VERIFYING; M1A-002_LOCALLY_INTEGRATED_IN_APPROVED_MAIN remains a separate confirmed baseline fact
Confirmed facts: at run start HEAD, local main, and cached origin/main resolved to 4f39ed3d27438e69a4a5a30ff6be499d247541c1; 8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06, 02550d7c674540430e1c11edb1edd9c091593f7b, and 2918f3ed80336aeb349e82d34f2833367641befd are ancestors; B-017 and B-018 remain resolved historical facts
Paths and symbols: current integration approval and reconciliation records plus active STATE and README status only; historical M1A-002-AUDIT.md unchanged
Commands and results: read-only Git identity and ancestry checks PASS; historical focused 178 and full 339 at 87% were not rerun by this documentation node
Findings: four-file candidate awaits independent re-review and terminal audit; no reconciliation commit or fast-forward integration exists; historical pre-integration evidence remains valid and is superseded only for current-baseline status; harness commits are engineering tooling, not M1A product functionality
Assumptions and unknowns: cached origin/main was not refreshed; no remote-state claim; live NCBI/TLS behavior intentionally unverified
Files modified in this reconciliation: docs/reviews/M1A-002-OWNER-INTEGRATION-APPROVAL-001.md, .delivery/M1A-002-INTEGRATION-RECONCILIATION.md, .delivery/STATE.md, and README.md
Recommended next action: independent re-review and terminal audit, then on PASS execute the already-authorized exact four-path commit and fast-forward-only local integration flow; do not begin M1A-003A or later work
```

## Current M1A handoff

```text
Task: M1A-PUBMED-DTD-INTEROPERABILITY
Status: M1A_LIVE_RUN_001_EXECUTED; LIVE_GATE_ACCEPTANCE_UNRESOLVED; NO_RERUN_AUTHORIZED; M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE; CLIENT_XML_DTD_INTEROPERABILITY_FAILURE; READY_FOR_INDEPENDENT_REVIEW; NO_LIVE_PASS
Baseline: PR #9 merge e8e28ffbde7fa3994ff8aa71dd62a956250147c1
Historical execution: one bounded PubMed ESearch request occurred at PR #8; command exit 1; historical connector outcome failed/unavailable/indeterminate; persisted evidence failed/partial/indeterminate; fetch not executed
After-state: exact retained 2205 bytes parse offline as PubMedSearchPage; count=676; returned_identifier_count=100; socket_calls=0; external_open_calls=0; raw/recovery/manifest identities unchanged
Recovery record: unchanged at 3032 bytes and SHA-256 1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf
Scope: exactly nine authorized paths; parser, unit/contract tests, and six delivery/status documents; no dependency, client, domain, schema, or public-interface change
Network in this node: none; sockets disabled; no rerun and no live medical-source request
Pending: independent review, terminal audit, candidate identity, and any authorized Git lifecycle; no PASS/commit/PR/merge claim
Next action: independent review of the provider-DTD candidate; any second live run remains Owner-controlled; do not begin M1B planning
```
