# M3-001 controlled orchestration contracts delivery record

Updated: `2026-08-19`

Status: **M3-001_REMEDIATION_CYCLE_8_CANDIDATE_AWAITING_EXTERNAL_REVIEW_AUDIT**

Feature branch: `codex/m3-001-controlled-orchestration-contracts`

Approved baseline: `c348fdba0d16bb5c3ccb23c1212d682eac6de938`

## Scope and design

M3-001 introduces framework-neutral, source-neutral orchestration contracts
for the already accepted bounded topology:

1. `scope_and_safety`
2. `plan_sources`
3. `collect_evidence`
4. `synthesize_claims`
5. `validate_report`
6. `save_pending_draft`
7. `request_export_approval`
8. `finalize_and_export`

No LangGraph, model-provider, connector, retrieval, database, API, export
destination, or new production dependency is added. Graph nodes coordinate
typed references and injected source-neutral capabilities; they do not copy
large source payloads or instantiate provider/framework objects.

The state retains run/report identity, original and interpreted
`ResearchScope`, an internal safety decision/reason, bounded source plan and
task state, `SourceOutcome` references, evidence/claim/citation references,
comparability/conflict references, validation and review/export state, report
hash, destination reference, and idempotency identity. It wraps the existing
`M1BSourcePlanEntryV1` and authoritative seven-combination `SourceOutcome`
contracts without changing public domain or API schemas.

Unresolved medical-boundary wording remains typed internal policy outcomes;
there is no new user-facing clinical or emergency wording decision.

## Frozen invariants

- A skipped source has no task and no fabricated `SourceOutcome`.
- Every selected source has exactly one task; synthesis waits for every
  selected task to reach a valid terminal source outcome.
- Persisted checkpoints fail closed if collection is marked complete, or the
  current node is beyond collection, while any selected task lacks a terminal
  `SourceOutcome` reference.
- Partial and unavailable coverage remain visible in the task/outcome
  references.
- Workflow-level collection failure never becomes `no_match` and carries no
  fabricated evidence.
- Failed report validation cannot reach pending review, approval, or export.
- Editing changes the report hash, invalidates approval, and requires
  revalidation and a new approval.
- No export capability is invoked before approval.
- `finalize_and_export` independently rechecks terminal `SourceOutcome`
  coverage for every selected task before calling the export capability.
- Export receives a deterministic report/destination idempotency key; resume
  returns the existing result instead of duplicating the side effect.
- Retrieved or synthesized content cannot expand the frozen node/permission
  set.

Collection is checkpointed at one logical attempt per transition. A task moves
from pending/retry-wait to a durable running checkpoint before I/O. Attempts
have stable task-bound IDs and idempotency keys. Typed retryable failures are
bounded at eight attempts; permanent or exhausted failures enter a blocked
workflow state without a source outcome. Unexpected exceptions are translated
to a non-retryable workflow execution error with the original cause and exact
attempt identity preserved.

## Repository files

| Path | Bytes | SHA-256 |
|---|---:|---|
| `src/medevidence/orchestration/__init__.py` | 2,303 | `fb066cceb6e203e2e8c3b6be7a147ba8b0766cbffc894e1ab82dd16070046879` |
| `src/medevidence/orchestration/contracts.py` | 30,663 | `94533513d969530cd7ac8214217311d583a1f11213f8be2f4822cb0dbab84423` |
| `src/medevidence/orchestration/ports.py` | 3,159 | `90fc6f9bdcc99f013c142c34507858572f4e679cb9f141ce89ab03025c35902a` |
| `src/medevidence/orchestration/workflow.py` | 24,186 | `41bb3bf12fd6cfed8daf3bdf093679dd119dbd75ebb854e15076d6d3d7eb84a3` |
| `tests/unit/orchestration/test_contracts.py` | 12,060 | `c1ff56ba51d145f891729a1210e546faac79616074641e005d1087901ff60919` |
| `tests/unit/orchestration/test_workflow.py` | 34,339 | `be2b7957806c162d1d7fa9856caffa841d4891c14614980136f2710679e36128` |

