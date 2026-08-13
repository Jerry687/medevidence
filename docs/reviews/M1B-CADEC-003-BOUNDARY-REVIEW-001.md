# M1B-CADEC-003 boundary review 001

- Status: `ADDITIONAL_MECHANICAL_CORRECTION_PENDING_FRESH_REVIEW`
- Work item: `M1B-CADEC-003`
- Branch: `feat/m1b-cadec-003-boundary-closeout`
- Baseline: `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`
- Candidate commit: none
- Reviewer: independent Review001
- Immutable Review001 verdict: `FAIL` - `P0 0 / P1 1 / P2 2`
- First remediation: batch 1/1 implemented
- Closure review: `FAIL` - `P0 0 / P1 1 / P2 1`
- Additional mechanical correction: Owner-authorized; fresh review pending

## Review objective

Independently verify that the six-path documentation candidate truthfully
closes Owner-frozen Option E: the integrated CADEC-002 exact external
loader/parser is the final executable M1B CADEC surface, while all text-bearing
materialization and `search_local_adr_corpus` ownership remain future M2 work
subject to `ME-000C`.

## Immutable upstream evidence to preserve

The review must preserve, not rewrite, the CADEC-001 and CADEC-002 historical
failure/remediation records:

- CADEC-001 feature `51bbe29a94aa3a16af5d55be01b06f6aa331ab44`, merge
  `af111b8efce0d2a47df4c3ba20f213a812ca12da`, PR #19, independent closure
  `PASS` at `P0 0 / P1 0 / P2 0` after immutable failure history, terminal
  audit `PASS` at `0/0/0`, aggregate
  `35a4d2349410c16209197c24e1900ca28067de993276d2c865be082c61548482`, PR
  quality run `31726952106` with both checks `SUCCESS`, and merged-main quality
  run `31727139728` `SUCCESS`;
- CADEC-002 feature `03fffef7ad8f68a9ca36c4961a5264b2e0b295ff`, merge
  `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`, PR #20, immutable initial
  review `FAIL` at `P0 0 / P1 2 / P2 0`, one remediation batch, independent
  closure and terminal audit each `PASS` at `0/0/0`, aggregate
  `d307456bcfb4b5cf20392d93e922fb75d0d5684d9e5064c8a811ac960f973d9a`, PR
  run `31748194823` and merged-main run `31748381436`, both with both checks
  `SUCCESS`.

## Required boundary checks

The independent reviewer must verify all of the following against the actual
candidate diff:

1. Exactly the six authorized documentation paths changed; no executable,
   test, dependency, external-evidence, database, or seventh path changed.
2. Exactly one visible CADEC M1B source plan entry has
   `planning_status=skipped_by_policy`,
   `reason_code=source_execution_not_authorized`, and the frozen human-readable
   reason. Visibility remains distinct from execution: the exact empty
   `cadec_query_requests` tuple and unchanged `M1BSourceSection` preserve no
   executable request, research-request connector invocation, `SourceOutcome`,
   report section, API/OpenAPI execution, or structured retrieval/search.
3. M1B exclusions are complete: persistence, migration, database ingestion,
   indexing, chunking, training, and retrieval evaluation.
4. The current output is metadata-only and not directly retrieval-consumable.
5. Future M2 owns both the text-bearing materializer and
   `search_local_adr_corpus`; it must reread and reverify the same exact
   external archive identity, preserve document/annotation/locator/split/
   Option-A lineage, emit exact chunks with bounded offsets and hashes, keep
   raw text outside Git, and remain subject to `ME-000C`.
6. Frozen facts remain exact: 1,250/1,248; the two named exclusions; malformed
   5; limitations 2/44/45=91; the two named empty documents with zero rows in
   all three layers; annotations/locators 24,478 partitioned
   9,089/6,300/9,089; sole exact CP1252 exception; split 992/119/137; provider
   gold only; REDIST, VOCAB, and Option-A provenance.
7. No document claims CADEC-003 independent-review PASS, terminal audit,
   commit, completion, or any post-terminal target as achieved. The markers
   `M1B-CADEC-003_COMPLETE`, `M1B-CADEC_VERTICAL_SLICE_COMPLETE`, and
   `READY_FOR_M2-CADEC-RETRIEVAL-PLANNING` remain targets only.
   `READY_FOR_M2-CADEC-RETRIEVAL-CONSUMPTION` is prohibited.
