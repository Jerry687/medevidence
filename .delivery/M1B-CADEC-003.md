# M1B-CADEC-003 delivery record

- Status: `M1B-CADEC-003_COMPLETE`; `M1B-CADEC_VERTICAL_SLICE_COMPLETE`;
  `READY_FOR_M2-CADEC-RETRIEVAL-PLANNING`
- Branch: `feat/m1b-cadec-003-boundary-closeout`
- Baseline: `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`
- Feature commit: `83617405e58bcec657bdaa84aceb8d2460d46fb1`
- Merge commit: `c226a632753e6fc65e8c84c74ec568d994612b7d`
- Pull request: #21 merged
- Immutable Review001: `FAIL` - `P0 0 / P1 1 / P2 2`
- First remediation: batch 1/1 implemented
- Closure review: `FAIL` - `P0 0 / P1 1 / P2 1`
- Additional mechanical correction: completed
- Fresh independent review: `PASS` - `P0 0 / P1 0 / P2 0`
- Terminal evidence audit: `PASS` - `P0 0 / P1 0 / P2 0`
- Completion: integrated

## Objective and boundary

Close the M1B CADEC documentation boundary around Owner-frozen Option E.
CADEC-002's exact external loader/parser is the final executable M1B CADEC
surface. M1B ends at exact archive/manifest input, one-open immutable-byte
verification, safe bounded loading/parsing, approved metadata-only documents,
provider-gold annotations, exact locators, Option-A provenance, and visible
limitations.

The current CADEC-002 output is metadata-only and is **not directly
retrieval-consumable**. The exact `cadec_query_requests` value remains
`tuple[()]`; `M1BSourceSection` remains unchanged. Repository governance
records CADEC as an explicitly known M1B source with
`planning_status=skipped_by_policy` and
`reason_code=source_execution_not_authorized`. Per-request runtime planning is
separate: `M1BResearchReportV1.source_plan` remains exactly
`scope.selected_sources`, DailyMed-only and FAERS-only plans remain
source-only, and CADEC is not added to `requested_sources`. Governance
visibility is distinct from execution and creates no executable request,
research-request connector invocation, `SourceOutcome`, report section, or
API/OpenAPI execution. M1B prohibits a structured retrieval/search tool,
persistence, migration, database ingestion, indexing, chunking, training, and
retrieval evaluation.

Future M2 owns `search_local_adr_corpus` and a text-bearing materializer,
subject to `ME-000C`. That future materializer must reread the exact approved
external archive, prove the same immutable archive/manifest identity, preserve
document, annotation, locator, split, and Option-A lineage, create exact
text-bearing chunks with bounded offsets and hashes, and keep raw text outside
Git. This record neither implements nor authorizes that work.
`READY_FOR_M2-CADEC-RETRIEVAL-CONSUMPTION` is explicitly prohibited.

The integrated boundary establishes `M1B-CADEC-003_COMPLETE`,
`M1B-CADEC_VERTICAL_SLICE_COMPLETE`, and
`READY_FOR_M2-CADEC-RETRIEVAL-PLANNING` without authorizing M2 work.

## Frozen exact facts

- canonical/admitted documents: 1,250/1,248;
- exclusions: `DICLOFENAC-SODIUM.7`, `LIPITOR.221`;
- malformed rows: 5;
- visible limitations: 2 original, 44 MedDRA, 45 SCT, total 91;
- zero-byte documents: `LIPITOR.40`, `VOLTAREN-XR.9`, each with zero original,
  MedDRA, and SCT rows;
- provider-gold annotations and locators: 24,478 total, partitioned 9,089
  original, 6,300 MedDRA, and 9,089 SCT;
- encoding: UTF-8 except the exact CP1252 path/hash exception frozen in
  [ADR-013](../docs/decisions/ADR-013-m1b-cadec-asset-contract.md);
- split: 992 train, 119 development, 137 test;
- origin and governance: provider gold only; REDIST, VOCAB, and Option-A
  provenance unchanged.

## Integrated evidence

