# Architecture

## M1B FAERS domain boundary

FAERS-001 implements source-neutral domain contracts plus their mechanically
additive representation in the existing enabled M1B OpenAPI envelope; it adds
no FAERS route or execution path. Request/report envelopes contain typed FAERS
request, query, result, section, and locator contracts. Frozen host,
timeout, retry, cache, and freshness values are non-authorizing connector design
metadata and perform no I/O. The future connector remains an outer adapter and
cannot leak provider payloads, raw reports, role inference, persistence rows, or
transport objects into the domain. No reverse dependency is introduced.

## 1. Status and objective

This document freezes the V1 architecture. It separates stable drug-safety
research contracts from replaceable data providers, databases, retrieval
models, agent frameworks, and delivery interfaces.

The architecture must support the formal semaglutide-versus-tirzepatide
gastrointestinal reference scenario without hard-coding those drugs or
adverse reactions.

## 2. Architectural principles

1. Source semantics are preserved; unlike source classes are not collapsed
   into an undifferentiated evidence score.
2. Offline/incremental ingestion is separate from online research execution.
3. Qdrant is a derived index, not a system of record.
4. LangGraph coordinates stable tools; it does not own business logic.
5. MCP and UI are delivery adapters over application capabilities.
6. Retrieval and evaluation run independently from an LLM.
7. Every material claim is traceable to a versioned source locator.
8. Partial source failure is visible and cannot masquerade as no evidence.
9. V1 uses one bounded workflow, not a general autonomous or multi-agent loop.

## 3. System context

```text
                          External and local sources
                 PubMed | DailyMed | openFDA | CADEC
                                    |
                     provider-specific connectors
                                    |
                  source records + immutable snapshots
                                    |
        +---------------------------+---------------------------+
        |                                                       |
        v                                                       v
offline/incremental data plane                            online query plane
normalize -> dedupe -> chunk -> index             scope -> plan -> stable tools
        |                                                       |
        v                                                       v
PostgreSQL metadata + Qdrant derived index        evidence/observations collected
                                                                |
                                                                v
                                                claims -> compare -> citation gate
                                                                |
                                                                v
                                             draft -> HITL -> finalize/export

Evaluation is a separate control plane that invokes stable ingestion,
retrieval, tool, orchestration, and API interfaces using versioned datasets.
```

## 4. Import and dependency direction

Runtime data flow is not Python import direction.

| Module | May depend on | Must not depend on |
|---|---|---|
| `domain` | Python standard library and approved schema library | Connectors, storage, retrieval vendors, LangGraph, FastAPI, MCP, UI, model SDKs |
| `connectors` | Domain contracts, consumer-owned connector ports, HTTP utilities | LangGraph, FastAPI routes, UI, MCP, Qdrant |
| `ingestion` | Domain contracts, connector ports, snapshot/storage/index ports | Orchestration, UI, MCP |
| `retrieval` | Domain contracts and retrieval ports | Orchestration state, API models, UI |
| `tools` | Domain contracts and abstract connector/retrieval/storage capabilities | Concrete provider clients, FastAPI, MCP, UI |
| `orchestration` | Stable tools, workflow contracts, model gateway | Concrete connectors, Qdrant, SQLAlchemy models, UI |
| `api` | Application/orchestration public interfaces | Direct provider or Qdrant access |
| `mcp_server` | Stable read-only tools | Direct connector, database, or vector access |
| `frontend` | FastAPI transport contract | Provider APIs, PostgreSQL, Qdrant, model providers |
| `evaluation` | Stable public interfaces and test adapters | Production import of held-out answers |

Interfaces are defined by the consuming application layer. Concrete adapters
implement those interfaces. A single composition root creates concrete HTTP,
PostgreSQL, Qdrant, model, tool, and workflow objects and injects them into
delivery adapters.

## 5. Data plane

### 5.1 Acquisition

Each connector converts a bounded source query into:

- source-specific records;
- an orthogonal terminal source outcome containing execution, coverage, and
  result status;
- query and pagination metadata;
- warnings and typed errors;
- an immutable raw response snapshot;
- a manifest as defined in `DATA_SOURCES.md`.

Connectors own HTTP timeouts, provider rate limits, pagination, response
parsing, retryable-error classification, and provider-specific caching rules.

### 5.2 Raw snapshot and manifest

