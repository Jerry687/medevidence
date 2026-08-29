# M3-006 source capability adapters

## Status

`AWAITING_TERMINAL_AUDIT`

- Work item: `M3-006-SOURCE-CAPABILITY-ADAPTERS`
- Branch: `codex/m3-006-source-capability-adapters`
- Baseline and current HEAD before candidate commit:
  `46eb93bb61524bae102c068d87372f1e63de7c89`
- Owner decision: `A - APPROVED WITH EXACT CLARIFICATIONS`
- Full M3 authorization SHA-256:
  `e6b812f6411b8e8a62a559ae0182b45cae25bc70d0173c135b94e97b8cd73fa8`
- Remediation: R1-R10 used; authorized budget 10/10 exhausted
- Holdout-20: sealed

This record preserves the initial and Round 3-R9 independent review FAILs and
records final Round 10 review PASS. It does not claim exact-byte rebind,
terminal audit, overall PASS, commit, push, PR, CI, ready, merge, or post-merge
verification.

## Outcome and design

The candidate supplies one source-capability boundary for PubMed, DailyMed,
FAERS, and local CADEC under the existing eight-node workflow. Plan rows equal
the exact selected scope sources; tasks equal only selected rows; skipped rows
remain visible without tasks or outcomes. Required operations are frozen and
checkpointed before effects, reconstruct on resume, and bind exact run, task,
attempt, source, ordinal, kind, query, acquisition, outcome, and observation
content. Final task state requires every final required operation terminal.

One deterministic aggregate authority applies the Owner-frozen execution,
coverage, result, and warning rules. PubMed preserves search plus exact ordered
PMID fetches. DailyMed preserves discovery/selection/fetch identity and creates
no non-required fetch. FAERS preserves exact aggregate execution and
persistence plus `faers_mandatory_limitations`.

CADEC rereads the exact approved archive and manifest, verifies all 1,248
admitted documents, retains the two approved zero-length documents without
chunks, and transiently scores the other 1,246 whole documents. The canonical
preferred-term query rejects overflow; BM25 is exactly `k1=0.9`, `b=0.4`; only
positive top-20 refs survive, ordered by descending score then UTF-8 document
ID. Integrity failure exposes no refs and maps to
`failed / unavailable / indeterminate`. CADEC remains auxiliary and always
carries `cadec_mandatory_limitations`. No text/chunk persistence or M2
router/qrels/corpus/metric change occurs.

The design keeps tools contract-only, orchestration dependent on explicit
injected application ports, and concrete CADEC paths/BM25 in infrastructure.
There is no mutable dispatch table or provider fallback.

Round 4 adds durable v3 typed input refs, scope/acquisition-intent binding,
RUNNING operation progress, and canonical reconstruction of every terminal
outcome field. PubMed reloads immutable ordered PMID membership from the
existing snapshot journal; DailyMed reloads durable discovery provenance. Each
source operation stage checkpoints before a dynamic fetch stage.

The structural `SourceCapabilities` authority now contains only PubMed,
DailyMed, and FAERS. The final sealed infrastructure wrapper alone internally
constructs the concrete CADEC adapter from explicit paths, intercepts CADEC,
and delegates the other sources. Production composition constructs this exact
route; callers cannot inject a search adapter or asset-free result.

Round 5 freezes the CADEC wrapper and its concrete adapter and replays the
configured asset for terminal equality. PubMed adds an attempt-scoped terminal
receipt and production composition builds the service from exact concrete
snapshot/repository authorities. DailyMed/FAERS replay durable operation
provenance. The common `validate_terminal_task` port is required before every
post-collection trusted, effecting, inspection, and terminal-return path.

Round 6 also replays every existing terminal prefix before the
`collect_evidence` source loop can plan or execute the next source. Critical
dispatcher/service/source authorities are frozen and class-qualified. PubMed
acquisition and private immutable DailyMed/FAERS snapshot replay stores are
constructed internally; live provenance cannot replace replay authority.

