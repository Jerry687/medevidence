# Security, Medical Safety, and Trust Boundaries

## FAERS-001 closed trust metadata

`FAERS_M1B_CONSTRAINED_V1` is a frozen, non-weakenable design tuple, not network
permission. Validation hosts remain empty and source network execution is false.
It fixes HTTPS host/path/method, zero redirects, count field, phase/deadline
timeouts, two attempts, retry classes, bounded backoff/Retry-After, five pages,
100 records/buckets, and 5,242,880-byte response/cumulative ceilings. Result
caching and stale fallback are forbidden; replay is immutable raw snapshot only.
Arbitrary query syntax, pre-encoded input, raw mode, role predicates, and any
weakened policy values fail closed.

## 1. V1 boundary

MedEvidence V1 is a local, single-user research demonstration over public data
and an approved local corpus. It is not approved for:

- diagnosis, treatment, dosing, emergency guidance, or individualized advice;
- PHI, real patient cases, or identifiable medical records;
- clinical decision support or regulatory submission;
- public multi-user or multi-tenant deployment;
- automated product safety ranking or causal conclusions.

Moving beyond this boundary requires a new privacy, authentication,
authorization, retention, threat-model, and operational decision.

## 2. Source-safety policy

### PubMed

The system must distinguish available abstract evidence from reviewed full
text, preserve retraction/correction warnings, and avoid filling absent methods
or results with model inference.

### DailyMed

Every labeling claim must identify the selected product, SETID, SPL version,
section, and effective/published context. Missing results or absent wording do
not prove absence of risk.

### FAERS/openFDA

FAERS output is descriptive spontaneous-report data. The application enforces
mandatory limitations in structured report fields; the model does not decide
whether to display them.

FAERS must not produce:

- incidence, prevalence, or relative/absolute risk;
- causal conclusions;
- “safer,” “more dangerous,” or product safety ranking;
- disproportionality/signal metrics in V1.

### CADEC

CADEC is auxiliary NLP/retrieval material. The application prevents CADEC
records from supporting product-risk, incidence, causal, regulatory, or
clinical claims. Gold and predicted annotations remain distinguishable.

## 3. Threat model

V1 threats include:

- prompt injection in user questions or retrieved content;
- model-proposed tool calls with manipulated or unbounded arguments;
- arbitrary URL access and SSRF;
- secret leakage through logs, traces, errors, prompts, or exports;
- malformed, oversized, poisoned, or tampered source files;
- snapshot or manifest mismatch;
- citation fabrication or source-version mismatch;
- unsupported cross-source conflict or consistency claims;
- FAERS/CADEC semantic misuse;
- repeated side effects after LangGraph resume;
- duplicate formal export;
- denial of service through broad queries, retries, or result volume;
- vulnerable dependencies and container images.

## 4. Trust boundaries

Treat all of the following as untrusted:

- user prompts and configuration;
- source text, metadata, markup, and links;
- local corpus content;
- model plans, tool arguments, claims, and citations;
- MCP requests;
- cached payloads and imported manifests until integrity checks pass.

Retrieved content is evidence data, never an instruction channel.

## 5. Prompt-injection controls

Prompt text alone is not a sufficient defense. V1 requires structural controls:

1. Tools are statically allowlisted.
2. Connector hosts, schemes, and endpoints are allowlisted in code/config.
3. Model-proposed arguments are parsed into typed schemas and policy-validated.
4. Date ranges, pages, records, payload bytes, tool calls, retries, and time are
   bounded outside the model.
5. Retrieved text is delimited and labeled as untrusted source content.
6. Source content cannot alter tool permissions, system policy, or export
   requirements.
7. Models cannot supply arbitrary source URLs or credentials.
8. Citation IDs must exist in the current run's authorized source set.
9. A deterministic post-generation gate validates source IDs, versions,
   locators, coverage, and required limitations.
10. Adversarial tests cover attempts to hide warnings, expand permissions,
    reveal secrets, fabricate citations, or export without approval.

## 6. Tool security

