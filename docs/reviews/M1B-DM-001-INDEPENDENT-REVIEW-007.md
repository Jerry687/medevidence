# M1B-DM-001 Independent Review 007

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

The finding is the same Owner-authorized security P1-01 class: the frozen
DailyMed trust policy must be non-weakenable at every accepted construction
boundary. Mechanical remediation is in progress. This verdict does not
authorize PASS, terminal audit, or any Git/integration lifecycle step.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Exact candidate manifest:
  `9a1ad8c2d2850c2b5ffcff67d5e19017beee740eb183c6b222270d1bdee258ca`
- Medical-source and other network requests: none
- Git mutations, dependency changes, schema changes, and DM-002 work: none

Independent Reviews 001–006 remain immutable historical evidence.

## Verified prior closures

Review 007 verified the post-Review 006 global uniqueness closure for
`acquisition_id`, `snapshot_id`, and `source_outcome_id`, including preservation
of valid `acquisition_intent_id` reuse. Representative direct drift attempts on
the other frozen security-policy models rejected. The complete parent
DailyMed trust policy also rejected the malformed path rows below.

## P1-01 — Exported trust-path row is independently weakenable

The publicly exported `DailyMedTrustPath` can be constructed directly with
`model_validate` even when its row is not one of the six frozen connector trust
rows. The following standalone mutations were accepted:

```text
path_template=/unfrozen/evil purpose=arbitrary mode=none ACCEPTED
discovery allowed_query_keys=('url',) ACCEPTED
getFile exact_query=(('type', 'pdf'),) ACCEPTED
```

The enclosing parent policy rejects these rows, but parent validation does not
close a separately exported model's own accepted construction boundary. This
violates the frozen requirement that callers and accepted internal boundaries
cannot supply altered host/path/query trust tuples.

Acceptance criteria:

1. Standalone `DailyMedTrustPath` validation must accept exactly one of the six
   frozen path/purpose/query rows.
2. Add direct negatives for arbitrary path, arbitrary purpose, query-key drift,
   exact-query drift, omission, duplication, and reordering.
3. Preserve the parent policy's exact frozen-row validation and all positive
   construction paths.
4. Do not change the six frozen rows, add a dependency, authorize network I/O,
   or expand schema/public concepts.

## Validation evidence

```text
Focused standalone trust-path reproducer: 14 passed
Focused security-policy gate: 53 passed
Four-domain gate: 323 passed
Reports, source outcomes, and byte-exact OpenAPI gate: 273 passed
Full unit/contract suite: 939 passed, 2 expected warnings, 80% coverage
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion. Green parent-policy and suite results do not override
the reproduced standalone exported-model counterexamples.

## Lifecycle result

Review 007 is `FAIL`. Same Owner-authorized security P1-01 remediation is in
progress. Fresh Review 008 and terminal evidence audit remain pending. Do not
claim PASS or perform commit, push, PR, CI, ready transition, merge,
integration, network execution, or `M1B-DM-002`.
