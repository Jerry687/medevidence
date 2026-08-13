# M1B-FAERS-001 delivery evidence

## Status

`TERMINAL_AUDIT001_PASS_AWAITING_FINAL_BYTE_REBIND_AND_GIT`

This record preserves Independent Reviews 001 and 002 as FAIL history and
records remediation cycles 1/3, 2/3, and 3/3. It does
not claim review PASS, terminal audit, commit, push, PR, CI, merge, verification,
`M1B-FAERS-001_COMPLETE`, or readiness to execute M1B-FAERS-002.

## Authority and baseline

- Work item: `M1B-FAERS-001`
- Branch: `feat/m1b-faers-001-contract-freeze`
- Baseline: `main@33213eca6b65ca90287ad2190ef22e21dc2104cc`
- Owner Freeze: `M1B-OWNER-PLANNING-FREEZE-v8-faers-pt-owner-resolution-final-r1.md`
- Owner Freeze bytes: `680144`
- Owner Freeze SHA-256: `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`
- Terminal planning audit: `M1B-OWNER-PLANNING-FREEZE-v8-FAERS-PT-OWNER-RESOLUTION-TERMINAL-AUDIT-002.md`
- Terminal planning audit bytes: `11989`
- Terminal planning audit SHA-256: `2eaa64526d148d244573ab57e765702041b3a9c59bdeef0530678294538b484d`
- Terminal planning audit verdict: `PASS - P0 0 / P1 0 / P2 0`
- Consequence: `M1B-FAERS-001.implementation_authorized=true` for this separately
  started work item only. M1B-FAERS-002 remains unauthorized and unstarted.

## Implemented candidate

The candidate adds only the Owner-frozen additive FAERS domain and documentation
contracts:

- exact `provider_count_occurrence` endpoint mode and statistical unit;
- no raw-report aggregation, patient/case unit, inferred report-version
  reconstruction, or additional deduplication;
- exact `role_policy=unfiltered_provider_roles` with no role field, predicate,
  or numeric-role inference;
- separately requested exact harmonized-substance and native-medicinal-product
  strategy/stratum/provider-field mappings, bounded NFC identity values, and no
  fallback, relabeling, or silent union;
- inclusive `receivedate` range with `end-start<=365`, plus required serialized
  `max_date_difference_days=365` and `max_inclusive_calendar_dates=366` query
  identity inputs;
- exact `GI_PT_SET_M1B_V1=("DIARRHOEA","NAUSEA","VOMITING")`, exact display
  mapping, MedDRA Version 29.0 English reference-only authority, explicit
  exclusions, and no alias/case/spelling/normalization-derived expansion;
- closed query identity/preimage, fixed bounds/profile, non-authorizing transport
  and freshness metadata, complete canonical aggregate buckets, truthful
  inherited outcome semantics, exact locators and standalone FAERS section
  contract, and mandatory no-incidence/causality/risk/ranking limitations;
- the exact typed 0..8 FAERS request tuple, `section_kind`-discriminated
  DailyMed/FAERS report union, same-source ordinal ownership, and exact trusted
  request/reference/outcome comparison;
- additive enabled OpenAPI components for those frozen models, with recursive
  response requiredness and input optionality matching runtime; no FAERS route;
- no change to existing M1A/PubMed behavior, the protected 76-component PubMed
  subtree, or the DailyMed route behavior.

## Remediation accounting

Implementation-local retry: `1/1`.

Independent-review remediation cycle: `3/3` (consumed).

The first full offline run exposed three byte-exact OpenAPI failures caused by
prematurely adding FAERS types to the already integrated DailyMed request/report
surface. The same implementation node removed only that premature envelope/union
integration while retaining the standalone FAERS contracts. Final OpenAPI and
full offline evidence pass. This correction changed no frozen FAERS semantic.

Independent Review001 then returned `FAIL — P0 0 / P1 2 / P2 0`, bound to the
exact reviewed 18-path manifest
`7788f4c9e062ba42e0f7a6386f7f65c0a43617d14e421f8b781c3b5d607dc3d3`.
Review record: `docs/reviews/M1B-FAERS-001-INDEPENDENT-REVIEW-001.md`, 3,961
bytes, SHA-256
`6c5837fa6cd0421112db8046e9151c6aa8db963b28817b68343cd88b88eb0ef0`.

