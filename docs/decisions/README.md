# Architecture Decision Records

Architecture Decision Records (ADRs) capture consequential decisions that
affect multiple layers, evidence semantics, safety policy, public contracts, or
production dependencies.

## Naming

```text
ADR-NNN-short-kebab-case-title.md
```

Start with `ADR-001`. Do not renumber accepted records.

## Status values

- Proposed
- Accepted
- Superseded
- Rejected
- Deprecated

## Required sections

```markdown
# ADR-NNN: Decision title

- Status:
- Approved by:
- Approval role:
- Approval date:
- Approval reference:
- Revision:
- Independent review reference:
- Independent review role: Validation only; not an approving authority

## Context
## Decision
## Alternatives considered
## Consequences
## Validation
## Supersedes / Superseded by
```

## Owner-accepted V1 records

These decisions were accepted by the Project Owner for M0. The original M0
audit FAIL and conditional approval remain preserved in their historical
records; the frozen remediation later received an unconditional independent
PASS and M0 became effective. The independent reviewer validates consistency
and is not the approving authority.

- [ADR-001: V1 reference domain](ADR-001-v1-reference-domain.md)
- [ADR-002: Source semantics](ADR-002-source-semantics.md)
- [ADR-003: Storage and snapshots](ADR-003-storage-and-snapshots.md)
- [ADR-004: Qdrant hybrid retrieval](ADR-004-qdrant-hybrid-retrieval.md)
- [ADR-005: Controlled LangGraph HITL](ADR-005-controlled-langgraph-hitl.md)
- [ADR-006: Evaluation split and reproducibility](ADR-006-evaluation-split-and-reproducibility.md)
- [ADR-007: Domain contracts and schema versioning](ADR-007-domain-contracts-and-schema-versioning.md)
- [ADR-008: V1 technology stack](ADR-008-v1-technology-stack.md)

Any change to an accepted decision requires a new ADR that supersedes it. Do
not edit history to make a prior decision appear different.

## Owner-accepted M1A governance record

- [ADR-009: M1A PubMed vertical-slice contracts and dependency gate](ADR-009-m1a-pubmed-vertical-slice-contracts.md)
  - Status: Accepted by Project Owner; effective for the post-merge M1A
    sequence
  - Authorization package:
    [M1A-001A-OWNER-AUTHORIZATION-001](../reviews/M1A-001A-OWNER-AUTHORIZATION-001.md)
  - Independent governance review:
    [M1A-001A-INDEPENDENT-REVIEW-001](../reviews/M1A-001A-INDEPENDENT-REVIEW-001.md)
  - Effect: After this exact governance candidate is merged into `main`, only
    `M1A-001B` may begin from the resulting approved baseline

ADR-009 approves the bounded M1A sequence, source-neutral PubMed contracts,
exact citation and snapshot semantics, synchronous PostgreSQL persistence,
draft-only FastAPI transport, `M1A-LIVE-RETENTION-v1`, and exact direct
dependency pins. The live query itself remains separately unauthorized, no
standalone ASGI server is approved, and no implementation, installation, or
lock-file change may occur on the unmerged governance branch.

## Owner-accepted M1A remainder amendment

- [ADR-010: M1A remainder freeze amendment](ADR-010-m1a-remainder-freeze-amendment.md)
  - Freeze: `M1A-REMAINDER-FREEZE-v3`
  - Present state: cycle-4 remediation committed and pushed; first hosted
    rerun PASS; evidence reconciliation and integration pending

