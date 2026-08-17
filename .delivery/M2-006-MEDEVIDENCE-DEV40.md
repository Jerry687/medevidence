# M2-006 Dev-40 retrieval benchmark delivery record

Updated: `2026-08-17`

Status: **TERMINAL_AUDIT_PASS_AWAITING_GIT_INTEGRATION**

Branch: `codex/m2-006-dev40-benchmark`

Approved baseline: `6d7a06520e1749069e2fa22be5105588dfc0e09f`

## Frozen scope

This work item implements one offline Dev-40 benchmark with exactly:

- BM25 (`k1=0.9`, `b=0.4`);
- the existing exact local CPU MedCPT configuration; and
- RRF(BM25,MedCPT) (`k=60`).

There is no parameter tuning, reranker, corpus/question/qrels modification,
Holdout-20 access, medical-source request, or model download. Results are
descriptive development-set evidence only and cannot establish statistical
superiority.

## Authoritative external bindings

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Corpus manifest | 1,111,679 | `249e4157c142d9738af6d5b5c5a88d6515461416b10e8f7bf8b38226c1a93e4a` |
| Blinded packet | 13,408,759 | `b3ff81d2a76aa21a16cee40b9f530e345bd92830c478a4d9c1c66048a1720203` |
| Full qrels | 1,257,098 | `3d871bae8ffd2be46e2546da01d5e67c93b25d2450b8dc8a09a579c0a905777d` |
| Nonzero qrels | 245,738 | `0b69ecb73ef4ba592658a56373e1cdf46b785286d67345dd96f7bb601dc69393` |
| Owner-confirmed adjudication | 328,121 | `6bba185b62b9bcd172c7cf694a9012a55eb91d880aec35bef9ee52c37ae2559f` |
| Authoritative metric contract | 3,269 | `a8d2f92266ec1d12ca9889c80d19b9b1b10dd2ce5f2ef8d8851011740995d50b` |
| Owner-confirmed bundle manifest | 1,452 | `1269869d85821286dbadccdaaacdb5975ca18dbdf743782bf477a67628d623e0` |

The adapter also preserves the immutable freeze run plan, source
reconciliation, and historical source-state identities. The generic corpus
verifier now differs only because its historical source-state inventory binds
an older repository test file. Benchmark loading therefore independently
revalidates the exact canonical corpus/packet paths and bytes, schemas, text
hashes, all 4,922 question/document pairs, quoted multiline TSV, adjudication,
contract, bundle, and freeze evidence while binding current benchmark source
bytes separately. No historical evidence is changed.

## Metric and artifact contract

All 23 questions are retained for exact frozen-input, qrels, adjudication, and
source-state reconciliation. Retrieval execution is restricted to exactly the
ordered 20 ranking-evaluable questions. All three modes retain one 214-entry
deterministic ranking for each of those 20 questions, including final/component
ranks and scores, relevance grade, per-question timing, and six metric fields.

- nDCG@10, Recall@5, Recall@10, and MRR@10 use exactly 20 questions.
- DirectHit@10 and DirectMRR@10 use exactly 17 questions.
- Q2/Q16/Q18 retain broad metrics and have null direct metrics.
- Q26/Q28/Q29 exist only in manifest-level source-state metadata with exact
  authoritative reasons and explicit declarations that ranking, component
  scores/ranks, metrics, and query timing were not executed.

Persistence is atomic and append-only to the one absent external
`benchmark-001` path. The CLI sets offline and single-thread environment
controls before importing model code and rejects an existing output before any
input/model load. Save performs a fresh exact-byte rebind and source-state
check before writing the manifest and three per-question JSONL files.

## Independent Review001 remediation

Review001 returned **FAIL — P0 0 / P1 1 / P2 0** because the initial candidate
executed and timed Q26/Q28/Q29 despite excluding them from denominators. The
single P1 is mechanically remediated within the frozen contract: dataset
loading still reconciles all 23 questions, while runner iteration, mode
validation, JSONL persistence, per-question metrics, and timing summaries now
admit only the exact 20 ranking-evaluable IDs. Tests instrument both BM25 and
MedCPT calls and require zero source-state query execution. Remediation cycle:
`1/3`.

## Current implementation scope

- `evaluation/dev40_benchmark.py`
- `evaluation/run_dev40_benchmark.py`
- `tests/unit/evaluation/test_dev40_benchmark.py`
- `evaluation/README.md`
- `.delivery/M2-006-MEDEVIDENCE-DEV40.md`

No dependency, production interface, schema, retrieval core, corpus, qrels,
or external evidence file was modified.

## Validation and lifecycle status

Pre-Review001 node-local evidence:

- `uv run --locked --no-sync pytest tests/unit/evaluation/test_dev40_benchmark.py tests/unit/evaluation/test_dev40_corpus.py tests/unit/evaluation/test_medcpt.py --disable-socket`
  passed `43` tests in `7.32s`;
- Ruff check passed on the three owned Python paths;
- Ruff format check passed on the three owned Python paths; and
- MyPy with `--follow-imports=skip` passed the two owned evaluation modules.

The final focused rerun passed the same `43` tests in `7.23s`; Ruff check,
Ruff format check, owned-module MyPy, and `git diff --check` also passed. Two
pre-review formatting/type-narrowing cycles were used.

Fresh post-remediation evidence:

- the exact focused command above passed `44` tests in `7.11s`, including an
  instrumented zero-call assertion for all three source-state questions;
- Ruff check passed on the three owned Python paths;
- Ruff format check passed on the three owned Python paths;
- MyPy with `--follow-imports=skip` passed the two owned evaluation modules;
  and
- `git diff --check` passed.

