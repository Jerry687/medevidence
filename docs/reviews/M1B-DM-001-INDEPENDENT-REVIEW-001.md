# M1B-DM-001 Independent Review 001

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

This verdict binds the final remediation 3/3 implementation candidate on
branch `feat/m1b-dm-001-contract-freeze` at approved baseline
`ebcd11eb91aa02ae9a7115188ea10604e9f335d1`. The implementation retry budget is
exhausted. Further correction requires renewed Owner authority.

## Review identity and boundary

- Work item: `M1B-DM-001`
- Owner freeze:
  `M1B-OWNER-PLANNING-FREEZE-v7-owner-resolution-final-r1.md`
- Freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Review scope: actual authorized-path diff and deterministic offline behavior
- Medical-source or other network access: none
- Repository writes by independent reviewer: none
- M1A/OpenAPI regression: green
- Terminal audit, commit, push, PR, CI, merge, and integration: not run

## Findings

### P1-1 — Exact security/trust policy models permit caller weakening

The typed connector transport, denied-class, XML inert-attribute, and ZIP
rejection metadata in `src/medevidence/domain/sources.py` assert exact defaults
but do not reject caller-supplied weakened tuples. Independent offline
construction accepted each of these counterexamples:

```text
retryable=("429",)
denied=("http",)
rejected_ascii_codepoints=(0,)
member_name_reject=("absolute",)
additional_safe_attributes_never_affect=("identity",)
```

This contradicts the Owner-frozen exact machine-oracle contract. The existing
tests compare default instances but do not prove that caller drift rejects.

Acceptance criteria for a future Owner-authorized correction: validate all
frozen policy tuple/scalar fields against their exact canonical values and add
one-field-at-a-time negative construction tests.

### P1-2 — Report contracts accept discovery/fetch tuple conflation

`DailyMedLabelSectionV1.validate_section_shape` checks nondecreasing acquisition
ordinals and unique query IDs, but does not require discovery and fetch to use
distinct acquisition identities, snapshots, and strictly increasing ordinals.
An independently constructed complete `M1BResearchReportV1` accepted search and
fetch references with:

```text
acquisition_id="acquisition:conflated"
snapshot_id="snapshot:conflated"
acquisition_ordinals=(0, 0)
```

Reproducer result:

```text
ACCEPTED_REPORT_CONFLATION True True (0, 0)
```

This violates the frozen distinct discovery/fetch acquisition and snapshot
rule and the mandatory tuple-conflation rejection.

Acceptance criteria for a future Owner-authorized correction: require the fetch
ordinal strictly after discovery, distinct acquisition IDs, distinct snapshot
IDs, and adversarial report tests for each conflation.

## Independent evidence

The reviewer independently verified:

```text
uv run --locked --no-sync pytest tests/unit/domain/test_source_outcomes.py tests/unit/domain/test_scope.py tests/unit/domain/test_reports.py tests/unit/domain/test_provenance.py tests/contract/api/test_openapi.py --disable-socket -q
257 passed
```

The Owner freeze SHA and baseline matched. The actual implementation remained
within the exact 18 authorized implementation paths, with no connector, parser,
API, dependency, or `M1B-DM-002` changes. The two counterexamples above override
the otherwise green test evidence.

## Lifecycle decision

Remediation 3/3 is exhausted. The findings are implementation-local defects
under already frozen semantics, but no fourth remediation cycle is authorized.
Status is therefore `OWNER_DECISION_REQUIRED` for renewed correction authority.
Do not proceed to terminal audit, commit, push, Draft PR, CI, ready transition,
merge, local-main fast-forward, integrated verification, or `M1B-DM-002`.
