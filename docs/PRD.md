# Product Requirements Document

## M1B FAERS aggregate contract candidate

M1B adds a bounded, research-only FAERS aggregate domain contract without
changing M1A or DailyMed behavior. It supports exactly provider-count occurrence
buckets for `GI_PT_SET_M1B_V1=(DIARRHOEA, NAUSEA, VOMITING)`, under MedDRA 29.0
English reference-only authority, with no role predicate and no raw individual
reports. Outputs disclose that the subset is non-comprehensive and that counts
establish neither incidence, causality, risk, exposure, nor product ranking.
Connector, persistence, tool, a FAERS API route, and live execution remain
outside FAERS-001. The existing enabled M1B OpenAPI envelope truthfully exposes
the additive typed FAERS request and report-section contracts.

## 1. Product definition

MedEvidence is a portfolio-grade research assistant for multi-source public
drug-safety information. It helps pharmaceutical, medical-research, and
pharmacovigilance users collect, compare, and audit source-aware findings.

MedEvidence is not a clinical decision-support system. It must not provide
diagnosis, treatment, dosage, emergency guidance, individualized medical
advice, regulatory approval, or an automated product-safety ranking.

## 2. V1 objective

V1 must demonstrate one complete, auditable research workflow:

```text
ResearchScope
  -> source-aware collection
  -> normalization and retrieval
  -> claim and citation construction
  -> comparability and conflict analysis
  -> structured draft report
  -> citation and safety gates
  -> human-approved export
```

The formal reference domain and acceptance scenario is:

> Compare public information about gastrointestinal adverse reactions for
> semaglutide and tirzepatide across PubMed, DailyMed, FAERS/openFDA, and the
> approved local CADEC corpus.

The reference domain is configuration and evaluation data, not hard-coded
application behavior. Drug, adverse-reaction, time-range, and source scope must
be represented by typed domain models so later releases can support other drugs
and adverse reactions without redesigning the workflow.

## 3. Target users

- Pharmacovigilance and drug-safety analysts performing preliminary research
- Medical-affairs and evidence-synthesis researchers
- Biomedical NLP and RAG engineers evaluating retrieval behavior
- Reviewers who require traceable sources instead of an opaque answer

V1 is an English-language, local, single-user demonstration using public data
and an approved local research corpus.

## 4. Source semantics

The four source classes are not interchangeable and must not be described as
equal-strength evidence:

| Source | V1 classification | Permitted role |
|---|---|---|
| PubMed | Scientific literature evidence | Retrieve and summarize study-level findings from available metadata and abstracts |
| DailyMed | Official labeling evidence | Retrieve product- and version-specific official labeling statements |
| FAERS/openFDA | Descriptive spontaneous-report data | Describe bounded reporting patterns with mandatory limitations |
| CADEC | Auxiliary NLP/retrieval corpus | Support entity extraction, terminology mapping, and retrieval experiments |

CADEC must not contribute to incidence, causal, clinical, regulatory, risk
ranking, or product-comparison conclusions.

FAERS must not be used to estimate incidence, infer causality, or rank products
by safety. V1 excludes disproportionality and safety-signal metrics.

## 5. V1 functional requirements

### V1-FR-001 — Configurable research scope

The system shall accept a typed `ResearchScope` containing drugs, adverse
reactions, optional time range, selected sources, language, and comparison
intent. The reference scenario shall be expressed through this contract rather
than application constants.

### V1-FR-002 — PubMed vertical slice

The system shall search PubMed and retrieve source records with PMID,
publication metadata, available abstract text, query provenance, retrieval
time, and document-status warnings. PubMed shall support the first end-to-end
report slice exposed through FastAPI.

### V1-FR-003 — DailyMed labeling

The system shall retrieve a specific product label with SETID, SPL version,
product identity, effective/published date, section identifiers, source
location, and version-selection provenance.

### V1-FR-004 — FAERS descriptive query

The system shall execute bounded, reproducible FAERS/openFDA aggregation
queries and return the statistical unit, filters, time window, result limit,
case-version treatment, drug role, coverage status, retrieval time, and
mandatory limitations.

