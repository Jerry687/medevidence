# M2-002 transformer baseline Independent Review001

Updated: `2026-08-14`

Review001 verdict: **FAIL — P0 0 / P1 1 / P2 1**

Post-remediation disposition:
**`OWNER_DECISION_REQUIRED`**

This record preserves the independent Review001 verdict and exact findings on
the original candidate. It also records the subsequent single-batch
remediation and r1 evidence. Independent Review002 subsequently evaluated the
exact pre-persistence candidate and returned **PASS — P0 0 / P1 0 / P2 0**.

## Reviewed original candidate

Original external run directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final`

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 33,260 | `0473abe092ffc9e025338ef00bcdc599fadf98ef1aaf9d03384333ee23bfe7f1` |
| `manifest.sha256` | 80 | `20ff605ca5dafa08cea747f25957bc203c92273216a9b6712fb3eb18207022ba` |
| `source.patch` | 135,903 | `0e04309131275e2b2faebe871e0cd014e18e6d8d81a905e56fbc960cbc80bf0c` |
| `source-state.json` | 1,144 | `1d51e28446e165a22963fcba3518e2e2d2b825ad0826c9ab7798777c06a1f4f6` |
| `source-untracked-snapshot.json` | 32,574 | `ddc63783364992bb89558b7eab3d66df01383f4760584b49e86f6be9bb386de4` |

Execution HEAD: `07c548737ec351c5a2a0669078f559700ac8b9b8`

Source-state identity:
`510701d5d358d6d7c10138baba1ab3be9f47128b20f60f66469557d2791ce3d2`

Original artifact acquisition manifest: 87,888 bytes; SHA-256
`1f461bd28727cb4a7b1e52c962bf1d0bbb83ca96267e09c0fbf0f199d2b1f180`;
schema `medevidence.m2-002.medcpt-artifact-acquisition.v1`.

Original raw network ledger: 52,054 bytes; SHA-256
`48384154493b330d25b804bb089db2a22079bb961b490b71f7973bb94bd8d0f1`;
38 entries.

## Review001 findings

### P1 — adapter self-trusted non-weight and aggregate identities

`load_medcpt_artifacts` compared non-weight cache bytes only with hashes
declared by the same supplied manifest and returned the manifest's
`canonical_aggregate_identity` without recomputing it from an independent
trust root.

The executable counterexample used the then-current valid fixture to supply
arbitrary tokenizer/config bytes, `example.invalid` acquisition URLs, and
`sha256:fixture`. The adapter accepted them under the approved repository
revisions and safetensors identities. Tokenizer/config drift can change model
inputs and rankings even when weight bytes remain unchanged, so the manifest
could not establish the claimed exact artifact identity.

Required closure was an independent hard binding of all 18 approved cache
files plus acquisition identities, local recomputation and validation of the
ordered canonical aggregate, and executable negative coverage for non-weight,
aggregate, blob, and URL drift.

### P2 — raw model-metadata acquisition lineage was incomplete

The preserved query metadata was 2,943 bytes with SHA-256
`6ead632a25d705d455ab3f85cfd517a9551f5ae99191a3e1094262310a80e9cd`;
the article metadata was 2,855 bytes with SHA-256
`5d71f6b956e598e431eed3a7b12a913122e57c968d4b4b0ac13004b8df8ec8f0`.
Neither raw metadata item had durable request URL/timestamp evidence, and
neither acquisition appeared in the original 38-entry ledger.

Required closure was successor evidence with exact, bounded authoritative
metadata requests; UTC timestamps; request/final URLs; response status,
bytes, and hashes; equality with preserved raw metadata; and exact raw-ledger
entry binding. Any failed or non-authoritative probe had to remain visible.

## Positive Review001 evidence

Review001 independently established that the original benchmark result files
were internally recomputable despite the two trust-boundary findings:

- all 1,292 per-query records across four modes recomputed exactly;
- all four aggregate summaries recomputed exactly;
- all 323 RRF top-ten rankings reconstructed exactly;
- frozen NFCorpus archive, corpus, query, and qrel identities matched;
- dataset counts and judgment histogram matched;
- CPU, serial execution, concurrency one, and one-thread controls matched;
- dependency evidence and CPU torch binding matched; and
- M2-001 historical scope and evidence remained preserved.

These positive checks did not override the P1/P2 trust-boundary defects. The
original run remains historical pre-remediation evidence only.

## Single-batch remediation

The Owner authorized one batched remediation covering both findings.

Successor acquisition evidence:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `medcpt-artifact-acquisition-r1.json` | 94,242 | `5943ceda5c8f3792af473a737099a6954fb30aaf62c1ec1334315305915f6755` |
| `network-ledger-r1.raw.json` | 56,755 | `a7b66388278e29f88b1602faffb6a195d3f1bd96f1769a2187394bb6193c97e5` |

The v1r1 manifest retains the same two repositories, immutable revisions, 18
cache files, 877,783,608 total bytes, and canonical aggregate SHA-256
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`.

