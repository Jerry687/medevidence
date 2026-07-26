# ADR-009: M1A PubMed vertical-slice contracts and dependency gate

- Status: Accepted by Project Owner; effective for the post-merge M1A sequence
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-26
- Approval reference:
  [M1A-001A-OWNER-AUTHORIZATION-001](../reviews/M1A-001A-OWNER-AUTHORIZATION-001.md)
- Revision: 2
- Independent review reference:
  [M1A-001A-INDEPENDENT-REVIEW-001](../reviews/M1A-001A-INDEPENDENT-REVIEW-001.md)
- Independent review role: Validation only; not an approving authority

## Context

M0 and `ME-000A` are complete and approved. The repository has an approved
Python 3.12.13 development baseline, offline quality controls, local
PostgreSQL/Qdrant infrastructure contracts, and CI foundation, but it has no
MedEvidence business implementation and no production Python dependencies.

M1A is the first approved business vertical slice. It must prove a complete but
bounded PubMed path without prematurely implementing later sources, retrieval,
orchestration, model generation, review, or export. Before that work starts,
the Project Owner needs one reviewable decision covering contracts, boundaries,
evidence semantics, persistence direction, live-query limits, and exact direct
dependency decisions.

The Project Owner accepted this ADR and made
`M1A-001A-OWNER-AUTHORIZATION-001` effective on 2026-07-26 after an
independent governance review returned PASS. This acceptance authorizes the
bounded M1A sequence and exact direct dependency decisions recorded here, but
the first implementation work item may begin only after this governance
package is merged into `main`. No dependency installation, lock-file change,
or business implementation is authorized on this governance branch.

## Decision

### 1. Phase transition and work-item sequence

The approved transition is from completed Phase 0 and `ME-000A` into the
bounded M1A PubMed vertical slice. M1A is decomposed into these sequential
work items:

1. `M1A-001A` - decision and dependency gate;
2. `M1A-001B` - source-neutral domain contracts;
3. `M1A-002` - bounded PubMed connector;
4. `M1A-003A` - immutable snapshots and manifests;
5. `M1A-003B` - PostgreSQL snapshot metadata;
6. `M1A-004` - PubMed tools, claims, citations, and draft report;
7. `M1A-005` - FastAPI and M1A acceptance evidence.

Each work item after `M1A-001A` uses a separate branch and focused Draft PR
created from the latest approved `main` baseline. No monolithic M1A
implementation PR is authorized.

The M1A implementation scope is limited to:

- typed source-neutral domain contracts;
- PubMed search and record retrieval;
- deterministic offline fixtures;
- immutable raw snapshots and manifests;
- PostgreSQL snapshot metadata;
- stable PubMed application tools;
- a deterministic minimal claim and exact abstract-span citation;
- a structured non-exportable draft report;
- FastAPI transport; and
- one separately opt-in bounded live PubMed smoke query.

DailyMed, FAERS/openFDA, CADEC implementation, Qdrant indexing or retrieval,
BM25, dense retrieval, RRF, reranking, LangGraph, LLM integration, `ME-000B`,
Streamlit, MCP, export, HITL, external tracing, and unrelated refactoring are
excluded. `ME-000B` remains deferred because M1A claim construction is
deterministic and extractive rather than model-generated.

### 2. Package boundaries

The approved M1A packages and responsibilities are:

| Boundary | M1A responsibility |
|---|---|
| `domain` | Source-neutral scope, publication, provenance, plan, outcome, claim, citation, and draft-report contracts plus validation rules and domain errors |
| `connectors.pubmed` | Fixed-host PubMed HTTP access, query construction, pagination, response-byte capture, XML parsing, retry classification, and upstream-error mapping |
| `ingestion` | Raw snapshot writing, canonical manifest construction, integrity verification, replay, and transformation lineage |
| `persistence` | SQLAlchemy/PostgreSQL implementations for snapshot, manifest, acquisition-attempt, and source-outcome metadata |
| `tools` | Stable `search_pubmed` and `fetch_pubmed_article` application operations over injected ports |
| `api` | Versioned FastAPI request validation, transport mapping, local safety boundary, and response/error serialization |
| composition root | The only location that creates concrete HTTP, snapshot, PostgreSQL, tool, and API objects and wires them together |
| `tests` and fixtures | Deterministic unit, offline contract, selected PostgreSQL integration, FastAPI integration/e2e, and separately opt-in live-smoke evidence |

The composition root is an outer-layer module. It contains wiring only and
does not become a service locator or a home for business rules.

Fixture placement follows the repository test classification:

