# M1A live PubMed run 002 acceptance review candidate 001

- Review reference: `M1A-LIVE-RUN-002-ACCEPTANCE-001`
- Work item: `M1A-LIVE-RUN-002-ACCEPTANCE`
- Branch: `docs/m1a-live-run-002-acceptance`
- Approved implementation baseline and live code revision:
  `531f867006f3d01ebbc14633ad6e5509e4e70a47`
- Evidence validation: **PASS**
- Initial independent review: **FAIL - P0 0 / P1 1 / P2 0**
- Remediation cycles consumed: `2` of maximum `2`
- Final independent re-review: **PASS - P0 0 / P1 0 / P2 0**
- Terminal evidence audit: **PENDING**
- Hosted CI and merge: **PENDING**

## Candidate decision

Validated external evidence supports the Owner-frozen target disposition:

`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`;
`M1A_LIVE_RUN_002_ACCEPTED`; `M1A_LIVE_ACCEPTANCE_PASS`; `M1A_COMPLETE`;
`READY_FOR_M1B_OWNER_PLANNING`.

This record binds the completed independent re-review of the actual corrected
six-path candidate; the documentation author is not its sole approver. The
terminal evidence audit, hosted CI, and every later Git lifecycle gate remain
pending and are not claimed.

## Authorized scope

The candidate is limited to:

- `.delivery/M1A-LIVE-RUN-002-ACCEPTANCE.md`;
- `docs/reviews/M1A-LIVE-RUN-002-ACCEPTANCE-001.md`;
- `.delivery/STATE.md`;
- `.delivery/M1A-LIVE-GATE-READINESS.md`;
- `README.md`; and
- `docs/TRACEABILITY_MATRIX.md`.

No source, test, dependency, schema, public-interface, security-boundary, or
evidence-semantics change is part of this candidate.

## Completed evidence validation

The redacted acceptance record is labeled
`acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json` beneath the
external root label `OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT`. It is `3,223` bytes
with SHA-256
`008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`.
It binds schema `1.0`, connector `m1a-002`, code revision
`531f867006f3d01ebbc14633ad6e5509e4e70a47`, execution time
`2026-08-09T05:13:33.284549Z`, and retention policy
`M1A-LIVE-RETENTION-v1`.

The accepted run contains one run, two contiguous acquisitions, and exactly
two requests: one search and one fetch. Search is
`succeeded / partial / matches`, with 100 valid results, one page, and
`truncated=true`; it is bounded and non-exhaustive. Fetch is
`succeeded / complete / matches`, with one valid retained publication, one
page, and `truncated=false`.

The closed-contract validation passed identity recomputation, containment,
schema, redaction, and unexpected-file checks. It found zero reparse points,
zero unexpected absolute references, no temporary or unexpected files, exact
false redaction flags, and no forbidden normalized key, complete URL, raw XML,
or abstract field. External artifacts remain outside Git.

Operator-supplied evidence reports that the exact live test exited `0` with
`1 passed`, wrote the acceptance record, cleared supplied environment values,
and left the repository clean immediately after the authorized run. This docs
node did not independently rerun the live test or infer those operator facts.
No rerun occurred; the live authority is consumed and
`rerun_authorized=false`.

## Historical and safety findings

Run 001 remains failed-interoperability evidence and is not rewritten as a
PASS. Run 002 is the successful acceptance run. The partial search cannot
support an exhaustive no-result or completeness claim, and neither outcome
supports causal, incidence, comparative-risk, or clinical conclusions. The
report remains a research-only, non-exportable, non-clinical draft.

## Initial review finding and remediation cycle 1

The initial independent review returned
**FAIL - P0 0 / P1 1 / P2 0**. The reproducible P1 finding was a semantic
weakening in the `V1-FR-002` acceptance criterion: the candidate replaced the
frozen PubMed-specific label `PMID/version` with the generic label
`source/version`. That change weakened the exact source-specific traceability
contract even though the new partial, non-exhaustive, and non-exportable safety
wording was correct.

Remediation cycle 1 applies one mechanical correction in
`docs/TRACEABILITY_MATRIX.md`: restore the exact label `PMID/version` and leave
the added partial/non-exhaustive/non-exportable safety wording unchanged. This
review record is the only other file changed in the cycle, so the failed review
and remediation history remain visible.

The fresh independent re-review then examined the corrected candidate. Cycle 2
updates only this record to bind that review evidence; it makes no further
semantic or executable change.

## Final independent re-review

The fresh independent re-review returned
**PASS - P0 0 / P1 0 / P2 0**. It verified exactly the six authorized paths,
no executable changes, and a clean diff check. The cycle-1 correction restores
the exact `PMID/version` contract without changing the added bounded,
non-exhaustive, and non-exportable safety language.

### External acceptance rebind

The reviewer re-bound the external acceptance record at `3,223` bytes to
SHA-256
`008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`.
Closed validation and redaction passed across `13` files. The evidence contains
one run, two contiguous acquisitions, and two requests. It has zero reparse
points. Raw artifact, canonical manifest, and acquisition registration-envelope
identities were recomputed, cross-bound to their acquisitions, and remained
distinct identity classes.

The added-line privacy scan found zero complete URLs, external absolute paths,
or raw XML. No source content, provider diagnostic, credential, or disallowed
future identity was introduced.

### Semantic re-review

The reviewer confirmed that Run 001 remains failed-interoperability evidence
and is never represented as a PASS. Run 002 remains the accepted live run. The
search remains explicitly partial, bounded, and non-exhaustive; the complete
single fetch does not upgrade search coverage. `M1A_COMPLETE` permits only
`READY_FOR_M1B_OWNER_PLANNING`: M1B has not started and no later live request is
authorized. The draft remains research-only, non-exportable, and non-clinical.

### Fresh validation evidence

| Gate | Result |
|---|---|
| Focused live harness | PASS: `44 passed, 2 skipped`; the real live test was skipped |
| All E2E tests | PASS: `45 passed, 2 skipped` |
| Unit and contract tests with sockets disabled | PASS: `749 passed`, `2 warnings`, `79%` coverage |
| Ruff check | PASS |
| Ruff format check | PASS: `67` files |
| MyPy | PASS: `34` files |
| `uv lock --check --offline` | PASS |
| Local Markdown links | PASS |
| `git diff --check` | PASS |
| Exact six-path scope | PASS |

These gates were already executed as the fresh independent reviewer evidence;
this record-only cycle did not rerun a live test or contact a medical source.

## Pending gates

- terminal evidence audit of scope, safe-fact allowlist, and no-self-reference;
- any applicable hosted CI;
- any authorized local commit, push, PR, merge, or integration verification.

No future commit, PR-head, CI, merge, or post-merge cleanliness identity is
pre-claimed here. M1B has not started.
