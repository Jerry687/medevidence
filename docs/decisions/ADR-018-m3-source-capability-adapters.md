# ADR-018: M3 source capability adapters

- Status: final Round 10 independently passed; awaiting terminal evidence audit
- Date: 2026-08-28
- Work item: `M3-006-SOURCE-CAPABILITY-ADAPTERS`
- Baseline: `46eb93bb61524bae102c068d87372f1e63de7c89`
- Full M3 authorization SHA-256:
  `e6b812f6411b8e8a62a559ae0182b45cae25bc70d0173c135b94e97b8cd73fa8`
- Clarifying decision: `OWNER DECISION: A - APPROVED WITH EXACT
  CLARIFICATIONS`

## Context

ADR-017 supplied the fixed eight-node LangGraph and PostgreSQL checkpoint
runtime but deliberately added no source adapter. M3-006 must connect the
`collect_evidence` application node to the already governed PubMed, DailyMed,
FAERS, and local CADEC capabilities without changing their public, evidence, or
source semantics.

The M1B CADEC records remain immutable history: loader/parser verification was
the final executable M1B CADEC surface. This decision supersedes only that
historical authorization deferral for the exact M3 local runtime described
here. It does not reopen M1B, change the M2 router, qrels, corpus, or metric
contract, or authorize a medical-source request.

## Decision

### Planning and task topology

For every request, `scope.selected_sources` has exactly one canonically ordered
plan row. Source tasks equal exactly the rows whose `planning_status` is
`selected`. A `skipped_not_applicable` or `skipped_by_policy` row remains
visible and has neither a task nor a `SourceOutcome`; no task exists without a
selected plan row.

Every selected task freezes source-specific required operations before the
corresponding operation can perform I/O. Plans bind run, task, attempt, source,
ordinal, operation kind, and query identity. Required-plan ordinals are
contiguous and identities are unique. A resumed task must reconstruct the same
plan. Where a result determines later required work, only canonical prefix
expansion is allowed:

- PubMed freezes its search before search I/O, then freezes exactly one fetch
  for every returned ordered PMID before any fetch I/O;
- DailyMed freezes all discovery operations before discovery I/O, then freezes
  a fetch only for each frozen selection path that requires one, before fetch
  I/O;
- FAERS freezes the full aggregate-operation set before aggregate I/O; and
- CADEC freezes verification followed by search before either local asset
  operation.

A policy-determined non-required operation is not fabricated as missing or
failed. A task cannot become terminal until every operation in its final
required set has a terminal, acquisition-bound result.

### Multi-operation aggregation

The terminal task disposition is reconstructed from all final required
operations:

- execution is `failed` if any operation failed, and `succeeded` otherwise;
- coverage is `complete` iff all operations are complete, `unavailable` iff all
  are unavailable, and `partial` otherwise;
- result is `matches` iff any operation has matches, `no_match` iff every
  operation is exactly `succeeded + complete + no_match`, and `indeterminate`
  otherwise; and
- warnings are the sorted unique union.

This aggregation never turns an incomplete zero-result execution into absence
of evidence.

### Source-specific operations

| Source | Frozen operations and projection |
|---|---|
| PubMed | One search followed by zero to 100 fetches, one per exact ordered PMID. Search and every fetch retain their persisted acquisition; only fetched, persisted publication evidence is projected. Existing query, page, payload, status, correction/retraction, and source-warning semantics are unchanged. |
| DailyMed | One to four discovery operations followed by at most one fetch per discovery, in discovery order. A fetch exists only for an exact selected label path. Existing SETID, SPL version, selection, section, complete/no-match, ambiguity, and degraded-source semantics are unchanged. |
| FAERS | One to eight unique narrative-free aggregate operations. Existing unit, PT set, date/query, latest-case-version, no-role-predicate, page/record/payload/time bounds, bucket, snapshot, and persistence contracts are revalidated. Every executed FAERS task carries warning identity `faers_mandatory_limitations`. |
| CADEC | Exactly `cadec_verify`, then `cadec_search`. The exact approved archive and manifest are reread and all 1,248 admitted documents are verified. The two approved zero-length documents remain corpus members but emit no chunk; all 1,246 other documents become transient whole-document chunks. |

### Exact CADEC local search

