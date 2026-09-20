# ADR-025: fixed Attempt011 calibration successor

Status: implementation under offline verification; live execution not started.
Decision date: 2026-09-14.
Authority: Owner delegated completion and remaining engineering decisions in
the current session. The supervisor selects this bounded successor. Historical
Attempt009/010 closure remains immutable and is not reinterpreted as success.

## Decision

Create a distinct fixed Attempt011 calibration identity. Preserve the frozen
36-case Development/synthetic packet, semantic V2 contract, DeepSeek model,
prompt/rubric, request configuration, 45-second shared per-case deadline and
maximum three HTTP attempts. The attempt label is new; old rows and results
must never be relabelled. A new hash-derived provider run identity binds the
new candidate configuration.

Before promoting active behavior, add dedicated Attempt010 historical
configuration, event, projection, case, status and external replay verification
with exact hashes from the original immutable artifacts. Existing Attempt007,
008 and 009 replay remains unchanged. New-run validation must reject historical
authority and historical replay must reject new-run authority.

The existing insert-only provider-attempt schema supports distinct hash-derived
run identities, so no database schema or provider transport policy change is
needed for this node. Keep START-before-send, lease, interrupted-attempt
reconciliation, no resend of existing runs, strict output/raw-path admission,
credential screening and terminal evidence accounting.

## Execution gates

No provider request precedes focused tests, full offline unit/contract gates,
PostgreSQL migration/ledger integration, independent review and terminal audit.
The exact candidate/input/output/run bounds must be recorded before a live run.
The output directory must be absent and non-reparse under the canonical project
`.local/evidence` tree. Neither Holdout nor medical-source requests are needed
for this calibration. A failed run remains failed with immutable raw evidence.

## Limits

The small-chunk fix provides checks between received raw chunks, not hard
wall-clock cancellation of a blocking read. Attempt011 is not presumed to fix
historical provider availability. Acceptance is computed from the full frozen
packet and actual persisted results, never from offline test counts or a
partial set of successful cases.

This dated successor authorization supersedes prior statements that no future
Attempt011 work was authorized. It does not alter those statements as records
of the earlier closure decision, nor accept M3-008B before new run evidence.
