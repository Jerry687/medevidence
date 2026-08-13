# M2 retrieval evaluation

This harness compares BM25, classical latent-semantic dense retrieval, and
RRF(BM25, LSI) over a frozen corpus while retaining recomputable per-query
evidence.

The M2 pilot exception is experiment-only. Classical LSI is not a transformer
embedding, and no backend here is Qdrant. `ME-000C` remains open for release
indexes, Qdrant, transformer dense retrieval, rerankers, and later retrieval
architecture.

## Environment and execution

Bootstrap installs both the development and dedicated retrieval/evaluation
dependency groups. NumPy and scikit-learn remain outside the production
default dependency surface.

Fixture smoke run:

```powershell
uv run --locked --no-sync python -m evaluation.run_evaluation `
  --jsonl tests/fixtures/retrieval/harness_smoke.json
```

Final NFCorpus evidence uses a deterministic tracked run directory while the
archive and extracted dataset remain outside Git:

```powershell
uv run --locked --no-sync python -m evaluation.run_evaluation `
  --beir "<local-extracted-nfcorpus>" `
  --split test `
  --dataset-name NFCorpus `
  --dataset-source "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip" `
  --distribution-archive "<local-nfcorpus.zip>" `
  --output evaluation/results `
  --run-id nfcorpus-real-thread1-final `
  --dimensions 256 `
  --rrf-k 60 `
  --bm25-k1 0.9 `
  --bm25-b 0.4 `
  --candidate-limit 100 `
  --final-limit 10 `
  --grade-min 1 `
  --random-seed 0 `
  --query-concurrency 1 `
  --blas-threads 1 `
  --modes sparse,dense,hybrid_rrf
