# ADR-012: M1B FAERS aggregate contracts

- Status: Terminal Audit001 PASS; final-byte rebind and Git pending
- Approved by: Boqi Niu, Project Owner
- Approval date: 2026-08-12
- Work item: `M1B-FAERS-001`
- Baseline: `33213eca6b65ca90287ad2190ef22e21dc2104cc`
- Owner Freeze: `M1B-OWNER-PLANNING-FREEZE-v8-faers-pt-owner-resolution-final-r1.md`
- Freeze SHA-256: `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`

## Decision

M1B V1 uses only the openFDA provider count endpoint and calls its statistical
unit `provider_count_occurrence`. It does not retrieve or aggregate individual
reports and makes no patient, case, deduplicated-report, incidence, causality,
risk, exposure, or product-ranking claim. Provider version behavior is accepted
as supplied; no additional report-version reconstruction or deduplication is
inferred.

The query contract has no role field or role predicate. Its sole token is
`role_policy=unfiltered_provider_roles`; numeric role values are never
interpreted. Drug identity uses exactly one separately requested mapping:

- `harmonized_substance` to the same-named stratum and
  `patient.drug.openfda.substance_name.exact`;
- `native_medicinal_product` to the same-named stratum and
  `patient.drug.medicinalproduct.exact`.

The pairs cannot cross, fall back, relabel, or silently union. Identity values
must already be nonblank bounded Unicode NFC text. The exact request strategy,
stratum, provider field, value, dates, PT contract, endpoint/unit, profile,
grammar, ordering, role policy, and every bound form the query identity.

`GI_PT_SET_M1B_V1` is exactly the bytewise UTF-8 ordered tuple
`("DIARRHOEA", "NAUSEA", "VOMITING")`. The only mapping is `DIARRHOEA` to
`Diarrhoea`, `NAUSEA` to `Nausea`, and `VOMITING` to `Vomiting`, under MedDRA
Version 29.0, English, reference-only use. `CONSTIPATION` and `ABDOMINAL PAIN`
are excluded for insufficient public version-bound current-PT evidence. No
alias, case conversion, spelling fallback, normalization-derived term, code,
hierarchy, terminology bundle, licensed payload, or redistribution grant is
admitted. The set is deliberately bounded and non-comprehensive.

The date predicate is inclusive `receivedate`. `end-start` is at most 365 days,
so one through 366 inclusive dates are valid. The serialized execution bounds
require the exact literals `max_date_difference_days=365` and
`max_inclusive_calendar_dates=366`; both participate in the query identity
preimage together with exact start/end dates. Missing dates do not enter the
stratum. `receiptdate` is not this contract.

The provider design policy freezes HTTPS `api.fda.gov:443`, GET
`/drug/event.json`, zero redirects, the exact reaction PT count field,
5/10/5/5-second phase timeouts, a 30-second deadline, two attempts, bounded
backoff/jitter/Retry-After, closed retry classes, five pages, page size 100,
100 records, 100 buckets, and 5,242,880-byte response/cumulative limits. It has
no result cache or stale fallback; replay is immutable exact raw snapshot only.
This is non-authorizing metadata: ordinary validation hosts are empty and
medical-source network execution is false.

Buckets are a complete unique collection of at most 100 exact PT members with
contiguous ordinals, nonnegative counts, and canonical `report_count DESC` then
`reaction_pt ASC` ordering; ties remain present. Results, source sections, and
locators compare the exact parent query, bucket, outcome, acquisition, snapshot,
identity stratum, role policy, endpoint, and unit. Partial, truncated, failed,
and unavailable states retain inherited `SourceOutcome` truthfulness; only
complete successful zero buckets can mean bounded `no_match`.

## Compatibility and scope

These contracts are additive to `M1BResearchRequestV1` and
`M1BResearchReportV1`. Existing M1A and DailyMed serialized behavior is
unchanged. This node adds no connector, persistence, migration, tool, FAERS API
route, dependency, database operation, or live source request. The enabled
additive OpenAPI surface truthfully exposes the frozen FAERS request and report
section models through the existing M1B envelope; the route inventory remains
PubMed plus DailyMed only. M1B-FAERS-002 remains separately Owner-gated.

## Validation status

The implementation candidate has complete fresh offline validation and an
independent Review003 PASS. Terminal evidence audit and the Git lifecycle remain
pending and must not be inferred from this ADR.

Independent Review 001 returned `FAIL — P0 0 / P1 2 / P2 0`. Remediation
cycle 1/3 added the missing required-present request `pt_values` and
`statistical_unit` fields. After the Owner authorized an additional mechanical
cycle, cycle 2/3 closed P1-02 with the exact 0..8 typed request tuple, the
discriminated DailyMed/FAERS section union, exact request-owned report/outcome
comparison, truthful recursive OpenAPI requiredness, and a regenerated enabled
fixture. Independent Review 002 returned `FAIL — P0 0 / P1 1 / P2 0` because
the serialized query-identity bounds omitted the two frozen date ceilings.
Final authorized cycle 3/3 adds both required exact literals to the request,
query, OpenAPI, and query-ID preimage, with omission/drift/bypass negatives and
an exact-formula test. Independent Review003 then inspected the
complete remediated candidate and returned `PASS — P0 0 / P1 0 / P2 0`, binding
the exact 22-path manifest
`bddadeeade832b763cd0f37e0ce15e666e03e0ee2a0eb627651c7fda57100859`.
At the Review003 gate, terminal audit and Git lifecycle remained pending;
review PASS alone was not completion.
Terminal Evidence Audit001 subsequently returned `PASS — P0 0 / P1 0 / P2 0`
on exact audited manifest
`e572da3ef99f568dbfba27569c3921b5879ce76a68cf7f2d8b65432048aa6f97`.
Audit persistence changes evidence bytes, so final-byte rebind and the Git
lifecycle remain pending; this is not completion or integration.
