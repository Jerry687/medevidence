# M1A live run 001 recovery and disposition

Updated: `2026-08-08`

Status: `M1A_LIVE_RUN_001_EXECUTED`; `LIVE_GATE_ACCEPTANCE_UNRESOLVED`;
`NO_RERUN_AUTHORIZED`;
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`;
`CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`; `NO_LIVE_PASS`;
`SECOND_RUN_OWNER_CONTROLLED`

Current baseline: PR #9 merge `e8e28ffbde7fa3994ff8aa71dd62a956250147c1`
Historical live-run code revision: PR #8 merge
`09cc42838475a4c1bab62050fbfeac14c5dd6761`

## Disposition

The separately authorized live command executed one bounded PubMed ESearch
request and exited `1`. The original acceptance record was not written because
the former test harness compared every response-header value as a substring of
the otherwise redacted summary. Harmless rate-limit values collided with safe
numeric summary text. This was a harness false positive, not evidence that a
credential, response body, header, complete URL, or source payload entered the
summary.

No rerun was performed. The existing raw response, journal, artifact link,
canonical manifest, and registration envelope remain immutable. The accepted
disposition is failed interoperability evidence, not a live PASS. This recovery
does **not** establish `M1A_LIVE_ACCEPTANCE_PASS`, complete M1A, authorize M1B
planning, or authorize a second live run.

## Interoperability root cause and offline after-state

The root cause is `CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`: the historical
client rejected the official external provider DOCTYPE before processing the
otherwise valid ESearch document. Raw response bytes were received; this was
not an NCBI outage.

After focused sockets-disabled parser and connector tests passed, the exact
retained 2,205 bytes were read offline without printing their content. The
bounded compatibility parser returned `PubMedSearchPage` with `count=676` and
`returned_identifier_count=100`; socket calls and external file-open calls were
zero. The raw, recovery, and manifest sizes and SHA-256 identities remain
unchanged. This after-state reclassifies the cause; it does not rewrite the
historical connector or persisted evidence outcomes. No rerun occurred, no
live PASS is claimed, and any second live run remains Owner-controlled.

See [M1A PubMed provider-DTD interoperability](M1A-PUBMED-DTD-INTEROPERABILITY.md)
for the bounded parser candidate and offline validation evidence.

## Recovered execution evidence

The recovery harness parsed the retained records through `RunIntent`,
`AcquisitionIntent`, `ArtifactLink`, `SnapshotManifest`, and
`AcquisitionRegistrationEnvelope`; recomputed each canonical identity; replayed
the manifest against the content-addressed raw artifact; and verified the frozen
code revision, exact M1A constrained limits, UTC ordering, acquisition linkage,
and outside-Git containment.

The exact retained raw bytes deterministically raise `InvalidPubMedXmlError`
from `parse_search_page` for the first search page. Together with
`failure_code=invalid_xml`, zero completed pages, one retained response,
`attempts_used=1`, and the frozen one-search-page code path, this reconstructs
the terminal connector outcome as:

```text
execution_status=failed
coverage_status=unavailable
result_status=indeterminate
valid_result_count=0
pages_completed=0
truncated=false
warning_codes=pubmed_source_unavailable
```

The persisted manifest and acquisition envelope separately and truthfully use
`failed / partial / indeterminate`: `_write_acquisition_evidence` preserves
received bytes by converting an unavailable-with-bytes connector result to a
partial persisted-evidence record. Persisted coverage is not treated as
connector coverage.

One retained response proves at least one request; `attempts_used=1` proves at
most one, so the directly proved request count is exactly one. The failed first
search path yields no PMID and therefore cannot enter the fetch branch; the
exact run layout also contains no `acquisition-0001`. Fetch was not executed.

Directly proved UTC times are:

- run intent: `2026-08-08T23:40:56.289242Z`;
- search start: `2026-08-08T23:40:56.417743Z`;
- response observation: `2026-08-08T23:40:56.693859Z`; and
- search completion: `2026-08-08T23:40:56.694860Z`.

## Sanitized immutable-artifact inventory

All paths below are relative to the approved external run root.

| Relative path | Bytes | SHA-256 | Validated type/result |
|---|---:|---|---|
| `journal/978299dd-bb4a-4c60-accb-dd54c611029a/run-intent.json` | 1,097 | `585f4c07f0c3ee8d7b81b2d92efc173cd8fbb0a1396da8301dd57567046555cb` | canonical `RunIntent` |
| `journal/978299dd-bb4a-4c60-accb-dd54c611029a/acquisition-0000/acquisition-intent.json` | 1,016 | `770f3782720ba368f5f04dc142ac4451fd4ecf342dcabe8da2a36cd917f7d2a9` | canonical search `AcquisitionIntent` |
| `journal/978299dd-bb4a-4c60-accb-dd54c611029a/acquisition-0000/artifact-link-0000.json` | 548 | `e5b4afca908445653c61915f6a642ea321e546901375e1cd6dbd6b73e0be05b5` | canonical `ArtifactLink` |
| `journal/978299dd-bb4a-4c60-accb-dd54c611029a/acquisition-0000/registration-envelope.json` | 1,111 | `df13a35cd0e6cae0c98aa2f40767ce8d89ad7ed40e8b7f5f87f466ba0524a89b` | canonical linked acquisition envelope |
| `pubmed/manifests/sha256/fa/fab3ba93ab1f81e9bd6ca7b8bc705a5c065faced452dea33895f13d66151165a.json` | 1,380 | `fab3ba93ab1f81e9bd6ca7b8bc705a5c065faced452dea33895f13d66151165a` | canonical replayed `SnapshotManifest` |
| `pubmed/sha256/6a/6a9e93bae1247dd69771be66c13f05eb7c0e6efd11ddbd1ae33698b1fd1f6aa3.bin` | 2,205 | `6a9e93bae1247dd69771be66c13f05eb7c0e6efd11ddbd1ae33698b1fd1f6aa3` | exact bytes; `InvalidPubMedXmlError` |
| `acceptance/pubmed-live-run-001-recovery.json` | 3,032 | `1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf` | structurally validated, exclusive no-clobber recovery record |

Canonical logical identities are preserved in the recovery record, including
raw artifact ID
`sha256:6a9e93bae1247dd69771be66c13f05eb7c0e6efd11ddbd1ae33698b1fd1f6aa3`
and canonical manifest/snapshot ID
`sha256:fab3ba93ab1f81e9bd6ca7b8bc705a5c065faced452dea33895f13d66151165a`.
The recovery record contains no sensitive value, raw content, response header,
complete URL, or source payload.

## Harness correction

Cycle 4 is an exceptionally Owner-authorized, offline-only privacy correction
candidate. The live test owns no email, connector, provider result, raw bytes,
headers, URL/query parameters, or container holding those values. It performs
only marker/opt-in gating, calls one traceback-hidden sensitive executor, and
asserts fields on a frozen closed scalar result. The executor alone retrieves
the email and snapshot root, constructs/owns/closes the connector, persists
evidence, and converts connector, provider, helper, and close failures to a
new fixed-code test-only exception `from None`.

The acceptance validator receives only the proposed redacted record. Its key
normalization is punctuation- and case-insensitive, rejects the required
singular/plural private-field variants recursively, rejects complete URLs,
enforces a closed schema, validates typed outcomes and hash/path-only evidence
references, and permits only the exact fixed-false redaction flag schema. It
does not compare against or receive an actual email, raw body, response header,
or complete URL. Generic validation failures never interpolate rejected data.

Reviewer-triggered mechanical rework pass 1 replaced manual-only source-gate
coverage with an executor-rooted local-helper closure. The gate rejects direct,
module-aliased, and locally aliased `pytest.fail` references and infers any new
reachable raw-bearing helper even when it is omitted from the supplementary
registry. Exact negative regressions cover `fail = pytest.fail;
fail(provider.body)` and a newly reachable `provider.body` helper without
traceback hiding.

Final authorized mechanical rework pass 2 strengthened the same closure to
reject any use or reference of the `pytest` module or any propagated alias;
there is no legitimate pytest dependency inside the sensitive execution
boundary. Three exact negative cases cover local `p = pytest; p.fail(...)`,
module-level `p = pytest` followed by `p.fail(...)`, and
`fail = getattr(pytest, "fail"); fail(...)`.

Fresh cycle-4 node-local validation with live opt-in variables unset and
sockets disabled reports `38 passed, 8 deselected` for the privacy/static/
subprocess selection and `44 passed, 2 skipped` for the complete E2E module.
The nested child path ran with `-vv --showlocals --disable-socket`, failed with
only the fixed redacted harness message, and its parent proved that synthetic
email, raw-body, authorization-header, and complete-URL sentinels were absent
from captured output. Ruff and format checks pass. Reviewer-triggered internal
rework passes consumed: `2` of maximum `2`.

The external recovery record remains unchanged at 3,032 bytes and SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
No rerun or source request occurred. Independent review, terminal audit,
candidate identity, and integration evidence remain pending; this record does
not claim `M1A_LIVE_ACCEPTANCE_PASS`, `M1A_COMPLETE`,
`READY_FOR_M1B_OWNER_PLANNING`, reviewer PASS, audit PASS, commit, PR, or merge.
