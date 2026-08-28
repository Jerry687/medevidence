# M3-002 Successor 002 Closed Validation Composition

## Current status

`AWAITING_TERMINAL_EVIDENCE_AUDIT`

- Work item: `M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION`
- Baseline: `35fd27231cd8042965bf3c4ccf62bd173600e0b5`
- Branch: `codex/m3-002-successor-002-closed-validation-composition`
- Remediation round: `8/10`; Review 009 returned the required zero-finding
  verdict and the candidate is ready for exact-byte rebind and terminal audit.
- Objective: implement one application-owned, deterministic
  `canonical_validate_report` authority and compose it directly into the
  workflow, without admitting or binding any caller-supplied validator, while
  requiring independently persisted proof of canonical Stage-2 assessment
  before formal progression.
- This is a clean successor from the baseline. No successor-001 source or test
  code may be copied, cherry-picked, wrapped, or mechanically continued.
- Rounds 1–8, immutable Reviews 003–008, and the Owner design resolution are
  preserved below. Independent Review 009 passed; exact-byte rebind and
  terminal audit are the next gates.

## Immutable predecessor evidence

- Original failed work item: `M3-002-CITATION-SAFETY-DEGRADATION`.
- Original `stop-002` SHA-256:
  `50f9ea3ef4e3a7f1880ad6e63cca7f330004321ba38212d676b0a9230c9fffa4`.
- Original sidecar SHA-256:
  `c4e89e72897e96d370231324505ce0570a3799b7d200cb778681392041cce9f8`.
- Successor-001 immutable terminal delivery-record SHA-256:
  `15afa69e98d806613f7128a63c02f6c5f4067549a7c811c9f05a67fa41b69b1c`.
- Original candidate and successor-001 are non-integrable historical evidence.
  They may be inspected only for requirements and adversarial regressions.

## Exact expanded 19-path allowlist

Only these paths may change for this work item:

1. `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md`
2. `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md`
3. `docs/decisions/README.md`
4. `docs/TRACEABILITY_MATRIX.md`
5. `src/medevidence/tools/report_validation.py`
6. `src/medevidence/orchestration/contracts.py`
7. `src/medevidence/orchestration/ports.py`
8. `src/medevidence/orchestration/__init__.py`
9. `src/medevidence/orchestration/workflow.py`
10. `src/medevidence/persistence/models.py`
11. `src/medevidence/persistence/repositories.py`
12. `src/medevidence/persistence/__init__.py`
13. `alembic/versions/20260827_01_m3_validation_receipt.py`
14. `tests/unit/tools/test_report_validation.py`
15. `tests/unit/orchestration/test_workflow.py`
16. `tests/unit/orchestration/test_contracts.py`
17. `tests/unit/persistence/test_metadata.py`
18. `tests/integration/persistence/test_migrations.py`
19. `tests/integration/persistence/test_validation_receipts.py`

`tests/unit/orchestration/test_contracts.py` is required because adding
`validation_receipt_ref` is the Owner-authorized durable checkpoint schema
change: ADR-007 requires a versioned serialized-contract regression and exact
`OrchestrationState` schema-version `1.0` to `2.0` compatibility/rejection
evidence.

`src/medevidence/orchestration/report_validation.py` must not be created. Any
twentieth changed repository path is a hard failure. Domain, connector,
ingestion, retrieval, evaluation, API, frontend, MCP, dependency, lock,
fixture, corpus, qrels, metric-contract, and Holdout paths remain outside
scope. The migration may create only the validation-receipt table required by
ADR-016; no unrelated table, column, index, or data rewrite is authorized.

## Trusted and untrusted model

### Trusted

- the exact reviewed application source bytes at the candidate hash;
- trusted static application composition, which selects the application
  adapters and capabilities used by the workflow;
- the one application-owned `canonical_validate_report` function and its
  lexically fixed standard-library/domain primitives;
- the independently durable `ValidationReceiptStorePort` capability selected
  by that trusted composition and its contract that successful save is durable
  before return and load returns only durable store state;
- the independently durable `DraftPersistencePort` capability selected by that
  trusted composition and its contract that successful pending save is durable
  before return and pending load returns only durable store state;
- the existence of an independently persisted receipt row in the
  application-owned validation-receipt store, only after application code has
  reconstructed and verified its exact content and identity;
- the existence of the exact independently persisted pending draft, only after
  application code has reconstructed and bound its persistence identity,
  report identity, and content hash to the approved report state;
- baseline domain and durable Pydantic validators, frozen enums/constants, and
  the eight-node topology; and
- normal Python language semantics while application code/module namespaces
  are not being rewritten by an in-process attacker.

### Untrusted

- every caller, durable checkpoint, scope, task, acquisition, outcome,
  evidence reference, synthesis, validation registry, hash, warning, claim,
  citation, numerical value, comparison, conflict, resolution, and nested
  object;
- every subclass, wrapper, object identity, post-construction mutation, and
  provider/framework-native value;
- every runtime/checkpoint/receipt payload and every value returned by semantic
  evaluation, validation-receipt save/load, pending-draft save/load, approval,
  or export, including every returned `PendingDraftRef`;
- retrieved text, prompts, model output, external documents, and tool output.

Untrusted values never supply a PASS-producing callable. Exact base types and
primitive values are reconstructed on every authority call. Capability output
is data only and cannot select a validator, helper, mapping, factory, binder,
or PASS route.

A fake or caller-selected receipt store that manufactures a self-consistent
receipt without independently durable save violates the trusted
`ValidationReceiptStorePort` capability contract and trusted static composition;
it is outside ordinary runtime DATA injection. The store implementation remains
a replaceable application adapter, but replacement occurs through trusted
composition, not from untrusted workflow state or request data. This boundary
does not add an origin token, binder, callable fingerprint, runtime capability
authentication, or general Python anti-tamper mechanism.

### Explicit non-goals

- No proof is claimed against arbitrary CPython memory modification,
  `function.__code__` replacement, module-global rewriting by already-arbitrary
  in-process code, debugger intervention, or a compromised interpreter.
- No compatibility adapter, validator binder, validator factory-origin proof,
  operation seal, callable fingerprint framework, or generic anti-tamper layer
  will be built.
- No public API/OpenAPI, dependency, model/provider, retrieval/router,
  source/evidence, clinical-safety, or workflow-topology semantic change is
  authorized. ADR-016 authorizes only the exact receipt reference, source-
  neutral receipt/store contracts, immutable PostgreSQL receipt table, and
  repository adapter within the frozen 19-path allowlist above. Exactly 18 of
  those 19 paths currently differ from baseline;
  `src/medevidence/persistence/__init__.py` remains unchanged. No other durable
  schema or persistence change is authorized.
- No live source access, Holdout-20 access, production data, PHI, credentials,
  performance claim, or M3-003 work is in scope.

## Closed authority and composition contract

### The only PASS-producing authority

`src/medevidence/tools/report_validation.py` will define exactly one public
function named `canonical_validate_report`. It accepts one exact frozen
source-neutral primitive request, an explicit mode (`assess` or
`verify_binding`), and, only in assess mode, an untrusted non-PASS-producing
semantic-result capability. It returns one exact frozen audit whose summary is
the sole source of structural, semantic, and safety PASS/FAIL values.

The request contains primitives for run/report identity, exact research scope,
ordered terminal source tasks, acquisitions/outcomes/evidence references,
synthesis references/hash/warnings, and the validation registry containing
claims, citations, evidence authority, numerical facts, semantic expectations,
evaluator identity, comparisons, conflicts, and resolutions. Assess mode also
constructs the semantic content of one `M3_VALIDATION_RECEIPT_V1` receipt;
verify mode consumes only the independently loaded, exactly reconstructed
receipt content and never trusts the checkpoint reference or an inline body as
proof.

The function must:

1. check outer exact type and cardinality before nested traversal;
2. reconstruct every nested value into exact application-owned base records;
3. re-run full `ResearchScope`, outcome, current-run lineage, source-specific,
   FAERS, CADEC, numerical, digest, warning, comparison, conflict, resolution,
   and report-hash rules;
4. complete all Stage 1 checks for all claims before any Stage 2 acquisition;
5. in assess mode acquire and reconstruct exact per-citation semantic results,
   preserving citation/method/version/result/relationship association, apply
   the frozen relationship-aware aggregation, and construct canonical receipt
   content;
6. in verify mode use only the independently loaded receipt plus hash-bound
   current inputs and never invoke the semantic capability;
7. accumulate all gates/reasons and return through one terminal audit
   construction; and
8. have no successful early return, registry method lookup, private module
   helper dispatch, caller callback, factory, binder, subclass trust, or
   alternate/legacy PASS implementation.

### Direct workflow composition

- `ReportValidationPort` is removed from `ports.py` and from workflow
  construction.
- `OrchestrationReportValidation`, `bind_report_validation_operation`, and any
  equivalent adapter/binder are forbidden.
- Trusted static workflow construction selects the application capabilities,
  including the required independently durable `ValidationReceiptStorePort`
  and `DraftPersistencePort`, plus optional `SemanticResultAcquisitionPort`.
  Validation-registry data and every capability return remain untrusted data;
  none supplies a PASS-producing operation.
- The Stage 2 port may return only exact semantic-result primitives. Missing,
  raised, coerced, mismatched, or unexpected results fail closed.
- Workflow code constructs the source-neutral request from primitive fields and
  calls `canonical_validate_report` directly at each validation gate. There is
  no injected validator method, bound operation, operation admission, or
  origin check.
- One non-decision mapper may convert the audit's three booleans and exact
  reason tuple into `ReportValidationState`. It must assert exact equality
  between durable gates/reasons and the audit and contains no independent PASS
  condition. It is the only production construction site for a passing
  `ReportValidationState`.
- Initial validation calls `assess`, constructs a canonical receipt only after
  Stage 1 and Stage 2 finish, persists it immutably, and only then writes
  `validation_receipt_ref` into durable state. Stored gates/reasons must exactly
  equal the assessment audit.
- Pre-save, pre-approval, pre-export/finalization, idempotent exported return,
  and synthesis-bearing terminal resume first reconstruct complete durable
  state, application topology, and the canonical request, then call pure
  evaluator-free `verify_binding` before any pending/receipt-store capability.
  A route carrying a pending draft next loads, reconstructs, and binds that exact
  durable pending row; it then loads, reconstructs, and binds the exact receipt.
  Stored gates/reasons must exactly equal the fresh audit. Only then may the
  workflow invoke an effect or return trusted terminal state.
- A re-created workflow must receive the same primitive registry/evaluator and
  policy identities for the current report. Drift fails binding. Any edit to
  report or validation-relevant state clears `validation_receipt_ref` and
  requires a new assessment and newly persisted receipt.
- Receipt storage uses one source-neutral `ValidationReceiptStorePort` with
  `save_receipt` and `load_receipt` capabilities selected by trusted static
  composition. The capability contract requires independent durable save;
  every returned payload is untrusted data. The application reconstructs the
  exact `ValidationReceipt` contract, recomputes its identity, and performs
  every current-state binding check.
- Pending-draft storage uses one source-neutral `DraftPersistencePort` selected
  by trusted static composition. Every returned `PendingDraftRef` is untrusted,
  exactly reconstructed, and bound to persistence/report/content identity. The
  save route immediately durable-read-backs and binds the saved row before
  publishing a pending-review checkpoint.

### One PASS path / zero alternate paths

Required executable/static evidence:

- exactly one `def canonical_validate_report` in production;
- exactly one terminal audit construction capable of `summary.passed=True`;
- zero `ReportValidationPort`, orchestration validation adapter, binder,
  operation factory, validator registry, compatibility, or legacy PASS paths;
- zero injected callable whose output is interpreted as a gate or PASS;
- all workflow PASS transitions data-dependent on the exact audit returned by
  `canonical_validate_report`, with every formal transition additionally bound
  to an independently loaded receipt created by the canonical assessment path;
  and
- direct reviewer call-graph reachability from initial validation, save,
  approval, export/idempotent return, and terminal resume to that same function.

## Exact data flow

```text
untrusted durable state + untrusted immutable registry data
  -> workflow primitive extraction (no validation decision)
  -> exact source-neutral request construction
  -> canonical_validate_report(ASSESS)
       -> cardinality-first outer checks
       -> exact primitive reconstruction
       -> global Stage 1 structural/source/safety checks
       -> untrusted semantic-result acquisition
       -> exact semantic result reconstruction
       -> relationship-aware aggregation
       -> one audit/summary construction
       -> canonical M3_VALIDATION_RECEIPT_V1 content
  -> immutable save_receipt
  -> checkpoint validation_receipt_ref
  -> [before every effect or terminal trusted return]
       -> reconstruct complete durable state, application topology, and request
       -> canonical_validate_report(VERIFY_BINDING), evaluator calls=0
       -> if pending is present: load_pending(reference)
       -> exact pending reconstruction and report/content binding
       -> load_receipt(reference)
       -> exact receipt reconstruction, identity, and current-state binding
  -> exact durable gate/reason/receipt-reference binding comparison
  -> workflow transition or fail-closed zero-effect rejection
```

No provider object, orchestration object copy, accepted subclass, caller
factory, validator object, or mutable callable crosses into authority.

## Capability invocation and reconstruction table

| Invocation | Immediate pre-check | Primitive input consumed | Result reconstruction and immediate post-check |
|---|---|---|---|
| Workflow construction | Exact application constructor; no validator argument; registry outer type/cardinality copied as primitives | Registry data and Stage 2 capability identity only | No PASS decision; later authority calls fully reconstruct the registry |
| Scope safety | Full durable checkpoint reconstruction; exact current node | Original scope primitives | Exact `ScopeSafetyEvaluation`; full domain validation; selected sources cannot expand |
| Source planning | Full durable checkpoint and permitted safety decision | Exact interpreted scope and decision | Exact ordered plan tuple; one row per selected source; skipped rows visible; tasks only for selected rows |
| Evidence collection | Full durable checkpoint, task/run/attempt/node binding before call | One exact running task, scope, stable attempt | Exact failure or collected-result base type; run/source/attempt/acquisition/outcome/evidence lineage rebuilt before checkpoint |
| Synthesis | Full durable checkpoint; exact source/task equality; every selected task terminal before call | Run/report/scope and ordered terminal task primitives | Exact durable synthesis base type; exact-max cardinality, refs, warnings, and hash primitives checked before state transition |
| Initial canonical validation | Full durable checkpoint and exact validation node; request constructor consumes primitives only | Run/report/scope/tasks/synthesis/registry | Direct `canonical_validate_report(..., mode=assess)`; one exact audit and canonical receipt content; no durable PASS yet |
| Stage 2 result acquisition, if required | Authority has completed global Stage 1 for every claim; exact evaluator identity and per-citation input digest fixed | Exact run/claim/citation/evidence/relationship primitives | Exact base result and enum; citation/method/version/result/relationship aggregate must bind; otherwise no passing receipt |
| Receipt persistence | Canonical assessment PASS; exact receipt marker/content/identity derived; no approval/export call | Exact source-neutral immutable receipt | `save_receipt` persists before the checkpoint reference; exact idempotent replay is allowed, conflicting duplicate/store failure creates no passing durable state |
| Canonical binding preflight | Complete durable/application/topology/request reconstruction; exact route topology; no store capability or effect invoked | Current run/report/content/input/source/evaluator/policy primitives plus stored gates/reasons | Direct evaluator-free `canonical_validate_report(VERIFY_BINDING)`; any invalid state fails before pending/receipt-store access, effect, or trusted return |
| Pending-draft loading and binding | Successful canonical binding preflight; exact pending reference from the rebuilt checkpoint | Pending persistence/report/content identities | `load_pending` result is rebuilt as exact `PendingDraftRef`; missing/foreign/stale/substituted/malformed data fails before receipt loading and every later effect/return |
| Receipt loading and binding | Successful canonical preflight and, when present, exact durable pending binding; nonblank receipt reference | Receipt reference plus current run/report/content/input/source/evaluator/policy primitives | `load_receipt` result is rebuilt as exact base contract; missing/unknown/inline/foreign/stale/different/inconsistent receipt fails before every effect/return |
| Pending-draft save | Complete canonical preflight and receipt binding; no pending save yet | Current run/report/scope/tasks/synthesis/registry/stored validation | Only after receipt-bound canonical PASS may `save_pending` run; returned reference is rebuilt and report/hash-bound, then exact `load_pending` read-back must PASS before checkpoint; failures produce no pending-review checkpoint |
| Export approval | Complete canonical preflight, exact durable pending binding, then exact receipt binding | Current report/hash/destination/tasks/warnings, registry, pending draft, and receipt | Exact review record rebuilt; pending/report/hash/destination/outcomes/warnings bound; failures produce approval=0 |
| Export/finalization | Complete canonical preflight, exact approved topology, exact durable pending binding, then exact receipt binding | Current report/hash/destination/tasks/approval/registry/pending draft/receipt | Exact export record rebuilt and idempotency/approval/report/hash bound; failures produce export/finalization=0 |
| Exported idempotent return | Complete canonical preflight, exact durable pending binding, then exact receipt binding before return | Entire current exported checkpoint, registry, pending draft, and receipt | Exact gates/reasons/ref, pending draft, approval, export record, tasks, warnings, and hash bind; evaluator calls=0 and no effect occurs |
| Synthesis-bearing terminal resume | Complete canonical preflight; pending and receipt binding when progression depends on PASS | Entire terminal checkpoint, registry, pending draft when present, and receipt | Validation-blocked/rejected/exported cross-fields and exact gates/reasons/ref bind; evaluator calls=0 and all effects=0 |
| Edit transition | Full current-state reconstruction and exact edit/review topology | Edited report or validation-relevant primitives | Clear `validation_receipt_ref`, reset validation, and require a new assessment/receipt; never repair or upgrade old receipt |