- pure contract and policy cases under `tests/unit`;
- synthetic PubMed responses under `tests/fixtures/pubmed`;
- offline connector contracts under `tests/contract`;
- disposable PostgreSQL checks under `tests/integration`;
- local user-flow checks under `tests/e2e`; and
- the live query under an explicitly selected `live_api` test.

### 3. Dependency direction

Python imports point inward through stable contracts:

```text
api -> tools -> domain
connectors.pubmed -> domain
ingestion -> domain plus consumer-owned snapshot/persistence ports
persistence -> domain plus consumer-owned persistence ports
composition root -> all concrete outer adapters
```

The `domain` package may depend only on the Python standard library and the
approved Pydantic v2 schema implementation. It must not import HTTPX, FastAPI,
SQLAlchemy, a PostgreSQL driver, provider SDKs, Qdrant, LangGraph, MCP, an LLM
SDK, or another outer adapter.

Connectors return source-neutral domain contracts and typed source-aware
errors; they do not expose HTTPX request/response objects. Persistence returns
domain/application contracts and does not expose SQLAlchemy rows or sessions.
The API calls tools/application services only and cannot call a connector,
database, or snapshot writer directly.

### 4. Schema policy

Persisted and externally exchanged M1A contracts carry the literal initial
schema version `1.0`. Validation is strict and rejects unknown fields at
durable boundaries. Durable cross-layer contracts are typed; an untyped
dictionary is not an accepted stored, tool, or API contract.

All internal timestamps are timezone-aware UTC. Serialized timestamps use
RFC 3339 UTC form with a `Z` suffix. Naive timestamps are rejected.

Domain value objects and externally exchanged records are immutable after
validation. A correction, refresh, or replay creates a new record/version or
attempt rather than mutating the prior object.

Any change to a serialized field name, type, required/optional status, enum,
version-identity rule, citation locator, or evidence meaning requires a new
approved decision before implementation. Short-lived local helper values do
not each need a schema version.

### 5. `ResearchScope`

The approved source-neutral `ResearchScope` contains:

- `schema_version`;
- a non-empty typed sequence of `DrugConcept` values;
- a non-empty typed sequence of `AdverseEventConcept` values;
- an optional inclusive date range with explicit date precision;
- a non-empty typed selected-source set;
- a BCP 47 language value, limited to English in M1A;
- a typed comparison intent;
- typed query, page, record, payload-byte, and total-time bounds; and
- a stable scope identity derived from its canonical serialized content.

M1A policy permits execution of PubMed only. The contract may use the existing
V1 source enum, but selecting an unimplemented source cannot trigger that
source; it is rejected or represented at planning as skipped by policy.

`ResearchScope` has no patient-record, patient-narrative, clinical-note,
file-upload, free-form endpoint, or arbitrary URL field. Connectors derive a
bounded query from typed concepts; a caller cannot supply a host or endpoint.

The semaglutide/tirzepatide gastrointestinal reference scope and a second
synthetic drug/adverse-reaction scope must use the same schema, validation,
planning, tool, and report path. Drug- or reaction-specific branches are
prohibited.

Exact ordinary offline query/result bound values remain an owner decision for
`M1A-001B`/`M1A-002`; the live-smoke bounds are frozen in Section 14.

### 6. Source planning and terminal outcomes

Planning and execution remain separate. Every considered source has exactly
one planning status:

- `selected`;
- `skipped_not_applicable`; or
- `skipped_by_policy`.

A skipped source has no `SourceOutcome`. A selected source that never starts
execution also has no fabricated terminal outcome and prevents report
completion.

Every executed source has exactly one immutable terminal outcome with the
three orthogonal dimensions defined in `ARCHITECTURE.md` Section 7.5. The
seven valid combinations are:

| # | Execution | Coverage | Result |
|---|---|---|---|
| 1 | `succeeded` | `complete` | `matches` |
| 2 | `succeeded` | `complete` | `no_match` |
| 3 | `succeeded` | `partial` | `matches` |
| 4 | `succeeded` | `partial` | `indeterminate` |
| 5 | `failed` | `partial` | `matches` |
| 6 | `failed` | `partial` | `indeterminate` |
| 7 | `failed` | `unavailable` | `indeterminate` |

The eleven remaining combinations are invalid and must be rejected:

