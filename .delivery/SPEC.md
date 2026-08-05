# Task specification: M1A-001B remediation and M1A-002 bounded PubMed connector

Updated: `2026-08-05`

## 1. Source material and authority

- Complete Owner task: session attachment `pasted-text.txt`, SHA-256
  `9778d890a62c35c54db9b2241ebea7ddfd665992ca18b6e2b28688128e71bb7a`
- Repository instructions: `AGENTS.md` and
  `src/medevidence/connectors/AGENTS.md`
- Governing product and safety records: `docs/PRD.md`,
  `docs/ARCHITECTURE.md`, `docs/TRACEABILITY_MATRIX.md`,
  `docs/DATA_SOURCES.md`, `docs/EVALUATION_PLAN.md`, and
  `docs/SECURITY.md`
- Governing decisions and authorization: ADR-002, ADR-007, ADR-008,
  ADR-009, and the M1A-001A review/authorization package
- No diagram or screenshot was attached. Textual architecture diagrams in the
  repository remain governing design evidence.

The 2026-08-05 Owner task is the latest explicit authorization. For this task
only, it supersedes older records that required a separate branch and merge
between M1A-001B and M1A-002: one clean-main feature branch and two separate
local commits are authorized. It does not authorize a push, pull request,
merge, live PubMed request, or any later M1A work item.

The repository requires a fixed official NCBI E-utilities HTTPS host but did
not contain its literal name. First-party NCBI E-utilities documentation
identifies the shared base URL as
`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`. This establishes the exact
host and the ESearch/EFetch path prefix without making an API request.

## 2. Explicit requirements

| ID | Requirement | Source | Priority |
|---|---|---|---|
| R1 | A report accepts an in-scope mixture of executable and currently non-executable sources only when every `ResearchScope.selected_sources` member has exactly one plan entry. Missing, duplicate, and out-of-scope entries are rejected. | Owner frozen M1A-001B decision | Must |
| R2 | An in-scope source may be `selected` or `skipped_by_policy`. A skipped source remains visible with a machine-readable and human-readable reason and can never have a fabricated `SourceOutcome`. | Owner frozen M1A-001B decision | Must |
| R3 | Selected, unattempted, executed, completed, failed, partial, and skipped states remain distinct. Existing bounds, provenance, outcome-triple, canonical-order, identity, and source-neutrality invariants remain strict. | Owner frozen M1A-001B decision; ADR-007/009 | Must |
| R4 | PubMed HTTP behavior is synchronous, explicit, transport-injected, HTTPS-only, fixed-origin/fixed-path constrained, and manually validates every redirect hop and final URL. It rejects arbitrary URLs, wildcard hosts, lookalikes, suffix confusion, userinfo, non-HTTPS, and unapproved ports/paths. | Owner M1A-002 network policy; Security Sections 5-6 | Must |
| R5 | Search and fetch have finite configuration for query length, page size, pages, records, payload bytes, connect/read/write/pool timeout, total deadline, attempts, exponential backoff, bounded jitter, maximum delay, `Retry-After`, and redirects. No connector cache exists in M1A-002. | Owner bounded-behavior list; root/connector instructions | Must |
| R6 | Search/fetch distinguish complete matches, exhaustive empty success, bounded truncation, successful partial parsing, failed partial retrieval, and unavailable failure. Stable first-seen PMID deduplication and earlier-page retention are deterministic. Incomplete coverage never becomes `no_match`. | Owner classification and partial-result requirements; source-outcome contract | Must |
| R7 | Connector-local typed failures distinguish rate limit, ordinary client error, eligible retryable server error, retry exhaustion, other server error, timeout, transport failure, invalid XML, semantically incomplete XML, payload overflow, redirect rejection, and internal contract violation. Only HTTP 429 and explicitly eligible 5xx responses retry. | Owner classification/retry requirements | Must |
| R8 | Untrusted PubMed XML is parsed with the approved lightweight hardened parser. Invalid XML, semantically incomplete documents, and malformed individual records remain distinct; valid records from a partially malformed response are retained with partial coverage. | ADR-009 dependency/parser decision; Owner XML requirements | Must |
| R9 | All automated tests use `httpx.MockTransport`, run with sockets disabled, and prove there is no implicit path from an injected/mock connector to a real transport. No live PubMed/NCBI API call occurs. | Owner offline policy; V1-NFR-004 | Must |
| R10 | Each work item passes focused and full offline validation, independent diff review, bounded remediation, terminal audit, and a separate local commit. Final state is clean and identifies exact commits. | Owner execution/completion/Git policy | Must |

