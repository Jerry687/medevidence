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

## M2-002 historical pre-remediation run

The original external run at
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final`
is retained as historical evidence only. Its 33,260-byte manifest has SHA-256
`0473abe092ffc9e025338ef00bcdc599fadf98ef1aaf9d03384333ee23bfe7f1`.
Independent Review001 returned **FAIL — P0 0 / P1 1 / P2 1** because the
adapter self-trusted non-weight manifest identities and did not preserve
complete raw model-metadata acquisition lineage. Its metrics remain
recomputable historical observations, but it is not the authoritative
post-remediation candidate.

## M2-002 authoritative r1 candidate

Status: **`OWNER_DECISION_REQUIRED`**

External run directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r1`

| File | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 33,484 | `1bb0a54f77dfb44559975989750f643cb31db8265c6c8954cd746c9826ad4609` |
| `manifest.sha256` | 80 | `a5a7a5e7c69ef92e6b70000d7ac139e49ff95b8c4da65bc918f1791b91c15afc` |
| `per-query-dense.jsonl` | 2,752,065 | `9780897513a9a1a27565787e109693cf782afe30cbb574f71ce0607ff7b17103` |
| `per-query-hybrid_rrf_medcpt.jsonl` | 3,848,061 | `72a3adb3e6eec85fde77ce03cf336ac1a00dcd0a7f62d5b55a1a94589d7a8dcd` |
| `per-query-medcpt.jsonl` | 2,742,395 | `8921035b360b9c7ea388afeaa797e26bfc359f072feaf94d2622d01971c2adfe` |
| `per-query-sparse.jsonl` | 1,899,240 | `206c374f7d2fa7848de4436979eee12a324ccc9873ae575652b505dc8477c537` |
| `source.patch` | 141,007 | `c3b946b5b9a05fb3c06b210cf9a6b4642ba8e8b93f1e2f9b40d5af55328fb409` |
| `source-state.json` | 1,349 | `bfa07945a399c0acec2815f75484a2c99487e737e185f09e393fcec448bf3e1c` |
| `source-untracked-snapshot.json` | 87,664 | `db2c418dea85658cb6d317f755c19821518c603fbfcb46ad6c947fc1e5b5cf9f` |

