# M1B-CADEC-001 licence and provenance review 001

- Status: `PASS` — terminal Review 001 closure `P0 0 / P1 0 / P2 0`
- Work item: `M1B-CADEC-001`
- Baseline: `46c799368e9cd1ed3f2a2c956931d921999044e1`
- Reviewer: independent review batch received by the integrating agent
- Verdict: independent review closure passed; terminal evidence audit pending

## Findings

1. `P1`: annotation and locator `validate_against` paths did not closed-
   revalidate the received instance and compare equality, leaving accepted-
   instance forgery paths.
2. `P1`: the prohibited-context tuple omitted ranking, advice, dosage,
   emergency guidance, and individualized medical advice.
3. `P1`: release admission did not strongly close every document, annotation,
   and locator to the exact manifest/release, canonical member label, split,
   and parent-artifact lineage.
4. `P1`: licence identity and the conservative licence-policy booleans were not
   exact closed contract fields.
5. `P1`: controlled-vocabulary references permitted free-form metadata instead
   of only the frozen high-level layer identities, exact unstated-version text,
   reference-only legal state, and false payload-emission flags.

## Review and remediation history

The original batch remains `FAIL` with `P0 0 / P1 5 / P2 0`. Its closure
attempt identified one residual finding (`P0 0 / P1 1 / P2 0`): annotation
`controlled_vocabulary_refs` were closed as individual values but were not an
exact function of annotation layer. The residual is
`REMEDIATED_PENDING_FINAL_CLOSURE`: `original` requires no reference, `meddra`
requires exactly the closed MedDRA reference, and `sct` requires exactly the
closed SNOMED CT reference. Wrong, empty, extra, and cross-layer references
reject.

Final independent closure found `P0 0 / P1 0 / P2 0`: all five original
findings and the one residual are closed after remediation cycle 3 of 3.
Remediation adds
closed self/equality validation and forgery negatives; the exact 13-context
safety tuple; release/manifest/audit/split and parent-lineage closure with safe
canonical member labels; exact CSIRO Data Licence ID 1061 policy; and closed
MedDRA/SNOMED CT reference-only metadata. No EvidenceClaim support, request or
report execution, API/OpenAPI, loader, corpus payload, vocabulary payload,
dependency, network, M2, or CADEC-002 behavior was added.

## Closure evidence

- Independent reviewer focused plus protected OpenAPI validation: 412 passed
  (401 focused and 11 OpenAPI).
- Integrating root full offline suite: 1,546 passed with 81% coverage and two
  expected warnings.
- Integrating root rerun: 401 focused tests and 11 protected OpenAPI tests
  passed; Ruff check, Ruff format check, and MyPy were green.
- Scope audit found exactly the 17 authorized K.7 paths and no other path.
- Network and prohibited operations: none.

Writer evidence is recorded in `.delivery/M1B-CADEC-001.md`. The candidate
state is `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`. This independent
review PASS is not a terminal evidence-audit PASS and does not claim terminal
audit, completion, integration, or commit.