- Validate every tool input against an explicit schema.
- Enforce approved source, language, query, date, pagination, and result limits.
- Use read-only source operations in V1.
- Keep credentials server-side and out of model context.
- Return typed invalid-input, timeout, rate-limit, unavailable, malformed, and
  partial-result outcomes.
- Log tool identity, bounded/redacted arguments, duration, cache status, retry
  count, result count, and error class.
- Do not expose provider SDK objects, raw authorization headers, or database
  handles to models, MCP clients, or UI code.

Connector retries are bounded and apply only to classified transient failures.
LangGraph must not create a second unbounded retry loop.

## 7. Two-stage citation and claim gate

Each material claim must include:

- claim ID and class;
- applicable drug/product, event, population/scope, and uncertainty;
- source classification;
- source record ID and exact version;
- exact text span or structured-field locator;
- `supports`, `contradicts`, or `context_only` relationship;
- automatic validation state and human-review state where applicable.

### Stage 1 — deterministic structural and policy validation

Stage 1 checks:

- source identity belongs to the current authorized run;
- source version and content hash match the cited snapshot;
- locator/span or structured field exists;
- the claim class is permitted for the source;
- FAERS and CADEC restrictions are satisfied;
- mandatory source limitations and coverage qualifiers are present.

Any Stage-1 failure is terminal for the formal-report claim.

### Stage 2 — versioned semantic support

Stage 2 records one of:

- `supported`;
- `uncertain`;
- `unsupported`.

The evaluator method, version, input claim, and citations are recorded.
`uncertain` requires human adjudication or removal. `unsupported` cannot enter
a formal report. An LLM judge may assist but cannot be the sole ground truth or
override a deterministic Stage-1 failure.

The complete citation gate fails closed when:

- a material claim has no sufficient citation;
- the cited record/version is absent from the run;
- the locator does not exist or does not support the full claim;
- a numerical claim lacks required unit/denominator/comparator/time context;
- required FAERS or CADEC limitations are absent;
- an unavailable source is represented as no evidence;
- a prohibited clinical, causal, incidence, or ranking conclusion appears.

A failed report may be saved as a non-exportable draft with diagnostics. A
material claim passes only when Stage 1 passes and Stage 2 is `supported` or is
resolved to supported by recorded human adjudication. No substantive claim may
survive a failed citation gate. A failed report cannot transition to
`pending_review`, `approved`, or `exported`.

## 8. Comparability and conflict safety

The application checks applicable dimensions before conflict classification:

- ingredient and product;
- formulation, route, and strength;
- population and indication;
- dose/exposure;
- observation and publication time;
- outcome/adverse-reaction definition;
- comparator and study/source question.

Scope mismatch produces `apparent_difference_scope_mismatch`, not a scientific
conflict. Sources are not combined by majority vote, and a shared reaction term
does not by itself constitute cross-source confirmation.

## 9. Medical-boundary handling

The safety policy classifies:

- permitted research synthesis;
- permitted descriptive source explanation;
- insufficient/partially answerable research;
- diagnosis or individualized risk;
- treatment/dose recommendation;
- emergency or urgent-care request;
- unsupported FAERS causality/ranking;
- regulatory or formal clinical use;
- attempts to remove warnings or source limitations.

Prohibited categories receive a consistent boundary response. If a request
includes an emergency or immediate-harm context, V1 does not attempt a research
report and follows the separately approved emergency-message policy. Exact
user-facing wording remains a pre-M3 policy approval item.

## 10. Snapshot and data integrity

- Raw snapshots are immutable and addressed by SHA-256.
- Manifests record the fields required by `DATA_SOURCES.md`.
- Hash, schema, expected record count, and lineage are verified before
  normalization or index publication.
- Qdrant is disposable and rebuildable from verified snapshots.
- Git contains only small approved fixtures, manifests, and evaluation data.
- Complete raw/normalized corpora, database volumes, caches, and indexes remain
  outside Git.
- A corrupted or unverified snapshot cannot contribute to an exportable report.