Every directly callable side-effecting workflow route performs the same durable
and canonical preflight before capability invocation. There is no validate-
after-effect path.

## Frozen regression inventory: original Reviews 001-017

Every row requires a public tool/workflow negative test plus zero semantic or
side-effect calls where applicable.

| Review | Required demonstrated bypass family |
|---|---|
| 001 | Removal metadata with formal content; non-self-binding objects/hash; fail-open FAERS/CADEC policy; per-claim rather than global Stage 1; lost per-citation result association. |
| 002 | Post-admission nested mutation; caller aggregate contradiction; noncanonical whitespace/hash; current-versus-historical evidence separation. |
| 003 | Polymorphic factory postconditions; non-exact semantic result/enum reconstruction; complete target inventory. |
| 004 | Exact-type caller aggregate retained executable authority; enum coercion after outer-only checks. |
| 005 | Instance-method adapter admitted wrappers/subclasses/uninitialized/replacement; exact changed-path evidence. |
| 006 | Class-level replacement of trusted-unbound validator dispatch forged PASS. |
| 007 | Hash omitted citation/warning/comparison/conflict bindings; stale validation export; contextual/contradicting citation sufficiency; open numerical context; non-exact comparability primitives. |
| 008 | Terminal resume skipped binding; evaluator identity absent; contradicting citation sufficiency; numerical fact mismatch; blank comparability; out-of-topology export ordering. |
| 009 | Resume/export reran evaluator; numerical fact lacked exact locator/text/canonical authority. |
| 010 | Ambiguous six-field text; incomplete pure lineage verification; contradictory validation-blocked/rejected fields. |
| 011 | FAERS bounded-count/disclaimer bypass; quantity phrase bypass; missing durable lineage/cross-task uniqueness; foreign rejected decision; scope absent from authority. |
| 012 | Finite lexical quantity detector bypass; fabricated/swapped validation-blocked reasons. |
| 013 | Replaceable `_assess`; dataclass subclass bypass with stale identity/arbitrary nested state. |
| 014 | Captured authority still resolved mutable private helpers and registry methods. |
| 015 | Captured helper chain resolved mutable types/templates/identities; nested subclasses serialized before exact admission. |
| 016 | Adapter dynamically resolved prewalk/dispatch/mapping helpers; incomplete `ResearchScope` reconstruction. |
| 017 | Foreign-run zero-evidence no-match; FAERS/CADEC reconstruction parity; selected/executed task mismatch; oversized duplicate authority not reviewable. |

## Frozen regression inventory: successor-001 Reviews 001-010

| Review | Required demonstrated bypass or evidence gap |
|---|---|
| S001-001 | Replaced adapter validate/verify forged PASS; stale synthesis reached save/approval; incomplete public FAERS/CADEC numerical matrices. |
| S001-002 | Workflow callable fields, adapter operation, and tool registry/evaluator were replaceable and enabled coherently rebound unassessed export. |
| S001-003 | Public closure cells exposed replaceable `WeakKeyDictionary` authority maps. |
| S001-004 | Mutable canonical policy dictionaries bypassed FAERS limitations; writable adapter captured-operation cells exported invalid content. |
| S001-005 | Missing pending draft bypassed persistence before approval/export; policy/code-constant mutation bypassed FAERS limitation; malformed evidence hash passed. |
| S001-006 | Exported checkpoint omitted exact pending draft; executed FAERS/CADEC zero-evidence/no-claim report omitted governed source warning. |
| S001-007 | Approved checkpoint rewound into collection; mutable base durable validator bypassed exported pending-draft checks; blank warning code passed. |
| S001-008 | Public synthesis/canonical reconstruction admitted 101 warnings despite durable max 100. |
| S001-009 | Workflow instance `__dict__`, mutable dispatch, and shadowable preflight enabled foreign approval/export and missing-pending return; direct save persisted before preflight; exact-max graph lacked a positive PASS. |
| S001-010 | Binder proved shape/seal/closure membership rather than canonical origin and admitted an independently constructed matching type; max+1 reconstruction asserted generic wrong-type rather than cardinality-specific errors. |

### Mandatory minimum executable cases

- All cross-review families: citation/source/version/snapshot/hash/locator drift;
  prompt injection; complete, partial, unavailable, matches, no-match, and all
  seven valid outcome triples plus invalid triples; warning suppression and
  substitution; removal/adjudication; stale run/scope/evaluator/hash; all 11
  comparison dimensions and five conflict outcomes; numerical six-field,
  locator, retained-text, fact/context drift; foreign acquisition/outcome/
  evidence/decision/reason/scope; duplicate evidence/tasks; and corrupt normal,
  blocked, rejected, approved, exported, edit, and idempotent resumes.
- Exact selected-source equality: missing, extra, duplicate, nonterminal,
  source-mismatched, and out-of-order tasks; exactly one terminal task/outcome
  per selected source before finalization.
- Foreign-run `succeeded/complete/no_match` with zero evidence and zero claims.
- FAERS and CADEC reconstruction with every numerical field changed one at a
  time, every source restriction re-executed, and semantic calls=0.
- Mandatory `faers_mandatory_limitations` and
  `cadec_mandatory_limitations` warnings for every executed source, including
  zero-evidence/no-claim outcomes; degradation warnings remain additive.
- Post-construction mutation and subclass matrices at every nested request and
  result type. Caller-created operation/binder/factory attacks are replaced by
  absence proofs: no validator object is accepted anywhere.
- Workflow has no validation adapter, validation port, callable validator
  field, mutable dispatch registry, or instance-shadowable validation helper.
  Foreign approval, invalid topology, missing pending draft, and stale binding
  produce collector/persistence/approval/export=0.
- Direct runtime and AST call-graph proof that every validation gate reaches
  the same `canonical_validate_report` and that no second PASS producer exists.
- Review 003 P1-01 receipt cases: forged passing checkpoint with no receipt;
  valid-looking inline-only receipt; foreign-run receipt; stale report-hash
  receipt; different-validation-input receipt; canonical assessed and persisted
  valid receipt; edit invalidation followed by required reassessment. Every
  invalid case has semantic calls during verify=0 and persistence/approval/
  export/finalization calls=0.
- Review 003 P1-02 relationship cases: supported `supports` may aggregate
  supported; supported `supports` plus semantically confirmed `contradicts`
  cannot aggregate supported and defaults unresolved to `uncertain`;
  `context_only` alone cannot support; existing explicit governed human/
  conflict resolution remains valid and recorded. No count, score, confidence,
  or source weighting is used.

## Cardinality-first exact-max contract

Outer exact tuple/base-type and length checks occur before element-type, graph,
identity, hash, or semantic checks. At the exact maximum, processing continues
and a fully valid graph can PASS. At max+1, construction and every public
authority route fail with the exact cardinality-specific code; a generic
wrong-type/graph error is not acceptable.

| Collection | Maximum | Required max+1 code |
|---|---:|---|
| Terminal task evidence references | 100 | `task_evidence_cardinality_exceeded` |
| Synthesis claim references | 200 | `synthesis_claim_cardinality_exceeded` |
| Synthesis citation references | 400 | `synthesis_citation_cardinality_exceeded` |
| Synthesis comparison references | 100 | `synthesis_comparison_cardinality_exceeded` |
| Synthesis conflict references | 100 | `synthesis_conflict_cardinality_exceeded` |
| Synthesis warning codes | 100 | `synthesis_warning_cardinality_exceeded` |
| Registry claims and resolutions | 200 each | `registry_claim_cardinality_exceeded` / `registry_resolution_cardinality_exceeded` |
| Registry citations, semantic expectations, evidence | 400 each | corresponding `registry_*_cardinality_exceeded` |
| Registry comparisons and conflicts | 100 each | corresponding `registry_*_cardinality_exceeded` |

Required boundary evidence includes exact 100 distinct canonical warnings with
a correctly rebound hash and public assess/verify PASS; 101 warnings reject
before Stage 1/evaluator. One genuinely valid maximum graph must assert
`audit.summary.passed is True`, no reasons, every claim accepted, pure verify
PASS, and the exact expected evaluator call count. Every max+1 parameter must
assert its specific code and zero evaluator calls.

## Compactness, call graph, and coverage evidence

- `tools/report_validation.py` physical LOC ceiling: `1100` lines.
- Total added production LOC across tools, ports, and workflow: record exact
  additions/deletions and keep below `1500` added lines. Generated or compressed
  compatibility code does not satisfy compactness.
- Record exact physical lines, bytes, and SHA-256 for every changed production
  and test path at each review candidate. After the delivery record is
  finalized, an external exact-byte manifest must bind all 19 allowlisted
  paths, including the delivery record and governance files; no self-
  referential hash is stored in the record.
- Produce an AST inventory of production function/class definitions, all calls
  to `canonical_validate_report`, all `ReportValidationState` PASS
  constructions, all gate writes, and all references to forbidden validator/
  adapter/binder names.
- Produce a direct runtime call graph for initial assess, save, approval,
  export, idempotent return, and each synthesis-bearing terminal resume. The
  graph must have one PASS-producing root and zero alternate roots.
- Focused coverage must report `100%` line coverage for the new tools module and
  every new/changed workflow validation branch. Overall repository coverage
  remains subject to the ordinary full-suite gate; green tests without the
  call-graph and coverage evidence are insufficient.
- Independent review must inspect source reachability directly and reproduce at
  least the operation-origin absence proof, a side-effect ordering attack, the
  100/101 warning boundary, one max+1 cardinality-first error, and the valid
  exact-maximum PASS.

## Work graph, ownership, and stop conditions

| Node | Dependency | Sole write ownership | Required output / command | Stop condition |
|---|---|---|---|---|
| G3 receipt design freeze | Review 003 plus Owner decision | Four governance paths only | ADR-016 and corrected exact 19-path scope; Round 3 may begin | Any unresolved receipt semantic |
| E3 discovery | G3 | Read-only | Exact contract, persistence, migration, and effect call sites | Unsafe/ambiguous baseline |
| I3 authority/aggregation | E3 | `src/medevidence/tools/report_validation.py` | Receipt semantic content and relationship-aware aggregate through the one authority | Alternate PASS path or source-semantic expansion |
| I3 contracts/ports | E3 | orchestration `contracts.py`, `ports.py`, `__init__.py` | Source-neutral receipt/ref/store contracts only | Public API, vendor-object, or dependency expansion |
| I3 persistence | Contracts | persistence `models.py`, `repositories.py`, `__init__.py`; exact new migration | One immutable receipt table and save/load adapter | Any unrelated schema/table/column/index |
| I3 workflow | Authority, contracts, persistence ports | `src/medevidence/orchestration/workflow.py` | Assess→persist→ref; complete local reconstruction→pure verify→pending bind when present→receipt bind before every effect/return; post-save pending read-back; edit invalidation | Replay Stage 2 or alternate authority required |
| T3 tool/workflow/contracts | Authority, contracts, workflow | Exact tool, workflow, and orchestration-contract unit-test paths | Review-003 A–K, `OrchestrationState` v1→v2 contract evidence, all retained regressions, and zero-effect matrices | Missing frozen behavior |
| T3 persistence | Contracts, persistence | Exact unit metadata, migration, and receipt integration test paths | DDL, immutable save, exact replay, conflict, load/not-found, rollback | Live/external service requirement |
| J3 validation join | All I3/T3 nodes | No new source owner | Focused, integration, call graph, LOC/coverage, full offline, static/scope gates | Any failure joins same-design remediation |
| R3 independent review | J3 | Read-only | Trace assess→save receipt→ref and every effect/return through local reconstruction→pure verify→pending bind when present→receipt bind; reproduce forged checkpoint and contradiction | Design insufficiency -> stop; same-design finding -> next round |
| M3-M10 remediation | Batched review finding | One explicitly reassigned allowlisted path per node | Same-design fix, regression, and fresh ordered gates | Round 10 exhausted or genuine hard boundary |
| B exact-byte rebind | Review PASS | Delivery record only | Changed-path hashes in-record, then external finalized exact 19-path manifest | Any byte drift |
| A terminal audit | Rebind | Read-only independent auditor | Evidence, scope, network, Git, candidate identity verdict | Any missing/contradictory evidence |
| C Git lifecycle | Terminal `PASS — P0 0 / P1 0 / P2 0` | Exact audited paths only | Stage, commit, push, Draft PR, CI, Ready, merge, post-merge verification, reconciliation | Any audited-byte or CI drift |

Only one writer owns a path at a time. Authority and contract work may run in
parallel after discovery because their paths do not overlap. Persistence waits
for the receipt/store contract; workflow waits for authority and contracts;
tests wait for their production owner; validation joins all writes.

## Deterministic commands and ordered gates

From the successor-002 repository root, with the successor `src` first on
`PYTHONPATH` and no dependency sync/download:

```text
uv run --locked --no-sync pytest tests/unit/tools/test_report_validation.py tests/unit/orchestration/test_workflow.py tests/unit/orchestration/test_contracts.py tests/unit/persistence/test_metadata.py tests/unit/domain/test_source_outcomes.py tests/unit/domain/test_reports.py tests/unit/domain/test_provenance.py tests/unit/test_dependency_boundaries.py --disable-socket
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
uv run --locked --no-sync pytest tests/integration/persistence/test_migrations.py tests/integration/persistence/test_validation_receipts.py
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv lock --check --offline
```

Required order:

1. focused adversarial tests and exact call-graph/LOC/coverage evidence;
2. full offline unit/contract suite;
3. Ruff;
4. format check;
5. strict MyPy;
6. offline lock and applicable local PostgreSQL migration/persistence checks;
7. exact 19-path scope/diff, secret, and dependency-file checks;
8. fresh offline dependency inventory with external manifest and zero network;
9. independent review;
10. exact-byte rebind; and
11. terminal evidence audit.

No earlier successor result may be reused as current-candidate PASS evidence.
The only acceptable final verdict is:

`PASS — P0 0 / P1 0 / P2 0`

## Remediation, Git, network, and Holdout boundaries

- Up to ten batched same-design remediation rounds are authorized. Rounds 1–2
  remain consumed history; Rounds 3–10 may close batched receipt-design findings
  and return to the full ordered validation sequence.
