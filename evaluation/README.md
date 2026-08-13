# M2 retrieval evaluation

Compares the four `EVALUATION_PLAN` section 6.1 baselines over one frozen
corpus and writes every raw artifact section 6.3 requires.

**Nothing here is an approved configuration.** Decision gate `ME-000C`
(tokenizer, sparse encoding, BM25 `k1`/`b`, embedding, reranker, limits) is
open. Every value is an experiment parameter, recorded with each run so a
figure can never be reported without the configuration that produced it.

## Running

Single-file fixture (harness smoke, no external data required):

```bash
python -m evaluation.run_evaluation \
  --jsonl tests/fixtures/retrieval/harness_smoke.json
```

BEIR-layout dataset:

```bash
python -m evaluation.run_evaluation --beir data/nfcorpus --split test
```

Useful flags: `--max-documents` (fast smoke; records a truncation warning),
`--dimensions`, `--rrf-k`, `--bm25-k1`, `--bm25-b`, `--candidate-limit`,
`--final-limit`, `--grade-min`, `--modes`.

## Getting a real dataset

The sandbox this was built in reaches PyPI only, so no benchmark could be
downloaded here. On a machine with normal network access:

1. Download a BEIR dataset, for example NFCorpus (~3.6k biomedical documents,
   323 test queries, published graded judgments) from the BEIR distribution.
2. Unzip so that `data/nfcorpus/` contains `corpus.jsonl`, `queries.jsonl`,
   and `qrels/test.tsv`.
3. Run the BEIR command above.

NFCorpus is a reasonable first choice because it is biomedical, small enough
to index in seconds, and its published numbers give an external reference for
whether this harness is behaving sensibly.

## Layout

```text
evaluation/
  datasets.py        strict loaders; BEIR layout and single-file fixtures
  metrics.py         Recall@k, Precision@k, MRR@k, nDCG@k, percentiles
  harness.py         builds indexes, runs baselines, writes raw artifacts
  run_evaluation.py  CLI
  results/           run-<timestamp>/ output (git-ignored)
```

Ranking arithmetic lives in `src/medevidence/retrieval/core.py` and is free of
project and vendor imports. `src/medevidence/retrieval/contracts.py` holds the
source-neutral Pydantic contracts that bind retrieval to the domain layer.

## Output

Each run writes `results/run-<UTC timestamp>/`:

- `manifest.json` — dataset summary, grade histogram, corpus content hash,
  full config plus its `config_id`, environment, index build times, per-mode
  summaries, and an explicit approval-status disclaimer;
- `per-query-<mode>.jsonl` — one record per query with the ranked ids, final
  scores, per-component scores and ranks, latency, and computed metrics.

Per-query records are sufficient to recompute every summary figure, which is
asserted by a contract test.

## Metric definitions

TREC/BEIR conventions, so numbers are comparable to published results:

- `DCG@k = Σ (2^rel_i − 1) / log2(i + 1)`, 1-based positions;
- `nDCG@k = DCG@k / IDCG@k`, `0.0` when no positive grade exists;
- `Recall@k` divides by *all* judged-relevant documents;
- `MRR@k` is `0.0` when nothing relevant appears in the top `k`.

Grade semantics (`0/1/2`) belong to the adjudication guide. `--grade-min`
controls what counts as relevant for the binary metrics; the plan's "directly
relevant" wording may map to grade `2` once `M2-ADJUDICATION` designates an
adjudicator.

## Current limitations

- **Dense retrieval is TF-IDF + truncated SVD (classical LSI), not a
  transformer embedding.** It requires no model download, so the comparison is
  reproducible offline. It must not be reported as a transformer baseline.
  `EmbeddingBackend` exists so a transformer backend can be substituted without
  changing any caller.
- **The reranker baseline (mode 4) is not implemented.** It needs a model and
  therefore an `ME-000C` decision.
- **No adjudicated dataset exists.** `harness_smoke.json` is synthetic, its
  grades were assigned by construction rather than by medical adjudication, and
  metrics over it validate the harness only. Gold-10 / Development-40 /
  Holdout-20 remain unbuilt and gated on `M2-ADJUDICATION`.
- **No release threshold is proposed.** Thresholds may only come from
  Development-40 and must be approved and versioned before the first Holdout-20
  run.
