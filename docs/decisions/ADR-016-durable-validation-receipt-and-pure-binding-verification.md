# ADR-016: Durable validation receipt and pure binding verification

- Status: Accepted by Project Owner
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-27
- Approval reference: `M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION`
- Revision: 3
- Independent review reference: M3-002 successor-002 Review 008 — immutable FAIL
- Independent review role: Validation only; not an approving authority

## Context

M3-002 successor-002 composes one application-owned canonical report validator
directly into the controlled workflow. Independent Review 003 remains immutable
`FAIL — P0 0 / P1 2 / P2 0`. It demonstrated that a forged passing checkpoint
could reach pending-draft persistence because pure `VERIFY_BINDING` could
reconstruct the same caller-supplied passing values but could not prove that
Stage 2 had previously executed. It also demonstrated that aggregation could
accept a claim with both semantically supported supporting evidence and a
semantically confirmed contradicting citation.

Re-executing Stage 2 at every resume and effect boundary would make binding
verification potentially model-backed, expensive, non-deterministic, and
side-effecting. Trusting a boolean, result enum, inline receipt, caller hash, or
checkpoint-supplied receipt body would leave the forged-checkpoint defect open.
Review 004 returned immutable `FAIL — P0 0 / P1 1 / P2 1`. It identified that
the implementation delivery record incorrectly described every injected
capability itself as untrusted even though durable proof necessarily depends on
a trusted independently durable receipt-store capability selected by the
application. It also identified missing executable coverage for post-save
missing reload and receipt-load capability error, both of which manually failed
closed with zero later effects.

Independent Review 008 returned immutable `FAIL — P0 0 / P1 0 / P2 2` after
independently verifying the executable Round-7 closures. It found that this ADR
still described receipt loading before canonical verification and did not record
the independently durable pending-draft capability and binding sequence. It
also found a delivery-record scope sentence that conflated the frozen 19-path
allowlist with the 18 paths actually changed.

## Decision

Stage 2 executes only during canonical assessment. Pure deterministic
`VERIFY_BINDING` is retained and makes zero semantic-evaluator calls during
resume, pending-draft save, approval, export, finalization, idempotent exported
return, and synthesis-bearing terminal return.

Formal progression requires an independently persisted immutable validation
receipt with marker `M3_VALIDATION_RECEIPT_V1`. The receipt semantically binds,
at minimum:

- schema and marker version, receipt identity, run identity, and report
  identity;
- the exact report-content hash and canonical validation-input identity/hash;
- the exact selected-source/task/outcome binding identity;
- the Stage-1 result identity;
- the Stage-2 evaluator method and version identity;
- the exact ordered per-claim/per-citation Stage-2 result identity;
- the relationship-aware aggregate result identity; and
- every policy/configuration version required for deterministic binding.

The receipt identity is derived from canonical semantic receipt content through
the repository's canonical JSON and SHA-256 identity conventions. Operational
timestamps may be retained but do not redefine semantic identity. The receipt
contains no opaque confidence score.

The durable workflow state carries only `validation_receipt_ref`. It never
carries an authoritative receipt body. Only the canonical assessment path may
construct a formal receipt, in this order:

```text
canonical current-state reconstruction
  -> deterministic Stage 1
  -> Stage 2 evaluation
  -> relationship-aware aggregation
  -> canonical receipt construction and identity derivation
  -> immutable receipt persistence
  -> checkpoint receipt reference
```

Receipt persistence must succeed before a durable passing checkpoint may
reference it. Evaluator failure creates no passing receipt. Receipt persistence
failure creates no passing durable state. Receipt creation performs no report
approval or export.

The trust boundary is trusted static application composition plus the trusted
independently durable `ValidationReceiptStorePort` and `DraftPersistencePort`
capabilities it selects. A successful `save_receipt` means the exact receipt is
independently durable before return; `load_receipt` returns only durable store
state. A successful `save_pending` means the exact pending draft is durable
before return; `load_pending` returns only durable store state. Both application
adapters remain replaceable, but replacement is a trusted composition action,
not runtime request/checkpoint data. Every returned receipt mapping and
`PendingDraftRef` remains untrusted data.

Before any pending/receipt-store capability, approval, export, finalization,
idempotent exported return, or synthesis-bearing terminal trusted return, the
workflow reconstructs the complete durable state, application topology, and
canonical request, then calls pure evaluator-free `VERIFY_BINDING`. A route
whose checkpoint contains a pending-draft reference next loads that exact
pending draft through the trusted `DraftPersistencePort`, reconstructs the
returned `PendingDraftRef`, and binds its persistence identity, report identity,
and content hash to the approved report state. Only then does the workflow load
the referenced receipt through the trusted receipt store, reconstruct its exact
contract, verify its identity and content, and bind it to the current
run/report/content/validation inputs/source topology/evaluator/policy. Only a
fully bound route may invoke its effect or return trusted terminal state.
Missing, unknown, inline-only, foreign-run, stale-content, different-input,
malformed, or internally inconsistent pending drafts or receipts fail closed
before any later effect or trusted return. Every runtime value, checkpoint,
receipt payload, receipt-store return, and pending-store return is untrusted
data; application reconstruction and the canonical validator remain
authoritative.