```

## Artifact contract

Ordinary generated runs remain ignored. The historical diagnostic evidence at
`evaluation/results/nfcorpus-real-final/` remains trackable; the authoritative
candidate is `evaluation/results/nfcorpus-real-thread1-final/`.

Each final run contains:

- `manifest.json` and its external `manifest.sha256` sidecar;
- `source.patch`, `source-state.json`, and the byte-exact untracked-source
  snapshot;
- one `per-query-<mode>.jsonl` file for each executed mode.

Every per-query record contains the full returned candidate pool (up to 100),
final top ten, component scores and ranks, latency, and metrics. Before writing,
the harness rejects missing or duplicate query records, incomplete candidate
evidence, non-recomputable metrics or summaries, and non-reconstructible RRF.

## Final NFCorpus run

Status: **`M2_001_REAL_BENCHMARK_COMPLETE`; `READY_FOR_M2_TRANSFORMER_BASELINE`**

Run directory: `evaluation/results/nfcorpus-real-thread1-final`

- `manifest.json`: 19,030 bytes; SHA-256
  `a9ef3cdeaf42c54921ae07c6b8fc9f872381132aad43926e33f8ba377d583356`
- `manifest.sha256`: 80 bytes; SHA-256
  `0747afb3007f5aa1ecf2f3f1bab558daa6c3f48760a342fc5359c08ae3059a80`
- `per-query-dense.jsonl`: 2,752,034 bytes; SHA-256
  `73fa318fac69123a0afdad6b1565ab77da4306830c29b9d1293f70303a261cc4`
- `per-query-hybrid_rrf.jsonl`: 3,852,273 bytes; SHA-256
  `2d867c9317f585418554000a72fc2b3b81a5f0b71410b7d94736c54e703973a5`
- `per-query-sparse.jsonl`: 1,899,202 bytes; SHA-256
  `fa7891b2c4f96cddbd6e3b9a9741fc8f69e63f03d952a28ad8dd6f36852a07d0`
- `source.patch`: 133,064 bytes; SHA-256
  `2604ad49876d5662c23dd582243a87b60d12d41045e947ba3731675141d8f754`
- `source-state.json`: 2,886 bytes; SHA-256
  `52a70e6aaf1fbc3eb1a6d3bea9f23cebabb84719bf0bc941ceda137349401b3d`
- `source-untracked-snapshot.json`: 11,488,052 bytes; SHA-256
  `fdead70a75a990f9d1dfe76f8f0e24275df0e5b1479b55f5a9b5013fdedc7333`
- NFCorpus archive: 2,448,432 bytes; SHA-256
  `efe5be03f8c5b86a5870102d0599d227c8c6e2484328e68c6522560385671b0b`
- Corpus identity:
  `sha256:511592c84193977f19027bcf1ab00d3ed1bb7857c744060327391e2fc9d3f66c`
- Dataset counts: 3,633 documents, 3,237 queries, 323 judged/evaluated
  test queries, and 12,334 judgments.

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | Build/index seconds |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.7745055727721116 | 0.23778780000066035 measured |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 16.409001857574022 | 2.148871199999121 measured |
| RRF(BM25, LSI) | 0.1662154048534712 | 0.31808525498497503 | 0.49357093714678857 | 17.64883498449744 | 2.3866589999997814 derived sum |

The hybrid build value is derived from measured sparse and dense builds. Query
execution was serial with concurrency one. The manifest records all five native
thread environment variables as `1`, pre-limit native-stack discovery, and one
thread for every BLAS/OpenMP pool at entry and exit of index build and every
selected query-latency context. OS scheduling, filesystem cache, and unrelated
host load were uncontrolled, so latency remains local wall-clock evidence, not
a production SLO.

Review001 remains historical **FAIL — P0 0 / P1 4 / P2 3**. The one authorized
remediation cycle is consumed (`1/1`) and closed all seven findings. Fresh
validation passed: 132 focused tests and 1,650 full offline tests,
plus Ruff, formatting, strict MyPy, lock, PowerShell parsing, and diff checks.

Terminal Audit001 remains historical **FAIL — P0 0 / P1 1 / P2 0**; the prior
24-thread run is diagnostic only. Review002 passed with
**P0 0 / P1 0 / P2 0** against HEAD
`ab15c55fbf9cee897a961905944ffee232a03372`, source-state
`fb87bea9a8cd271a58b1d790a455cc241973d0c0178f5b924bbcadd3c97fa884`,
and the artifact identities above. No separate candidate path-manifest was
supplied or claimed.

Terminal Audit002 passed with **P0 0 / P1 0 / P2 0** on the exact 33-path
pre-persistence candidate. Its 3,854-byte canonical path manifest had SHA-256
`8f5a8b355e0681c1782b26aa3d881d687f8f88db4753f7722bd13f448564bb6b`.
This establishes `M2_001_REAL_BENCHMARK_COMPLETE` and
`READY_FOR_M2_TRANSFORMER_BASELINE` for this experiment-only baseline.

No commit was authorized or performed. `ME-000C` remains open for release
indexes, Qdrant, transformer dense retrieval, rerankers, and later retrieval
architecture. No M3 work was authorized or started.

## Metric definitions

The harness uses standard TREC/BEIR conventions:

- `DCG@k = sum((2^rel_i - 1) / log2(i + 1))` for 1-based rank `i`;
- `nDCG@k = DCG@k / IDCG@k`, or `0.0` with no positive judgment;
- `Recall@k` divides retrieved relevant documents by all judged-relevant
  documents;
- `MRR@k` is the reciprocal rank of the first relevant result, or `0.0` when
  no relevant result appears by `k`.

`--grade-min` controls the binary relevance threshold. The final NFCorpus run
used `1`.

## Limitations

- Dense retrieval is TF-IDF plus truncated SVD (classical LSI), not a
  transformer embedding.
- No reranker baseline is implemented.
- NFCorpus is an external retrieval benchmark, not the MedEvidence
  Development-40 or Holdout-20 evaluation set.
- No production threshold or release configuration is established.
- Benchmark metrics do not support clinical, causal, incidence, regulatory,
  comparative product-risk, ranking, or advice conclusions.