8. Medical-source requests and external CADEC evidence, database, and M2
   worktree access remain zero. Bounded read-only GitHub PR/check/run metadata
   requests used to verify integrated evidence are disclosed separately from
   prohibited live medical-source access; no remote mutation occurred.

## Writer-provided structural evidence

Writer evidence is limited to documentation structure and is awaiting
independent verification:

- exact six-path `git status` audit;
- `git diff --check`;
- UTF-8 without BOM, LF-only line endings, and final newline checks;
- local Markdown link/anchor checks where practical;
- searches for stale CADEC-001/002 candidate states and executable/prohibited
  boundary consistency;
- file SHA-256 hashes bound after final writer validation.

No application suite is required because executable bytes are unchanged.
Read-only inspection of existing executable files was allowed and performed
for review/evidence; no executable or test file was modified. Writer structural
evidence does not constitute an independent-closure verdict.

## Immutable Review001 findings and verdict

Review001 is immutably `FAIL` at `P0 0 / P1 1 / P2 2`:

1. `P1`: PRD generic M1B source-workflow and partial-coverage wording
   contradicted Owner-frozen Option E, while the `V1-FR-005` traceability row
   assigned CADEC search, chunking, indexing, and gold/predicted parsing to M1B.
   Exactly one CADEC M1B plan entry must remain visible with
   `planning_status=skipped_by_policy`; visibility is distinct from prohibited
   execution, with no executable request, research-request connector
   invocation, `SourceOutcome`, report section, or API/OpenAPI execution.
2. `P2`: delivery/review network accounting incorrectly stated that no other
   network request occurred. Bounded read-only GitHub PR/check/run metadata
   access occurred; medical-source, archive, database, and M2 access remained
   zero, and no remote mutation occurred.
3. `P2`: delivery/review access and test rationale incorrectly stated that
   executable/test-file access was forbidden. Read-only executable and test
   inspection was allowed and performed, no executable or test bytes changed,
   and no application suite was required.

These findings and the Review001 `FAIL` verdict are immutable and are not
rewritten by remediation.

## Remediation batch 1/1

The single Owner-authorized mechanical batch:

- carves CADEC out of PRD generic M1B workflow, `SourceOutcome`, and partial-
  coverage wording while retaining fail-closed standalone loader verification;
- rewrites the `V1-FR-005` row around the completed M1B exact loader/parser and
  metadata-only output, with materialization/search assigned only to future M2
  after `ME-000C`, and removes M1B predicted-parse/chunk/index/search claims;
- corrects network accounting to disclose bounded read-only GitHub metadata
  access separately from zero medical-source/archive/database/M2 access and
  zero remote mutation; and
- records that no application suite is required because executable bytes are
  unchanged, while read-only executable inspection was allowed and performed.

## Closure review after remediation batch 1/1

The closure review remains a separate historical lifecycle event with verdict
`FAIL` at `P0 0 / P1 1 / P2 1`:

- `P1`: the first remediation overreached from no CADEC source execution to no
  visible CADEC plan entry, contrary to the durable exactly-one-plan invariant;
- `P2`: the review record required exact Review001 transcription fidelity,
  preserving the original one-P1/two-distinct-P2 taxonomy and findings without
  merging or reclassifying them.

This closure-review failure does not rewrite the immutable Review001 findings,
IDs, classification, severity, evidence, or `P0 0 / P1 1 / P2 2` verdict.

## Owner-authorized additional mechanical correction

The additional correction freezes exactly one visible CADEC M1B source plan
entry with `planning_status=skipped_by_policy`,
`reason_code=source_execution_not_authorized`, and reason `CADEC remains
visible in the M1B source plan, but source execution is not authorized under
Option E.` It distinguishes plan visibility from execution while preserving no
executable request, research-request connector invocation, `SourceOutcome`,
report section, API/OpenAPI execution, or M1B retrieval/search surface.

Current state is `ADDITIONAL_MECHANICAL_CORRECTION_PENDING_FRESH_REVIEW`. A
fresh independent review must inspect the actual corrected diff and final
bytes. No fresh-review PASS, terminal evidence audit, commit, completion, or
post-terminal marker is claimed.
