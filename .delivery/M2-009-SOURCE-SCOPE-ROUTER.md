# M2-009 deterministic source-scope router delivery record

Updated: `2026-08-19`

Status: **M2-009_IMPLEMENTATION_COMPLETE**

Feature branch: `codex/m2-009-source-scope-router`

Approved baseline: `3199960f74a312fa23f1d99cfd8bf382bf7933df`

## Frozen behavior and architecture boundary

M2-009 implements the single M2-008-frozen deterministic pre-retrieval policy:

- PubMed-only source scope selects the source-neutral `dense` retrieval mode;
- DailyMed-only source scope selects the source-neutral `sparse` retrieval mode;
- PubMed plus DailyMed selects the existing `hybrid_rrf` retrieval mode; and
- every empty, malformed, duplicate, FAERS, CADEC, or otherwise unsupported
  scope fails closed with a typed reason.

The production selector accepts only `tuple[SourceType, ...]`. It has no
question-text, question-ID, qrels, relevance-grade, ranking, score, metric,
threshold, model, or mutable-configuration input. The evaluation adapter binds
`dense` to the accepted MedCPT configuration, `sparse` to BM25, and
`hybrid_rrf` to the existing RRF(BM25,MedCPT) implementation. Production wiring
beyond the retrieval boundary is intentionally outside this work item.

No alternate routing policy, parameter tuning, reranker, metadata retrieval
change, representation change, corpus/question/qrels/adjudication/metric-
contract change, or new dependency is introduced.

## Accepted planning and benchmark bindings

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| M2-006 benchmark manifest | 93,871 | `0258c25d986bdb084ff6f87af87fac18a389cc1aceb1c57c509fe2ae4d29f14b` |
| M2-008 routing contract | 16,570 | `d62556c1e1fa5ca7fbd304a2e4cbe87f7f4e455c5e7a2d388342a7ace714a596` |
| M2-008 routing validation | 2,575 | `ae142d861a434315ffde2155ca4f5d4ea5d5e034ce28e949854cec2160478e4b` |
| M2-008 replay manifest | 5,038 | `4a1c89b0682e3de3f1127afab1f1226406e1ab1ba2296b1dbba91455cbbd362d` |
| M2-008 routed records | 813,943 | `7aa751bdf6623a12183e2278c8624320b273b4070b88419d0674c34c72f5b6c8` |
| Owner exception closure | 6,557 | `1dec574bc36ab4aeb98d6ed4341b7ae2030e3c1f53d9ba88acb02aeef6c2782f` |

The Owner exception applies only to the historical read-only Git metadata
operation recorded by M2-008. It does not weaken M2-009 network governance.
No non-integrable M2-007 script, test, manifest, or sidecar is imported or
executed.

The routed run rebinds the unchanged Dev-40 inputs:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Corpus manifest | 1,111,679 | `249e4157c142d9738af6d5b5c5a88d6515461416b10e8f7bf8b38226c1a93e4a` |
| Blinded packet | 13,408,759 | `b3ff81d2a76aa21a16cee40b9f530e345bd92830c478a4d9c1c66048a1720203` |
| Full qrels | 1,257,098 | `3d871bae8ffd2be46e2546da01d5e67c93b25d2450b8dc8a09a579c0a905777d` |
| Nonzero qrels | 245,738 | `0b69ecb73ef4ba592658a56373e1cdf46b785286d67345dd96f7bb601dc69393` |
| Owner-confirmed adjudication | 328,121 | `6bba185b62b9bcd172c7cf694a9012a55eb91d880aec35bef9ee52c37ae2559f` |
| Authoritative metric contract | 3,269 | `a8d2f92266ec1d12ca9889c80d19b9b1b10dd2ce5f2ef8d8851011740995d50b` |
| Owner-confirmed bundle manifest | 1,452 | `1269869d85821286dbadccdaaacdb5975ca18dbdf743782bf477a67628d623e0` |

## One authorized offline routed execution

The single execution selected exactly 14 MedCPT, 5 BM25, and 1 existing RRF
ranking for the 20 retrieval-evaluable questions. Each persisted question has
all 214 deterministic ranks and selected-component provenance. Every selected
record equals the accepted M2-008 persisted component after excluding only the
fresh latency measurement.

Q26, Q28, and Q29 remain source-state behavior cases. They receive no selector
call, retrieval, ranking, component score/rank, metric, or query-timing record.

| Metric | Routed value | Denominator |
|---|---:|---:|
| nDCG@10 | `0.44642304480349304` | 20 |
| Recall@5 | `0.08614420999984652` | 20 |
| Recall@10 | `0.16614228425791394` | 20 |
| MRR@10 | `0.775` | 20 |
| DirectHit@10 | `1.0` | 17 |
| DirectMRR@10 | `0.5872549019607842` | 17 |

Q15 selects BM25 and preserves DirectHit@10/DirectMRR@10 `1.0/1.0`; the
accepted MedCPT and RRF values for Q15 are `0/0`.

These are descriptive Development-40 results only. They do not establish
statistical superiority, production generalization, release readiness,
clinical validity, or any Holdout-20 result.

### Timing evidence