This delivery record is the seventh authorized repository path. No dependency,
lock, domain, API, connector, retrieval, persistence, evaluation, corpus,
qrels, metric-contract, or frozen M2 path changes.

## Validation

- Focused orchestration suite after cycle 8: **37 passed** with sockets
  disabled.
- The final cycle-8 full socket-disabled unit/contract suite was
  **2,048 passed**, two expected warnings, `79%` coverage, in `50.68s`.
- Ruff check: **PASS**.
- Ruff format check: **147 files already formatted**.
- MyPy: **57 source files PASS**.
- Locked dependency check: **PASS** (`87` packages, no change).
- `git diff --check`: **PASS**.
- Candidate scope before this record: exactly six authorized new paths; with
  this record: exactly seven authorized new paths.

Validation used the already locked baseline environment with the isolated
worktree source on `PYTHONPATH`; no package synchronization or download was
performed. An ignored bootstrap-only worktree `.venv` created by the first
`uv run` attempt is outside Git scope and contains no synchronized project
dependencies.

## Independent review and remediation

R1 returned **FAIL — P0 0 / P1 1 / P2 0** because a multi-source collection
transition checkpointed only after every source, so a later exception could
repeat an earlier completed source.

Remediation cycle 1 changed collection to process and checkpoint one source at
a time. R2 confirmed that closure but returned **FAIL — P0 0 / P1 1 / P2 0**
because the active attempt itself was not checkpointed or bounded before I/O.

Remediation cycle 2 added the two-phase attempt checkpoint, stable attempt
identity, typed retry/permanent failures, eight-attempt bound, blocked state,
and non-retryable unexpected-error translation. R3 returned
**PASS — P0 0 / P1 0 / P2 0** with no remaining findings.

A subsequent delivery-record review returned
**FAIL — P0 0 / P1 0 / P2 1** because it described the ignored bootstrap
environment as empty and gave a self-hash verification instruction that the
record could not satisfy. Documentation remediation cycle 3 corrected both
statements: the environment is identified as bootstrap-only with no
synchronized project dependencies, and the six table identities are separated
from the delivery record's external exact-byte binding. This successor record
is independently rebound before terminal audit.

The cycle-3 successor review then returned
**FAIL — P0 0 / P1 0 / P2 1** because the record had not yet preserved that
delivery-review failure and its remediation. Documentation remediation cycle 4
added the missing history block. Its successor review returned
**FAIL — P0 0 / P1 0 / P2 1** because the new review result and cycle-4
resolution were not yet recorded. The then-final authorized documentation
remediation cycle 5 appended this complete pre-audit failure history. Its
external exact-byte rebind returned **PASS — P0 0 / P1 0 / P2 0**.

The subsequent terminal audit returned **FAIL — P0 0 / P1 1 / P2 0**. Its
counterexample deserialized a schema-valid checkpoint that marked collection
and synthesis complete while one selected task remained `pending`, then
reached `exported` with `collector_calls=0`, `export_calls=1`, and zero source-
outcome references. The root causes were a missing post-collection checkpoint
invariant in `OrchestrationState.validate_checkpoint` and a missing independent
selected-task terminal guard in `finalize_and_export`.

That terminal failure and five-of-five remediation exhaustion are preserved in
the append-only external stop record
`D:/Projects/medevidence-external-evidence/M3-001-CONTROLLED-ORCHESTRATION-CONTRACTS/stop-001.json`:
5,499 bytes, SHA-256
`0e9f79f275b5be8515648f0358f6bba18b3486db448f5eea23d2b9c6bd79d7e0`.
The stop record is immutable history and was not rewritten.

After that stop, the Owner explicitly authorized one exceptional additional
remediation cycle, cycle 6 of 6, limited to the exact seven paths. Cycle 6 adds
the fail-closed persisted-checkpoint invariant and the export-time defense in
depth without changing retry, source-outcome, topology, or public-contract
semantics. Regressions reject pending selected tasks at post-collection and
post-synthesis deserialization, retain valid pending collection resume, and
prove a validation-bypassing corrupt finalization state calls neither collector
nor exporter and creates no source outcome or export record.