### V1-FR-005 — CADEC auxiliary corpus

The system shall search an approved, versioned CADEC subset and preserve corpus,
annotation, split, and gold-versus-predicted provenance. CADEC output shall be
identified as auxiliary and excluded from product-risk conclusions.

### V1-FR-006 — Reproducible ingestion

Every ingestion run shall create an immutable raw file snapshot plus a
manifest containing source, query, retrieval time, record count, SHA-256,
connector version, and schema version. Normalization and indexing must be
replayable from approved snapshots.

### V1-FR-007 — Source-aware normalization

The system shall preserve original drug and adverse-reaction terms alongside
canonical mappings, mapping method, mapping confidence, product/formulation
context, and data-quality warnings.

### V1-FR-008 — Retrieval modes

The same frozen textual corpus shall support independently runnable BM25
sparse, dense, and RRF hybrid retrieval through one source-neutral contract.
An optional reranker may be evaluated but shall not be required for system
availability.

### V1-FR-009 — Claims and citations

Every material factual, numerical, comparative, or regulatory claim shall
reference one or more versioned source records and exact text spans or
structured-field locators. A citation must indicate whether it supports,
contradicts, or only contextualizes a claim.

### V1-FR-010 — Comparability and conflict

Before declaring consistency or conflict, the system shall compare drug
ingredient/product, formulation, route, population, indication, dose, time
window, outcome definition, comparator, and source question where available.
The result shall distinguish:

- consistent within a comparable scope;
- apparent difference caused by scope or definition;
- unresolved conflict among comparable findings;
- insufficient information;
- unavailable source.

### V1-FR-011 — Structured report

The system shall generate a report containing interpreted scope, source
coverage, source-specific findings, claims and citations, comparisons,
conflicts, limitations, retrieval-as-of time, and review/export state.

### V1-FR-012 — Controlled orchestration

A bounded LangGraph workflow shall coordinate stable tools without embedding
connector, normalization, retrieval, or citation-validation business logic in
graph nodes. Connector failure shall produce explicit partial coverage rather
than an empty-success result.

### V1-FR-013 — Citation and safety gates

Citation validation shall use two stages:

1. deterministic structural and policy validation of source identity, source
   version, locator/span existence, content hash, claim/source compatibility,
   and FAERS/CADEC restrictions;
2. versioned semantic-support evaluation returning `supported`, `uncertain`,
   or `unsupported`.

An uncertain claim requires human adjudication or removal. An unsupported
claim cannot enter a formal report. An LLM judge cannot be the sole ground
truth. A report shall remain a non-exportable draft when any material claim
fails either stage, required source limitations are missing, or the request
crosses the approved medical-information boundary.

### V1-FR-014 — Human-approved export

LangGraph human-in-the-loop shall be used only for formal export confirmation.
The sequence shall be `validate_report -> save_pending_draft ->
request_export_approval -> finalize_and_export`. The pending draft shall be
saved idempotently as `pending_review`. Approval shall route to the separate
`finalize_and_export` node using `report_id` and an idempotency key. Rejection
shall not export the report. No non-idempotent effect may occur before
approval.

### V1-FR-015 — Delivery interfaces

V1 shall expose the research workflow through FastAPI, a Streamlit
demonstration UI, and a read-only MCP adapter over stable tools. UI and MCP
must not bypass application tools.

### V1-FR-016 — Orthogonal source outcomes

Planning shall represent every considered source using exactly one of:

- `planning_status=selected`;
- `planning_status=skipped_not_applicable`;
- `planning_status=skipped_by_policy`.

Only a source that actually executes shall emit a terminal `SourceOutcome`:

- `execution_status`: `succeeded` or `failed`;
- `coverage_status`: `complete`, `partial`, or `unavailable`;
- `result_status`: `matches`, `no_match`, or `indeterminate`.