## 11. Secrets and operational PHI boundary

- `.env.example` contains placeholders only.
- Real credentials use environment injection or an approved secret store.
- Never commit, print, trace, prompt, or return API keys, passwords, cookies,
  authorization headers, or full connection strings.
- Logs redact configured user/source content, secrets, and restricted payloads.
- V1 exposes no file upload and defines no patient-record schema.
- V1 accepts public drug-safety research questions only.
- Input suspected to contain patient identifiers or a patient-case narrative is
  rejected fail-closed before research planning or source execution.
- Rejected raw input is not persisted in databases, snapshots, caches, traces,
  evaluation runs, or exports.
- Application logs contain a request ID, rejection reason code, detector/policy
  version, and redacted metadata only; they do not contain the raw suspected
  PHI.
- Synthetic tests cover person names, dates linked to a patient, medical-record
  and account numbers, addresses, contact details, and free-text patient
  narratives.
- The system does not claim certified de-identification, HIPAA compliance, or
  any regulatory privacy certification.

Any leaked credential must be revoked and rotated. A repository/history scan is
required before public release.

## 12. HITL and idempotent export

HITL is used only after a draft passes citation and safety gates.

Required sequence:

1. Create a stable `report_id` and content hash.
2. `validate_report` passes both citation stages and all safety policy.
3. `save_pending_draft` idempotently persists the validated draft as
   `pending_review`.
4. `request_export_approval` calls LangGraph `interrupt` with report identity,
   hash, target, source coverage, and warnings.
5. Perform no non-idempotent side effect before approval.
6. Record approve, edit/revalidate, or reject with reviewer and UTC time.
7. On approval, route to the separate `finalize_and_export` node.
8. Derive or validate an idempotency key from the approved report/destination.
9. Atomically check existing export state, write/finalize once, and store final
   hash, destination, timestamp, and outcome.
10. On resume/retry, return the existing export result when the same idempotency
   key has completed.

Editing invalidates the previous approval, produces a new content hash, reruns
validation, and requires a new approval. Human approval records authorization
to export; it is not a certification of clinical correctness.

This is the only V1 approval interrupt. Broad, expensive, or sensitive queries
must be deterministically bounded, rejected, or safely degraded; they do not
create additional HITL interrupts.

## 13. Availability and degradation

- Use explicit connect/read timeouts and bounded retries with jitter.
- Respect provider limits and client-identification requirements.
- Cache only according to approved freshness rules.
- Keep unexecuted sources in the planning layer as `selected`,
  `skipped_not_applicable`, or `skipped_by_policy`; skipped sources do not
  receive a fabricated `SourceOutcome`.
- Report `execution_status`, `coverage_status`, and `result_status` according
  to the normative source-outcome contract.
- `result_status` is exactly `matches`, `no_match`, or `indeterminate`.
- Only `succeeded + complete + no_match` represents a successful exhaustive
  zero-result query.
- Truncation, enforced limits before exhaustion, or incomplete pagination can
  never be `complete` and a zero-result partial operation is
  `indeterminate`.
- Failed zero-result and unavailable operations are `indeterminate`, never
  `no_match`; partial matches retain partial coverage.
- A partial report names missing sources and retrieval-as-of time.
- Final reports distinguish `no_match` from `indeterminate`, and run-level
  aggregation cannot upgrade partial or unavailable coverage to complete.
- Source failure is never translated into “the evidence does not exist.”
- Workflows have total time, source, page, record, tool-call, and token/cost
  budgets.

## 14. Observability and audit

Record correlation, run, report, source-task, checkpoint, and export IDs;
workflow transitions; tool/model timing; source coverage; retry/cache status;
snapshot and schema versions; citation/safety outcomes; and human review.

Do not log full prompts, evidence payloads, model reasoning, or report contents
by default. Trace access follows the same local-user boundary as reports.

## 15. Dependency and container safety

- Pin and review production dependency and image versions before release.
- Generate a dependency inventory and run vulnerability checks in CI.
- Use least-privilege containers and local-only ports where supported.
- Do not run application containers as root without a documented exception.
- Do not activate Redis, public ingress, or additional services without a new
  decision and threat-model update.