The r1 ledger transparently records:

- index 38: a non-authoritative parameterless query-metadata probe whose
  1,991-byte response, SHA-256
  `3e7f355e4c3b7e1a524d343080ce934ebd53584b81e70efb717d99f8851b9e7c`,
  did not match the preserved raw metadata;
- index 39: the authoritative query `?blobs=true` metadata GET with exact UTC,
  URL, status 200, 2,943 bytes, SHA-256
  `6ead632a25d705d455ab3f85cfd517a9551f5ae99191a3e1094262310a80e9cd`,
  and preserved equality;
  and
- index 40: the authoritative article `?blobs=true` metadata GET with exact
  UTC, URL, status 200, 2,855 bytes, SHA-256
  `5d71f6b956e598e431eed3a7b12a913122e57c968d4b4b0ac13004b8df8ec8f0`,
  and preserved equality.

The remediated adapter:

- requires the exact v1r1 manifest and successor ledger identities;
- independently pins all 18 path, byte, SHA-256, blob, requested/final URL,
  etag, and LFS identities;
- recomputes and validates the ordered canonical aggregate;
- validates the raw metadata, v1 supersession, failed probe, authoritative
  requests, and exact ledger indexes; and
- rejects the old v1 manifest.

Executable negatives cover config, tokenizer, README, aggregate, blob,
requested URL, final URL, repository metadata, metadata lineage, successor
ledger, prohibited `.bin`, unlisted file, and old-v1 drift.

## Fresh remediation evidence

- focused adapter tests: `17 passed`;
- broader evaluation tests: `111 passed`;
- full offline unit/contract suite: `1,793 passed`, two expected warnings,
  79% coverage;
- Ruff check: PASS;
- Ruff formatting: `120 files already formatted`;
- strict MyPy: `52` source files, PASS;
- `uv lock --check`: `87` packages, PASS; and
- diff checks: PASS.

The fresh r1 benchmark execution completed in 2,468.6 seconds. Quality metrics
match the historical run exactly; all latency and build timings are fresh r1
measurements.

## Exact r1 candidate reviewed by Review002