- Do not stop for same-design P0/P1/P2 findings while a round remains. Stop with
  `OWNER_DECISION_REQUIRED` only when Round 10 is exhausted, the reviewer
  demonstrates that the durable-receipt design itself is insufficient, a
  twentieth path is required, or a genuine dependency/public API/OpenAPI/
  unrelated schema/security/governance/clinical-safety/live-source/Holdout/
  unsafe-repository boundary is reached.
- Unit, contract, lint, type, architecture, dependency, and evidence work is
  offline. Medical-source, model/provider, retrieval, advisory, dependency-
  download, and all other network traffic is unauthorized.
- Holdout-20 remains sealed. No live PubMed, NCBI, DailyMed, FAERS, CADEC, or
  other medical-source request is permitted.
- This design-freeze node performs no staging, commit, push, PR, merge, rebase,
  reset, clean, branch deletion, history rewrite, or remote operation. Existing
  lifecycle authority becomes active only after fresh review, exact-byte
  rebind, and terminal `PASS — P0 0 / P1 0 / P2 0`: stage exact audited paths,
  commit, push, Draft PR, hosted CI, Ready, merge, post-merge verification,
  control-plane reconciliation, then start the separately authorized M3-003.
  Normal GitHub lifecycle network is authorized only for that post-PASS
  sequence; medical-source, model, package-download, and Holdout traffic remain
  prohibited.

## P1 evidence

- Baseline HEAD and branch were checked read-only.
- The baseline worktree was clean before this record was created.
- Successor-001 and original stopped evidence were inspected read-only.
- Source/test implementation: not started.
- Tests and validation commands run: none.
- Network operations: `0`.
- Git staging, commit, push, PR, merge, rebase, reset, clean, and remote
  operations: `0`.

Current status:
`DURABLE_RECEIPT_DESIGN_FREEZE_COMPLETE_ROUND_3_IN_PROGRESS`.

No implementation PASS, test PASS, review PASS, audit PASS, rebind PASS, Git
integration, or final verdict is claimed.

## Pre-review implementation evidence — candidate 001

This section supersedes the initial freeze status for the current implementation
candidate without rewriting that historical freeze evidence.

Current status:
`IMPLEMENTED_AWAITING_INDEPENDENT_REVIEW_001`.

This is a pre-review status only. It is not `PASS`, does not consume or replace
independent review, does not constitute exact-byte rebind or terminal audit, and
does not authorize or claim any Git integration operation.

### Implemented closed design

- Production contains exactly one `canonical_validate_report` definition and
  one terminal `ReportValidationAudit` construction capable of returning the
  sole canonical PASS summary.
- `ControlledOrchestrationWorkflow` composes that application authority
  directly. It has exactly two production call sites: initial
  `ValidationMode.ASSESS` and pure `ValidationMode.VERIFY_BINDING`.
- There is exactly one workflow validation-request builder and exactly one
  semantic-result acquisition expression. The semantic capability supplies
  untrusted result data only and is reached only after the complete global
  Stage 1 barrier.
- The constructor accepts immutable `ValidationRegistryInput` data and a
  `SemanticResultProvider`. It accepts no runtime validation operation,
  `ReportValidationPort`, validator object, adapter, binder, factory, origin
  proof, seal, callable fingerprint, or alternate PASS authority.
- Workflow instances have slots and no instance dictionary or `_dispatch`.
  No critical validation helper is selected through caller-controlled dynamic
  lookup.
- Initial validation, pending-draft save, approval, export, idempotent exported
  return, and synthesis-bearing terminal resume all reach the same application
  authority. Save, approval, and export invoke their capabilities only after
  complete durable reconstruction, application topology/binding validation,
  and canonical verification. Invalid state produces zero downstream effects.
- The durable mapping creates a non-default `ReportValidationState` only from
  the canonical summary's three booleans and exact reason tuple, with an
  equality postcondition. Default-state constructions cannot produce PASS.
- Registry, checkpoint, task, acquisition, outcome, evidence, synthesis,
  semantic-result, approval, pending-draft, and export values remain untrusted
  data and are rebuilt from primitives. No source, evidence, public API,
  OpenAPI, persistence, retrieval, router, corpus, qrels, metric-contract, or
  dependency semantics changed.

Direct application call graph:

```text
initial validate
  -> durable/application preflight
  -> build primitive request
  -> canonical_validate_report(ASSESS)
       -> all Stage 1 claims
       -> optional one semantic acquisition per bound citation
       -> one terminal audit/PASS root

save / approval / export / idempotent return / terminal resume
  -> durable/application preflight
  -> build primitive request with stored gates/reasons
  -> canonical_validate_report(VERIFY_BINDING)
  -> exact stored-binding equality
  -> capability or pure return only after PASS
```

### Exact current code/test bytes before Review 001

These hashes were recomputed from disk after the ordered pre-review gates. They
bind the five code/test/ports paths for the candidate presented to Review 001;
the delivery record itself is intentionally not self-bound here.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `src/medevidence/tools/report_validation.py` | 1096 | 62334 | `5532eb77eefc77c53ae019ff8bb25814873a79b5677c0cce4ad30956a755b733` |
| `src/medevidence/orchestration/workflow.py` | 953 | 40963 | `90647d22e5ec569970138f48ab5455ed030edea9a7542a56239d23f4448adeaf` |
| `tests/unit/tools/test_report_validation.py` | 1639 | 60243 | `82ef366f117ac7ad0f2c1141d72f7c6317e628e1ad848b6aac8587bbd0653687` |
| `tests/unit/orchestration/test_workflow.py` | 1585 | 59046 | `b38c935b73b32e6daf93765984cf33324b293b32c7e14377f68901f2b40d11fd` |
| `src/medevidence/orchestration/ports.py` | 120 | 3159 | `90fc6f9bdcc99f013c142c34507858572f4e679cb9f141ce89ab03025c35902a` |

The canonical authority is exactly 1096 physical lines, below the frozen 1100
line ceiling. `ports.py` is allowlisted but byte-unchanged from baseline. No
change was made to `contracts.py`, domain, connector, ingestion, retrieval,
evaluation, API, frontend, MCP, dependency, lock, fixture, corpus, qrels, or
metric-contract paths.

### Frozen regression inventory mapped to executable tests

| Frozen family | Executable evidence |
|---|---|
| Exact outer/nested types, mutation, primitive grammar, subclass and nonprimitive rejection | `test_mutation_and_exact_runtime_base_types_are_reconstructed`, `test_constructor_cardinality_guards_reject_non_tuples`, `test_primitive_shape_and_grammar_rejections`, `test_identity_helpers_reject_nonprimitive_nested_values`, reconstruction-defense matrices |
| Exact current run/scope/task/acquisition/outcome/evidence ownership, including zero-evidence no-match | `test_foreign_run_zero_evidence_no_match_fails`, `test_selected_source_task_equality`, `test_stage1_reason_branches_are_executable`, workflow corrupt-resume and preflight matrices |
| All seven terminal outcome triples, partial/unavailable/no-match distinctions, bounds and warnings | `test_all_seven_terminal_outcome_triples`, `test_invalid_outcome_and_no_match_semantics`, `test_outcome_reconstruction_defenses`, M3-001 retry/partial/unavailable workflow tests |
| FAERS/CADEC closed semantics, numerical six-field reconstruction and mandatory limitations | `test_faers_numerical_reconstruction_is_exact`, `test_faers_fact_and_numerical_claim_text_are_reconstructed`, `test_cadec_numerical_claim_and_fact_are_forbidden`, `test_source_warning_is_required_even_without_evidence_or_claims`, `test_zero_evidence_source_warnings_are_bound_without_fabrication` |
| Citation/evidence lineage, version/snapshot/hash/locator/record drift and supporting-citation sufficiency | `test_evidence_citation_lineage_drift`, `test_task_evidence_reconstruction_defenses`, `test_stage1_reason_branches_are_executable`, `test_audit_reason_families_are_fail_closed` |
| Global Stage 1 before semantic acquisition, evaluator identity and pure verification | `test_global_stage1_barrier_and_evaluator_identity`, `test_pure_verify_reproduces_reasons_and_never_calls_provider`, `test_stage1_failure_and_pure_binding_failure_invoke_no_new_evaluator_or_effect` |
| Semantic result exact type/enum/method/version/result association and adjudication/removal | `test_closed_semantic_resolution`, `test_stored_validation_and_semantic_provider_failures`, maximum-graph semantic traces, Stage 1 reason matrix |
| Numerical fact/context exact authority and claim binding | FAERS field matrix, `test_task_evidence_reconstruction_defenses`, `test_faers_fact_and_numerical_claim_text_are_reconstructed`, `test_stage1_reason_branches_are_executable[numerical_authority]` |
| All 11 comparability dimensions and five conflict outcomes, hash/classification drift | `test_all_dimensions_and_conflict_outcomes`, `test_claim_comparison_reconstruction_defenses`, `test_comparison_graph_reason_branches_are_executable` |
| Exact maxima and cardinality-first max+1 errors | `test_exact_maximum_graph_passes`, `test_max_plus_one_has_specific_cardinality_error`, `test_warning_100_passes_and_101_fails` |
| Pending/approval/export/report-hash binding, exact topology, edit and idempotent resume | M3-001 happy/retry/edit/approval/idempotency tests plus `test_invalid_state_preflight_precedes_every_direct_effect`, `test_corrupt_exported_resumes_fail_before_idempotent_return`, `test_terminal_disposition_fields_and_decisions_are_revalidated` |
| Caller capability output, wrapper/subclass and unknown-contract rejection | `test_collection_mapping_rejects_unknown_and_subclass_results`, `test_untrusted_effect_results_are_reconstructed_and_rejected` |
| One authority, no runtime operation/port/adapter/binder/factory, direct reachability | `test_authority_ast_and_dependency_boundary`, `test_closed_application_composition_ast_and_runtime_inventory` |

The historical original Review 001-017 and successor-001 Review 001-010
families remain represented by these cross-family matrices; no predecessor code
was copied or mechanically continued.

### Ordered deterministic validation evidence

All application/test/static checks below used the successor worktree source
first, existing locked local dependencies, socket-disabled offline execution,
and no dependency synchronization or download.

1. Tools authority focused suite: `120 passed`.
2. Workflow plus tools suites: `167 passed`.
3. Focused M3/domain/dependency-boundary suite: `623 passed`.
4. Full offline `tests/unit tests/contract --disable-socket` suite:
   `2191 passed`, two expected warnings, `81%` repository coverage, `60.36s`.
5. Ruff check: PASS across 149 files.
6. Ruff format check: PASS across 149 files.
7. Strict MyPy: PASS across 58 source files.
8. Offline lock check: PASS; 87 locked packages resolved without network.
9. The then-frozen six-path scope, diff, secret, and dependency-file checks:
   PASS for the Review 001 candidate; the governance amendment below corrects
   that incomplete allowlist to seven paths before Round 1 source changes.
10. Fresh offline dependency inventory: PASS; 86 installed packages; network
    operations `0`; advisory lookup `not_run_offline`.

Tools focused line/branch coverage is `99%`. The only uncovered defensive lines
are structurally dominated and have executable dominance evidence:

- line 640 repeats task-evidence cardinality after the public exact-task outer
  cardinality guard has already rejected the same condition;
- line 988 was initially described as dominated after identities were
  normalized into dictionary keys. Review 001 disproved that explanation:
  duplicate resolutions collapse in the dictionary and can produce PASS. This
  is an open P1 defect, not accepted dominance evidence, and is assigned to
  Round 1 remediation; and
- line 1066 repeats the exact semantic-expectation binding condition already
  applied to every claim by global Stage 1, with no capability or effect between
  the checks.

The workflow module reports `87%` line/branch coverage. Uncovered locations are:
`123->125, 142, 152, 178, 220, 232, 244, 280, 282, 284, 308, 363, 503, 518,
587, 663, 724, 733, 743, 748, 760, 774, 800, 824, 844, 849->exit, 861, 863,
867, 878, 890`. These are legacy transition negatives or defensive checks
dominated by exact Pydantic durable reconstruction and earlier application
preflight. Public-route tests demonstrate rejection and zero effects at the
dominant check rather than invoking private helpers or tampering with runtime
authority to manufacture coverage. Independent Review 001 must inspect and
decide this reachability evidence directly; no 100% workflow coverage claim is
made.

Fresh offline dependency inventory manifest:

