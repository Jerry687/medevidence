# M1A live run 001 recovery independent review 001

- Review reference: `M1A-LIVE-RUN-001-RECOVERY-001`
- Work item: `M1A-LIVE-RUN-001-RECOVERY-AND-REDACTION-HARNESS-FIX`
- Branch: `fix/m1a-live-run-001-recovery`
- Approved baseline: `09cc42838475a4c1bab62050fbfeac14c5dd6761`
- Reviewed pre-record candidate:
  `sha256:458803844783d524ecd461717fd089a0ab81c77331489a93a18cb6070b8d0fce`
- Independent review: **PASS - P0 0 / P1 0 / P2 0 / P3 0**
- Mechanical rework passes consumed: `2` of maximum `2`
- Terminal evidence audit: **PENDING**
- Live-gate disposition: **LIVE_GATE_ACCEPTANCE_UNRESOLVED;
  NO_RERUN_AUTHORIZED**

## Authority and scope

The exceptional Owner authorization permitted only the recovery/redaction
test harness and its milestone/disposition records. This independent review
covered the exact six-path pre-record candidate identified above. Production
source, dependencies, schemas, public interfaces, live medical-source access,
another live run, and external-evidence mutation were outside scope.

The reviewed test boundary keeps only marker/opt-in gating, calls one
traceback-hidden sensitive executor, and asserts only fields of a frozen closed
scalar result. The executor alone retrieves the Owner email and external root,
constructs/owns/closes the connector, owns provider and raw-bearing values,
persists evidence, validates explicit bounds, and translates ordinary
connector/provider/helper/close failures into a newly constructed fixed-code
test-only exception with the original chain suppressed.

The review also covered compact punctuation- and case-insensitive structural
key normalization, the exact fixed-false redaction schema, fixed sanitized
exception state, the `-vv --showlocals` subprocess disclosure regression, and
the executor-rooted AST call-graph gate. The final source gate rejects every
`pytest` module reference or propagated alias in the sensitive reachable
closure, imported or assigned `pytest.fail`, local/module `p = pytest`
aliases, `getattr(pytest, "fail")`, and newly reachable raw-bearing helpers
omitted from the supplementary registry.

## Review history

Two bounded mechanical rework passes were consumed. The first replaced a
manual-only sensitive-function check and literal-call-only `pytest.fail`
detection with executor-rooted reachability, alias-aware fail detection, and
inference of newly reachable raw-bearing helpers. The second removed the
remaining pytest-module alias paths and added exact negative regressions for:

- local `p = pytest; p.fail(provider.body)`;
- module-level `p = pytest`, followed by `p.fail(provider.body)`; and
- `fail = getattr(pytest, "fail"); fail(provider.body)`.

The final reviewed pre-record candidate resolves those findings. No further
review finding remains: **P0 0 / P1 0 / P2 0 / P3 0**.

## Fresh validation evidence

- privacy/static/subprocess selection: `38 passed, 8 deselected`;
- focused recovery/live-gate selection: `44 passed, 1 skipped, 1 deselected`;
- complete E2E module with sockets disabled: `44 passed, 2 skipped`;
- full sockets-disabled unit/contract suite: `713 passed`, 79% coverage;
- Ruff check: PASS;
- Ruff format check: PASS;
- MyPy over `src`: PASS;
- offline lock validation: PASS; and
- diff check: PASS.

The two E2E skips are expected control behavior: the disclosure child is
selected only by its parent regression, and the live PubMed test remains
default-disabled without explicit marker selection. The focused selection
separately deselects the live test. No validation command selected the live
marker or enabled the Owner live-run environment opt-in.

## Immutable recovery evidence

The external recovery record remains 3,032 bytes with SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
It was revalidated read-only and was not changed, deleted, renamed, or printed.

Recovered live run 001 facts remain:

- exactly one bounded PubMed ESearch request was directly proved;
- the reconstructed connector outcome is
  `failed / unavailable / indeterminate`;
- the persisted manifest and acquisition envelope separately remain
  `failed / partial / indeterminate` because received bytes were retained;
- fetch was not executed;
- the original acceptance record was not written;
- `rerun_performed=false`; and
- the recovery record does not establish an exhaustive no-result outcome.

## Network, sensitive-data, and Git review

No network operation, live medical-source request, live test, or real connector
instantiation occurred during implementation, remediation, or review
validation. No patient data, credential, secret, raw response, header, complete
URL, or source payload was introduced into the Git candidate.

No Git staging, commit, push, pull, fetch, merge, rebase, reset, clean, branch
deletion, history rewrite, or remote-state mutation occurred. The reviewed
pre-record candidate remained based on
`09cc42838475a4c1bab62050fbfeac14c5dd6761` with an empty index.

## Decision

**PASS - P0 0 / P1 0 / P2 0 / P3 0** for the exact reviewed pre-record
candidate
`sha256:458803844783d524ecd461717fd089a0ab81c77331489a93a18cb6070b8d0fce`.

This is an independent implementation-review decision only. The terminal
evidence audit, post-record seven-path candidate identity, any local commit,
PR, push, merge, and Owner disposition remain pending. This review does not
establish `M1A_LIVE_ACCEPTANCE_PASS`, `M1A_COMPLETE`, or
`READY_FOR_M1B_OWNER_PLANNING`. The failed/unavailable outcome remains
indeterminate, no rerun is authorized, and M1B planning has not begun.