## 3. Observable behavior

| ID | Input or action | Expected output or state | Error and boundary behavior |
|---|---|---|---|
| R1-R3 | A scope containing PubMed and CADEC, with PubMed selected and CADEC skipped by policy | Immutable draft report retains both plan entries and only the PubMed outcome | Missing/duplicate entries and any CADEC outcome fail validation |
| R4 | A fixed ESearch/EFetch request through an injected transport | Request URL is exact-origin HTTPS with an approved path | Any redirect or final URL outside the exact origin/path policy fails before another request |
| R5-R7 | A bounded search/fetch under success, 429, eligible 5xx, 4xx, timeout, or transport failure | Finite calls, delays, payload, pages, records, and typed terminal result | Retry budget/deadline exhaustion is explicit; ordinary 4xx is never retried |
| R6 | A later page/batch fails after earlier valid records | Earlier records remain and the terminal outcome is failed/partial, never complete | Zero retained results are indeterminate; retained results remain partial matches |
| R8 | XML bytes are valid, invalid, incomplete, or contain malformed records | Deterministic typed parse result or failure | DTD/entities and syntactically invalid XML fail closed; mixed valid/malformed records are partial |
| R9 | Default unit/contract command with `--disable-socket` | All tests pass with `MockTransport`; zero live calls | Constructor requires a transport and has no implicit real-network default |

## 4. Interfaces and data

### Existing compatibility-sensitive domain interfaces

- `ResearchScope.selected_sources` remains the serialized in-scope/requested
  source tuple. It is not renamed.
- `SourcePlanEntry`, `PlanningStatus`, `SourcePlanReasonCode`, and
  `SourceOutcome` retain schema version `1.0` and their existing fields/enums.
- The seven valid `SourceOutcome` triples remain unchanged.
- Domain code continues to import only the standard library, Pydantic, and
  intra-domain modules.

### New connector-local interfaces

- `PubMedConnectorConfig`: immutable finite transport, pagination, payload,
  deadline, retry, redirect, and no-cache policy.
- `PubMedConnector`: requires an injected `httpx.BaseTransport`; an explicitly
  named production factory is the only code path that creates
  `httpx.HTTPTransport`.
- `PubMedSearchResult` and `PubMedFetchResult`: typed connector results carrying
  source-neutral `SourceOutcome`, connector-local state/failure details, raw
  response bytes for later snapshot work, warnings, and retry/page metadata.
- `PubMedArticle`: provider-specific parsed record DTO. HTTPX objects never
  cross the connector boundary.
- Fixed endpoints:
  `/entrez/eutils/esearch.fcgi` and
  `/entrez/eutils/efetch.fcgi` on exact host
  `eutils.ncbi.nlm.nih.gov`.

### State transitions

```text
requested source -> exactly one selected or skipped_by_policy plan entry
selected -> not started (no outcome) -> attempted -> one immutable terminal outcome
skipped_by_policy -> no execution -> no outcome

HTTP attempt -> success
             -> eligible 429/5xx -> bounded delay -> retry or exhausted
             -> permanent HTTP/transport/XML/policy failure

complete source -> complete matches or complete no_match
bounded stop    -> succeeded partial matches/indeterminate
later failure   -> failed partial matches/indeterminate
initial failure -> failed unavailable indeterminate
```

## 5. Acceptance and test coverage

| Requirement | Existing/provided evidence | Additional verification required |
|---|---|---|
| R1-R3 | Domain outcome/provenance/report suites; current mixed-plan rejection reproduces the defect | Positive mixed selected/skipped report; missing plan; duplicate plan; out-of-scope plan; skipped-not-applicable in-scope; fabricated skipped outcome |
| R4 | Generic socket-blocking contract only | Allowed same-origin redirect; cross-origin/downgrade/path/port/userinfo/trailing-dot/lookalike/suffix rejection; final URL check |
| R5 | Domain numeric bound tests only | Exact/min/max configuration; page/record/payload/deadline/attempt/delay/redirect enforcement |
| R6 | Domain terminal-triple and limitation tests | One/multi-page, empty, both truncations, duplicates, inconsistent counts, later-page partial, fetch partial/missing records |
| R7 | Source-neutral failure tests only | 429 with/without `Retry-After`, eligible 5xx recovery/exhaustion, ordinary 4xx, timeout, connection failure, internal contract error |
| R8 | Constructed publication contract tests only | Valid search/fetch fixtures, missing elements, invalid XML, DTD/entity rejection, malformed record retention |
| R9 | `tests/contract/test_offline_network.py` | Required transport/no fallback assertion plus full suite with `--disable-socket` |
| R10 | Authoritative repository commands | Focused tests, full four-command gate, dependency/architecture checks, final-audit helper, independent reviewers, clean post-commit status |