- path:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-002-s2-deps-00a36f9fa9fb4da5bc658b9732caad95`
- manifest SHA-256:
  `84fcf58b4dec4574808e926fd4bc9d1894fb7e27dd119a1c844b8fabf6d5f48a`
- advisory status: `not_run_offline`
- installed package count: `86`
- network operations: `0`

### Scope, environment, network, review, and Git state

- Exact repository allowlist: PASS. The only implementation/test changes are
  the delivery record, tools authority, workflow, and two unit-test files;
  allowlisted `ports.py` is unchanged.
- Secret scan: PASS. No credentials, PHI, patient data, production exports, or
  new sensitive values were introduced.
- Dependency and lock files: unchanged. No dependency, provider, model, package
  download, advisory request, medical-source access, or other network access
  occurred.
- Holdout-20 remained sealed. No PubMed, NCBI, DailyMed, FAERS, CADEC, or other
  medical-source traffic occurred.
- A failed `uv --locked --no-sync` probe created an ignored dependency-empty
  `.venv` skeleton in the successor worktree. It contains no installed project
  dependencies, is outside Git status/scope, and was not used for validation.
  Cleanup was not performed because the platform blocked the verified removal;
  no bypass was attempted.
- Independent Review 001: not run.
- Exact-byte rebind: not run.
- Terminal evidence audit: not run.
- Staging, commit, push, PR, CI, Ready, merge, rebase, reset, clean, branch
  deletion, history rewrite, and remote operations: `0` / not performed.
- No implementation PASS or final `PASS — P0 0 / P1 0 / P2 0` verdict is
  claimed before fresh independent review, rebind, and terminal audit.

## Independent Review 001 — immutable verdict and Round 1 governance amendment

Independent Review 001 returned the immutable verdict:

`FAIL — P0 0 / P1 3 / P2 2`

This verdict is preserved as candidate evidence and is not downgraded by prior
green validation. The exact five findings are:

1. **P1 — Duplicate human-resolution identities can still produce canonical
   PASS.** `canonical_validate_report` converts resolutions to a dictionary
   before testing uniqueness. Duplicate valid `ADJUDICATED_TO_SUPPORTED`
   resolutions therefore collapse to one mapping entry and can admit an
   uncertain formal claim. Review reproduction observed `passed=True`, no
   reasons, and `resolution_count=2`. This violates resolution uniqueness and
   deterministic traceability.
2. **P1 — A legitimate validation-blocked terminal checkpoint cannot resume
   idempotently.** `run_next` invokes pure binding verification for every
   synthesis-bearing terminal state, but `_verify_binding` rejects every
   non-passing audit even when the recomputed failed gates and reasons exactly
   equal stored validation. Review reproduction reached
   `VALIDATION_BLOCKED`, then `run_next(state)` raised canonical binding
   failure with zero effects. This violates the frozen terminal-resume
   contract.
3. **P1 — Nested untrusted containers remain unbounded and can PASS.** A valid
   PubMed numerical request with one fact repeated 5,000 times, canonically
   re-identified and rehashed, returned PASS with one semantic call. Missing
   bounds also affect evidence locators and claim citation/limitation tuples.
   This violates the repository requirement to bound every untrusted tool
   argument and creates deterministic resource-exhaustion exposure.
4. **P2 — The frozen zero-port requirement is not implemented.** Although the
   workflow accepts no runtime validator and directly calls the tools
   authority, `ReportValidationPort` remains defined in
   `src/medevidence/orchestration/ports.py` and publicly re-exported by
   `src/medevidence/orchestration/__init__.py`. The workflow-only AST test does
   not establish repository-wide absence.
5. **P2 — Mandatory coverage evidence is incomplete, and the line-988
   dominance explanation is disproven.** The frozen gate requires 100% tools
   and changed workflow validation-branch coverage, while the candidate
   recorded 99% and 87%. Finding 1 proves line 988 is reachable as a duplicate
   resolution PASS rather than dominated by another rejection.

Review 001 independently verified the baseline/branch, five-path candidate
hashes, focused `167 passed`, exact-maximum/max+1/100-101 warning boundaries,
and no network or Git mutations. Those green observations do not override the
five findings or the immutable FAIL verdict.

### Governance amendment: corrected seven-path scope

The initial six-path freeze omitted
`src/medevidence/orchestration/__init__.py`, even though the same frozen design
simultaneously required zero `ReportValidationPort` definition and zero public
re-export. Removing the obsolete port definition alone cannot satisfy that
requirement while the package initializer continues to re-export it.

The exact allowlist is therefore corrected, before Round 1 source remediation,
to the seven paths listed in the authoritative allowlist above by adding only:

`src/medevidence/orchestration/__init__.py`

This is a same-design freeze correction inside the already authorized
orchestration namespace. It is necessary to remove an obsolete public import;
it does not introduce a public API/OpenAPI/schema, persistence, source/evidence,
retrieval, router, dependency, model/provider, security, governance, or
clinical-safety expansion. No eighth repository path is authorized.

### Remediation Round 1/8 plan

Round 1 is assigned only the five Review 001 findings:

- reject duplicate resolution identities before dictionary construction and
  add the exact review reproduction as a negative test;
- permit pure idempotent resume of a validation-blocked terminal checkpoint
  only when the freshly recomputed failed gates and exact reasons equal stored
  validation, with evaluator and all effects remaining zero;
- add cardinality-first finite bounds and exact max/max+1 negative tests for
  every currently unbounded nested evidence/claim container identified by the
  review, without changing source or evidence meaning;
- remove the obsolete `ReportValidationPort` definition from allowlisted
  `ports.py` and its re-export from newly allowlisted
  `orchestration/__init__.py`, and strengthen absence evidence across the
  complete authorized production namespace; and
- close mandatory tools/workflow coverage gaps with executable public-route
  tests or retain only genuinely unreachable defensive branches with correct,
  independently reviewable dominance evidence. Line 988 is explicitly not
  classified as unreachable.

Planned Round 1 writers may change only the exact seven-path allowlist and must
retain single-writer ownership. `contracts.py`, domain, connectors, ingestion,
retrieval, evaluation, API, frontend, MCP, dependency, lock, fixture, corpus,
qrels, metric-contract, and Holdout paths remain prohibited.

Current status:
`REMEDIATION_ROUND_1_IN_PROGRESS`.

No Round 1 source or test remediation is claimed by this governance amendment.
No Review PASS, final PASS, exact-byte rebind, terminal audit, staging, commit,
push, PR, merge, or other Git/network operation is claimed.

## Remediation Round 1/8 implementation evidence

The immutable Review 001 verdict remains:

`FAIL — P0 0 / P1 3 / P2 2`

The evidence below records the Round 1 candidate closures presented for fresh
Independent Review 002. It does not rewrite Review 001 and is not a PASS claim.

### Review 001 finding closure candidates

1. **Duplicate identities, including resolutions.** Canonical validation now
   constructs raw identity tuples for claims, citations, evidence, semantic
   expectations, resolutions, comparisons, and conflicts and rejects duplicate
   identities before constructing lookup dictionaries. The exact Review 001
   duplicate `ADJUDICATED_TO_SUPPORTED` resolution reproduction now fails with
   `registry_identity_duplicate`, invokes the evaluator zero times, and pure
   VERIFY reproduces the exact stored failed gates and reasons.
2. **Validation-blocked terminal resume.** Terminal verification now compares
   freshly recomputed structural, semantic, and safety gates plus exact reasons
   with stored validation. `require_pass=False` is used only for a legitimate
   `VALIDATION_BLOCKED` terminal disposition; an exact failed checkpoint returns
   an equal freshly reconstructed state with semantic and all effect counters
   unchanged. Gate, reason, synthesis hash, or registry drift rejects with zero
   effects. Save, approval, rejected resume, export, and exported idempotent
   return continue to require canonical PASS.
3. **Nested bounds.** Cardinality-first guards now cover every Review 001
   container with graph-valid exact maxima and specific max+1 codes before
   malformed-member traversal or evaluator acquisition:
   - claim citation IDs: maximum 300;
     `claim_citation_cardinality_exceeded` at 301;
   - claim presented limitations: maximum 100;
     `claim_limitation_cardinality_exceeded` at 101;
   - evidence locators: maximum 1;
     `evidence_locator_cardinality_exceeded` at 2; and
   - evidence numerical facts: maximum 100;
     `evidence_numerical_fact_cardinality_exceeded` at 101.

   The 300 citation maximum is the graph-valid bound produced by one selected
   source task's 100 evidence references times the three exact citation
   relationships. The single locator maximum preserves exact equality with the
   durable evidence reference's one locator. A 400-citation/100-locator PASS
   would require changing the frozen task/evidence/lineage graph, so those
   non-constructible maxima were not fabricated. Bounded 4096/4097 claim
   limitation and evidence excerpt cases are also executable.
4. **Zero runtime validation port.** The obsolete `ReportValidationPort`
   definition was removed from `src/medevidence/orchestration/ports.py` and its
   re-export was removed from `src/medevidence/orchestration/__init__.py` under
   the corrected seven-path allowlist. Repository-wide production AST/text
   evidence covers all Python sources and explicitly checks both files. No
   validation adapter, binder, factory, or caller-provided validation operation
   was introduced.
5. **Coverage evidence correction.** The false line-988 dominance statement is
   removed. Line 988's duplicate-resolution behavior is now executable and
   rejected. Current tools and workflow coverage plus the remaining exact
   unreachable/dominated branches are recorded below for Review 002 to inspect
   directly. No private helper is called to manufacture coverage.

### Exact Round 1 candidate bytes before Review 002

The following values were recomputed from the current worktree after the Round
1 ordered validation gates. They bind all six code/test paths in the corrected
seven-path allowlist; the delivery record remains intentionally excluded from
its own in-record hash table.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `src/medevidence/tools/report_validation.py` | 1127 | 64726 | `a344f539b36c699c3ec7c69fa733302e8513b9b5e62631a9a14cb692891dc5ca` |
| `src/medevidence/orchestration/workflow.py` | 973 | 41753 | `dcd757ff5a100e99ea7df69f20ddeae93b47514c6859a53646a4ad7809b54679` |
| `src/medevidence/orchestration/ports.py` | 105 | 2766 | `7c585472c22c294c87ed7342a4d9fd2917fc333d955e0cb67ed12709211b46e3` |
| `src/medevidence/orchestration/__init__.py` | 95 | 2249 | `7e292a21b40f9d4b2b6d9e5c1fad637410cbd3050373ee2344738a462799b98c` |
| `tests/unit/tools/test_report_validation.py` | 1934 | 70823 | `7783165a41af61ac978022f004fd313363357b9143ea4e412068b122a3838af4` |
| `tests/unit/orchestration/test_workflow.py` | 1699 | 63861 | `5c081556c43c62c31fcb16513a13475d963622bcc0476c1a2723ea259936e478` |

The tools authority is 1127 physical lines, 27 lines above the original 1100
line compactness ceiling. This exact fact is surfaced for Review 002; no
compactness-gate PASS is claimed or inferred from the functional checks.

### Round 1 ordered validation evidence

All commands used the successor source first, existing locked local
dependencies, socket-disabled offline execution, and no synchronization or
download.

1. Tools authority suite: `130 passed`.
2. Workflow plus tools suites: `184 passed`.
3. Focused M3/domain/dependency-boundary suite: `640 passed`.
4. Full offline unit/contract suite: `2208 passed`, two expected warnings,
   `81%` repository coverage, `50.97s`.
5. Ruff check: PASS across 149 files.
6. Ruff format check: PASS across 149 files.
7. Strict MyPy: PASS across 58 source files.
8. Offline lock check: PASS; 87 locked packages, network `0`.
9. Exact seven-path scope, diff, secret, and dependency-file checks: PASS.
10. Fresh offline dependency inventory: PASS; 86 installed packages; advisory
    status `not_run_offline`; network operations `0`.

Tools line/branch coverage is `99%`. The only uncovered lines are 655, 696,
and 1097:

- line 655 repeats task-evidence cardinality after the exact outer guard has
  already rejected the same condition;
- line 696 is the duplicate-locator defense after the graph-valid locator
  maximum of one, so any tuple capable of containing a duplicate is rejected by
  cardinality first; and
- line 1097 repeats semantic-expectation binding already completed for every
  claim by the global Stage 1 barrier, with no capability or effect between the
  two checks.

The old false line-988 dominance claim is not present in this evidence. Duplicate
resolution identity is now a reached negative test.

Workflow line/branch coverage is `87%`. The exact remaining locations are:

`123->128, 145, 155, 181, 223, 235, 247, 283, 285, 287, 311, 366, 506, 521,
590, 666, 744, 753, 763, 768, 780, 794, 820, 844, 864, 881, 883, 887, 898,
910`.

The new `require_pass` and exact gate/reason equality branches are executable in
both directions. The remaining locations are legacy transition negatives or
defenses dominated by `OrchestrationState.model_validate` and earlier public
preflight. Public-route tests assert the dominant rejection and zero effects;
private helpers are not invoked to game coverage. Independent Review 002 must
verify this reachability evidence directly.

Fresh offline dependency inventory manifest:

- path:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-002-s2-r1-deps-c3089e62491b41e8befc3e35aaad9f0f`
- SHA-256:
  `39b5dbac628b6665e24f617b40b0f517fd51c9e1d109ae7b3b3057c42ae85832`
- advisory status: `not_run_offline`
- installed package count: `86`
- network operations: `0`

### Round 1 scope and lifecycle state

- Remediation budget consumed: `1/8`.
- Exact corrected seven-path scope: PASS; no eighth path changed.
- `contracts.py`, domain, connectors, ingestion, retrieval, evaluation, API,
  frontend, MCP, dependency, lock, fixture, corpus, qrels, metric-contract, and
  Holdout paths remain unchanged and prohibited.
- Dependency files and lock bytes are unchanged. Secret/dependency-file checks:
  PASS.
- Medical-source, model/provider, dependency-download, advisory, Holdout, and
  all other network traffic: `0`.
- Independent Review 002: not run.
- Exact-byte rebind: not run.
- Terminal evidence audit: not run.
- Staging, commit, push, PR, CI, Ready, merge, rebase, reset, clean, branch
  deletion, history rewrite, and remote operations: `0` / not performed.

Current status:
`AWAITING_INDEPENDENT_REVIEW_002`.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Remediation Round 3/10 — durable receipt implementation candidate

Current status:
`DURABLE_RECEIPT_IMPLEMENTED_AWAITING_INDEPENDENT_REVIEW_004`.

This section supersedes only the current design-freeze status. It preserves
immutable Review 003 `FAIL — P0 0 / P1 2 / P2 0`, the rounds 1–2 history, the
Owner receipt-design resolution, and the execution-platform classifier
non-findings. It does not claim Review 004, final PASS, exact-byte rebind,
terminal audit, staging, commit, push, PR, CI, Ready, merge, or M3-003.

### Implemented authority, receipt, and persistence path

- `OrchestrationState` is explicitly versioned
  `m3.orchestration-state.v2` and carries only
  `ValidationReceiptRef` version `m3.validation-receipt-ref.v1`, containing the
  receipt identity and content hash. Version-1 durable state and inline receipt
  authority fail closed under exact contract tests.
- The canonical ASSESS path reconstructs the report input, completes Stage 1,
  acquires exact Stage-2 results, applies relationship-aware aggregation,
  constructs `M3_VALIDATION_RECEIPT_V1`, and returns it as audit data.
- Workflow receipt persistence converts the receipt to canonical payload,
  calls `save_receipt`, reconstructs the returned payload with
  `validation_receipt_from_payload`, verifies it against the exact request and
  audit, reloads it by identity, reconstructs and verifies it again, compares
  both values with the assessed receipt, and only then writes the durable
  reference.
- Before pending-draft persistence, approval, export/finalization, idempotent
  exported return, or synthesis-bearing terminal trusted return, the workflow
  completes durable/application/topology/request reconstruction and invokes
  `canonical_validate_report(VERIFY_BINDING)` with no semantic provider before
  any pending/receipt-store capability. `_verify_binding` checks exact stored
  validation equality; when a pending reference exists it loads, reconstructs,
  and binds that exact durable row before loading the referenced receipt,
  reconstructing it with `validation_receipt_from_payload`, binding reference
  identity/hash, and calling `verify_validation_receipt` against current inputs.
  Invalid state reaches no later capability, effect, or trusted return; semantic
  evaluator calls are zero.
- `DraftPersistencePort` is selected by trusted static composition. Save returns
  untrusted pending-reference data that is exactly reconstructed and bound, then
  immediately reloaded and rebound before a pending-review checkpoint is
  published. Approval, export, idempotent export, and terminal resume also load
  and bind the exact durable pending draft before receipt loading.
- Report edit clears `validation_receipt_ref`; the prior receipt cannot
  authorize the edited state and a new canonical assessment/receipt is
  required.
- `ValidationReceiptStorePort` is source-neutral. The PostgreSQL repository is
  a mapping-only adapter: `src/medevidence/persistence/**` imports no report-
  validation tool or tool-layer authority. Application/tool code owns payload
  reconstruction and receipt verification.
- `m3_validation_receipts` is an independent immutable table with exact
  marker, identity, hash, version, and JSON-object constraints. Repository save
  supports only exact idempotent replay; collision/drift, malformed payload,
  missing load, and transactional failure remain explicit. Migration
  `20260827_01_m3_validation_receipt.py` adds and removes only this table.
- ADR-016, its index entry, and the V1 traceability mapping record the Owner-
  authorized receipt design without rewriting prior ADRs.

Implemented call graph:

```text
canonical_validate_report(ASSESS)
  -> Stage 1 for every claim
  -> Stage 2 semantic-result acquisition
  -> relationship-aware aggregate
  -> canonical receipt content/identity in ReportValidationAudit
  -> canonical_validation_receipt_payload
  -> ValidationReceiptStorePort.save_receipt
  -> validation_receipt_from_payload
  -> verify_validation_receipt(request, ASSESS audit)
  -> ValidationReceiptStorePort.load_receipt
  -> validation_receipt_from_payload
  -> verify_validation_receipt(request, ASSESS audit)
  -> ValidationReceiptRef

every effect or terminal trusted return
  -> complete durable/application reconstruction
  -> canonical_validate_report(VERIFY_BINDING), evaluator calls=0
  -> exact stored gate/reason equality
  -> when present: DraftPersistencePort.load_pending
  -> exact pending persistence/report/content binding
  -> ValidationReceiptStorePort.load_receipt
  -> validation_receipt_from_payload
  -> exact reference identity/content-hash binding
  -> verify_validation_receipt(current request, VERIFY audit)
  -> effect or trusted return

save_pending_draft after the common preflight and receipt binding
  -> DraftPersistencePort.save_pending
  -> exact returned pending reconstruction/binding
  -> DraftPersistencePort.load_pending
  -> exact durable read-back binding
  -> pending-review checkpoint
```

### Relationship-aware Stage-2 implementation

- Any semantic `unsupported` result aggregates `unsupported`.
- A required direct `supports` or `contradicts` citation remaining `uncertain`
  aggregates `uncertain`.
- A semantically confirmed applicable `contradicts` citation prevents
  automatic support and aggregates unresolved `uncertain` even when a
  `supports` citation is supported.
- Automatic `supported` requires at least one supported `supports` citation
  and no unresolved contradiction or direct uncertainty.
- `context_only` never supplies direct support; context-only input cannot pass
  the Stage-1 supporting-citation requirement.