External run directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r1`

| Artifact | Bytes | SHA-256 |
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

R1 execution HEAD: `07c548737ec351c5a2a0669078f559700ac8b9b8`

R1 source-state identity:
`a719bcd8e47d6538c7c187dac46cc79f002dea493fe285a9597191947e8c9862`

## Independent Review002 closure review

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

The reviewer confirmed the successor v1r1 acquisition manifest and r1 ledger,
the exact 18-file cache and recomputed aggregate, transparent ledger index 38,
authoritative UTC `?blobs=true` metadata GETs at indexes 39 and 40 with exact
preserved-byte equality, and fail-closed rejection of old v1 and all tested
identity mutations. All nine r1 artifacts rehashed exactly; source-state
identity, patch, and snapshot matched.

The reviewer independently recomputed all 1,292 per-query records and four
summaries and reconstructed all 323 RRF top-ten rankings and candidate pools.
Quality and rankings equal the historical run exactly; timestamps, builds, and
all timings are fresh, with 1,290 of 1,292 query latencies differing. The frozen
dataset was 3,633 documents, 3,237 queries, 323 judged queries, 12,334 judgments,
and a grade histogram of 11,758 plus 576. All ten thread observations were one.

The dependency review bound the 28,196-byte manifest SHA-256
`a0835993f71d45df80292c8eea8d14f8bce2fe922cff294df7c5c42eafd74c7c`:
86 packages were reconciled as 85 active plus one inactive; advisory inventory
was 84 pip packages plus one OSV-only and one inactive package, with zero
vulnerabilities, skips, exceptions, or unresolved identities. All eight M2-001
artifacts and the documentation boundaries also matched.

Review002 verdict: **PASS — P0 0 / P1 0 / P2 0**. Because persisting this result
changed three paths in the reviewed prefix, M2-002 Terminal Audit001 evaluated
the resulting post-persistence candidate below.

## M2-002 Terminal Audit001

Terminal Audit001 verdict: **FAIL — P0 0 / P1 0 / P2 1**. The audited exact
current pre-persistence candidate is the UTF-8, LF-terminated concatenation in
canonical path-first ordinal order, with each line formatted
`path<TAB>bytes<TAB>lowercase-sha256<LF>`: 1,224 bytes, SHA-256
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

The P2 finding is that the r1 manifest lacks persisted observed actual torch
intra-op and inter-op thread counts, embedding/model dtype, and index memory.
The implementation requests one thread and float32, but it does not persist the
observed actual runtime values. Index memory is practically measurable as
`3633 * 768 * 4 = 11,160,576` bytes.

The audit confirmed metrics and rankings remain correct. No remediation was
performed because the single authorized remediation batch is exhausted at 1/1.
The Owner must choose whether to authorize a new remediation and fresh benchmark
that persist observed runtime values, or close the work item without terminal
acceptance. This record makes no terminal acceptance, readiness, release, or
superiority determination.

No Git operation is authorized or recorded by this evidence-only
finalization. No benchmark or network request is rerun by this documentation
step.

## R2 candidate submitted for fresh independent review

Submission status before Review003: **AWAITING_INDEPENDENT_REVIEW**. This is a candidate-evidence binding,
not a review verdict. Review001 FAIL, Review002 PASS, Terminal Audit001 FAIL,
and the immutable r1 evidence remain historical records exactly as stated
above. No terminal PASS, completion, readiness, release, or superiority claim
is made here.

R2 directory:
`D:\Projects\medevidence-m2-002-benchmark-results\nfcorpus-medcpt-real-final-r2`

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

The r2 manifest records observed actual PyTorch intra-op/inter-op counts `1/1`;
query and article parameter dtype `torch.float32`; query and document
embedding/index dtype `float32`; and exact document embedding matrix memory
`11,160,576` bytes measured by `numpy.ndarray.nbytes`. The definition is
limited to the matrix and explicitly excludes process RSS, allocator overhead,
model memory, and total application memory.

| Mode | Recall@10 | nDCG@10 | MRR@10 | Mean latency/query (ms) | P50 (ms) | P95 (ms) | Build/index seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.14641067054843881 | 0.3055754029503277 | 0.5068381738660377 | 0.8319074299453899 | 0.2597999991849065 | 2.846459997817872 | 0.2409466999961296 measured |
| Classical LSI dense | 0.15286419137082669 | 0.2993301171081958 | 0.4660278146346258 | 13.868896284577835 | 13.751399994362146 | 14.182479989540296 | 2.2162746000103652 measured |
| MedCPT dense | 0.1827810170966193 | 0.3674126109143263 | 0.5487689812767212 | 30.03730216757726 | 28.166100004455075 | 36.38049000437603 | 2497.3564415 measured |
| RRF(BM25, MedCPT) | 0.1810206378195796 | 0.3649385324032572 | 0.5698289842252691 | 30.629491949801395 | 28.79150000808295 | 39.83871000964427 | 2497.597388199996 derived sum |

All four quality summaries equal r1 exactly. The recorded semantic comparison
matched 1,292/1,292 records across query/mode identity, rankings, scores,
candidate evidence, metrics, and component evidence; 9/9 r1 artifacts rehashed
unchanged. Fresh timing is retained as r2 machine-local evidence.

Candidate validation evidence is 54 focused tests; 1,797 full offline tests,
two expected warnings and 79% coverage; Ruff; format over 120 files; MyPy over
52 source files; `uv lock` over 87 packages; and diff checks, all PASS. The
exact pre-documentation candidate canonical ordinal path-first UTF-8/LF
identity was 12 rows, 1,224 bytes, SHA-256
`1f85f3dabfed3dd01346e0c75cd740cfa4218dd42d46df058a123437748f96fa`.

This candidate used only frozen local dataset/model/dependency artifacts. No
model reacquisition, Hugging Face request, dependency/advisory request,
medical-source request, Git operation, or second r2 run occurred. A fresh
independent review must evaluate these exact bytes before any terminal audit or
acceptance claim.

## M2-002 Independent Review003 — r2 provenance remediation

Verdict: **PASS — P0 0 / P1 0 / P2 0**.

Status before Terminal Audit002: **AWAITING_TERMINAL_AUDIT**. This review is not a
terminal audit and makes no completion, readiness, commit, merge, release, or
superiority claim. Review001 FAIL, Review002 PASS, Terminal Audit001 FAIL, and
all recorded r1/r2 identities remain immutable history.

Review003 was bound to the ordinal repository-relative path manifest with
UTF-8 rows formatted `path<TAB>bytes<TAB>lowercase-sha256<LF>`. The exact
reviewed identity was 12 rows, 1,224 bytes, SHA-256
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

The reviewer rehashed immutable r1 9/9 and r2 9/9; independently recomputed
the 1,292 per-query metric records; reconstructed all 323 RRF pools/rankings;
and found r1/r2 semantic evidence equal 1,292/1,292. Exactly 1,289 query
latencies and every build timing differed, confirming timing was fresh rather
than copied. Frozen dataset/qrels, exact model revisions and 18 cache files,
dependencies, configuration, and Git baseline were unchanged.

Runtime provenance matched the manifest: PyTorch intra/inter-op `1/1`;
query/article parameter dtype `torch.float32`; query and document embedding
index dtype `float32`; and 11,160,576 document-matrix bytes measured by
`numpy.ndarray.nbytes`, explicitly excluding process RSS, allocator overhead,
model memory, and total application memory. Safetensors inspection reported F32
tensors. The code change was provenance-only, did not hard-code the expected
matrix byte value, and failed before artifact creation when required runtime
evidence was unavailable.

Review003 performed no write, network request, model acquisition, dependency
or advisory audit, medical-source access, or benchmark execution. The exact
post-persistence bytes require terminal audit before any acceptance claim.

## M2-002 Terminal Audit002

Terminal verdict: **PASS — P0 0 / P1 0 / P2 0**.

Current work-item status: **TERMINAL_PASS_AWAITING_GIT_FINALIZATION**. No commit,
push, PR, hosted CI, merge, or integrated verification is claimed. Completion
and readiness markers remain withheld.

The audit bound branch `feat/m2-002-medcpt-ps7`, HEAD
`07c548737ec351c5a2a0669078f559700ac8b9b8`, and an empty index to the exact
ordinal repo-relative path-first UTF-8/LF candidate: 12 rows, 1,224 bytes,
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

Audit002 verified the Review003 persistence delta was exactly three docs with
the other nine candidate paths unchanged; r1 and r2 rehashed 9/9; source
binding was exact; dataset counts were 3,633/3,237/323/12,334; and the model
cache was 18 files, 877,783,608 bytes, aggregate SHA-256
`64f7094f2b7384d17219200436990aaceb1a321e00578f5f576c6546f2d42d2a`.

Runtime provenance was exactly intra/inter-op `1/1`, parameter dtype
`torch.float32`, query/index dtype `float32`, and 11,160,576 matrix bytes via
`numpy.ndarray.nbytes` with the exact limitation. Across r1/r2, 2,584 per-query
metric records and eight summaries recomputed; 323 RRF pools reconstructed;
semantics matched 1,292/1,292; and 1,289 latencies plus all four builds differed.
Dependencies reconciled 86 = 85 active + 1 inactive with zero vulnerabilities,
exceptions, unresolved identities, or accelerator packages. The 54 focused,
1,797 full offline/two-warning/79%-coverage, Ruff, format 120, MyPy 52, lock 87,
and diff evidence remained passing and bound.

The terminal audit itself made zero writes and zero network or benchmark
requests. Exact-byte Git finalization remains pending.

## CI-only dependency-audit remediation submitted for fresh review

Current status: **CI_DELTA_AWAITING_INDEPENDENT_REVIEW**. This submission does
not amend or supersede immutable Review003 PASS 0/0/0, Terminal Audit002 PASS
0/0/0, r1, r2, or any of the 1,292 ranking/metric records. It records no new
review verdict, terminal acceptance, completion, readiness, merge, or
integrated verification.

The accepted candidate commit
`719e2ad1f424b0085b151cef6a634d17ef02d799` is on Draft PR #26. Its first
hosted checks were `compose-config` PASS in 42 seconds, `windows-quality` PASS
in 2 minutes 24 seconds, and `dependency-audit` FAIL in 1 minute 39 seconds.
The failure was the exact expected `torch==2.13.0+cpu` pip-audit skip with no
OSV paths supplied by the workflow, not a benchmark, metric, model, dataset, or
reported-vulnerability defect. The Owner authorized only this CI closure.

The exact pre-documentation implementation/test delta submitted for review is:

```text
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

