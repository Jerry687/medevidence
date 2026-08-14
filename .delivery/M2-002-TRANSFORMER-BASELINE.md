# M2-002 transformer baseline candidate record

Updated: `2026-08-14`

Status: **`OWNER_DECISION_REQUIRED`**

This record binds the external M2-002 MedCPT benchmark candidate. It does not
make a terminal acceptance, readiness, release, or superiority determination.

## Scope and semantic boundary

The candidate evaluates four retrieval modes over the exact frozen NFCorpus
test judgments:

- BM25 sparse retrieval;
- classical TF-IDF plus truncated-SVD LSI dense retrieval;
- MedCPT dense retrieval; and
- the approved two-way RRF(BM25, MedCPT) fusion.

The RRF mode has exactly two components; there is no three-way fusion.
Production dependency defaults and retrieval defaults are unchanged. MedCPT is
evaluation-only and loads exact external safetensors artifacts locally.

The experiment-only `ME-000C` boundary applies only to this benchmark.
`ME-000C` remains open for production/release indexes, Qdrant, rerankers, and
later retrieval architecture. The measurements do not establish clinical,
causal, incidence, regulatory, comparative product-risk, production-readiness,
release-threshold, or individualized-advice claims.

## Authoritative run identity

External run directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r1`

Manifest execution timestamp: `2026-08-14T02:36:13.506522-05:00`

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

Execution revision: `07c548737ec351c5a2a0669078f559700ac8b9b8`

Source-state identity:
`a719bcd8e47d6538c7c187dac46cc79f002dea493fe285a9597191947e8c9862`

Reconstruction is HEAD plus `source.patch`; the two untracked adapter/test
files are bound by the source snapshot:

- `.delivery/M2-002-TRANSFORMER-BASELINE.md`: 10,126 bytes; SHA-256
  `0459b872d317144e6ba2bb020d38b2cdf3daa8af6129552923fafd5eb7090acb`;
- `evaluation/medcpt.py`: 35,693 bytes; SHA-256
  `5fadb2b2a7078405386b0d2d0a07e659753c21faa55c7a2f0e92c470458a88a8`;
- `tests/unit/evaluation/test_medcpt.py`: 19,625 bytes; SHA-256
  `deee5062b8c33a53c1aad92e586efbc5da0c3721ab21136780b54b53b5fd5318`.

The tracked patch binds `evaluation/README.md`, `evaluation/harness.py`,
`evaluation/run_evaluation.py`, `pyproject.toml`,
`scripts/dependency-audit.ps1`,
`tests/contract/evaluation/test_harness.py`,
`tests/unit/test_dependency_boundaries.py`, and `uv.lock`.

## Frozen dataset provenance

- Dataset and split: `NFCorpus`, test judgments
- Distribution URL:
  `https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip`
- Archive: 2,448,432 bytes; SHA-256
  `efe5be03f8c5b86a5870102d0599d227c8c6e2484328e68c6522560385671b0b`
- Corpus identity:
  `sha256:511592c84193977f19027bcf1ab00d3ed1bb7857c744060327391e2fc9d3f66c`
- Documents: 3,633
- Dataset queries: 3,237
- Judged/evaluated test queries: 323
- Judgments: 12,334 (11,758 grade 1; 576 grade 2)

| Consumed file | Bytes | SHA-256 |
|---|---:|---|
| `corpus.jsonl` | 6,219,364 | `10cc83ef1826b1425e6a87090b5140b39b27755d5a27e48215a88611c899991f` |
| `queries.jsonl` | 441,466 | `d024e6621b84925d485ae473d316a0c3af31c62c8068a59fb29d22f7613aef2a` |
| `qrels/test.tsv` | 279,572 | `f8fba6ef3d4dd9c3a242a8ba4ae38276fc3622fce7dcbae764766d564542fd2a` |

The archive and dataset bytes remain external to Git.

## Exact model and artifact provenance

| Role | Repository | Immutable revision | `model.safetensors` bytes | `model.safetensors` SHA-256 |
|---|---|---|---:|---|
| Query | `ncbi/MedCPT-Query-Encoder` | `d83a36cc6b8e3a5c5e9d9d6ba156808c1643dcbc` | 437,951,328 | `19d78c0d5eaee2f81e6c47c5425bbadcc0c6af016cbb5da4a000d64e59d6e342` |
| Article | `ncbi/MedCPT-Article-Encoder` | `d05a736da4bb84ee4057b7f7999485be6ed85465` | 437,951,328 | `a5d5ffe4d8666c1d0aa15f371b94fc3492ca8f927e5621abd4b3ee9fc845b0f3` |

Artifact acquisition manifest:
`D:\Projects\medevidence-m2-002-model-evidence\medcpt-artifact-acquisition-r1.json`

- Schema: `medevidence.m2-002.medcpt-artifact-acquisition.v1r1`
- Bytes: 94,242
- SHA-256:
  `5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755`
- Successor raw ledger: 56,755 bytes; SHA-256
  `a7b66388278e29f88b1602faffb6a195d3f1bd96f1769a2187394bb6193c97e5`
- Cache inventory: 2 repositories, 18 files, 877,783,608 bytes
- Canonical aggregate SHA-256:
  `64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`

The adapter independently pins all 18 path/byte/SHA-256, blob, URL, etag, and
LFS identities, recomputes the canonical aggregate, and rejects the superseded
v1 manifest. The v1r1 lineage binds the transparent failed parameterless probe
at ledger index 38 and the two authoritative `?blobs=true` metadata GETs at
indexes 39 and 40, including UTC timestamps, URLs, status, bytes, hashes, and
exact equality with the preserved raw metadata. No model fallback or network
retrieval is part of benchmark loading.

## Exact retrieval and execution configuration

- BM25: `k1=0.9`, `b=0.4`
- Tokenizer: `unicode_lower_alnum_v1`
- Classical dense: `tfidf_svd_v1`, requested and actual dimensions `256`
- MedCPT: CPU, evaluation/inference mode, dimensions `768`
- MedCPT query: maximum length `64`, batch size `1`
- MedCPT article: `[title, text]` pair, maximum length `512`, batch size `8`
- MedCPT pooling: `last_hidden_state` CLS token
- MedCPT normalization: none; similarity: inner product
- RRF: exactly BM25 plus MedCPT, `k=60`
- Candidate limit: `100`; final limit: `10`
- Relevant grade minimum: `1`
- Random seed: `0`
- Query execution: serial single process, concurrency `1`
- Requested BLAS and torch/native threads: `1`
- Python: `3.12.13`; platform: `Windows-11-10.0.26200-SP0`
- NumPy: `2.5.1`; scikit-learn: `1.9.0`; SciPy: `1.18.0`
- torch: `2.13.0+cpu`; transformers: `5.15.0`
- `uv.lock`: 143,454 bytes; SHA-256
  `069feed3524ee157acad46381f55b898af0cd56c179471a925677006812e2680`

`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`,
`BLIS_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` were each `1`. Every captured
BLAS/OpenMP pool reported one thread at entry and exit of index build and all
four query-latency contexts. OS scheduling, filesystem cache, and unrelated
host load remained uncontrolled; latency is local wall-clock evidence, not a
production SLO.

## Exact candidate measurements

All metrics below are macro averages over the same 323 judged test queries.

| Mode | Precision@5 | Recall@5 | Precision@10 | Recall@10 | nDCG@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.27678018575851393 | 0.11773217189696483 | 0.2148606811145511 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 |
| Classical LSI dense | 0.2848297213622291 | 0.11358580148971073 | 0.23219814241486067 | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 |
| MedCPT dense | 0.3380804953560372 | 0.14029693672397467 | 0.2696594427244582 | 0.1827810170966193 | 0.3674126109143263 | 0.5487689812767212 |
| RRF(BM25, MedCPT) | 0.33436532507739936 | 0.1451514861204906 | 0.26130030959752326 | 0.1810206378195796 | 0.3649385324032572 | 0.5698289842252691 |

| Mode | Mean latency/query (ms) | P50 (ms) | P95 (ms) | Build/index seconds | Timing kind |
|---|---:|---:|---:|---:|---|
| BM25 | 0.7037046440136719 | 0.19659999816212803 | 2.464779998990707 | 0.23272179999912623 | measured |
| Classical LSI dense | 15.814452941480615 | 15.819200001715217 | 16.277499996795086 | 2.107056199994986 | measured |
| MedCPT dense | 29.08273126946938 | 26.992700004484504 | 36.29832999795326 | 2439.565887099998 | measured |
| RRF(BM25, MedCPT) | 29.242885449118933 | 27.341100001649465 | 38.752260000183014 | 2439.798608899997 | derived sum of measured BM25 and MedCPT builds |

These descriptive measurements do not establish that any mode is superior and
do not authorize model selection or production deployment. The modes differ
across reported metrics, and latency is limited to this local host and run.

## Review001 and single-batch remediation

Independent Review001 returned **FAIL — P0 0 / P1 1 / P2 1** on the original
candidate at
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final`.
That run is retained as historical pre-remediation evidence; its 33,260-byte
manifest has SHA-256
`0473abe092ffc9e025338ef00bcdc599fadf98ef1aaf9d03384333ee23bfe7f1`.

