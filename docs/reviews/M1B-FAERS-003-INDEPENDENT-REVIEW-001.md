# M1B-FAERS-003 Independent Review 001

## Verdict

`FAIL — P0 0 / P1 2 / P2 0`

The aggregate report builder, conditional application injection, evidence
comparators, mandatory limitations, disabled live harness, dependency boundary,
and protected PubMed/DailyMed surfaces passed the exercised offline checks.
However, the new public FAERS boundary is not exact: integral JSON floats are
silently normalized into integer contract fields, and the route's OpenAPI
request/response schemas advertise the source-generic M1B unions rather than the
FAERS-only shapes enforced at runtime. Both defects are at the public trust
boundary and must be remediated before a fresh complete independent review.

This is not terminal-audit, Git, integration, live-source, or completion
evidence.

## Exact candidate identity

- branch: `feat/m1b-faers-003-report-api`
- baseline, `HEAD`, branch tip, and merge-base:
  `263be374bd7039b07ded5a5fc095b2377c3ae37c`
- index: empty
- candidate state: unstaged tracked edits plus untracked authorized files
- manifest algorithm: Ordinal repository-relative
  `path<TAB>byte_count<TAB>sha256`, case-sensitive path sort, UTF-8 lines joined
  by LF, with no terminal LF
- manifest rows: `22`
- manifest preimage bytes: `2208`
- manifest SHA-256:
  `a4072857a957db638e3395f7e4335c702df91909a2b157c851367c01e7843939`
- this review record is deliberately excluded from that pre-verdict candidate
  manifest and is the sole reviewer-created file

Canonical manifest:

```text
.delivery/M1B-FAERS-003.md	3485	8067cce9949b24d6990acdb5b34dc4383866cf5f7226cfef6faa0742d30b63fd
docs/ARCHITECTURE.md	29291	b2d3146e74d16df851a6c1bffc483c1f307d8d90546bc84b799cf81788d02d3a
docs/DATA_SOURCES.md	17216	839d30b6fa09b0d909bd41af47d3f5546bc0d0f087ea14f92cdb131dea1b2c19
docs/EVALUATION_PLAN.md	23563	61c24f8987b2d38cf91d7137108d0d3f32571bff8d67f56ffdd77601ce75012f
docs/PRD.md	24593	d72f7802ee48dd9abc459c34cd5f81fe42e60446344b93249f93ac6a1a9cc2af
docs/SECURITY.md	21260	8d045ed4bbef5bd948c660778588f150d3eb0ed80a58839ff6883d6476d69a5e
docs/TRACEABILITY_MATRIX.md	45953	4c5437a91fdfae066996feb89249e48406b4e1d5096fff7b71853786124e7f77
src/medevidence/api/app.py	9423	aaabafd398eed789d690ba4bbe175fd9454ed1f468e009ad3576e29717ef33ed
src/medevidence/api/contracts.py	18284	8e704d65dcdeb8d8a700eefa420d10bd9ac3056f8d125382b8b31cbfc1027b1f
src/medevidence/api/routes.py	20403	ff585f1290e74e9be04a9e7666a414443a9ce11800d7f2c891292394e8d075f1
src/medevidence/composition.py	44489	99793133c60fcd7496773a9bf29902e9d78df6de758e265bb939c0547480c1c8
src/medevidence/tools/__init__.py	1683	b591a17f72a90760d4368c91c18eb0e0c18b1437c5cf908b714108dfa112c142
src/medevidence/tools/faers_report.py	4177	db198a973273beaf77b1eb6d990cdcd41b20d707501bef6b7669ff5b94be9a24
src/medevidence/tools/ports.py	17462	7e8198b678db582f1e34cff838b7b26d3005a607d3affef801038028b5f9d379
tests/contract/api/test_openapi.py	21500	b451ae3de75ee38129cc66ff80484153da5d642edb04a0e23a731557c9944801
tests/e2e/test_live_faers.py	488	5ed527da9197eb2a8537dda621e53acbb0001faf99802f97b5b78b911452ec29
tests/fixtures/api/openapi-v1.json	100987	d644412d660bc886cace41c78c3953ef41649e73eead209372efecbdc346cec6
tests/integration/api/test_research_faers.py	4103	79b14880bbf63a1b27d303faca717cdf6685918479add4c654159bc882a311c7
tests/unit/api/test_contracts.py	12060	598aedc3d9a432cbab66a2ce1c81ee08989235d211afd8419ac12f4581c15cfc
tests/unit/api/test_routes.py	22642	23bf19a4c371454e497775f2393dc91ef9de321832975927fb0a77b44e18a32e
tests/unit/tools/test_contracts.py	22640	5fdf73257153ff776c715c04db5a61ee8d029668a8e17af16d9c79bf9e911a39
tests/unit/tools/test_faers_report.py	4507	0e708cc05acf69fb6762f973519b81f23f8deaaf3474db5ecc5bd068b61fef7d
```