CADEC-001 feature `51bbe29a94aa3a16af5d55be01b06f6aa331ab44` was integrated
by merge `af111b8efce0d2a47df4c3ba20f213a812ca12da` through PR #19. Review
closure is `PASS` at `P0 0 / P1 0 / P2 0` after immutable failure history;
terminal audit is `PASS` at `0/0/0`; audited aggregate is
`35a4d2349410c16209197c24e1900ca28067de993276d2c865be082c61548482`.
PR quality run `31726952106` recorded `windows-quality` and `compose-config`
both `SUCCESS`; merged-main quality run `31727139728` was `SUCCESS`.

CADEC-002 feature `03fffef7ad8f68a9ca36c4961a5264b2e0b295ff` was integrated
by merge `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a` through PR #20. Immutable
initial review is `FAIL` at `P0 0 / P1 2 / P2 0`; one remediation batch closed
both findings; independent closure and terminal audit are each `PASS` at
`0/0/0`; audited aggregate is
`d307456bcfb4b5cf20392d93e922fb75d0d5684d9e5064c8a811ac960f973d9a`.
PR run `31748194823` and merged-main run `31748381436` both recorded
`windows-quality` and `compose-config` as `SUCCESS`.

CADEC-003 feature `83617405e58bcec657bdaa84aceb8d2460d46fb1` was integrated
by merge `c226a632753e6fc65e8c84c74ec568d994612b7d` through PR #21. Fresh
independent review and terminal evidence audit each passed at
`P0 0 / P1 0 / P2 0`. The immutable Review001 and closure-review failure
history remains preserved in
[Review001](../docs/reviews/M1B-CADEC-003-BOUNDARY-REVIEW-001.md).

## Historical CADEC-003 candidate writer scope and evidence

The pre-review CADEC-003 candidate authorized exactly six documentation paths:

- `docs/PRD.md`;
- `docs/ARCHITECTURE.md`;
- `docs/TRACEABILITY_MATRIX.md`;
- `docs/decisions/ADR-013-m1b-cadec-asset-contract.md`;
- `.delivery/M1B-CADEC-003.md`;
- `docs/reviews/M1B-CADEC-003-BOUNDARY-REVIEW-001.md`.

The writer performs structural documentation validation: exact six-path status,
`git diff --check`, UTF-8 without BOM, LF endings, final newlines, local
Markdown links/anchors where practical, stale-state search, and boundary-
consistency search. No application suite is required because executable bytes
are unchanged. Read-only inspection of existing executable files was allowed
and performed for review/evidence; no executable or test file was modified. No
independent-closure or terminal-audit verdict is self-issued.

## Historical CADEC-003 candidate network, data, and Git

- Medical-source requests: zero.
- Bounded read-only GitHub PR/check/run metadata requests occurred to verify
  the recorded CADEC-001/002 integration evidence; no GitHub or other remote
  mutation occurred.
- Other network requests beyond that bounded GitHub metadata inspection: zero.
- External CADEC archive, manifest, audit, corpus, database, and M2 worktree
  access: zero.
- Raw/private evidence persisted in Git: zero.
- Stage, commit, push, pull/fetch, merge, rebase, reset, clean, branch deletion,
  history rewrite, and remote mutation: not performed.

## Historical review sequence and final closure

Review001 remains immutably `FAIL` at `P0 0 / P1 1 / P2 2`; its one P1 and two
distinct P2 findings remain unchanged. Remediation batch 1/1 was followed by
closure-review `FAIL` at `P0 0 / P1 1 / P2 1` for no-plan overreach and
Review001 transcription fidelity. The final Owner-authorized mechanical
correction subsequently passed fresh independent review and terminal audit at
`P0 0 / P1 0 / P2 0`; feature commit
`83617405e58bcec657bdaa84aceb8d2460d46fb1` was integrated through PR #21 at
merge `c226a632753e6fc65e8c84c74ec568d994612b7d`. These current-state facts do
not rewrite the immutable historical findings or events.

## Owner interview questions

1. Why is the integrated CADEC-002 output not directly retrieval-consumable?
2. Why must M2 reread and reverify the exact external archive before producing
   text-bearing chunks?
3. How do the empty request tuple and unchanged source-section union prevent
   accidental M1B CADEC execution?