The approved archive SHA-256 is
`4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a`;
the approved 1,699,979-byte manifest SHA-256 is
`1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa`.
The 1,250 canonical documents admit exactly 1,248 after excluding
`DICLOFENAC-SODIUM.7` and `LIPITOR.221`. The two admitted zero-length documents
are `LIPITOR.40` and `VOLTAREN-XR.9`.

The canonical query joins, with one ASCII space and in existing scope order,
all `scope.drugs[*].preferred_term` values followed by all
`scope.adverse_reactions[*].preferred_term` values. There is no synonym,
expansion, inferred terminology, qrels, winner mapping, or query-specific
tuning. The runtime rejects rather than truncates a query beyond the existing
scope query bound.

The existing deterministic BM25 scores every eligible document with exactly
`k1=0.9` and `b=0.4`. Only positive-score results are retained, at most 20,
ordered by score descending and then `document_id` UTF-8 bytes ascending.
Because every eligible document is scored, the top-20 projection is complete,
not partial.

Successful complete search with positive results yields
`succeeded / complete / matches`; successful complete search with no positive
result yields `succeeded / complete / no_match`. Archive, manifest,
membership, hash, materialization, or search-integrity failure yields
`failed / unavailable / indeterminate` and exposes no partial CADEC evidence
references. All CADEC outcomes carry warning identity
`cadec_mandatory_limitations` and the existing mandatory limitation text.
Returned records are whole-document auxiliary evidence only. They create no
clinical, causal, incidence, regulatory, product-risk, comparative-safety, or
ranking authority.

No CADEC text or chunk is persisted to Git, Qdrant, PostgreSQL, or another
database. The runtime does not change M2 routing, qrels, corpus, or metrics.

### Layering and trust boundary

Tools own source-neutral contracts and pure planning. Orchestration statically
dispatches only the four explicit injected capabilities and reconstructs all
plans, acquisitions, observations, outcomes, and aggregate dispositions.
Infrastructure alone owns the concrete local CADEC archive path and BM25
adapter. No provider-, filesystem-, retrieval-, database-, or LangGraph-native
object crosses the application contract.

The source capability dispatcher is sealed and uses explicit static branches;
there is no mutable dispatch table, dynamic private-helper authority, or
provider fallback. Existing PubMed, DailyMed, and FAERS execution/persistence
ports remain injected. M3-006 adds no dependency, public API/OpenAPI change,
schema/migration, model/provider, source/evidence semantic change, or medical
network authority.

## Consequences

- Source topology and operation completeness are durable and replay-checkable.
- A successful task outcome is computed from exact terminal operations rather
  than trusted source summaries.
- CADEC local retrieval is deterministic and transient while preserving the
  exact licensed-asset boundary and auxiliary-only meaning.
- M1B and M2 historical records remain valid for their milestones; this ADR is
  the later, narrowly scoped M3 execution authority.
- Holdout-20 remains sealed. Independent review, exact-byte rebind, terminal
  audit, and the authorized Git lifecycle remain required before PASS.

## Round 3 review and closure record

The initial independent review is immutable:
`FAIL — P0 0 / P1 4 / P2 0`. It demonstrated four defects: CADEC could accept a
fake exact-asset/no-match projection and degraded CADEC provenance could expose
refs or evade reconstruction; required operations omitted their exact PubMed
PMID and DailyMed selected-label subjects; the terminal aggregate could disagree
with its child provenance; and no concrete production DailyMed/FAERS projection
authority was reachable.

Round 3 closes only those findings. `RequiredSourceOperation` v2 adds an exact
`input_identity`: PubMed search binds scope/query/catalog and each fetch binds
PMID/query/ordinal; DailyMed discovery/fetch bind their complete request and
selected-label identity; FAERS binds the exact request plus canonical query;
CADEC verification/search bind the exact frozen plan subjects.

`TerminalSourceOutcomeRef` v2 separately binds the aggregate outcome identity,
the ordered identities of every child operation acquisition, and one exact
representative child acquisition. Durable task/collection v2 validation
recomputes the aggregate from all children and requires the exact four
dimensions, evidence projection, limitations, and provenance. A degraded CADEC
task has exact governed limitations and zero observations/evidence refs.