Owner freeze independently verified:

- `C:\Users\BoqiNiu\Downloads\M1B-PASS8-CODEX-SYNC-PACK\M1B-OWNER-PLANNING-FREEZE-v8-faers-pt-owner-resolution-final-r1.md`
- bytes: `680144`
- SHA-256:
  `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`
- applicable authorization: Section K.6

## Findings

### P1-01 — Raw FAERS JSON silently coerces integral floats into exact integer fields

Files and symbols:

- `src/medevidence/api/contracts.py::_validate_raw_m1b_request`
- specifically `M1BResearchRequestV1.model_validate_json(..., strict=False)` and
  the subsequent Python equality comparison
- `tests/unit/api/test_contracts.py` lacks numeric-type drift negatives

The raw boundary parses with `strict=False`, then attempts to detect
normalization by comparing the serialized model mapping with the original JSON
mapping. Python considers an integer and its integral float equal, so this does
not detect type drift. Values including `512.0`, `5.0`, `100.0`, `30000.0`,
`365.0`, and `5242880.0` are accepted for exact integer/Literal fields and
returned as integers. The emitted OpenAPI correctly advertises those locations
as JSON integers, making runtime more permissive than the public contract.

Reproduction, run offline from the repository root:

```powershell
@'
import json
from tests.unit.tools.test_faers_report import _report_request
from medevidence.api.contracts import validate_raw_faers_request

payload = _report_request().model_dump(mode="json")
payload["scope"]["query_bounds"]["max_query_characters"] = 512.0
request = validate_raw_faers_request(
    json.dumps(payload).encode(),
    content_type="application/json",
    content_encoding=None,
)
print(type(request.scope.query_bounds.max_query_characters).__name__)
'@ | uv run --locked --no-sync python -
```

Observed: the request is accepted and prints `int`. The same acceptance was
independently reproduced in nested FAERS fields
`effective_total_deadline_ms`, `execution_bounds.max_date_difference_days`,
`execution_bounds.max_pages`, `execution_bounds.max_query_characters`, and
`execution_bounds.max_cumulative_bytes`.

Impact:

- the public raw trust boundary is not type-exact;
- runtime behavior contradicts the integer-only OpenAPI contract; and
- the delivery/security claim that the closed raw request preserves exact
  nested fields is unsupported for JSON numeric types.

Acceptance criteria:

- reject every JSON float at an integer or integer-Literal location, including
  an exactly integral float;
- retain valid JSON date/string/enum handling without broad coercion;
- compare raw and validated structure with type-sensitive semantics; and
- add positive integer-boundary tests plus representative scope and nested
  FAERS float, Boolean, numeric-string, non-integral-float, and overflow
  negatives through both the validator and HTTP route.

### P1-02 — FAERS OpenAPI advertises source-generic requests and responses that runtime rejects

Files and symbols:

- `src/medevidence/api/routes.py::research_faers` route registration
- `src/medevidence/api/app.py::_register_public_components`
- `src/medevidence/api/app.py::_require_dailymed_response_fields`
- `tests/contract/api/test_openapi.py`

The FAERS route's request body references the source-generic
`M1BResearchRequestV1`, whose schema permits DailyMed request elements and any
`SourceType`; it has no FAERS-only constant or conditional requirement. The 200
response similarly references source-generic `M1BResearchReportV1`, whose
section discriminator advertises both `dailymed_label` and `faers_aggregate`.
Runtime is materially narrower: `validate_raw_faers_request` requires FAERS as
the sole requested source, and `_validate_faers_response` requires the exact
FAERS plan and FAERS request echo.