These controls are release gates for the local V1. Enterprise RBAC, public
ingress hardening, disaster recovery, and multi-tenant incident procedures are
postponed until their deployment boundary exists.

## 16. V1 safety acceptance gates

- All material report claims have valid source versions and exact locators.
- A failed critical citation cannot enter `pending_review` or `exported`.
- FAERS safety tests contain no unqualified incidence, causal, relative-risk,
  or product-ranking output.
- Every FAERS result displays statistical unit, query window, coverage, and
  mandatory limitations.
- CADEC never changes a clinical or product-risk conclusion.
- DailyMed claims identify product, SETID, SPL version, and section.
- Retracted literature cannot silently support a positive conclusion.
- Source failure always produces explicit partial/unavailable coverage.
- Prompt-injection tests produce no permission expansion, arbitrary host
  access, warning suppression, citation fabrication, secret leakage, or
  unauthorized export.
- Diagnosis, dosing, treatment, and individualized-risk tests do not cross the
  approved boundary.
- Repeated graph resume/export calls create no duplicate export.
- Representative conflict, refusal, FAERS, and citation cases receive
  designated human adjudication before V1 publication.

## 17. Remaining policy approvals

- Exact clinical-boundary and emergency-message wording
- Who is qualified to adjudicate safety/conflict cases and approve exports
- Report export formats and allowed local destinations
- Model provider data-use and retention policy
- CADEC license and distributable content
- Retention period for snapshots, drafts, reviews, exports, logs, and traces

## 18. M1B-DM-001 DailyMed trust and parser contract

The frozen `connector_trust_allowlist` is non-authorizing design metadata. It
contains exactly HTTPS `dailymed.nlm.nih.gov:443`, GET, one same-origin
redirect, and the six closed path/query templates recorded in ADR-011. It is
not a runtime or validation host permission. In M1B-DM-001,
`ordinary_validation_hosts=[]`, runtime permitted hosts are empty, and
`medical_source_network_execution_authorized=false`. No request constructor or
transport is implemented by this node.

The same typed oracle exactly freezes the 13 denied classes, cross-host
redirect prohibition, phase timeouts `5/10/5/5` seconds, 30-second deadline,
two attempts, 250-ms base/4-second cap/100-ms jitter, 10-second Retry-After
cap, closed retryable/permanent classes, five-page/100-candidate/5,242,880-byte
discovery bounds, immutable fixed-version cache, no discovery cache, and no
stale fallback.

SETID validation is fail-closed before any future path rendering: exactly 36
lowercase ASCII UUID characters, canonical parse/serialization equality, and
non-nil. SPL version is a positive canonical ASCII integer. Exact identity
must agree across request, response metadata, selected decision, and parsed SPL.

The future XML parser must use the frozen `defusedxml` policy and accept only
root `{urn:hl7-org:v3}document`. It rejects DTD/entity declarations, external
resolution, schema loading, XInclude, XSLT, recovery, malformed XML, namespace
or root drift, and all exceeded bounds. Identity selectors are exactly one
direct HL7 `setId` with unqualified `root` and one direct HL7 `versionNumber`
with unqualified `value`. Additional safe selector attributes are allowed but
semantically inert; namespaced/local-name lookalikes do not establish identity.

Historical ZIP processing never extracts to a filesystem. The compressed body,
total uncompressed bytes, and each uncompressed member are each limited to
5,242,880 bytes; the archive contains at most 128 entries. Complete central-
directory validation occurs before accepting evidence and bounds are enforced
again while reading. Encrypted, symlink, device, and special entries reject.
Before any normalization or interpretation, member names reject every ASCII C0
control U+0000 through U+001F and DEL U+007F, plus absolute, traversal,
backslash, device, drive, UNC, empty/dot segments, and duplicate normalized
names. Unsafe input is never normalized into acceptance.

