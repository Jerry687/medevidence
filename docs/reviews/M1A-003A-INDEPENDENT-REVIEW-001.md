# M1A-003A Independent Review 001

- Work item: `M1A-003A`
- Branch: `feat/m1a-003a-snapshot-manifests`
- Baseline: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Status: **CYCLE-4 REMEDIATION COMMITTED, PUSHED, AND HOSTED RERUN PASS; EVIDENCE RECONCILIATION REVIEW/AUDIT AND REMOTE FINALIZATION PENDING**
- Implementation candidate identity:
  `sha256:8df53196ccd2eb5f377eb42b0625269e925644385c02cd9cb72a6664ce419627`
  (2,235 bytes; 21 files)
- Implementation commit: `c3d724b2097c8df1249b217f610a78291039edbb`
- Implementation parent: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Evidence-record commit: `94e3d96f33e0752b34e6a016d19b9d1b7577f3f6`
- Cycle-4 remediation commit: `52e71f0802e31580304980f487eba3c23f57db41`
- Cycle-4 remediation parent: `94e3d96f33e0752b34e6a016d19b9d1b7577f3f6`
- Pull request: `#4`
- Reviewer: independent MedEvidence review lane

## Review decision

The first uncommitted candidate failed independent review. Green implementer
tests did not override reproducible contract, storage, containment, and handoff
defects. The reviewed historical candidate identity was
an uncommitted worktree state; no stable commit identity was created.

### Findings

- P1: complete acquisition envelopes and manifests could claim complete
  matches or no-match without a completed page or retained source bytes.
- P1: pre-body timeout or transport failure fabricated an empty incomplete raw
  response instead of retaining only a nonempty observed prefix.
- P1: capacity and writer-lock enforcement were not end to end; journal and
  manifest paths bypassed the store gate and defaults did not account for
  committed on-disk state.
- P1: containment did not reject the lock leaf or recovery-entry leaf when
  either was a symlink or reparse point.
- P1: there was no executable source-neutral connector-to-ingestion capture
  path, and replay did not bind expected manifest, link, metadata, and
  validated-count identities.
- P2: journal parsing accepted noncanonical whitespace and CRLF bytes.
- P2: a complete run could remain indeterminate, and failed acquisition
  envelopes did not require both failure code and redacted detail.

## Remediation cycle 1

The single authorized writer implemented a bounded correction within the
original allowlist:

- complete states now require one completed page and retained complete source
  evidence;
- the connector omits pre-body failures and retains nonempty incomplete
  prefixes;
- raw, journal, and manifest files share one lock-gated, containment-checked,
  capacity-accounted atomic publication primitive backed by an on-disk ledger;
- lock and recovery leaf reparses reject;
- a source-neutral response observation and capture path persists exact bytes,
  links, and manifests, while replay requires expected manifest, links, and
  validated count;
- journal parsing requires byte-for-byte canonical form;
- the missing terminal-state invariants reject.

Remediation evidence is 112 focused offline tests and 382 full unit/contract
offline tests passing, with repository-wide Ruff/format and MyPy passing. This
section records implementer remediation only.

## Cycle 1 re-review decision

Cycle 1 re-review returned FAIL with four P1 defects. The reviewer referred to
the historical uncommitted worktree candidate by the abbreviated label
`ca9799...`; subsequent edits make that label historical rather than a current
candidate identity.

- P1: complete coverage incorrectly required every retained retry response to
  be complete, so a valid incomplete/error attempt followed by a successful
  complete retry rejected.
- P1: `capture_acquisition` published raw and link files before manifest
  validation, leaving committed fragments after invalid count, status, or
  cumulative input.
- P1: complete matches or no-match could use a retained 4xx/5xx response as
  completion evidence.
- P1: partial `matches` could claim records with no retained source evidence
  or artifact links.

## Remediation cycle 2

The same single authorized writer applied a bounded correction:

- ordered earlier incomplete/error attempts remain retained, while the
  terminal effective response for complete coverage must be nonempty,
  body-complete, and HTTP 2xx;
- capture now validates the journal path and computes every body hash,
  artifact link, manifest file, manifest, and canonical serialization in
  memory before the first publication;
- count, status/count, terminal HTTP status, and cumulative-limit failures are
  tested to leave zero committed raw, link, or manifest files;
- every `matches` manifest and acquisition envelope requires retained evidence,
  while partial matches may keep an incomplete prefix with zero completed
  pages.

Cycle-2 evidence was 120 focused offline tests and 390 full unit/contract
offline tests passing, with repository-wide Ruff/format and MyPy passing. At
that evidence point, independent re-review and terminal evidence audit
remained pending.

## Cycle 2 re-review decision

Cycle 2 re-review returned FAIL with one P1 and one P2 finding. The reviewer
referred to the historical uncommitted worktree candidate by the abbreviated
label `4a7b...`; subsequent edits make that label historical.