Reproduction and evidence:

```text
FAERS request schema:  #/components/schemas/M1BResearchRequestV1
requested_sources:     unconstrained SourceType array; no const
request section fields: dailymed_selection_requests, faers_query_requests,
                        cadec_query_requests
FAERS response schema: #/components/schemas/M1BResearchReportV1
response section variants: dailymed_label and faers_aggregate
```

A valid `M1BResearchRequestV1` DailyMed-only payload is therefore represented
by the advertised request schema, but posting that exact payload to
`/v1/research/faers` returns HTTP `422 invalid_request`. Tests currently assert
only that both routes reference the shared model; no negative proves route
schema/runtime parity. The inverse response over-admission is equally visible
from the advertised discriminated union even though runtime fails it as a tool
contract error.

Impact:

- generated clients and validators can accept a request the server rejects;
- the FAERS 200 response contract promises variants the endpoint cannot return;
  and
- the documented claim of truthful exact OpenAPI/runtime parity is false.

Acceptance criteria:

- expose FAERS-route request and response schemas that encode FAERS-only source,
  section, plan, and required request-element constraints enforced by runtime;
- preserve the byte-pinned default PubMed and DailyMed-only OpenAPI surfaces;
- keep the public serialized envelope fields/version values unchanged unless a
  separately approved public-contract decision says otherwise; and
- add schema acceptance/rejection tests proving valid FAERS payloads pass while
  DailyMed-only, mixed-source, missing-FAERS-request, DailyMed-section response,
  and foreign-plan response shapes fail the FAERS route schemas.

## Reviewed behavior and closed checks

- Report tool reconstructed typed FAERS executions, exact parent request/query,
  source outcome, acquisition/snapshot identity, canonical buckets, complete
  one-per-bucket locators, and exact mandatory limitations before returning a
  draft, research-only, non-exportable report.
- Exact PT tuple `("DIARRHOEA", "NAUSEA", "VOMITING")`,
  `provider_count_occurrence`, `unfiltered_provider_roles`, inclusive
  `receivedate`, frozen date/query/bounds identity, bucket order, and locator
  equality remain enforced by the existing durable contracts and report
  comparators.
- Complete no-result and partial/failed zero-result states remain distinct via
  the retained `SourceOutcome`; partial/unavailable outcomes require warning
  codes and do not become complete no-match.
- Raw duplicate keys, unknown fields, planning fields, patient-like keys,
  discriminator absence/drift, and foreign source sets reject before application
  execution, apart from the numeric-type defect above.
- Returned reports undergo strict reconstruction, recursive required-field
  presence checks, exact request/scope/plan/section parity, and error
  translation.
- The public models expose aggregate bucket evidence only; no individual FAERS
  report, narrative, demographic, reporter, or provider-native payload field was
  found in the candidate model graph or deterministic fixtures.
- Composition forwards only an explicitly injected source-neutral FAERS report
  application. It creates no FAERS connector, persistence adapter, credential,
  host permission, or fallback.
- Default PubMed, PubMed transitive component, and DailyMed-only OpenAPI byte
  pins passed. Conditional route combinations and local `$ref` resolution
  passed.
- The changed paths are within K.6. Connector, ingestion, persistence,
  migration, dependency, Docker, retrieval, evaluation, and CADEC paths are
  unchanged. `pyproject.toml` and `uv.lock` have no diff.
- PostgreSQL is not applicable because this work item has no schema or
  persistence change.

## Fresh validation evidence

- Focused report/API/OpenAPI command from K.6: `194 passed`, one existing
  TestClient deprecation warning.
- Offline FAERS API integration with `--disable-socket`: `1 passed`.
- Live FAERS harness with `--disable-socket`: `1 skipped` with the required
  separate-Owner-authorization reason; no request executed.
- Dependency and offline boundary selection:
  `tests/unit/test_dependency_boundaries.py` plus
  `tests/contract/test_offline_network.py`: `12 passed`, one expected
  socket-block warning.
- Full offline unit/contract suite with coverage: `1435 passed`, two expected
  warnings, `80%` total coverage; `coverage.xml` produced by the command is
  ignored and did not enter candidate scope.