Raw API responses and approved corpus files are content-addressed by SHA-256.
Git stores only small sanitized fixtures, manifests, and evaluation data.
Complete raw and normalized corpora remain outside Git.

PostgreSQL stores snapshot identity, source metadata, query, version, content
hash, connector/schema version, transformation lineage, and file/object
location. Raw files remain the replayable acquisition record.

### 5.3 Normalization and deduplication

Normalization preserves original values and emits explicit mappings. A mapping
contains method, vocabulary/version when applicable, confidence, and warnings.

Deduplication is source-aware and never deletes the original snapshot:

- PubMed: PMID and correction/retraction relationships;
- DailyMed: SETID, SPL version, product, and section;
- FAERS: report/case identifier, version, and the approved latest-version rule;
- CADEC: corpus version, document ID, annotation version, and dataset split.

### 5.4 Chunking and indexing

- PubMed is indexed from available abstract/title/metadata with explicit
  abstract-only scope.
- DailyMed is indexed by product-specific label section and SPL version.
- CADEC retains short-document and annotation-span context.
- FAERS aggregate results remain structured observations and are not inserted
  into the ordinary semantic document index.

Qdrant stores only rebuildable document-chunk payload references and sparse/
dense vectors. PostgreSQL and snapshot files remain authoritative.

## 6. Online query plane

The online workflow receives a `ResearchScope`, applies safety/scope policy,
builds a bounded plan, calls stable tools, and produces source-aware claims.
It must not trigger a general corpus rebuild or silently ingest an unbounded
source.

Live source results may be cached and persisted as a bounded research snapshot.
If the required frozen index is missing or stale, the workflow returns an
explicit operational state instead of building an index inside an agent node.

## 7. Core domain contracts

V1 uses Pydantic v2 for typed, versioned contracts while excluding transport
and vendor-native types from domain schemas.

### 7.1 Research and terminology

- `ResearchScope`: drugs, adverse reactions, time range, selected sources,
  language, comparison intent, and configured bounds.
- `DrugConcept`: canonical identity and optional product/formulation context.
- `DrugMention` and `DrugMapping`: original text, mapped concept, method,
  confidence, and warnings.
- `AdverseEventConcept`, `EventMention`, and `EventMapping`: original and
  normalized reaction terminology with coding-system provenance.

### 7.2 Source and provenance

- `SourcePlanEntry`: considered source plus `selected`,
  `skipped_not_applicable`, or `skipped_by_policy` planning status and reason.
- `SourceRecord`: a discriminated union of publication, label, FAERS
  observation, and auxiliary-corpus records.
- `Provenance`: source, stable ID, version/status, URI or replayable query,
  retrieved/published/effective timestamps, snapshot hash, connector/schema
  version, and transformation lineage.
- `SourceOutcome`: terminal result for an actually executed source, containing
  orthogonal execution, coverage, and result status plus bounds, counts,
  warnings, and failure metadata.

### 7.3 Retrieval

- `DocumentChunk`: derived text, source record/version, exact locator, content
  hash, chunker/index version, and metadata.
- `RetrievalQuery`: normalized query, filters, mode, candidate limit, and final
  limit.
- `RetrievalHit`: chunk/evidence ID, rank, retrieval method, original component
  scores, fused/reranked score, and citation locator.

### 7.4 Claims and reports

- `EvidenceClaim`: material statement, claim class, applicable scope,
  uncertainty wording, and supporting/contradicting/contextual evidence IDs.
- `Citation`: source record/version plus exact text span or structured-field
  locator and validation state.
- `ComparabilityAssessment`: compared dimensions, missing dimensions, and
  comparable/not-comparable result.
- `ConflictAssessment`: consistent, scope-different, unresolved conflict,
  insufficient, or source-unavailable.
- `ResearchReport`: scope, source coverage, claims, citations, comparisons,
  limitations, configuration, timestamps, and review/export state.

### 7.5 Source planning and outcome model

Planning and execution are separate contracts. Every considered source has one
planning status:

| Field | Allowed values | Meaning |
|---|---|---|
| `planning_status` | `selected`, `skipped_not_applicable`, `skipped_by_policy` | Whether the source will execute, does not apply to the scope, or is prohibited by policy |

Skipped sources do not have a `SourceOutcome`. A selected source must actually
start execution before a `SourceOutcome` can exist. A selected task that never
reaches execution prevents report finalization rather than receiving a
fabricated source result.

