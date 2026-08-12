# M1B-DM-001 Independent Review 004

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

The finding is a same-class public-binding defect under already frozen
semantics. The Owner's explicit do-not-stop same-class clause permits batch
mechanical remediation within the same authorized cycle; this failed verdict
does not authorize PASS or terminal audit.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Canonical ordinal 21-path manifest SHA-256:
  `e4f3ec8e43e2292ffe1c9c6206892f61d7111eb5c27392a21022122b14b5819e`
- CurrentCulture alias manifest SHA-256:
  `88574fcb86094047cb17c366bc8d6e280e2b476a7e0210b8bd57ac2fc8d98aaf`
- Authorized path count: 21
- Medical-source or other network requests: none
- Git mutations, dependency changes, and outer-path changes: none

## Verified prior closures

Review 004 verified the Review 003 remediation behavior: trusted canonical
reference/outcome pairs reject foreign acquisition, intent, snapshot, and
source-outcome identities; retained discovery snapshot and locator selected
candidate are chained; prior Review 001/002 closures remain intact.

## P1 — Candidate, pin, and per-request evidence authority can be rebound

### A. Decision/candidate parity drift

Observed:

```text
ACCEPTED_DECISION_CANDIDATE_PARITY_DRIFT
candidate=11111111-1111-1111-1111-111111111111 ('3',)
decision=99999999-9999-9999-9999-999999999999 99
```

A forged, internally recomputed `decision_id` was accepted with the original
authoritative candidate and a complete report. The decision's selected SETID
and SPL version were not compared with the authoritative selected candidate.

### B. Pinned-version mismatch

Observed:

```text
ACCEPTED_PIN_MISMATCH
requested=99999999-9999-9999-9999-999999999999 99
selected=11111111-1111-1111-1111-111111111111 3
```

The exact request, report, trusted ref/outcome pairs, and trusted decision were
accepted despite the selected identity disagreeing with the pinned SETID and
SPL version.

### C. Two-drug cross-request evidence swap

Observed:

```text
ACCEPTED_CROSS_REQUEST_EVIDENCE_SWAP
drug:test-0 -> query:dailymed-matrix-1-search
drug:test-1 -> query:dailymed-matrix-0-search
```

Each section's decision, discovery/fetch refs, and limitations were swapped,
and trusted decisions were supplied in the swapped section order. Global
unions remained internally complete, but evidence belonging to one request was
accepted under the other request.

These are three manifestations of the same missing exact request-owned
candidate/decision/evidence binding. They permit authoritative label identity
or acquisition evidence to be attributed to the wrong exact request.

## Acceptance criteria

No new field, schema, or public concept is needed. Mechanical closure requires:

1. Compare the authoritative selected candidate's SETID with
   `decision.selected_setid` and require `decision.selected_spl_version` to be
   an exact version of that candidate.
2. Require request-owned ephemeral tuples using existing models:
   `(DailyMedSelectionRequestV1, AcquisitionOutcomeRef, SourceOutcome)` and
   `(DailyMedSelectionRequestV1, LabelSelectionDecision)`, and compare their
   exact canonical unions per request rather than only global unions.
3. For `PINNED_VERSION`, require selected SETID/SPL version to equal the exact
   pin while preserving partial-match review-required behavior and the frozen
   no-candidate/indeterminate states.
4. Add tests for valid strict/exact pinned selection; pinned mismatch; direct
   selected-scalar drift; two-drug swap; missing, extra, duplicate, and
   reordered request-owned tuples; pinned partial matches; no-candidate; and
   indeterminate discovery.

## Validation evidence

```text
Review-focused gate: 48 passed
DailyMed domain plus byte-exact OpenAPI: 308 passed
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
Full unit/contract suite: 922 passed, 2 expected warnings, 80% coverage
```

The two warnings are the existing Starlette TestClient deprecation and the
deliberate socket-block assertion. Green tests do not override the three
accepted counterexamples. The exact 21-path scope and candidate identity
remained stable after validation.

## Lifecycle result

Review 004 is `FAIL`. Batch same-class remediation is in progress under the
Owner-authorized cycle's explicit do-not-stop clause. Fresh Review 005 and
terminal audit remain pending. Do not claim PASS or perform commit, push, PR,
CI, merge, integration, network execution, or `M1B-DM-002`.
