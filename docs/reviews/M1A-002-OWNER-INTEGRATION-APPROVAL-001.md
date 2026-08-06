# M1A-002 Project Owner Integration Approval Record

- Approval reference: `M1A-002-OWNER-INTEGRATION-APPROVAL-001`
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: `2026-08-06`
- Status: **APPROVED AND EFFECTIVE — M1A-002 LOCALLY INTEGRATED INTO THE
  APPROVED `main` BASELINE**
- Revision: 1
- Approved local `main` identity:
  `4f39ed3d27438e69a4a5a30ff6be499d247541c1`
- M1A-002 implementation identity:
  `02550d7c674540430e1c11edb1edd9c091593f7b`
- M1A-002 evidence-finalization identity:
  `2918f3ed80336aeb349e82d34f2833367641befd`
- Integration reconciliation:
  [M1A-002-INTEGRATION-RECONCILIATION](../../.delivery/M1A-002-INTEGRATION-RECONCILIATION.md)
- Historical terminal audit:
  [M1A-002-AUDIT](../../.delivery/M1A-002-AUDIT.md)

## Purpose and present effect

This record confirms the Project Owner's approval of the current local
`main` baseline containing the bounded M1A-002 PubMed connector. At the start
of the reconciliation run, local `main` resolved to
`4f39ed3d27438e69a4a5a30ff6be499d247541c1`, and the M1A-002 implementation
and evidence-finalization commits were verified as ancestors of that exact
identity.

This approval is limited to the locally integrated M1A-002 scope already
reviewed and evidenced in the historical terminal audit. It does not perform a
Git operation and does not expand the approved M1A product scope.

## Immutable integration identity

The approved current local baseline is bound exclusively to:

```text
local main:                    4f39ed3d27438e69a4a5a30ff6be499d247541c1
M1A-001B ancestor:             8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06
M1A-002 implementation:        02550d7c674540430e1c11edb1edd9c091593f7b
M1A-002 evidence finalization: 2918f3ed80336aeb349e82d34f2833367641befd
```

Read-only ancestry checks verified all three listed M1A ancestors against
`4f39ed3d27438e69a4a5a30ff6be499d247541c1`.

At run start, the cached remote-tracking ref `refs/remotes/origin/main` also
resolved to `4f39ed3d27438e69a4a5a30ff6be499d247541c1`. No fetch or other network
operation was authorized or performed, so this is evidence about the local
cached ref only and is not a claim about the current remote repository state.

The descendant commits
`088d9529037f80e312c1c77561feb404943abd09`,
`728018c3a426f502d414662517ff5fa09feaca28`, and
`4f39ed3d27438e69a4a5a30ff6be499d247541c1` add or correct engineering-agent
harness and repository-policy tooling. They are not M1A product functionality
and do not expand the approved bounded PubMed connector behavior.

## Historical evidence and limited supersession

The historical [M1A-002 terminal audit](../../.delivery/M1A-002-AUDIT.md)
remains unchanged and valid for the pre-integration state it recorded. Its
statements that the candidate was local-only, not merged into `main`, and not
part of the approved baseline were true at that audit point. This approval
supersedes those statements only as descriptions of the current local baseline;
it does not rewrite or invalidate the historical review, validation, B-017,
B-018, candidate-identity, or post-commit evidence.

The connector retains the historical offline validation and dependency
evidence recorded by that audit. No application test, dependency audit, or
source behavior check was freshly rerun merely to create this approval record,
and no historical result is represented as fresh evidence.

## Carried limitations

- Live NCBI/TLS behavior remains intentionally unverified.
- No live PubMed, NCBI, or other medical-source request was made during
  integration reconciliation.
- The conservative publication-status mapping does not claim exhaustive
  coverage of every future PubMed vocabulary value.
- The synchronous deadline cannot preempt a malicious injected transport or
  parser while that callable is blocked; it rejects completeness after control
  returns.
- The historical dependency-evidence artifact remains external temporary
  evidence as recorded by the terminal audit; this record does not recreate or
  re-audit it.
- Cached `origin/main` alignment is not live remote verification.

## Work that remains unauthorized

This approval does not authorize:

- `M1A-003A`, `M1A-003B`, `M1A-004`, or `M1A-005` implementation;
- any other later milestone or source implementation;
- a live PubMed/NCBI request or live TLS acceptance run;
- new or upgraded dependencies;
- architecture, schema, public-interface, security-boundary, or evidence-
  semantics changes;
- fetch, pull, push, remote-state modification, any merge other than the exact
  gated local fast-forward authorized below, rebase, reset, clean, tag, branch
  deletion, history rewrite, or any unrelated Git operation; or
- representing the engineering harness as M1A product functionality.

The exact live query, NCBI client-identification values, execution time, and
acceptance command remain behind their separate Owner gate.

## Authorized reconciliation completion flow

The Project Owner authorizes the following exact local Git sequence only after
both the independent review and terminal evidence audit return PASS for the
same four-file reconciliation candidate:

1. stage exactly:
   - `.delivery/M1A-002-INTEGRATION-RECONCILIATION.md`;
   - `.delivery/STATE.md`;
   - `README.md`; and
   - `docs/reviews/M1A-002-OWNER-INTEGRATION-APPROVAL-001.md`;
2. create one local commit with the exact subject:

   ```text
   docs(delivery): reconcile M1A-002 approved baseline
   ```

3. verify the resulting commit, exact four-path scope, and clean reconciliation
   branch worktree;
4. verify local `main` still resolves exactly to
   `4f39ed3d27438e69a4a5a30ff6be499d247541c1`;
5. switch to `main`; and
6. fast-forward only from `docs/m1a-002-baseline-reconciliation`.

The authorized commands are:

```powershell
git add -- .delivery/M1A-002-INTEGRATION-RECONCILIATION.md .delivery/STATE.md README.md docs/reviews/M1A-002-OWNER-INTEGRATION-APPROVAL-001.md
git commit -m "docs(delivery): reconcile M1A-002 approved baseline"
git show --name-only --format=fuller HEAD
git status --short
git rev-parse main
git switch main
git merge --ff-only docs/m1a-002-baseline-reconciliation
```

The `git rev-parse main` output in this sequence must be exactly
`4f39ed3d27438e69a4a5a30ff6be499d247541c1` before `git switch main`.

If either independent gate does not PASS, the candidate identity or path scope
changes after those gates, local `main` no longer identifies
`4f39ed3d27438e69a4a5a30ff6be499d247541c1`, or the fast-forward condition
does not hold, this authorization stops before the affected Git operation.

This authorization does not extend to fetch, pull, push, remote-state
modification, a non-fast-forward merge, any other commit, any other path,
rebase, reset, clean, tag, branch deletion, history rewrite, or another
unrelated or destructive Git operation.

## Decision

**The Project Owner approves and recognizes M1A-002 as locally integrated into
the approved `main` baseline at
`4f39ed3d27438e69a4a5a30ff6be499d247541c1`, subject to the limitations and
non-authorizations in this record.**

This record itself does not execute the authorized stage, commit, verification,
branch switch, or fast-forward integration. It does not push, fetch, pull,
modify remote state, run application tests, or perform live-source
verification.