Every actually executed source emits exactly one terminal `SourceOutcome`:

| Dimension | Allowed values | Meaning |
|---|---|---|
| `execution_status` | `succeeded`, `failed` | Whether the executed connector/tool operation completed according to contract |
| `coverage_status` | `complete`, `partial`, `unavailable` | Whether the declared bounded scope was exhaustively covered, incompletely covered, or produced no usable response |
| `result_status` | `matches`, `no_match`, `indeterminate` | Whether valid matches exist, a complete successful search found none, or absence cannot be determined |

The following seven combinations are the complete set of valid terminal
outcomes:

| # | Execution | Coverage | Result | Normative meaning |
|---|---|---|---|---|
| 1 | `succeeded` | `complete` | `matches` | The bounded query completed and returned at least one valid result |
| 2 | `succeeded` | `complete` | `no_match` | The complete declared query scope was searched successfully and returned zero valid results |
| 3 | `succeeded` | `partial` | `matches` | Valid results were returned, but pagination, truncation, time, query limits, or another declared boundary limited coverage |
| 4 | `succeeded` | `partial` | `indeterminate` | A partial search returned zero valid results, so absence cannot be stated |
| 5 | `failed` | `partial` | `matches` | Some valid results were retained before the operation failed |
| 6 | `failed` | `partial` | `indeterminate` | The operation failed after partial execution and returned no valid results |
| 7 | `failed` | `unavailable` | `indeterminate` | No usable source response was obtained |

All other combinations are invalid. Explicit invalid classes include:

| Execution | Coverage | Result | Reason |
|---|---|---|---|
| any | `partial` | `no_match` | Partial coverage cannot establish absence |
| `failed` | any | `no_match` | Failed execution cannot establish absence |
| any | `unavailable` | `no_match` | No usable response cannot establish absence |
| `succeeded` | `unavailable` | any | Successful execution cannot have unavailable coverage |
| `failed` | `complete` | any | Failed execution cannot claim complete coverage |
| any | `unavailable` | `matches` | Matches require usable coverage |

Only `succeeded + complete` may produce `no_match`. Truncation, a query limit
reached before exhaustion, incomplete pagination, or parse loss can never be
`complete`. Failed or partial execution is never represented as absence of
evidence. Partial matches remain visible with `coverage_status=partial`.

Run-level aggregation considers only `planning_status=selected` sources:

- every selected source must have a validated terminal `SourceOutcome` before
  a report can finalize; skipped sources remain visible in the plan and are
  excluded from outcome aggregation;
- run coverage is `complete` only when every selected source is complete,
  `unavailable` only when every selected source is unavailable, and `partial`
  for every other mixture containing partial or unavailable coverage;
- run result is `matches` when any selected source has matches;
  it is `no_match` only when every selected source is
  `succeeded + complete + no_match`; every other zero-match run is
  `indeterminate`;
- workflow completion is recorded separately and never rewrites individual
  source execution statuses.

Run aggregation cannot upgrade partial or unavailable source coverage to
complete. Source-task attempts may transition from internal pending/running
states, but only a validated terminal `SourceOutcome` is exposed across
layers. A terminal outcome is immutable for that attempt; a refresh creates a
new attempt and provenance record.

### 7.6 Two-stage citation validation

Every material claim passes two independent stages:

**Stage 1 — deterministic structural and policy validation**

- source identity belongs to the current authorized run;
- source version and content hash match the cited snapshot;
- locator/span or structured field exists;
- claim class is permitted for the source classification;
- FAERS and CADEC restrictions are satisfied;
- mandatory source limitations and coverage qualifiers are present.

Stage 1 returns `passed` or `failed` with machine-readable reasons.

**Stage 2 — versioned semantic support evaluation**

- `supported`: the cited content supports the claim as scoped and worded;
- `uncertain`: support is ambiguous, incomplete, or requires domain judgment;
- `unsupported`: the content does not support the claim.

The semantic evaluator records method, version, inputs, and result. It may
combine deterministic rules, human adjudication, and an approved model-assisted
assessment, but an LLM judge cannot be the sole ground truth. `uncertain`
requires human adjudication or claim removal. `unsupported` claims cannot enter
a formal report. A claim passes the citation gate only when Stage 1 passes and
Stage 2 is `supported` or is explicitly resolved to supported by recorded human
adjudication.

