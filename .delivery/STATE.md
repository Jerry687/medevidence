# Delivery state: M1A-002 bounded PubMed connector finalization

Updated: `2026-08-05`
Repository: `D:\Projects\medevidence`
Branch: `codex/m1a-002-product-finalization`

## Goal

Finalize the tracked post-commit delivery evidence for the verified, bounded
M1A-002 PubMed connector without live API, remote Git, merge, or baseline
approval claims.

## Work items

| ID | Requirement IDs | Work item | Status | Owner | Done when | Evidence | Reviewer |
|---|---|---|---|---|---|---|---|
| P1 | R1-R3 | Remediate `ResearchReport` planning semantics, tests, and stale status text | DONE | main | Focused/full offline gates and independent review pass | Focused 117 passed; full 164 passed | Independent final re-review PASS |
| P2 | R10 | Terminal audit and local M1A-001B commit | DONE | main | Audit PASS, exact commit created, post-commit tree clean | Commit `8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06`; post-commit tree clean | Independent terminal audit PASS |
| P3 | R4-R9 | Add approved dependencies and implement bounded PubMed connector/parser | DONE | main | Full Owner test matrix and terminal security audit pass offline | B-017 reproduction fixed; focused 178 and full 339 pass offline | Independent terminal security re-audit PASS |
| P4 | R10 | Dependency/evidence audit, local implementation commit, and post-commit verification | DONE | main | Required source, security, test, type, lint, dependency, scope, candidate, commit, and post-commit evidence PASS | Implementation committed locally as `02550d7c674540430e1c11edb1edd9c091593f7b`; independently audited committed tree matched staged candidate; post-commit verification PASS | Independent terminal security re-audit PASS; ready for Owner integration review |

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
- Live TLS/NCBI behavior is intentionally unverified because the exact live
  query and command remain Owner-gated.
- The final dependency evidence is an external temporary artifact; its manifest
  and candidate identity are recorded here, but the artifact is not committed.
- Live TLS/NCBI behavior remains intentionally unverified.
- M1A-002 is committed locally at
  `02550d7c674540430e1c11edb1edd9c091593f7b` (parent
  `8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06`), but it is not pushed, merged
  into `main`, or part of the approved baseline.
- This evidence-finalization record does not require a self-referential hash
  and does not claim that its own commit is merged or remotely published.

## Current step

`READY_FOR_OWNER_INTEGRATION_REVIEW - M1A-002 implementation is committed locally at
02550d7c674540430e1c11edb1edd9c091593f7b; B-017 and B-018 are resolved;
post-commit verification is PASS; candidate is ready for Owner integration
review.`

## Next step

Owner integration review. M1A-002 remains local-only: do not push, merge into
`main`, or treat it as part of the approved baseline without separate Owner
authorization. Live NCBI/TLS behavior remains intentionally unverified.

## Latest handoff

```text
Task: M1A-002 evidence finalization
Status: READY_FOR_OWNER_INTEGRATION_REVIEW
Confirmed facts: M1A-002 implementation committed locally at 02550d7c674540430e1c11edb1edd9c091593f7b with parent 8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06; B-017 and B-018 are resolved; independently audited committed tree matched staged candidate; post-commit verification PASS
Paths and symbols: implementation candidate identities and dependency manifest remain as recorded in this ledger and M1A-002-AUDIT.md
Commands and results: focused 178 PASS; full 339 PASS at 87%; refreshed dependency audit, repeated terminal security audit, and post-commit verification PASS
Findings: candidate is ready for Owner integration review
Assumptions and unknowns: not pushed; not merged into main; not part of the approved baseline; live NCBI/TLS behavior intentionally unverified
Files modified in this correction: only STATE.md and M1A-002-AUDIT.md
Recommended next action: Owner integration review; no remote Git or merge action is authorized
```