Round 7 extends replay to every LangGraph active/terminal trusted result,
freezes and guards the concrete snapshot/acquisition/replay authorities, and
separates exact CADEC scope execution bounds from the top-20 result projection.

Round 8 binds report tasks to the canonical plan-selected subset of full scope,
preserves skipped rows without tasks/outcomes through export, and conditionally
composes exact source groups across all 15 nonempty source subsets.

Round 9 replays the exact full source plan before every trusted boundary and
binds its ordered row/status/reason content into canonical report and receipt
identity. Workflow/planner dependencies are final, slotted, and frozen.

Final Round 10 replaces mutable planning Protocol authority with exact
`CanonicalSourcePlanningAuthority`, bound to strict scope and full canonical
plan, final/slotted/no-dict/immutable, exact-typed by workflow, and invoked
class-qualified for initial and replay paths.

## Graph nodes and results

| Node | Dependency | Authorized ownership/output | Result |
|---|---|---|---|
| D0 preflight/discovery | merged M3-005 baseline | Read-only branch, baseline, source-policy, asset, test, and path mapping | PASS; clean discovery started at exact baseline |
| D1 planning authority | D0 | Exact canonical planner, workflow typing, shadow/Protocol negatives | PASS after R10 |
| D2 report validation | D1 | Prior full-plan/report/receipt identity binding | PRESERVED |
| D3 runtime/evaluation | D1 | Harness, LangGraph, and M3-003 canonical planner migration | PASS after R10 |
| D4 coordinated attack | D1 | Selected-to-skip mutation reaches zero effects | PASS after R10 |
| D5 governance/evidence | D1-D4 | ADR-018, governing docs, traceability, this delivery record | COMPLETE locally for final Round 10; final fresh review pending |
| J1 integrated validation | D1-D5 implementation bytes | Full offline, static, validator/aggregate compactness | Fresh Round 10 full/static PASS; documentation-inclusive rerun after final review remains required |
| R1 remediation | initial validation | Evaluator interface, CADEC layering, FAERS legacy execution/persistence | CLOSED without semantic expansion |
| R2 remediation | compactness regression | Minimal compaction of the canonical validator integration surface | CLOSED at `1794/1800` |
| J2 initial independent review | frozen pre-R3 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 4 / P2 0` |
| R3 remediation | four initial P1 findings | Exact operation subjects, aggregate/child provenance, CADEC reconstruction/degradation, concrete DailyMed/FAERS authorities | CLOSED locally; fresh review required |
| J2b fresh Round 3 review | frozen Round 3 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 3 / P2 0` |
| R4 remediation | three Round 3 P1 findings | Durable stage progress/reload, typed v3 authority, canonical terminal outcome, final CADEC composition | CLOSED locally; fresh review required |
| J2c fresh Round 4 review | frozen Round 4 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 3 / P2 0` |
| R5 remediation | three Round 4 P1 findings | Frozen CADEC rerun, PubMed terminal receipt/concrete composition, durable source replay before trust | CLOSED locally; fresh review required |
| J2d fresh Round 5 review | frozen Round 5 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 2 / P2 0` |
| R6 remediation | two Round 5 P1 findings | Replay before next source; frozen internally composed replay authorities | CLOSED locally; fresh review required |
| J2e fresh Round 6 review | frozen Round 6 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 3 / P2 0` |
| R7 remediation | three Round 6 P1 findings | Active inspect replay, frozen underlying stores/adapters, exact CADEC scope bounds | CLOSED locally; fresh review required |
| J2f fresh Round 7 review | frozen Round 7 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 2 / P2 0` |
| R8 remediation | two Round 7 P1 findings | Plan-selected validator and conditional exact source composition | CLOSED locally; fresh review required |
| J2g fresh Round 8 review | frozen Round 8 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 1 / P2 0` |
| R9 remediation | sole Round 8 P1 finding | Exact full-plan replay and report/receipt identity binding | CLOSED locally; fresh review required |
| J2h fresh Round 9 review | frozen Round 9 candidate | Actual diff and authoritative-path reachability | Immutable `FAIL — P0 0 / P1 1 / P2 0` |
| R10 final remediation | sole Round 9 P1 finding | Exact immutable canonical planning authority and coordinated-attack closure | CLOSED locally; budget exhausted |
| J2i final fresh Round 10 review | frozen Round 10 candidate | Actual diff, exact-type/class-qualified planner reachability, all historical regressions | Immutable `PASS — P0 0 / P1 0 / P2 0`; no findings |
| J3 exact-byte rebind/audit | J2i PASS | Hash/scope/secret/dependency evidence and terminal auditor | PENDING |

## Validation evidence to date

- Initial full run: `6 failed, 2579 passed, 55 errors`.
- R1 minimal failing set: `3 passed`.
- M3-003 evaluation compatibility: `89 passed`.
- Legacy D2 source contracts: `103 passed`.
- R1 CADEC layering/exact-asset focus: `313 passed`.
- R2 compactness: `1794/1800`; focused `314 passed`.
- Exact approved CADEC asset: `20 passed`, proving 1,250 canonical, 1,248
  admitted, two excluded, two zero-length, 1,246 scored, and top-20 projection.
- Fresh integrated focus after R2: `589 passed in 10.09s`.
- Full socket-disabled unit/contract suite: `2643 passed, 2 warnings`, `82%`
  coverage, `86.29s`.
- Ruff: PASS.
- Format check: PASS, 172 files.
- Strict MyPy: PASS, 67 source files.
- Offline lock: PASS, 108 package entries.
- Diff check: PASS.

The initial independent review is immutable:
`FAIL — P0 0 / P1 4 / P2 0`. It found:

1. CADEC fake exact-asset/no-match admission plus degraded refs and incomplete
   reconstruction;
2. required operations omitted exact PubMed PMID and DailyMed selected-label
   subjects;
3. terminal aggregate identity could mismatch child provenance; and
4. no concrete production DailyMed/FAERS projection authority was reachable.

Round 3 closes those findings with required-operation v2 `input_identity`;
terminal-ref v2 aggregate identity plus every ordered child acquisition and an
exact representative child; recomputed task/collection v2 aggregation, exact
limitations, and degraded CADEC zero refs; complete field-for-field CADEC
verification/result reconstruction; exact PubMed/DailyMed/FAERS/CADEC subjects;
sealed concrete DailyMed/FAERS authorities required by exact type; and
workflow/M3-003 evaluation v2 compatibility.

Round 3 node-local handoffs report combined focused `341 passed`, workflow/
authority `340 passed`, and exact-asset PASS. Their literal commands were not
retained and are not terminal evidence. The fresh authoritative full command:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

returned `2662 passed, 2 warnings`, `82%`, in `91.56s`. Static node-local Ruff,
format, MyPy, offline-lock, and diff checks passed. Their exact commands remain:

```text
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv lock --check --offline
git diff --check
```

The fresh Round 3 review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It found:

1. an asset-free fake CADEC route;
2. dynamic PubMed/DailyMed suffixes not durably checkpointed before fetch; and
3. self-consistent terminal query/count/intent/operation forgery.

Round 4 closes those findings with v3 typed input refs, scope and acquisition-
intent binding, RUNNING progress prefixes, immutable PubMed membership journal
reload, durable DailyMed discovery reload, one operation stage per workflow
checkpoint, canonical reconstruction of every terminal outcome field, and the
sole final infrastructure-owned CADEC composition route. Exact CADEC asset and
membership inputs are passed to the internal concrete adapter; the structural
three-source dispatcher has no CADEC port.

The fresh authoritative Round 4 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2685 passed, 2 warnings`, `82%`, in `103.16s`. Ruff, format (`173`
files), strict MyPy (`67` source files), offline lock (`108` entries), and diff
passed. Compactness is exactly `1800/1800`. Static commands are the same exact
commands recorded above.