Only persisted contracts and externally exchanged schemas require explicit
schema versions. Short-lived internal helper values do not each require a
separate version.

## 8. Connector and tool contracts

### 8.1 Connector capabilities

| Connector | Required operation | V1 result |
|---|---|---|
| PubMed | Search; fetch a PMID record | Versioned `PublicationRecord` page/record |
| DailyMed | Resolve/select label; retrieve SETID/SPL | Versioned `LabelRecord` with sections |
| FAERS/openFDA | Execute bounded aggregation | `FaersQueryResult` with query semantics |
| Local ADR | Load/search approved corpus snapshot | `AdrCorpusRecord` marked auxiliary |

Each collection result includes coverage status, replayable query, source and
retrieval versions, pagination/limit information, and warnings. The terminal
payload uses the three-dimension `SourceOutcome`. Permanent
invalid-input failures are distinct from timeouts, rate limits, upstream
unavailability, malformed responses, and partial results.

### 8.2 Stable tools

V1 application tools are:

- `search_pubmed`
- `fetch_pubmed_article`
- `query_faers`
- `get_drug_label`
- `normalize_drug_name`
- `search_local_adr_corpus`

Tools validate input limits, invoke injected capabilities, and return bounded
domain contracts. MCP maps to these tools without reimplementing them.
In V1, `fetch_pubmed_article` means the available PubMed record and abstract;
it does not imply licensed or reviewed full-text retrieval.

## 9. Retrieval architecture

The `RetrievalPort` exposes BM25 sparse, dense, hybrid, and optional reranked
modes through one query/result contract.

V1 Qdrant collections use named sparse and dense representations for the same
versioned chunks:

1. BM25 sparse candidate generation;
2. dense candidate generation;
3. RRF rank fusion over the two candidate lists;
4. optional second-stage reranking over a bounded fused candidate set.

RRF is the frozen V1 fusion baseline because it combines ranks without treating
incomparable sparse and dense raw-score scales as directly additive. Original
component ranks and scores remain available for evaluation.

Metadata filters, candidate limits, final `k`, corpus snapshot, and relevance
judgments must be identical when comparing retrieval modes. The reranker is not
a runtime requirement and becomes the default only after measured benefit and
latency tradeoff are approved.

### 9.1 Retrieval configuration decision gate

ADR-004 freezes Qdrant as the V1 derived hybrid index and RRF as the fusion
method, but it does not freeze executable retrieval configuration. Decision
gate `ME-000C`, owned by Boqi Niu as Project Owner and due before M2, must
approve:

- Qdrant client and server versions;
- tokenizer and text-normalization policy;
- sparse encoding implementation;
- BM25 `k1` and `b`;
- dense embedding model and version;
- reranker candidate/model and version;
- candidate, fusion, rerank, and final limits.

No M0 document or executable configuration may imply that these values have
already been selected.

## 10. Controlled LangGraph workflow

### 10.1 Workflow nodes

V1 uses one bounded graph:

1. `scope_and_safety`
2. `plan_sources`
3. `collect_evidence`
4. `synthesize_claims`
5. `validate_report`
6. `save_pending_draft`
7. `request_export_approval`
8. `finalize_and_export`

Collection may fan out across approved sources and fan in before synthesis.
Nodes remain thin and call tools. Deterministic validation must not exist only
inside prompts.

### 10.2 Agent state

The versioned state contains:

- run and report IDs;
- original and interpreted `ResearchScope`;
- safety decision and bounded plan;
- source tasks, status, attempts, snapshot IDs, and warnings;
- evidence, observation, claim, and citation references;
- comparability/conflict results;
- draft validation result;
- report status and review record;
- export destination, content hash, and idempotency key when approved.

Large raw documents and provider payloads are referenced, not copied into every
checkpoint.

### 10.3 Retry and degradation

Connectors retry transient network failures. The graph handles workflow-level
degradation, re-planning, and resume; it must not repeat connector retry loops.
Completed source tasks are idempotent and are not repeated after resume unless
their policy explicitly allows refresh.

### 10.4 HITL and export

HITL is used only for formal export:

1. `validate_report` must pass citation and safety gates.
2. `save_pending_draft` idempotently persists the draft as `pending_review`.
3. `request_export_approval` calls `interrupt` with the exact report identity, content
   hash, destination, source coverage, and material warnings.