The run binds HEAD `07c548737ec351c5a2a0669078f559700ac8b9b8`,
source-state identity
`a719bcd8e47d6538c7c187dac46cc79f002dea493fe285a9597191947e8c9862`,
and the exact patch and untracked snapshot above. It uses the successor
94,242-byte v1r1 acquisition manifest, SHA-256
`5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755`,
and the 56,755-byte r1 raw network ledger, SHA-256
`a7b66388278e29f88b1602faffb6a195d3f1bd96f1769a2187394bb6193c97e5`.
The model revisions, 18 cache files, and canonical aggregate
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`
are unchanged.

MedCPT ran on CPU in evaluation mode with one torch/native thread, query batch
size 1, document batch size 8, query maximum length 64, article-pair maximum
length 512, CLS pooling to 768 dimensions, no L2 normalization, and inner
product scoring. Query execution was serial with concurrency one. The frozen
NFCorpus identities and counts remain unchanged: 3,633 documents, 3,237
queries, 323 judged/evaluated queries, and 12,334 judgments.

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | P50 (ms) | P95 (ms) | Build/index seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.7037046440136719 | 0.19659999816212803 | 2.464779998990707 | 0.23272179999912623 measured |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 15.814452941480615 | 15.819200001715217 | 16.277499996795086 | 2.107056199994986 measured |
| MedCPT dense | 0.1827810170966193 | 0.3674126109143263 | 0.5487689812767212 | 29.08273126946938 | 26.992700004484504 | 36.29832999795326 | 2439.565887099998 measured |
| RRF(BM25, MedCPT) | 0.1810206378195796 | 0.3649385324032572 | 0.5698289842252691 | 29.242885449118933 | 27.341100001649465 | 38.752260000183014 | 2439.798608899997 derived sum |

The single Owner-authorized batched remediation hard-pinned all 18 artifact
and acquisition identities, recomputed the aggregate, rejected v1, and bound
the two authoritative metadata GETs plus the transparent failed probe to the
r1 ledger. Fresh gates recorded 17 focused tests, 111 broader evaluation
tests, 1,793 full offline tests with two expected warnings and 79% coverage,
Ruff and formatting, MyPy over 52 source files, `uv lock` over 87 packages, and
diff checks. Independent Review002 returned **PASS — P0 0 / P1 0 / P2 0**
against the exact 12-path pre-persistence candidate. Its ordinal
`path<TAB>bytes<TAB>lowercase-sha256<LF>` identity is 1,223 bytes with SHA-256
`28a7e7d7c881832fbda08e0299bfa2646e39b923a3d9f120f7bd4d90e64c1a26`.
Review002 independently rechecked the successor artifact/ledger/cache,
fail-closed mutations, all nine r1 artifacts, source reconstruction, all 1,292
per-query records, four summaries, 323 RRF rankings/candidate pools, ten thread
observations, dependency closure, M2-001 artifacts, and documentation claims.

M2-002 Terminal Audit001 returned **FAIL — P0 0 / P1 0 / P2 1** against the
exact current pre-persistence 12-path candidate. Its canonical path-first
`path<TAB>bytes<TAB>lowercase-sha256<LF>` identity is 1,224 bytes with SHA-256
`ebf1bdb46f99a6bf2691e6e836dee60008f819c597cd9c3c9de6034cf9cee18e`.
The r1 manifest does not persist observed actual torch intra-op or inter-op
thread counts, embedding/model dtype, or index memory. The code requests one
thread and float32, but requested values are not evidence of the observed
runtime state. Index memory is practically measurable as
`3633 * 768 * 4 = 11,160,576` bytes. Metrics and rankings remain correct, but
the authorized remediation batch is exhausted at 1/1. Owner authorization is
required to choose whether to open a new remediation and fresh benchmark or
close the work item without terminal acceptance.

The authoritative dependency Audit manifest remains the 28,196-byte
`dependency-final-osv/evidence-manifest.json`, SHA-256
`a0835993f71d45df80292c8eea8d14f8bce2fe922cff294df7c5c42eafd74c7c`.
These observations do not establish a superior retriever or authorize a
production choice. Latency is local wall-clock evidence only. The experiment-
only `ME-000C` exception remains open for production/release indexes, Qdrant,
rerankers, and later retrieval architecture.

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

## M2-002 r2 provenance-remediation candidate

Submission status before Review003: **AWAITING_INDEPENDENT_REVIEW**. This section records the single
Owner-authorized remediation of Terminal Audit001 P2. It does not supersede or
alter the historical r1 evidence, Review001 FAIL, Review002 PASS, or Terminal
Audit001 FAIL, and it makes no terminal acceptance or readiness claim.

External run directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r2`

| File | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 34,332 | `571b1ad4c5960b9088d9457b47d653bf0afd9e5785a56e6c966bae661c1cb407` |
| `manifest.sha256` | 80 | `54f295aa3222b91a38307bf78eea61e6dc094446d94df011755f812007f10991` |
| `per-query-dense.jsonl` | 2,752,084 | `b4cfef197a75bcd47016801c9c5c777f6d1ecaa39f33963f5ffa194ee9d7662c` |
| `per-query-hybrid_rrf_medcpt.jsonl` | 3,848,032 | `3f4886a6b5a776e8017279c784ec124d4a0b6704fcb0262ffe756e11f3b46ea0` |
| `per-query-medcpt.jsonl` | 2,742,406 | `6737c63ef03d492947d1229d6280c7468146790187a0f94ffa1a4221969e1e18` |
| `per-query-sparse.jsonl` | 1,899,175 | `541a0a2256df10e3e270458329439dcebc94705f74163490481cb636bf70d151` |
| `source.patch` | 145,774 | `475e6239df217e48fdecff84469b76731b3e2051da1582d44e8441f772ea28e3` |
| `source-state.json` | 1,552 | `6fb021c1554441a0614818af5713b1e1227f8d3b8a212c530cc472ba8ac5fe76` |
| `source-untracked-snapshot.json` | 124,612 | `fbe10356d727e6c90a8b84b210cb158d51b315b0263b049a1a7aec84b694879e` |

