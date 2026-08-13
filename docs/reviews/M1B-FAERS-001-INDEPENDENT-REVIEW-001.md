# M1B-FAERS-001 Independent Review 001

## Verdict

**FAIL — P0 0 / P1 2 / P2 0**

Reviewed candidate:

- Branch: `feat/m1b-faers-001-contract-freeze`
- Baseline: `main@33213eca6b65ca90287ad2190ef22e21dc2104cc`
- Exact reviewed 18-path manifest SHA-256:
  `7788f4c9e062ba42e0f7a6386f7f65c0a43617d14e421f8b781c3b5d607dc3d3`
- Delivery record: 6,849 bytes; SHA-256
  `586fa1e45f00f5f5c18a3a88a5c27c28ad5c852bfd1bfe3ec6dd637fe963ff68`
- Owner Freeze: `M1B-OWNER-PLANNING-FREEZE-v8-faers-pt-owner-resolution-final-r1.md`,
  680,144 bytes, SHA-256
  `1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`
- Terminal planning Audit002: 11,989 bytes, SHA-256
  `2eaa64526d148d244573ab57e765702041b3a9c59bdeef0530678294538b484d`,
  `PASS — P0 0 / P1 0 / P2 0`.

The review inspected the complete candidate diff and executable behavior. Green
validation gates do not override the contract defects below.

## P1-01 — FAERS request omits two frozen required-present fields

`FaersAggregateRequestV1` does not serialize `pt_values` or
`statistical_unit`, although Owner Freeze H.1 requires both fields on the
request. Construction therefore accepts their omission because the properties
do not exist in the model.

Required closure:

- add immutable `pt_values` with exact serialized tuple
  `("DIARRHOEA","NAUSEA","VOMITING")`;
- add exact `statistical_unit="provider_count_occurrence"`;
- ensure both are present in every serialized request;
- reject omission, drift, alternate order, alias/case/spelling/normalization
  variants, and accepted-instance bypass;
- retain the existing provider-count endpoint mode and all other frozen fields.

Classification: implementation-local mechanical P1. It is remediable within
the authorized `scope.py` and mechanically dependent test/document paths.

## P1-02 — Frozen public FAERS envelope and source-section union are placeholders

`M1BResearchRequestV1.faers_query_requests` remains `tuple[()]`, and
`M1BSourceSection` remains only `DailyMedLabelSectionV1`. This contradicts
Owner Freeze H.1: `faers_query_requests` is a typed `FaersAggregateQueryV1`
tuple of cardinality 0..8, and the existing discriminated source-section union
must admit `FaersAggregateSectionV1` with exact source/request/outcome ownership.
The current public model schemas cannot accept a FAERS request or FAERS section.

Implementing that required public union changes the enabled DM003 OpenAPI
generated from the shared models. The M1B-FAERS-001 K.4 allowlist denies the API
contract and byte-exact OpenAPI fixture paths needed to keep generated OpenAPI,
runtime validation, required-field parity, and contract fixtures truthful.
A schema override would conceal runtime/public drift and is rejected.

Classification: authorization-boundary conflict. Closure requires explicit
Owner authority to expand the file boundary to the mechanically dependent API
contracts, OpenAPI contract tests, and normalized OpenAPI fixture while
preserving M1A and DailyMed compatibility. This review does not authorize or
implement that expansion.

## Reviewed validation evidence

- focused domain tests: `364 passed`;
- byte-exact OpenAPI/offline/dependency selection: `19 passed`, one expected
  socket-block warning;
- Ruff: PASS;
- format: `83 files already formatted`;
- MyPy: PASS for 40 source files;
- full offline: `1255 passed`, two expected warnings, 79% coverage;
- diff and exact path-scope checks: PASS.

These gates are overridden by P1-01 and P1-02.

## Operations and consequence

No FAERS/openFDA or other medical-source request, network operation, dependency
change, Docker/database operation, Git mutation, or M1B-FAERS-002 work occurred.

P1-01 may be mechanically remediated within cycle 1/3. P1-02 requires an Owner
authorization decision. Independent review PASS, terminal audit, commit, push,
PR, CI, merge, integrated verification, `M1B-FAERS-001_COMPLETE`, and
`READY_FOR_M1B-FAERS-002` are prohibited from this candidate.

## Post-review remediation status

Review 001 remains an immutable FAIL decision for its exact reviewed candidate.
Cycle 1/3 mechanically closed P1-01. After the Owner explicitly expanded the
mechanically dependent API/OpenAPI path authority, cycle 2/3 implemented P1-02:
the request envelope now carries the exact bounded typed FAERS tuple, the report
uses a `section_kind`-discriminated DailyMed/FAERS union, external validation
requires the exact canonical request-owned acquisition/outcome union, and the
enabled OpenAPI/fixture represents the additive models without adding a FAERS
route. These changes await a fresh complete Independent Review 002; this note
does not revise the Review 001 verdict or claim PASS.

## Independent Review 002

### Verdict

**FAIL — P0 0 / P1 1 / P2 0**

