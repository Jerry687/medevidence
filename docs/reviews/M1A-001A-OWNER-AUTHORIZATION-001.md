# M1A-001A Project Owner Decision and Authorization Package

- Authorization reference: M1A-001A-OWNER-AUTHORIZATION-001
- Decision owner: Boqi Niu
- Authorization role: Project Owner
- Prepared date: 2026-07-26
- Effective authorization date: 2026-07-26
- Status: **APPROVED AND EFFECTIVE — M1A-001B AUTHORIZED AFTER MERGE**
- Revision: 2
- Unresolved owner decisions: 0
- Governing accepted decision:
  [ADR-009](../decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md)
- Independent governance review:
  [M1A-001A-INDEPENDENT-REVIEW-001](M1A-001A-INDEPENDENT-REVIEW-001.md)
- Required future review: Focused independent review of each implementation
  work item before merge

## Purpose and present effect

This package records the Project Owner decisions required to transition from
completed Phase 0 and `ME-000A` into the bounded M1A PubMed vertical slice.

This authorization is effective for the governance and dependency decisions
recorded here. It approves ADR-009 Revision 2 and the exact direct dependency
pins, boundaries, and sequential workflow defined there. It does not authorize
installation, synchronization, a lock-file change, or MedEvidence business
implementation on this unmerged governance branch.

After this package is merged into `main`, only `M1A-001B` may begin from that
approved baseline. `M1A-002` through `M1A-005` remain unauthorized until each
preceding focused work item is approved and merged. The live PubMed acceptance
query remains separately unauthorized.

## Immutable approved baseline

This package is bound exclusively to:

- approved M0 tag: `m0-approved-v1`;
- final audited ME-000A implementation:
  `c6384c766d0e65240ba617d9b78f17dd7f500260`;
- approved ME-000A `main` merge commit:
  `540420d437ff7306f4c53dc784ccf8ec5ced9e1d`; and
- approved ME-000A tag: `me-000a-approved-v1`, resolving to the same merge
  commit.

The M0 and ME-000A review, approval, audit, manifest, commit, and tag records
remain historical artifacts. This package neither rewrites them nor represents
the current descendant as byte-identical to the frozen M0 corpus.

## Approved phase transition

M1A is authorized only as this sequential work-item series:

1. `M1A-001A` — decision and dependency gate;
2. `M1A-001B` — source-neutral domain contracts;
3. `M1A-002` — bounded PubMed connector;
4. `M1A-003A` — immutable snapshots and manifests;
5. `M1A-003B` — PostgreSQL snapshot metadata;
6. `M1A-004` — PubMed tools, claims, citations, and draft report;
7. `M1A-005` — FastAPI and M1A acceptance evidence.

Every work item after `M1A-001A` must use a separate branch and focused Draft
PR created from the latest approved `main` baseline. A work item may begin only
after its prerequisite work is approved and merged. No monolithic M1A
implementation PR is authorized.

## Approved M1A scope

This authorization approves only:

- typed source-neutral domain contracts;
- PubMed search and record retrieval;
- deterministic offline fixtures;
- immutable raw snapshots and manifests;
- PostgreSQL snapshot metadata;
- stable PubMed application tools;
- deterministic attributed extracts and exact abstract-span citations;
- structured non-exportable `draft` reports;
- FastAPI transport; and
- one separately opt-in bounded live PubMed smoke query.

The following remain excluded:

- DailyMed;
- FAERS/openFDA;
- CADEC implementation;
- Qdrant indexing or retrieval;
- BM25, dense retrieval, RRF, and reranking;
- LangGraph;
- LLM integration;
- `ME-000B` implementation;
- Streamlit;
- MCP;
- export and HITL;
- external tracing; and
- unrelated refactoring.

`ME-000B` remains deferred because M1A claim construction is deterministic and
extractive rather than model-generated.

## Approved direct dependency authorization

The exact approved direct-pin table is:

| Direct pin | First requiring work item | Class |
|---|---|---|
| `pydantic==2.13.4` | `M1A-001B` | Production |
| `httpx==0.28.1` | `M1A-002` | Production |
| `tenacity==9.1.4` | `M1A-002` | Production |
| `defusedxml==0.7.1` | `M1A-002` | Production |
| `sqlalchemy==2.0.51` | `M1A-003B` | Production |
| `alembic==1.18.5` | `M1A-003B` | Production tooling |
| `psycopg[binary]==3.3.4` | `M1A-003B` | Production |
| `fastapi==0.140.0` | `M1A-005` | Production |
| `pip-audit==2.10.1` | `M1A-001B` | Development |