- P1: partial `matches` required a retained file but did not require any
  nonempty HTTP 2xx evidence, so 503-only, 4xx-only, and zero-byte histories
  could support claimed records.
- P2: approved journal filenames were not bound to exact concrete record
  types before immutable publication, allowing a wrong record to poison a
  no-clobber filename.

## Remediation cycle 3

The final authorized remediation cycle:

- requires every `matches` manifest to contain at least one retained nonempty
  HTTP 2xx body or incomplete prefix;
- preserves an earlier usable 2xx observation when a later 503/incomplete
  response ends partial coverage;
- rejects 503-only, 4xx-only, zero-byte-only, and error-only histories across
  both accepted partial-match execution triples;
- binds each approved journal filename to its exact concrete record type and
  binds artifact-link filenames to their ordinal before the store is called;
  and
- exercises every allowed mapping and every wrong concrete type/filename pair,
  then publishes the correct record to the same path to prove no-clobber was
  not poisoned.

Cycle-3 implementer evidence was 154 focused offline tests and 424 full
unit/contract offline tests passing, with repository-wide Ruff/format and
MyPy passing. At that evidence point, independent re-review and terminal
evidence audit remained pending.

## Terminal independent implementation review

After remediation cycle 3, the terminal independent reviewer returned
**PASS** with no P0, P1, or P2 findings for implementation candidate
`sha256:8df53196ccd2eb5f377eb42b0625269e925644385c02cd9cb72a6664ce419627`.
The reviewer reported 35 targeted assertions passing; its exact selector was
not supplied and is not invented here. The independently reproduced broad
focused selection passed 197 tests, and the full offline unit/contract suite
passed 424 tests.

This terminal PASS does not erase the three historical FAIL decisions above
and is validation only, not Project Owner approval or approved-`main` status.

## Terminal pre-commit evidence audit

The terminal pre-commit evidence audit returned **PASS**. It verified the
2,235-byte/21-file candidate identity, exact allowlist, validation evidence,
offline/network boundary, and readiness for the separately authorized local
implementation commit.

Post-commit verification recorded:

- implementation commit `c3d724b2097c8df1249b217f610a78291039edbb`;
- exact parent `a3fd66477046c9e026d7b2222e882cd94a84d535`;
- exact implementation tree `bf85382096c5b511b091cc43c0e3fc236605ee57`;
- exactly 21 committed paths, zero path or content mismatches, and a clean
  worktree;
- Ruff check and format check passing;
- MyPy passing for 17 source files;
- broad focused selection: 197 passed; and
- full sockets-disabled unit/contract suite: 424 passed, one expected
  `pytest-socket` warning, 86% aggregate coverage.

At the terminal post-implementation verification point, no network,
medical-source request, dependency operation, container, or database activity
had occurred. Only the local implementation commit had then been created; the
remote lifecycle had not started.

## Cycle 4: Windows LF checkout portability

The evidence record was later committed at
`94e3d96f33e0752b34e6a016d19b9d1b7577f3f6`, pushed, and opened as PR `#4`.
Hosted run `31146015339` passed `compose-config`, Ruff check, Ruff format, and
MyPy. Windows unit/contract tests reported 422 passed and 2 failed because
`tests/fixtures/snapshots/manifest-v1.json` was checked out with CRLF instead
of its canonical LF bytes.

The Project Owner authorized cycle 4 as a deterministic mechanical remediation
limited to root `.gitattributes` with exactly:

```text
/tests/fixtures/snapshots/manifest-v1.json text eol=lf
```

No source, test, dependency, workflow, interface, database, or medical-source
semantics change. Fresh local cycle-4 validation passed: exact attribute and
fixture LF checks, Ruff, format, MyPy, focused 197, and full sockets-disabled
424/86% with one expected socket-block warning.

The remediation was committed as
`52e71f0802e31580304980f487eba3c23f57db41`, with parent
`94e3d96f33e0752b34e6a016d19b9d1b7577f3f6` and exactly the seven authorized
paths including root `.gitattributes`, then pushed to PR `#4`. A fresh
`core.autocrlf=true` clone checked out `52e71f0`; `git check-attr` reported
`text: set` and `eol: lf`, the fixture was 1,155 bytes with terminal LF and
zero CR bytes, and the two formerly failing tests passed 2/2.

Hosted rerun `31147466248` passed `compose-config` with 114 cases, Windows
Ruff check, Ruff format for 32 files, MyPy for 17 source files, and the offline
unit/contract suite with 424 passed, one expected warning, and 86% coverage.
Historical failed run `31146015339` remains recorded above.

This six-document evidence reconciliation is a local candidate pending
independent evidence-only review and terminal evidence audit. A later evidence
commit/push and its hosted rerun remain pending, as do final PR readiness,
merge, and approved-`main` integration. No final PR PASS, readiness, merge,
integration, or live-source validation is claimed.