The P1 finding showed that `load_medcpt_artifacts` self-trusted non-weight file
hashes and republished an unrecomputed aggregate. The executable counterexample
accepted arbitrary tokenizer/config bytes, `example.invalid` acquisition URLs,
and `sha256:fixture` under the approved revisions and weight identities. This
allowed ranking-changing tokenizer drift to pass under nominally unchanged
model identities.

The P2 finding showed incomplete acquisition lineage for the original raw
metadata: query 2,943 bytes / SHA-256
`6ead632a25d705d455ab3f85cfd517a9551f5ae99191a3e1094262310a80e9cd`
and article 2,855 bytes / SHA-256
`5d71f6b956e598e431eed3a7b12a913122e57c968d4b4b0ac13004b8df8ec8f0`
lacked request URL and timestamp evidence and were absent from the original
38-entry, 52,054-byte ledger, SHA-256
`48384154493b330d25b804bb089db2a22079bb961b490b71f7973bb94bd8d0f1`.

Review001 also positively recomputed all 1,292 per-query records, all four
summaries, and all 323 RRF top-ten rankings exactly, and confirmed the frozen
dataset/qrels, thread settings, dependency evidence, and M2-001 scope.

The single Owner-authorized batched remediation closed both finding classes in
implementation and executable tests. It hard-pinned all 18 cache and
acquisition identities, recomputed the aggregate, rejected v1, and bound the
v1r1 metadata and r1 ledger described above. Negative tests cover tokenizer,
config, README, aggregate, blob, requested/final URL, repository metadata,
lineage, successor-ledger, prohibited `.bin`, unlisted file, and old-v1 drift.