The cycle-6 Reviewer then returned **FAIL — P0 0 / P1 1 / P2 0**. A
validation-bypassing `model_copy` appended a duplicate same-source `pending`
task to an otherwise valid ready-to-finalize state. The set-based export guard
collapsed that duplicate and permitted export, so cycle 6 did not close the
selected-task finalization invariant.

The Owner subsequently authorized at most cycles 7 through 9 for that same
finding only. Cycle 7 reconstructs the exact durable state at the top of
`finalize_and_export`, translates Pydantic validation failure to a deterministic
`WorkflowTransitionError` with its cause preserved, and then compares ordered
selected plan rows, all task rows, and terminal outcome-backed task rows one to
one before either export I/O or an existing-export idempotent return. Focused
regressions cover duplicate pending, sole pending, missing outcome, duplicate
terminal, and corrupted already-exported shapes while preserving valid export
and valid idempotent resume.

Cycle-7 intermediate independent review returned
**PASS — P0 0 / P1 0 / P2 0** after reproducing the corruption matrix and
valid direct-finalization idempotent behavior. The subsequent final cycle-7
review returned **FAIL — P0 0 / P1 1 / P2 0** on the same manifestation through
a different entry point: `run_next` returned any `current_node=None` checkpoint
before durable reconstruction, so an exported state with a duplicate same-
source `pending` task bypassed the cycle-7 finalization guard.

Cycle 8 centralizes durable checkpoint reconstruction and invokes it at the
very top of both `run_next` and `finalize_and_export`, before terminal return,
dispatch, export I/O, or idempotent return. The exact regression mutates a
valid exported state by appending one duplicate same-source `pending` task and
proves `run_next` raises the deterministic `WorkflowTransitionError` with the
Pydantic cause preserved, performs no collector call, adds no export call, and
does not return the corrupt state. Valid terminal resume remains an equality-
preserving no-op with one historical export total.

Cycle-8 intermediate independent review returned
**PASS — P0 0 / P1 0 / P2 0** after exercising corrupt terminal states for
every terminal disposition, corrupt active/dispatch states, the full direct-
finalization matrix, and valid resume/idempotent behavior. Fresh final
independent review, exact-byte rebind, and terminal audit remain external. This
record does not self-attest those results or claim terminal PASS.

The terminal audit is a separate lifecycle gate and is not self-attested by
this record. Commit, push, PR, merge, and control-plane successor maintenance
occur only after that gate passes.

## Network, Holdout, and Git boundary

Implementation, validation, review, and remediation performed no medical-
source request, model/provider execution, dependency download, advisory lookup,
retrieval run, or Holdout-20 access. The canonical repository's unrelated
`evaluation/metrics.py` change was not touched. At this reviewed snapshot the
seven authorized paths are uncommitted and unstaged; no amend, force-push,
rebase, reset, clean, history rewrite, or branch deletion occurred.

## Manual verification

1. Rehash the six implementation/test paths and compare them with the table;
   compare this delivery record separately with the terminal exact-byte binding.
2. Run `pytest tests/unit/orchestration --disable-socket`.
3. Exercise a two-source collection where source one completes and source two
   fails; verify source one is never dispatched again.
4. Exercise eight typed retryable failures and verify collection blocks without
   a `SourceOutcome`, evidence, synthesis, approval, or export.
5. Exercise approve, reject, edit, and resumed export paths and verify only the
   exact approved hash/destination can produce one export.

## Owner interview questions

1. Why does M3 state reference `M1BSourcePlanEntryV1` and `SourceOutcome`
   instead of modifying the public M1A report/source-plan contracts?
2. Why is collection split into a pre-I/O attempt checkpoint and a later
   dispatch transition?
3. How do validation state, report hash, approval binding, and the idempotency
   key jointly prevent an unvalidated, edited, or duplicate export?
