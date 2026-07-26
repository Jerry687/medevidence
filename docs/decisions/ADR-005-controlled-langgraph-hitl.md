# ADR-005: Controlled LangGraph workflow and HITL

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

The project should demonstrate durable agent orchestration without moving
connector, retrieval, validation, or export business logic into prompts and
graph nodes. LangGraph resume can re-execute code around an interrupt, creating
duplicate side effects if export is not idempotent.

## Decision

V1 uses one bounded LangGraph workflow with thin nodes for scope/safety,
planning, collection, synthesis, validation, review, and finalization.

HITL is used only for formal export confirmation:

1. deterministic citation and safety gates pass;
2. `save_pending_draft` idempotently saves the draft as `pending_review`;
3. `request_export_approval` interrupts with report identity, hash, destination,
   coverage, and warnings;
4. no non-idempotent side effect occurs before approval;
5. approval routes to a separate `finalize_and_export` node;
6. export uses `report_id` and an idempotency key;
7. repeated resume/export returns the existing result;
8. rejection exports nothing;
9. edits change the hash, rerun validation, and require new approval.

The exact sequence is:

```text
validate_report
  -> save_pending_draft
  -> request_export_approval
  -> finalize_and_export
```

No additional V1 interrupt is permitted for broad, sensitive, or expensive
queries. Such requests are deterministically bounded, rejected, or safely
degraded.

PostgreSQL provides durable checkpoints and report/export state.

## Alternatives considered

- An open-ended ReAct agent.
- Human approval before every source query.
- Export inside the same node before or around the interrupt.
- In-memory-only checkpoints for the final V1.

## Consequences

- Tool behavior and safety remain independently testable.
- Formal export has an auditable, duplicate-resistant transition.
- Ordinary research queries do not require unnecessary approval.
- Node and state design must preserve idempotency and bounded retries.

## Validation

- Resume and retry tests create exactly one export for one idempotency key.
- Rejected and failed-validation reports cannot export.
- Graph nodes do not instantiate connectors or storage/vector clients.
- Partial source failure produces a report with explicit coverage.

## Supersedes / Superseded by

None.