The only valid terminal combinations are the seven rows in
`ARCHITECTURE.md` Section 7.5. Only
`succeeded + complete + no_match` represents a successful exhaustive
zero-result query. Partial zero-result and failed zero-result executions are
`indeterminate`; failed or partial execution must never become absence of
evidence. Partial matches retain partial coverage. Final reports distinguish
`no_match` from `indeterminate`, and run aggregation cannot promote partial or
unavailable coverage to complete.

## 6. V1 non-functional requirements

### V1-NFR-001 — Research-only safety

Clinical, treatment, dosing, emergency, and individualized requests shall
follow the approved refusal/redirection policy. Outputs shall display the
research-only boundary.

### V1-NFR-002 — Provenance and reproducibility

Every published result shall be traceable to a source snapshot, schema,
connector version, query, model/prompt configuration where applicable, and
code revision.

### V1-NFR-003 — External-call resilience

All external calls shall use explicit timeouts, bounded retries with backoff
and jitter, rate-limit handling, query/result bounds, caching, and typed errors.

### V1-NFR-004 — Offline deterministic tests

Unit and contract tests shall not access live external services. Live API tests
shall be opt-in and excluded from default CI.

### V1-NFR-005 — Replaceable infrastructure

Domain and application contracts shall not expose FastAPI, LangGraph, Qdrant,
PostgreSQL, provider SDK, or model-vendor objects.

### V1-NFR-006 — Observability

Each run shall have a correlation ID and structured records for node/tool
duration, source status, retries, cache behavior, model/token/cost metadata
where available, citation-gate outcome, and export review.

### V1-NFR-007 — Local public-data boundary

V1 shall be local and single-user and shall:

- provide no file-upload or patient-record schema;
- accept public research questions only;
- reject suspected patient identifiers or patient-case narratives fail-closed;
- not persist rejected raw input;
- log only request IDs and redacted rejection metadata, not raw suspected PHI;
- include synthetic rejection tests for names, dates, record numbers,
  addresses, and patient narratives;
- not claim certified de-identification, HIPAA compliance, clinical validation,
  or regulatory use.

### V1-NFR-008 — Measured claims only

Quality, latency, cost, and reliability claims shall be computed from saved raw
evaluation results. Targets and estimates shall not be presented as achieved
measurements.

## 7. V1 report contract

A report must include:

- stable report and research-run identifiers;
- original and interpreted research scope;
- source coverage and unavailable-source warnings;
- source-specific sections using the approved source classifications;
- material claims with exact citations;
- comparability and conflict assessments;
- mandatory FAERS and CADEC limitations when those sources are used;
- retrieval and source “as of” timestamps;
- configuration, snapshot, and workflow versions;
- `draft`, `pending_review`, `approved`, `rejected`, or `exported` status;
- research-only safety notice.

V1 shall not publish a single numerical confidence score. It may display
separate, explainable dimensions such as traceability, directness,
applicability, coverage, consistency, data quality, and citation status.

## 8. Included in V1

- Configurable typed scope with the formal reference scenario
- PubMed, DailyMed, bounded FAERS/openFDA, and approved CADEC subset
- Immutable file snapshots, manifests, PostgreSQL metadata, and Qdrant indexes
- BM25, dense, RRF hybrid, and optional reranker experiment
- Stable tools and one controlled LangGraph workflow
- Claim-level citations, conflict classes, safety gates, and partial coverage
- FastAPI, Streamlit, read-only MCP tools, Docker Compose, and offline CI
- Sixty unique evaluation cases: Development-40, whose initial adjudicated
  subset is Gold-10 plus Additional-Development-30, and a separate
  non-overlapping Holdout-20
- Structured logging and foundational OpenTelemetry instrumentation

## 9. Explicitly postponed

- Redis and distributed cache/locking
- React and public multi-user deployment
- ClinicalTrials.gov and automatic full-text PMC ingestion
- GraphRAG, knowledge graphs, and multi-agent debate
- ROR, PRR, IC, automated signal detection, and product safety ranking
- Automated causality, meta-analysis, or evidence-grading decisions
- A single numerical confidence score
- PHI, patient uploads, real internal cases, and individualized risk
- Public multi-tenancy, enterprise RBAC, and HIPAA claims
- Kubernetes, Kafka, and distributed task queues
- Automated regulatory submission or export without human approval