The fresh Round 4 review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It found:

1. writable CADEC `_search` authority;
2. self-consistent durable child forgery without source-specific replay; and
3. coordinated PubMed progress-journal and checkpoint substitution.

Round 5 freezes the CADEC wrapper/internal adapter and reruns concrete assets;
adds a PubMed terminal progress receipt and concrete `SnapshotStore`/
repository composition with no prebuilt service; reloads DailyMed discovery/
fetch and FAERS aggregate provenance; and requires
`EvidenceCollectionPort.validate_terminal_task` before all post-collection
trusted, effect, inspection, and terminal-return paths. M3-003 is replay-
compatible.

The fresh authoritative Round 5 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2705 passed, 2 warnings`, `82%`, in `112.81s`. Static node checks
passed and compactness is `1791/1800`.

The fresh Round 5 review is immutable:
`FAIL — P0 0 / P1 2 / P2 0`. It found:

1. a terminal source prefix was not replayed before next-source work; and
2. non-CADEC replay authorities were caller-supplied or replaceable.

Round 6 replays all existing terminal tasks before the `collect_evidence` loop
or next-source effects. It freezes and class-qualifies the dispatcher, PubMed
service, DailyMed/FAERS authorities, and CADEC wrapper/adapter. Production
composition internally constructs PubMed acquisition plus immutable
DailyMed/FAERS snapshot replay stores, keeping live provenance separate and
preventing caller replay injection. Every later replay entry remains intact.

The fresh authoritative Round 6 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2723 passed, 2 warnings`, `82%`, in `81.52s`. Static node checks
passed and compactness is `1792/1800`.