The r2 manifest records observed PyTorch intra-op and inter-op thread counts of
one; query and article model parameter dtype `torch.float32`; query embedding
and document embedding/index dtype `float32`; and document embedding matrix
memory of 11,160,576 bytes measured by `numpy.ndarray.nbytes`. This memory
measurement covers only the document embedding matrix, not Python process RSS,
allocator overhead, model memory, or total application memory.

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | P50 (ms) | P95 (ms) | Build/index seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.8319074299453899 | 0.2597999991849065 | 2.846459997817872 | 0.2409466999961296 measured |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 13.868896284577835 | 13.751399994362146 | 14.182479989540296 | 2.2162746000103652 measured |
| MedCPT dense | 0.1827810170966193 | 0.3674126109143263 | 0.5487689812767212 | 30.03730216757726 | 28.166100004455075 | 36.38049000437603 | 2497.3564415 measured |
| RRF(BM25, MedCPT) | 0.1810206378195796 | 0.3649385324032572 | 0.5698289842252691 | 30.629491949801395 | 28.79150000808295 | 39.83871000964427 | 2497.597388199996 derived sum |

All four ranking-metric triples equal r1 exactly. A semantic comparison found
1,292 of 1,292 per-query records equal across query/mode identity, rankings,
scores, candidate evidence, metrics, and components; timing is newly observed
r2 evidence. All nine r1 artifacts rehashed unchanged. Focused provenance tests
passed 54 tests; the full offline suite passed 1,797 tests with two expected
warnings and 79% coverage; Ruff, the 120-file format check, MyPy over 52 source
files, the 87-package lock check, and diff checks passed.

The exact pre-documentation candidate was the canonical ordinal path-first,
UTF-8/LF manifest with 12 rows, 1,224 bytes, SHA-256
`1f85f3dabfed3dd01346e0c75cd740cfa4218dd42d46df058a123437748f96fa`.
This cycle made no network request, model acquisition, dependency/advisory
audit, Git operation, or second benchmark execution.

### M2-002 Independent Review003

Status before Terminal Audit002: **AWAITING_TERMINAL_AUDIT**. Independent Review003 returned
**PASS — P0 0 / P1 0 / P2 0** for the exact r2 remediation candidate. This is
not terminal acceptance and does not claim completion, readiness, commit,
release approval, or retriever superiority.

The reviewed candidate recipe is ordinal sorting by repository-relative path,
then UTF-8 encoding of LF-terminated rows formatted
`path<TAB>bytes<TAB>lowercase-sha256<LF>`. Its exact 12-row, 1,224-byte
identity is SHA-256
`8119f8850de2a484ed66de2814e6b2be7c96fb425600fa23aba7a948c2cffc03`:

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	22583	a11f150f8e500fba63a4302e1be32d01bcd4b9fb9291a189bfa09719bcd61ed6
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	17473	4f40a7cef21eba56a9a642b2a10190bbc9ce3729ca1ce2f0367bc352c6b083e4
evaluation/README.md	16682	2318a51d7dd42508922d7065f49aa716aa1c7d073e910ae0efcf4ef6857dd8ef
evaluation/harness.py	37520	1d8d1c00681e8188b172a5030a244434985c88eba50c256e6533ad76a8e49fb6
evaluation/medcpt.py	38243	82af49624f9ba27cda5ef194fc562e2ced468d484f60598c650fa76406aed698
evaluation/run_evaluation.py	7217	ead334cca2ee40576c1e98085d133e50c34b9bac0821c9b21a942f67bb284119
pyproject.toml	1627	8974cd31bcd4ee17a7a839b052bc1cf0499c573429251768fd8dc94536f26567
scripts/dependency-audit.ps1	87126	f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70
tests/contract/evaluation/test_harness.py	26016	8e62a1d19cab3651e3a746cd7530b0ca51ce67142aec8d673d0d66fbbfc1a212
tests/unit/evaluation/test_medcpt.py	22504	5d8556d472c8e55edfec5f7b7f24e9c24c0b8e3b6c994ae995c0b0ccc496a000
tests/unit/test_dependency_boundaries.py	32904	44b95bf9040ac4d39160bbd14b224dc40548e75df4951855a1efd341f37c545b
uv.lock	143454	069feed3524ee157acad46381f55b898af0cd56c179471a925677006812e2680
```

The reviewer rehashed r1 9/9 and r2 9/9, recomputed the 1,292 per-query metric
records and 323 RRF pools, and found r1/r2 semantic evidence equal 1,292/1,292.
Exactly 1,289 query latencies and all build timings differed as fresh timing
evidence. Frozen data/qrels, exact model revisions and 18-file cache,
dependencies, configuration, and Git baseline were unchanged. Observed
provenance was exactly one intra-op and one inter-op thread, F32 safetensors and
`torch.float32` parameters, `float32` query/index embeddings, and 11,160,576
matrix bytes measured by `numpy.ndarray.nbytes` with the stated limitation.
The change was provenance-only, failed before artifact creation when evidence
was unavailable, and did not hard-code the expected byte value. Review003 made
no write, network request, model acquisition, dependency audit, or benchmark
execution.

### M2-002 Terminal Audit002

Current status: **TERMINAL_PASS_AWAITING_GIT_FINALIZATION**. Terminal Audit002
returned **PASS — P0 0 / P1 0 / P2 0**. It does not claim that commit, push,
PR, hosted CI, merge, or integrated verification has occurred, and it does not
emit M2-002 completion or readiness markers.

The audit was bound to branch `feat/m2-002-medcpt-ps7`, HEAD
`07c548737ec351c5a2a0669078f559700ac8b9b8`, an empty index, and the ordinal
repo-relative path-first UTF-8/LF candidate manifest: 12 rows, 1,224 bytes,
SHA-256
`a7b8c5ab976b901c26c968263001b9093b128099bbf3ff41dc29399091568ffa`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	25852	f77b7e8d6b8c4573855845a046114867577cbbf7f5a0faac0f06746a4725abaa
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	20635	780154c5720726b1f8f8dbe3c261e851eb2048e35e5e84e46a78fd84f3e54aa9
evaluation/README.md	19404	c5e559d8e61deb256ebc2522e2290deabcb47bc63a90cb2282b243346f57167e
evaluation/harness.py	37520	1d8d1c00681e8188b172a5030a244434985c88eba50c256e6533ad76a8e49fb6
evaluation/medcpt.py	38243	82af49624f9ba27cda5ef194fc562e2ced468d484f60598c650fa76406aed698
evaluation/run_evaluation.py	7217	ead334cca2ee40576c1e98085d133e50c34b9bac0821c9b21a942f67bb284119
pyproject.toml	1627	8974cd31bcd4ee17a7a839b052bc1cf0499c573429251768fd8dc94536f26567
scripts/dependency-audit.ps1	87126	f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70
tests/contract/evaluation/test_harness.py	26016	8e62a1d19cab3651e3a746cd7530b0ca51ce67142aec8d673d0d66fbbfc1a212
tests/unit/evaluation/test_medcpt.py	22504	5d8556d472c8e55edfec5f7b7f24e9c24c0b8e3b6c994ae995c0b0ccc496a000
tests/unit/test_dependency_boundaries.py	32904	44b95bf9040ac4d39160bbd14b224dc40548e75df4951855a1efd341f37c545b
uv.lock	143454	069feed3524ee157acad46381f55b898af0cd56c179471a925677006812e2680
```