The production validator remains byte-identical:
`scripts/dependency-audit.ps1`, 87,126 bytes, SHA-256
`f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70`.
The workflow uses one shared PR/push path, exactly one pip-audit, exactly one
direct no-retry/nonredirecting OSV POST, external `RUNNER_TEMP` evidence,
strict fail-before-OSV handling for malformed/vulnerable/non-exact-skip pip
evidence, exact Windows amd64 CPU Torch binding, and all three existing
preserved-evidence parameters.

Local evidence is 93 focused tests plus Ruff, format over 120 files, MyPy over
52 source files, 87-package lock validation, and diff checks, all PASS. The
single mechanical retry addressed formatting/UTC lint only. The CI remediation
made no local network request, model load/acquisition, NFCorpus execution,
medical-source access, benchmark rerun, or Git operation. Fresh independent
review must bind the final five-path candidate before terminal re-audit.

## M2-002 CI Delta Review004

Verdict: **PASS — P0 0 / P1 0 / P2 0**.

Current status: **CI_DELTA_REVIEW_PASS_AWAITING_TERMINAL_AUDIT**. This verdict
is limited to the Owner-authorized CI-only remediation. It does not reopen or
alter r1, r2, Review003, Terminal Audit002, dependency policy, or benchmark
semantics, and it makes no completion, readiness, merge, release, or integrated
verification claim.