## 10. Development milestones

### M0 — Design, interfaces, and ADR freeze

Acceptance:

- V1 requirements have stable IDs and map to architecture, tests, and criteria.
- Source roles, domain contracts, connector/tool boundaries, storage,
  retrieval, HITL, evaluation split, and technology stack are recorded.
- Required ADRs contain explicit project-owner approval metadata.
- Open questions have an owner and a latest-decision milestone.
- The original independent FAIL and all remediation claims are preserved in
  the audit record.
- An independent re-review of the actual repository issues PASS; only then
  does the conditional owner approval become effective.
- No business implementation has started.

### M1A — PubMed end-to-end vertical slice

Acceptance:

- A configurable `ResearchScope` reaches PubMed through a stable tool.
- An offline fixture and one bounded live query produce versioned records.
- An idempotent snapshot and manifest are generated.
- A minimal claim and exact PMID/abstract-span citation are produced.
- A structured draft report is returned through FastAPI.
- Timeout, malformed response, successful no-match, partial-match,
  partial-indeterminate, and unavailable-indeterminate outcomes have
  deterministic three-dimension status tests.

### M1B — Add DailyMed, FAERS, and CADEC sequentially

Acceptance:

- Each source passes its own offline contract tests before joining the workflow.
- DailyMed outputs identify product, SETID, SPL version, and label section.
- FAERS outputs expose statistical unit and mandatory non-causal limitations.
- CADEC remains visibly auxiliary and cannot affect product-risk conclusions.
- Each added source can fail independently and produce partial coverage.

### M2 — Retrieval and reranking evaluation

Acceptance:

- The same frozen corpus runs BM25, dense, and RRF hybrid modes.
- Results do not leak Qdrant-native objects across the retrieval contract.
- Gold-10, the initial adjudicated subset of Development-40, completes
  end-to-end metric validation before Additional-Development-30.
- Development-40 and separate non-overlapping Holdout-20 remain versioned.
- Raw per-query rankings, configuration, latency, and metrics are saved.
- A reranker is enabled by default only if measured benefit justifies latency.
- Release thresholds are proposed only from Development-40, approved and
  versioned before the first Holdout-20 run, and include explicit zero-tolerance
  safety events.

### M3 — Controlled LangGraph workflow

Acceptance:

- Graph nodes call stable tools and contain no connector/retrieval logic.
- Source failure, insufficient evidence, citation failure, and unsafe scope
  have explicit outcomes.
- The only interrupt sequence is `validate_report -> save_pending_draft ->
  request_export_approval -> finalize_and_export`.
- No non-idempotent side effect occurs before export approval.
- Draft persistence, resume, rejection, and idempotent export are tested.
- A failed citation gate cannot produce an `exported` report.

### M4 — Streamlit, MCP, Docker, and release acceptance

Acceptance:

- Streamlit completes the reference workflow through FastAPI.
- MCP exposes approved read-only tools and cannot bypass them.
- Docker Compose starts the approved V1 services.
- CI runs lint, format, type, unit, contract, and focused integration checks.
- The demonstration includes a normal comparison, source degradation,
  citation failure, evidence conflict, and safety refusal.
- Every public metric and portfolio claim links to reproducible raw results.

## 11. Open decisions and latest decision gates

These questions do not change the frozen V1 architecture, but they must be
resolved by the stated gate.