The fresh Round 6 review is immutable:
`FAIL — P0 0 / P1 3 / P2 0`. It found:

1. active inspection omitted terminal-source replay;
2. coordinated forgery remained through replaceable stores/adapters; and
3. CADEC used top-20 as `max_records=20` instead of exact scope 100.

Round 7 invokes `validate_terminal_sources` before every LangGraph active or
terminal trusted result; makes `SnapshotStore` final/slotted/read-only/guarded
and freezes class-qualified acquisition, replay, and CADEC authorities; and
uses exact `ExecutionBounds.from_scope` for CADEC success/failure while keeping
20 solely as positive-result projection.

The fresh authoritative Round 7 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2727 passed, 2 warnings`, `82%`, in `81.39s`. Static node checks
passed and compactness is `1799/1800`.

The fresh Round 7 review is immutable:
`FAIL — P0 0 / P1 2 / P2 0`. It found:

1. validator task equality used full scope and blocked a valid skipped run; and
2. composition unconditionally constructed DailyMed/FAERS, rejecting
   PubMed-only.

Round 8 adds canonical `selected_task_sources` derived from selected plan rows,
preserves skipped rows without tasks/outcomes through export, and conditionally
constructs exact complete dependency groups for all 15 nonempty source subsets.
CADEC-only uses no snapshot store; network sources share one store iff present.

The fresh authoritative Round 8 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2757 passed, 2 warnings`, `82%`, in `81.95s`. Static node checks
passed, validator size is `1291/1300`, and compactness is `1800/1800`.

The fresh Round 8 review is immutable:
`FAIL — P0 0 / P1 1 / P2 0`. It found that checkpoint bytes could
self-authenticate the full source plan, allowing selected-to-skip task removal
or post-receipt skip-reason drift to export.

Round 9 replays the frozen planner and compares every ordered full-plan row,
including status and reason code/text, before collection, source effects,
post-collection effects, inspection, and trusted/terminal returns. Strict
`source_plan_id` binds canonical report request and validation receipt. The
workflow and planner dependencies are final/slotted/frozen. Both coordinated
attacks produce zero effects.