The save route follows the same pre-capability ordering through receipt binding,
then invokes `save_pending`. It reconstructs and binds the returned pending
reference and immediately calls `load_pending` to read back, reconstruct, and
bind the exact durable row before publishing it in a checkpoint. A missing,
foreign, stale, substituted, malformed, or unavailable read-back creates no
pending-review checkpoint.

A fake or caller-selected store that manufactures a self-consistent receipt
without an independently durable save violates the trusted capability contract
and trusted composition. It is outside ordinary runtime DATA injection. The
design does not attempt an origin token, binder, callable fingerprint, runtime
capability authentication, or general Python anti-tamper defense.

Any report or validation-relevant state edit clears the receipt reference. The
edited state requires a new canonical assessment and newly persisted receipt
before formal progression. Receipts are never silently repaired or upgraded.

An actual PostgreSQL migration is required. Existing durable checkpoints can
serialize the reference but provide no independent application-owned store, so
they cannot authenticate their own proof. The migration adds only an immutable
validation-receipt table; no unrelated table, column, index, public API,
OpenAPI, dependency, source, evidence, retrieval, corpus, qrels, or metric
contract changes are authorized. The checkpoint reference remains in the
existing durable payload rather than requiring a new report/checkpoint column.

Stage-2 aggregation is relationship-aware under the existing relationships
`supports`, `contradicts`, and `context_only`:

1. `context_only` never satisfies direct material-claim support.
2. Automatic `supported` requires at least one `supports` citation evaluated
   `supported`, no unresolved semantically confirmed contradiction, and no
   required direct citation remaining `uncertain`.
3. An applicable, semantically confirmed `contradicts` citation prevents
   automatic `supported`; the default unresolved aggregate is `uncertain`.
4. Majority vote, citation count, retrieval score, confidence, and source-type
   weighting never resolve the conflict.
5. Only the existing governed comparability/conflict adjudication contract may
   contextualize a contradiction, and that resolution remains explicit.

## Alternatives considered

- Re-execute Stage 2 before every effect and trusted return. Rejected because
  it violates pure deterministic binding verification.
- Trust a checkpoint boolean, result enum, inline receipt, self-computed hash,
  or caller-provided receipt body. Rejected because the checkpoint is untrusted
  and cannot manufacture proof of prior assessment.
- Store receipt content inline in the checkpoint without an independent store.
  Rejected for the same self-authorization defect.
- Stop successor-002 as non-integrable. Not selected because the Owner
  authorized this exact minimal durable-receipt design.

## Consequences

- Pure `VERIFY_BINDING` remains deterministic and evaluator-free.
- Formal transitions obtain durable proof that canonical Stage 1 and Stage 2
  executed for the exact current report inputs.
- The application owns receipt reconstruction, identity verification, and
  transition authority; trusted static composition selects the replaceable
  independently durable receipt-store and pending-draft adapters.
- One receipt table, source-neutral store capability, repository adapter, and
  migration are required and are limited to this work item.
- Report edits invalidate prior proof and require a new assessment.
- Supporting and contradicting evidence cannot automatically collapse to a
  passing material claim.
- Arbitrary Python interpreter, process, or memory compromise remains outside
  the trust model; no general runtime anti-tamper system is introduced.

## Validation

- A forged passing checkpoint with no stored receipt performs zero evaluator,
  persistence, approval, export, or finalization calls and fails closed.
- A valid-looking inline-only receipt, foreign-run receipt, stale report receipt,
  and different-validation-input receipt each fail closed.
- A receipt produced and persisted by canonical assessment permits progression
  while `VERIFY_BINDING` performs zero semantic-evaluator calls.
- Every effect/terminal route performs complete local reconstruction and pure
  `VERIFY_BINDING` before either durable-store capability; routes with a pending
  draft then bind its exact durable read before receipt loading and binding.
- Pending-draft save publishes no checkpoint reference until an immediate exact
  durable read-back succeeds; missing, substituted, stale, foreign, or malformed
  pending data fails closed with no later effect.
- Editing receipt-bound state rejects the old receipt and requires a new
  assessment and receipt.
- Supporting-only, supporting-plus-confirmed-contradiction, context-only, and
  existing explicit human-resolution cases enforce the frozen aggregation
  rules.
- PostgreSQL migration, immutable save/idempotent exact replay, conflicting
  duplicate rejection, load/not-found, and transaction-failure tests pass.
- Workflow tests cover successful save followed by missing reload and receipt-
  load capability error; both fail closed before reference publication or any
  later effect.
- Independent review traces assessment through receipt persistence, checkpoint
  reference, pure binding verification, and every effect/terminal boundary.

## Supersedes / Superseded by

Supersedes none. This record supplements ADR-005 and ADR-007 without rewriting
their accepted history. Superseded by none.