Every bounded regular `.xml` member is classified with the same fail-closed XML
policy. Exactly one HL7 SPL document must exist and must match the selected
SETID/version. Zero or multiple candidates, including multiple candidates with
only one identity match, reject. Malformed/unclassifiable XML rejects. Safe
non-XML attachments remain nonauthoritative and are not retained as label
evidence.

The machine oracles additionally bind exact LOINC authority/steward/system/
release/order, direct selector and unqualified-attribute counts, lookalike/
nested non-counting, filename non-evidence, directory non-evidence, exact safe-
name normalization, case-insensitive `.xml` classification, and rejection of
multiple SPL candidates even when only one matches.

Partial discovery is also a security/evidence-authority boundary. Every
positive-count partial matches result is `review_required`, including a
resolved-equivalent or pinned request, and cannot trigger fetch, authoritative
normalization, citation, or a label locator. The three zero-result
indeterminate triples create no selection decision.

## 19. M1B-DM-003 public-boundary controls

The additive DailyMed request uses a required `m1b.request.v1` discriminator
and closed nested models. Unknown fields and caller-supplied planning fields
reject before application execution. Patient-like keys retain the shared raw
boundary rejection precedence. The response is reconstructed as a closed
`M1BResearchReportV1` and must echo the exact request identity, scope, and
DailyMed request elements while containing exactly one selected DailyMed plan
entry whose required nullable `reason_code` and `reason` fields are present with
null values and contain no skip-reason values.

No default DailyMed application, connector, transport, credential, host, or
network fallback is installed. Ordinary validation remains socket-disabled,
and the live harness is unconditionally skipped pending separate exact Owner
authorization.

## 20. M1B-FAERS-003 public-boundary controls

The additive FAERS route accepts only a required `m1b.request.v1` envelope with
FAERS as the sole requested and in-scope source. Duplicate JSON keys,
patient-like fields, unknown fields, caller planning state, foreign source
requests, and missing required nested fields reject before the application is
invoked. The returned value is reconstructed as a closed
`M1BResearchReportV1` and must echo the exact request, scope, selected FAERS
plan, request elements, trusted outcomes, sections, buckets, and locators.

The report boundary admits aggregates only: no individual FAERS report or
narrative payload is represented by its public models. Exact mandatory
limitations prevent counts from being presented as incidence, causality,
relative or comparative risk, comparative safety, ranking, or general absence
of GI adverse events. The FAERS application is optional and injected; no
default connector, credential, host permission, persistence adapter, or network
fallback is installed. The live harness is unconditionally skipped without a
separate exact one-run Owner authorization.

## 21. M1B-CADEC-001 asset trust boundary

CADEC archive/member bytes, annotations, vocabulary material, manifest, and
freeze audit remain untrusted external inputs. CADEC-001 admits no such bytes
to Git and performs no acquisition or medical-source request. The release
contract binds only exact hashes, sizes, counts, split membership hashes,
encoding policy, and governance state.

REDIST is fail-closed: external raw only, no redistribution, and no real
corpus-derived fixtures. The exact CSIRO Data Licence ID 1061 policy requires
attribution, non-commercial internal research only, no IP assertion over the
data, and no implied provider accuracy or endorsement. Vocabulary models admit
only `MedDRA` or `SNOMED CT`, exact unstated-version text, `reference-only`
legal status, and false emission flags; identifiers, terms, hierarchy, payload,
or redistributable assertions reject. The sole CP1252 exception requires the exact path and byte hash;
all other text is UTF-8. Unicode identifiers must already be NFC.

Five malformed rows remain rejected without repair or reinterpretation. The
separate 91 reference-binding limitations remain visible without being
relabeled or normalized away. Only provider-gold origin is representable.
Auxiliary locators retain prohibited clinical, causal, incidence, regulatory,
product-risk/comparison, diagnosis, treatment, ranking, advice, dosage,
emergency-guidance, and individualized-medical-advice contexts. They also
closed-revalidate identity, policy, span, release, split, and exact parent
lineage. CADEC-002 requires new Owner authorization for any loader, execution,
persistence, search, index, report, or API boundary.