4. Broad, expensive, or sensitive research queries do not create additional
   approval interrupts; they are deterministically bounded, rejected, or
   safely degraded.
5. No non-idempotent effect occurs before approval.
6. Rejection sets `rejected` and performs no export.
7. Approval routes to the independent `finalize_and_export` node.
8. Export uses `report_id` plus an idempotency key and atomically records the
   finalized content hash and destination.
9. Repeated resume or delivery requests return the existing export result
   rather than creating a duplicate.

PostgreSQL is the approved durable checkpoint and report-state backend for V1.

## 11. Delivery architecture

- FastAPI exposes typed research, status, review, and export operations.
- Streamlit calls FastAPI and displays source class, version, coverage,
  citations, conflicts, limitations, and review status.
- MCP exposes only approved read-only research tools. Formal export is not an
  MCP V1 tool.
- Evaluation invokes stable internal interfaces and API contracts without
  depending on Streamlit.

## 12. Persistence

| Store | V1 responsibility |
|---|---|
| File snapshots | Immutable raw responses/corpus inputs and optional normalized artifacts |
| PostgreSQL | Source/snapshot metadata, hashes, lineage, normalized identities, run/report metadata, cache entries, review/export records, LangGraph checkpoints |
| Qdrant | Rebuildable sparse/dense vectors and chunk payload references |

Redis is explicitly postponed. A cache interface may be retained, but the V1
implementation uses PostgreSQL-backed bounded caching where persistence is
needed.

## 13. Observability

Structured logs and foundational OpenTelemetry instrumentation record:

- correlation, run, report, and source-task IDs;
- connector/tool/node name, duration, outcome, retry count, and cache status;
- snapshot, schema, connector, index, model, and prompt versions;
- retrieval mode and candidate/final counts;
- citation and safety gate outcomes;
- HITL decision and idempotent export outcome;
- token/cost metadata when supplied by the provider.

Logs and traces apply the redaction policy in `SECURITY.md`.

## 14. Approved V1 technology stack

- Python 3.12
- Pydantic v2
- HTTPX and Tenacity
- FastAPI
- SQLAlchemy 2 and Alembic
- PostgreSQL
- Qdrant
- LangGraph
- Streamlit
- pytest, pytest-socket, Ruff, and mypy
- structured logging and foundational OpenTelemetry
- configurable model-provider gateway with one approved V1 adapter

Redis, React, GraphRAG, multi-agent designs, ClinicalTrials.gov, signal
detection metrics, PHI workflows, and public multi-tenant infrastructure are
outside V1.

## 15. Deployment boundary

V1 is a local, single-user Docker Compose deployment. It is not approved for
public exposure, PHI, clinical use, or regulatory submission. PostgreSQL and
Qdrant bind to local interfaces by default. Public deployment would require a
new security, authentication, privacy, retention, and operational decision.

## 16. Architectural invariants and acceptance scenarios

These invariants are release-blocking and must be demonstrated explicitly:

### INV-001 — Online research cannot mutate the offline index

Given an online research request, when the workflow queries sources and
retrieval tools, then it cannot publish, rebuild, delete, or mutate the offline
Qdrant collection or authoritative snapshots. Missing/stale indexes produce a
bounded operational outcome, not an implicit rebuild.

### INV-002 — Qdrant deletion cannot delete provenance

Given authoritative snapshots and PostgreSQL metadata, when the Qdrant
collection is deleted, then source records, manifests, hashes, transformation
lineage, reports, and review records remain intact and queryable from their
authoritative stores.

### INV-003 — Qdrant is rebuildable

Given verified file snapshots and matching PostgreSQL metadata, when an index
rebuild is executed through the offline ingestion plane, then Qdrant can be
recreated with deterministic source/chunk identities and the declared
index/configuration version.

### INV-004 — Partial source failure remains visible

Given at least one partial or unavailable selected source, when a draft or
final report is produced, then run/source outcomes, missing coverage, warnings,
and retrieval-as-of time remain visible. The report cannot imply complete
coverage or convert failure into no evidence.

### INV-005 — Failed citation claims cannot survive

Given a material claim that fails deterministic Stage 1 or returns uncertain/
unsupported at semantic Stage 2 without recorded human resolution, when report
validation completes, then that claim is removed or the report remains
non-exportable. No substantive claim may survive a failed citation gate.