ADR-009 Section 15 is the authoritative review table for purpose, Python
3.12.13 compatibility, license, direct security status, major transitive
dependencies, selection rationale, and caveats.

This authorization approves the exact direct pins only, and only for addition
when the first requiring focused work item begins. It does not pre-approve
resolved transitive versions, hashes, additional extras, later direct
dependencies, or version changes.

The first future dependency/lock PR must:

- contain no direct dependency outside the approved table;
- save the resolved dependency graph and license inventory;
- run and save a known-vulnerability audit of the resolved lock;
- verify Python 3.12.13 compatibility;
- test `defusedxml` on Python 3.12.13;
- inventory bundled `libpq`, `libssl`, and other native-library versions in
  `psycopg-binary`;
- assign advisory-monitoring and patch ownership for those native libraries;
- verify that the required platform-specific binary wheel is available;
- complete focused PostgreSQL integration validation for local Windows use;
- contain no FastAPI optional extras; and
- receive focused owner review before merge.

The approved `psycopg[binary]==3.3.4` direct pin is self-contained and
bundles native client libraries. Those bundled libraries create inventory,
advisory-monitoring, and patch-ownership obligations separate from the Python
package, and binary-wheel availability is platform-dependent and best-effort.
Local Windows development may use the binary extra only after the reviews and
validation above. Production suitability must be reassessed; a locally linked
or source-built deployment may be preferable in a controlled production
environment. This authorization does not represent the binary distribution as
installed, locked, or production-ready.

## Live-query authorization boundary

The only current live-query candidate is:

```text
semaglutide[Title/Abstract] AND gastrointestinal[Title/Abstract]
```

Any future authorization would require all of the following:

- explicit `live_api` marker selection;
- `MEDEVIDENCE_RUN_LIVE_PUBMED=1`;
- fixed NCBI E-utilities HTTPS host and approved search/fetch paths;
- `tool=medevidence` and an owner-supplied `NCBI_EMAIL`;
- no arbitrary endpoint, URL, query, or record identifier;
- at most one page and at most one record;
- no default-CI execution; and
- saved evidence containing the query, UTC time, code revision, terminal
  outcome, and snapshot/manifest identities.

The Project Owner approved the retention and disposition policy below but did
not authorize live execution. The exact query, NCBI client-identification
values, execution time, and final acceptance command require a later focused
Owner approval before `M1A-005` executes any live request. Default CI remains
fully offline.

## Approved live-query artifact retention and disposition

The policy identifier is `M1A-LIVE-RETENTION-v1`.

| Artifact class | Approved storage | Approved retention |
|---|---|---|
| Raw live PubMed response snapshots | Configured local immutable snapshot root outside Git | Through the complete V1 development and acceptance lifecycle; no automatic deletion |
| Snapshot manifests | With immutable snapshot artifacts outside Git | Indefinitely as integrity and replay records |
| Normalized `PublicationRecord` artifacts | Approved local artifact location outside Git | Through the V1 development and acceptance lifecycle |
| PostgreSQL snapshot, run, provenance, and artifact metadata | PostgreSQL | Indefinitely unless a later Owner-approved migration or retention decision changes the policy |
| Live-query command and run metadata | PostgreSQL and approved redacted acceptance evidence | Indefinitely |
| Acceptance evidence and result summaries | Small redacted summaries under `docs/reviews`; full approved evidence outside Git as applicable | Indefinitely |
| Approved redacted operational logs | Approved operational log location outside Git | 90 days |

Raw live responses must not be committed to Git unless separately sanitized,
reviewed, licensed, bounded, and explicitly approved. Raw payload bytes remain
outside PostgreSQL columns. A committed acceptance summary contains no raw
abstract body, credential, header, secret, or unredacted upstream payload.

Snapshot manifests are immutable and are never overwritten or silently
replaced. Normalized records preserve schema version, source snapshot
identity, and content hash; a newer normalized version supplements rather than
overwrites an earlier version. Deletion of PostgreSQL metadata preserves an
auditable tombstone or disposition record.

When any raw response bytes arrive before a failed, unavailable, or partial
terminal outcome, those exact bytes and their manifest remain under the same
immutable snapshot policy. A completely unavailable attempt with no raw bytes
may retain only typed failure/run metadata and a zero-file manifest. Failure
metadata remains redacted and cannot fabricate a successful
`PublicationRecord`.

Identical raw bytes reuse the existing content-addressed snapshot. Every
research or acceptance run retains its own run identity, query, timestamp,
code revision, connector version, outcome, and snapshot-hash reference.
Duplicate runs create neither duplicate raw files nor overwritten run
metadata.

