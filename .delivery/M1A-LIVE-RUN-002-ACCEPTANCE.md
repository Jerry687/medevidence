# M1A live PubMed run 002 acceptance

Updated: `2026-08-09`

Status: **M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE;
M1A_LIVE_RUN_002_ACCEPTED; M1A_LIVE_ACCEPTANCE_PASS; M1A_COMPLETE;
READY_FOR_M1B_OWNER_PLANNING**

## Decision

The validated, redacted acceptance record for the separately authorized live
run 002 satisfies the frozen M1A live-query contract. Run 002 is accepted as
`M1A_LIVE_RUN_002_ACCEPTED` and establishes `M1A_LIVE_ACCEPTANCE_PASS`.
Together with the already integrated offline M1A vertical slice, this closes
M1A as `M1A_COMPLETE` and makes the repository
`READY_FOR_M1B_OWNER_PLANNING`.

This state does not start M1B, authorize an M1B implementation, authorize
another medical-source request, or make the draft report exportable or
clinical. The live-run authority was consumed and `rerun_authorized=false`.

## Acceptance artifact

Only safe labels and redacted identities are recorded here. Raw and normalized
source content remains outside Git.

| Field | Accepted value |
|---|---|
| External root label | `OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT` |
| Acceptance relative label | `acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json` |
| Acceptance size | `3,223` bytes |
| Acceptance SHA-256 | `008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25` |
| Executed at | `2026-08-09T05:13:33.284549Z` |
| Schema / connector | `1.0` / `m1a-002` |
| Code revision | `531f867006f3d01ebbc14633ad6e5509e4e70a47` |
| Retention policy | `M1A-LIVE-RETENTION-v1` |
| Rerun state | no rerun occurred; `rerun_authorized=false`; live authority consumed |

The exact accepted query was:

```text
("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])
```

## Bounded execution and outcomes

Run 002 comprised one run and two contiguous acquisitions. It used exactly two
requests: one search request and one fetch request.

| Operation | Terminal outcome | Valid results | Pages | Truncated | Acceptance meaning |
|---|---|---:|---:|---|---|
| Search | `succeeded / partial / matches` | 100 | 1 | `true` | The enforced first-page bound was reached; coverage is explicitly partial and non-exhaustive. |
| Fetch | `succeeded / complete / matches` | 1 retained publication | 1 | `false` | The single authorized fetch acquisition completed within its bound. |

The search result is not exhaustive. Its 100 valid results establish only that
the bounded query returned matches within the acquired page. The one complete
fetch establishes only that one authorized retained publication was fetched;
it does not make the search exhaustive.

## Provenance identities

| Operation | Raw artifact ID | Manifest ID | Acquisition registration-envelope ID |
|---|---|---|---|
| Search | `sha256:e64697f75c00d30ef6866402895fc806b17ed25959d730fb74e7457ecbce6d19` | `sha256:f72204653a1d8ae28a8df2129863c3d8c6b952db4328685c5ab78aeafbec8f19` | `registration-envelope:acquisition:sha256:b993505a82ac234f3d26c0d111fc88009cef76c08e1ad9fca22b6140ee8cb8c9` |
| Fetch | `sha256:b955634d5c1c0965d14c5848444190f641abf1d1c186e85aa2c429fb055e5ceb` | `sha256:f1a0483f59808ab3855bdff96336b1f0a2efa78a716c64fb474cf4d263a9071b` | `registration-envelope:acquisition:sha256:d9d9546d4f79debed942d971aabafdf957b7fd97166fd067c36f42816a75541e` |

## Closed-contract validation

The external acceptance validation returned **PASS** for the closed record.
It recomputed raw, manifest, linkage, and envelope identities; verified that
the evidence is contained outside Git; and found:

- `0` reparse points;
- `0` unexpected absolute references;
- no temporary or unexpected files;
- exact false values for every redaction flag; and
- no forbidden normalized key, complete URL, raw XML, or abstract field.

Artifact-link logical identifiers and source-content fields are deliberately
not reproduced in this Git-tracked record.

The live-command result is operator-supplied evidence, not independently
inferred by this documentation node: the exact live test was selected, exited
`0`, reported `1 passed`, wrote the acceptance record, cleared the supplied
environment values, and left the repository clean immediately after the live
run. This documentation node did not rerun the test, read the client identity,
instantiate transport, or contact a medical source.

## Run 001 historical separation

Live run 001 remains permanently visible as
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`. It historically
ended `failed / unavailable / indeterminate`; received bytes were preserved
separately as `failed / partial / indeterminate`; fetch was not executed; and
it never established `M1A_LIVE_ACCEPTANCE_PASS`. Run 002 supplements that
history. It does not rewrite Run 001 as successful.

## Safety and evidence limits

The partial search is bounded and non-exhaustive. Neither it nor the single
retained publication establishes causality, incidence, prevalence, relative or
absolute risk, comparative product safety, diagnosis, treatment, dosing, or
any individualized clinical conclusion. Source limitations and publication
context remain mandatory. Any report remains a research-only,
non-exportable, non-clinical `draft` until its separately governed citation,
review, and export gates pass.

## Manual offline verification

1. Locate the Owner-held external root represented only by
   `OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT`; do not copy its absolute location
   into Git or logs.
2. Resolve only the acceptance relative label recorded above and verify that
   it is a regular contained file of exactly `3,223` bytes.
3. Recompute SHA-256 and compare it with the accepted digest above.
4. Parse the record offline and verify the exact query, execution timestamp,
   code revision, versions, retention policy, two contiguous acquisitions,
   request counts, outcome triads, truncation flags, and listed identities.
5. Re-run the closed-schema, containment, identity, and redaction validators
   offline. Do not select the live marker or instantiate transport.

## Owner interview questions

1. Why is `succeeded / partial / matches` with `truncated=true` a valid bounded
   search result but not an exhaustive evidence claim?
2. How do raw artifact, canonical manifest, and acquisition registration-
   envelope identities prove different parts of the retained lineage?
3. Why does `READY_FOR_M1B_OWNER_PLANNING` permit planning only, while M1B
   implementation and every further live request still require separate Owner
   authorization?
