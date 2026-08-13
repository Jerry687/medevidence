# M2-001 retrieval baseline harness delivery record

Updated: `2026-08-13`

Status: **`M2_001_REAL_BENCHMARK_COMPLETE`; `READY_FOR_M2_TRANSFORMER_BASELINE`**

Terminal Audit002 passed on the exact pre-persistence 33-path candidate.

Branch: `feat/m2-retrieval-eval-codex`

Execution revision: `ab15c55fbf9cee897a961905944ffee232a03372`

## Scope and semantic boundary

This M2 pilot evaluated three in-memory retrieval modes over the exact NFCorpus
test judgments:

- BM25 sparse retrieval;
- classical TF-IDF plus truncated-SVD LSI dense retrieval; and
- RRF(BM25, LSI).

Classical LSI is not a transformer embedding, and none of these pilot backends
is Qdrant. The experiment-only `ME-000C` exception applies only to this M2
benchmark. `ME-000C` remains open for release indexes, Qdrant, transformer
dense retrieval, rerankers, and later retrieval architecture.

## Authoritative candidate identity

Final run directory: `evaluation/results/nfcorpus-real-thread1-final`

Executed at: `2026-08-13T16:25:51.616043+00:00`

| File | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 19,030 | `a9ef3cdeaf42c54921ae07c6b8fc9f872381132aad43926e33f8ba377d583356` |
| `manifest.sha256` | 80 | `0747afb3007f5aa1ecf2f3f1bab558daa6c3f48760a342fc5359c08ae3059a80` |
| `per-query-dense.jsonl` | 2,752,034 | `73fa318fac69123a0afdad6b1565ab77da4306830c29b9d1293f70303a261cc4` |
| `per-query-hybrid_rrf.jsonl` | 3,852,273 | `2d867c9317f585418554000a72fc2b3b81a5f0b71410b7d94736c54e703973a5` |
| `per-query-sparse.jsonl` | 1,899,202 | `fa7891b2c4f96cddbd6e3b9a9741fc8f69e63f03d952a28ad8dd6f36852a07d0` |
| `source.patch` | 133,064 | `2604ad49876d5662c23dd582243a87b60d12d41045e947ba3731675141d8f754` |
| `source-state.json` | 2,886 | `52a70e6aaf1fbc3eb1a6d3bea9f23cebabb84719bf0bc941ceda137349401b3d` |
| `source-untracked-snapshot.json` | 11,488,052 | `fdead70a75a990f9d1dfe76f8f0e24275df0e5b1479b55f5a9b5013fdedc7333` |

The source-state identity is
`fb87bea9a8cd271a58b1d790a455cc241973d0c0178f5b924bbcadd3c97fa884`.
It binds the execution revision, tracked binary patch, changed-path inventory,
and exact untracked-file snapshot. The corpus content identity is
`sha256:511592c84193977f19027bcf1ab00d3ed1bb7857c744060327391e2fc9d3f66c`.

No separate candidate path-manifest was supplied or claimed by Review002.

## Dataset and distribution provenance

- Dataset: `NFCorpus`
- Distribution URL:
  `https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip`
- Archive: `nfcorpus.zip`
- Archive bytes: `2,448,432`
- Archive SHA-256:
  `efe5be03f8c5b86a5870102d0599d227c8c6e2484328e68c6522560385671b0b`
- Documents: `3,633`
- Dataset queries: `3,237`
- Judged/evaluated test queries: `323`
- Judgments: `12,334` (`11,758` grade 1; `576` grade 2)

| Consumed file | Bytes | SHA-256 |
|---|---:|---|
| `corpus.jsonl` | 6,219,364 | `10cc83ef1826b1425e6a87090b5140b39b27755d5a27e48215a88611c899991f` |
| `queries.jsonl` | 441,466 | `d024e6621b84925d485ae473d316a0c3af31c62c8068a59fb29d22f7613aef2a` |
| `qrels/test.tsv` | 279,572 | `f8fba6ef3d4dd9c3a242a8ba4ae38276fc3622fce7dcbae764766d564542fd2a` |

Dataset and archive bytes remain outside Git.

## Exact benchmark configuration

