# ADR-010: M1A remainder freeze amendment

- Status: Accepted by Project Owner; cycle-4 remediation hosted rerun passed, evidence reconciliation and integration pending
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-06
- Approval reference: `M1A-REMAINDER-FREEZE-v3`
- Revision: 1
- Independent review reference:
  [M1A-003A-INDEPENDENT-REVIEW-001](../reviews/M1A-003A-INDEPENDENT-REVIEW-001.md)
- Independent review role: Validation only; not an approving authority

## Context

ADR-009 froze exact PubMed raw-body snapshots and canonical manifests but did
not enumerate the later journal identity recipe, ordinal references, and
constrained-run capacity. The Owner selected namespaced, self-field-excluded,
terminal-LF-bearing identities. This is an append-only amendment; ADR-009
history remains unchanged.

## Decision

### Canonical identities and closed schemas

`M1A_CANONICAL_JSON_V1` rejects duplicate or unknown keys, floats, non-finite
numbers, `null`, and Boolean-as-integer values. Absent optionals are omitted.
Serialization is UTF-8 without BOM or normalization, sorted keys, compact
separators, `ensure_ascii=False`, `allow_nan=False`, and exactly one terminal
LF. The hash preimage is:

```text
ASCII(namespace) || NUL || canonical JSON bytes including LF
```

Only the applicable self field is removed. The identity-bearing record is
then persisted under the same profile. This recipe is separate from the
existing generic `canonical_json` and `derive_identity` behavior.

| Record | Namespace | Self field | Prefix | Length |
|---|---|---|---|---:|
| Run intent | `medevidence:m1a:run-intent:v1` | `run_intent_id` | `run-intent:sha256:` | 82 |
| Acquisition intent | `medevidence:m1a:acquisition-intent:v1` | `acquisition_intent_id` | `acquisition-intent:sha256:` | 90 |
| Artifact link | `medevidence:m1a:artifact-link:v1` | `link_id` | `artifact-link:sha256:` | 85 |
| Acquisition envelope | `medevidence:m1a:registration-envelope:acquisition:v1` | `registration_envelope_id` | `registration-envelope:acquisition:sha256:` | 105 |
| Run envelope | `medevidence:m1a:registration-envelope:run:v1` | `registration_envelope_id` | `registration-envelope:run:sha256:` | 97 |

The exact closed schemas are materialized as typed contracts in
`src/medevidence/ingestion/contracts.py`. They contain no open metadata map and
enforce the frozen run/search/fetch limits, runtime UUID4 IDs, catalog/query
fields, all seven outcome triples, ordered contiguous unique ordinal
references, exact failure-field presence, and direct run-report reference.
The structurally distinct reference types forbid self-links and cycles.
Immutable journal publication binds `run-intent.json` to `RunIntent`,
`acquisition-intent.json` to `AcquisitionIntent`, ordinal artifact-link
filenames to their matching `ArtifactLink`, and
`registration-envelope.json` to either concrete registration-envelope type.
The caller supplies the separately approved preallocated relative directory.

### Exact deterministic vectors

Each displayed JSON object is the exact self-ID-stripped canonical text.
Append LF to obtain the stated byte length; prepend the applicable ASCII
namespace and NUL to obtain the SHA-256 preimage. The final ID is its table
prefix plus digest.