The CPU-only MedCPT build took `184.9652999999962` seconds; BM25 build took
`0.019506500000716187` seconds. The routed query total was
`784.7360000087065` ms across 20 questions, with mean
`39.23680000043532` ms, P50 `41.285199997219024` ms, and P95
`66.03053499748061` ms. Timing is machine-local serial evidence and is not a
portable production-performance claim.

### Routed execution artifacts

External root:
`D:\Projects\medevidence-external-evidence\M2-009-SOURCE-SCOPE-ROUTER\routed-execution-001`

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 22,502 | `51d7efd8621a9bc1304456a203f6b9843825ae71ac8ab8f062dbd188199f416b` |
| `manifest.sha256` | 80 | `125863f4dd7f820ad40486f7e520f81fc367b705c116a09cb07229c404748c0f` |
| `routing-decisions.json` | 11,511 | `78f51154f647e356beb488ec487ece2f720fbddaa2362c222280df91f054e57b` |
| `per-question-routed.jsonl` | 808,822 | `3ed95a139079ad0f3998f9e23ebfb1938d0de0e6924095874a56f4f3cf090fb7` |
| `summary.json` | 1,721 | `f30e5339a55448f4412d59ae07fcdea518b4db01cc488516cb286403aa2b1d72` |

Persistence is atomic to one exact absent external path. The CLI rejects an
existing output before any corpus, qrels, routing, or model read; writes to a
pending sibling; rebinds source, dataset, routing, and model/cache identities;
and renames only the complete candidate.

## MedCPT identity and offline boundary

The execution used the existing local CPU-only MedCPT cache. Its acquisition
manifest is 94,242 bytes with SHA-256
`5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755`.
All 18 cache files total 877,783,608 bytes and have aggregate SHA-256
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`.

The CLI set Hugging Face/Transformers offline flags and single-thread native
runtime controls before model imports. Candidate implementation, validation,
and execution performed zero medical-source requests, zero model downloads,
zero package/advisory requests, and zero Holdout-20 accesses. The M2-009 run
made zero network operations.

## Repository changes

| Path | Bytes | SHA-256 |
|---|---:|---|
| `src/medevidence/retrieval/source_scope_routing.py` | 2,297 | `2f490c72f25a51292f89309a3d528735f872d29cd2da455e151bd68d4fc6518a` |
| `tests/unit/retrieval/test_source_scope_routing.py` | 3,441 | `d49dad8ddc93089ca2ca464a735cd61da5bae1d1f5baee3a63767a54eb498433` |
| `evaluation/dev40_source_scope_router.py` | 41,654 | `c9bf77f5ed45c4d5454b09b21d13def6f59cb5ff9ee5161a2fd147bde06a86f5` |
| `evaluation/run_dev40_source_scope_router.py` | 4,343 | `8ecce57dbc01e3d2400486d5bd3186d4b6ea0cfa41d7c05aee0c63cb6b76d746` |
| `tests/unit/evaluation/test_dev40_source_scope_router.py` | 22,383 | `523782d8e0dcee3d0fdc042a08b8bdb0db41dcf748eda875a9ab4284fc06887c` |

This delivery record is the sixth and final authorized repository path. No
production connector, API, tool, orchestration, persistence, schema, corpus,
qrels, adjudication, metric-contract, dependency, or lock file changes.

## Validation and independent review

- Focused router/evaluation suite: **31 passed**.
- Full socket-disabled unit/contract suite: **2,011 passed**, two expected
  warnings, `79%` coverage, in `53.33s`.
- Ruff check: **PASS**.
- Ruff format check: **141 files already formatted**.
- MyPy: **53 source files PASS**.
- Locked dependency check: **PASS**.
- `git diff --check`: **PASS**.
- Independent Review R1: **PASS — P0 0 / P1 0 / P2 0**, no findings.
- Independent qrels recomputation reproduced all six macro metrics and all
  20/17 denominators; exact Stage-A component comparison passed for all 4,280
  ranking entries.

The terminal audit is a separate external lifecycle gate and is not
self-attested by this delivery record. Repository commit/push/PR/merge occurs
only after that independent gate passes.

## Candidate Git state and operations

At the reviewed candidate snapshot, the branch is based exactly on
`3199960f74a312fa23f1d99cfd8bf382bf7933df`; the six authorized paths are
uncommitted and no path is staged. No amend, force-push, rebase, reset, clean,
history rewrite, or branch deletion occurred. The separate original workspace
contains an unrelated pre-existing `evaluation/metrics.py` annotation change;
M2-009 uses a clean isolated worktree and does not touch that change.

## Manual verification

1. Rehash the six repository paths and five external execution files against
   the tables above.
2. Run the focused router/evaluation tests with `--disable-socket`.
3. Recompute each routed question from the accepted M2-008 selected component,
   ignoring only fresh latency, then recompute the six macro metrics from the
   authoritative qrels.
4. Confirm Q26/Q28/Q29 are absent from per-question output and are manifest-only
   zero-execution cases.
5. Confirm the branch diff contains only the six authorized paths.

## Owner interview questions

1. Why does the production selector return source-neutral retrieval modes while
   the evaluation adapter separately binds `dense` to MedCPT?
2. How do the API shape and tests prove the router cannot use Dev-40 winner
   labels, qrels, ranking scores, question IDs, or question text?
3. Why do Q26/Q28/Q29 remain visible in evidence while receiving no selector or
   retrieval execution?