- BM25: `k1=0.9`, `b=0.4`
- Tokenizer: `unicode_lower_alnum_v1`
- Dense method: `tfidf_svd_v1`, requested and actual dimensions `256`
- RRF: `k=60`
- Candidate limit: `100`; final limit: `10`
- Relevant grade minimum: `1`
- Random seed: `0`
- Query execution: serial, single process, concurrency `1`
- BLAS threads requested inside guarded construction/search: `1`
- Python: `3.12.13`
- NumPy: `2.5.1`; scikit-learn: `1.9.0`; SciPy: `1.18.0`
- Platform: `Windows-11-10.0.26200-SP0`
- `uv.lock`: 108,274 bytes; SHA-256
  `26603561a612b39cb900d2472fe7933d1e600fefd78a54f767472c3f467d26f4`

`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`,
`BLIS_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` were each `1`. The native stack
was discovered before limiting. Every captured BLAS/OpenMP pool reported
`num_threads=1` at entry and exit for index build and all three query-latency
contexts. The observed libraries were two `libscipy_openblas` backends and the
`vcomp` OpenMP runtime. OS scheduling, filesystem cache, and unrelated host
load remained uncontrolled, so latency is local wall-clock evidence, not a
production SLO.

## Exact final results

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | P50 (ms) | P95 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.7745055727721116 | 0.2237999997305451 | 2.6660600004106514 |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 16.409001857574022 | 16.566000000239 | 17.160360000343644 |
| RRF(BM25, LSI) | 0.1662154048534712 | 0.31808525498497503 | 0.49357093714678857 | 17.64883498449744 | 17.206400001668953 | 20.56107999978849 |

Build/index timing:

- BM25: `0.23778780000066035` seconds, measured;
- classical LSI dense: `2.148871199999121` seconds, measured; and
- hybrid: `2.3866589999997814` seconds, derived as the sum of the measured
  sparse and dense builds, not a separately measured build.

These are benchmark measurements over NFCorpus relevance judgments. They are
not incidence, clinical, causal, regulatory, comparative product-risk,
production-readiness, or release-threshold claims.

## Review and remediation evidence

Independent Review001 remains immutable historical evidence:
**FAIL — P0 0 / P1 4 / P2 3**.

Terminal Audit001 remains immutable historical **FAIL — P0 0 / P1 1 / P2 0**.
The earlier `evaluation/results/nfcorpus-real-final/` 24-thread run remains
diagnostic evidence only.

The one Owner-authorized remediation cycle is consumed: `1/1`. It closed all
seven reviewed finding classes:

1. exact dirty execution-source binding;
2. retrieval-group bootstrap and CI installation;
3. a narrow tracked final-evidence path;
4. fail-closed qrel and evaluated-query validation;
5. exact retrieval dependency-boundary and audit evidence;
6. explicit concurrency/thread and measured-versus-derived timing semantics;
7. reconstructible full candidate/component rankings plus pre-save validation.

Fresh validation for the thread-1 candidate:

- focused retrieval/evaluation/dependency tests: `132 passed`;
- full offline unit/contract suite: `1,650 passed`, 2 warnings, 80% coverage;
- Ruff lint and formatting: PASS;
- strict MyPy over `src`: PASS;
- `uv lock --check`, PowerShell parsing, and `git diff --check`: PASS.

No tests were rerun during this evidence-only finalization.

Independent Review002 returned **PASS — P0 0 / P1 0 / P2 0** on the exact
candidate identities above. Artifact recomputation matched the manifest,
sidecar, all output artifacts, saved rankings, metrics, and timing semantics.

## Network and Git boundaries

The thread-1 rerun and this finalization reused the exact local NFCorpus archive;
they made no network request. No PubMed, NCBI, DailyMed, FAERS, or other
medical-source API was contacted. No transformer weights, model, Qdrant, or
reranker were downloaded or started.

No Git stage, commit, push, merge, rebase, reset, clean, or history rewrite was
performed by this finalization. No commit authority was granted.

## Terminal evidence decision

Terminal Audit002 returned **PASS — P0 0 / P1 0 / P2 0** on the 33-path
pre-persistence candidate. Its canonical path manifest was 3,854 bytes with
SHA-256
`8f5a8b355e0681c1782b26aa3d881d687f8f88db4753f7722bd13f448564bb6b`.
This establishes `M2_001_REAL_BENCHMARK_COMPLETE` and
`READY_FOR_M2_TRANSFORMER_BASELINE` for this experiment-only baseline.

No commit was authorized or performed. `ME-000C` remains open for release
indexes, Qdrant, transformer dense retrieval, rerankers, and later retrieval
architecture. No M3 work was authorized or started.