Fresh closure evidence:

- focused adapter tests: `17 passed`;
- broader evaluation tests: `111 passed`;
- full offline unit/contract suite: `1,793 passed`, two expected warnings,
  79% coverage;
- Ruff check: PASS;
- Ruff format check: `120 files already formatted`;
- strict MyPy over `src`: `52` source files, PASS;
- `uv lock --check`: `87` packages, PASS; and
- diff checks: PASS.

The r1 execution completed in 2,468.6 seconds. Retrieval quality metrics equal
the original run exactly; latency and build timings above are fresh r1 local
measurements. Independent Review002 evaluated this closure and the r1 evidence
and returned **PASS — P0 0 / P1 0 / P2 0**.

## Independent Review002

Review002 was bound to this exact pre-persistence 12-path candidate. The
identity is the UTF-8, LF-terminated concatenation of the following lines in
ordinal path order, each formatted
`path<TAB>bytes<TAB>lowercase-sha256<LF>`: 1,223 bytes, SHA-256
`28a7e7d7c881832fbda08e0299bfa2646e39b923a3d9f120f7bd4d90e64c1a26`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	13386	eeb3f485eab6dda64776444ab59f712c8f3c95f3f998446aa161309152de294c
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	8486	fe205e17393667b9fb45da436f49318903e56a78d5d3f0397230093b565d61d1
evaluation/README.md	11706	da93f4f99a92d60a58ab61293ac66c88609a4b4b88a7d6c1dc3a7fc73bc0bc8e
evaluation/harness.py	37321	d95c626c3d482a91b9280b34a0a6b92eb713e3170011b0c007f7ede88a85d24c
evaluation/medcpt.py	35693	5fadb2b2a7078405386b0d2d0a07e659753c21faa55c7a2f0e92c470458a88a8
evaluation/run_evaluation.py	7217	ead334cca2ee40576c1e98085d133e50c34b9bac0821c9b21a942f67bb284119
pyproject.toml	1627	8974cd31bcd4ee17a7a839b052bc1cf0499c573429251768fd8dc94536f26567
scripts/dependency-audit.ps1	87126	f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70
tests/contract/evaluation/test_harness.py	23517	38315ffd33e6f8cd3003aad3aaa8801cb669fa3b8baeffe2be9e46cd19a9ed59
tests/unit/evaluation/test_medcpt.py	19625	deee5062b8c33a53c1aad92e586efbc5da0c3721ab21136780b54b53b5fd5318
tests/unit/test_dependency_boundaries.py	32904	44b95bf9040ac4d39160bbd14b224dc40548e75df4951855a1efd341f37c545b
uv.lock	143454	069feed3524ee157acad46381f55b898af0cd56c179471a925677006812e2680
```

The reviewer revalidated the v1r1 manifest and ledger, the 18-file cache and
recomputed aggregate, the transparent failed probe and exact authoritative
metadata lineage, and fail-closed rejection of v1 and identity mutations. The
review also rehashed all nine r1 run artifacts, checked the exact source
reconstruction, recomputed all 1,292 per-query records and four summaries,
reconstructed all 323 RRF top-ten rankings and candidate pools, and confirmed
all ten thread observations were one. Quality and rankings equal the historical
run exactly; timestamps, build timings, and all query timings are fresh, with
1,290 of 1,292 per-query latencies differing.

Review002 also confirmed the frozen dataset counts and judgment histogram, the
dependency closure described below, all eight M2-001 artifacts, and the absence
of premature documentation claims. Its final verdict is **PASS — P0 0 / P1 0 /
P2 0**. This persistence changes the three documentation files in that reviewed
prefix. M2-002 Terminal Audit001 subsequently evaluated that post-persistence
candidate as recorded below.

## M2-002 Terminal Audit001

Terminal Audit001 verdict: **FAIL — P0 0 / P1 0 / P2 1**. It was bound to the
exact current pre-persistence 12-path candidate below. The identity is the
UTF-8, LF-terminated concatenation in canonical path-first ordinal order, with
each line formatted `path<TAB>bytes<TAB>lowercase-sha256<LF>`: 1,224 bytes,
SHA-256
`ebf1bdb46f99a6bf2691e6e836dee60008f819c597cd9c3c9de6034cf9cee18e`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	16140	72d39ed0c3ab04cfe345bbf214c1436158f0a7fcfd386497c0340d3dd201193b
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	11398	fc102397ffa1523904ad7eca5ab50d1067391298beb1e60d8691f5e08ad6c915
evaluation/README.md	12273	a5700aef5fad9fa92dae9887dcc7401ec89454ff069d0af5edaf45ab5ba7a823
evaluation/harness.py	37321	d95c626c3d482a91b9280b34a0a6b92eb713e3170011b0c007f7ede88a85d24c
evaluation/medcpt.py	35693	5fadb2b2a7078405386b0d2d0a07e659753c21faa55c7a2f0e92c470458a88a8
evaluation/run_evaluation.py	7217	ead334cca2ee40576c1e98085d133e50c34b9bac0821c9b21a942f67bb284119
pyproject.toml	1627	8974cd31bcd4ee17a7a839b052bc1cf0499c573429251768fd8dc94536f26567
scripts/dependency-audit.ps1	87126	f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70
tests/contract/evaluation/test_harness.py	23517	38315ffd33e6f8cd3003aad3aaa8801cb669fa3b8baeffe2be9e46cd19a9ed59
tests/unit/evaluation/test_medcpt.py	19625	deee5062b8c33a53c1aad92e586efbc5da0c3721ab21136780b54b53b5fd5318
tests/unit/test_dependency_boundaries.py	32904	44b95bf9040ac4d39160bbd14b224dc40548e75df4951855a1efd341f37c545b
uv.lock	143454	069feed3524ee157acad46381f55b898af0cd56c179471a925677006812e2680
```