- Ruff: PASS.
- Ruff format check: PASS, `99 files already formatted`.
- MyPy: PASS, `46 source files`.
- `git diff --check`: PASS.
- Initial dependency-boundary invocation named a nonexistent
  `tests/contract/test_offline_boundary.py`, collected zero tests, and exited
  nonzero. It was corrected to the repository's actual
  `tests/contract/test_offline_network.py`; the corrected selection passed as
  recorded above. The failed typo is not treated as validation evidence.
- Independent adversarial raw-number reproduction: FAIL as P1-01.
- Independent route-schema/runtime reproduction: FAIL as P1-02.

## Operations and remaining gates

- FAERS/openFDA, PubMed, DailyMed, NCBI, and all other medical-source requests:
  `0`.
- Other external network requests: `0`.
- Docker operations: `0`.
- Database operations: `0`.
- Dependency changes or installation: `0`.
- Reviewer Git mutations: `0`; no stage, commit, push, fetch, pull, merge,
  rebase, reset, clean, branch operation, PR, or CI action was performed.
- Reviewer filesystem writes: this review record only.
- No terminal audit was performed or authorized.

Required next gate: remediate both P1 findings within the already frozen and
authorized boundary, rerun the complete applicable offline validation, and
perform a fresh independent review of the entire resulting candidate. This
Review001 `FAIL` does not authorize terminal audit or any Git lifecycle step.

## Owner defense questions

1. Why must raw JSON validation distinguish `512` from `512.0` even though
   Python numeric equality considers them equal?
2. Why does a source-specific endpoint need route-specific OpenAPI constraints
   when the durable envelope model supports multiple M1B sources?
3. Which comparators prevent partial or failed zero-bucket FAERS execution from
   being reported as exhaustive no-match evidence?

## Independent Review 002

### Verdict

`PASS — P0 0 / P1 0 / P2 0`

This fresh complete review inspected the full post-remediation candidate diff
and executable behavior. Review001 remains the historical `FAIL — P0 0 / P1 2
/ P2 0`; this section records the separately executed Review002 only. Both
Review001 findings are closed, no new defect was found, and the candidate may
proceed to the separately required terminal evidence audit. This verdict is not
terminal-audit, commit, push, pull request, CI, merge, integrated verification,
completion, vertical-slice-complete, or CADEC-readiness evidence.

### Exact candidate binding

- branch: `feat/m1b-faers-003-report-api`
- baseline, `HEAD`, branch tip, `main`, and merge-base:
  `263be374bd7039b07ded5a5fc095b2377c3ae37c`
- index: empty
- candidate state: unstaged tracked edits plus untracked authorized files
- manifest algorithm: Ordinal repository-relative
  `path<TAB>byte_count<TAB>sha256`, case-sensitive path sort, UTF-8 lines joined
  by LF, with no terminal LF
- start candidate manifest rows: `23`
- start candidate manifest preimage bytes: `2333`
- start candidate manifest SHA-256:
  `7906832214221f846178b2260197bf36e90d95bced7f6f1a4e6e1eab2c191945`
- end candidate excluding this Review002 append: identical `23` rows, `2333`
  preimage bytes, and SHA-256
  `7906832214221f846178b2260197bf36e90d95bced7f6f1a4e6e1eab2c191945`
- the pre-append review record was `13,899` bytes with SHA-256
  `a444257494c4d7a3ce079f5bd3b731701b73a82edca3bf3e689247d360f94c94`;
  this authorized Review002 append is excluded from the candidate identity

The exact canonical 23-row manifest is the one enumerated below:

```text
.delivery/M1B-FAERS-003.md	4628	c6ec1b85c6c1617e06231e299f7ff3e65ad632b3031c4b5e740fc6cdbb703004
docs/ARCHITECTURE.md	29291	b2d3146e74d16df851a6c1bffc483c1f307d8d90546bc84b799cf81788d02d3a
docs/DATA_SOURCES.md	17216	839d30b6fa09b0d909bd41af47d3f5546bc0d0f087ea14f92cdb131dea1b2c19
docs/EVALUATION_PLAN.md	23563	61c24f8987b2d38cf91d7137108d0d3f32571bff8d67f56ffdd77601ce75012f
docs/PRD.md	24593	d72f7802ee48dd9abc459c34cd5f81fe42e60446344b93249f93ac6a1a9cc2af
docs/SECURITY.md	21260	8d045ed4bbef5bd948c660778588f150d3eb0ed80a58839ff6883d6476d69a5e
docs/TRACEABILITY_MATRIX.md	45953	4c5437a91fdfae066996feb89249e48406b4e1d5096fff7b71853786124e7f77
docs/reviews/M1B-FAERS-003-INDEPENDENT-REVIEW-001.md	13899	a444257494c4d7a3ce079f5bd3b731701b73a82edca3bf3e689247d360f94c94
src/medevidence/api/app.py	15886	d859a60cad10652323769050aaa06364d8e42f520b18bd1ff3abe2dfda739a91
src/medevidence/api/contracts.py	19132	b913e74a2a8c5a58ffebd5a9ce9ba72469f65a125dc071bd1ff1b11149ba71ef
src/medevidence/api/routes.py	20475	f6a57ced0f3849579a5983a5d51c904f9709fac46a68ea64f20534ed80da75c6
src/medevidence/composition.py	44489	99793133c60fcd7496773a9bf29902e9d78df6de758e265bb939c0547480c1c8
src/medevidence/tools/__init__.py	1683	b591a17f72a90760d4368c91c18eb0e0c18b1437c5cf908b714108dfa112c142
src/medevidence/tools/faers_report.py	4177	db198a973273beaf77b1eb6d990cdcd41b20d707501bef6b7669ff5b94be9a24
src/medevidence/tools/ports.py	17462	7e8198b678db582f1e34cff838b7b26d3005a607d3affef801038028b5f9d379
tests/contract/api/test_openapi.py	28888	03ce0bbd91284766416764e46ad79b79fd6a17204d3fcc79f34b3a679978503b
tests/e2e/test_live_faers.py	488	5ed527da9197eb2a8537dda621e53acbb0001faf99802f97b5b78b911452ec29
tests/fixtures/api/openapi-v1.json	103037	1669d1698dce678e6980f1ba723df2c503243b946c0ebfe263cebfe89f209d77
tests/integration/api/test_research_faers.py	4103	79b14880bbf63a1b27d303faca717cdf6685918479add4c654159bc882a311c7
tests/unit/api/test_contracts.py	15513	0e4a2138de951f04787e429a5df4d97b3514781832cefc2232ef0f405d0464e8
tests/unit/api/test_routes.py	24182	74150272cbf7a01f3f496647fa9b615ba7f341eeab9019915a4251e716a71c52
tests/unit/tools/test_contracts.py	22640	5fdf73257153ff776c715c04db5a61ee8d029668a8e17af16d9c79bf9e911a39
tests/unit/tools/test_faers_report.py	4507	0e708cc05acf69fb6762f973519b81f23f8deaaf3474db5ecc5bd068b61fef7d
```

The Owner freeze was independently reverified at `680,144` bytes and SHA-256
`1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`;
Section K.6 is the applicable authorization.

### Review001 closure evidence

- **P1-01 closed:** `_json_values_match_exactly` compares JSON primitive types
  before equality. Independent reproduction changed every one of the `17`
  frozen integer locations to an integral JSON float; all `17/17` rejected.
  The valid request retained exact Python `int` values. Six representative HTTP
  cases covering an integral float, Boolean, numeric string, non-integral float,
  and overflow all returned `422 invalid_request`, and the injected FAERS
  application execution count remained `0` in every case.
- **P1-02 closed:** the FAERS path now references route-only
  `M1BResearchRequestV1FaersRoute` and `M1BResearchReportV1FaersRoute`
  components. An independent exact structural evaluator exercised every JSON
  Schema keyword used by these local `allOf` overlays and resolved their local
  `$ref` graph. A valid FAERS request passed both with explicit empty
  DailyMed/CADEC arrays and with those optional empty arrays omitted. Nonempty
  foreign DailyMed or CADEC arrays, DailyMed-only, mixed-source, and
  missing-FAERS-request shapes rejected. A valid FAERS response passed; foreign
  scope, plan, outcome, and DailyMed-section variants rejected. The repository
  has no installed general JSON Schema validator, so no dependency was added or
  downloaded for this review.
