# ADR-007: Domain contracts and schema versioning

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

A single generic evidence object cannot safely represent publications, labels,
FAERS aggregates, CADEC annotations, retrieval chunks, claims, and citations.
The project also needs typed contracts without leaking infrastructure objects.

## Decision

V1 uses Pydantic v2 for typed, source-aware contracts. The stable model groups
are:

- configurable research scope and terminology mappings;
- source-planning status, discriminated source-record types, provenance, and
  execution outcomes;
- evidence items and derived document chunks;
- retrieval queries and hits;
- claims, citations, comparability/conflict;
- reports, review/export state, and bounded workflow state.

FAERS aggregates and CADEC auxiliary records retain distinct types and allowed
uses. Qdrant, SQLAlchemy, FastAPI, LangGraph, MCP, and model-provider native
objects cannot become domain contracts.

Persisted and externally exchanged schemas have explicit versions. Temporary
internal helpers do not require independent versions.

Source planning and execution are separate. A considered source has
`planning_status=selected`, `skipped_not_applicable`, or `skipped_by_policy`.
Skipped sources have no `SourceOutcome`. Only an actually executed source may
produce the three-dimensional outcome:

- execution: `succeeded` or `failed`;
- coverage: `complete`, `partial`, or `unavailable`;
- result: `matches`, `no_match`, or `indeterminate`.

The seven valid combinations and all invalid classes are normative in
`ARCHITECTURE.md` Section 7.5. Only successful complete execution may produce
`no_match`; partial or failed zero-result execution is `indeterminate`.

## Alternatives considered

- One generic dictionary/document type for all layers.
- Standard-library dataclasses plus separate boundary mappers.
- Vendor-native Qdrant/LangChain documents as shared contracts.
- Version every temporary DTO.

## Consequences

- Runtime validation and serialization are consistent across tools, API, graph,
  fixtures, and evaluation.
- Domain code depends on Pydantic but not application frameworks or vendors.
- Schema evolution requires compatibility tests and migration policy.
- Source-specific distinctions remain visible.

## Validation

- Schema tests reject invalid source/claim combinations and missing provenance.
- Serialized contracts include supported schema versions.
- Dependency checks find no prohibited vendor types in domain schemas.
- Historical fixtures remain readable or fail with an explicit incompatibility.

## Supersedes / Superseded by

None.