## 16. M1B-DM-001 additive DailyMed contract architecture

ADR-011 adds DailyMed contracts inside `domain` only. Runtime dependency
direction remains unchanged; no connector, parser, persistence, tool, API, or
composition behavior is introduced by this node.

```text
M1BResearchRequestV1
  -> DailyMedSelectionRequestV1
  -> executed discovery SourceOutcome
  -> exhaustive selection matrix
  -> LabelSelectionDecision or no decision row
  -> optional distinct fetch SourceOutcome (selected only)
  -> stable DailyMedLabelVersion + LabelSection
  -> DailyMedLabelSectionV1 + optional DailyMedLocatorV1
  -> M1BResearchReportV1 (draft, non-exportable)
```

The selection matrix is exact: complete matching discovery selects only after
deterministic exact/equivalent-group resolution; unresolved complete matches
require review with at least two candidates; every positive-count partial
matches discovery requires review regardless of resolution or pin; complete
zero-result no-match is the sole no-candidate state; the three zero-result
indeterminate triples create no decision row. No partial discovery may select.

Stable identity and observation identity stay separate. Candidate and decision
records bind the complete discovery tuple and retained member evidence.
`DailyMedLabelVersion` and `LabelSection` contain no acquisition/fetch fields.
Its version ID preimage is exactly schema/source/SETID/SPL-version/content-hash;
marketing state (`active|archived|unknown`), dates, and artifact binding remain
full-row verified but do not change that ID. `RetainedSplResponse` binds one
selected decision to the exact complete fetch member, outcome, stable version,
and ordered stable sections. Each label locator repeats that exact observation
and section span. A degraded discovery or failed fetch has no label locator.

`M1BResearchRequestV1`, `M1BResearchReportV1`, and the distinct additive
`M1BSourcePlanEntryV1(schema_version="m1b.source-plan.v1")` planning model are
parallel additive contracts. M1A `ResearchReport`, its
`SourcePlanEntry(schema_version="1.0")` JSON Schema/OpenAPI component, and
PubMed PMID/version semantics remain unchanged.

The DailyMed connector trust contract is non-authorizing metadata. It records
only HTTPS `dailymed.nlm.nih.gov:443`, GET, one same-origin redirect, and the six
ADR-011 typed path/query designs. Ordinary/runtime permitted hosts are empty and
medical-source execution is false. Future XML/ZIP implementation belongs to
M1B-DM-002 and must implement the frozen no-I/O, exact-selector, resource-bound,
pre-normalization C0/DEL rejection, no-extraction, and exactly-one-SPL rules.
The metadata also closes the exact timeout/retry/backoff/deadline/pagination/
payload/cache profile and full denied resource/query/redirect classes; it
contains no executable transport.

## 17. M1B-DM-003 report and API architecture

```text
trusted DM-002 evidence
  -> tools/dailymed_report.py
  -> M1BResearchReportV1.validate_against(...)
  -> optional injected DailyMed application port
  -> POST /v1/research/dailymed
```

The tools layer, not the caller or API adapter, constructs the sole selected
DailyMed plan entry. The API performs closed raw-request validation, calls one
explicitly injected source-neutral application function, reconstructs the
returned report, and checks request, scope, planning, and request-section echo
parity. Composition supplies no default DailyMed transport or live fallback.
When the callable is absent the M1A application surface remains unchanged.

## 18. M1B-FAERS-003 report and API architecture

```text
trusted FAERS-002 aggregate executions
  -> tools/faers_report.py
  -> FaersAggregateSectionV1 + exact FaersLocatorV1 bucket set
  -> M1BResearchReportV1.validate_against(...)
  -> optional injected FAERS report application port
  -> POST /v1/research/faers
```

The report tool reconstructs every execution and proves request, query,
acquisition outcome, snapshot, bucket, locator, and limitation equality before
returning a draft. It cannot consume individual FAERS reports or narratives.
The API validates raw JSON before model construction, invokes only the injected
application, reconstructs the returned report with required-field presence,
and checks exact request/scope/plan/section parity. Composition supplies no
default connector, persistence adapter, credential, or network fallback.

OpenAPI registration is conditional. The default M1A schema and the existing
PubMed and DailyMed route/component projections remain protected; enabling the
FAERS application adds only the frozen FAERS route and report-reachable
components.