## 22. M3-006 source-capability trust boundary

ADR-018 is the later exact Owner authorization for local M3 CADEC execution;
the M1B statement above remains immutable historical scope. The authorization
does not include a medical-source network call, model/provider, public API,
schema/migration, dependency, or Holdout access.

Untrusted plan rows, checkpoints, source projections, persisted acquisition
echoes, CADEC paths, archive/manifest bytes, admitted document text, and search
results are reconstructed before use. Plan rows must equal selected scope
sources; tasks must equal selected plan rows. Required operations bind run,
task, attempt, source, ordinal, kind, and query and are checkpointed before
their effects. Resume must reproduce the same plan. Terminal admission requires
every final required operation and exact acquisition/outcome/observation
binding.

The dispatcher is sealed, statically branches over the four approved sources,
and accepts explicit injected application ports. It contains no mutable
dispatch table, dynamic private-helper authority, provider fallback, or
concrete infrastructure construction. Tools expose source-neutral contracts;
only infrastructure owns CADEC filesystem paths and concrete BM25 behavior.

CADEC local search fails closed on any archive, manifest, membership, encoding,
hash, materialization, duplicate, foreign result, non-finite score, ordering,
or result-binding drift. Failure returns no partial evidence and maps to
`failed / unavailable / indeterminate`. Zero positive results become no-match
only after all 1,246 eligible documents were validly scored. Text and chunks
are transient and must not enter Git, PostgreSQL, Qdrant, logs, checkpoints, or
durable application contracts.

Every executed FAERS task carries `faers_mandatory_limitations`; every CADEC
success or failure carries `cadec_mandatory_limitations`. Those limitations and
the auxiliary-only CADEC role prevent incidence, causality, regulatory,
clinical, product-risk, comparative-safety, or ranking claims. Holdout-20
remains sealed.

### 22.1 Round 3 fail-closed closures

The initial independent verdict is preserved exactly as
`FAIL — P0 0 / P1 4 / P2 0`. Round 3 closes the demonstrated trust-boundary
bypasses by making the operation's complete input subject part of its durable
identity, binding terminal aggregate content separately from all child
acquisitions, and requiring the representative acquisition to equal one exact
child binding.

`CadecVerifiedCorpus` now reconstructs the complete frozen verification tuple;
no caller-supplied count/hash/policy subset can stand in for the exact asset.
Every CADEC failure or unavailable/indeterminate result has exact governed
limitations and zero observations/evidence refs. Sealed concrete DailyMed and
FAERS authorities own request construction, persisted provenance validation,
terminal projection, and limitations; the static dispatcher rejects structural
fakes and subclasses by requiring exact authority types. The candidate awaits
fresh independent review and has no PASS/Git authority from these closures.

### 22.2 Round 4 durable-stage and composition controls

The fresh Round 3 review is preserved exactly as
`FAIL — P0 0 / P1 3 / P2 0`. Round 4 closes its three trust-boundary findings:

- typed v3 refs bind operation role/value inputs, scope, derived input identity,
  and acquisition intent;
- a RUNNING task stores only an exact completed-result prefix, and the workflow
  checkpoints each source stage before a dynamic fetch suffix can execute;
- PubMed and DailyMed must reload immutable persisted progress and reject
  missing, stale, alternate, or corrupt membership/provenance;
- terminal validation reconstructs every `SourceOutcome` field from child
  operations, preventing self-consistent query/count/intent/operation forgery;
  and
- CADEC is removed from the structural dispatcher. Only the sealed final
  infrastructure wrapper can internally construct the concrete adapter from
  explicit archive/manifest paths; production composition has the sole route.

The CADEC operation also binds exact asset and membership identities, so an
asset-free fake cannot satisfy planning. Fresh review, rebind, and audit remain
required; no PASS or Git claim is made.

### 22.4 Round 6 replay-before-next-source controls