Terminal evidence confirmed Review003 persistence changed exactly the three
documentation paths while the other nine candidate paths were unchanged; r1
and r2 artifacts rehashed 9/9; and source patch/state/snapshot bindings were
exact. The frozen benchmark contained 3,633 documents, 3,237 queries, 323
judged/evaluated queries, and 12,334 qrels. The exact two-model cache contained
18 files and 877,783,608 bytes with aggregate SHA-256
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`.

Observed runtime evidence was PyTorch intra/inter-op `1/1`, query/article
parameters `torch.float32`, query/index embeddings `float32`, and 11,160,576
document-matrix bytes measured by `numpy.ndarray.nbytes` with the matrix-only
limitation. The auditor recomputed 2,584 per-query metric records across r1 and
r2, all eight summaries, and all 323 RRF pools; r1/r2 semantics matched
1,292/1,292, while 1,289 query latencies and all four build timings differed.
The universal dependency set reconciled 86 = 85 active + 1 inactive with zero
vulnerabilities, exceptions, unresolved identities, or accelerator packages.
Focused 54, full offline 1,797 with two warnings and 79% coverage, Ruff,
120-file format, MyPy 52, lock 87, and diff checks remained bound and passing.
Audit002 itself made zero writes and zero network or benchmark requests.

### M2-002 CI-only dependency-audit remediation submission

Status: **CI_DELTA_AWAITING_INDEPENDENT_REVIEW**. The accepted r2 benchmark,
Review003 PASS 0/0/0, and Terminal Audit002 PASS 0/0/0 remain immutable and
were not rerun. This is not a new acceptance, completion, readiness, merge, or
integrated-verification claim.

Commit `719e2ad1f424b0085b151cef6a634d17ef02d799` was submitted as Draft PR #26.
The first hosted run returned `compose-config` PASS in 42 seconds,
`windows-quality` PASS in 2 minutes 24 seconds, and `dependency-audit` FAIL in
1 minute 39 seconds at the exact expected `torch==2.13.0+cpu` skip because the
workflow did not supply the existing validator's OSV evidence paths. The
Owner-authorized CI-only closure changes exactly these pre-documentation bytes:

```text
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