P1-01 is mechanically remediated: the request now requires explicit serialized
`pt_values=("DIARRHOEA","NAUSEA","VOMITING")` and
`statistical_unit="provider_count_occurrence"`; omission, drift, inference
variants, and accepted-instance bypass reject.

P1-02 is mechanically remediated under the Owner's additional path authority.
The public `faers_query_requests` field now admits 0..8 exact frozen request
elements, iff FAERS is in scope, ordered and unique by drug/identity strategy.
`M1BSourceSection` is a discriminated DailyMed/FAERS union; report validation
binds every FAERS section to its exact request, query, trusted acquisition
reference, outcome, run/source ownership, and canonical same-source ordinal.
The enabled OpenAPI and normalized fixture expose this additive surface without
adding `/v1/research/faers` or relaxing the DailyMed-only endpoint validator.

Independent Review002 returned `FAIL — P0 0 / P1 1 / P2 0`, binding exact
22-path manifest
`69dc5b2fca5971aac5d62a56c2f46b187a2630c0e12ff9ed32c51dbecf770fdf`
and the 10,001-byte delivery SHA-256
`d8e7dc599cdb6c947bfae42e0f71e1dd81e650deaf653a1b1b059e7f6d23e478`.
It verified both Review001 closures and retracted its provisional transport
tuple concern. Its sole P1 is remediated in final cycle 3/3: both frozen date
ceilings are required serialized literal bounds and therefore participate in
the existing query-ID preimage; omission, drift, and accepted-instance bypass
reject.

## Validation evidence

Fresh root evidence supplied at this join:

- focused four authorized domain test files with `--disable-socket`:
  `364 passed in 0.66s`;
- byte-exact OpenAPI, offline-boundary, and dependency-boundary selection:
  `19 passed in 1.17s`, with one expected socket-block warning;
- `uv run --locked --no-sync ruff check .`: PASS;
- `uv run --locked --no-sync ruff format --check .`: `83 files already formatted`;
- `uv run --locked --no-sync mypy src`: PASS for `40` source files;
- full offline unit and contract suite with sockets disabled and coverage:
  `1255 passed`, two expected warnings, `79%` coverage, `16.25s`;
- `git diff --check`: PASS;
- exact authorized-path comparison: PASS.

Fresh cycle-1 remediation evidence:

- focused four authorized domain files: `364 passed in 0.69s`;
- OpenAPI, offline socket boundary, and dependency boundary: `19 passed in
  1.06s`, one expected socket-block warning;
- Ruff: PASS;
- format: `83 files already formatted`;
- MyPy: PASS for 40 source files;
- `git diff --check`: PASS.

Fresh cycle-2 validation evidence:

- focused four domain files with sockets disabled: `383 passed in 0.73s`;
- API/OpenAPI, offline-network, and dependency-boundary selection with sockets
  disabled: `130 passed`, two expected warnings, `3.43s`;
- byte-exact OpenAPI contract alone: `8 passed in 1.14s`;
- `uv run --locked --no-sync ruff check .`: PASS;
- `uv run --locked --no-sync ruff format --check .`: `83 files already formatted`;
- `uv run --locked --no-sync mypy src`: PASS for `40` source files;
- full offline unit and contract suite with sockets disabled and coverage:
  `1275 passed`, two expected warnings, `80%` coverage, `17.13s`;
- `git diff --check`: PASS;
- changed paths remain inside the Owner-expanded remediation allowlist.

Fresh cycle-3 validation evidence:

- focused four domain files with sockets disabled: `384 passed in 0.72s`;
- API/OpenAPI, offline-network, and dependency-boundary selection with sockets
  disabled: `130 passed`, two expected warnings, `3.21s`;
