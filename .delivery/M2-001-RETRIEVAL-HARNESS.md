# M2-001 retrieval baseline harness — delivery record

Updated: `2026-08-13`

Status: **`IMPLEMENTED_AND_OFFLINE_VERIFIED`; `NO_ADJUDICATED_DATASET`;
`NO_MEASURED_RETRIEVAL_CLAIM`; `ME-000C_STILL_OPEN`**

Branch: `feat/m2-retrieval-eval`
Baseline: `main` at `46c7993`

## 1. What this delivers

The machinery for `EVALUATION_PLAN` section 6: three retrieval baselines over
one frozen corpus, the metric set of section 6.3, the controlled variables of
section 6.2, and the raw-artifact retention that section 6.3 and `V1-NFR-008`
require.

It does **not** deliver retrieval-quality numbers. See section 5.

## 2. Files

| Path | Purpose | Lines |
|---|---|---:|
| `src/medevidence/retrieval/core.py` | tokenizer, BM25, dense LSI, RRF — no project or vendor imports | 268 |
| `src/medevidence/retrieval/contracts.py` | source-neutral Pydantic contracts binding retrieval to the domain | 197 |
| `evaluation/metrics.py` | Recall@k, Precision@k, MRR@k, nDCG@k, percentiles | 176 |
| `evaluation/datasets.py` | strict BEIR-layout and single-file loaders | 226 |
| `evaluation/harness.py` | index construction, baseline execution, artifact writing | 258 |
| `evaluation/run_evaluation.py` | CLI | 116 |
| `evaluation/README.md` | usage, definitions, limitations | — |
| `tests/fixtures/retrieval/harness_smoke.json` | 30-doc synthetic fixture, 8 queries, 31 positive grades | — |
| `tests/unit/retrieval/test_core.py` | 24 tests | — |
| `tests/unit/evaluation/test_metrics.py` | 23 tests | — |
| `tests/unit/evaluation/test_datasets.py` | 15 tests | — |
| `tests/contract/evaluation/test_harness.py` | 17 tests | — |
| `tests/conftest.py` | makes `evaluation` importable; falls back to `src` only if needed | — |

## 3. Design decisions and why

**Numerics separated from contracts.** All ranking arithmetic is in `core.py`,
which imports nothing from the project. `contracts.py` holds the Pydantic
layer. This keeps the arithmetic directly testable, and it is why the core
could be executed and verified in an environment where the 3.12-only domain
layer cannot even be imported (section 6).

**No vendor object crosses the boundary.** There is no Qdrant client. The
indexes are in-memory behind the same interface a Qdrant backend would satisfy,
which discharges the "results do not leak Qdrant-native objects" acceptance
criterion by construction rather than by inspection, and avoids depending on
`ME-000C`'s Qdrant version question.

**Dense retrieval is TF-IDF + truncated SVD (classical LSI).** The sandbox
could reach PyPI only; no transformer weights were obtainable. LSI is a genuine
dense vector method requiring no download, so the comparison is reproducible
offline. It is labelled as LSI everywhere and must not be reported as a
transformer baseline. `EmbeddingBackend` is a protocol, so a transformer
backend substitutes without any caller change.

**RRF fuses on rank, not score.** BM25 scores and cosine similarities have
incomparable scales; rank fusion avoids inventing a normalization.

**Ties break on document id** in every ranking path, so repeated runs over the
same corpus produce byte-identical orderings.

**Loaders fail closed.** Duplicate ids, malformed JSON, non-integer grades, and
judgments referencing absent documents all raise. A silently shrunk qrel set
inflates every metric, so silence is the dangerous behaviour.

**Corpus truncation is never silent.** `--max-documents` keeps all judged
documents and records a warning that propagates into the run manifest.

## 4. Verification performed

| Check | Result |
|---|---|
| Unit and contract tests, sockets disabled | **79 passed** |
| Metric correctness | nDCG, DCG, Recall, Precision, MRR and percentiles checked against hand-computed values in the test suite and independently at the console |
| Determinism | repeated runs produce identical rankings; asserted by contract test |
| Config sensitivity | `config_id` stable across equal configs, differs when `rrf_k` changes |
| Raw-artifact completeness | manifest carries config, `config_id`, corpus content hash, dataset summary, grade histogram, environment, per-mode summaries, approval disclaimer |
| Recomputability | a contract test recomputes `ndcg@10` from the saved per-query record and matches the reported value |
| Ruff lint | passed |
| Ruff format | passed, 13 files |
| End-to-end CLI | runs three baselines over the fixture and writes artifacts |

Fixture run output (harness validation only, **not** a quality claim):

```text
mode          recall@5   recall@10      mrr@10     ndcg@10
sparse          0.7458      0.8958      1.0000      0.9350
dense           0.7708      0.9583      1.0000      0.9489
hybrid_rrf      0.7458      0.9583      1.0000      0.9446
```

These numbers are high because the fixture is 30 documents with grades assigned
by construction. They demonstrate that the pipeline runs end to end and that
the three modes produce differing, plausible orderings. They say nothing about
retrieval quality.

## 5. What is deliberately absent

- **No adjudicated dataset.** Gold-10, Development-40 and Holdout-20 do not
  exist. `M2-ADJUDICATION` has not designated a medical or pharmacovigilance
  adjudicator, and this work did not invent relevance judgments — the same
  restraint the packet applied when it left `GI_PT_SET_M1B_V1` empty.
- **No reranker baseline.** Mode 4 needs a model and therefore `ME-000C`.
- **No release threshold.** Thresholds may only be proposed from
  Development-40 and must be approved and versioned before any Holdout-20 run.
- **No transformer embedding**, for the network reason in section 3.
- **No project corpus.** M1 retrieved one publication live; chunking of stored
  records into a corpus is not implemented, so the harness currently consumes
  external datasets rather than the project's own store.

## 6. Environment limitation affecting verification

The build environment runs Python 3.10 and reaches PyPI only. The repository
targets Python 3.12.13 and uses `StrEnum` and PEP 695 `type` aliases, and its
checked-in `.venv` is a Windows virtual environment.

Consequences:

- `core.py`, `metrics.py`, `datasets.py`, `harness.py`, `run_evaluation.py` and
  all tests were executed and pass, because they avoid 3.12-only syntax;
- `contracts.py` was **not executed**. It was parsed and linted by Ruff with
  `target-version = py312`, so its syntax and style are verified, but it has no
  runtime or `mypy` coverage yet;
- `mypy --strict` was not run at all.

**Required before merge:** run the authoritative four-command gate on a 3.12
environment. `contracts.py` is the file most likely to need correction.

## 7. Getting real numbers

One manual step, on a machine with normal network access:

1. Download a BEIR dataset — NFCorpus is recommended first: biomedical, ~3.6k
   documents, 323 test queries, published graded judgments, indexes in seconds.
2. Unzip to `data/nfcorpus/` containing `corpus.jsonl`, `queries.jsonl`,
   `qrels/test.tsv`.
3. `python -m evaluation.run_evaluation --beir data/nfcorpus --split test`

Published NFCorpus results give an external reference for whether the harness
behaves sensibly. That comparison is the first genuine evidence this project
would hold about retrieval, and it does not require any open decision gate,
because a public benchmark with published judgments needs no adjudicator.

## 8. Standing limitation

Implementation and verification were performed by one actor. Every check in
section 4 is mechanically reproducible from the committed tests. No independent
review has occurred.
