# ADR-002: Preserve source semantics

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

PubMed literature, DailyMed labeling, FAERS spontaneous reports, and CADEC
patient-authored annotations answer different questions and cannot be treated
as equal-strength observations.

## Decision

V1 uses these classifications:

- PubMed: scientific literature evidence;
- DailyMed: official labeling evidence;
- FAERS/openFDA: descriptive spontaneous-report data;
- CADEC: auxiliary NLP/retrieval corpus.

CADEC cannot support risk ranking, incidence, causal, regulatory, or clinical
conclusions. FAERS cannot produce incidence, causality, relative risk, signal
metrics, or product safety ranking. Cross-source consistency/conflict requires
an explicit comparability assessment and cannot use majority voting.

Source classification and mandatory limitations are structured domain fields
and deterministic validation rules, not optional generation instructions.

## Alternatives considered

- Put all records into one evidence collection with a common score.
- Allow the model to infer appropriate source weight.
- Exclude FAERS and CADEC entirely.

## Consequences

- Reports remain scientifically interpretable and source-aware.
- Source-specific models, fields, tests, and UI labels are required.
- FAERS can demonstrate structured tool use without overstating meaning.
- CADEC retains portfolio value for biomedical NLP without contaminating risk
  conclusions.

## Validation

- Source-semantic contract tests enforce allowed claim types.
- FAERS and CADEC adversarial cases cannot cross prohibited boundaries.
- Reports visually and structurally separate the four source classes.

## Supersedes / Superseded by

None.