Review004 bound branch `feat/m2-002-medcpt-ps7`, HEAD
`719e2ad1f424b0085b151cef6a634d17ef02d799`, and an empty index to the exact
ordinal repository-relative path-first UTF-8/LF manifest: 5 rows, 564 bytes,
SHA-256
`789f9877a19f9cb1d9ba01e4a01f96dce53d7ffaa09d49de0263db9dbb7a8b2c`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	31897	9ff8f0459fee1a2effcfad53cacbdb69fe6585431fe32b5a8181d50d3368ef2f
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	25760	49df739ef86c6667c576c8fdcdfc1fa521c918b1c64f96c56491bfad66f8445a
evaluation/README.md	24400	b54017c62d4f2278061761bcfb421fc022ce48925c641917668dfdcebd77c863
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

The reviewer verified that PR and post-merge main execute one shared workflow
path; raw pip-audit evidence remains retained externally; malformed,
vulnerable, or non-exact-skip evidence fails before OSV; and the workflow makes
one exact direct POST without redirect following or retry. Installed
`torch==2.13.0+cpu`, the explicit CPU index, lock marker, Windows amd64 wheel,
and exact wheel SHA remain bound before fallback acquisition. All three
preserved-evidence parameters reach the unchanged production validator, which
independently proves the 84 pip-audit pass + 1 exact OSV fallback + 1 inactive
identity reconciliation.