- byte-exact OpenAPI contract alone: `8 passed in 1.15s`;
- `uv run --locked --no-sync ruff check .`: PASS;
- `uv run --locked --no-sync ruff format --check .`: `83 files already formatted`;
- `uv run --locked --no-sync mypy src`: PASS for `40` source files;
- full offline unit and contract suite with sockets disabled and coverage:
  `1276 passed`, two expected warnings, `80%` coverage, `16.79s`.
- `git diff --check`: PASS.

Independent Review003 returned `PASS — P0 0 / P1 0 / P2 0` for the exact
22-path candidate whose canonical 2,256-byte manifest preimage has SHA-256
`bddadeeade832b763cd0f37e0ce15e666e03e0ee2a0eb627651c7fda57100859`.
It bound this delivery before review at 11,420 bytes/SHA-256
`9b2fe38627e102d4470ce3186a99087de7dcad317908e0de382cb90a1d307a20`
and the combined review before append at 7,725 bytes/SHA-256
`2a5e20d2a650a279b348281bef9c2d7cbd6f02feb34db4a658c999b5d9f7e9a3`.
Fresh reviewer evidence was focused `384/0.65s`; API/boundary `130`, two
expected warnings, `3.22s`; OpenAPI `8/1.08s`; full offline `1276`, two expected
warnings, `80%/16.00s`; Ruff, format `83`, MyPy `40`, diff, scope, and encoding
PASS. At that review gate, terminal audit remained pending.

No test result above is live-source, terminology-release, clinical, connector,
persistence, database, or production evidence.

## Exact candidate manifest

The manifest deliberately excludes this `.delivery` record to avoid a
self-referential identity. It covers exactly the 21 current implementation,
test, fixture, ADR, historical-review-status, and governing-document paths.

Algorithm: convert paths to POSIX separators; sort with
`[StringComparer]::Ordinal`; emit each row as
`path<TAB>byte_count<TAB>lowercase_file_sha256`; join the UTF-8 rows with LF and
no terminal LF; SHA-256 the resulting bytes.

Manifest SHA-256:
`a58bfa4db4a72106bef9fbb00cd3f0cd0890d9f70f932ff3f36cae0db1909181`

```text
docs/ARCHITECTURE.md	28195	c04c0aa3b1f9021121099f8dfb80593b21041ca63d00ef408de22f7867f41fea
docs/DATA_SOURCES.md	16180	8f036a694e16978fa0f94002aaf1f24f2d2b48657f5ccd0b1e9389c04ab0769e
docs/decisions/ADR-012-m1b-faers-contracts.md	5893	925a774faed4174a5134d471d626a6c20af4431f60baf14cf6def16851c22c68
docs/EVALUATION_PLAN.md	22343	8dd15cba1f25a6b1b21fbb9767818f7a3bed2fd23b61f9c1332d7b29db460ff8
docs/PRD.md	23285	e1f1c98d80c1c3d5f060cfb45547e26ba4efb284c9cbb80cac2cfa45bab1e12a
docs/reviews/M1B-FAERS-001-INDEPENDENT-REVIEW-001.md	9627	7baf0d371a06a1c6d8021ea73346fcb8776d2e13e00863aec8e8e217c2201fb6
docs/SECURITY.md	20129	bb35192594055031fdcd4d00679300e162f042abe85a7a555ba0445bb7e11647
docs/TRACEABILITY_MATRIX.md	45137	0cdb2bd581f45b33eae1ffd9c920f26e2152092c46588d73b0d6222c68f523f1
src/medevidence/api/app.py	9005	daff34d8e69d435f5ca97f4bdb874f8e1f8f66196398d4a8dd46ec10a44a4e9b
src/medevidence/domain/__init__.py	7650	e9450baf54e7d565ceeb96fb875845665782d061a8deb6c08b499483f69c5e98
src/medevidence/domain/claims.py	32325	5e8305f1af305bfddcd05ec9e89a44b6908a95b71a00373af76a0be1d59ac4f5
src/medevidence/domain/identifiers.py	12201	34ae9d4facfb23a83174450d68e6753c8a390414894a4a100caa787f5a44364b
src/medevidence/domain/reports.py	69188	1d5ee2d938521a4070c1b0650003bf3364b8b9792b763d7ffa093ce7c9faf41c
src/medevidence/domain/scope.py	15702	8aafdb1e945a90c8e869a4771ab8e3c2f01f2c13a0c6ac184897940ee999e1c0
src/medevidence/domain/sources.py	104763	fadc5dc9819dc4d486f09e984d2a0ae3c9c3dfde7acd8395cb2afbd7bc018737
tests/contract/api/test_openapi.py	19603	5129e1cb94b3f1f5c40d61bcef639e541842e5e07bf9fa9179807987314cc68a
tests/fixtures/api/openapi-v1.json	96741	b2fb6da8c1bc14daf30dc3003da54f22fbb98fbb70efb61828accf8a44ca6b36
tests/unit/domain/test_provenance.py	23756	869cda6b2f92ba6355dd0203f6683ef36a3f0b8eeeedf2d45d688d2caebb7124
tests/unit/domain/test_reports.py	147553	9da93fc1516d3b04e2ed5690af39096021d6f90daa601860a49cfbe9e414be16
tests/unit/domain/test_scope.py	21132	dfa9a2a34a101ab637171e6c9f8d64af272db2c17950b97eabbf7bfe0913eee4
tests/unit/domain/test_source_outcomes.py	30730	d10d521f1a3241024502de1399df878de4c2809511d7832e2fd8a7e93e811236
```