The P2 finding is that the r1 manifest does not persist the observed actual
torch intra-op thread count, torch inter-op thread count, embedding/model dtype,
or index memory. The implementation requests one thread and float32, but those
requests do not establish the actual observed runtime values in the benchmark
evidence. Index memory is practically measurable for the recorded matrix as
`3633 * 768 * 4 = 11,160,576` bytes.

The audit confirmed that metrics and rankings remain correct. No remediation
was performed: the authorized remediation batch is exhausted at 1/1. Owner
authorization is required to choose between opening a new remediation with a
fresh benchmark that persists observed runtime values, or closing the work item
without terminal acceptance.

## Dependency evidence

Authoritative final evidence directory:
`D:\Projects\medevidence-m2-002-ps7-dependency-evidence\dependency-final-osv`

| Evidence | Bytes | SHA-256 |
|---|---:|---|
| `evidence-manifest.json` | 28,196 | `a0835993f71d45df80292c8eea8d14f8bce2fe922cff294df7c5c42eafd74c7c` |
| `package-reconciliation.json` | 13,189 | `e56f604c36099e0e8a840a5d89f91f674f74e6d800a48b0a343b6bcc5d3f6430` |
| `licenses.json` | 35,493 | `ee13fdb65301a6f51a0e5deae8e2e539a7c88fd458ac4be5b37c0b9582b14484` |