- The existing explicit `ADJUDICATED_TO_SUPPORTED` resolution remains the only
  governed automatic path from an uncertain aggregate to formal acceptance.
  No count, majority, retrieval score, confidence, source weighting, or new
  conflict taxonomy is introduced.

### Exact Round-3 pre-review candidate identities

The worktree has exactly 18 changed paths, all inside the 19-path allowlist.
The delivery-record row is the exact pre-append identity immediately before
this Round-3 evidence section was added; it is necessarily superseded by this
append and is not claimed as the final self-bound delivery identity. Every
other changed-path row binds the current bytes submitted to Review 004.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md` (pre-evidence append) | 1320 | 80833 | `dd25801961c4bfb21c3dd1d6babccfdbc3df7cc65155472d3d10f77b6373a02b` |
| `alembic/versions/20260827_01_m3_validation_receipt.py` | 64 | 2527 | `a72fc3a807e228aa32c9d049d90493b9bca456384fd3f9919f9ee3d2e48358f7` |
| `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md` | 158 | 8186 | `611402a65dc58a0e993a93e8bfefdc8d3ef7395997e4c204ada4768f05edd163` |
| `docs/decisions/README.md` | 135 | 5953 | `373eedcaee578db758977e179dd8939b612b995a5890491feb8f28633b5db6e1` |
| `docs/TRACEABILITY_MATRIX.md` | 559 | 56991 | `e50ffcf0988c07644d208776d4757f222a34e2b9b1fa930ddcbe3e38c871b81b` |
| `src/medevidence/orchestration/__init__.py` | 99 | 2369 | `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c` |
| `src/medevidence/orchestration/contracts.py` | 725 | 32037 | `9634a30439b3f12ef8838b2a40fdbd586b96ca1e7531baa0243a1b82049e5d2e` |
| `src/medevidence/orchestration/ports.py` | 117 | 3116 | `05a1b51d4390850c84581f220f98a6d80be8ddbace282dba4475fa23f2db90e7` |
| `src/medevidence/orchestration/workflow.py` | 1053 | 45456 | `dab24b249c62266df86b164e3c7919b1d15cc023802d45ae24aaffa273a27edc` |
| `src/medevidence/persistence/models.py` | 2287 | 100864 | `de32bb675105c1717a494abf3bc411607a99b7433c21f1e5985c6b84d1824f03` |
| `src/medevidence/persistence/repositories.py` | 2622 | 107008 | `9a46934e4e8bf56e3b7b509b06d8ebbef11ef663d68de0e5d8f205b336d9aa95` |
| `src/medevidence/tools/report_validation.py` | 1279 | 86260 | `a8fbe6f00c39a854cef032fcb1d15611c757b30aa8c80a5294890ee2313676d5` |
| `tests/integration/persistence/test_migrations.py` | 430 | 16519 | `8f994d61d566cfb1187bc7ccdb54f429e3dbe2d6f0d140d6b4262a1409761bf3` |
| `tests/integration/persistence/test_validation_receipts.py` | 242 | 8905 | `e77e4a4f8d225234be5fcc46f9fadb454595754d2ba4a24983ef8205d5824dc0` |
| `tests/unit/orchestration/test_contracts.py` | 472 | 16184 | `381a057bc5875252056de848f3a91d678d8de036a5abe2e47cf5786018d297cc` |
| `tests/unit/orchestration/test_workflow.py` | 2153 | 83292 | `80f6883af3a2b43bcd757f673e661c5cf251098fe50f61d304fe74908cea4592` |
| `tests/unit/persistence/test_metadata.py` | 1046 | 38893 | `13246c09bbf68b43df8f20ecfa88a550d961026e2b413e0740201953072ec5bb` |
| `tests/unit/tools/test_report_validation.py` | 2819 | 103454 | `b39c4cf7a7df8881936fb42f1c2b45644afb47ef0373b4204bb4121cde4096d3` |

The sole unchanged allowlisted path is byte-identical to baseline:

| Path | Physical LOC | Bytes | SHA-256 | Diff from baseline |
|---|---:|---:|---|---|
| `src/medevidence/persistence/__init__.py` | 77 | 1985 | `7bc9a7dd7fb6b74508d6f593baef603b13c746e35ce36c01db91bbf0a491af5b` | none (`git diff --quiet` exit 0) |

### Ordered Round-3 validation evidence

All application validation used the current successor bytes, locked local
dependencies, and no dependency synchronization or download.

1. Focused receipt/validator/workflow/persistence selection: `488 passed`.
2. Tools, workflow, and orchestration-contract suites: `272 passed`.
3. Persistence unit suite: `123 passed`.
4. Full socket-disabled unit/contract suite: `2293 passed`, two expected
   warnings, `81%` repository coverage, `63.50s`.
5. Ruff check: PASS across 151 files.
6. Ruff format check: PASS across 151 files.
7. Strict MyPy: PASS across 58 source files.
8. Offline lock check: PASS; 87 locked packages.
9. Dependency-boundary suite: `93 passed`.
10. Conditional offline persistence integration before a database was
    available: `4 passed, 10 skipped`.
11. Actual local PostgreSQL integration used the already-present PostgreSQL
    18.4 image ID `1961f96e6029` with no pull. Migration and receipt tests:
    `14 passed`, including upgrade/downgrade/upgrade. The exact test container
    was removed and Docker was stopped after validation.
12. Alembic offline `--sql` generation remains unavailable because the
    pre-existing FAERS migration calls `MockConnection.exec_driver_sql`. This
    is reported as an existing tooling limitation, not converted to PASS.
    Actual PostgreSQL migration execution plus fake-DDL migration assertions
    provide the applicable Round-3 migration evidence.
13. Exact 19-path allowlist / 18 changed-path scope, diff, secret, and
    dependency-file checks: PASS.
14. Fresh offline dependency inventory: PASS; 86 installed packages; advisory
    status `not_run_offline`; external network operations `0`.

Dependency inventory manifest:

- path:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-receipt-r3-deps-97be55bbc6a74096a4f33a6538a94835`
- SHA-256:
  `ae82ff2c3403b173a202bfcddcdf9604e707b3b03eaa37ec93fed30cca4bace8`
- installed package count: `86`
- advisory status: `not_run_offline`
- external network operations: `0`

### Coverage, compactness, and reviewer-attention evidence

- Canonical tools authority: `99%`; exact uncovered lines are `660`, `697`,
  `954`, `1060`, and `1244`. They are respectively a repeated inner task-
  evidence bound after the outer maximum, duplicate locator after the maximum-
  one locator admission, the Stage-2 fallback dominated by the Stage-1 direct-
  support requirement and preceding aggregate branches, canonical JSON of an
  exact receipt dataclass failing to deserialize as an object, and repeated
  semantic-expectation binding after the complete Stage-1 barrier. Review 004
  must verify these reachability claims directly.
- Workflow line/branch aggregate: `89%`. Exact uncovered reviewer-attention
  locations are `154, 244, 320, 378, 521, 536, 605, 681, 705, 713, 717, 721,
  738-739, 752, 789, 824, 833, 843, 848, 860, 874, 900, 924, 944, 967, 972,
  978, 990`. The new receipt-specific set is `705, 713, 717, 721, 738-739,
  752, 789`; the remaining lines are prior topology/application guards. These
  are submitted for direct review rather than declared closed by aggregate
  coverage.
- Orchestration contracts report `80%` and the full persistence repository
  reports `45%` overall because both files contain substantial pre-existing
  contracts/repositories outside the receipt scope. Focused receipt contract,
  mapping, failure, migration, and actual PostgreSQL branches are executable
  and were run as recorded above.
- Receipt-extended compactness gates pass: canonical tools physical LOC
  `1279 <= 1300`; total production additions `1747 <= 1800`. These replace the
  pre-receipt compactness measurements for this ADR-016 implementation
  candidate; no compatibility layer or second validator was added.

### Round-3 lifecycle state

- Remediation round: `3/10`.
- Changed scope: exactly 18 of 19 allowlisted paths; persistence `__init__.py`
  unchanged.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations: `0`.
- Independent Review 004: not run.
- Exact-byte rebind: not run.
- Terminal evidence audit: not run.
- Staging, commit, push, PR, CI, Ready, merge, post-merge verification,
  control-plane reconciliation, and M3-003: not started.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 004 — immutable FAIL and Round 4 plan

Fresh independent review returned the formal immutable verdict:

`FAIL — P0 0 / P1 1 / P2 1`

Execution-platform safety-classifier interruptions remain platform non-findings
and are not counted in this verdict. The exact Review 004 findings are:

1. **P1 — The documented capability trust model contradicted the durable-
   receipt design.** The delivery record declared every injected capability and
   result untrusted while workflow construction accepted an arbitrary
   `ValidationReceiptStorePort`. The reviewer supplied a store that returned a
   self-consistent current-input receipt that was never independently saved. A
   forged passing `SAVE_PENDING_DRAFT` checkpoint reached pending persistence
   with `semantic_calls=0`, `save_receipt_calls=0`, `load_receipt_calls=1`, and
   `pending_persistence_calls=1`. Closing the finding requires trusted static
   application-owned composition or an explicit trust-boundary revision; green
   payload reconstruction alone cannot satisfy a threat model that treats the
   capability itself as malicious.
2. **P2 — Two required receipt-store failure branches lacked executable
   coverage.** No test exercised successful receipt save followed by reload
   returning `None` at workflow line 713, or the receipt-load capability raising
   at lines 738–739. The reviewer manually reproduced both as fail-closed with
   zero later effects, but uncovered manual behavior is not executable
   regression evidence.

The Round-3 validation, schema, receipt, migration, relationship aggregation,
mapping-only persistence, scope, and zero-external-network evidence remain
preserved as pre-review evidence. They do not override the Review 004 FAIL.

### Owner trust-boundary correction

- Trusted: the reviewed static application composition and the independently
  durable `ValidationReceiptStorePort` capability selected by it.
- Untrusted: all runtime/checkpoint/receipt payloads and every value returned by
  the store or other capability. Every return is strictly reconstructed and
  bound before use.
- The trusted store contract requires durable save before successful return and
  load of only independently durable state. A fake store manufacturing unsaved
  data violates that capability contract and trusted composition; it is not an
  ordinary runtime DATA-injection case.
- The store remains a replaceable application adapter selected by trusted
  composition. No origin token, binder, factory-origin proof, callable
  fingerprint, runtime capability authentication, or general Python anti-
  tamper redesign is authorized or attempted.

### Bounded remediation Round 4/10

Round 4 changes only:

1. the `ValidationReceiptStorePort` protocol docstring so its independent
   durability and trusted-composition contract is explicit; and
2. workflow regressions for successful save then missing reload and for receipt-
   load capability error, each proving fail-closed behavior and zero later
   effects.

No canonical source authority, receipt identity, Stage-1/Stage-2, relationship,
source/evidence, public API, schema, migration, persistence, retrieval, router,
corpus, qrels, metric-contract, or dependency semantics change is authorized.

Current status:
`REMEDIATION_ROUND_4_IN_PROGRESS`.

- Remediation round: `4/10`.
- Review 004 remains `FAIL — P0 0 / P1 1 / P2 1` until a fresh independent
  review verifies the exact remediated bytes.
- Exact-byte rebind, terminal audit, staging, commit, push, PR, CI, Ready,
  merge, post-merge verification, control-plane reconciliation, and M3-003 have
  not started.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations remain `0`.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Remediation Round 4/10 closure candidate

Current status:
`AWAITING_INDEPENDENT_REVIEW_005`.

Review 004 remains immutable `FAIL — P0 0 / P1 1 / P2 1`. Round 4 changes only
the frozen trust-contract documentation and the two missing receipt-store
failure regression families; canonical report authority and receipt semantics
are byte-unchanged.

### Round-4 closure behavior

- `ValidationReceiptStorePort` now documents that trusted static application
  composition selects an application-owned independently durable store
  capability. It also states that every returned mapping is untrusted and must
  be reconstructed and verified, and that callers/runtime data cannot supply a
  receipt body. It adds no origin authentication, token, binder, or validation
  authority.
- Successful assessment receipt save followed by reload returning `None` now
  fails before a `ValidationReceiptRef` or passing durable state is produced.
  The test preserves the input checkpoint bytes, observes one assessment, one
  save, one reload, and zero pending persistence, approval, or export calls.
- Receipt-load capability exception coverage is parameterized across pending-
  draft save, approval, export, idempotent exported return, and terminal resume.
  Each route preserves evaluator-call count, adds exactly one load attempt,
  invokes no receipt save/replay, and leaves persistence/approval/export effect
  counts unchanged.
- The trusted capability versus untrusted output distinction changes no
  canonical Stage-1/Stage-2 decision, receipt content/identity, relationship
  aggregation, source/evidence restriction, public API, durable schema,
  migration, repository mapping, retrieval, router, corpus, qrels, metric
  contract, or dependency semantics.

### Exact Round-4 candidate identities

The worktree has exactly 18 changed paths within the 19-path allowlist. The
delivery row is the exact pre-append identity immediately before this closure
section and is not claimed as a final self-bound delivery identity. Every other
row binds the current bytes submitted for Review 005.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md` (pre-Round-4 closure append) | 1628 | 98357 | `79c9a8ad0df03ef7f969f6e30f51b15fa1cf0810f73a93ec41c808cc295792a1` |
| `alembic/versions/20260827_01_m3_validation_receipt.py` | 64 | 2527 | `a72fc3a807e228aa32c9d049d90493b9bca456384fd3f9919f9ee3d2e48358f7` |
| `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md` | 183 | 9796 | `4c97407e63845d1a9116991bede629484b815704f7fd5cd7816c6f003a90ec2b` |
| `docs/decisions/README.md` | 135 | 5953 | `373eedcaee578db758977e179dd8939b612b995a5890491feb8f28633b5db6e1` |
| `docs/TRACEABILITY_MATRIX.md` | 594 | 59456 | `f7a29bfbf1482c286635a986931f8eac4ddc227b646f2f7a6eb028e922113aa7` |
| `src/medevidence/orchestration/__init__.py` | 99 | 2369 | `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c` |
| `src/medevidence/orchestration/contracts.py` | 725 | 32037 | `9634a30439b3f12ef8838b2a40fdbd586b96ca1e7531baa0243a1b82049e5d2e` |
| `src/medevidence/orchestration/ports.py` | 123 | 3451 | `711f25295ca892a899a327c70469c2789bf28106ea6e16e41f777ada650dcb9d` |
| `src/medevidence/orchestration/workflow.py` | 1053 | 45456 | `dab24b249c62266df86b164e3c7919b1d15cc023802d45ae24aaffa273a27edc` |
| `src/medevidence/persistence/models.py` | 2287 | 100864 | `de32bb675105c1717a494abf3bc411607a99b7433c21f1e5985c6b84d1824f03` |
| `src/medevidence/persistence/repositories.py` | 2622 | 107008 | `9a46934e4e8bf56e3b7b509b06d8ebbef11ef663d68de0e5d8f205b336d9aa95` |
| `src/medevidence/tools/report_validation.py` | 1279 | 86260 | `a8fbe6f00c39a854cef032fcb1d15611c757b30aa8c80a5294890ee2313676d5` |
| `tests/integration/persistence/test_migrations.py` | 430 | 16519 | `8f994d61d566cfb1187bc7ccdb54f429e3dbe2d6f0d140d6b4262a1409761bf3` |
| `tests/integration/persistence/test_validation_receipts.py` | 242 | 8905 | `e77e4a4f8d225234be5fcc46f9fadb454595754d2ba4a24983ef8205d5824dc0` |
| `tests/unit/orchestration/test_contracts.py` | 472 | 16184 | `381a057bc5875252056de848f3a91d678d8de036a5abe2e47cf5786018d297cc` |
| `tests/unit/orchestration/test_workflow.py` | 2255 | 86958 | `d5bbbfb151f9e26ce31744ce20b9605098f4d7a039210006254b47949d7656c4` |
| `tests/unit/persistence/test_metadata.py` | 1046 | 38893 | `13246c09bbf68b43df8f20ecfa88a550d961026e2b413e0740201953072ec5bb` |
| `tests/unit/tools/test_report_validation.py` | 2819 | 103454 | `b39c4cf7a7df8881936fb42f1c2b45644afb47ef0373b4204bb4121cde4096d3` |

The sole unchanged allowlisted path remains byte-identical to baseline:

| Path | Physical LOC | Bytes | SHA-256 | Diff from baseline |
|---|---:|---:|---|---|
| `src/medevidence/persistence/__init__.py` | 77 | 1985 | `7bc9a7dd7fb6b74508d6f593baef603b13c746e35ce36c01db91bbf0a491af5b` | none (`git diff --quiet` exit 0) |

### Ordered Round-4 validation evidence

1. Focused receipt/validator/workflow/persistence selection: `494 passed`.
2. Round-4 workflow selection: `81 passed`.
3. Tools, workflow, and orchestration-contract suites: `278 passed`.
4. Full socket-disabled unit/contract suite: `2299 passed`, two expected
   warnings, `81%` repository coverage, `60.49s`.
5. Ruff check: PASS across 151 files.
6. Ruff format check: PASS across 151 files.
7. Strict MyPy: PASS across 58 source files.
8. Offline lock check: PASS; 87 locked packages.
9. Exact 19-path allowlist / 18 changed-path scope, diff, secret, and
   dependency-file checks: PASS.
10. Fresh offline dependency inventory: PASS; 86 installed packages; advisory
    status `not_run_offline`; external network operations `0`.

Dependency inventory manifest:

- path:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-receipt-r4-deps-e6395a752e55488296dd3950bc663c2d`
- SHA-256:
  `c4dbfdd3be05c1a42682750ba2cd717c1c7c427aff06f3cdc697f975b0b8707b`