| # | Execution | Coverage | Result |
|---|---|---|---|
| X01 | `succeeded` | `complete` | `indeterminate` |
| X02 | `succeeded` | `partial` | `no_match` |
| X03 | `succeeded` | `unavailable` | `matches` |
| X04 | `succeeded` | `unavailable` | `no_match` |
| X05 | `succeeded` | `unavailable` | `indeterminate` |
| X06 | `failed` | `complete` | `matches` |
| X07 | `failed` | `complete` | `no_match` |
| X08 | `failed` | `complete` | `indeterminate` |
| X09 | `failed` | `partial` | `no_match` |
| X10 | `failed` | `unavailable` | `matches` |
| X11 | `failed` | `unavailable` | `no_match` |

Only `succeeded + complete` may produce `no_match`. Truncation, an enforced
bound reached before exhaustion, incomplete pagination, or parse loss is
partial coverage. Partial or failed zero-result execution is
`indeterminate`, never an absence-of-evidence claim.

`SourceOutcome` remains separate from publication status. Its
`execution_status`, `coverage_status`, and `result_status` fields describe
source execution and coverage only; they cannot encode correction, retraction,
expression-of-concern, or unknown publication status. A retracted publication
that was retrieved successfully may still have a successful source outcome,
while its eligibility to support a claim is restricted independently.

### 7. `PublicationRecord`

The approved source-neutral publication record contains:

- `schema_version="1.0"` and `source_type=pubmed`;
- PMID as the stable source identifier;
- DOI and PMCID when available;
- title and optional canonical abstract;
- authors, journal, language, publication types, and publication date with
  explicit precision;
- a typed current publication status;
- status source or PubMed relationship metadata, related PMID or notice
  identity when available, and notice type;
- publication-status retrieval-as-of time, machine-readable warning codes, and
  human-readable disclosure text;
- indexing status;
- explicit `title_and_abstract` or `title_only` evidence scope;
- source URL or replayable lookup key;
- retrieval time, connector version, snapshot identity, and transformation
  lineage;
- parse and source-status warnings; and
- a deterministic SHA-256 content/version hash.

The canonical abstract is built deterministically from PubMed abstract
sections in source order. Character content and section order are preserved;
line endings become `\n`; sections are separated by `\n\n`; and Unicode
normalization, whitespace folding, case conversion, generated summaries, and
full-text substitution are prohibited. When a source section label is
retained, it is stored as structured metadata rather than inserted into the
citable text.

The publication-version identity is the PMID plus the deterministic canonical
record hash. A re-fetch with changed canonical content or status produces a
new version identity. M1A never represents an available abstract as reviewed
full text.

#### 7.1 Typed publication-status contract

`PublicationStatus` is a required, source-neutral typed value object. Its
status is exactly one of:

- `current_or_no_known_notice`;
- `corrected`;
- `retracted`;
- `expression_of_concern`; or
- `unknown_or_unverified`.

`current_or_no_known_notice` means only that the declared status source showed
no known correction, retraction, or expression-of-concern notice as of the
recorded retrieval time. It is not a clinical-quality score, guarantee of
validity, or assertion that no later or unindexed notice exists.

The value object preserves:

- the status value;
- the status source and PubMed relationship type or equivalent lookup
  metadata;
- related PMID and notice identity when available;
- notice type;
- a timezone-aware UTC status retrieval-as-of time;
- the applicable machine-readable status warning codes; and
- deterministic human-readable disclosure text.

`notice_type` is typed as `correction`, `retraction`,
`expression_of_concern`, or absent when no known notice is available. An
unrecognized or unresolved upstream relationship preserves its source value,
uses `unknown_or_unverified`, and cannot be coerced to a known notice type.

The required status warning codes are:

- `publication_status_current_or_no_known_notice`;
- `publication_status_corrected`;
- `publication_status_retracted`;
- `publication_status_expression_of_concern`; and
- `publication_status_unknown_or_unverified`.

Exactly one corresponds to the current status value, and typed
relationship/provenance warnings may be added. Every non-current or unknown
status has a visible warning requirement. Unresolved or conflicting
relationships add a distinct
`publication_status_relationship_unresolved` warning and cannot be silently
collapsed to `current_or_no_known_notice`.

The `publication_status_identity` is the SHA-256 of the canonical serialized
status value object, including its relationship/notice metadata and status
provenance. Publication status is part of the canonical record hash and
publication-version identity. A change in status, related PMID, notice
identity/type, status source, warning codes, or status provenance therefore
creates a new status and publication version identity.

### 8. Exact abstract-span citations

An M1A citation contains:

- `schema_version="1.0"`;
- PMID and publication-version identity;
- publication status and `publication_status_identity`;
- references to every required publication-status warning code;
- the canonical abstract SHA-256;
- zero-based half-open `[start, end)` offsets measured in Unicode code points
  into the exact canonical stored abstract;