Reviewed candidate:

- exact 22-path manifest SHA-256:
  `69dc5b2fca5971aac5d62a56c2f46b187a2630c0e12ff9ed32c51dbecf770fdf`;
- delivery record: 10,001 bytes, SHA-256
  `d8e7dc599cdb6c947bfae42e0f71e1dd81e650deaf653a1b1b059e7f6d23e478`;
- branch and baseline remain the identities recorded above.

Review 002 verified the Review 001 P1-01 and P1-02 closures. It also reproduced
and retracted a provisional transport retry/permanent-policy concern: the fixed
positional tuple contracts reject omission, duplication, and reordering, so it
is not a finding.

### P1 — FAERS query identity omits frozen date-bound constants

`FaersAggregateQueryV1.query_id` is derived from the serialized closed query,
but `FaersExecutionBoundsV1` omits the frozen
`max_date_difference_days=365` and `max_inclusive_calendar_dates=366` values.
Owner Freeze E.3 requires the exact start/end dates and all bounds to participate
in query identity. The reviewed fixture-dependent exemplar produced a current
identity beginning `688b...`, versus `4b12...` when the frozen date constants
were included in the formula; those prefixes are illustrative, not universal
contract identities.

Required closure is to add both exact literal fields to the serialized bounds,
thereby including them in request, query, OpenAPI, and the existing query
identity preimage; require their presence; reject omission, drift, and
accepted-instance bypass; and prove the exact formula and date validation remain
closed. Classification: implementation-local mechanical P1, authorized for
final remediation cycle 3/3.

### Reviewed gates and operations

- focused domain: `383 passed`;
- API/OpenAPI/offline/dependency selection: `130 passed`, two expected warnings;
- Ruff, format (`83` files), MyPy (`40` source files), diff and scope: PASS;
- full offline: `1275 passed`, two expected warnings, `80%` coverage;
- no network, medical-source, dependency, Docker, database, Git, or FAERS-002
  operation occurred.

Green gates are overridden by the confirmed P1. Review 002 remains immutable
FAIL evidence for its exact candidate. Fresh Review 003 and terminal audit are
required after cycle 3/3 remediation.

### Post-Review 002 remediation status

Review 002 remains immutable FAIL evidence for its exact candidate. Final
authorized cycle 3/3 adds required serialized
`max_date_difference_days=365` and
`max_inclusive_calendar_dates=366` literals to `FaersExecutionBoundsV1`.
Because the existing query preimage serializes the complete bounds model, both
now participate in `FaersAggregateQueryV1.query_id` together with exact start
and end dates. Tests reject omission, either literal's drift, and forged-model
bypass, and recompute the exact identity formula. The OpenAPI fixture is
regenerated additively; default PubMed digests and the PubMed-plus-DailyMed
route inventory remain unchanged. Fresh complete Review 003 and terminal audit
remain pending; this status does not revise either historical FAIL verdict.

## Independent Review 003

### Verdict

**PASS — P0 0 / P1 0 / P2 0**

Reviewed exact candidate:

- changed paths: `22`;
- canonical manifest preimage: `2,256` bytes;
- manifest SHA-256:
  `bddadeeade832b763cd0f37e0ce15e666e03e0ee2a0eb627651c7fda57100859`;
- pre-review delivery: 11,420 bytes, SHA-256
  `9b2fe38627e102d4470ce3186a99087de7dcad317908e0de382cb90a1d307a20`;
- this combined review before the Review003 append: 7,725 bytes, SHA-256
  `2a5e20d2a650a279b348281bef9c2d7cbd6f02feb34db4a658c999b5d9f7e9a3`.

The complete independent review verified all historical finding closures:

- required-present exact request `pt_values` and `statistical_unit`;
- typed 0..8 FAERS request tuple, discriminated source-section union, canonical
  request/acquisition/outcome ownership, and truthful enabled OpenAPI;
- required exact serialized date-bound literals `365` and `366` in the complete
  query-ID preimage;
- preservation of the frozen provider-count, no-role, PT, date, identity,
  bounds, transport-metadata, result, limitation, and research-only semantics;
- unchanged M1A/PubMed compatibility, retained DailyMed route behavior, and no
  `/v1/research/faers` route.

Fresh independent-review gates:

- focused four-domain selection: `384 passed in 0.65s`;
- API/OpenAPI/offline/dependency boundary selection: `130 passed`, two expected
  warnings, `3.22s`;
- byte-exact OpenAPI: `8 passed in 1.08s`;
- full offline unit/contract suite: `1276 passed`, two expected warnings, `80%`
  coverage, `16.00s`;
- Ruff PASS; format `83` files; MyPy `40` source files; diff, scope, and encoding
  checks PASS.

No network, medical-source, dependency, Docker, database, Git, or FAERS-002
operation occurred. Review003 passes the independent-review gate for the exact
reviewed bytes. Terminal evidence audit remains mandatory; this is not a
completion, commit, integration, or FAERS-002-readiness claim.
