# ADR-006: Evaluation split and reproducibility

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

A large evaluation set is not useful if annotation rules are ambiguous, the
held-out set is used for tuning, or published metrics cannot be recomputed from
raw results.

## Decision

V1 evaluation proceeds in stages:

1. Gold-10, the initial adjudicated subset of Development-40;
2. Additional-Development-30, completing forty unique development cases;
3. twenty separate, non-overlapping untouched held-out cases.

V1 therefore has sixty unique cases, not seventy.

Annotation guidance is frozen before Gold-10 for relevance, material claims,
citation spans, comparability/conflict, partial answers, and refusals.

The held-out set cannot tune prompts, examples, routing, retrieval/fusion/
reranking parameters, normalization rules, thresholds, or model selection.
Exposure is recorded as contamination.

Every run preserves dataset/split, source snapshots, configuration, models,
prompts, parameters, date, code revision, environment, raw per-item outputs,
rankings, claims, citations, traces, errors, and judgments. Raw results are
append-only. LLM-as-a-judge may assist but cannot be the only scoring method.

Release thresholds are proposed from Development-40 only and approved/versioned
before Holdout-20. Holdout-20 runs once for the declared release candidate.
Post-holdout changes create a new candidate, invalidate the previous final
evaluation claim, and require a new untouched holdout.

## Alternatives considered

- Create one undivided one-hundred-question set.
- Tune repeatedly on the held-out set.
- Retain only aggregate metric tables.
- Use an LLM judge as ground truth.

## Consequences

- The initial public dataset is smaller but more defensible.
- Metric and annotation defects are found before expensive expansion.
- Formal claims require an untouched holdout or a documented replacement.
- Human adjudication capacity is a release dependency.

## Validation

- Dataset files and run artifacts identify split and contamination status.
- Known-answer tests validate metric implementations.
- Published metrics recompute from raw results.
- No held-out example appears in prompts, fixtures, demos, or tuning logs.

## Supersedes / Superseded by

None.