- Default M1A, PubMed transitive components, and DailyMed-only normalized
  OpenAPI byte pins passed. All local references resolved, and the enabled
  fixture is `103,037` bytes with SHA-256
  `1669d1698dce678e6980f1ba723df2c503243b946c0ebfe263cebfe89f209d77`.

### Complete-candidate review

- `build_faers_report` reconstructs typed trusted executions, requires the exact
  request ordering and run ownership, emits one locator for every canonical
  bucket, propagates the complete frozen limitation tuple, and finishes with
  the authoritative `M1BResearchReportV1.validate_against` comparison.
- The exact PT tuple, provider-count-occurrence unit, unfiltered role policy,
  inclusive receivedate identity, execution bounds, query identity, outcome,
  acquisition, snapshot, bucket order, count, and locator relationships remain
  closed by existing domain validators plus the report comparator.
- Partial, failed, truncated, and unavailable outcome states remain visible.
  Only a successful complete zero-bucket execution can represent the bounded
  no-match state; indeterminate zero-result execution is not promoted to
  exhaustive or complete evidence.
- The public graph contains aggregate evidence only. No individual FAERS
  report, patient record, demographic, narrative, reporter identity, provider
  body, credential, or private source path was found in the changed contracts,
  report tool, API, fixture, or deterministic tests.
- Mandatory wording preserves the non-comprehensive three-PT scope and states
  that provider counts do not establish incidence, causality, risk,
  comparative safety, ranking, or general absence of GI adverse events.
- The API performs bounded duplicate-aware raw parsing before application
  execution, reconstructs returned values strictly, recursively requires
  serialized field presence, and compares request ID, exact scope, sole
  selected FAERS plan, and ordered request-section echo before HTTP 200.
- Composition only forwards an explicitly injected source-neutral report
  application. Construction installs no default connector, transport,
  persistence adapter, database connection, credential, host permission, or
  fallback. The default route inventory remains PubMed-only.
- Exact K.6 scope audit passed for all `23` paths. No connector, ingestion,
  persistence, migration, dependency, Docker, retrieval, evaluation, frontend,
  or CADEC path changed. `pyproject.toml` and `uv.lock` have no diff.
- The delivery and traceability records correctly retain Review001 failure,
  describe remediation as pending Review002 until this append, and make no
  terminal-audit, Git, integration, live-source, completion, or successor-node
  claim.

### Fresh validation evidence

- focused K.6 report/API/OpenAPI selection: `288 passed`, one existing
  TestClient deprecation warning
- offline FAERS API integration with sockets disabled: `1 passed`
- disabled live FAERS harness with sockets disabled: `1 skipped`, with the
  required separate exact Owner-authorization reason; no request executed
- dependency and offline-network boundary selection: `12 passed`, one expected
  socket-block warning
- full unit and contract suite with sockets disabled and coverage:
  `1529 passed`, two expected warnings, `80%` total coverage; `coverage.xml` was
  generated as an ignored artifact and did not enter candidate scope
- Ruff: PASS
- Ruff format: PASS, `99 files already formatted`
- MyPy: PASS, `46 source files`
- `git diff --check`: PASS
- exact authorized-path audit: PASS, `23` actual paths and `0` unauthorized
- dependency and denied-directory diff checks: PASS, no output

### Operations and remaining risk

- FAERS/openFDA, PubMed, DailyMed, NCBI, and other medical-source requests: `0`
- other external network requests: `0`
- Docker operations: `0`
- database operations: `0`
- dependency installation or mutation: `0`
- reviewer Git mutations: `0`; no stage, commit, push, fetch, pull, merge,
  rebase, reset, clean, branch operation, PR, or CI action occurred
- reviewer filesystem writes: this Review002 append only
- terminal evidence audit: not performed

Remaining risk is bounded to the separately required terminal evidence audit,
final-byte rebind after this append, and the separately authorized Git
lifecycle. No live-source truth, source availability, latency, clinical
validity, or empirical completeness was established by this offline review.

### Owner defense questions for Review002

1. Why does the FAERS route use a route-only OpenAPI overlay instead of
   narrowing the shared M1B durable envelope?
2. How does type-sensitive raw JSON comparison close the `512` versus `512.0`
   mismatch while retaining date and enum parsing?
3. Which report and API comparators prevent a partial zero-result outcome or a
   foreign plan/section from being returned as successful complete FAERS
   evidence?
