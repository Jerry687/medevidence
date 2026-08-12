# M1B-DM-002 Independent Review 004

Verdict: `FAIL — P0 0 / P1 1 / P2 0`

## Reviewed identity

- Branch: `feat/m1b-dm-002-connector`
- HEAD/baseline: `6eecfd9da033ccf56f05ea59f0a636b463d6a2b9`
- Owner freeze SHA-256: `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Delivery record: 7,110 bytes, SHA-256
  `ed19cda44f5a4915fa46ea45aa604460c4439493425c2599080cedff79a89d80`
- Review003: 4,118 bytes, SHA-256
  `cd2e3b949dc9b29374319250636138597452496ee355802b0da689b6b58f3b05`
- Review001 and Review002 remained byte-identical.
- Exact 38-path Ordinal/no-terminal-LF manifest:
  `c0c080a331a823d51aba96ab83704cc56ffec95c5db27ac1ed8f53746615caea`
- Index empty; strict UTF-8/LF without BOM; `git diff --check` passed.

## P1-01 — Complete responses can retain a contradictory `Content-Length`

`_validated_response_headers()` retains `Content-Length` without validating its
syntax, multiplicity, bound, or agreement with exact raw response bytes.
`_read_body()` bounds raw chunks but does not compare a normally completed raw
byte count with the retained declared length.

The reviewer injected a valid 58-byte discovery JSON response with
`Content-Length: 999`. Discovery succeeded, `body_complete=True`, the retained
body was 58 bytes, and the retained header remained 999:

```text
failure=None
body_complete=True
retained body length=58
retained content-length=999
```

The evidence record therefore asserts incompatible framing metadata while
classifying the response as complete. This weakens exact-response provenance and
can conceal truncation or framing drift in an injected/custom transport.

Required acceptance:

- permit an absent `Content-Length`;
- when present, require exactly one canonical nonnegative ASCII decimal value
  without comma-list, sign, whitespace, leading-zero ambiguity, overflow, or
  duplicate field;
- reject declared length above 5,242,880 before body consumption;
- after normal raw-stream completion, require declared length to equal exact
  retained raw bytes;
- preserve truthful partial termination for payload limit, timeout, and stream
  failure;
- test exact, shorter, longer, zero, duplicate, comma-list, malformed, negative,
  overflow, bound-plus-one, redirect/retry, streaming, and already-consumed cases.

## Verified closures

Review003 exact-wire closure passed: nonidentity and malformed content encodings
reject before acceptance; absent or canonical identity encoding is admitted;
streaming uses raw chunks; already-consumed identity responses retain exact
bytes; body/SHA parity holds; gzip-wrapped historical ZIP rejects; raw exact
bound and bound-plus-one partial semantics are correct.

All twelve earlier P1 closures also remain intact: frozen configuration and six
request designs; cache reparsing; pagination/truncation; XML security and decoded
character accounting; structural section paths; exhaustive selection matrix;
parser-bound capture/replay; specialized persistence comparators; immutable
migration DDL; cumulative query and response bounds; and generic-repository
specialized-table rejection.

## Fresh evidence

- Focused connector/tool/ingestion/persistence: `299 passed`
- Full unit and contract suite with sockets disabled: `1133 passed`, two expected
  warnings
- Ruff check: passed
- Ruff format check: 79 files formatted
- MyPy: 39 source files passed
- `git diff --check`: passed
- Candidate identity remained unchanged after review validation

PostgreSQL was not rerun by the reviewer because the review node was read-only;
the candidate separately records six passing local PostgreSQL tests.

No network or medical-source request, corpus access, patient data, repository
write, Git mutation, Docker/database operation, dependency change, commit, push,
PR, merge, or DM-003 work occurred in review.

The remediation budget is exhausted at 3/3. Terminal audit and every Git
lifecycle step remain blocked; further correction requires Owner authorization.