New runs supplement rather than replace prior runs. An artifact may be marked
superseded but remains traceable. Corrupt or invalid artifacts are quarantined
or marked invalid and cannot be silently deleted or reused. Deletion requires
explicit Project Owner authorization and a disposition record containing the
artifact identity, reason, UTC time, and approving authority.

Manifests, live-query run metadata, and acceptance evidence persist the
`M1A-LIVE-RETENTION-v1` identifier. Ordinary logs remain outside Git and
contain no raw abstract text, credentials, authorization headers, connection
strings, or complete upstream responses. Audit identities and result summaries
required for approved acceptance evidence remain preserved separately from
expiring logs.

## Owner decisions resolved

The Project Owner resolves all 16 items as follows:

1. **Accepted:** ADR-009 package boundaries and dependency direction.
2. **Accepted:** schema version `1.0`, strict validation, immutability, UTC
   serialization, and serialized-change approval policy.
3. **Accepted:** the `ResearchScope` fields; exact ordinary query, page,
   record, payload-byte, and total-time bounds remain for focused
   `M1A-001B`/`M1A-002` review.
4. **Accepted:** the exact seven valid and eleven invalid terminal
   source-outcome combinations and future database enforcement.
5. **Accepted:** `PublicationRecord` canonical abstract, content/version
   identity, typed publication status, provenance, related-notice metadata,
   warning codes, disclosure, and status identity.
6. **Accepted:** Unicode code-point half-open abstract offsets,
   exact-quote/hash/version drift validation, status-bound citations, and
   no-valid-span/no-claim policy.
7. **Accepted:** deterministic attributed extracts, all publication-status use
   restrictions, report/API warning preservation, and continued deferral of
   `ME-000B`.
8. **Accepted:** exact response-body snapshots, canonical JSON manifests,
   content-addressed paths, atomic immutable writes, replay checks, and
   unavailable-attempt provenance.
9. **Accepted:** PostgreSQL metadata authority, raw files outside database
   columns, and synchronous SQLAlchemy/Psycopg; exact DDL remains reserved for
   `M1A-003B`.
10. **Accepted:** `/v1/`, transport-only FastAPI, draft-only reports, and
    focused request/response/error review before `M1A-005`.
11. **Accepted with recorded risks:** all nine direct dependency pins and
    classes, including FastAPI's limited soak time, the `defusedxml`
    classifier gap, all Psycopg binary/native-library obligations, and the
    networked development-only role of `pip-audit`.
12. **Resolved — not authorized:** M1A has no standalone ASGI server
    dependency. `M1A-005` may use an in-process ASGI test client; Uvicorn or
    another server requires a later explicit Owner decision.
13. **Resolved — live execution deferred:** the displayed PubMed query remains
    the sole candidate, but the exact query, NCBI client-identification values,
    execution time, and final acceptance command require focused Owner
    approval before any `M1A-005` live request.
14. **Accepted:** the artifact retention and disposition policy
    `M1A-LIVE-RETENTION-v1` recorded above.
15. **Confirmed:** every later work item uses a separate branch, sequential
    focused Draft PR, independent review, and Project Owner approval.
16. **Approved:** this package is effective on 2026-07-26 with the post-merge
    authorization boundary stated below.

## Effectiveness conditions satisfied

The Project Owner:

1. resolved all 16 items;
2. accepted ADR-009 Revision 2;
3. confirmed the exact nine-row dependency table;
4. recorded the effective date, status, approver, and accepted ADR revision;
5. explicitly recorded the deferred live execution and standalone-server
   decisions; and
6. authorized only the next sequential work item, `M1A-001B`, after this
   governance package is merged into `main`.

Even after this package becomes effective, later work items do not receive
blanket merge approval. Each remains subject to focused implementation,
tests, validation, independent review, and Project Owner approval.

## Candidate binding

The independent review record binds this effective uncommitted governance
candidate through per-file SHA-256 values for exactly:

- `AGENTS.md`;
- `README.md`;
- `docs/decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md`;
- `docs/decisions/README.md`; and
- this authorization record.

The independent review record excludes itself from that five-file hash set to
avoid self-reference. No committed candidate SHA exists yet because this
authorization does not permit an automatic commit. Before any Git write, the
five hashes must be reverified. After an intentional candidate commit, that
commit SHA becomes the immutable Git identity used by the subsequent
review/approval and merge workflow.

## Current decision

**APPROVED AND EFFECTIVE — M1A-001B AUTHORIZED AFTER MERGE**

No business code, dependency installation or synchronization,
`pyproject.toml` change, `uv.lock` change, migration, fixture, test, workflow,
container change, or live external request is authorized on this unmerged
governance branch. Once the exact governance candidate is approved and merged,
only a new focused `M1A-001B` branch may begin from the resulting approved
`main` baseline.