- the exact quoted substring;
- the supporting relationship; and
- deterministic validation state and reason codes.

Validation recomputes the abstract hash and requires:

```text
canonical_abstract[start:end] == exact_quote
```

Validation fails closed when the quote, offsets, PMID, publication version, or
abstract hash differs; the span is empty or out of range; or no canonical
abstract exists. Byte, UTF-16 code-unit, token, sentence, HTML, or rendered
page offsets are not accepted as the durable M1A locator.

Structural validation also fails closed when:

- publication status or `publication_status_identity` is omitted;
- citation status does not match its `PublicationRecord`;
- a related correction, retraction, or expression-of-concern relationship,
  related PMID, or notice identity has changed;
- any required status warning reference is absent; or
- the publication version, status source, or status provenance has drifted.

### 9. Deterministic claim policy

M1A claims are deterministic attributed extracts. The stored claim text is the
exact validated abstract span; attribution, PMID, publication version, scope,
and limitations are separate structured fields. A renderer may add a fixed
non-medical prefix such as `PMID <id> reports:`, but it cannot paraphrase or
combine evidence into a new medical conclusion.

M1A produces:

- no synthesized medical conclusion;
- no treatment, diagnosis, dosage, or individualized advice;
- no product safety ranking;
- no incidence, relative-risk, or causal inference;
- no claim supported only by title text; and
- no claim is emitted when an exact valid supporting span cannot be
  constructed.

Publication status imposes a separate deterministic use policy:

- `current_or_no_known_notice` may support an affirmative attributed extract
  only when all other citation and evidence checks pass;
- `corrected` must resolve and disclose the correction relationship, use the
  current corrected record or corrected content when the source relationship
  permits, and retain its status warning;
- `retracted` cannot support an unqualified affirmative material claim and may
  be cited only for explicit retraction, correction-history, or other
  source-status context;
- `expression_of_concern` can never be presented as unqualified support; a
  retained extract requires a visible warning and a typed `support_limited` or
  source-status context;
- `unknown_or_unverified` is disclosed, is never treated as current, and may
  appear only as warning-bearing `support_limited` or source-status context;
  and
- no claim is created when required publication-status provenance,
  relationships, identity, or warning references cannot be validated.

The typed use context is a policy restriction, not a clinical-quality score.
Status restrictions cannot be relaxed because the source execution itself
succeeded.

Partial and unavailable coverage remains explicit in the draft report and is
never converted into no evidence. Because this policy uses no model-generated
claim, `ME-000B` is not required for M1A.

### 10. Raw snapshots and canonical manifests

The snapshot stores the exact raw HTTP response-body bytes supplied to the
parser, before character decoding, XML parsing, normalization, or record
extraction.
HTTP status, media type, content encoding, selected cache/provenance headers,
and the fixed request identity are manifest metadata; transport framing is not
part of the body snapshot.

The snapshot identity is `sha256:<lowercase-hex-digest>`. The approved
content-addressed path is:

```text
<configured-root>/pubmed/sha256/<first-two-hex>/<digest>.bin
```

The storage root is required configuration outside Git. Writes are atomic and
immutable. A write uses a same-directory temporary file, flushes and verifies
bytes/hash, then atomically publishes to an absent content path. An existing
path is reused only after its bytes verify against the requested digest.
Snapshot files are never overwritten or mutated.

The manifest is canonical UTF-8 JSON with no BOM, LF line endings, keys sorted
by Unicode code point, compact separators, and no NaN or Infinity values. It
contains the fields required by `DATA_SOURCES.md`, including exact file size
and hash, bounded query identity, UTC attempt times, connector and schema
versions, pagination/limits, status triad, warnings, and code revision. Its
identity is the SHA-256 of its canonical bytes.

Replay verifies raw bytes, snapshot ID, manifest bytes/ID, schema support,
record count, and derived publication hashes before returning records.

An unavailable attempt with no usable body creates no raw snapshot and no
fabricated source record. It retains typed failure provenance in an immutable
acquisition-attempt record and may create a zero-file manifest: bounded
request identity, UTC timestamps, error class, retry count, coverage/result
status, and redacted diagnostics. If any raw response bytes arrive before a
failed, unavailable, or partial terminal outcome, those exact bytes and their
manifest remain subject to the same immutable snapshot policy and cannot be
discarded because execution failed or coverage was partial.

### 11. PostgreSQL metadata

PostgreSQL is authoritative for snapshot, manifest, acquisition-attempt,
publication-version, transformation-lineage, and source-outcome metadata. Raw
HTTP payload bytes remain in immutable files and are never copied into
database columns.