ADR-010 appends exact journal identity, ordinal-reference, immutable snapshot,
canonical manifest, and constrained-capacity rules while preserving ADR-009
history. The implementation commit is
`c3d724b2097c8df1249b217f610a78291039edbb`. Hosted run `31146015339`
identified a Windows LF-checkout portability defect and remains recorded as a
failed run. Exact seven-path remediation commit
`52e71f0802e31580304980f487eba3c23f57db41` was pushed to PR `#4`; a fresh
`core.autocrlf=true` clone verified the LF checkout and the two formerly
failing tests passed 2/2. Hosted rerun `31147466248` passed compose-config
(114 cases), Ruff, format (32 files), MyPy (17 source files), and the offline
unit/contract suite (424 passed, one expected warning, 86% coverage).
Independent evidence-only review/audit of the reconciliation candidate, its
later commit/push and hosted rerun, PR readiness, merge, and approved-`main`
integration remain pending. No live-source validation occurred. It provides
no database, tool, report, or API implementation.

## Owner-accepted M2 DailyMed source-native section record

- [ADR-014: M2 DailyMed source-native section occurrences](ADR-014-m2-004-dailymed-source-native-sections.md)

ADR-014 separates exact provider display titles from frozen generic LOINC
names and preserves repeated same-code SPL occurrences by source location and
content. It is additive to ADR-011, authorizes no medical-source request, and
does not complete or rerun the stopped M2-003 Gold-10 work item.

## Owner-accepted M2 Gold-10 V2 acquisition record

- [ADR-015: M2-005 MedEvidence Gold-10 V2 acquisition and corpus freeze](ADR-015-m2-005-medevidence-gold10-v2.md)

ADR-015 reuses the immutable M2-003 PubMed and OZEMPIC evidence, applies only
two exact deletion-only safe-parsing transformations, and admits M2-004
source-native retrieval occurrences without deduplication. Its new one-shot
MOUNJARO authority is gated by a fresh independent pre-network PASS and exact
live acknowledgement; it never transfers authority from M2-003.

## Owner-accepted M3 durable validation-receipt record

- [ADR-016: Durable validation receipt and pure binding verification](ADR-016-durable-validation-receipt-and-pure-binding-verification.md)

ADR-016 preserves evaluator-free deterministic `VERIFY_BINDING` and requires
formal workflow progression to load and bind an independently persisted
`M3_VALIDATION_RECEIPT_V1` receipt created only by canonical assessment. It
authorizes one minimal PostgreSQL receipt migration and relationship-aware
Stage-2 aggregation for successor-002. It does not rewrite ADR-005 or ADR-007,
authorize public API changes, or claim implementation, review, audit, or PASS.

## Owner-accepted M3 LangGraph checkpoint-runtime record

- [ADR-017: LangGraph PostgreSQL checkpoint runtime](ADR-017-langgraph-postgres-checkpoint-runtime.md)

ADR-017 records the exact Owner-approved `langgraph==1.2.11` and
`langgraph-checkpoint-postgres==3.1.2` runtime, fixed eight-node topology,
primitive-only untrusted checkpoint boundary, and isolated package-owned
PostgreSQL checkpoint schema. It preserves ADR-016 validation-receipt authority
and adds no source adapter, provider, public API, business-lifecycle migration,
or export behavior. The round-6 independent review remains immutable
`FAIL — P0 0 / P1 3 / P2 2`; round 7 closed all executable findings, and its
fresh re-review returned immutable `FAIL — P0 0 / P1 0 / P2 1` solely for
stale delivery evidence. Round 8 updates only governance/evidence and requires
fresh re-review, exact-byte rebind, and terminal audit before any PASS or Git-
integration claim.

## Owner-accepted M3 source-capability record

- [ADR-018: M3 source capability adapters](ADR-018-m3-source-capability-adapters.md)

ADR-018 freezes exact plan-row/task equality, durable required-operation
planning, four-dimensional multi-operation aggregation, explicit PubMed,
DailyMed, FAERS, and CADEC adapters, and the transient exact-asset CADEC BM25
runtime. It supersedes only the M1B authorization deferral for this exact M3
runtime; immutable M1B/M2 semantics and evidence remain unchanged. It adds no
dependency, public API/schema, medical network, model/provider, persistence,
router, qrels, corpus, metric-contract, or Holdout authority.

