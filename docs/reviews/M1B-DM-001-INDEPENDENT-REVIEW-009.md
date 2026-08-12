# M1B-DM-001 Independent Review 009

## Verdict

`FAIL - P0 0 / P1 2 / P2 0`

Both findings are mechanically equivalent accepted-instance revalidation
defects under the already Owner-frozen closed-contract and exact-provenance
rules. This review does not authorize PASS, terminal audit, or any Git or
integration lifecycle step.

## Candidate identity and boundary

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Exact candidate manifest:
  `1cfb367f52576a765f7ccf5e3ef5d80053906dd7a8e4dffecb0066728350d3d4`
- Medical-source and other network requests: none
- Git mutations, dependency changes, schema changes, and DM-002 work: none

Independent Reviews 001-008 remain immutable historical evidence.

## Verified Review 008 closure

Review 009 verified that existing instances of all six DailyMed security
policy models revalidate against the frozen tuples, nested connector drift
rejects, standalone LOINC rows accept exactly one of the four frozen rows, and
the LOINC oracle revalidates every frozen field.

```text
Focused policy/LOINC gate: 30 passed
Combined DailyMed/OpenAPI gate: 335 passed
Full unit/contract suite: 949 passed, 2 expected warnings
Coverage: 80%
Full-suite duration: 6.50s
Ruff check and format check: passed
MyPy --no-incremental: 34 source files passed
git diff --check and candidate scope checks: passed
```

The warnings are the existing Starlette TestClient deprecation and deliberate
socket-block assertion.

## P1-01 - Closed DailyMed domain instances bypass revalidation

An existing `DailyMedCandidateLabel` instance accepted drift in 18 of 35
tested fields at the public/trusted validation boundary. Accepted mutations
included `body_complete=false` and `termination_reason="evil"`; candidate
binding normalized those invalid values into an apparently complete binding.
Existing stable section instances also accepted title and section-ID drift.

Acceptance requires every newly added closed DM-001 model entering trusted,
request, report, retained-response, or locator context to revalidate existing
instances. Candidate binding must preserve completeness and termination
values exactly, and adversarial tests must reject candidate, stable-version,
stable-section, warning, request, reference, decision, and nested-report drift.

## P1-02 - Locator and retained-response instances bypass closed contracts

Existing locator instances accepted drift in schema version, locator kind,
snapshot identity, and fetch operation. Existing retained-response instances
accepted drift in schema version, response ID, media type, byte size, and
retrieval time. Nested report/request validation did not consistently force
those objects back through their closed validators.

Acceptance requires direct and nested instance revalidation for locator,
retained response, complete report/request, and request-owned trusted tuples.
It adds no serialized field, schema, public concept, dependency, or network
authority.

## Same-class mechanical remediation closure

The implementation node applied unified existing-instance revalidation to the
14 newly added closed DM-001 model types entering public or trusted context:
source plan, candidate binding, candidate label, selection decision, label
version, retained response, selection warning, label section, DailyMed
selection request, M1B request, locator, acquisition reference, DailyMed
report section, and M1B report. Already-remediated security and LOINC models
remain exact.

Candidate binding now carries completeness and termination values without
substitution. Trusted report/request/acquisition/candidate and
locator/retained/version/section boundaries explicitly revalidate instances.
Adversarial tests cover every candidate field, all reproduced locator and
retained-response dimensions, stable section title/ID, warning,
request/reference, and nested complete report drift.

```text
Focused owned gate: 335 passed
Domain plus byte-exact OpenAPI gate: 372 passed
Ruff check: passed
Ruff format check: 8 owned files already formatted
MyPy --no-incremental: 34 source files passed
git diff --check: passed
```

## Lifecycle result

Review 009 remains the historical `FAIL` review that triggered this
same-class remediation. Root full offline validation, fresh complete
Independent Review 010, and terminal evidence audit are pending. No PASS,
commit, push, PR, CI, ready transition, merge, local-main fast-forward,
medical-source network execution, or `M1B-DM-002` claim is authorized or made.