M1A uses synchronous SQLAlchemy and the synchronous Psycopg API. Transactions
are explicit; sessions and SQLAlchemy models remain inside the persistence
adapter. Database constraints reject all eleven invalid source-outcome
combinations and enforce source/snapshot identity uniqueness and referential
lineage.

Exact tables, columns, indexes, constraint names, and Alembic migrations
remain subject to the focused `M1A-003B` design and owner review. The
live-artifact retention semantics in Section 14.1 are frozen, but this ADR does
not authorize a migration or freeze exact DDL.

### 12. Stable PubMed tools and reports

M1A exposes the stable application operations `search_pubmed` and
`fetch_pubmed_article`. They accept validated source-neutral input, invoke
injected capabilities, and return bounded source-neutral contracts. Provider
or persistence-native objects cannot cross the tool boundary.

The M1A report is a structured `draft`. It contains interpreted scope, PubMed
plan/outcome, publication version, deterministic extract claim, exact
citation, retrieval-as-of time, limitations, snapshot/manifest identity, and
research-only notice.

The report also contains typed publication-status data that cannot be omitted
downstream:

- source-level status and warning entries for each retained
  `PublicationRecord`;
- claim-level references to the applicable status warnings;
- related PMID or notice identity when available; and
- visible disclosure for every `corrected`, `retracted`,
  `expression_of_concern`, and `unknown_or_unverified` record.

The later M1A-005 API schema and serializer must preserve the status identity,
typed warning codes, warning references, related notice identity, and visible
disclosure. A transport mapping that drops them is invalid.

There is no `pending_review`, `approved`, `rejected`, or `exported` transition
in M1A. The draft is non-exportable.

### 13. FastAPI transport

M1A API routes are namespaced under `/v1/`. FastAPI is a transport adapter:
routes validate/translate requests, call tools/application services, and map
typed results/errors. Routes cannot call PubMed, PostgreSQL, or snapshot
storage directly.

The transport returns structured draft reports only. It exposes no export,
HITL, arbitrary URL, file upload, patient record, clinical note, model prompt,
or provider-native object.

Exact route paths below `/v1/`, request/response schemas, and error status
mapping require focused owner review before `M1A-005`. No standalone ASGI
server dependency is authorized for M1A. `M1A-005` may test FastAPI through an
in-process ASGI test client. Uvicorn or any other server dependency requires a
later explicit Project Owner decision. FastAPI is approved without optional
`standard` or `all` extras, so this ADR does not authorize FastAPI Cloud
tooling, form-upload support, or other optional capabilities.

### 14. Live PubMed smoke boundary

The only current M1A live-query candidate is:

```text
semaglutide[Title/Abstract] AND gastrointestinal[Title/Abstract]
```

The live test:

- is excluded from default unit, contract, integration, e2e, and CI commands;
- carries the existing `live_api` pytest marker;
- requires `MEDEVIDENCE_RUN_LIVE_PUBMED=1`;
- uses only the fixed NCBI E-utilities HTTPS host and approved search/fetch
  paths;
- sets `tool=medevidence` and requires an owner-supplied `NCBI_EMAIL`;
- accepts no arbitrary host, endpoint, URL, query, or identifier from the test
  caller;
- requests at most one search page and at most one record;
- performs no concurrent or repeated smoke calls;
- uses the approved explicit connect/read timeout and retry policy; and
- saves acceptance evidence containing the exact query, UTC time, code
  revision, connector/schema version, terminal outcome, and snapshot/manifest
  identities.

The retention policy in Section 14.1 is approved, but it does not authorize a
live request. Before `M1A-005` executes any live acceptance query, the Project
Owner must separately approve the exact query, NCBI client-identification
values, execution time, and final acceptance command. A successful zero-result
query may validate search/outcome handling but cannot fabricate a fetch
result. Default CI remains fully offline.

#### 14.1 Approved live-query artifact retention and disposition policy

The approved policy identifier is `M1A-LIVE-RETENTION-v1`. It applies to every
M1A live-query run, manifest, retained artifact, and acceptance-evidence
summary.

**Raw live PubMed response snapshots**

- Store exact raw response bytes under the configured local immutable snapshot
  root outside Git using SHA-256 content addressing.
- Retain them through the complete V1 development and acceptance lifecycle
  without automatic deletion.
- Reassess archival or deletion only through a later explicit Project Owner
  decision.
- Do not commit raw responses to Git unless they are separately sanitized,
  reviewed, licensed, bounded, and explicitly approved.