The fresh authoritative Round 9 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2764 passed, 2 warnings`, `82%`, in `82.51s`. Static node checks
passed, validator size is `1292/1300`, and compactness is `1800/1800`.

The fresh Round 9 review is immutable:
`FAIL — P0 0 / P1 1 / P2 0`. It found that mutable injected
`SourcePlanningPort` method shadowing could authorize selected-to-skip export.

Final Round 10 adds exact `CanonicalSourcePlanningAuthority`: final, slotted,
no-dict, immutable, strict-scope/full-plan bound, exact-typed at workflow
construction, and called class-qualified for initial planning and replay.
Mutable Protocols, subclasses, foreign scopes, field replacement, and instance
shadows reject. Harness/runtime/M3-003 use the same authority; the coordinated
attack produces zero effects.

The fresh authoritative final Round 10 full command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

It returned `2766 passed, 2 warnings`, `82%`, in `82.54s`. Static node checks
passed, validator size is `1292/1300`, and compactness is `1800/1800`.

Fresh final Round 10 independent review returned
`PASS — P0 0 / P1 0 / P2 0` with no findings. Direct reviewer evidence:

- planner attacks: `5/5` passed;
- workflow/runtime/composition: `264` passed;
- projection/replay: `89` passed;
- authority/subsets: `17` passed;
- Ruff, format, and strict MyPy: PASS;
- scope `43` and non-self manifest `42`: exact match; and
- validator `1292/1300` and compactness `1800/1800`: PASS.

All prior immutable FAIL records remain unchanged. This review advances the
candidate only to `AWAITING_TERMINAL_AUDIT`.

Exact commands for the fresh post-R2 evidence were:

```text
uv run --locked --no-sync pytest tests/unit/orchestration tests/unit/tools/test_cadec_runtime.py tests/unit/tools/test_research.py tests/unit/tools/test_dailymed.py tests/unit/tools/test_faers.py tests/unit/infrastructure/test_cadec_local_search.py tests/unit/evaluation/test_m3_003_development_safety.py tests/unit/test_dependency_boundaries.py tests/contract/tools/test_faers_tools.py --disable-socket -q
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync mypy src
uv lock --check --offline
git diff --check
```

No exact-byte rebind, terminal audit, overall PASS, secret scan, dependency
audit, or post-review scope audit is claimed for the documentation-inclusive
bytes recorded here; those gates must be fresh after this file freezes. No
further remediation round is authorized.

## Exact derived allowlist

The independently derived scope contains exactly 43 candidate paths. The first 34
are implementation/tests and the final nine are governance/evidence:

```text
evaluation/m3_003_development_safety.py
src/medevidence/composition.py
src/medevidence/connectors/cadec/loader.py
src/medevidence/ingestion/snapshots.py
src/medevidence/infrastructure/cadec_local_search.py
src/medevidence/orchestration/contracts.py
src/medevidence/orchestration/dailymed_faers_capability.py
src/medevidence/orchestration/langgraph_runtime.py
src/medevidence/orchestration/ports.py
src/medevidence/orchestration/pubmed_capability.py
src/medevidence/orchestration/source_capabilities.py
src/medevidence/orchestration/source_task_projection.py
src/medevidence/orchestration/workflow.py
src/medevidence/tools/cadec_runtime.py
src/medevidence/tools/dailymed.py
src/medevidence/tools/faers.py
src/medevidence/tools/ports.py
src/medevidence/tools/report_validation.py
src/medevidence/tools/research.py
tests/unit/ingestion/test_snapshots.py
tests/unit/infrastructure/test_cadec_local_search.py
tests/unit/orchestration/test_contracts.py
tests/unit/orchestration/test_dailymed_faers_capability.py
tests/unit/orchestration/test_langgraph_runtime.py
tests/unit/orchestration/test_pubmed_capability.py
tests/unit/orchestration/test_source_capabilities.py
tests/unit/orchestration/test_source_task_projection.py
tests/unit/orchestration/test_workflow.py
tests/unit/test_source_capability_composition.py
tests/unit/tools/test_cadec_runtime.py
tests/unit/tools/test_dailymed.py
tests/unit/tools/test_faers.py
tests/unit/tools/test_report_validation.py
tests/unit/tools/test_research.py
docs/ARCHITECTURE.md
docs/DATA_SOURCES.md
docs/EVALUATION_PLAN.md
docs/PRD.md
docs/SECURITY.md
docs/TRACEABILITY_MATRIX.md
docs/decisions/ADR-018-m3-source-capability-adapters.md
docs/decisions/README.md
.delivery/M3-006-SOURCE-CAPABILITY-ADAPTERS.md
```

## Current SHA-256 manifest

These hashes were independently recomputed from the 42 frozen post-review candidate
paths after the other eight governance paths froze. The delivery file's own
hash must be computed externally after it freezes to avoid self-binding.
The exact 42-line manifest below, encoded as UTF-8 with LF separators and a
trailing LF, is 4,465 bytes with SHA-256
`f1e06283aeff81e6dfc0af0cf038f4a06aada330c4c5dddf69e72cd56e93aea6`.

```text
224e55ffe2d61bb2b97a97dc6b0d2763190bac6a5f65b2b94d29707effe125c0  evaluation/m3_003_development_safety.py
bd88200626b0d9a55a07e2a6c203c452ff2a554c06eef31258e4462eabfec675  src/medevidence/composition.py
b4b080d5d7a78cd8fe410371085bf630feb6401686699782d8cad56d7dbc1065  src/medevidence/connectors/cadec/loader.py
8317dafeae123523ab6ea425b36f411b2dae58177f4af59c04756ea69f17a74c  src/medevidence/ingestion/snapshots.py
afd522ae03063adc9af7bc05a0e6434e3142a6cfe331ff7da0574e6b635b9146  src/medevidence/infrastructure/cadec_local_search.py
5a9a521d1fddf386bd79401567b5145ffa716760db5da51be822f9525e3a2a85  src/medevidence/orchestration/contracts.py
330c8482fdfd007d101e80e6cf8bc7d98860decfed07c8345d9e6aa46bc4f771  src/medevidence/orchestration/dailymed_faers_capability.py
1582677d74b48385abfdd45509b0e0e0c85b3bed9273978a3b129ed78e01b9d9  src/medevidence/orchestration/langgraph_runtime.py
c7a789ff281f237249ccbba9e833c3b939e5e72163dcc63d67c83fa78088c257  src/medevidence/orchestration/ports.py
46d7576769b33226df41d48ac3119d38370d73948776febf56ba308c6ab5b8cc  src/medevidence/orchestration/pubmed_capability.py
bc104241f023e8395e39a2a85fc1dc4ef291bbfd7ca79f7152ba05dc35e83f7e  src/medevidence/orchestration/source_capabilities.py
2678bcdd4578596ab701d0b8fb1c8870c88bad8974df1fb8f93074d87acd01eb  src/medevidence/orchestration/source_task_projection.py
3b8cbb362c72e79d5b690b2e50f7886406d0894b4fbd831e58635043af3635e7  src/medevidence/orchestration/workflow.py
34e0e2660a8da8c28fb8a82a72e65daac982c1b2d8bd8fdcb73ce71fceed23a3  src/medevidence/tools/cadec_runtime.py
d38e03ea34192bee0c3adb09cf3c78fd844b7322c28a0ebe2c6feacb97af5c69  src/medevidence/tools/dailymed.py
fcb4b998ab9df8ce263aa13f5991576f3df09e414372cb718c414a8a25f143c2  src/medevidence/tools/faers.py
911e55122dd86cf294eeb2bab214e08b0d0719fbb3a0744a8db58868906679c4  src/medevidence/tools/ports.py
9c6a4e88e34c1d1d18cc9654d9eceb45d00c6502ce39b7ea9cd79122c0c6af86  src/medevidence/tools/report_validation.py
455f933811d829130af29db8b2e944cc0bbc06f91e857e97ea436185ed101b5b  src/medevidence/tools/research.py
121295641bbec3b095e3a6fda3cc60525c1253abd80f76bf123ee7a8f8de9b2e  tests/unit/infrastructure/test_cadec_local_search.py
9317ee94985d9355bb25e13b7040a634abac2f59c859cf90e6798cb48b99c17b  tests/unit/ingestion/test_snapshots.py
ebb21748ba2ec408bae68e90feec952347a36540680d6cc96a280c200c3910fe  tests/unit/orchestration/test_contracts.py
0ea56769e56216decb4c1e6fdb2f4bbd7c3a248cdeb5a59ec5df2dd37490fef4  tests/unit/orchestration/test_dailymed_faers_capability.py
c27dba2d36699f0d2ad79fdb5f521a060574d18639845e18cbe69f2c114dfa35  tests/unit/orchestration/test_langgraph_runtime.py
efb9485d994b5bbd009b43e82ad8828182432e33da3ca2355725bb5e8e46c97d  tests/unit/orchestration/test_pubmed_capability.py
4ab317df17f6905328690dfc24b3833e5f20489047de0e87d926460cb815dc79  tests/unit/orchestration/test_source_capabilities.py
f03061a20a40cf290e18f2b98b4ae63e613d9e9690759a2b78d4f3a5813e6751  tests/unit/orchestration/test_source_task_projection.py
532b5904b95b2e3c66e0caa27fe25d945c0335a9a1353f704bd247abcf549a6f  tests/unit/orchestration/test_workflow.py
185f8369766dc1ab40fe90528aab1bef36ab46b0d72bd3b1bccf43548dfb41a9  tests/unit/test_source_capability_composition.py
f31ae9a9a6e6959e68d25cd92303b5f8f5f1cba390b54a812997b097d42bf7c4  tests/unit/tools/test_cadec_runtime.py
1ce50dcbdd77fa531a5092bf508fc1e9abdfbf36da906d2f94e3dea5f32dc889  tests/unit/tools/test_dailymed.py
2e6ad13def7e15fd1a637c3c33c5c6fff13acde133c113e119ccf5b4eb5a8609  tests/unit/tools/test_faers.py
b586e7e61c0c8f802728ee4d831d76ee0c9364d651ac91f20765e2966787d539  tests/unit/tools/test_report_validation.py
3eab3078ab0c691d91684395955694934cfe1a5046eaada612d7b01ce6c54caa  tests/unit/tools/test_research.py
75071b1d18f17c641b95ae28017b8e385054697ab7fe6428d137b13e2434d4e4  docs/ARCHITECTURE.md
1d0312b1bbaa70bfb16260e8c289c050dbbe5c93d091c43e677dfdb844078ca1  docs/DATA_SOURCES.md
225e2baac96b48082bd660fd2655abe8bf3130798335255f83e90d9ee626ee08  docs/EVALUATION_PLAN.md
fa2ff2d7dc6ea749913da85baa5af93befa54e2eaaec300b4f3b4d01dfcd8182  docs/PRD.md
9d7d4d1aa8966b25e36fd77e115833addef94f05537987512624738e16d0c873  docs/SECURITY.md
e2861e0325d6f278663635729ac9d0ab01970a33d58b662dd5f55af7c7fd50ab  docs/TRACEABILITY_MATRIX.md
0e328f2f5a5fb17769c994f8cf2f4f01ac494a4fdb6a96498afd2afef7e102bc  docs/decisions/ADR-018-m3-source-capability-adapters.md
dbcd558b10107b122af7fc80fc16165fa068fcf2af20ee74e8704d899c13b398  docs/decisions/README.md
```

## Network and Git

- Medical-source traffic: none.
- Model/provider execution or download: none.
- Holdout-20: not accessed.
- Dependency change/download: none for M3-006.
- Git operations in this node: none; no stage, commit, push, PR, or merge.

## Remaining gates and risk

Final independent review has passed with no findings. Terminal audit must now
verify the documentation-inclusive exact bytes, all R1-R10 history and closure
evidence, focused/full/static/lock/scope/diff/secret/dependency gates, network
absence, and final candidate identity. Until exact-byte rebind and terminal
audit pass, the candidate is not integrable.

Manual audit should recompute the 42-path non-self manifest, external delivery
hash, 43-path scope, and final reviewer commands against unchanged bytes.

The Owner should be able to answer:

1. Why is a structural planning Protocol insufficient authority?
2. How does exact planner construction bind scope and full plan?
3. Why are both initial planning and replay class-qualified?