The Owner-mandated M1A-002 matrix includes at minimum: one-page success,
multi-page success, empty result, page truncation, record truncation, duplicate
PMIDs, missing XML elements, invalid XML, inconsistent count, 429 with and
without `Retry-After`, eligible 5xx then success, exhausted 5xx, ordinary 4xx,
connection failure, timeout, later-page partial, allowed redirect, disallowed
redirect, lookalike rejection, and proof that real network access cannot occur
in tests.

## 6. Non-functional requirements

- Python 3.12.13, strict mypy, Ruff, immutable typed contracts, UTC timestamps.
- Query/pagination/retry/payload/time behavior is finite under every path.
- No secrets, response payloads, or personal client-identification values are
  logged or committed.
- No live source call, hidden network fallback, unbounded accumulation, or
  provider-native object crosses the connector boundary.
- Cache policy is explicitly `none` for M1A-002. Immutable snapshots and cache
  persistence remain M1A-003A work.
- Quality/latency/reliability claims require saved evidence; this task reports
  only commands actually run.

## 7. Non-goals

- Live PubMed execution or live acceptance evidence.
- Snapshot/manifest persistence, PostgreSQL, application tools, claims/report
  construction beyond the frozen M1A-001B remediation, FastAPI, or composition
  root.
- DailyMed, FAERS/openFDA, CADEC execution, retrieval/RAG, Qdrant, LangGraph,
  LLMs, Streamlit, MCP, export/HITL, external tracing, or unrelated refactors.
- Tenacity: the bounded explicit loop is clearer and avoids an unnecessary
  direct dependency.
- Standard-library-only XML parsing: ADR-009 records that it is insufficient
  for untrusted XML and approves lightweight `defusedxml==0.7.1`.

## 8. Assumptions and resolved decisions

| Decision | Basis | Verification |
|---|---|---|
| The new Owner task supersedes the old inter-item branch/merge gate for this task only | It explicitly orders M1A-002 after the local remediation commit and authorizes one feature branch/two commits | Preserve separate commits; do not push/merge |
| Exact NCBI host is `eutils.ncbi.nlm.nih.gov` | First-party NCBI E-utilities Quick Start documents the shared base URL | Fixed constant plus exact-origin tests |
| Stable first-seen deduplication | Preserves upstream order and does not fabricate records | Cross-page duplicate tests |
| Same exact host and approved ESearch/EFetch paths are the only redirect targets | Smallest SSRF-safe interpretation of the Owner policy | Redirect/path/lookalike tests |
| Retryable 5xx set is 500, 502, 503, and 504 | Conventional transient set; narrow and reversible | Retry/no-retry request-count tests |
| Numeric defaults live in connector configuration and remain within existing domain maxima | No durable domain-schema change is needed | Configuration boundary tests and exact `SourceOutcome.configured_bounds` |
| Package resolution/install for the approved exact pins is authorized as a normal implementation step | The task authorizes dependency and lock changes required by M1A-002 | Record exact graph change and audit; stop if an unapproved dependency appears |

## 9. Approved design summary

- Current flow:
  `ResearchScope -> SourcePlanEntry -> SourceOutcome -> Provenance ->
  PublicationRecord -> ResearchReport`.
- M1A-001B slice: replace only the aggregate's blanket selected-only rule with
  the frozen selected-or-skipped-by-policy rule; retain all existing plan-set,
  outcome, bounds, evidence, warning, limitation, ordering, and identity checks.
- M1A-002 slice:
  `typed config -> fixed request builder -> injected HTTPX transport ->
  exact URL/redirect policy -> bounded retry/deadline/payload reader ->
  hardened XML parser -> deterministic aggregation -> connector-local typed
  result + source-neutral SourceOutcome`.
- Expected modification surface is limited to `.delivery`, the report
  aggregate/tests/status text for M1A-001B, then approved dependency metadata,
  connector package, PubMed unit/contract fixtures/tests, dependency-boundary
  checks, dependency-audit candidate binding, and accurate status text for
  M1A-002.
- Rejected complex alternative: a generic multi-provider HTTP framework with
  Tenacity and pluggable URL routing. It adds abstractions and dependency
  surface without improving the fixed-host single-provider acceptance path.

There are no unresolved implementation questions that require Owner input at
the start of M1A-001B.
