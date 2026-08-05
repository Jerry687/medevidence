# Coding task state: M1A-001B remediation and M1A-002 bounded PubMed connector

Updated: `2026-08-05`
Repository: `D:\Projects\medevidence`
Branch: `codex/m1a-001b-remediation-m1a-002`

## Goal

Locally commit a verified M1A-001B mixed selected/skipped report-contract
remediation and then a fully bounded, offline-tested M1A-002 PubMed connector,
without any live API or remote Git operation.

## Work items

| ID | Requirement IDs | Work item | Status | Owner | Done when | Evidence | Reviewer |
|---|---|---|---|---|---|---|---|
| P1 | R1-R3 | Remediate `ResearchReport` planning semantics, tests, and stale status text | DONE | main | Focused/full offline gates and independent review pass | Focused 117 passed; full 164 passed | Independent final re-review PASS |
| P2 | R10 | Terminal audit and local M1A-001B commit | VERIFYING | main | Audit PASS, exact commit created, post-commit tree clean | Independent terminal audit PASS; local commit pending | Independent terminal audit PASS |
| P3 | R4-R9 | Add approved dependencies and implement bounded PubMed connector/parser | PENDING | main | Full Owner test matrix passes offline | Pending | Pending |
| P4 | R10 | Dependency/evidence audit, independent review, remediation, and local M1A-002 commit | PENDING | main | All gates PASS, exact commit created, final tree clean | Pending | Pending |

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

## Bug queue

| Bug ID | Requirement IDs | Found by | Reproduction | Owner | Status | Retest | Reviewer |
|---|---|---|---|---|---|---|---|
| B-001 | R1-R3 | Owner task + independent analysts | Mixed PubMed selected / CADEC skipped report is rejected by blanket selected-only aggregate check | main | FIXED | Focused and full suites PASS | Independent final re-review PASS |

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

## Unverified risks

- Exact M1A-002 resolved dependency graph and license/vulnerability result are
  unknown until the approved pins are locked and audited.
- Connector numeric defaults and public DTO shape are new but remain
  connector-local and require independent review.
- No current code exercises HTTP redirects, deadlines, hardened XML, or
  partial pagination; these are P3 test gates.

## Current step

`P2 - create the exact scoped local M1A-001B commit.`

## Next step

Stage only the seven audited M1A-001B paths, create the local commit, and verify
the post-commit state before starting P3.

## Latest handoff

```text
Task: Discovery and requirement synthesis
Status: COMPLETED
Confirmed facts: B-001 reproduced; branch and host decisions resolved
Paths and symbols: reports.py validate_aggregate; report/source tests; connector package absent
Commands and results: Git safety PASS; baseline 158 tests PASS; no live API
Findings: blanket selected-only rule is the defect; exact host absent locally
Assumptions and unknowns: dependency graph and connector defaults await P3
Files modified: .delivery/SPEC.md, .delivery/STATE.md
Recommended next action: implement P1 test-first
```