## Operations and remaining gates

- Network and medical-source requests: none.
- FAERS/openFDA endpoint requests: none.
- Dependency changes: none.
- Docker operations: none.
- Database or migration operations: none.
- Git stage, commit, push, PR, CI, ready, merge, fetch, pull, or local-main
  integration: none.

Terminal Audit001 has passed; final-byte rebind remains required before the
authorized Git lifecycle continues. M1B-FAERS-002 must not start.

## Remaining gates

Terminal audit is complete. Final-byte rebind and the already authorized Git
lifecycle remain pending. This delivery record makes no completion, integration,
or FAERS-002 readiness claim.

## Terminal Evidence Audit 001

**PASS — P0 0 / P1 0 / P2 0**

Audited exact candidate:

- changed paths: `22`;
- canonical manifest preimage: `2,256` bytes;
- manifest SHA-256:
  `e572da3ef99f568dbfba27569c3921b5879ce76a68cf7f2d8b65432048aa6f97`;
- delivery before audit persistence: 12,014 bytes, SHA-256
  `240c94d0b93812815ba3f306dd9564f9ba2ad6f811124d93d1b4f8b93b4386cc`;
- combined review: 9,627 bytes, SHA-256
  `7baf0d371a06a1c6d8021ea73346fcb8776d2e13e00863aec8e8e217c2201fb6`.

The audit confirmed Review003 remains valid for its exact reviewed manifest
`bddadeeade832b763cd0f37e0ce15e666e03e0ee2a0eb627651c7fda57100859`
and the 7,725-byte review prefix SHA-256
`2a5e20d2a650a279b348281bef9c2d7cbd6f02feb34db4a658c999b5d9f7e9a3`.
It verified the required request fields, typed 0..8/union/ownership/OpenAPI
closure, date bounds `365`/`366` in the exact query preimage, and all frozen
provider-count, no-role, PT, identity, transport-metadata, limitation,
compatibility, and no-FAERS-route semantics.

Fresh terminal-audit gates:

- focused domain: `384 passed in 0.73s`;
- API/OpenAPI/offline/dependency boundary: `130 passed`, two expected warnings,
  `3.55s`;
- byte-exact OpenAPI: `8 passed in 1.19s`;
- full offline: `1276 passed`, two expected warnings, `80%` coverage, `14.98s`;
- Ruff PASS; format `83`; MyPy `40`; diff, encoding, fixture, scope,
  dependencies, routes, and index checks PASS.

No network, medical-source, dependency, Docker, database, or Git operation
occurred. Persisting the audit changes evidence bytes, so a final-byte rebind is
still required before the already authorized Git lifecycle. This is not a
commit, completion, integration, or FAERS-002-readiness claim.