| Decision gate | Open decision | Decision owner | Resolve no later than |
|---|---|---|---|
| `ME-000A` | Exact production dependency, container-image, GitHub Action, and lock-file versions | Boqi Niu, Project Owner | Before the first dependency installation or container execution |
| `ME-000B` | Exact report-generation LLM provider/model and provider data-use/retention policy | Boqi Niu, Project Owner | Before real provider integration |
| `ME-000C` | Qdrant client/server version, tokenizer, sparse encoding, BM25 `k1`/`b`, dense embedding, reranker, and candidate/final limits | Boqi Niu, Project Owner | Before M2 index construction or retrieval comparison |
| `ME-000D` | External tracing vendor and exporter/data-retention policy | Boqi Niu, Project Owner | Before external trace export is enabled |
| `M1B-DAILYMED` | Detailed DailyMed selection rules for ambiguous candidate labels | Project owner with designated domain reviewer | Before DailyMed work in M1B |
| `M1B-FAERS` | Approved FAERS aggregate dimensions, date window, case-version, and deduplication policy | Project owner with designated pharmacovigilance reviewer | Before FAERS work in M1B |
| `M1B-CADEC` | CADEC asset location, license, distributable subset, and authoritative prior model outputs | Boqi Niu, Project Owner | Before CADEC work in M1B |
| `M3-MEDICAL-BOUNDARY` | Clinical-boundary and emergency-message wording | Project owner with designated medical reviewer | Before M3 safety-policy implementation |
| `M2-ADJUDICATION` | Medical/pharmacovigilance adjudicator for Gold-10, conflict, and safety cases | Boqi Niu, Project Owner | Before Gold-10 adjudication in M2 |
| `M3-EXPORT` | V1 export formats, local destinations, and retention periods | Boqi Niu, Project Owner | Before M3 export implementation |

## 12. M1B-DM-001 DailyMed contract freeze

M1B-DM-001 implements the additive domain/public-contract portion of
V1-FR-003 under [ADR-011](decisions/ADR-011-m1b-dailymed-contracts.md). It does
not implement or authorize DailyMed transport, parsing, persistence, API
routes, live smoke, or any medical-source network request.

The frozen acceptance behavior is:

- SETID is the exact lowercase, non-nil canonical UUID string; UUID version and
  variant are unrestricted. SPL version is a positive canonical integer
  string. Exact identity parity is required across request, discovery,
  decision, fetch, and parsed SPL surfaces.
- `succeeded/complete/matches` may select only after deterministic exact or
  equivalent-group resolution. Every positive-count
  `succeeded/partial/matches` and `failed/partial/matches` is
  `review_required`, including count one, resolved-equivalent, and pinned
  requests. Partial discovery never selects.
- only zero-count `succeeded/complete/no_match` is `no_candidate`. The three
  zero-count indeterminate triples create no decision row.
- source-indexed DailyMed sections remain visible for no-candidate, review, and
  decisionless indeterminate discovery. They have no authoritative stable
  label result or label locator.
- stable label versions and sections are fetch-independent; a label locator is
  admitted only after selected plus a distinct successful, complete, usable
  fetch.
- marketing state is closed to `active|archived|unknown`. Stable label-version
  identity derives only from schema, source, SETID, SPL version, and content
  hash; dates, marketing state, and artifact binding do not change that ID.
- `RetainedSplResponse` and `LabelSelectionWarning` close the fetch and warning
  evidence bindings. Requested sections absent after a usable fetch remain
  visible as `section_absent:<LOINC-code>` and never gain an unbound locator.
- the section registry is the exact four Active LOINC 2.82 code/title pairs in
  ADR-011. No fuzzy title matching or expansion is allowed.
- `connector_trust_allowlist` stores the six closed DailyMed HTTPS path/query
  designs but authorizes no network I/O. Ordinary/runtime host lists are empty
  and medical-source network execution is false for this work item.
- future XML/ZIP implementations must use the frozen fail-closed bounds,
  direct HL7 selector attributes, inert additional safe attributes, no
  filesystem extraction, and pre-normalization rejection of every ASCII C0
  control and DEL.
- the typed connector oracle also freezes all denied classes, `5/10/5/5`
  second phase timeouts, 30-second deadline, two attempts, retry/backoff/
  Retry-After limits, five-page/100-candidate/5,242,880-byte discovery bounds,
  immutable fixed-version cache, and no discovery cache or stale fallback.

The additive `M1BResearchRequestV1`/`M1BResearchReportV1` schemas do not mutate
the existing M1A request/report schemas or `/v1/research/pubmed` behavior.
M1B-DM-002 remains separately unauthorized.