The fresh Round 5 review is preserved exactly:
`FAIL — P0 0 / P1 2 / P2 0`. `collect_evidence` now replays every existing
terminal task before its source loop, so a forged terminal prefix cannot be
carried into planning or effects for another source.

All critical source composition instances freeze normal replacement of trusted
fields and use class-qualified dispatch. Production composition internally
constructs PubMed service/acquisition authority and immutable snapshot-backed
DailyMed/FAERS replay stores. Caller-supplied live provenance is kept separate
and cannot act as or replace replay authority. Replay before synthesis,
validation, save, approval, export, trusted/idempotent returns, and terminal
inspection remains intact. Fresh review, rebind, and audit remain required; no
PASS or Git claim is made.

### 22.9 Final independent security review

Fresh final Round 10 independent review returned
`PASS — P0 0 / P1 0 / P2 0` with no findings. Planner shadow attacks passed
`5/5`; workflow/runtime/composition, projection/replay, authority/subset, and
static boundary checks all passed. Historical FAIL findings remain immutable.
Exact-byte rebind and terminal audit remain required; status is
`AWAITING_TERMINAL_AUDIT` and no overall PASS/Git claim is made.

### 22.5 Round 7 inspect and underlying-authority controls

The fresh Round 6 review is preserved exactly:
`FAIL — P0 0 / P1 3 / P2 0`. LangGraph reconstructs scheduling/topology and
then invokes `validate_terminal_sources` before every active or terminal result
can leave `inspect`, `start`, or `resume`.

`SnapshotStore` is sealed, final, slotted, root-read-only, and freezes internal
probes/state after construction. Acquisition, DailyMed/FAERS replay, and CADEC
authorities likewise reject normal field/method replacement and are invoked
class-qualified. Coordinated checkpoint/store substitution therefore fails
before trusted return or effects.

CADEC's top-20 result cap is not accepted as an execution bound. Exact scope
bounds are reconstructed for success and failure, preserving the governed
`max_records=100`. Fresh review, rebind, and audit remain required; no PASS or
Git claim is made.

### 22.7 Round 9 checkpoint plan authority

The fresh Round 8 review is preserved exactly:
`FAIL — P0 0 / P1 1 / P2 0`. Every trusted workflow entry now invokes the
frozen planner and requires byte-semantic equality of the full canonical plan
before terminal replay or effects. The derived `source_plan_id` is strict and
bound into canonical report and validation receipt identities.

The final/slotted workflow rejects normal planner/dependency replacement.
Selected-to-skip plus task removal and post-receipt reason drift fail before
source I/O, evaluator, persistence, approval, export, inspection, or trusted
return. Fresh review, rebind, and audit remain required; no PASS or Git claim is
made.

### 22.8 Final Round 10 planner-shadow control

The fresh Round 9 review is preserved exactly:
`FAIL — P0 0 / P1 1 / P2 0`. Workflow accepts only the exact final, slotted,
no-dictionary `CanonicalSourcePlanningAuthority`. Its strict scope and complete
canonical plan are reconstructed during construction and fields cannot be
replaced afterward.

Initial and replay calls are class-qualified, so an instance-level method
shadow, mutable Protocol implementation, subclass, or foreign scope cannot
authorize plan drift. The demonstrated coordinated attack reaches zero source,
semantic, persistence, approval, and export effects. Fresh final review,
rebind, and audit remain required; remediation budget 10/10 is exhausted and no
PASS or Git claim is made.

### 22.6 Round 8 skipped-source and dependency-group controls

The fresh Round 7 review is preserved exactly:
`FAIL — P0 0 / P1 2 / P2 0`. Canonical validation now treats full scope and
plan-selected task sources as separate bound identities. A skipped row remains
auditable but cannot gain a task/outcome; a missing, extra, reordered, duplicate,
or noncanonical selected-task subset fails closed.

Production composition accepts an authority group iff its source is selected,
requires every member of that group, and rejects partial or extraneous groups.
All 15 nonempty source subsets are covered. CADEC-only cannot be forced to
accept a replay store, while selected network sources require one shared exact
store. Fresh review, rebind, and audit remain required; no PASS or Git claim is
made.