`CadecVerifiedCorpus` now equals the complete frozen verification tuple field
for field, and adapter results are strictly reconstructed against the exact
plan and scope. Sealed `CanonicalDailyMedProjectionAuthority` and
`CanonicalFaersProjectionAuthority` reconstruct governed requests and persisted
provenance and own their terminal projection; `SourceCapabilities` admits only
those exact concrete authority types. Workflow and M3-003 evaluation fixtures
use the v2 contracts. Fresh review remains required before PASS.

## Round 4 review and closure record

The fresh Round 3 independent review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It demonstrated an asset-free fake CADEC route,
dynamic PubMed/DailyMed fetch suffixes that were not checkpointed before fetch,
and self-consistent terminal query/count/intent/operation forgery.

Round 4 closes only those findings. Durable operation v3 uses typed role/value
input refs, scope identity, canonical input identity, and acquisition intent;
terminal outcomes are reconstructed field-for-field from exact child
operations rather than accepted as a self-consistent summary. A RUNNING source
task may retain only the exact completed operation-result prefix, represented
by `SourceTaskProgressResult`, so each dynamic suffix is durably checkpointed
before the later fetch stage.

PubMed persists an immutable search-progress membership journal through the
existing `SnapshotStore`, then a fresh service reloads and revalidates run,
scope, query, intent, snapshot/manifest, ordered PMIDs, source outcome, and
count before fetch. DailyMed reloads exact durable discovery provenance before
reconstructing any selected fetch.

`SourceCapabilities` is now a sealed three-source authority with no CADEC path
or port. The final sealed infrastructure wrapper alone accepts explicit CADEC
asset paths, internally constructs `CadecLocalSearchAdapter`, intercepts CADEC,
and delegates PubMed/DailyMed/FAERS. Production composition constructs this
exact wrapper; there is no structural CADEC result or caller-supplied adapter
route. Typed CADEC inputs bind exact asset, membership, and query-plan
identities. Fresh review remains required before PASS.

## Round 5 review and closure record

The fresh Round 4 independent review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It demonstrated that CADEC `_search` remained
writable, that a self-consistent forged durable child lacked source-specific
terminal replay, and that coordinated substitution of the PubMed progress
journal and checkpoint could pass together.

Round 5 freezes the CADEC wrapper and its internally constructed adapter, then
validates every CADEC terminal task by concrete asset rerun and exact terminal
equality. PubMed persists an attempt-scoped terminal progress receipt binding
the search receipt, ordered PMIDs, every operation/acquisition/outcome/evidence
projection, limitations, and terminal projection. Production composition
accepts exact concrete `SnapshotStore` and persistence authorities and builds
the PubMed service internally; callers cannot supply a prebuilt service or fake
store route.

DailyMed and FAERS terminal validation reloads exact durable discovery, fetch,
and aggregate provenance. `EvidenceCollectionPort.validate_terminal_task`
provides one replay authority for every source. The workflow invokes it before
synthesis, report validation, pending save, approval, export, all trusted or
idempotent terminal returns, and terminal inspection. M3-003 evaluation uses a
compatible replay authority. Fresh review remains required before PASS.

## Round 6 review and closure record

The fresh Round 5 independent review is immutable:
`FAIL — P0 0 / P1 2 / P2 0`. It demonstrated that a terminal source prefix was
not replayed before the workflow began the next source and that non-CADEC replay
authorities remained caller-supplied or replaceable.

Round 6 invokes terminal replay at the start of `collect_evidence`, before its
source loop or any next-source plan/effect. Existing replay before every later
trusted, effecting, inspection, idempotent-return, and terminal path remains.

`SourceCapabilities`, `PubMedResearchService`, both DailyMed/FAERS authorities,
the CADEC wrapper, and the concrete CADEC adapter freeze their critical fields
and use class-qualified authority calls. Production composition constructs the
PubMed service and acquisition adapter internally. DailyMed/FAERS live
provenance is separated from internally constructed immutable snapshot-backed
replay stores; callers can supply live execution provenance but cannot supply
or replace terminal replay authority. Fresh review remains required before
PASS.

## Round 7 review and closure record

The fresh Round 6 independent review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It demonstrated that active LangGraph inspection
did not replay terminal source prefixes, coordinated forgery remained possible
through replaceable underlying stores/adapters, and CADEC incorrectly used its
top-20 projection as `max_records=20` instead of the exact scope bound of 100.