## 19. M1B CADEC loader-only architecture and M2 boundary

CADEC-001 freezes the standalone domain contracts. CADEC-002 is the exact final
executable M1B surface:

```text
approved external archive + authoritative manifest
  -> one bounded read of each explicit path into retained immutable bytes
  -> exact archive/manifest identity + safe ZIP inventory + encoding policy
  -> strict provider-gold brat loader/parser
  -> approved metadata-only documents + provider-gold annotations
  -> exact locators + content-free verification summary
  -> STOP: final executable M1B CADEC boundary
```

Hashing and use operate on the same retained immutable bytes. No filesystem
extraction occurs. Finite input, entry-count, aggregate compressed,
aggregate-uncompressed, expansion-ratio, member, row, and span bounds fail
closed. The approved output remains metadata-only and is **not directly
retrieval-consumable**.

The exact `M1BResearchRequestV1.cadec_query_requests` value remains
`tuple[()]` and `M1BSourceSection` is unchanged. Repository governance records
CADEC as an explicitly known M1B source with
`planning_status=skipped_by_policy` and
`reason_code=source_execution_not_authorized`. This is not a global runtime
plan object or an entry injected into every report. Each
`M1BResearchReportV1.source_plan` remains exactly its request's
`scope.selected_sources`, so DailyMed-only and FAERS-only runtime plans remain
source-only and CADEC is not added to `requested_sources`. Governance
visibility is distinct from execution: there is no executable request,
research-request connector invocation, `SourceOutcome`, report section, or
API/OpenAPI execution. The M1B boundary also excludes a structured retrieval/
search tool, persistence, migration, database ingestion, indexing, chunking,
training, and retrieval evaluation. In particular, M1B does not define or
expose `search_local_adr_corpus`.

Every child uses Option A: `source + corpus_id + corpus_version + split +
artifact identity`. The namespaced archive and manifest hashes supply the
corpus ID/version without inventing a provider version; the exact manifest,
terminal audit, and split-membership identities are repeated and validated.
Documents require safe canonical member labels, annotations require the exact
parent document artifact, and locators require the exact parent annotation
artifact. Spans are zero-based, non-empty, half-open
Unicode code-point intervals; multiple segments are ordinal-contiguous,
ordered, non-overlapping, and document-bounded. Durable children have
deterministic identities. NFC, strict frozen extra-forbid validation, exact
split/hash metadata, and accepted-instance revalidation fail closed. Asset
mismatch remains distinct from the five frozen malformed-row rejections.

The integrated loader preserves the 1,250/1,248 canonical/admitted boundary,
the exact two exclusions, five malformed rows, 2/44/45 visible limitations,
sole CP1252 exception, 992/119/137 split, and provider-gold-only policy. It
admits exactly two zero-byte documents (`LIPITOR.40` and `VOLTAREN-XR.9`) only
when original, MedDRA, and SCT each contain zero rows. It produces 24,478 exact
annotation/locator pairs partitioned 9,089/6,300/9,089 across those layers.
REDIST, VOCAB, and Option-A provenance remain unchanged.

The future M2 continuation is deliberately separated from the executable M1B
flow:

```text
future M2 only, after ME-000C approval
approved external archive + authoritative manifest
  -> reread and verify the same immutable archive/manifest identity
  -> text-bearing CADEC materializer
  -> preserve document/annotation/locator/split/Option-A lineage
  -> exact text-bearing chunks with bounded offsets and content hashes
  -> search_local_adr_corpus through the approved retrieval boundary
```

Raw text remains outside Git. The materializer and
`search_local_adr_corpus` are M2-owned, not implemented or authorized by this
boundary record, and remain subject to `ME-000C`. The marker
`READY_FOR_M2-CADEC-RETRIEVAL-CONSUMPTION` must not be emitted or claimed.
CADEC-003 feature commit `83617405e58bcec657bdaa84aceb8d2460d46fb1` was
integrated by merge `c226a632753e6fc65e8c84c74ec568d994612b7d` through PR
#21 after independent review and terminal audit each passed at
`P0 0 / P1 0 / P2 0`. This establishes `M1B-CADEC-003_COMPLETE`,
`M1B-CADEC_VERTICAL_SLICE_COMPLETE`, and
`READY_FOR_M2-CADEC-RETRIEVAL-PLANNING`; it does not authorize M2 work.