### 22.3 Round 5 replay-before-trust controls

The fresh Round 4 verdict is preserved exactly:
`FAIL — P0 0 / P1 3 / P2 0`. Round 5 freezes normal replacement of the CADEC
wrapper's delegate/search and the concrete adapter paths, then reruns the exact
configured asset for every CADEC terminal task. PubMed's terminal receipt binds
the search receipt and entire terminal projection, defeating coordinated
journal/checkpoint substitution; production composition accepts no prebuilt
PubMed service or fake snapshot-store route.

DailyMed and FAERS replay exact persisted operation provenance.
`EvidenceCollectionPort.validate_terminal_task` is invoked before every
post-collection trusted/effect path and terminal inspection, including
synthesis, deterministic/semantic validation, pending save, approval, export,
and idempotent returns. A self-consistent but non-replayable child therefore
fails before any later capability. Fresh review, rebind, and audit remain
required; no PASS or Git claim is made.

## 23. M3-007 OpenAI generation-gateway trust boundary

The only approved model-provider surface is
`POST https://api.openai.com/v1/responses` through existing HTTPX with model
`gpt-5.6-sol` and reasoning effort `medium`. Requests set `store=false` and
`background=false`, provide no tools, and do not opt into extended prompt-cache
retention. No SDK or new dependency is added.

The gateway is a bounded candidate generator, not an evidence, validation,
approval, or export authority. The model, typed request input, and generated
candidate have no credential, filesystem, database, MCP, web, retrieval,
source-connector, or other tool access. The gateway alone receives the
environment-injected OpenAI bearer credential solely to authorize the exact
approved endpoint. Evidence content is explicitly labeled and delimited as
untrusted data; instructions in that content cannot change policy, request
configuration, schemas, or permissions. Only exact evidence identities
supplied for the current run may be selected.

Structured output is parsed strictly and then reconstructed by application
code. Unknown, duplicate, missing, stale, foreign, or out-of-bounds identities;
unsupported fields; malformed JSON; oversized data; and prohibited claim forms
fail closed. Zero evidence cannot produce a claim. Missing, partial,
unavailable, and conflicting evidence remain visible. The generator cannot
invent completion, limitations, numerical context, agreement, incidence,
causality, relative or absolute risk, regulatory authority, product-risk
ordering, comparative safety, diagnosis, treatment, dosage, or individualized
advice.

The versioned prompt/config/schema contract owns finite request, response,
token, deadline, timeout, attempt, backoff, and retry bounds. Redirects are
forbidden. The bearer credential never enters model context and is excluded
from prompts, receipts, errors, logs, and persisted artifacts. Untrusted
evidence text, generated prose, authorization headers, and provider reasoning
are likewise excluded from logs and receipts.

An immutable `M3_GENERATION_RECEIPT_V1` binds the exact prompt, configuration,
model, reasoning, and schema identities, versions, and hashes, the canonical
candidate hash, and bounded provider execution metadata. It records the actual
Zero Data Retention status rather than assuming ZDR is active. The Owner has
accepted applicable OpenAI API business-data retention for the public-data V1
boundary with `store=false` and `background=false`. Receipt persistence reuses
the existing immutable application journal and adds no database migration.

All default tests and validation remain offline and socket-disabled. Live
provider access requires an explicit live-provider marker/run and an
environment-injected key; a missing key blocks that live gate and is not a fake
PASS. Import and construction perform no network activity. An authorized live
provider test may contact only the approved OpenAI endpoint and is reported
separately from medical-source activity. No PubMed, NCBI, DailyMed, FAERS,
CADEC, or other medical-source network is authorized.

M3-007 does not integrate generation into the workflow and does not implement
or change Stage-2 semantic support. M3-008 owns the evaluator and a later
authorized item owns workflow composition. Public API/OpenAPI, persistence
schema, source/evidence semantics, retrieval/router/qrels/corpus/metric
contracts, and Holdout-20 remain unchanged and sealed.