**Snapshot manifests**

- Store manifests with immutable snapshot artifacts outside Git.
- Retain them indefinitely as integrity and replay records.
- Never overwrite or silently replace a manifest.

**Normalized `PublicationRecord` artifacts**

- Store normalized records outside Git in the approved local artifact
  location.
- Retain them through the V1 development and acceptance lifecycle.
- Preserve schema version, source snapshot identity, and content hash.
- A newer normalized version supplements rather than overwrites an earlier
  version.

**PostgreSQL and run metadata**

- PostgreSQL remains authoritative for snapshot, run, provenance, and artifact
  metadata.
- Retain metadata indefinitely unless a later Owner-approved migration or
  retention decision changes the policy.
- Any deletion must preserve an auditable tombstone or disposition record.

**Acceptance evidence**

- A small redacted acceptance summary may be stored under `docs/reviews` and
  committed to Git.
- It must contain no raw abstract body, credential, header, secret, or
  unredacted upstream payload.
- Approved summaries, hashes, commit identities, manifest identities,
  commands, and outcomes are retained indefinitely.

**Logs**

- Ordinary logs remain outside Git.
- Approved redacted operational logs are retained for 90 days.
- Logs contain no raw abstract text, credentials, authorization headers,
  connection strings, or complete upstream responses.
- Audit identities and result summaries required for approved acceptance
  evidence are preserved separately from expiring logs.

**Failed, unavailable, and partial attempts**

- If any raw response bytes arrive before failure, retain those exact bytes and
  their manifest under the immutable snapshot policy.
- A completely unavailable attempt with no raw response bytes may retain only
  typed failure/run metadata and a zero-file manifest.
- Partial response bytes are not discarded because execution failed or
  coverage was partial.
- Failure metadata remains redacted and cannot fabricate a successful
  `PublicationRecord`.

**Duplicate, idempotent, superseded, and invalid runs**

- Identical raw bytes reuse the existing content-addressed snapshot.
- Every research or acceptance run retains its own run identity, query,
  timestamp, code revision, connector version, outcome, and snapshot-hash
  reference.
- Duplicate runs create neither duplicate raw files nor overwritten run
  metadata.
- New runs supplement prior runs. An artifact may be marked superseded but
  remains traceable.
- Corrupt or invalid artifacts are quarantined or marked invalid and cannot be
  silently deleted or reused.

Deletion requires explicit Project Owner authorization and a disposition
record containing artifact identity, reason, UTC time, and approving
authority. Manifests, live-query run metadata, and acceptance evidence persist
the explicit retention-policy identifier. Public PubMed data only is allowed;
patient data, credentials, authorization headers, and raw abstract text in
ordinary logs remain prohibited.

### 15. Approved direct dependency pins

Research cutoff: `2026-07-26`. Sources are official project documentation,
official release records, Python 3.12.13 documentation, and version-specific
PyPI metadata.

For every exact version below, the version-specific PyPI vulnerability field
returned no direct advisory on the research date. That observation is not a
resolved dependency-tree audit and does not cover future disclosures, optional
extras, system libraries, or bundled native libraries. The first lock proposal
after this approval must be reviewed and audited before merge; the audit
result, resolved graph, licenses, and exceptions must be saved.

