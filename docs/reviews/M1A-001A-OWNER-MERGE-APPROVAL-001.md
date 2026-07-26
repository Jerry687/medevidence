# M1A-001A Project Owner Merge Approval Record

- Approval reference: M1A-001A-OWNER-MERGE-APPROVAL-001
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-26
- Status: **APPROVED FOR CREATE-A-MERGE-COMMIT WORKFLOW**
- Revision: 1
- Candidate branch: `docs/m1a-001a-decision-gates`
- Target branch: `main`
- Approved committed candidate:
  `0e4ceaf2ece188f38e5f99d0ff0e5b8ea37c2832`
- Final independent review:
  [M1A-001A-FINAL-INDEPENDENT-REVIEW-001](M1A-001A-FINAL-INDEPENDENT-REVIEW-001.md)
- Effective governance authorization:
  [M1A-001A-OWNER-AUTHORIZATION-001](M1A-001A-OWNER-AUTHORIZATION-001.md)

## Immutable approval identity

This approval is bound exclusively to committed M1A-001A candidate:

```text
0e4ceaf2ece188f38e5f99d0ff0e5b8ea37c2832
```

The approved candidate is a direct child of the approved ME-000A `main`
baseline `540420d437ff7306f4c53dc784ccf8ec5ced9e1d` and contains the exact
six-file scope recorded by
`M1A-001A-FINAL-INDEPENDENT-REVIEW-001`.

The final independent review returned PASS with no Critical, High, or Medium
findings. Hosted jobs `windows-quality` and `compose-config` passed for the
exact candidate.

The final independent review and this approval are post-candidate governance
records. Before merge, the six reviewed candidate files must still match
candidate `0e4ceaf2ece188f38e5f99d0ff0e5b8ea37c2832`, and the pull request may
add only these two final governance records beyond that committed candidate.

## Merge authorization

The Project Owner authorizes the pull request containing the exact approved
candidate and these two final governance records to be merged into `main`
using GitHub's **Create a merge commit** method.

- Squash merging is explicitly prohibited.
- Rebase merging is explicitly prohibited.
- The candidate commit must remain present in the resulting merge history.
- The resulting merge commit must contain both final governance records.
- This record does not itself stage, commit, merge, tag, or push anything.

Any change to an earlier candidate file after
`0e4ceaf2ece188f38e5f99d0ff0e5b8ea37c2832` invalidates this approval and
requires a new committed-candidate review and new Owner approval.

## Post-merge implementation authorization

After the authorized merge commit is present on `main`, only `M1A-001B` may
begin. Its required branch is:

```text
feat/m1a-001b-domain-contracts
```

That branch must be created from the resulting merged `main` baseline, not
from the pre-merge candidate commit or an older baseline.

This approval does not automatically create the branch or begin
implementation. `M1A-001B` remains limited to source-neutral domain contracts
and its approved dependency boundary.

## Work that remains unauthorized

This approval does not authorize:

- `M1A-002`;
- `M1A-003A`;
- `M1A-003B`;
- `M1A-004`;
- `M1A-005`;
- a monolithic M1A implementation;
- live PubMed execution;
- a standalone ASGI server dependency;
- DailyMed, FAERS/openFDA, or CADEC implementation;
- retrieval, LangGraph, LLM, UI, MCP, export, or HITL implementation; or
- unrelated refactoring.

`M1A-002` through `M1A-005` remain sequentially gated and unauthorized until
each preceding focused work item is independently reviewed, approved, and
merged. The approved retention policy does not authorize a live request.

The exact live query, NCBI client-identification values, execution time, and
final command still require separate focused Project Owner approval. No
standalone ASGI server is approved for M1A; any future M1A-005 validation may
use only the already approved in-process ASGI test-client boundary unless a
later Owner decision changes it.

## Decision

**M1A-001A is approved for the Create-a-merge-commit workflow described in
this record.**

No stage, commit, merge, push, live request, or `M1A-001B` implementation is
performed by this approval record. Later implementation must branch from the
merged `main` baseline.