The schema `3.0` Audit manifest records `overall_outcome=pass` and
`advisory_status=passed_no_known_vulnerabilities`: 86 external packages, zero
known vulnerabilities, skips, exceptions, missing license metadata, or
license-review items. It binds the Windows amd64
`torch==2.13.0+cpu` official CPU wheel and the exact candidate file-set
identity `sha256:683cf5a5aec88c79f41fcb501a3450fa5824af4bb8eb4c4180c1b7b03257bc59`.

Independent dependency review returned **PASS — P0 0 / P1 0 / P2 0**
in-session. That review was not persisted, so no review file, path, or hash is
claimed. This dependency review is not an independent review of the benchmark
candidate documented here.

## Candidate disposition and boundaries

The exact r1 external artifacts, source reconstruction, model snapshots,
dataset, configuration, dependency evidence, and descriptive measurements are
bound above. Review001 remains an immutable historical FAIL on the original
candidate. Independent Review002 passed the exact pre-persistence candidate at
P0 0 / P1 0 / P2 0. Terminal Audit001 failed at P0 0 / P1 0 / P2 1, and the
authorized remediation batch is exhausted. An Owner decision is required; this
record makes no terminal acceptance or readiness claim.

This evidence-only finalization read local artifacts and made no network
request. It did not contact PubMed, NCBI APIs, DailyMed, FAERS, or any other
medical source. It did not alter benchmark results, model artifacts, cache,
dataset bytes, dependencies, code, or tests.

No Git stage, commit, push, pull, fetch, merge, rebase, reset, clean, branch
operation, or history rewrite was performed by this finalization.

## Owner-authorized Terminal Audit001 P2 remediation: r2 candidate

Submission status before Review003: **AWAITING_INDEPENDENT_REVIEW**. The historical Review001 FAIL,
Review002 PASS, Terminal Audit001 FAIL, and immutable r1 benchmark remain as
recorded above. This successor section does not claim terminal acceptance,
completion, readiness, release approval, or retriever superiority.

