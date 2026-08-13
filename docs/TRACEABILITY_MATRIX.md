# V1 Traceability Matrix

## M1B-FAERS-001

| Owner decision | Domain evidence | Offline tests |
|---|---|---|
| Unit/mode/latest | Query, bucket, and result models | `test_source_outcomes.py` |
| No role predicate | Request/query/bucket/locator literals | `test_scope.py`, `test_reports.py` |
| Identity/date/query | Request/date/query validators and exact date-bound query-ID preimage | `test_scope.py`, `test_source_outcomes.py`, `test_openapi.py` |
| PT authority/exclusions | Exact constants and bucket literal | `test_scope.py`, `test_source_outcomes.py` |
| Bounds/transport/freshness | Execution and policy models | `test_provenance.py` |
| Aggregate/report/locator | Exact result/section/locator comparators and discriminated source-section union | `test_source_outcomes.py`, `test_reports.py`, `test_openapi.py` |
| Limitations | Exact mandatory limitation tuple | `test_source_outcomes.py`, `test_reports.py` |

Status: Terminal Audit001 PASS; final-byte rebind and Git pending.
No connector, persistence, migration, tool, FAERS API route, dependency,
network, or M1B-FAERS-002 work is claimed. The enabled M1B OpenAPI envelope
reflects the additive typed FAERS request/section union only.

Review001 remains immutable FAIL history. P1-01 was remediated in cycle 1/3.
Owner-authorized cycle 2/3 closes P1-02 with an exact 0..8 typed FAERS request
tuple, discriminated DailyMed/FAERS section union, exact request-owned
request/result/outcome comparison, and additive enabled OpenAPI parity. No
FAERS route was added; PubMed default bytes and the 76-component PubMed subtree
remain unchanged. Review002 returned `FAIL — P0 0 / P1 1 / P2 0` for omitted
serialized date-bound query-identity constants. Final cycle 3/3 requires exact
present literals `365` and `366`, includes them in the query-ID preimage and
OpenAPI, and rejects omission, drift, and accepted-instance bypass. Fresh
Review003 inspected the complete remediated 22-path candidate and returned
`PASS — P0 0 / P1 0 / P2 0`, binding manifest
`bddadeeade832b763cd0f37e0ce15e666e03e0ee2a0eb627651c7fda57100859`.
It verified all three historical finding closures, frozen FAERS semantics,
unchanged M1A/PubMed compatibility, retained DailyMed behavior, and absence of
a FAERS route. At that review gate, terminal audit remained pending; no
completion or Git lifecycle was claimed.

Terminal Evidence Audit001 returned `PASS — P0 0 / P1 0 / P2 0`, binding exact
audited manifest
`e572da3ef99f568dbfba27569c3921b5879ce76a68cf7f2d8b65432048aa6f97`.
All focused, API/OpenAPI, full offline, static, scope, encoding, fixture,
dependency, route, and index gates passed. Persisting audit evidence changes
the candidate bytes; final-byte rebind and Git remain pending, with no
completion, integration, or FAERS-002 claim.

## 1. Purpose and use

This matrix maps every V1 requirement to exact governing design locations,
implementation milestone, required evidence, and acceptance criterion.

Rules:

- A requirement is incomplete until its referenced evidence exists.
- Planned evidence and thresholds are not passed results.
- A requirement/design change must update this matrix and governing ADR.
- Evidence records code revision, dataset/snapshot/configuration version, and
  command or run ID.
- `N/A — reason` is used only when an artifact is genuinely irrelevant.

### Current M1A integration status

M1A is integrated in approved `main` at
`531f867006f3d01ebbc14633ad6e5509e4e70a47`, the accepted Run 002 code
revision. Earlier baseline, candidate, and pending-
merge statements below are historical evidence and are superseded for current
status by the integration and acceptance records.