Review remediation consumption is exactly `2/3`.

Direct MyPy traversal of the same two modules now reports only the existing
out-of-scope `evaluation/metrics.py:29` missing generic type arguments. The
owned implementation has no direct MyPy finding, and `evaluation/metrics.py`
was not authorized for modification.

Review002 confirmed the P1 closure and found one P2 wording defect: two durable
descriptions still said that mode results covered all 23 questions. Remediation
cycle `2/3` changed only those phrases to the exact 20 ordered
ranking-evaluable questions. Review003 then returned
**PASS — P0 0 / P1 0 / P2 0** after independently observing 20 records per
mode, 60 total mode calls, 40 MedCPT searches, and zero Q26/Q28/Q29 records or
searches.

## Full offline validation

Fresh post-remediation integrating-worktree evidence:

- `uv run --locked --no-sync ruff check .`: PASS;
- `uv run --locked --no-sync ruff format --check .`: `136 files already formatted`;
- `uv run --locked --no-sync mypy src`: PASS for `52` source files;
- `uv lock --check`: PASS with `87` packages;
- focused benchmark/corpus/MedCPT suite: `44 passed`;
- full socket-disabled unit/contract suite: `1,991 passed`, two expected
  warnings, `79%` coverage; and
- `git diff --check`: PASS.

The two warnings are the existing Starlette `httpx` deprecation warning and
the expected proof that `pytest-socket` blocked socket creation.

## Benchmark execution and measured results

The one offline benchmark execution completed at
`2026-08-17T05:51:44.160399+00:00`. Manifest identity:

- bytes: `93,871`;
- SHA-256: `0258c25d986bdb084ff6f87af87fac18a389cc1aceb1c57c509fe2ae4d29f14b`;
- run ID: `M2-006-MEDEVIDENCE-DEV40-BENCHMARK-001`; and
- declared medical-source operations, model downloads, and Holdout-20 access:
  `0`, `0`, and `false`.

| Mode | nDCG@10 | Recall@5 | Recall@10 | MRR@10 | DirectHit@10 | DirectMRR@10 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.2728773364817932 | 0.05179374535358309 | 0.11029123900304119 | 0.5504761904761905 | 0.9411764705882353 | 0.4681372549019608 |
| MedCPT | 0.39460224332658184 | 0.07205690841254493 | 0.13205498267061236 | 0.6849999999999999 | 0.8823529411764706 | 0.5166666666666666 |
| RRF(BM25,MedCPT) | 0.3207381556120896 | 0.07433862398787106 | 0.14135936514954725 | 0.6541666666666667 | 0.8823529411764706 | 0.3588235294117647 |

The first four metric denominators are exactly `20`; the two direct metric
denominators are exactly `17`.

| Mode | Build seconds | Query mean ms | Query P50 ms | Query P95 ms | Query total ms |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.01871249999385327 | 0.2518249995773658 | 0.2623000036692247 | 0.3287600004114211 | 5.036499991547316 |
| MedCPT | 181.21206410002196 | 53.03689500433393 | 49.19089999748394 | 67.3705500143115 | 1060.7379000866786 |
| RRF(BM25,MedCPT) | 181.23077660001582 derived component sum | 48.122474999399856 | 48.83184998470824 | 59.67472001211718 | 962.4494999879971 |

Timing is machine-local serial wall-clock evidence and is not a portable
production-performance claim.

External result artifacts:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `per-question-bm25.jsonl` | 782,935 | `1bbddef5ce209579a3186e320acdb04465bf0caece300949c768c42b112c951a` |
| `per-question-medcpt.jsonl` | 796,330 | `4638fa8815ec1242884007ae6029fc658bd43f7fb6162e285b7d56bd75c38cef` |
| `per-question-rrf-bm25-medcpt.jsonl` | 962,043 | `9b96c199ea18675682dd71fe8f30d8a5f2ae7b338ce39627309f776ae2c3b434` |

## Exact-byte rebind

After execution, all seven authoritative inputs matched their declared bytes
and SHA-256 values. The exact MedCPT acquisition manifest remained
`5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755`
and the 18-file cache aggregate remained
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`.
Every current benchmark source-state file and all three output artifacts
matched the bytes and SHA-256 values embedded in the manifest. The manifest
sidecar matched exactly.

These results are descriptive Development-40 evidence only. The table does not
establish statistical superiority. It does not support a release, clinical,
causal, incidence, comparative-safety, or Holdout-20 claim.

Network operations for implementation, validation, and benchmark execution:
`0` medical-source operations and `0` model downloads.

Git operations so far: branch creation only. No stage, commit, push, PR, merge,
rebase, reset, clean, or remote-state change has occurred.

## Terminal evidence audit

Terminal audit returned **PASS — P0 0 / P1 0 / P2 0** on the exact
uncommitted candidate. The independent read-only recomputation verified:

- `4,922` qrel pairs;
- `60` per-question mode records;
- `12,840` complete ranking entries;
- `360` per-question metric fields, including `18` intentionally null direct
  fields;
- all `4,280` RRF scores and orders;
- every aggregate metric, denominator, and timing summary;
- all seven authoritative inputs, three outputs, manifest/sidecar, current
  source state, historical freeze evidence, and the 18-file MedCPT cache; and
- zero Q26/Q28/Q29 JSONL records, with exact manifest-only source-state
  metadata.

The auditor independently reran Ruff, formatting, MyPy, lock, diff, and the
socket-disabled unit/contract suite: `1,991 passed` with the same two expected
warnings. Secret-pattern findings were zero. Audit activity performed no
repository or external-evidence file write, model load, network operation,
staging, commit, or remote Git mutation.