The exactly one authorized successor run is:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r2`.

| Artifact | Bytes | SHA-256 |
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

Observed runtime evidence in the same r2 manifest is:

- PyTorch intra-op threads: `1`;
- PyTorch inter-op threads: `1`;
- query encoder parameter dtype: `torch.float32`;
- article encoder parameter dtype: `torch.float32`;
- query embedding dtype: `float32`;
- document embedding/index dtype: `float32`;
- dense-index memory: `11,160,576` bytes;
- measurement: `numpy.ndarray.nbytes`.

The memory value is the exact document embedding matrix only. It is not Python
process RSS, allocator overhead, model memory, or total application memory.

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | P50 (ms) | P95 (ms) | Build/index seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.8319074299453899 | 0.2597999991849065 | 2.846459997817872 | 0.2409466999961296 measured |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 13.868896284577835 | 13.751399994362146 | 14.182479989540296 | 2.2162746000103652 measured |
| MedCPT dense | 0.1827810170966193 | 0.3674126109143263 | 0.5487689812767212 | 30.03730216757726 | 28.166100004455075 | 36.38049000437603 | 2497.3564415 measured |
| RRF(BM25, MedCPT) | 0.1810206378195796 | 0.3649385324032572 | 0.5698289842252691 | 30.629491949801395 | 28.79150000808295 | 39.83871000964427 | 2497.597388199996 derived sum |

Every r2 ranking-quality metric equals r1 exactly. The semantic comparator
matched 1,292/1,292 records across query and mode identity, rankings, scores,
candidate rankings/scores, metrics, and components. Timing is fresh r2
machine-local evidence. All 9/9 r1 artifacts rehashed unchanged.

Validation passed: 54 focused tests; 1,797 full offline tests with two expected
warnings and 79% coverage; Ruff; format over 120 files; MyPy over 52 source
files; `uv lock` over 87 packages; and diff checks. The exact pre-evidence
candidate canonical ordinal path-first UTF-8/LF identity was 12 rows, 1,224
bytes, SHA-256
`1f85f3dabfed3dd01346e0c75cd740cfa4218dd42d46df058a123437748f96fa`.

This remediation used the frozen NFCorpus data, exact cached MedCPT revisions,
existing local model cache, and existing dependency environment. It made no
Hugging Face, model, dependency/advisory, medical-source, or other network
request; performed no model acquisition; ran no second successor benchmark;
and performed no Git operation. Independent review and terminal audit remain
pending.

## M2-002 Independent Review003

Status before Terminal Audit002: **AWAITING_TERMINAL_AUDIT**. The one fresh independent review
of the exact r2 remediation candidate returned **PASS — P0 0 / P1 0 / P2 0**.
This review result is not terminal acceptance and does not claim M2-002
completion, readiness, commit, merge, release approval, or superiority.

The reviewed candidate identity uses ordinal repository-relative path order and
UTF-8 rows formatted `path<TAB>bytes<TAB>lowercase-sha256<LF>`. The exact
12-row, 1,224-byte manifest has SHA-256
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

Review003 independently established:

- immutable r1 benchmark artifacts rehashed 9/9 and r2 artifacts rehashed 9/9;
- 1,292 per-query metric records recomputed and 323 RRF candidate pools and
  rankings reconstructed;
- r1/r2 semantic evidence matched 1,292/1,292, while 1,289 query latencies and
  every build timing differed as expected for the fresh r2 execution;
- frozen NFCorpus data/qrels, exact MedCPT revisions and 18 cache files,
  dependency closure, retrieval configuration, and Git baseline were unchanged;
- actual provenance recorded PyTorch intra/inter-op `1/1`, query/article
  parameter dtype `torch.float32`, query/index dtype `float32`, and document
  matrix memory 11,160,576 bytes measured by `numpy.ndarray.nbytes` with the
  exact matrix-only limitation;
- the cached model weights were safetensors with F32 tensors;
- the implementation delta was provenance-only, did not alter retrieval or
  metric semantics, failed before artifact creation when a required runtime
  observation was unavailable, and did not hard-code 11,160,576; and
- the review itself made no repository or evidence write, no network request,
  and no benchmark execution.

Review001 FAIL, Review002 PASS, Terminal Audit001 FAIL, r1 identities, and r2
identities remain preserved above. Exact-byte terminal audit is the next and
only current gate. No Git operation has been performed by this evidence
finalization.

## M2-002 Terminal Audit002

Verdict: **PASS — P0 0 / P1 0 / P2 0**.

Current status: **TERMINAL_PASS_AWAITING_GIT_FINALIZATION**. This evidence
verdict does not state or imply that commit, push, PR creation, hosted CI,
merge, or integrated verification has occurred. M2-002 completion and readiness
markers are deliberately withheld until those Git lifecycle gates finish.

Audit002 bound branch `feat/m2-002-medcpt-ps7`, HEAD
`07c548737ec351c5a2a0669078f559700ac8b9b8`, and an empty index to the exact
ordinal repo-relative path-first UTF-8 row manifest
`path<TAB>bytes<TAB>lowercase-sha256<LF>`: 12 rows, 1,224 bytes, SHA-256
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

Terminal checks established:

- Review003 persistence changed exactly the three documentation paths; all
  other nine paths in the candidate remained byte-identical;
- immutable r1 artifacts rehashed 9/9 and r2 artifacts rehashed 9/9, including
  exact source patch, source-state, and untracked-snapshot binding;
- frozen NFCorpus identity/counts were 3,633 documents, 3,237 queries, 323
  judged/evaluated queries, and 12,334 qrels;
- exact MedCPT model/cache evidence was 18 files, 877,783,608 bytes, aggregate
  SHA-256
  `64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`;
- actual runtime provenance was PyTorch intra/inter-op `1/1`, query/article
  parameters `torch.float32`, query/index embeddings `float32`, and document
  matrix memory 11,160,576 bytes measured by `numpy.ndarray.nbytes` under the
  exact matrix-only limitation;
- 2,584 per-query metric records across r1/r2 and all eight aggregate summaries
  recomputed, all 323 RRF pools reconstructed, and semantic evidence matched
  1,292/1,292; 1,289 latencies and all four build timings differed;
- dependencies reconciled 86 universal identities as 85 active plus one
  inactive, with zero vulnerabilities, exceptions, unresolved identities, or
  CUDA/NVIDIA/Triton accelerator packages; and
- validation remained bound: 54 focused tests; 1,797 full offline tests with
  two warnings and 79% coverage; Ruff; 120-file format check; MyPy over 52
  source files; 87-package lock check; and diff checks.

The terminal auditor made zero repository/evidence writes and zero network,
model, dependency/advisory, medical-source, or benchmark requests. Review001,
Review002, Terminal Audit001, Review003, r1, and r2 history remain preserved.