The initial ADR-018 candidate review remains immutable
`FAIL — P0 0 / P1 4 / P2 0`. Round 3 adds exact operation subject identities,
aggregate-plus-child terminal provenance, exact CADEC verification and degraded
zero-ref reconstruction, and sealed concrete DailyMed/FAERS projection
authorities required by exact type at composition. The candidate is
`AWAITING_FRESH_REVIEW_AFTER_ROUND_3`; no PASS or Git integration is claimed.

The fresh Round 3 review remains immutable
`FAIL — P0 0 / P1 3 / P2 0`. Round 4 closes its asset-free fake CADEC,
uncheckpointed dynamic suffix, and self-consistent terminal forgery findings
with v3 typed inputs/progress/acquisition intents, durable PubMed/DailyMed
reload, canonical all-field outcomes, and final sealed infrastructure CADEC
composition. Status is `AWAITING_FRESH_REVIEW_AFTER_ROUND_4`; no PASS or Git
integration is claimed.

Final Round 10 fresh independent review returned
`PASS — P0 0 / P1 0 / P2 0` with no findings after directly exercising planner
attacks and authoritative replay/composition paths. All immutable FAIL history
remains preserved. Status is `AWAITING_TERMINAL_AUDIT`; this is not an overall
terminal PASS or Git-integration claim.

The fresh Round 9 review remains immutable
`FAIL — P0 0 / P1 1 / P2 0`. Final Round 10 introduces the exact final/slotted/
immutable `CanonicalSourcePlanningAuthority`, rejects mutable Protocol planners,
and uses class-qualified initial/replay calls. Status is
`AWAITING_FINAL_FRESH_REVIEW_AFTER_ROUND_10`; remediation budget 10/10 is
exhausted and no PASS or Git integration is claimed.

The fresh Round 4 review remains immutable
`FAIL — P0 0 / P1 3 / P2 0`. Round 5 closes writable CADEC authority,
source-replay omission, and coordinated PubMed journal/checkpoint substitution
with frozen concrete CADEC replay, a PubMed terminal receipt and concrete
composition, durable DailyMed/FAERS replay, and mandatory
`validate_terminal_task` before every post-collection trusted/effect path.
Status is `AWAITING_FRESH_REVIEW_AFTER_ROUND_5`; no PASS or Git integration is
claimed.

The fresh Round 8 review remains immutable
`FAIL — P0 0 / P1 1 / P2 0`. Round 9 replays the exact full source plan at every
trusted boundary and binds its ordered status/reason content into report and
receipt identity. Frozen workflow/planner dependencies prevent checkpoint self-
authentication. Status is `AWAITING_FRESH_REVIEW_AFTER_ROUND_9`; no PASS or Git
integration is claimed.

The fresh Round 6 review remains immutable
`FAIL — P0 0 / P1 3 / P2 0`. Round 7 adds LangGraph active/terminal trusted-
return replay, freezes the concrete snapshot and replay authorities, and binds
CADEC to exact scope execution bounds while retaining top-20 solely as result
projection. Status is `AWAITING_FRESH_REVIEW_AFTER_ROUND_7`; no PASS or Git
integration is claimed.

The fresh Round 5 review remains immutable
`FAIL — P0 0 / P1 2 / P2 0`. Round 6 replays every existing terminal prefix
before the next source loop/effect and freezes all source capability/service
authorities. PubMed acquisition and DailyMed/FAERS immutable replay stores are
constructed internally; live provenance no longer grants replay authority.
Status is `AWAITING_FRESH_REVIEW_AFTER_ROUND_6`; no PASS or Git integration is
claimed.

The fresh Round 7 review remains immutable
`FAIL — P0 0 / P1 2 / P2 0`. Round 8 makes validator tasks equal exact plan-
selected sources while preserving skipped rows without tasks/outcomes, and
conditionally composes exact source groups for all 15 nonempty subsets. Status
is `AWAITING_FRESH_REVIEW_AFTER_ROUND_8`; no PASS or Git integration is
claimed.
