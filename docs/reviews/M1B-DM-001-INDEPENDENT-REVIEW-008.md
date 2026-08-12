# M1B-DM-001 Independent Review 008

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

Both findings are mechanical manifestations of already Owner-frozen
non-weakenability and exact LOINC registry semantics. Remediation is in
progress. This verdict does not authorize PASS, terminal audit, or any
Git/integration lifecycle step.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Exact candidate manifest:
  `939e99998c63dfe3ae664aa5ef6e265bc28e0e2787ea7cb73a32002dfb29e93e`
- Medical-source and other network requests: none
- Git mutations, dependency changes, schema changes, and DM-002 work: none

Independent Reviews 001–007 remain immutable historical evidence.

## Verified prior closure

Review 008 verified that direct `DailyMedTrustPath.model_validate` now accepts
exactly one of the six frozen rows and rejects direct row drift. The parent
policy remains exact. The findings below address already-constructed-instance
revalidation and the separate exported LOINC row boundary.

## P1-01 — Existing model instances bypass frozen-policy revalidation

Security-policy validators accept already-constructed model instances without
rechecking every frozen scalar and nested row. Mutation experiments produced
these accepted/total drift counts:

```text
DailyMedTrustPath       0 / 5
DailyMedRedirectPolicy  5 / 5
DailyMedTransportPolicy 17 / 19
DailyMedConnectorPolicy 10 / 15
DailyMedXmlPolicy       35 / 36
DailyMedZipPolicy       25 / 28
```

Representative accepted weakened values include:

```text
authorizes_network_io=true
max_attempts=99
external_io=true
filesystem_extraction=true
```

This bypass violates the frozen rule that any accepted/deserialized policy
object must equal the full frozen contract exactly. A per-class experiment that
always revalidates the instance's complete data closes all tested canonical and
nested drifts.

Acceptance criteria:

1. Every exported security-policy class must revalidate existing instances
   against its complete frozen tuple, including nested models.
2. Reject every altered scalar, tuple, omission, duplication, reorder, and
   nested-policy instance.
3. Preserve canonical construction and parent-policy behavior.

## P1-02 — Exported LOINC row and oracle instances accept drift

The standalone exported LOINC row accepted an arbitrary alias/title, evil URL,
and a mixed row assembled from different frozen entries. The enclosing oracle
also accepted seven of eight tested existing-instance drifts.

This permits a caller to create a row outside the exact four-code LOINC 2.82
registry or pass a mutated existing oracle instance without complete
revalidation.

Acceptance criteria:

1. Standalone LOINC row validation accepts exactly one of the four frozen
   code/title/status/URL rows.
2. Reject arbitrary alias/title, URL drift, and mixed-row construction.
3. Revalidate existing oracle instances against every frozen scalar and row.
4. Preserve the exact four-code registry, ordering, authority, steward,
   release, mapping mode, and expansion-disabled values.

## Validation evidence

```text
Combined DailyMed/OpenAPI gate: 327 passed
Full unit/contract suite: 941 passed, 2 expected warnings, 80% coverage
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion. Green canonical-construction tests do not override the
reproduced existing-instance and standalone-row counterexamples.

## Lifecycle result

Review 008 is `FAIL`. Same Owner-frozen non-weakenability and LOINC mechanical
remediation is in progress. Fresh Review 009 and terminal evidence audit remain
pending. Do not claim PASS or perform commit, push, PR, CI, ready transition,
merge, integration, network execution, or `M1B-DM-002`.