Run 001 remains
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`. Its historical
connector outcome is `failed / unavailable / indeterminate`, its received
bytes remain separately preserved as `failed / partial / indeterminate`, and
fetch was not executed. It never established a live PASS.

The separately authorized Run 002 is `M1A_LIVE_RUN_002_ACCEPTED` and establishes
`M1A_LIVE_ACCEPTANCE_PASS`. One run used exactly two requests and two contiguous
acquisitions. Search was `succeeded / partial / matches`, with 100 valid
results, one page, and `truncated=true`; fetch was
`succeeded / complete / matches`, with one valid retained publication, one
page, and `truncated=false`. The partial search is explicitly bounded and
non-exhaustive. The redacted acceptance record and validated identities are
recorded in [M1A-LIVE-RUN-002-ACCEPTANCE](../.delivery/M1A-LIVE-RUN-002-ACCEPTANCE.md).

The durable M1A state remains `M1A_COMPLETE`. The Owner-authorized
`M1B-DM-001` additive domain-contract implementation is now a local candidate
whose first independent review returned `P0/P1/P2 = 0/4/1` and whose final
remediation 3/3 review returned `FAIL — P0 0 / P1 2 / P2 0`. The Owner then
authorized one extra remediation cycle limited to both P1 findings. Extra
remediation 1/1 and fresh offline validation completed, but Review 002 returned
`FAIL — P0 0 / P1 1 / P2 1` on candidate manifest
`f8c9cb5b13a93d4c15847855785afac80d16e0332462a9b0734e9cb576769ffe`.
Same-class P1-02 remediation and dependent P2 evidence were implemented with
fresh offline validation, but Review 003 returned
`FAIL — P0 0 / P1 2 / P2 0` on exact 20-path manifest
`06b77e138ed4f87b2ddc749ef8eb67fd214b61512714f56b95e881afbbeeb6b3`.
The extra cycle 1/1 is consumed and status is `OWNER_DECISION_REQUIRED` for
another bounded mechanical cycle. Terminal audit and Git integration were not
run. The Owner subsequently authorized exactly one new cycle limited to Review
003 P1-01/P1-02. The implementation and fresh validation completed, but Review
004 returned `FAIL — P0 0 / P1 1 / P2 0` on canonical ordinal manifest
`e4f3ec8e43e2292ffe1c9c6206892f61d7111eb5c27392a21022122b14b5819e`.
Same-class batch remediation was authorized under the explicit do-not-stop
clause. The implementation and fresh root validation completed, but Review 005
returned `FAIL — P0 0 / P1 2 / P2 0` on exact 22-path manifest
`420cfd5a5ec52a30d53dee54d5bac2cfff2a11c0b450e03031434d4ea1881bca`.
Same-class batch remediation and fresh root validation completed, but Review
006 returned `FAIL — P0 0 / P1 1 / P2 0` on exact candidate manifest
`75416c4fb6a3df9bbcf40783bcc4aab9f12e3d3c8df9118fdaebfe7f756dbeef`.
It accepted cross-request reuse of acquisition, snapshot, and source-outcome
IDs because global uniqueness was enforced only for acquisition ordinals.
Owner-authorized same-class remediation now enforces global uniqueness of
`acquisition_id`, `snapshot_id`, and `source_outcome_id` while preserving valid
`acquisition_intent_id` reuse. Fresh root validation passed, but Review 007
returned `FAIL — P0 0 / P1 1 / P2 0` on manifest
`9a1ad8c2d2850c2b5ffcff67d5e19017beee740eb183c6b222270d1bdee258ca`.
The exported `DailyMedTrustPath` accepts non-frozen standalone rows even though
the parent policy rejects them. Same Owner-authorized security P1-01
remediation now restricts standalone validation to exactly one of the six
frozen rows with direct drift negatives; parent validation is unchanged and no
schema/public concept changed. Fresh root validation passes; Review 008 and
terminal audit were the next gates. Review 008 returned
`FAIL — P0 0 / P1 2 / P2 0` on manifest
`939e99998c63dfe3ae664aa5ef6e265bc28e0e2787ea7cb73a32002dfb29e93e`.
It found existing-instance security-policy revalidation bypasses and
standalone/mutated LOINC drift. Same Owner-frozen non-weakenability and LOINC
mechanical remediation now revalidates all six security model instance types,
including nested connector drift, and enforces exact one-of-four LOINC rows
plus row/oracle instance revalidation. Frozen values remain unchanged. Fresh
root validation passes; Review 009 and terminal audit are pending. This is not
an integrated M1B completion claim.
The Run 002
authority is consumed, `rerun_authorized=false`, and every further
medical-source request requires new exact Owner authorization. No medical-source
request is authorized or performed by `M1B-DM-001`.
The acceptance establishes no causal, incidence, comparative-risk, or clinical
conclusion; the draft remains research-only, non-exportable, and non-clinical.

## 2. Functional requirements

| PRD requirement ID | Architecture section/anchor | Data-source policy section/anchor | Security section/anchor | Evaluation section/anchor | Governing ADR | Milestone | Test/evaluation evidence | Acceptance criterion |
|---|---|---|---|---|---|---|---|---|
| [`V1-FR-001`](PRD.md#v1-fr-001--configurable-research-scope) | [§7.1 Research and terminology](ARCHITECTURE.md#71-research-and-terminology) | [§7 Terminology normalization](DATA_SOURCES.md#7-terminology-normalization) | [§9 Medical-boundary handling](SECURITY.md#9-medical-boundary-handling) | [§3 Evaluation item schema](EVALUATION_PLAN.md#3-evaluation-item-schema) | [ADR-001](decisions/ADR-001-v1-reference-domain.md), [ADR-007](decisions/ADR-007-domain-contracts-and-schema-versioning.md) | M1A | Domain schema, API contract, and second synthetic-scope tests | Reference scenario loads through typed configuration; a second scope uses the same path without drug/ADR branches |
| [`V1-FR-002`](PRD.md#v1-fr-002--pubmed-vertical-slice) | [§8.1 Connector capabilities](ARCHITECTURE.md#81-connector-capabilities) | [§2 PubMed](DATA_SOURCES.md#2-pubmed) | [§2 PubMed source policy](SECURITY.md#pubmed) | [§2.1 Gold-10](EVALUATION_PLAN.md#21-gold-10-calibration-subset) | [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-003](decisions/ADR-003-storage-and-snapshots.md), [ADR-009](decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md) | M1A | M1A is integrated at accepted code revision `531f867006f3d01ebbc14633ad6e5509e4e70a47`. Run 001 remains `M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`: historical connector outcome `failed / unavailable / indeterminate`, received bytes preserved separately as `failed / partial / indeterminate`, fetch not executed, and no live PASS. Run 002 is `M1A_LIVE_RUN_002_ACCEPTED`: the redacted closed-contract record at external root label `OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT` and relative label `acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json` is 3,223 bytes with SHA-256 `008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`. One run used two contiguous acquisitions and two total requests. Search is `succeeded / partial / matches`, 100 valid results, one page, `truncated=true`, explicitly bounded and non-exhaustive; fetch is `succeeded / complete / matches`, one valid retained publication, one page, `truncated=false`. This establishes `M1A_LIVE_ACCEPTANCE_PASS`, `M1A_COMPLETE`, and `READY_FOR_M1B_OWNER_PLANNING`; M1B has not started, no rerun occurred, the authority is consumed, and `rerun_authorized=false`. | Draft contains PMID/version and exact available-abstract locator; no-match, partial, failed, and unavailable outcomes remain distinct; partial search supports no exhaustive, causal, incidence, comparative-risk, or clinical conclusion and the draft remains non-exportable |
| [`V1-FR-003`](PRD.md#v1-fr-003--dailymed-labeling) | [§8.1 Connector capabilities](ARCHITECTURE.md#81-connector-capabilities), [§16 M1B-DM-001](ARCHITECTURE.md#16-m1b-dm-001-additive-dailymed-contract-architecture) | [§3 DailyMed](DATA_SOURCES.md#3-dailymed), [§11 M1B-DM-001](DATA_SOURCES.md#11-m1b-dm-001-exact-dailymed-source-contract) | [§2 DailyMed source policy](SECURITY.md#dailymed), [§18 M1B-DM-001](SECURITY.md#18-m1b-dm-001-dailymed-trust-and-parser-contract) | [§5 Question taxonomy](EVALUATION_PLAN.md#5-question-taxonomy), [§13 M1B-DM-001](EVALUATION_PLAN.md#13-m1b-dm-001-deterministic-contract-evaluation) | [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-003](decisions/ADR-003-storage-and-snapshots.md), [ADR-011](decisions/ADR-011-m1b-dailymed-contracts.md), [Review 001](reviews/M1B-DM-001-INDEPENDENT-REVIEW-001.md), [Review 002](reviews/M1B-DM-001-INDEPENDENT-REVIEW-002.md), [Review 003](reviews/M1B-DM-001-INDEPENDENT-REVIEW-003.md), [Review 004](reviews/M1B-DM-001-INDEPENDENT-REVIEW-004.md), [Review 005](reviews/M1B-DM-001-INDEPENDENT-REVIEW-005.md), [Review 006](reviews/M1B-DM-001-INDEPENDENT-REVIEW-006.md), [Review 007](reviews/M1B-DM-001-INDEPENDENT-REVIEW-007.md), [Review 008](reviews/M1B-DM-001-INDEPENDENT-REVIEW-008.md) | M1B | Reviews 001-008 remain immutable failure history. Review 008 verified direct trust-path closure, then found existing-instance security-policy bypasses and standalone/mutated LOINC drift. Manifest `939e99998c63dfe3ae664aa5ef6e265bc28e0e2787ea7cb73a32002dfb29e93e`; verdict `FAIL — P0 0 / P1 2 / P2 0`. Post-Review 008 remediation revalidates all six security model instance types and nested connector drift, and enforces exact one-of-four LOINC rows plus row/oracle instance revalidation; frozen values are unchanged. Fresh evidence: focused `301/0.46s`; combined DailyMed/OpenAPI `335/0.74s`; Ruff/format/MyPy PASS; full `949`, two warnings, `80%/7.33s`; exact 26-path scope/diff PASS. Review 009/audit pending; no PASS, Git, network, integration, or DM-002 claim | Only `succeeded/complete/matches` may select after deterministic exact/equivalent-group resolution; partial matches always require review; the only `no_candidate` state is `succeeded/complete/no_match`; every retained section locator binds the selected label identity and a successful complete usable fetch |
| [`V1-FR-004`](PRD.md#v1-fr-004--faers-descriptive-query) | [§8.1 Connector capabilities](ARCHITECTURE.md#81-connector-capabilities) | [§4 FAERS/openFDA](DATA_SOURCES.md#4-faersopenfda) | [§2 FAERS/openFDA source policy](SECURITY.md#faersopenfda) | [§8 Agent and safety evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation) | [ADR-002](decisions/ADR-002-source-semantics.md) | M1B | Query/limit units; timeout, 429, truncation, partial fixtures; Gold-10 FAERS case | Output exposes statistical unit, query/time/limits/role/version policy and mandatory limitations; zero unqualified incidence, causal, relative-risk, or ranking claims |
| [`V1-FR-005`](PRD.md#v1-fr-005--cadec-auxiliary-corpus) | [§19 M1B CADEC loader-only boundary](ARCHITECTURE.md#19-m1b-cadec-loader-only-architecture-and-m2-boundary) | [§14 exact CADEC asset contract](DATA_SOURCES.md#14-m1b-cadec-001-exact-asset-contract) | [§21 CADEC asset trust boundary](SECURITY.md#21-m1b-cadec-001-asset-trust-boundary) | [§16 deterministic CADEC contract evaluation](EVALUATION_PLAN.md#16-m1b-cadec-001-deterministic-asset-contract-evaluation) | [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-003](decisions/ADR-003-storage-and-snapshots.md), [ADR-013](decisions/ADR-013-m1b-cadec-asset-contract.md) | M1B loader-only complete; future M2 materialization/search after `ME-000C` | Integrated CADEC-001/002 exact asset, metadata-only document, provider-gold annotation, locator, split, Option-A lineage, immutable-byte loader/parser, and prohibited-claim evidence; exactly one visible CADEC plan entry is `skipped_by_policy` with `reason_code=source_execution_not_authorized`; no predicted parse, chunk, index, search, executable request, research-request connector invocation, `SourceOutcome`, report section, API/OpenAPI execution, persistence, or retrieval-evaluation evidence is claimed | Visibility is distinct from execution: M1B ends at the exact external loader/parser and metadata-only output, which is not directly retrieval-consumable; future M2 must reread and reverify the approved external archive before text-bearing materialization and `search_local_adr_corpus` |
| [`V1-FR-006`](PRD.md#v1-fr-006--reproducible-ingestion) | [§5.2 Raw snapshot and manifest](ARCHITECTURE.md#52-raw-snapshot-and-manifest) | [§8 Snapshot and manifest policy](DATA_SOURCES.md#8-snapshot-and-manifest-policy) | [§10 Snapshot and data integrity](SECURITY.md#10-snapshot-and-data-integrity) | [§11 Reproducibility](EVALUATION_PLAN.md#11-reproducibility-and-artifact-policy) | [ADR-003](decisions/ADR-003-storage-and-snapshots.md), [ADR-010](decisions/ADR-010-m1a-remainder-freeze-amendment.md) | M1A/M1B | M1A-003A, M1A-003B, and M1A-004 are preserved ancestors of the current M1A-005-integrated baseline `47504a4016f968ed0a0dd10e4280b1a957c15461`; their final review, audit, hosted-CI, and historical evidence remain preserved. M1A-004 owns exact ADR-010 acquisition-intent validation and rejects malformed, reused, or cross-acquisition persistence results. | Every run emits required manifest fields; verified replay gives stable IDs; integrity failure blocks normalization/index publication |
| [`V1-FR-007`](PRD.md#v1-fr-007--source-aware-normalization) | [§5.3 Normalization](ARCHITECTURE.md#53-normalization-and-deduplication), [§7.1](ARCHITECTURE.md#71-research-and-terminology) | [§7 Terminology normalization](DATA_SOURCES.md#7-terminology-normalization) | N/A — normalization safety is enforced through source/claim policies, not a separate security control | [§3 Evaluation item schema](EVALUATION_PLAN.md#3-evaluation-item-schema) | [ADR-007](decisions/ADR-007-domain-contracts-and-schema-versioning.md) | M1A/M1B | Exact/synonym/fuzzy/unresolved mapping and ambiguity tests | Original term, method, confidence, vocabulary/version, and warnings persist; uncertain mapping never silently becomes exact |
| [`V1-FR-008`](PRD.md#v1-fr-008--retrieval-modes) | [§9 Retrieval architecture](ARCHITECTURE.md#9-retrieval-architecture), [§9.1 decision gate](ARCHITECTURE.md#91-retrieval-configuration-decision-gate) | N/A — retrieval configuration is index policy, not source-semantic policy | [§15 Dependency safety](SECURITY.md#15-dependency-and-container-safety) | [§6 Retrieval evaluation](EVALUATION_PLAN.md#6-retrieval-evaluation) | [ADR-004](decisions/ADR-004-qdrant-hybrid-retrieval.md) | M2 after `ME-000C` | Frozen-corpus BM25/dense/RRF runs, contract tests, raw rankings | Three modes use one corpus/filters/contract and retain component/final ranks; reranker remains optional |
| [`V1-FR-009`](PRD.md#v1-fr-009--claims-and-citations) | [§7.4 Claims and reports](ARCHITECTURE.md#74-claims-and-reports), [§7.6 citation validation](ARCHITECTURE.md#76-two-stage-citation-validation) | [§6 Shared source contracts](DATA_SOURCES.md#6-shared-source-contracts) | [§7 Citation gate](SECURITY.md#7-two-stage-citation-and-claim-gate) | [§4.3 Citation span](EVALUATION_PLAN.md#43-citation-span-rule), [§7 Claim/citation](EVALUATION_PLAN.md#7-claim-and-citation-evaluation) | [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-007](decisions/ADR-007-domain-contracts-and-schema-versioning.md), [ADR-009](decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md) | M1A/M2/M3 | M1A-004 commit `2f6cb0a` is an ancestor of the current M1A-005-integrated baseline `47504a4016f968ed0a0dd10e4280b1a957c15461`; its tests cover Unicode offsets, exact quote/hash binding, smallest-span tie-break, missing evidence, and retracted/corrected/EOC/unknown policies. | Material claim passes structural/policy Stage 1 and semantic Stage 2; uncertain is adjudicated/removed and unsupported never enters a formal report |
| [`V1-FR-010`](PRD.md#v1-fr-010--comparability-and-conflict) | [§7.4 Claims and reports](ARCHITECTURE.md#74-claims-and-reports) | [§1 Governing principle](DATA_SOURCES.md#1-governing-principle) | [§8 Comparability safety](SECURITY.md#8-comparability-and-conflict-safety) | [§4.4 Conflict classes](EVALUATION_PLAN.md#44-comparability-and-conflict-classes) | [ADR-002](decisions/ADR-002-source-semantics.md) | M2/M3 | Gold-10 conflict cases, dimension units, majority-vote negative case | One approved class follows dimension comparison; source co-mention/majority vote cannot create consistency |
| [`V1-FR-011`](PRD.md#v1-fr-011--structured-report) | [§7.4 Claims and reports](ARCHITECTURE.md#74-claims-and-reports), [§11 Delivery](ARCHITECTURE.md#11-delivery-architecture) | [§10 Report reproducibility](DATA_SOURCES.md#10-freshness-and-report-reproducibility) | [§7 Citation gate](SECURITY.md#7-two-stage-citation-and-claim-gate) | [§7 Claim/citation evaluation](EVALUATION_PLAN.md#7-claim-and-citation-evaluation) | [ADR-001](decisions/ADR-001-v1-reference-domain.md), [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-009](decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md) | M1A/M3 | M1A-004 commit `2f6cb0a` is an ancestor of the current M1A-005-integrated baseline `47504a4016f968ed0a0dd10e4280b1a957c15461`; its report tests bind run/catalog/run-intent, reconstructed ordered acquisitions, exact publication/citation/claim lineage, and report-artifact identity. | Report contains scope, three-dimension source outcomes, source sections, claims/citations, conflicts, limitations, as-of/version, and review state |
| [`V1-FR-012`](PRD.md#v1-fr-012--controlled-orchestration) | [§10 Controlled workflow](ARCHITECTURE.md#10-controlled-langgraph-workflow) | N/A — orchestration does not own source semantics | [§5 Prompt-injection controls](SECURITY.md#5-prompt-injection-controls), [§12 HITL](SECURITY.md#12-hitl-and-idempotent-export) | [§8 Agent evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation) | [ADR-005](decisions/ADR-005-controlled-langgraph-hitl.md) | M3 | Dependency check, tool-double graph tests, bounded trajectory | Nodes instantiate no provider/storage clients; requests are bounded/rejected/degraded; source failures remain visible |
| [`V1-FR-013`](PRD.md#v1-fr-013--citation-and-safety-gates) | [§7.6 citation validation](ARCHITECTURE.md#76-two-stage-citation-validation) | [§1 Governing principle](DATA_SOURCES.md#1-governing-principle) | [§7 Citation gate](SECURITY.md#7-two-stage-citation-and-claim-gate) | [§7 Claim/citation](EVALUATION_PLAN.md#7-claim-and-citation-evaluation), [§10 Judge policy](EVALUATION_PLAN.md#10-llm-as-a-judge-policy) | [ADR-002](decisions/ADR-002-source-semantics.md), [ADR-005](decisions/ADR-005-controlled-langgraph-hitl.md) | M3 | Structural mutation, semantic support, FAERS/CADEC, medical-boundary, injection suites | Failed Stage 1 or unresolved uncertain/unsupported Stage 2 cannot reach pending review/export; LLM judge is not sole truth |
| [`V1-FR-014`](PRD.md#v1-fr-014--human-approved-export) | [§10.4 HITL/export](ARCHITECTURE.md#104-hitl-and-export) | N/A — export control is not a source policy | [§12 HITL/export](SECURITY.md#12-hitl-and-idempotent-export) | [§8 Agent evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation), [§12 E3](EVALUATION_PLAN.md#gate-e3--threshold-and-release-candidate-freeze) | [ADR-005](decisions/ADR-005-controlled-langgraph-hitl.md) | M3/M4 | Approve/reject/edit/resume/concurrency/idempotency tests | Exact four-node sequence; only export interrupts; no pre-approval non-idempotent effect; one export per idempotency key |
| [`V1-FR-015`](PRD.md#v1-fr-015--delivery-interfaces) | [§11 Delivery architecture](ARCHITECTURE.md#11-delivery-architecture) | N/A — delivery adapters consume source-aware contracts | [§4 Trust boundaries](SECURITY.md#4-trust-boundaries), [§5 Prompt injection](SECURITY.md#5-prompt-injection-controls) | [§8 Agent evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation) | [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M1A/M4 | M1A-005 commit `5a75b96` provides one explicit-factory FastAPI operation, exact normalized OpenAPI, strict raw-body and closed error contracts, no default live transport, and offline ASGI acceptance. PR #7 hosted checks and final review/audit passed; PR #7 is merged in current baseline `47504a4016f968ed0a0dd10e4280b1a957c15461`. | Streamlit/FastAPI completes reference flow; MCP is read-only; neither bypasses tools |
| [`V1-FR-016`](PRD.md#v1-fr-016--orthogonal-source-outcomes) | [§7.5 Source planning/outcome](ARCHITECTURE.md#75-source-planning-and-outcome-model) | [§6 Shared source contracts](DATA_SOURCES.md#6-shared-source-contracts) | [§13 Availability/degradation](SECURITY.md#13-availability-and-degradation) | [§3.1 Contract cases](EVALUATION_PLAN.md#31-source-planning-and-outcome-contract-cases), [§8 Agent evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation) | [ADR-007](decisions/ADR-007-domain-contracts-and-schema-versioning.md), [ADR-009](decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md) | M1A/M1B/M3 | M1A-004 commit `2f6cb0a` is an ancestor of the current M1A-005-integrated baseline `47504a4016f968ed0a0dd10e4280b1a957c15461`; it covers all seven accepted composite triples, complete-only `no_match`, degraded and bound-reached behavior, visible skips, and acquisition/run persistence ordering. | SourceOutcome exists only for executed sources; only succeeded+complete may yield no_match; partial/failed zero-result is indeterminate; aggregation never upgrades incomplete coverage |

## 3. Non-functional requirements

| PRD requirement ID | Architecture section/anchor | Data-source policy section/anchor | Security section/anchor | Evaluation section/anchor | Governing ADR | Milestone | Test/evaluation evidence | Acceptance criterion |
|---|---|---|---|---|---|---|---|---|
| [`V1-NFR-001`](PRD.md#v1-nfr-001--research-only-safety) | [§15 Deployment boundary](ARCHITECTURE.md#15-deployment-boundary) | [§1 Governing principle](DATA_SOURCES.md#1-governing-principle) | [§1 V1 boundary](SECURITY.md#1-v1-boundary), [§9 Medical boundary](SECURITY.md#9-medical-boundary-handling) | [§8 Safety evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation) | [ADR-001](decisions/ADR-001-v1-reference-domain.md), [ADR-002](decisions/ADR-002-source-semantics.md) | M1A/M3/M4 | Diagnosis/dose/treatment/emergency/individual-risk cases | Prohibited requests produce no clinical guidance/exportable report and show approved research boundary |
| [`V1-NFR-002`](PRD.md#v1-nfr-002--provenance-and-reproducibility) | [§5 Data plane](ARCHITECTURE.md#5-data-plane), [§12 Persistence](ARCHITECTURE.md#12-persistence) | [§8 Snapshot policy](DATA_SOURCES.md#8-snapshot-and-manifest-policy), [§10 Reproducibility](DATA_SOURCES.md#10-freshness-and-report-reproducibility) | [§10 Data integrity](SECURITY.md#10-snapshot-and-data-integrity), [§14 Audit](SECURITY.md#14-observability-and-audit) | [§11 Artifact policy](EVALUATION_PLAN.md#11-reproducibility-and-artifact-policy) | [ADR-003](decisions/ADR-003-storage-and-snapshots.md), [ADR-006](decisions/ADR-006-evaluation-split-and-reproducibility.md) | M1A–M4 | M1A-003B PR `#5` is merged and integrated in approved baseline `5102d56c73b6714d3608a93a47aa31f70ffa1097`. Its integrated gates passed 532 offline unit/contract tests and 236 PostgreSQL integration cases with zero Docker residue. Earlier failed candidates and 193/194 and 218/219 database runs remain preserved as historical evidence rather than current status. See `.delivery/M1A-003B-AUDIT.md`. | Claims trace to snapshot/version/locator and metrics trace to dataset/config/code/raw run |
| [`V1-NFR-003`](PRD.md#v1-nfr-003--external-call-resilience) | [§5.1 Acquisition](ARCHITECTURE.md#51-acquisition), [§8.1 Connectors](ARCHITECTURE.md#81-connector-capabilities) | [§6 Shared source contracts](DATA_SOURCES.md#6-shared-source-contracts) | [§6 Tool security](SECURITY.md#6-tool-security), [§13 Availability](SECURITY.md#13-availability-and-degradation) | [§9 Engineering evaluation](EVALUATION_PLAN.md#9-engineering-evaluation) | [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M1A/M1B | Timeout, retry class, 429, truncation, malformed, partial, cache tests; bounded provider-DTD allowlist and no-resolution regressions | Calls are bounded and only transient failures retry; external DTD metadata is never dereferenced; exhaustion and coverage remain explicit |
| [`V1-NFR-004`](PRD.md#v1-nfr-004--offline-deterministic-tests) | [Evaluation control plane](ARCHITECTURE.md#3-system-context) | N/A — test isolation is repository policy | [§6 Tool security](SECURITY.md#6-tool-security) | [§1 Objective](EVALUATION_PLAN.md#1-objective), [§11 Reproducibility](EVALUATION_PLAN.md#11-reproducibility-and-artifact-policy) | [ADR-006](decisions/ADR-006-evaluation-split-and-reproducibility.md), [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M1A–M4 | CI runs exact unit+contract command with sockets disabled | Directory-based unit/contract suites pass offline; live API remains explicit opt-in |
| [`V1-NFR-005`](PRD.md#v1-nfr-005--replaceable-infrastructure) | [§4 Dependency direction](ARCHITECTURE.md#4-import-and-dependency-direction) | [§6 Shared contracts](DATA_SOURCES.md#6-shared-source-contracts) | N/A — this is an architecture dependency rule | [§1 Objective](EVALUATION_PLAN.md#1-objective) | [ADR-007](decisions/ADR-007-domain-contracts-and-schema-versioning.md), [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M0/M1A/M2/M3 | Import checks and fake connector/retrieval/model adapters | Domain/application contracts expose no infrastructure/provider-native object |
| [`V1-NFR-006`](PRD.md#v1-nfr-006--observability) | [§13 Observability](ARCHITECTURE.md#13-observability) | [§8 Manifest fields](DATA_SOURCES.md#82-required-manifest-fields) | [§14 Observability/audit](SECURITY.md#14-observability-and-audit) | [§9 Engineering evaluation](EVALUATION_PLAN.md#9-engineering-evaluation), [§11 artifacts](EVALUATION_PLAN.md#11-reproducibility-and-artifact-policy) | [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M1A–M4 | Trace completeness, outage trace, redaction, latency/cost artifacts | IDs correlate API/graph/tool/connector/retrieval/citation/review/export without secrets or prohibited payloads |
| [`V1-NFR-007`](PRD.md#v1-nfr-007--local-public-data-boundary) | [§15 Deployment boundary](ARCHITECTURE.md#15-deployment-boundary) | [§8.1 Git boundary](DATA_SOURCES.md#81-git-boundary) | [§1 V1 boundary](SECURITY.md#1-v1-boundary), [§11 PHI boundary](SECURITY.md#11-secrets-and-operational-phi-boundary) | [§8 Safety evaluation](EVALUATION_PLAN.md#8-agent-and-safety-evaluation), [§12 E3](EVALUATION_PLAN.md#gate-e3--threshold-and-release-candidate-freeze) | [ADR-001](decisions/ADR-001-v1-reference-domain.md), [ADR-008](decisions/ADR-008-v1-technology-stack.md) | M0/M3/M4 | No-upload/schema inspection; synthetic name/date/record/address/narrative rejection; log/persistence audit | Suspected PHI fails closed before planning, raw input is not persisted/logged, and no certified de-identification/compliance claim is made |
| [`V1-NFR-008`](PRD.md#v1-nfr-008--measured-claims-only) | [§13 Observability](ARCHITECTURE.md#13-observability) | [§10 Report reproducibility](DATA_SOURCES.md#10-freshness-and-report-reproducibility) | [§14 Audit](SECURITY.md#14-observability-and-audit) | [§11 Artifacts](EVALUATION_PLAN.md#11-reproducibility-and-artifact-policy), [§12 gates](EVALUATION_PLAN.md#12-evaluation-sequence-and-gates) | [ADR-006](decisions/ADR-006-evaluation-split-and-reproducibility.md) | M2–M4 | Metric recomputation, public-claim audit, contamination report | Every published number recomputes from raw results with denominators/failures; no manual metric entry |

## 4. Invariant acceptance scenarios

### M1B-DM-001 Review 009 status

Independent Review 009 binds manifest
`1cfb367f52576a765f7ccf5e3ef5d80053906dd7a8e4dffecb0066728350d3d4`
and returned `FAIL - P0 0 / P1 2 / P2 0`. It verified Review 008 closure, then
reproduced accepted instance drift in 18/35 candidate fields, stable-section
title/ID, locator schema/kind/snapshot/fetch operation, and retained-response
schema/ID/media/bytes/time. Same-class implementation now revalidates all 14
new closed DM-001 model types at public/trusted and nested report/request
boundaries and preserves candidate completeness/termination values without
normalization. Implementation-node gates are focused `335`, domain/OpenAPI
`372`, Ruff/format, MyPy `34`, and diff PASS. Root full validation, Review 010,
and terminal audit remain pending; no PASS, Git, network, integration, or
DM-002 claim is made.

Fresh post-Review 009 root validation completed on the exact 27-path candidate,
including Review 009: domain plus byte-exact OpenAPI `372 passed in 0.76s`;
Ruff PASS; format `67` files; MyPy `34` source files; full offline `951 passed`,
two expected warnings, `80%` coverage in `6.64s`; and diff check PASS. Fresh
complete Review 010 and terminal audit remain pending; no PASS, Git, network,
integration, or DM-002 claim is made.

### M1B-DM-003 implementation candidate

The additive DailyMed report tool and `POST /v1/research/dailymed` map
V1-FR-003, V1-FR-011, V1-FR-015, V1-FR-016, V1-NFR-001,
V1-NFR-002, and V1-NFR-004 to deterministic offline tests. The report tool
constructs trusted planning, performs the existing full report comparator, and
preserves source acquisition references. The API rejects caller planning fields
and closed-schema drift. OpenAPI testing pins the prior PubMed route subtree and
all 76 transitively referenced M1A components by canonical SHA-256 while adding
the separate M1B request/report operation. Live DailyMed execution remains
unauthorized and skipped.

Review history remains exact and distinct:

- Independent Review 001 bound manifest
  `e41abf6ef789cadf33793d9c70bbf1a87490ad71a3ba909b8e52f734ce68690a`
  and returned `FAIL — P0 0 / P1 2 / P2 2`.
- Independent Review 002 bound manifest
  `242b5442db3d6f0c9f43d4c45a05f221f627cc3811bc95b95d7472fd2530b789`
  and returned `FAIL — P0 0 / P1 1 / P2 0`.
- Independent Review 003 bound canonical manifest
  `eeb5d0ffbfd28e6d64b9c20edce0065bd1b63e2857bf4fc25f0c4c7bd5593d8e`
  and returned `FAIL — P0 0 / P1 1 / P2 0`.
- Independent Review 004 bound canonical manifest
  `d149a36a369591963010456664999bb07c114041972ed9b104ff059370875c4a`
  and returned `PASS — P0 0 / P1 0 / P2 0` after verifying the frozen PubMed
  graph and complete enabled DailyMed response requiredness.

The post-Review-004 evidence-persistence candidate was audited under exact
canonical `StringComparer.Ordinal` manifest
`23748ca9d4db441cc79a14da90c2ad18f8b62bd4f5e96ae77a0b2cab5df3447c`.
The case-insensitive alias
`3c9a362a0cb7abb4930d2c4d6d2f78377fe444b9dcabd8f70db62209a7d05d47`
covered the same bytes but is superseded and noncanonical. Terminal Audit 001
returned `FAIL — P0 0 / P1 0 / P2 1` solely because this traceability section
was stale. That P2 metadata defect is mechanically remediated here. Fresh
metadata Review 005 then bound canonical manifest
`17eeaea2c32c86b5766251d21c7ed8e0824ce68a7f745497333349fa0fcedafd`
and returned `FAIL — P0 0 / P1 0 / P2 1`: `docs/SECURITY.md` incorrectly said
the selected plan had no reason fields, while the required nullable
`reason_code` and `reason` fields are present with null values. Its
case-insensitive alias
`5a8ae15acd7cb46cc37f013f4f458d9260c190b5fc3df69785923a4c2e6800ff`
is noncanonical. That documentation-only P2 is mechanically remediated. Fresh
Review 006 bound canonical manifest
`391abc4fc5b8e999295b7468812e6b76ad2aa2da9b85b0e2c46ec11d494f6ded`
and returned `PASS — P0 0 / P1 0 / P2 0`, verifying the exact required-nullable
SECURITY closure and unchanged implementation evidence. Status is
`REVIEW006_PASS_AWAITING_TERMINAL_REAUDIT`; no completion, Git, network,
live-source, integration, merge, or FAERS claim is made. Terminal Re-Audit 002
then bound canonical pre-persistence manifest
`a7ecad26899a2ed1ce46b53e9d839e69459b8e81d946cf6aba4296557f7a0830`
and returned `PASS — P0 0 / P1 0 / P2 0`. Current status is
`TERMINAL_REAUDIT002_PASS_AWAITING_FINAL_BYTE_REBIND_AND_GIT`: persisting the
PASS changes evidence bytes, so this is not completion, commit, integration,
live-source, merge, or FAERS acceptance.

Review 015 remediation constructs positive trusted-fetch authority from explicit
fixture constants and independent stable-label evidence, with no retained/
locator reads. Fresh evidence is report-focused `137 passed`, domain plus
byte-exact OpenAPI `380 passed in 0.90s`, Ruff/format PASS, MyPy `34` source
files, and full offline `959 passed`, two expected warnings, `80%` coverage in
`7.06s`; diff check passed. Review 016 and terminal audit remain pending; no
PASS, Git, network, integration, or DM-002 claim is made.

### M1B-DM-001 Review 016 PASS

[Review 016](reviews/M1B-DM-001-INDEPENDENT-REVIEW-016.md) binds pre-finalization
manifest `567f4663669759a82fc67ccf25419a443b6f2e200e5e5a36226b15c81549d700`
and records `PASS — P0 0 / P1 0 / P2 0`. All prior findings and the full
offline/static/scope boundary passed independent review. Evidence-finalized
bytes now require exact terminal audit; no Git, network, integration or DM-002
claim is made.

### M1B-DM-001 Terminal Audit 001 PASS

[Terminal Audit 001](reviews/M1B-DM-001-TERMINAL-AUDIT-001.md) binds the
pre-audit-record 34-path manifest
`8b0781a741163703467d7c96e732bee24c3854cdacde26405de886b6e1364405`
and records `PASS — P0 0 / P1 0 / P2 0`. All evidence, scope, lock, security,
provenance, compatibility and zero-network gates passed. This record's final
bytes require terminal rebind before staging; no Git/integration or DM-002 claim
is made.

Review 011 same-class remediation removes the public intrinsic-only decision
bypass, requires complete trusted discovery context throughout downstream
comparison, and reconstructs SourceOutcome at the classifier and every report
construction/validation boundary. Fresh evidence is focused `281 passed`,
domain plus byte-exact OpenAPI `380 passed in 0.86s`, Ruff/format PASS, MyPy
`34` source files, and full offline `959 passed`, two expected warnings, `80%`
coverage in `6.85s`; diff check passed. Review 012 and terminal audit remain
pending; no PASS, Git, network, integration, or DM-002 claim is made.

### M1B-DM-001 Review 015 status

[Review 015](reviews/M1B-DM-001-INDEPENDENT-REVIEW-015.md) binds exact 32-path
manifest `9f71d93bf5710043697edfd848dc0a4d7bbb4232729edbcc3a939395f44bcd64`
and records `FAIL — P0 0 / P1 0 / P2 1`. Runtime closure passes; the remaining
P2 is independent positive trusted-fetch fixture construction. Mechanical
fixture closure and Review 016 remain pending; no audit, PASS, Git, network,
integration, or DM-002 claim is made.

### M1B-DM-001 Review 012 status

[Review 012](reviews/M1B-DM-001-INDEPENDENT-REVIEW-012.md) binds exact 29-path
manifest `8445fb3a9c2bed48819b03c8989f4d9ef593f3d7ede874f9010b417697f1d188`
and records `FAIL — P0 0 / P1 1 / P2 0`. The remaining same-class gap permits
omission of authoritative decision/candidate/outcome/manifest context at the
public locator comparator. Mechanical closure and Review 013 remain pending;
no audit, PASS, Git, network, integration, or DM-002 claim is made.

Review 012 remediation makes complete authoritative selection context mandatory
for locator comparison and removes the incomplete intrinsic-report call.
Fresh evidence is locator-focused `137 passed`, domain plus byte-exact OpenAPI
`380 passed in 0.82s`, Ruff/format PASS, MyPy `34` source files, and full
offline `959 passed`, two expected warnings, `80%` coverage in `6.59s`; diff
check passed. Review 013 and terminal audit remain pending; no PASS, Git,
network, integration, or DM-002 claim is made.

### M1B-DM-001 Review 013 status

[Review 013](reviews/M1B-DM-001-INDEPENDENT-REVIEW-013.md) binds exact 30-path
manifest `c5ac09050724eab58b489b859d6a34d9e355ecca2adfd74bc843faf72396b959`
and records `FAIL — P0 0 / P1 1 / P2 0`. Public retained/locator comparators
still require the existing trusted fetch acquisition reference to reject a
coherently forged chain. Mechanical closure and Review 014 remain pending; no
audit, PASS, Git, network, integration, or DM-002 claim is made.

Review 013 remediation supplies a canonical request-owned nonserialized trusted
fetch-evidence row of existing identity types and closes acquisition, attempt,
manifest, member, link, raw-artifact, and raw-hash binding without mutual
self-authentication. Fresh evidence is focused `281 passed`, domain plus
byte-exact OpenAPI `380 passed in 0.86s`, Ruff/format PASS, MyPy `34` source
files, and full offline `959 passed`, two expected warnings, `80%` coverage in
`6.80s`; diff check passed. Review 014 and terminal audit remain pending; no
PASS, Git, network, integration, or DM-002 claim is made.

### M1B-DM-001 Review 014 status

[Review 014](reviews/M1B-DM-001-INDEPENDENT-REVIEW-014.md) binds exact 31-path
manifest `7ba32e4738a45f990b3b6f0fde6c2d34b9a1062aed8d6f638824479739f61274`
and records `FAIL — P0 0 / P1 1 / P2 0`. Public retained/locator comparison
must reassert the frozen distinct acquisition, distinct snapshot, and strictly
later fetch ordinal relationship. Mechanical closure and Review 015 remain
pending; no audit, PASS, Git, network, integration, or DM-002 claim is made.

Review 014 remediation makes public retained/locator comparison require a
different fetch acquisition ID, different snapshot, and strictly later ordinal
than authoritative discovery. Fresh evidence is focused `281 passed`, domain
plus byte-exact OpenAPI `380 passed in 0.88s`, Ruff/format PASS, MyPy `34`
source files, and full offline `959 passed`, two expected warnings, `80%`
coverage in `7.16s`; diff check passed. Review 015 and terminal audit remain
pending; no PASS, Git, network, integration, or DM-002 claim is made.

| Invariant | PRD requirements | Architecture anchor | Policy anchors | Evidence | Acceptance |
|---|---|---|---|---|---|
| Online research does not publish or mutate the offline index | FR-006, FR-008, FR-012; NFR-005 | [INV-001](ARCHITECTURE.md#inv-001--online-research-cannot-mutate-the-offline-index) | [Storage ADR](decisions/ADR-003-storage-and-snapshots.md) | Online-flow integration test with index mutation spy/permissions | No publish/rebuild/delete/mutation call; missing/stale index yields bounded operational outcome |
| Deleting Qdrant does not delete provenance | FR-006; NFR-002 | [INV-002](ARCHITECTURE.md#inv-002--qdrant-deletion-cannot-delete-provenance) | [Data integrity](SECURITY.md#10-snapshot-and-data-integrity), [Storage ADR](decisions/ADR-003-storage-and-snapshots.md) | Destructive local integration test against disposable Qdrant fixture | Snapshot, manifest, PostgreSQL lineage, reports, and reviews remain intact |
| Qdrant rebuilds from verified snapshots and PostgreSQL metadata | FR-006, FR-008; NFR-002 | [INV-003](ARCHITECTURE.md#inv-003--qdrant-is-rebuildable) | [Manifest policy](DATA_SOURCES.md#8-snapshot-and-manifest-policy), [Retrieval ADR](decisions/ADR-004-qdrant-hybrid-retrieval.md) | Clear/rebuild/recompare IDs and index version | Rebuilt index has deterministic source/chunk IDs and declared configuration |
| Partial source failure remains visible | FR-011, FR-012, FR-016; NFR-003 | [INV-004](ARCHITECTURE.md#inv-004--partial-source-failure-remains-visible) | [Availability](SECURITY.md#13-availability-and-degradation), [Source contracts](DATA_SOURCES.md#6-shared-source-contracts) | Tool-double partial/unavailable report tests | Source and run triads, warning, and as-of time survive into final report; no complete/no-evidence claim |
| No substantive claim survives failed citation gate | FR-009, FR-013; NFR-001 | [INV-005](ARCHITECTURE.md#inv-005--failed-citation-claims-cannot-survive) | [Citation security gate](SECURITY.md#7-two-stage-citation-and-claim-gate), [Citation evaluation](EVALUATION_PLAN.md#7-claim-and-citation-evaluation) | Stage-1 mutation, uncertain, unsupported, and adjudication tests | Claim is removed or report stays non-exportable; zero gate escapes |

## 5. M0 consistency acceptance

M0 remediation is ready for independent re-review when:

- all twenty-four PRD requirements appear exactly once in Sections 2–3;
- every requirement has exact architecture, data, security, evaluation, ADR,
  milestone, evidence, and acceptance references;
- genuine irrelevance is explicitly `N/A — reason`;
- ADR-001 through ADR-008 contain owner approval and independent-review
  metadata without treating the reviewer as approval authority;
- the 60-case split, three-dimension source outcomes, two-stage citation gate,
  export-only HITL, PHI boundary, and invariant scenarios are consistent;
- repository runtime/configuration contains no V1 Redis service, volume,
  dependency, or environment variable;
- unresolved executable decisions remain behind `ME-000A` through `ME-000D`;
- no MedEvidence business implementation exists;
- independent re-review records PASS before owner approval becomes effective.

### M1B-DM-001 Review 010 status

[Review 010](reviews/M1B-DM-001-INDEPENDENT-REVIEW-010.md) binds exact manifest
`6955add1ad6e5f0d58517a749fb8b9f7b41fc1c384784ca8e11da8194b97e8e0`
and records `FAIL - P0 0 / P1 1 / P2 0`. Public method calls still accepted
drifted warning, candidate, trusted outcome/decision, retained, locator, and
report-context instances. The mechanically dependent remediation reconstructs
complete self and argument data at each affected DM-001 factory, projection,
and comparator. No schema, dependency, network authority, or DM-002 scope is
added. Fresh validation, Review 011, and terminal audit remain pending.

Fresh post-remediation evidence is: domain plus byte-exact OpenAPI `373 passed
in 0.82s`; Ruff PASS; format `67` files; MyPy `--no-incremental` PASS for `34`
source files; full offline `952 passed`, two expected warnings, `80%` coverage
in `6.64s`; and diff check PASS. Review 011 and terminal audit remain pending;
no PASS, Git, network, integration, or DM-002 claim is made.

### M1B-FAERS-003 implementation candidate status

The candidate adds a trusted-execution FAERS aggregate report builder, an
optional injected `POST /v1/research/faers` adapter, truthful enabled OpenAPI,
offline API integration coverage, and an unconditionally disabled live-smoke
harness. It preserves the exact statistical unit, three-PT set, unfiltered role
policy, query/date/bounds identity, aggregate-only privacy boundary, and full
mandatory limitations. PubMed and DailyMed compatibility remain explicitly
pinned.

Review001 recorded `FAIL - P0 0 / P1 2 / P2 0`; remediation cycle 1/3 closed
raw integer type coercion and FAERS-route OpenAPI over-admission. Review002 then
recorded `PASS - P0 0 / P1 0 / P2 0`. Terminal Audit001 found no candidate
defect but refreshed ignored coverage outputs; strict read-only Re-Audit002
then recorded `FAIL - P0 0 / P1 0 / P2 1` for the stale pending-status
paragraph removed by metadata correction. Strict read-only Re-Audit003 then
recorded `FAIL - P0 0 / P1 0 / P2 1` because delivery still said staging was
zero despite the disclosed stage-and-unstage sequence. That accounting is now
corrected. Fresh read-only final-byte rebind remains pending. No commit, push,
PR, merge, integrated verification, completion, or CADEC execution is claimed.
Medical-source requests are zero. CADEC-001 and CADEC-002 are integrated at
merge commits `af111b8efce0d2a47df4c3ba20f213a812ca12da` and
`a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`, respectively. This FAERS record
makes no CADEC-003 completion claim.

### M1B-DM-001 Review 011 status

[Review 011](reviews/M1B-DM-001-INDEPENDENT-REVIEW-011.md) binds exact 28-path
manifest `564e352be9ad2470c58be20156036c9f66f8aa90ad9964048f085dc6d5de254b`
and records `FAIL — P0 0 / P1 2 / P2 0`. The remaining same-class defects are
caller-controlled intrinsic decision validation and invalid existing
`SourceOutcome` acceptance by the classifier/report-construction boundary.
Remediation and Review 012 remain pending; no audit, PASS, Git, network,
integration, or DM-002 claim is made.

### M1B-CADEC-001 integrated status

CADEC-001 feature commit
`51bbe29a94aa3a16af5d55be01b06f6aa331ab44` was integrated by merge commit
`af111b8efce0d2a47df4c3ba20f213a812ca12da` through PR #19. Its immutable
failure history is preserved; independent closure is `PASS` with
`P0 0 / P1 0 / P2 0`, terminal audit is `PASS` with `0/0/0`, and audited
aggregate identity is
`35a4d2349410c16209197c24e1900ca28067de993276d2c865be082c61548482`.
PR quality run `31726952106` recorded `windows-quality` and `compose-config`
as `SUCCESS`; merged-main quality run `31727139728` was `SUCCESS`.

### M1B-CADEC-002 integrated loader status

CADEC-002 feature commit
`03fffef7ad8f68a9ca36c4961a5264b2e0b295ff` was integrated by merge commit
`a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a` through PR #20. Immutable Review
001 remains `FAIL` with `P0 0 / P1 2 / P2 0`; one remediation batch closed both
findings, independent closure is `PASS` with `0/0/0`, and terminal audit is
`PASS` with `0/0/0`. Audited aggregate identity is
`d307456bcfb4b5cf20392d93e922fb75d0d5684d9e5064c8a811ac960f973d9a`.
PR run `31748194823` and merged-main run `31748381436` both recorded
`windows-quality` and `compose-config` as `SUCCESS`.

The integrated loader/parser is the Owner-frozen Option E final executable M1B
CADEC surface. It preserves 1,250/1,248 canonical/admitted documents; exact
exclusions `DICLOFENAC-SODIUM.7` and `LIPITOR.221`; five malformed rows;
2/44/45 visible limitations; two exact empty documents (`LIPITOR.40` and
`VOLTAREN-XR.9`) with zero rows across original, MedDRA, and SCT; 24,478
provider-gold annotations and locators partitioned 9,089/6,300/9,089; the sole
exact CP1252 exception; split 992/119/137; and REDIST, VOCAB,
provider-gold-only, and Option-A lineage. The output is metadata-only and is not
directly retrieval-consumable.

### M1B-CADEC-003 boundary-closeout candidate status

The documentation-only CADEC-003 candidate is based on integrated merge
`a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`. Immutable Review001 is `FAIL` at
`P0 0 / P1 1 / P2 2`. Remediation batch 1/1 was followed by closure-review
`FAIL` at `P0 0 / P1 1 / P2 1` for no-plan overreach and Review001
transcription fidelity. The Owner-authorized additional mechanical correction
is `ADDITIONAL_MECHANICAL_CORRECTION_PENDING_FRESH_REVIEW`; no fresh-review
PASS, terminal audit, commit, completion, or post-terminal marker is claimed.

Exactly one CADEC M1B source plan entry is visible with
`planning_status=skipped_by_policy`,
`reason_code=source_execution_not_authorized`, and reason `CADEC remains
visible in the M1B source plan, but source execution is not authorized under
Option E.` Visibility is distinct from execution. The exact empty
`cadec_query_requests` tuple and unchanged `M1BSourceSection` preserve no
executable request, research-request connector invocation, `SourceOutcome`,
report section, or API/OpenAPI execution. M1B also prohibits structured
retrieval/search, persistence/migration/database ingestion, indexing,
chunking, training, and retrieval evaluation.

Future M2 owns `search_local_adr_corpus` and a text-bearing materializer that
must reread the approved external archive, prove the same immutable identity,
preserve document/annotation/locator/split/Option-A lineage, emit exact chunks
with offsets and hashes, and keep raw text outside Git. This remains subject to
`ME-000C`; it is not authorized or implemented here. Current CADEC-002 output
is not directly retrieval-consumable, and
`READY_FOR_M2-CADEC-RETRIEVAL-CONSUMPTION` is explicitly prohibited. The exact
post-terminal targets `M1B-CADEC-003_COMPLETE`,
`M1B-CADEC_VERTICAL_SLICE_COMPLETE`, and
`READY_FOR_M2-CADEC-RETRIEVAL-PLANNING` remain unachieved targets only.