```json
{"adverse_event_concept_ids":["m1a.event.gastrointestinal"],"catalog_version":"m1a-concepts-v1","code_revision":"a3fd66477046c9e026d7b2222e882cd94a84d535","created_at_utc":"2026-08-06T12:00:00.000000Z","drug_concept_ids":["m1a.drug.semaglutide"],"execution_limits":{"max_acquisitions":101,"max_attempts":2,"max_cumulative_payload_bytes_per_acquisition":5242880,"max_pages":1,"max_payload_bytes_per_response":5242880,"max_publications":100,"max_query_characters":512,"max_raw_responses_per_acquisition":4,"max_raw_responses_per_run":404,"max_redirects":1,"page_size":100,"total_deadline_ms_per_acquisition":30000},"execution_profile_id":"M1A_CONSTRAINED_V1","pubmed_query":"(\"semaglutide\"[Title/Abstract]) AND (\"gastrointestinal\"[Title/Abstract])","request_id":"request:00000000-0000-4000-8000-000000000001","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","scope_id":"scope:sha256:6806e021895ff9d0f62b33691db00baf8e64df8fc6c879dd9705e55e640be950","source":"pubmed"}
{"acquisition_ordinal":0,"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","created_at_utc":"2026-08-06T12:00:01.000000Z","execution_limits":{"base_backoff_ms":250,"cache_policy":"none","connect_timeout_ms":5000,"jitter_ms":100,"max_attempts":2,"max_backoff_ms":4000,"max_payload_bytes":5242880,"max_redirects":1,"max_retry_after_ms":10000,"pool_timeout_ms":5000,"read_timeout_ms":10000,"total_deadline_ms":30000,"write_timeout_ms":5000},"execution_profile_id":"M1A_CONSTRAINED_V1","operation":"search","request":{"db":"pubmed","path":"/entrez/eutils/esearch.fcgi","retmax":100,"retmode":"xml","retstart":0,"term":"(\"semaglutide\"[Title/Abstract]) AND (\"gastrointestinal\"[Title/Abstract])"},"run_id":"run:00000000-0000-4000-8000-000000000002","run_intent_id":"run-intent:sha256:9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3","schema_version":"1.0","source":"pubmed"}
{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","artifact_id":"sha256:6eb820e0f9762c611c2a77189f686afeca64dfb212e023017e0346e7ab826c39","artifact_kind":"pubmed_http_response","body_complete":true,"byte_size":6,"http_status":200,"media_type":"application/xml","observed_at_utc":"2026-08-06T12:00:02.000000Z","ordinal":0,"schema_version":"1.0","termination_reason":"complete_response"}
{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","artifact_id":"sha256:6eb820e0f9762c611c2a77189f686afeca64dfb212e023017e0346e7ab826c39","artifact_kind":"pubmed_http_response","body_complete":true,"byte_size":6,"http_status":200,"media_type":"application/xml","observed_at_utc":"2026-08-06T12:00:02.000000Z","ordinal":1,"schema_version":"1.0","termination_reason":"complete_response"}
{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","acquisition_ordinal":0,"artifact_links":[],"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","attempts_used":2,"completed_at_utc":"2026-08-06T12:00:05.000000Z","coverage_status":"unavailable","envelope_kind":"acquisition","execution_status":"failed","failure_code":"transport","manifest_id":"sha256:882cc8b218bbda8d2b09f876cf85572a34d71ae9ee5b219dc0e0172b7381384b","operation":"search","pages_completed":0,"redacted_detail":"café","registration_state":"ready_for_insert","result_status":"indeterminate","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","source":"pubmed","started_at_utc":"2026-08-06T12:00:01.000000Z","truncated":false,"valid_result_count":0,"warning_codes":["source_unavailable"]}
{"acquisition_intent_id":"acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d","acquisition_ordinal":0,"artifact_links":[{"link_id":"artifact-link:sha256:2f8434e5e24961345317bab57bac64258cc1c90bb48345b3059f15417b6cf5c5","ordinal":0},{"link_id":"artifact-link:sha256:7fa751bc6e92282f0fecb59a1448a824e39b5f0045bf7fdb365549ca5add838a","ordinal":1}],"attempt_id":"attempt:00000000-0000-4000-8000-000000000003","attempts_used":1,"completed_at_utc":"2026-08-06T12:00:04.000000Z","coverage_status":"complete","envelope_kind":"acquisition","execution_status":"succeeded","manifest_id":"sha256:b773825e8ed1ea53d961ca97debe5e1cdd622112bb983fd2cba6bdc7be0f21d4","operation":"search","pages_completed":1,"registration_state":"ready_for_insert","result_status":"matches","run_id":"run:00000000-0000-4000-8000-000000000002","schema_version":"1.0","source":"pubmed","started_at_utc":"2026-08-06T12:00:01.000000Z","truncated":false,"valid_result_count":2,"warning_codes":[]}
{"acquisition_registrations":[{"acquisition_registration_envelope_id":"registration-envelope:acquisition:sha256:3febdc11e8ebca14a433a7798653d7a85d3aa3385596649ff41a1911d506f4f3","run_ordinal":0}],"completed_at_utc":"2026-08-06T12:00:06.000000Z","coverage_status":"complete","envelope_kind":"run","registration_state":"ready_for_insert","report_artifact_id":"sha256:a6070e92bca201ba4b41003b1a4283631b1655e7c700a9a62b3c82ee8b0a630a","report_byte_size":1024,"report_id":"report:sha256:15d5c59556be02904a08a6b469ee4caa94df11963b39e0207acc7012c6531fa2","report_media_type":"application/json","report_status":"draft","result_status":"matches","run_id":"run:00000000-0000-4000-8000-000000000002","run_intent_id":"run-intent:sha256:9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3","run_status":"completed","schema_version":"1.0","started_at_utc":"2026-08-06T12:00:00.000000Z","warning_codes":[]}
```

| Vector | Bytes | Digest |
|---|---:|---|
| Run intent | 996 | `9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3` |
| Acquisition intent | 899 | `fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d` |
| Link 0 | 454 | `2f8434e5e24961345317bab57bac64258cc1c90bb48345b3059f15417b6cf5c5` |
| Link 1 | 454 | `7fa751bc6e92282f0fecb59a1448a824e39b5f0045bf7fdb365549ca5add838a` |
| Zero-link envelope | 854 | `2e112576a8189251bdada4331fd192b462263938564e0ddb68ed352fd5bceffa` |
| Two-link envelope | 998 | `3febdc11e8ebca14a433a7798653d7a85d3aa3385596649ff41a1911d506f4f3` |
| Run envelope | 905 | `fbebd711453be4be772e0eeec23dbffd788357b23bb34877cebbdad4d438cfb2` |