- installed package count: `86`
- advisory status: `not_run_offline`
- external network operations: `0`

The actual local PostgreSQL 18.4 migration/receipt result remains `14 passed`
and covers upgrade/downgrade/upgrade. It is bound to unchanged Round-4
persistence model, repository, migration, and persistence-integration bytes;
no image pull or external network occurred, and the validation container had
already been removed with Docker stopped. Alembic offline `--sql` remains the
reported pre-existing FAERS `MockConnection.exec_driver_sql` limitation rather
than a claimed PASS.

### Coverage and compactness submitted to Review 005

- Canonical tools authority remains `99%`; its five exact unreachable lines are
  `660, 697, 954, 1060, 1244`, with the Round-3 reachability explanations
  unchanged.
- Workflow line/branch aggregate increases to `90%`. Remaining reviewer-
  attention locations are `154, 244, 320, 378, 521, 536, 605, 681, 705, 721,
  752, 789, 824, 833, 843, 848, 860, 874, 900, 924, 944, 967, 972, 978, 990`.
  Review-004 lines 713 and 738–739 are now executed. Remaining receipt-specific
  locations `705, 721, 752, 789` retain their prior dominance/error-translation
  explanations and require direct reviewer inspection.
- Compactness remains tools physical LOC `1279 <= 1300` and total production
  additions `1747 <= 1800`.

### Round-4 lifecycle state

- Remediation round: `4/10`.
- Independent Review 005: not run.
- Exact-byte rebind: not run.
- Terminal evidence audit: not run.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations: `0`.
- Staging, commit, push, PR, CI, Ready, merge, post-merge verification,
  control-plane reconciliation, and M3-003: not started.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 005 and Remediation Round 5/10

Independent Review 005 returned the immutable verdict:

`FAIL — P0 0 / P1 1 / P2 2`

Its exact findings were:

1. **P1 — confirmed contradiction adjudication lacked governed comparison and
   conflict binding.** A generic resolution could change an `uncertain`
   aggregate to `supported` without identifying the exact existing comparison,
   conflict, or governed scope-mismatch outcome that contextualized the
   contradiction.
2. **P2 — three directly reachable workflow defenses lacked executable public
   coverage.** The missing cases were finalization from DRAFT without approval,
   a self-consistent foreign persisted receipt differing from the checkpoint
   reference, and duplicate evidence identity spanning selected tasks.
3. **P2 — candidate accounting drifted.** The exact Round-4 compactness value
   was `1748`, not `1747`, and the frozen allowlist contained 19 paths while 18
   paths were actually changed.

Round 5 closes those findings without changing the receipt design or source,
evidence, comparison, or conflict semantics. A confirmed contradiction may be
contextualized only when the resolution binds an exact existing comparison and
conflict whose already-governed outcome is
`APPARENT_DIFFERENCE_SCOPE_MISMATCH`. Ordinary uncertain-support adjudication
remains available only without comparison/conflict bindings. The receipt and
its canonical payload bind those optional identities, so missing, extraneous,
foreign, unresolved, or drifted bindings fail closed. The three public workflow
regressions prove zero downstream effects. The exact-maximum citation fixture
remains genuinely valid and PASSes; max+1 fails for the intended cardinality
reason.

### Round-5 exact candidate identities before Review 006

The worktree has exactly 18 changed paths within the frozen 19-path allowlist;
`src/medevidence/persistence/__init__.py` remains byte-identical to baseline.
The delivery row below is its pre-Round-5-closure identity and is not a
self-binding final manifest.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md` (pre-Round-5 closure) | 1757 | 106178 | `c393fde85eb5e2fc50074efec89dda0203243baa2da2c6e1a0d0a7d99d28e354` |
| `alembic/versions/20260827_01_m3_validation_receipt.py` | 64 | 2527 | `a72fc3a807e228aa32c9d049d90493b9bca456384fd3f9919f9ee3d2e48358f7` |
| `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md` | 183 | 9796 | `4c97407e63845d1a9116991bede629484b815704f7fd5cd7816c6f003a90ec2b` |
| `docs/decisions/README.md` | 135 | 5953 | `373eedcaee578db758977e179dd8939b612b995a5890491feb8f28633b5db6e1` |
| `docs/TRACEABILITY_MATRIX.md` | 594 | 59456 | `f7a29bfbf1482c286635a986931f8eac4ddc227b646f2f7a6eb028e922113aa7` |
| `src/medevidence/orchestration/__init__.py` | 99 | 2369 | `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c` |
| `src/medevidence/orchestration/contracts.py` | 725 | 32037 | `9634a30439b3f12ef8838b2a40fdbd586b96ca1e7531baa0243a1b82049e5d2e` |
| `src/medevidence/orchestration/ports.py` | 123 | 3451 | `711f25295ca892a899a327c70469c2789bf28106ea6e16e41f777ada650dcb9d` |
| `src/medevidence/orchestration/workflow.py` | 1053 | 45456 | `dab24b249c62266df86b164e3c7919b1d15cc023802d45ae24aaffa273a27edc` |
| `src/medevidence/persistence/models.py` | 2287 | 100864 | `de32bb675105c1717a494abf3bc411607a99b7433c21f1e5985c6b84d1824f03` |
| `src/medevidence/persistence/repositories.py` | 2622 | 107008 | `9a46934e4e8bf56e3b7b509b06d8ebbef11ef663d68de0e5d8f205b336d9aa95` |
| `src/medevidence/tools/report_validation.py` | 1296 | 88489 | `d021576c9aee47d5235abeb7e47b915e57e001e4bfbe4fcb9ee8779ef43874a6` |
| `tests/integration/persistence/test_migrations.py` | 430 | 16519 | `8f994d61d566cfb1187bc7ccdb54f429e3dbe2d6f0d140d6b4262a1409761bf3` |
| `tests/integration/persistence/test_validation_receipts.py` | 242 | 8905 | `e77e4a4f8d225234be5fcc46f9fadb454595754d2ba4a24983ef8205d5824dc0` |
| `tests/unit/orchestration/test_contracts.py` | 472 | 16184 | `381a057bc5875252056de848f3a91d678d8de036a5abe2e47cf5786018d297cc` |
| `tests/unit/orchestration/test_workflow.py` | 2376 | 91535 | `fb8b7d29cab2347d7b7cbf48cf63bd1f6192b1dbad31c1cf5e5160fbb85f3f76` |
| `tests/unit/persistence/test_metadata.py` | 1046 | 38893 | `13246c09bbf68b43df8f20ecfa88a550d961026e2b413e0740201953072ec5bb` |
| `tests/unit/tools/test_report_validation.py` | 3111 | 114987 | `20d6f6243bcac050ccbfbbf97cccf5035dd545ff5cb69b24fb3471ef9e1996e0` |

### Round-5 ordered validation evidence

1. Tools authority suite: `201 passed`; validator coverage `99%`.
2. Integrated focused validator/workflow/contracts/persistence/dependency
   selection: `516 passed`; workflow coverage `91%`, contracts `80%`.
3. Full socket-disabled unit/contract suite: `2321 passed`, two expected
   warnings, `81%` repository coverage, `65.33s`.
4. Ruff check PASS; Ruff format check PASS across 151 files; strict MyPy PASS
   across 58 source files.
5. Offline lock PASS with 87 packages.
6. Exact 19-path allowlist / 18 changed-path scope, `git diff --check`, bounded
   secret-pattern, and dependency-file checks PASS. The compactness measure is
   now exactly `1765 <= 1800` added production lines across tools, ports, and
   workflow; validator physical LOC is `1296 <= 1300`.
7. Fresh offline dependency inventory: 86 packages, advisory status
   `not_run_offline`, external manifest SHA-256
   `a6918b1572e730c45fe0978d92d37e6a1b9ac0e238b3d9f5da1391e9bd2acfd8`,
   external network operations `0`.
8. The actual PostgreSQL 18.4 migration/receipt result remains `14 passed` and
   is bound to persistence, migration, and persistence-integration bytes that
   are unchanged in Round 5. No image pull occurred; the prior disposable
   container was removed and Docker stopped.

Two initial command starts produced no candidate execution: isolated-worktree
`uv run --no-sync` could not find pytest, and the first inventory start could
not find pip-audit. Both were rerun using the existing approved coordination
environment with candidate `src` first; no sync, install, download, test, or
audit was performed by the failed starts.

### Round-5 lifecycle state

- Remediation round: `5/10`.
- Independent Review 006: pending.
- Exact-byte rebind and terminal audit: not run.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations: `0`.
- Git staging, commit, push, PR, CI, Ready, merge, post-merge verification,
  control-plane reconciliation, and M3-003: not started.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 006 and Remediation Round 6/10

Independent Review 006 returned the immutable verdict:

`FAIL — P0 0 / P1 2 / P2 0`

It independently verified every Review-005 closure, including governed
contradiction binding, the valid exact-maximum graph, twelve cardinality-
specific max+1 failures, the exact 19-path allowlist, and `git diff --check`.
Its two findings were:

1. **P1 — critical pre-effect helper dispatch remained instance-shadowable,
   and finalization loaded a receipt before rejecting invalid approval
   topology.** A normal subclass with an instance dictionary shadowed
   `_verify_binding`, allowing a forged unknown receipt reference to reach
   pending persistence. A DRAFT/no-approval finalization invoked receipt load
   before its node/approval guard.
2. **P1 — approval and export did not bind the exact pending-draft persistence
   identity.** Substituting only `pending_draft.persistence_id` before approval,
   before export, or in an exported idempotent checkpoint could be accepted
   because the approval record bound report/hash but not the persisted draft
   identity.

Review 006 focused tests produced `285 passed`; its exact 18-path candidate
manifest was
`1e2bfdf3d4b8b388cf95df104e4d534ed80c21827212a24504514d3735cd08b0`.
It performed no writes, Git operations, network, medical-source, model,
package-download, or Holdout access.

Round 6 retains the same static application trust model. All durable,
topology, application, canonical-request, pending-draft, approval, and export
checks that require no capability now dominate receipt loading and every later
effect. Critical pre-effect and terminal-return helpers use lexically fixed
class dispatch, so subclass instance-dictionary shadowing cannot replace the
authoritative path; no origin seal, binder, callable fingerprint, or generic
anti-tamper mechanism is introduced.

The internal durable approval contract is versioned from
`m3.review-record.v1` to `m3.review-record.v2` and explicitly binds
`pending_draft_persistence_id`. The exact pending identity is derived from the
report ID and content hash, supplied to pending persistence and approval,
reconstructed from both returns, and compared through approval, export, and
idempotent terminal return. This is an internal orchestration checkpoint
contract change required by the already frozen exact-pending-draft invariant;
it changes no public API/OpenAPI or PostgreSQL schema.

Executable regressions prove zero capability calls for subclass helper
shadowing, DRAFT/no-approval finalization, foreign pending identity before
approval, substituted identity after approval before export, and mutated
identity on exported idempotent return.

### Round-6 exact candidate identities before Review 007

The worktree remains exactly 18 changed paths inside the frozen 19-path
allowlist. The delivery row is its pre-Round-6-closure identity and is not a
self-binding final manifest.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md` (pre-Round-6 closure) | 1861 | 112928 | `3b9b1841ee6a926ec8b13baa3a9a77a7234a3cf59d4815598add6a6a818a3b96` |
| `alembic/versions/20260827_01_m3_validation_receipt.py` | 64 | 2527 | `a72fc3a807e228aa32c9d049d90493b9bca456384fd3f9919f9ee3d2e48358f7` |
| `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md` | 183 | 9796 | `4c97407e63845d1a9116991bede629484b815704f7fd5cd7816c6f003a90ec2b` |
| `docs/decisions/README.md` | 135 | 5953 | `373eedcaee578db758977e179dd8939b612b995a5890491feb8f28633b5db6e1` |
| `docs/TRACEABILITY_MATRIX.md` | 616 | 60808 | `bcf8b0761c273119913c2fb3b1ece2b6ec6252a20a7300a138d97b8a77103db6` |
| `src/medevidence/orchestration/__init__.py` | 99 | 2369 | `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c` |
| `src/medevidence/orchestration/contracts.py` | 729 | 32256 | `fb5e1309221811e395734a8a28a0b024880a16164b333ef40c0682acd95c3edb` |
| `src/medevidence/orchestration/ports.py` | 125 | 3537 | `b7ce23b72196f7333dbfb1e552286cc86e16ab80a17d2dfb638cd0abb3f2768f` |
| `src/medevidence/orchestration/workflow.py` | 1084 | 47367 | `16394ecd66732e95e41c72f4a5fb244f3d5da5f4d866a4ce6ce3889d1bc2d0b7` |
| `src/medevidence/persistence/models.py` | 2287 | 100864 | `de32bb675105c1717a494abf3bc411607a99b7433c21f1e5985c6b84d1824f03` |
| `src/medevidence/persistence/repositories.py` | 2622 | 107008 | `9a46934e4e8bf56e3b7b509b06d8ebbef11ef663d68de0e5d8f205b336d9aa95` |
| `src/medevidence/tools/report_validation.py` | 1296 | 88489 | `d021576c9aee47d5235abeb7e47b915e57e001e4bfbe4fcb9ee8779ef43874a6` |
| `tests/integration/persistence/test_migrations.py` | 430 | 16519 | `8f994d61d566cfb1187bc7ccdb54f429e3dbe2d6f0d140d6b4262a1409761bf3` |
| `tests/integration/persistence/test_validation_receipts.py` | 242 | 8905 | `e77e4a4f8d225234be5fcc46f9fadb454595754d2ba4a24983ef8205d5824dc0` |
| `tests/unit/orchestration/test_contracts.py` | 499 | 17271 | `6b186d57f64038bf53878496c99cd2f4d05fe05954825e6af06f8359ed56033c` |
| `tests/unit/orchestration/test_workflow.py` | 2553 | 97467 | `5cc000fc60aa694cdd3a2e420139f6e0600df79d2878202eb7475a103fad4216` |
| `tests/unit/persistence/test_metadata.py` | 1046 | 38893 | `13246c09bbf68b43df8f20ecfa88a550d961026e2b413e0740201953072ec5bb` |
| `tests/unit/tools/test_report_validation.py` | 3111 | 114987 | `20d6f6243bcac050ccbfbbf97cccf5035dd545ff5cb69b24fb3471ef9e1996e0` |