The dependency script is unchanged at 87,126 bytes, SHA-256
`f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70`.
One shared PR/push path performs one pip-audit and one no-retry,
nonredirecting OSV POST, retains evidence under `RUNNER_TEMP`, fails closed on
unexpected pip-audit or OSV evidence, validates the exact CPU Torch binding,
and passes all three preserved-evidence paths to the unchanged audit script.

Local checks passed: 93 focused tests, Ruff, format over 120 files, MyPy over
52 source files, lock validation over 87 packages, and diff checks. The one
mechanical retry corrected formatting/UTC lint only. No local network, model,
benchmark, medical-source, or Git operation occurred. Fresh independent review
of this exact CI delta is pending.

### M2-002 CI Delta Review004

Review004 returned **PASS — P0 0 / P1 0 / P2 0**. Current status is
**CI_DELTA_REVIEW_PASS_AWAITING_TERMINAL_AUDIT**; no terminal acceptance,
completion, readiness, merge, or integrated-verification claim is made.

The review bound branch `feat/m2-002-medcpt-ps7`, HEAD
`719e2ad1f424b0085b151cef6a634d17ef02d799`, and an empty index to this exact
ordinal path-first UTF-8/LF manifest: 5 rows, 564 bytes, SHA-256
`789f9877a19f9cb1d9ba01e4a01f96dce53d7ffaa09d49de0263db9dbb7a8b2c`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	31897	9ff8f0459fee1a2effcfad53cacbdb69fe6585431fe32b5a8181d50d3368ef2f
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	25760	49df739ef86c6667c576c8fdcdfc1fa521c918b1c64f96c56491bfad66f8445a
evaluation/README.md	24400	b54017c62d4f2278061761bcfb421fc022ce48925c641917668dfdcebd77c863
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

The reviewer confirmed the shared PR/main path, retained raw pip evidence,
strict pre-OSV gate, one exact no-redirect/no-retry direct POST, exact
artifact/lock/wheel binding, three preserved-evidence parameters, and the
unchanged validator's independent 84 + 1 + 1 reconciliation. The executable
tests were meaningful and the evidence history truthful. Review004 itself made
zero writes, network requests, test executions, model loads, or benchmark
runs. This three-document persistence now requires exact-byte terminal audit.

### M2-002 CI Delta Terminal Audit003

Terminal Audit003 returned **PASS — P0 0 / P1 0 / P2 0**. Current status is
**CI_DELTA_TERMINAL_PASS_AWAITING_HOSTED_CI**. No Ready, merge, post-merge,
integrated-completion, or final readiness marker is claimed.

The audit bound branch `feat/m2-002-medcpt-ps7`, HEAD
`719e2ad1f424b0085b151cef6a634d17ef02d799`, and an empty index to the exact
ordinal path-first UTF-8/LF candidate: 5 paths, 564 bytes, SHA-256
`f0daf3a5a9a5944ac83790357ad98eb75546f2e1d1365d1128af46b266d4c02d`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	33870	166bdf79d32f4951f0f3fa60ea515883d6657500eca628be40ab8d0ac7ca72bb
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	28252	9892856bbd70199bf81df7668d3d7e7350d7f4addc4a6f89a4595845c8d89221
evaluation/README.md	26019	ec51aff3b51da689390b7f2625118c36d065cfbd92219d633554a81dd23bf9c6
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

Audit003 verified exact scope, Review004 workflow/test byte equality, and the
three-document review-prefix proof. The audit script remained unchanged at
87,126 bytes, SHA-256
`f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70`.
The workflow retained one shared path, raw pip evidence, strict pre-OSV
validation, one exact no-retry/no-redirect POST, 10/30-second timeouts,
1,048,576-byte response maximum, exact CPU artifact/lock/wheel identity,
acquisition evidence, and all three preserved paths. The unchanged validator
reconciles 84 + 1 + 1 = 86 identities.

R1 and r2 rehashed 9/9 each. UTF-8/LF, diff, 93 focused tests, Ruff, format
120, MyPy 52, and lock 87 remained accepted. Audit003 itself made zero writes,
network requests, tests, model operations, or benchmark runs. Hosted PR CI is
the next gate.
