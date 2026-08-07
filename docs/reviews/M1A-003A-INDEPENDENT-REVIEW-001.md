# M1A-003A Independent Review 001

- Work item: `M1A-003A`
- Branch: `feat/m1a-003a-snapshot-manifests`
- Baseline: `a3fd66477046c9e026d7b2222e882cd94a84d535`
- Status: **THREE FAIL DECISIONS RECORDED; FINAL REMEDIATION CYCLE 3 AWAITS RE-REVIEW**
- Candidate commit: not created
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

Cycle-2 evidence is 120 focused offline tests and 390 full unit/contract
offline tests passing, with repository-wide Ruff/format and MyPy passing.
Independent re-review and terminal evidence audit remain pending; this
document does not declare PASS.

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

Cycle-3 evidence is 154 focused offline tests and 424 full unit/contract
offline tests passing, with repository-wide Ruff/format and MyPy passing.
Independent re-review and terminal evidence audit remain pending. This
document does not declare PASS.
