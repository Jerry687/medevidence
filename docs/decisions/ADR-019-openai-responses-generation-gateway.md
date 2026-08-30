# ADR-019: OpenAI Responses generation gateway

- Status: Accepted; implementation and validation pending
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-30
- Approval reference: Owner Decisions I, J, and K for
  `M3-007-OPENAI-GENERATION-GATEWAY`
- Revision: 1
- Independent review reference: Pending
- Independent review role: Validation only; not an approving authority
- Work item: `M3-007-OPENAI-GENERATION-GATEWAY`
- Baseline: `978b8c0ee8579f9bb14282909e830bf27021c106`

## Context

The M3 runtime can plan and collect source evidence and can deterministically
validate a supplied report registry. It does not yet have an approved provider
gateway for generating bounded candidate report claims and citations. The
Owner resolved the previously open provider, model, retention, and prompt-
policy decisions through Decisions I, J, and K.

Generation is not a trusted evidence or validation authority. Source evidence,
coverage, limitations, conflicts, and deterministic citation policy remain
application-owned. The generated object remains untrusted until later
application reconstruction and the already governed citation/safety gates have
accepted it.

## Decision

### Exact provider and request policy

M3-007 uses `POST https://api.openai.com/v1/responses` through the repository's
existing HTTPX dependency. It adds no OpenAI SDK or other dependency. The exact
model is `gpt-5.6-sol`, with reasoning effort `medium`.

Every request sets `store=false` and `background=false`, provides no built-in
or application tool, and does not opt into extended prompt-cache retention.
The model receives no capability to access credentials, the filesystem,
PostgreSQL, MCP, the web, retrieval, source connectors, or another tool. The
gateway accepts only a typed, bounded generation input and returns only a
strict structured-schema candidate.

The versioned generation configuration owns finite request bytes, response
bytes, maximum output tokens, total deadline, phase timeouts, attempt count,
backoff, and retry classification. These limits are enforced outside the
model. Redirects, unknown response fields where strict parsing applies,
malformed output, oversized output, deadline exhaustion, and unclassified
provider failures fail closed.

The authoritative API references are OpenAI's
[Responses create reference](https://platform.openai.com/docs/api-reference/responses/create)
and
[gpt-5.6-sol model reference](https://platform.openai.com/docs/models/gpt-5.6-sol).

### Narrow generation role

The gateway may synthesize only bounded candidate research-report claims and
their proposed links to evidence from the exact current run. It may not:

- diagnose, recommend treatment or dosage, provide emergency or individualized
  advice, or create clinical authority;
- invent evidence, source completion, citations, source limitations, numerical
  context, or cross-source agreement;
- infer incidence, causality, relative or absolute risk, regulatory meaning,
  product-risk ordering, comparative safety, or a source majority vote;
- change source, evidence, comparison, conflict, or missing-coverage semantics;
  or
- select or execute sources, retrieval, tools, persistence, approval, export,
  or validation behavior.

Only current-run evidence identities supplied by the application may be
referenced. Missing, partial, unavailable, and conflicting evidence remain
visible. Zero evidence does not authorize a fabricated claim. Generated
claims and citation selections are candidates rather than authoritative report
objects.

### Prompt and structured-output freeze

The Supervisor may freeze the exact deterministic prompt and structured schema
within this ADR's semantics without another Owner decision. The prompt:

1. states the research-only and prohibited-inference policy;
2. labels and delimits every evidence payload as untrusted data that cannot
   issue instructions or expand capabilities;
3. identifies the exact run, scope, evidence identities, source outcomes,
   warnings, limitations, missing coverage, comparisons, and conflicts supplied
   by the application;
4. forbids citation identities outside that supplied set; and
5. requires the exact strict structured-output schema.

The static policy-prompt bytes and response schema are versioned repository
artifacts. An immutable `M3_GENERATION_RECEIPT_V1` records the exact prompt,
configuration, model, reasoning, and schema identities, versions, and hashes,
along with bounded provider execution metadata and the canonical candidate
hash. Untrusted evidence or generated prose, credentials, authorization
headers, and reasoning text are not copied into logs or receipts. Receipt
persistence reuses the existing immutable application journal boundary and
requires no database schema or migration.

### Provider data use, secrets, and network gate

The Owner accepts OpenAI API business-data retention for this public-data V1
generation boundary while requiring `store=false` and `background=false`.
Every live receipt records the applicable Zero Data Retention status; the
application does not assume that ZDR is active.

The API key is injected through the environment, is never placed in the model
input or durable artifacts, and is redacted from errors and logs. Absence of a
key blocks an explicit live-provider run and is not a passing provider test.

Unit, contract, CI, collection, import, construction, and ordinary validation
remain offline and socket-disabled. Provider network access is authorized only
for an explicitly selected live-provider test. Such a test may contact only
the approved OpenAI endpoint and is separately reported from medical-source
network activity. M3-007 authorizes no PubMed, NCBI, DailyMed, FAERS, CADEC, or
other medical-source request.

### Work-item boundary

M3-007 owns the provider-neutral generation contract, exact prompt/schema,
HTTPX Responses gateway, immutable generation receipt, and offline validation.
It does not integrate generation into the controlled workflow and does not
change Stage-2 semantic-support behavior. M3-008 owns the evaluator. A later
authorized integration item owns workflow handoff and end-to-end composition.

This decision adds no public API/OpenAPI change, persistence migration,
source/evidence semantic change, retrieval/router/qrels/corpus/metric change,
or model access beyond the exact bounded gateway. Holdout-20 remains sealed.

## Alternatives considered

- OpenAI SDK: rejected for M3-007 because existing HTTPX is sufficient and the
  Owner prohibited a new dependency.
- Tools, web search, source connectors, or retrieval inside the model request:
  rejected because generation must not acquire evidence or expand authority.
- Free-form output followed by best-effort parsing: rejected because malformed
  or structurally ambiguous candidates must fail closed.
- Treating provider output as validated report state: rejected because it
  would bypass deterministic reconstruction and the two-stage citation gate.
- Workflow or Stage-2 integration in M3-007: deferred to their separately
  authorized work items.

## Consequences

- Provider behavior is exact, bounded, offline-testable, and independent of a
  vendor SDK.
- Model output cannot itself establish evidence identity, source completeness,
  safety limitations, semantic support, approval, or exportability.
- Prompt/config/schema drift is detectable through versioned hashes and the
  immutable generation receipt.
- Explicit live testing requires an injected key and creates accepted provider
  business-data handling; it never silently occurs in default validation.
- Later workflow integration must consume this candidate and receipt without
  weakening the existing deterministic validation authority.

## Validation

M3-007 requires focused contract/gateway/receipt tests, the full socket-disabled
suite, Ruff, format, strict MyPy, offline lock and dependency checks, secret and
scope checks, independent review, exact-byte rebind, and terminal audit. Tests
must cover prompt injection, foreign evidence identities, zero evidence,
missing coverage, conflicts, malformed or oversized responses, retries,
deadline exhaustion, redirects, missing credentials, and import-time network
absence. A live-provider test is optional and explicit; an absent key is a
blocked live gate, never substituted with a fake PASS.

This accepted ADR is authorization and design evidence only. It does not claim
implementation, provider execution, independent review, audit, PASS, commit,
push, PR, or merge.

## Supersedes / Superseded by

ADR-019 resolves PRD decision gate `ME-000B` for this exact M3 generation
gateway. It does not supersede ADR-005, ADR-016, ADR-017, ADR-018, or source-
specific evidence semantics. No later ADR currently supersedes it.