| Exact direct pin | Purpose | First item | Python 3.12.13 | License | Major transitive dependencies | Security and selection rationale | Class |
|---|---|---|---|---|---|---|---|
| [`pydantic==2.13.4`](https://pypi.org/project/pydantic/2.13.4/) | Strict typed/versioned durable contracts | `M1A-001B` | Explicit 3.12 classifier; requires Python >=3.9 | MIT | `pydantic-core==2.46.4`, `annotated-types`, `typing-extensions`, `typing-inspection` | Latest stable v2 release on cutoff; direct PyPI advisory list empty; exact core coupling remains visible | Production |
| [`httpx==0.28.1`](https://pypi.org/project/httpx/0.28.1/) | Synchronous bounded PubMed HTTP transport | `M1A-002` | Explicit 3.12 classifier; requires Python >=3.8 | BSD-3-Clause | `anyio`, `certifi`, `httpcore==1.*`, `idna`, and `h11` through `httpcore` | Latest stable non-prerelease; supports explicit timeouts and sync API; direct advisory list empty | Production |
| [`tenacity==9.1.4`](https://pypi.org/project/tenacity/9.1.4/) | Bounded classified retry/backoff with jitter | `M1A-002` | Explicit 3.12 classifier; requires Python >=3.10 | Apache-2.0 | None at runtime | Latest stable; no runtime dependency expansion; direct advisory list empty | Production |
| [`fastapi==0.140.0`](https://pypi.org/project/fastapi/0.140.0/) | `/v1/` transport adapter | `M1A-005` | Explicit 3.12 classifier; requires Python >=3.10 | MIT | `starlette`, `pydantic`, `typing-extensions`, `typing-inspection`, `annotated-doc` | Latest stable and compatible with approved Pydantic; direct advisory list empty; released 2026-07-24, and the owner accepts its limited soak time; no extras approved | Production |
| [`sqlalchemy==2.0.51`](https://pypi.org/project/SQLAlchemy/2.0.51/) | Synchronous PostgreSQL persistence adapter | `M1A-003B` | Explicit 3.12 classifier and CPython 3.12 wheels | MIT | `greenlet`, `typing-extensions` | Latest stable SQLAlchemy 2 release on cutoff; direct advisory list empty; keeps ORM/SQL outside domain | Production |
| [`alembic==1.18.5`](https://pypi.org/project/alembic/1.18.5/) | Reviewed PostgreSQL schema migrations | `M1A-003B` | Explicit 3.12 classifier; requires Python >=3.10 | MIT | `SQLAlchemy`, `Mako`, `typing-extensions` | Latest stable; aligns with the approved SQLAlchemy 2 selection; direct advisory list empty; migrations still require focused review | Production tooling |
| [`psycopg[binary]==3.3.4`](https://pypi.org/project/psycopg/3.3.4/) | Synchronous PostgreSQL DBAPI driver on Windows/local CI | `M1A-003B` | Explicit 3.12 and Windows classifiers; requires Python >=3.10 | LGPL-3.0-only | `psycopg-binary==3.3.4`; conditional `typing-extensions` | Self-contained binary extra bundles native client libraries; platform wheels are best-effort; local Windows use requires lock, vulnerability, native-library inventory, and focused integration review; not pre-approved for production | Production |
| [`defusedxml==0.7.1`](https://pypi.org/project/defusedxml/0.7.1/) | Harden parsing of untrusted PubMed XML | `M1A-002` | Metadata permits 3.12, but classifiers stop at 3.9; focused 3.12.13 tests required | PSFL | None | Latest stable; Python 3.12.13 documentation recommends `defusedxml` for untrusted XML; direct advisory list empty; age/classifier gap is an explicit acceptance risk | Production |
| [`pip-audit==2.10.1`](https://pypi.org/project/pip-audit/2.10.1/) | Audit the approved resolved lock against known Python advisories | `M1A-001B` | Explicit 3.12 classifier; requires Python >=3.10 | Apache-2.0 | `CacheControl`, `cyclonedx-python-lib`, `packaging`, `pip-api`, `pip-requirements-parser`, `requests`, `rich`, `tomli`, `tomli-w`, `platformdirs` | Current stable PyPA tool; direct advisory list empty; audit is networked and separately selected, not part of default offline quality checks | Development |

Python 3.12.13 itself warns that standard-library XML modules are not secure
against maliciously constructed data and recommends `defusedxml` for server
code parsing untrusted XML:
<https://docs.python.org/3.12/library/xml.html>.

The `psycopg[binary]` distribution is self-contained and bundles native client
libraries. Its bundled `libpq`, `libssl`, and other native-library versions
create separate inventory, advisory-monitoring, and patch-ownership
obligations beyond Python-package auditing. Binary wheel availability is
platform-dependent and best-effort.

M1A local Windows development may use the approved binary extra only after
resolved-lock review, vulnerability review, native-library inventory, and
focused PostgreSQL integration validation. Deployment suitability must be
reassessed before production use; a locally linked or source-built deployment
may be preferable where the environment requires controlled system-library
patching. This approval does not claim that the binary distribution is
installed, locked, or production-ready, and it does not change the approved
`psycopg[binary]==3.3.4` pin or driver mode.
The self-contained, best-effort-wheel, and local-installation distinctions are
documented in the
[official Psycopg installation guidance](https://www.psycopg.org/psycopg3/docs/basic/install.html).

The authorization approves exact direct pins only. It does not pre-approve
resolved transitive versions, hashes, optional extras beyond
`psycopg[binary]`, or future upgrades. The future lock review must demonstrate
that the complete graph is compatible with Python 3.12.13 and contains no
unreviewed direct capability.

### 16. Dependency authorization rule

The Project Owner approved the exact direct pins, types, licenses, transitive
surface, compatibility evidence, security caveats, and version-selection
rationale in the effective authorization record.

Each pin may be added only in its first requiring focused work item. No
dependency installation, synchronization, `pyproject.toml` change, `uv.lock`
change, production-package import, or business implementation is authorized on
the unmerged `M1A-001A` governance branch. After this governance package is
merged, only `M1A-001B` may begin; its dependency/lock proposal remains subject
to the saved graph, license, vulnerability, compatibility, and focused-review
requirements in this ADR.

Every later direct dependency addition, optional extra, or version change
requires separate Project Owner authorization. A future vulnerability finding
does not authorize a silent upgrade; it triggers a focused security decision
and, when necessary, an emergency owner authorization.

## Alternatives considered

- Implement all of M1A in one PR.
- Return HTTPX, SQLAlchemy, Psycopg, or FastAPI-native objects across layers.
- Use generic dictionaries as source records, outcomes, citations, or reports.
- Store raw PubMed response payloads in PostgreSQL columns.
- Use asynchronous HTTP and database stacks in the first slice.
- Parse untrusted PubMed XML with the standard library alone.
- Use byte, UTF-16, sentence, token, or rendered-page citation offsets.
- Generate or paraphrase claims with an LLM in M1A.
- Add Uvicorn and FastAPI optional extras implicitly.
- Run live PubMed tests in default CI.

## Consequences

- M1A has a reviewable implementation sequence and cannot become a broad
  multi-source or RAG refactor.
- Domain, evidence, citation, and failure semantics can be tested before
  external I/O.
- Exact citations remain stable only for the exact canonical abstract version;
  source drift correctly invalidates them.
- Raw bytes remain replayable while PostgreSQL holds authoritative metadata.
- The synchronous stack reduces first-slice operational complexity.
- Direct pins are reproducible, but the complete resolved graph still requires
  an approved lock and vulnerability/license review.
- `defusedxml` reduces XML risk but carries a stale-classifier compatibility
  caveat.
- Psycopg's binary extra improves local Windows portability, but bundled
  `libpq`, `libssl`, and other native libraries require inventory,
  advisory-monitoring, and patch ownership; production deployment suitability
  remains unapproved.
- FastAPI 0.140.0 has limited release soak time, which the Project Owner
  explicitly accepted for the bounded M1A scope.
- M1A has no formal export or model-generated synthesis and cannot be presented
  as a complete V1 system.

## Validation

The independent governance review returned PASS and the Project Owner resolved
all decision items required for effectiveness. After merge, the focused work
items must demonstrate:

- reference and second synthetic scopes follow the same path;
- all seven valid source outcomes pass and all eleven invalid combinations
  fail in deterministic tests;
- skipped sources produce no `SourceOutcome`;
- exact citations fail on any quote, offset, PMID, version, hash, publication
  status, relationship, warning, or status-provenance drift;
- a missing/invalid abstract produces no claim;
- snapshot and canonical manifest replay verifies hashes and identities;
- unavailable acquisition preserves typed failure provenance without a source
  record;
- PostgreSQL constraints reject invalid terminal outcomes;
- API routes call only tools/application services and return `draft`;
- default unit/contract tests remain offline with sockets disabled;
- the live test cannot run without the marker selection and environment opt-in;
- the live test is limited to one page and one record; and
- saved acceptance evidence records query, UTC time, code revision, outcome,
  and snapshot/manifest identity.

Future deterministic publication-status acceptance requirements are:

1. `PS-01`: a current record with no known notice validates with
   `current_or_no_known_notice` and its as-of provenance;
2. `PS-02`: a corrected record resolves and discloses its related notice;
3. `PS-03`: a retracted record is rejected as affirmative material support;
4. `PS-04`: a retracted record is permitted only for explicit retraction,
   correction-history, or source-status context;
5. `PS-05`: an expression-of-concern warning is surfaced in both claim and
   report with `support_limited` or source-status context;
6. `PS-06`: a missing required publication-status warning is rejected;
7. `PS-07`: a status mismatch between `PublicationRecord` and citation is
   rejected;
8. `PS-08`: a changed related PMID, notice identity, or status provenance is
   rejected;
9. `PS-09`: unknown or unverified publication status is disclosed and is not
   treated as current; and
10. `PS-10`: report and API serialization preserve every required status
    identity, warning, warning reference, notice relationship, and disclosure.

These are governance acceptance requirements for future focused work items;
this decision adds no tests or implementation.

No quality, safety, latency, or reliability claim may be made until its raw,
reproducible evidence exists.

## Supersedes / Superseded by

This ADR refines ADR-003, ADR-007, and ADR-008 for the bounded M1A PubMed slice.
It does not supersede them.