### Round-6 ordered validation evidence

1. Implementation-node validator/workflow/contracts selection: `305 passed`.
2. Supervisor focused validator/workflow/contracts/persistence/dependency
   selection: `521 passed`; validator coverage `99%`, workflow `90%`, contracts
   `80%`.
3. Full socket-disabled unit/contract suite: `2326 passed`, two expected
   warnings, `81%` repository coverage, `67.93s`.
4. Ruff and format PASS across 151 files; strict MyPy PASS across 58 source
   files; offline lock PASS with 87 packages.
5. Exact 19-path allowlist / 18 changed paths, `git diff --check`, bounded
   secret-pattern, and dependency-file checks PASS. Validator physical LOC is
   `1296 <= 1300`; exact tools/ports/workflow growth is `1798 <= 1800`.
6. Fresh offline dependency inventory: 86 packages, advisory status
   `not_run_offline`, manifest SHA-256
   `869a63fa9ff14246057fa53b3694ea5bb28c37576cbccd534656816635edcf29`,
   external network operations `0`.
7. Persistence, migration, and persistence-integration bytes remain unchanged;
   the actual PostgreSQL 18.4 migration/receipt evidence remains `14 passed`.

### Round-6 lifecycle state

- Remediation round: `6/10`.
- Independent Review 007: pending.
- Exact-byte rebind and terminal audit: not run.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations: `0`.
- Git staging, commit, push, PR, CI, Ready, merge, post-merge verification,
  control-plane reconciliation, and M3-003: not started.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 007 and Remediation Round 7/10

Independent Review 007 returned the immutable verdict:

`FAIL — P0 0 / P1 2 / P2 1`

Its exact findings were:

1. **P1 — canonical request validation still followed receipt-store load.** A
   FAERS checkpoint missing `faers_mandatory_limitations` failed canonical
   verification only after one receipt load.
2. **P1 — deterministic pending identity did not prove persistence.** A forged
   checkpoint could derive the expected ID and fabricate a matching pending
   reference without calling `save_pending`, then obtain approval, export, and
   idempotent terminal acceptance.
3. **P2 — the instance-shadow test was not executable at the intended
   boundary.** It also corrupted approval topology, so the test passed before
   reaching the lexically fixed `_verify_binding` call.

Review 007 independently verified the code-level instance-shadow closure, all
Review-005 maximum/boundary closures, single canonical authority, compactness,
scope, dependency, and diff gates. Its exact candidate manifest was
`60a618a39451e44f6b190c23bdb934ce696737f8db273c81c99675c03152eeb8`.

Round 7 moves evaluator-free `canonical_validate_report(VERIFY_BINDING)` before
receipt loading, so all canonical source/safety/structural failures dominate
every store capability. It extends the trusted application-owned
`DraftPersistencePort` with durable `load_pending`; every returned pending row
is untrusted and exactly reconstructed. Save now requires successful durable
read-back before checkpointing. Approval, export/finalization, idempotent
export, and terminal resume first complete local preflight, then load and bind
the exact durable pending row, then load/bind the receipt, and only then perform
an effect or trusted return. Missing, forged, substituted, stale, malformed, or
foreign pending state fails closed. No database schema, public API, dependency,
origin token, binder, fingerprint, or anti-tamper mechanism is introduced.

The instance-shadow regression now uses an otherwise-valid
`SAVE_PENDING_DRAFT` topology with only an unknown receipt reference; it reaches
the lexically fixed implementation, observes the authoritative receipt load,
and proves zero pending/approval/export effects.

### Round-7 exact candidate identities before Review 008

The worktree remains exactly 18 changed paths inside the frozen 19-path
allowlist. The delivery row is its pre-Round-7-closure identity and is not a
self-binding final manifest.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `.delivery/M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION.md` (pre-Round-7 closure) | 1971 | 120005 | `398c633e46f6a6327c1d6aa5957d4775041c86f0470ccdfdebce6ddd189fc30f` |
| `alembic/versions/20260827_01_m3_validation_receipt.py` | 64 | 2527 | `a72fc3a807e228aa32c9d049d90493b9bca456384fd3f9919f9ee3d2e48358f7` |
| `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md` | 183 | 9796 | `4c97407e63845d1a9116991bede629484b815704f7fd5cd7816c6f003a90ec2b` |
| `docs/decisions/README.md` | 135 | 5953 | `373eedcaee578db758977e179dd8939b612b995a5890491feb8f28633b5db6e1` |
| `docs/TRACEABILITY_MATRIX.md` | 644 | 62573 | `00d1ac4bde1e0ca9d86ac15f84cc5c125d894bad3b95faaabc5abf3ce822a1a3` |
| `src/medevidence/orchestration/__init__.py` | 99 | 2369 | `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c` |
| `src/medevidence/orchestration/contracts.py` | 729 | 32256 | `fb5e1309221811e395734a8a28a0b024880a16164b333ef40c0682acd95c3edb` |
| `src/medevidence/orchestration/ports.py` | 121 | 3297 | `fac8c36c25b168263e89af4955eaddd90ce300d38a9003fd28dd97d3fa072983` |
| `src/medevidence/orchestration/workflow.py` | 1086 | 48330 | `7bd86e443a2b5142300674176802ba2528c1ce8e1dbf3955d52dd999d262bc3c` |
| `src/medevidence/persistence/models.py` | 2287 | 100864 | `de32bb675105c1717a494abf3bc411607a99b7433c21f1e5985c6b84d1824f03` |
| `src/medevidence/persistence/repositories.py` | 2622 | 107008 | `9a46934e4e8bf56e3b7b509b06d8ebbef11ef663d68de0e5d8f205b336d9aa95` |
| `src/medevidence/tools/report_validation.py` | 1296 | 88489 | `d021576c9aee47d5235abeb7e47b915e57e001e4bfbe4fcb9ee8779ef43874a6` |
| `tests/integration/persistence/test_migrations.py` | 430 | 16519 | `8f994d61d566cfb1187bc7ccdb54f429e3dbe2d6f0d140d6b4262a1409761bf3` |
| `tests/integration/persistence/test_validation_receipts.py` | 242 | 8905 | `e77e4a4f8d225234be5fcc46f9fadb454595754d2ba4a24983ef8205d5824dc0` |
| `tests/unit/orchestration/test_contracts.py` | 499 | 17271 | `6b186d57f64038bf53878496c99cd2f4d05fe05954825e6af06f8359ed56033c` |
| `tests/unit/orchestration/test_workflow.py` | 2737 | 104431 | `137840b400e43d3fc18c97b6c937368889d5ea45ab939d18a21f2956393d3275` |
| `tests/unit/persistence/test_metadata.py` | 1046 | 38893 | `13246c09bbf68b43df8f20ecfa88a550d961026e2b413e0740201953072ec5bb` |
| `tests/unit/tools/test_report_validation.py` | 3111 | 114987 | `20d6f6243bcac050ccbfbbf97cccf5035dd545ff5cb69b24fb3471ef9e1996e0` |

### Round-7 ordered validation evidence

1. Implementation-node focused tests: `329 passed`.
2. Supervisor focused validator/workflow/contracts/persistence/dependency
   selection: `545 passed`; validator coverage `99%`, workflow `90%`, contracts
   `80%`.
3. Full socket-disabled unit/contract suite: `2350 passed`, two expected
   warnings, `81%` repository coverage, `66.72s`.
4. Ruff and format PASS across 151 files; strict MyPy PASS across 58 source
   files; offline lock PASS with 87 packages.
5. Exact 19-path/18-changed-path scope, diff, secret, and dependency-file
   checks PASS. Validator LOC is `1296 <= 1300`; tools/ports/workflow growth is
   `1796 <= 1800`.
6. Fresh offline dependency inventory: 86 packages, advisory status
   `not_run_offline`, manifest SHA-256
   `c907ee33cbe2120df7a40b644af4757a3f828d9b87f3aa541860931d1596082e`,
   external network operations `0`.
7. Unchanged persistence/migration bytes retain actual PostgreSQL 18.4
   migration/receipt evidence of `14 passed`.

### Round-7 lifecycle state

- Remediation round: `7/10`.
- Independent Review 008: pending.
- Exact-byte rebind and terminal audit: not run.
- Medical-source, model/provider, dependency-download, Holdout, and external
  network operations: `0`.
- Git staging, commit, push, PR, CI, Ready, merge, post-merge verification,
  control-plane reconciliation, and M3-003: not started.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 008 and Remediation Round 8/10

Independent Review 008 returned the immutable verdict:

`FAIL — P0 0 / P1 0 / P2 2`

Its exact findings were:

1. **P2 — ADR-016 described superseded effect-boundary ordering.** The current
   implementation completes durable/topology/application/request reconstruction
   and evaluator-free canonical `VERIFY_BINDING` before any pending/receipt-
   store capability. Pending-bearing routes then load/reconstruct/bind the exact
   durable pending draft before receipt load/reconstruction/binding; pending
   save immediately durable-read-backs the exact saved row before checkpoint.
   ADR-016 instead still described receipt loading before canonical verification
   and omitted the trusted application-owned `DraftPersistencePort`, untrusted
   returned `PendingDraftRef`, and post-save read-back contract.
2. **P2 — one current scope sentence conflated allowlist and changed-path
   counts.** The frozen allowlist contains exactly 19 paths; exactly 18 paths
   currently differ from baseline because
   `src/medevidence/persistence/__init__.py` remains unchanged.

Review 008 independently verified the unchanged executable candidate evidence:
focused validation `545 passed`; full socket-disabled unit/contract suite
`2350 passed` with two expected warnings; exact max fixture PASS plus intended
max+1 boundary failures; `git diff --check`; validator LOC `1296 <= 1300`;
tools/ports/workflow growth `1796 <= 1800`; exact 19-path allowlist with 18
changed paths; and zero network or Git operations.

Round 8 changes only this delivery record, ADR-016, and the existing
traceability mapping. It aligns all current architecture sequences with the
already-implemented local reconstruction → evaluator-free canonical VERIFY →
exact durable pending binding when present → exact receipt binding → effect or
trusted return order. It records trusted static selection of both durable-store
capabilities, treats all returned pending/receipt values as untrusted data, and
records immediate pending durable read-back before checkpoint. It also corrects
only the current 19-allowlisted/18-changed-path wording; all historical
measurements and verdicts remain immutable. No code or test byte changed in
Round 8, so the independently verified focused/full/max/boundary/compactness
evidence above applies to those unchanged executable bytes and was not
needlessly rerun by this documentation-only node.

Round-8 documentation validation passes Markdown structure and local-reference
resolution, required/obsolete wording searches, exact changed-scope accounting,
and `git diff --check`. External network, medical-source, model/provider,
dependency-download, Holdout, staging, commit, push, PR, CI, Ready, merge,
post-merge, control-plane, and M3-003 operations remain `0` / not performed.

Current lifecycle state:

- Remediation round: `8/10`.
- Independent Review 009: pending.
- Exact-byte rebind and terminal audit: not run.
- Current status: `AWAITING_INDEPENDENT_REVIEW_009`.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.

## Independent Review 009 — zero-finding review PASS

Fresh independent Review 009 returned:

`PASS — P0 0 / P1 0 / P2 0`

Findings: none. The reviewer directly verified ADR/delivery/traceability
consistency, canonical-before-capability ordering, durable pending read-back,
receipt binding, instance-shadow resistance, exact maximum and all twelve
max+1 boundary reasons, the single canonical authority, compactness, and exact
scope. Fresh executable evidence was `313 passed`, with boundary/shadow subset
`14 passed` and effect/terminal fail-closed subset `26 passed`, all socket-
disabled.

Review 009 bound:

- baseline/HEAD `35fd27231cd8042965bf3c4ccf62bd173600e0b5`;
- canonical 19-path allowlist manifest SHA-256
  `4f3c4f42af1960e24f04fc5bb11c6636f181031171300de3322f9899dd3a2712`;
- canonical 18-changed-path manifest SHA-256
  `2ba31b116dfba7fb1eef697bb10295acaed722e4d07013eca3627c75517d273c`;
- validator physical LOC `1296 <= 1300` and tools/ports/workflow growth
  `1796 <= 1800`; and
- zero staged paths, Git writes, network, medical-source, model, package-
  download, or Holdout operations.

This review PASS authorizes exact-byte rebind; it is not the terminal evidence-
audit or integration PASS. These verdict-recording documentation edits must be
included in the external final 19-path manifest. Candidate repository bytes
must then remain frozen through terminal audit.

Current lifecycle state:

- Remediation consumed: `8/10`; no additional round is active.
- Independent Review 009: `PASS — P0 0 / P1 0 / P2 0`.
- Exact-byte rebind: next.
- Terminal evidence audit: pending.
- Git integration and M3-003: not started.
- Current status: `AWAITING_TERMINAL_EVIDENCE_AUDIT`.

No terminal-audit PASS, final integration PASS, staging, commit, push, PR, CI,
Ready, merge, post-merge verification, reconciliation, or M3-003 start is
claimed by this in-repository record.

## Independent Review 003 — design hard stop

Fresh independent plain review returned the formal immutable verdict:

`FAIL — P0 0 / P1 2 / P2 0`

Platform safety-classifier failures encountered by other review attempts are
execution-platform interruptions only. They are not M3-002 candidate findings,
are not counted in the verdict above, and do not replace the completed fresh
plain review.

The exact Review 003 findings are:

1. **P1-01 — A forged passing pre-save durable checkpoint can trigger
   persistence without evidence that initial ASSESS executed.** The forged
   checkpoint contains a synthesis and caller-supplied passing stored gates and
   reasons. Pure VERIFY recomputes those values from the same untrusted registry
   and therefore accepts their equality, while `semantic_calls == 0`; the
   pending-draft persistence capability is then invoked. Closed composition
   prevents caller-supplied validator code, but it does not prove historical
   execution of Stage 2 ASSESS.
2. **P1-02 — One SUPPORTS citation plus one semantically confirmed CONTRADICTS
   citation can still PASS.** Stage 2 aggregation combines semantic results
   without incorporating `CitationRelationship`. When both citation results
   are confirmed as supported, the contradicting relationship does not prevent
   acceptance or require adjudication, so a materially contradicted formal
   claim can receive canonical PASS.

### P1-01 classification: closed-composition design conflict

P1-01 is classified:

`CLOSED_COMPOSITION_DESIGN_CONFLICT`

The conflict is structural, not an ordinary same-design mechanical defect:

- the baseline durable `ReportValidationState` stores only three gates and a
  reason tuple; it contains no assessment receipt, evaluator-execution receipt,
  or independently bound Stage 2 completion identity;
- the frozen pure VERIFY contract intentionally forbids semantic evaluator
  replay before save, approval, export, idempotent return, and terminal resume;
  and
- current authorization prohibits durable schema and persistence changes.

Consequently, the current approved design supplies neither permitted mechanism
that could distinguish a legitimate previously assessed passing checkpoint from
a forged checkpoint containing the same untrusted registry and stored passing
values. Continuing mechanically would require violating at least one frozen
boundary.

The Owner hard-stop condition therefore applies before Round 3. Remediation
budget consumed remains `2/8`; Round 3 has not started and no Round 3 changes
are authorized by this record.

### Owner decision required

Progress requires one explicit Owner choice:

1. **Authorize Stage 2 re-execution before every effect and synthesis-bearing
   resume.** This changes the frozen pure-VERIFY/no-evaluator-replay behavior and
   would require new bounded evaluator failure/idempotency tests.
2. **Authorize a durable validation-receipt schema and persistence change.**
   The receipt must independently bind report/run/scope/registry/evaluator,
   assessment result, and exact content identity before pure VERIFY can prove
   prior ASSESS. This expands durable schema/persistence scope and requires a
   separately frozen migration/compatibility design.