Negative controls are LF removed
`2ceff0d4f475a27f7645b3a7ce1a0aa20788a3658b0c64be6b529224ed224d5b`,
CRLF `fe63963dc54dcef3bce1ab536e5705d4022480e813ced2a482bff463a16e5817`,
self included
`d029fe5e18602cb7cb1572c5a51d78ad0ae931dfff3fa9391629e1067549436f`,
NFD `7c110a1cb9c1bec65008d16ebbd9c08d29a073f87a513463b5d6dd44273147b6`,
and run-envelope/acquisition-namespace
`8ce3a97088fa6c1521c72031f8cf66275356248272961ca1e6d292b7db0532c3`.
Invalid order, duplicate/missing ordinal, and unknown fields reject pre-hash.

### Snapshot, manifest, and capacity contract

Exact raw bodies use
`<root>/pubmed/sha256/<first2>/<digest>.bin`. Same-directory temporary writes
are flushed, fsynced, verified, and published only when absent. Raw, journal,
and manifest files share this lock-gated publication primitive. Existing files
are verified, never overwritten. Containment rejects symlink/reparse traversal.
Recovery observes only one exact contained directory and retains incomplete
prefixes as opaque bytes. One nonblocking writer owns the zero-byte
`<root>/.m1a-constrained-v1.lock`.

Closed canonical manifests include source/request identity, attempt times,
count, status triad, warnings, ordered retry file metadata,
connector/schema/code revision, and retention policy. Earlier retained
incomplete/error attempts remain visible; complete coverage requires its
terminal effective response to be nonempty, body-complete, and HTTP 2xx.
Every `matches` outcome also requires at least one retained nonempty HTTP 2xx
body or prefix, even when a later retained failure ends partial coverage.
Their ID is SHA-256 over complete canonical bytes.
They use
`<root>/pubmed/manifests/sha256/<first2>/<digest>.json`. Maximum size is
1,048,576 bytes. Replay checks canonical bytes, schema, raw path, size, and
hash and binds expected manifest, ordered link metadata, and validated count.
Unavailable execution may use a zero-file manifest.

Frozen capacity is 1,214 persistent files, 1,215 including the root lock,
1,216 at temporary peak, 8,425,963,520 committed bytes, 12,720,930,816
temporary peak bytes, and a 13,958,643,712-byte initial floor. The default
ledger accounts for committed and incomplete files on disk; bounded probes
remain injectable for deterministic boundary tests.

## Alternatives considered

- Reuse generic identities without namespace/NUL/LF.
- Substitute raw artifact IDs for relationship link IDs.
- Embed complete link tuples in envelopes.
- Overwrite content-addressed paths.
- Create a run-scoped artifact link for the report.

## Consequences

Logical journal identity, raw identity, and complete-file integrity remain
distinct. Ordinal multiplicity is preserved. The report is a direct run
envelope reference. M1A-003A adds no database, dependency, live source, tool,
API, report-generation, or export behavior.

## Validation

The implementation at `c3d724b2097c8df1249b217f610a78291039edbb` passed
vector/mutation, exact-byte,
no-clobber, corruption, capacity, containment, recovery, canonical fixture,
replay, connector handoff, dependency-boundary, Ruff, format, MyPy, and full
offline unit/contract checks. Terminal independent implementation review and
the pre-commit evidence audit passed. PR `#4` hosted run `31146015339` later
exposed a Windows CRLF checkout defect in the canonical LF fixture: Compose,
Ruff, format, and MyPy passed, while tests reported 422 passed and 2 failed.
Cycle 4 added only the exact fixture-specific `text eol=lf` rule in remediation
commit `52e71f0802e31580304980f487eba3c23f57db41`, whose parent is
`94e3d96f33e0752b34e6a016d19b9d1b7577f3f6` and whose exact seven paths
include root `.gitattributes`. The commit was pushed to PR `#4`.

A fresh `core.autocrlf=true` clone checked out `52e71f0`, reported
`text: set`/`eol: lf`, produced the 1,155-byte terminal-LF fixture with zero
CR bytes, and passed the two formerly failing tests 2/2. Hosted rerun
`31147466248` passed compose-config with 114 cases, Windows Ruff, format for 32
files, MyPy for 17 source files, and the offline unit/contract suite with 424
passed, one expected warning, and 86% coverage. Failed run `31146015339`
remains historical evidence.

Independent evidence-only review and terminal audit of the six-document
reconciliation candidate remain pending. Its later commit/push and hosted
rerun, PR readiness, merge, and approved-`main` integration also remain
pending. No final PR PASS, merge, integration, or live-source validation is
claimed.

## Supersedes / Superseded by

This record amends ADR-009 for the frozen M1A remainder identity, journal,
storage, and capacity details. It does not supersede or rewrite ADR-009.