## 13. M1B-DM-003 DailyMed report and API integration

M1B-DM-003 adds the Owner-frozen report/tool and delivery boundary without
changing selection, connector, ingestion, or persistence semantics. A pure
tools-layer operation builds `M1BResearchReportV1` only from exact trusted
acquisition outcomes, selection decisions, fetch evidence, and source sections.
It creates exactly one selected DailyMed planning entry; callers cannot submit
planning status or reasons.

`POST /v1/research/dailymed` accepts the closed `m1b.request.v1` envelope and
returns only the closed `m1b.report.v1` envelope. Unknown fields fail closed,
including `source_plan`, `planning_status`, `reason`, and `reason_code`. Reports
remain research-only, `draft`, and non-exportable. The existing PubMed route and
its transitive OpenAPI component subtree remain byte-compatible.

Ordinary and integration validation is offline with sockets blocked. The live
DailyMed harness is disabled; executing it requires a separate exact one-run
Owner authorization.

## 14. M1B-FAERS-003 aggregate report and API integration

M1B-FAERS-003 adds the frozen FAERS aggregate report/tool and typed API
projection without changing the connector, parser, snapshot, persistence, or
migration semantics merged in FAERS-002. The tools layer accepts only exact
typed FAERS executions and constructs a draft, research-only, non-exportable
`M1BResearchReportV1` with one complete locator per aggregate bucket.

`POST /v1/research/faers` is installed only when an explicit FAERS report
application is injected. It accepts the closed `m1b.request.v1` envelope for
FAERS alone, rejects unknown and caller-planning fields, and returns the closed
`m1b.report.v1` envelope. The default application, PubMed route, and DailyMed
route retain their existing behavior and OpenAPI contracts.

Every FAERS result retains `provider_count_occurrence`,
`unfiltered_provider_roles`, `GI_PT_SET_M1B_V1=("DIARRHOEA", "NAUSEA",
"VOMITING")`, exact query/date/bounds identity, and the full mandatory
limitation tuple. Counts establish no incidence, causality, relative or
comparative risk, comparative safety, or ranking. No individual FAERS report,
narrative, or provider payload crosses the report boundary. Ordinary tests are
offline; the live harness is disabled pending separate exact Owner authority.

## 15. M1B-CADEC-001 asset and standalone domain contract freeze

M1B-CADEC-001 resolves the CADEC asset-governance gate for an external-only
approved corpus and adds source-neutral typed asset, document, provider-gold
annotation, locator, split, vocabulary-reference, and provenance contracts. It
does not add loader, ingestion, persistence, migration, search, index,
training, tool, orchestration, API, or report-section execution. The existing
empty `cadec_query_requests` tuple and M1B source-section union remain
unchanged, so CADEC execution is disabled and OpenAPI is unaffected.

The exact asset has 1,250 canonical and 1,248 admitted documents. The exact
sorted exclusions are `DICLOFENAC-SODIUM.7` and `LIPITOR.221`. Five malformed
rows are rejected and never repaired or reinterpreted. The separate 91
reference-binding limitations (2 original-term, 44 MedDRA, 45 SCT) remain
visible and are not malformed, rejected, normalized, repaired, or
reinterpreted by this node. Only provider gold annotations are admitted; no
predicted artifact is admitted.

Raw corpus bytes remain external and non-redistributable, with no
corpus-derived real fixtures in Git. Controlled vocabularies expose only
the exact `MedDRA` and `SNOMED CT` references, exact unstated-version text, and
`reference-only` legal status, never restricted identifiers, terms, hierarchy,
or payload. The CSIRO Data Licence ID 1061 requires attribution and permits
only non-commercial internal research under the conservative no-IP-assertion,
no-provider-endorsement, and no-redistribution policy. Children bind the exact
release manifest, audit, split membership, and parent lineage. Auxiliary use
also prohibits ranking, advice, dosage, emergency guidance, and individualized
medical advice. `MEDEVIDENCE_CADEC_SPLIT_V1` and its exact membership hashes are
recorded in ADR-013. CADEC-002 is separately Owner-gated.
