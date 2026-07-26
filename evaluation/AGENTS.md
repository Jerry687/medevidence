# Evaluation Rules

These rules extend the repository-root `AGENTS.md` for evaluation datasets,
runners, raw results, metrics, and reports.

## Dataset separation

- V1 contains exactly sixty unique cases: Development-40 and a separate,
  non-overlapping Holdout-20.
- Gold-10 is the initial adjudicated subset of Development-40;
  Additional-Development-30 completes Development-40. It is not a third split.
- Keep training or construction examples, prompt-tuning/development data, and
  held-out test data separate and versioned.
- Do not inspect the held-out answers to tune prompts, retrieval parameters,
  tool routing, thresholds, or model selection.
- Do not modify prompts or system behavior based on held-out failures. Record
  the result, form a hypothesis, update on development data, then evaluate on a
  new untouched holdout or the next approved evaluation cycle.
- Record any accidental holdout exposure as contamination; do not silently
  continue reporting the score.
- Propose thresholds from Development-40 only. Approve and version thresholds,
  zero-tolerance events, datasets, prompts, routing, retrieval configuration,
  model selection, and release ID before the first Holdout-20 run.
- Run Holdout-20 only once for the declared release candidate. Any subsequent
  behavior-affecting change invalidates that final-evaluation claim and
  requires a new untouched holdout for a new claim.

## Reproducibility

Every run must archive or reference:

- dataset and relevance-judgment version;
- git commit or source snapshot;
- model, embedding, reranker, and judge names/versions;
- full prompt/template versions or hashes;
- retrieval, generation, and tool parameters;
- date/time in UTC;
- random seeds where applicable;
- environment and relevant hardware;
- raw per-example inputs, outputs, citations, traces, and errors;
- aggregate and category-level metrics.

Raw results are append-only evaluation evidence. Do not overwrite them with
summaries or only retain selected successful examples.

## Metric integrity

- Never fabricate, estimate, manually fill, or cosmetically adjust experiment
  numbers.
- Compute metrics from saved raw outputs using versioned code.
- Clearly separate measured values, derived values, estimates, and targets.
- Report denominators, excluded cases, failed cases, and missing data.
- Do not compare runs with different corpora or judgments as if they were a
  controlled experiment.
- Report regressions and uncertainty, not only improvements.
- Any number used in README, resume, interview notes, or screenshots must trace
  to a reproducible run artifact.

## LLM-as-judge

- Treat judge scores as measurements with known limitations, not ground truth.
- Never use LLM-as-a-judge as the sole scoring or ground-truth method.
- Version the judge model, rubric, prompt, and sampling settings.
- Calibrate against a human-reviewed subset.
- Check agreement and disagreement by question category.
- Preserve judge rationales when allowed, while applying redaction policy.

## Independence and leakage control

- Retrieval evaluation must run without an LLM.
- Evaluation code may invoke production components through stable interfaces,
  but production code must not import evaluation datasets or expected answers.
- Do not place held-out examples in production prompts, demos, fixtures, or
  documentation.
- Frozen source snapshots are preferred for reproducible offline scoring.
- Live-source freshness checks must be reported separately from benchmark
  scores.

## Review requirements

Before publishing a result:

1. Validate raw-result completeness.
2. Recompute aggregate metrics from raw files.
3. Confirm dataset split and contamination status.
4. Review failures and category-level slices.
5. Record configuration and environment.
6. Link every published claim to its run artifact.