The focused tests exercise the extracted workflow program with synthetic
subprocess and HTTPS boundaries, validate accepted evidence through the
unchanged production validator, and cover relevant fail-closed cases. The
delivery and evaluation evidence distinguish historical hosted failure,
Owner-authorized closure, review status, and remaining terminal/hosted gates
truthfully. Review004 itself performed zero repository/evidence writes, network
requests, tests, model operations, or benchmark execution. This persistence is
evidence-only and requires final-byte rebind plus terminal audit.

## M2-002 CI Delta Terminal Audit003

Verdict: **PASS — P0 0 / P1 0 / P2 0**.

Current status: **CI_DELTA_TERMINAL_PASS_AWAITING_HOSTED_CI**. This terminal
decision accepts only the exact CI-remediation repository candidate. It
preserves all earlier evidence and makes no Ready, merge, post-merge,
integrated-completion, or final readiness claim.

Audit003 bound branch `feat/m2-002-medcpt-ps7`, HEAD
`719e2ad1f424b0085b151cef6a634d17ef02d799`, and an empty index to the exact
ordinal repository-relative path-first UTF-8/LF manifest: 5 paths, 564 bytes,
SHA-256
`f0daf3a5a9a5944ac83790357ad98eb75546f2e1d1365d1128af46b266d4c02d`.

```text
.delivery/M2-002-TRANSFORMER-BASELINE.md	33870	166bdf79d32f4951f0f3fa60ea515883d6657500eca628be40ab8d0ac7ca72bb
.github/workflows/dependency-audit.yml	20572	0a258f941887c0323b1d29673fdd894c34db605fe7170d5e0feae0384562b0a2
docs/reviews/M2-002-TRANSFORMER-BASELINE-INDEPENDENT-REVIEW-001.md	28252	9892856bbd70199bf81df7668d3d7e7350d7f4addc4a6f89a4595845c8d89221
evaluation/README.md	26019	ec51aff3b51da689390b7f2625118c36d065cfbd92219d633554a81dd23bf9c6
tests/unit/test_dependency_boundaries.py	42155	43c5ffa413d4b48468194eb4b5309bc9f25b2a5064ee0f5a71fafce71cacf2e1
```

The terminal auditor proved exact scope, exact workflow/test equality with
Review004, and exact three-document Review004 prefixes before persistence. The
production audit script was outside the delta and remained 87,126 bytes with
SHA-256
`f811e80fd12ebe7d416d3d70677b87564323bd4e43dc18a5a88e769d4645bf70`.

The audited workflow has one common PR/main path, retains raw pip-audit bytes,
rejects malformed/vulnerable/non-exact-skip evidence before OSV, and performs
one exact direct POST without redirect or retry. It enforces 10-second connect,
30-second read, and 1,048,576-byte response bounds; proves the exact installed
CPU Torch, lock, source, marker, Windows amd64 wheel, and hash; emits the exact
acquisition schema; and supplies all three preserved paths. The unchanged
validator independently proves the 84 pip-audit pass + 1 exact OSV fallback +
1 inactive identity = 86 reconciliation.

Immutable r1 and r2 rehashed 9/9 each. UTF-8/LF and diff checks passed, and the
accepted 93 focused, Ruff, format 120, MyPy 52, and lock 87 evidence remained
bound. Audit003 itself executed no writes, network request, test, model load,
or benchmark. This three-document persistence is evidence-only; hosted PR CI
must independently exercise the accepted candidate next.