Round 7 exposes pure workflow `validate_terminal_sources` and invokes it for
every LangGraph trusted result, including active inspection and terminal or
idempotent return. `SnapshotStore` is final and slotted, exposes a read-only
root, and guards its internal authority state. `_AcquisitionAdapter`, the
DailyMed/FAERS replay adapters, and CADEC wrapper/adapter are frozen and invoked
class-qualified, closing coordinated normal replacement.

CADEC success and failure now carry exact `ExecutionBounds.from_scope(scope)`.
The positive-result limit remains separately fixed at 20 and cannot replace or
weaken the scope's `max_records`. Fresh review remains required before PASS.

## Round 8 review and closure record

The fresh Round 7 independent review is immutable:
`FAIL — P0 0 / P1 2 / P2 0`. It demonstrated that canonical report validation
compared tasks to the full selected scope and therefore blocked visible skipped
rows, and that production composition unconditionally constructed DailyMed and
FAERS authorities, rejecting a PubMed-only request.

Round 8 adds `CanonicalReportRequest.selected_task_sources`, which must be a
unique canonical subset of full `scope.selected_sources`. It is derived from
exact plan rows with `planning_status=selected`; validator task equality is
against that subset. Skipped-not-applicable and skipped-by-policy rows remain
visible without task or outcome through validation, review, and export.

Composition conditionally accepts only complete dependency groups for the
sources actually selected and covers all 15 nonempty subsets of the four-source
set. CADEC-only constructs no snapshot/replay store. A single shared replay
store exists iff PubMed, DailyMed, or FAERS is selected. Extraneous, partial,
or mismatched groups fail closed. Fresh review remains required before PASS.

## Round 9 review and closure record

The fresh Round 8 independent review is immutable:
`FAIL — P0 0 / P1 1 / P2 0`. It demonstrated that an untrusted checkpoint could
self-authenticate its source plan: a selected row and its task could be removed
as a skip, or skip reason metadata could drift after receipt and still export.

Round 9 re-executes the planner and compares the exact full canonical plan
before collection, source effects, every post-collection effect, and all trusted
or terminal returns. Equality binds row order, source, planning status, reason
code, and reason text. `source_plan_id` is the strict identity of that full row
tuple and is included in `CanonicalReportRequest`, canonical report identity,
validation receipt, and receipt verification.

`ControlledOrchestrationWorkflow` is final, slotted, and freezes its planner and
other dependencies. Plan replay occurs before terminal replay. Coordinated
selected-to-skip task removal or post-receipt reason drift therefore produces
zero source, semantic, persistence, approval, or export effects. Fresh review
remains required before PASS.

## Final Round 10 review and closure record

The fresh Round 9 independent review is immutable:
`FAIL — P0 0 / P1 1 / P2 0`. It demonstrated that a mutable injected
`SourcePlanningPort` could shadow its planning method and authorize a forged
selected-to-skip plan through export.

Round 10 replaces that Protocol authority with exact
`CanonicalSourcePlanningAuthority`: final, slotted, no instance dictionary,
guarded against field replacement, and bound at construction to one strict
`ResearchScope` plus one full canonical plan. Workflow construction rejects any
other type. Initial planning and replay invoke the class-qualified authority,
so instance method shadowing and mutable structural planners are not authority.

Workflow harnesses, LangGraph runtime fixtures, and M3-003 evaluation now build
the same canonical planner. The coordinated selected-to-skip attack produces
zero source, semantic, persistence, approval, and export effects. This exhausts
the authorized remediation budget at 10/10. Final fresh review remains required
before PASS.

## Final independent review

The fresh final Round 10 independent verdict is immutable:
`PASS — P0 0 / P1 0 / P2 0`. The reviewer reported no findings and directly
verified the canonical planner authority and all historical closure paths.

Fresh reviewer evidence is planner attacks `5/5`, workflow/runtime/composition
`264`, projection/replay `89`, authority/subsets `17`, and Ruff, formatting,
strict MyPy, scope `43`, non-self manifest `42`, validator size `1292/1300`,
and compactness `1800/1800` all PASS. The most recent full offline suite remains
`2766 passed, 2 warnings`, `82%`.

This review PASS is not the terminal work-item PASS. Exact-byte rebind and
terminal evidence audit remain required; status is `AWAITING_TERMINAL_AUDIT`
and no Git lifecycle claim is made.