3. **Stop successor-002.** Preserve Review 003 FAIL and the current candidate as
   non-integrable historical implementation/regression evidence.

No option is selected or inferred by this record.

P1-02 remains unresolved. No semantic-relationship aggregation or adjudication
remediation was attempted after Review 003 because the design hard stop occurred
first. It must not be represented as closed by prior green tests.

Current status:
`OWNER_DECISION_REQUIRED_CLOSED_COMPOSITION_DESIGN_CONFLICT`.

Exact-byte rebind, terminal evidence audit, staging, commit, push, PR, CI,
Ready, merge, post-merge verification, control-plane reconciliation, and
M3-003 have not started. Network operations and Git operations remain `0`.
No Review PASS or final `PASS — P0 0 / P1 0 / P2 0` is claimed.

## Owner design resolution — durable validation receipt

- Owner Accepted: `2026-08-27`
- Work item: `M3-002-SUCCESSOR-002-CLOSED-VALIDATION-COMPOSITION`
- Governing record:
  `docs/decisions/ADR-016-durable-validation-receipt-and-pure-binding-verification.md`

This resolution does not alter the immutable Review 003 verdict
`FAIL — P0 0 / P1 2 / P2 0`, does not erase Rounds 1–2, and is not Round-3
remediation. It selects the independently persisted durable-receipt option and
rejects Stage-2 replay during binding verification.

### Frozen receipt identity and persistence contract

- Marker/schema identity: `M3_VALIDATION_RECEIPT_V1`.
- Semantic content binds receipt, run, report, exact report content hash,
  canonical validation-input identity/hash, selected-source/task/outcome
  identity, Stage-1 result identity, Stage-2 evaluator method/version, exact
  ordered per-claim/per-citation Stage-2 result identity, relationship-aware
  aggregate identity, and required policy/configuration versions.
- `receipt_id` is deterministically derived from the exact canonical semantic
  content using existing canonical JSON/SHA-256 identity conventions.
  Operational timestamps may be stored but are excluded from semantic identity
  unless an existing repository invariant requires otherwise. No opaque
  confidence score is introduced.
- Durable `OrchestrationState.validation_receipt_ref` is a reference only. A
  checkpoint body, boolean, enum, inline receipt, self-computed hash, or other
  caller assertion cannot authorize progression.
- The source-neutral exact contracts are `ValidationReceipt` and
  `ValidationReceiptStorePort`; the store exposes only `save_receipt` and
  `load_receipt`. Persistence output is untrusted data and is reconstructed and
  verified by application code.
- The PostgreSQL adapter saves immutable canonical receipt content and loads it
  by exact receipt identity. An exact repeated insert may be idempotent only
  when reconstructed semantic bytes/content are identical; a conflicting
  duplicate fails closed.
- A real migration is required because existing durable checkpoint/report
  storage contains no independent application-owned receipt authority. The
  exact migration creates only the validation-receipt table. The checkpoint
  reference remains inside the existing durable payload, so no unrelated
  checkpoint/report column or data migration is permitted.

### Frozen authority and effect sequence

```text
canonical reconstruction
  -> deterministic Stage 1
  -> Stage 2 evaluation
  -> relationship-aware aggregation
  -> canonical receipt construction
  -> immutable save_receipt
  -> durable validation_receipt_ref

every save/approval/export/finalization/idempotent/terminal boundary
  -> complete durable and application reconstruction
  -> canonical_validate_report(VERIFY_BINDING), semantic calls=0
  -> exact stored gate/reason/reference equality
  -> when present: load_pending(pending_draft.persistence_id)
  -> exact pending persistence/report/content binding
  -> load_receipt(validation_receipt_ref)
  -> exact receipt content/identity/current-state binding
  -> effect or trusted return

save_pending_draft after common preflight and receipt binding
  -> save_pending
  -> exact returned PendingDraftRef reconstruction and binding
  -> load_pending
  -> exact durable pending read-back binding
  -> pending-review checkpoint
```

Trusted static application composition selects both the independently durable
`DraftPersistencePort` and `ValidationReceiptStorePort`. Every returned
`PendingDraftRef` and receipt payload is untrusted data and is exactly
reconstructed. Missing, unknown, inline-only, foreign-run, stale report-hash,
different-validation-input, evaluator/policy-inconsistent, malformed, or
otherwise unbound receipts fail before any persistence, approval, export,
finalization, idempotent return, or terminal trusted return. Missing, foreign,
stale, substituted, malformed, or otherwise unbound pending drafts fail before
receipt loading and any later effect/return; a failed post-save durable read-back
publishes no pending-review checkpoint. A report or validation-relevant edit
clears the reference; progression requires a new assessment and new persisted
receipt. No pending draft or receipt is silently repaired or upgraded. This is
application composition and data reconstruction, not a general Python runtime
anti-tamper mechanism.

### Frozen relationship-aware aggregation

- `context_only` never satisfies direct material-claim support.
- Automatic `supported` requires at least one `supports` citation whose
  semantic result is `supported`, no unresolved semantically confirmed
  contradiction, and no required direct citation remaining `uncertain`.
- An applicable, semantically confirmed `contradicts` citation prevents
  automatic `supported`; the default unresolved result is `uncertain`.
- Majority vote, citation count, retrieval score, model confidence, and source-
  type weighting are forbidden resolution mechanisms.
- Only the existing governed comparability/conflict adjudication contract may
  contextualize a contradiction, and the resolution remains explicit. No new
  conflict taxonomy is introduced.

### Review-003 executable acceptance set

The exact A–K cases are: forged PASS/no receipt; inline-only receipt;
foreign-run receipt; stale report-hash receipt; different validation inputs;
valid receipt from actual canonical Stage-2 assessment with evaluator-free
verify; edit invalidation and reassessment; supported supporting citation;
supported supporting plus confirmed contradicting citation producing
unresolved `uncertain`; context-only insufficiency; and preserved explicit
human-resolution behavior. All earlier M3-002 and successor regressions remain
required.

### Current lifecycle state after design resolution

- Budget: `2/10` consumed; Rounds 3–10 authorized for same-design findings.
- Exact scope: the expanded 19-path allowlist in this record; no twentieth
  path.
- Round 3: in progress. This allowlist correction is the first Round-3 action;
  receipt schema/source/test writing and persistence execution have not yet
  begun at this checkpoint.
- Review 003 P1-01/P1-02: open and not represented as remediated.
- Exact-byte rebind, terminal audit, staging, commit, push, PR, CI, Ready,
  merge, post-merge verification, control-plane reconciliation, and M3-003:
  not started.
- Network and Git operations for this design-freeze node: `0`.

Current status:
`DURABLE_RECEIPT_DESIGN_FREEZE_COMPLETE_ROUND_3_IN_PROGRESS`.

No implementation PASS, review PASS, audit PASS, final
`PASS — P0 0 / P1 0 / P2 0`, or integration is claimed.

## Independent Review 002 and Remediation Round 2/8 evidence

Independent Review 002 returned the immutable verdict:

`FAIL — P0 0 / P1 1 / P2 3`

This verdict and its exact four findings are preserved:

1. **P1 — Scope collections bypass cardinality-first admission and leak a
   non-canonical exception.** Review reproduced max+1 drugs reaching inner
   Pydantic validation instead of an outer cardinality-specific
   `CanonicalValidationError`. The same missing-bound pattern affected request
   tasks, comparison dimensions, outcome warnings, and stored reasons.
2. **P2 — Mandatory changed-workflow coverage remains incomplete, and claimed
   exceptions include publicly reachable branches.** Review directly reached
   selected-source expansion and exported-idempotency drift and identified
   additional public defenses for collection-result binding, terminal lineage,
   evidence authority, rejected-state consistency, transition guards, and
   absent synthesis.
3. **P2 — Both frozen compactness ceilings are exceeded.** Review measured the
   tools authority at 1127 physical lines and total additions at 1546, exceeding
   the 1100 and below-1500 ceilings.
4. **P2 — Duplicate identity rejection is not globally performed before
   lookup-map construction.** Duplicate resolutions were functionally closed,
   but report-content hashing still constructed a citation map before the raw
   duplicate-identity check.

Review 002 also verified the Round 1 closures for duplicate resolutions,
validation-blocked exact resume, the first nested maxima, zero validation port,
the authorized seven-path scope, unchanged contracts/dependencies/lock, and
zero network/Git operations. Those observations do not override its FAIL.

### Round 2 closure candidates

1. **Cardinality-first public admission.** Exact public matrices now cover:
   drugs 4/5, adverse reactions 8/9, selected sources 4/5, request tasks 4/5,
   comparison dimensions 11/12, outcome warnings 100/101, the complete
   `ClaimClass` permission set plus one wrong-type member, and the complete
   `InferenceUse` permission set plus one wrong-type member. Every
   graph-representable exact maximum produces canonical PASS with the expected
   evaluator count. Every max+1 case returns its exact cardinality code before
   malformed-member traversal or evaluation.

   Stored reasons use a request-relative bound rather than a fabricated fixed
   100-reason PASS: exact stored failed reasons equal to the fresh closed
   summary VERIFY successfully, while length + 1 containing a malformed member
   raises `stored_validation_reason_cardinality_mismatch` before reason
   traversal. The closed reason universe cannot generate 100 distinct canonical
   reasons, so no false exact-100 PASS is claimed.

   The graph-valid nested maxima remain claim citations 300, evidence locators
   1, claim limitations 100, and numerical facts 100. Three relationships over
   one selected task's maximum 100 evidence references yield 300 unique
   canonical citations; one locator preserves exact durable locator binding.
2. **Raw identity sequencing.** Raw claim, citation, evidence, expectation,
   resolution, comparison, and conflict identity tuples are checked before
   report hashing or lookup-map construction. An instrumented duplicate
   resolution reproduction calls neither `canonical_report_content_hash` nor
   the semantic evaluator and returns `registry_identity_duplicate`. The
   instrumentation observes call sequencing only and is not treated as a
   runtime-replacement threat model.
3. **Compactness.** The Round 2 compactness gate measured the tools authority
   at 1080 physical lines and production additions at 1499, satisfying the
   original ceilings. The final request-relative stored-reason adjustment then
   reduced the current exact tools file to 1078 physical lines; no compactness
   regression was introduced.
4. **Reachable workflow coverage.** Public-route tests now execute scope
   expansion, nonpermitted planning, mismatched failure/result attempts,
   foreign result source/run, persisted failed-task resume, terminal and wrong
   node guards, absent synthesis, and the requested zero-effect drift paths.
   Workflow coverage increased from 87% to 92%. Remaining locations are listed
   below with corrected dominance/unconstructibility evidence.

### Exact Round 2 candidate bytes before Review 003

These six code/test path values were recomputed from the current worktree. The
delivery record is excluded from its own table pending later exact-byte rebind.

| Path | Physical LOC | Bytes | SHA-256 |
|---|---:|---:|---|
| `src/medevidence/tools/report_validation.py` | 1078 | 66746 | `d1dea1bd4ef911376849e845992d166057502fc7f2353546b7b9011f651184d1` |
| `src/medevidence/orchestration/workflow.py` | 973 | 41753 | `dcd757ff5a100e99ea7df69f20ddeae93b47514c6859a53646a4ad7809b54679` |
| `src/medevidence/orchestration/ports.py` | 105 | 2766 | `7c585472c22c294c87ed7342a4d9fd2917fc333d955e0cb67ed12709211b46e3` |
| `src/medevidence/orchestration/__init__.py` | 95 | 2249 | `7e292a21b40f9d4b2b6d9e5c1fad637410cbd3050373ee2344738a462799b98c` |
| `tests/unit/tools/test_report_validation.py` | 2231 | 82071 | `c5db3260cdc5ba7b252a2b2a2e846660ec2725cad275263143bc4ce5b0372aa4` |
| `tests/unit/orchestration/test_workflow.py` | 1837 | 70005 | `38f237483f686d181766467f059ac291f3d198a4d294e8692a4ff9f2010a66d6` |

### Round 2 ordered validation evidence

All commands used current successor bytes, existing locked local dependencies,
socket-disabled offline execution, and no synchronization or download.

1. Tools suite: `144 passed`.
2. Workflow plus tools suites: `209 passed`.
3. Focused M3/domain/dependency-boundary suite: `665 passed`.
4. Full offline unit/contract suite: `2233 passed`, two expected warnings,
   `81%` repository coverage, `59.27s`.
5. Ruff check: PASS across 149 files.
6. Ruff format check: PASS across 149 files.
7. Strict MyPy: PASS across 58 source files.
8. Offline lock check: PASS; 87 locked packages; network `0`.
9. Exact seven-path scope, diff, secret, and dependency-file checks: PASS.
10. Fresh offline dependency inventory: PASS; 86 installed packages; advisory
    status `not_run_offline`; network operations `0`.

Tools line/branch coverage is `99%`. Its only remaining uncovered lines are
605, 642, and 1043:

- line 605 repeats task-evidence cardinality after the exact outer task guard;
- line 642 is a duplicate-locator defense after the graph-valid locator maximum
  of one, so any duplicate-capable tuple is rejected by cardinality first; and
- line 1043 repeats semantic-expectation binding already completed globally by
  Stage 1, with no capability or effect between checks.

Workflow line/branch coverage is `92%`, increased from 87%. The exact remaining
locations are:

`145, 235, 311, 366, 506, 521, 590, 666, 744, 753, 763, 768, 780, 794, 820,
844, 864, 887, 910`.

Their current classification for Review 003 is:

- line 145 requires a `current_node` outside the closed `WorkflowNode` enum;
- line 235 requires a RUNNING source task without the required active attempt;
- lines 311 and 590 require a post-collection selected task without terminal
  state/outcome;
- line 366 is the deterministic direct summary-to-validation equality check,
  with no untrusted operation between construction and comparison;
- lines 506 and 521 repeat finalization checks after durable/application
  selected-task and approval preflight;
- line 666 requires nonterminal stored gates in a topology that already
  requires terminal validation;
- lines 744, 753, 763, 768, 780, 794, 820, 844, and 864 repeat application
  checks dominated by `OrchestrationState.model_validate` over status/topology,
  selected tasks, terminal lineage/evidence, approval/export binding, and
  terminal disposition consistency;
- line 887 is dominated by `StaticWorkflowPermissions` exact-topology
  validation; and
- line 910 is dominated by the exact current/completed topology-prefix rule.

Public tests assert each dominant rejection and zero effects. No private helper
is called to manufacture coverage. Independent Review 003 must inspect this
reachability evidence directly.

Fresh offline dependency inventory manifest:

- path:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-002-s2-r2-deps-54b13d2aa7c44fd59fe2b007e1fbd4ef`
- SHA-256:
  `a2cdfe7b2cb279fc711781f47a5ebef88815ad3394f67b81acef28568ae23897`
- advisory status: `not_run_offline`
- installed package count: `86`
- network operations: `0`

### Round 2 scope and lifecycle state

- Remediation budget consumed: `2/8`.
- Exact corrected seven-path scope: PASS; no eighth path changed.
- Scope, diff, secret, and dependency-file checks: PASS.
- `contracts.py`, domain, connectors, ingestion, retrieval, evaluation, API,
  frontend, MCP, dependency, lock, fixture, corpus, qrels, metric-contract, and
  Holdout paths remain unchanged and prohibited.
- Medical-source, model/provider, dependency-download, advisory, Holdout, and
  all other network traffic: `0`.
- Independent Review 003: not run.
- Exact-byte rebind: not run.
- Terminal evidence audit: not run.
- Staging, commit, push, PR, CI, Ready, merge, rebase, reset, clean, branch
  deletion, history rewrite, and remote operations: `0` / not performed.

Current status:
`AWAITING_INDEPENDENT_REVIEW_003`.

No Review PASS, final `PASS — P0 0 / P1 0 / P2 0`, exact-byte rebind, terminal
audit, or Git integration is claimed.
