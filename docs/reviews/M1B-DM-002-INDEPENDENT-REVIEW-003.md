# M1B-DM-002 Independent Review 003

Verdict: `FAIL — P0 0 / P1 1 / P2 0`

## Reviewed identity

- Branch: `feat/m1b-dm-002-connector`
- HEAD/baseline: `6eecfd9da033ccf56f05ea59f0a636b463d6a2b9`
- Owner freeze SHA-256: `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Delivery record: 5,945 bytes, SHA-256
  `8a90f0682e91e384ae6ca77b702e834a82d8e57f7c5b9ec561c88b284f3f8333`
- Review001: 6,482 bytes, SHA-256
  `31211409c6f51a812ed35066363959dfe9cb7c85cd0b564597f13579825cb766`
- Review002: 3,403 bytes, SHA-256
  `559315dcf782791d0614391843a865d09c0ded27d01f4926fc74151b8f80a9be`
- Exact 37-path Ordinal/no-terminal-LF manifest:
  `4d25a194846fe0ec31daca8624f3b30cb5e9f572c793fe283520104161a77225`
- Index empty; strict UTF-8/LF without BOM; `git diff --check` passed.

## P1-01 — Connector retains decoded bytes instead of exact HTTP response bytes

`DailyMedConnector._read_body()` used `httpx.Response.iter_bytes()`, which
transparently decodes HTTP content encoding. Although the request sends
`Accept-Encoding: identity`, an injected or upstream response may return
`Content-Encoding: gzip`. The connector then bounds, parses, retains, hashes,
and snapshots decoded content as though it were the exact acquired response.
`content-encoding` was also absent from the retained safe response headers.

Offline reproducer with `httpx.MockTransport` returned a 68-byte gzip body for
a 58-byte JSON payload. The request header was `identity`; discovery succeeded;
`RawDailyMedResponse.body` was 58 decoded bytes, not the 68 exact transport
bytes:

```text
accept identity
wire_size 68
retained_size 58
wire_equal False
decoded_equal True
failure None
```

This violates the frozen exact response/raw-byte retention rule and applies the
compressed HTTP-body ceiling to the wrong representation. Persisted artifact
identity and byte size could therefore describe an implicit transformation
rather than the acquired response.

Required acceptance:

- read and bound exact transport bytes using raw streaming;
- under the frozen identity-only profile, fail closed before evidence acceptance
  on every present non-identity content encoding;
- preserve and validate canonical content-encoding evidence;
- ensure historical ZIP parsing receives exact ZIP bytes without HTTP-decoding
  ambiguity;
- add gzip, deflate, malformed/multiple encoding, decompression-expansion,
  exact-bound, and bound-plus-one tests;
- assert retained/hash-accounted bytes equal the exact transport stream.

## Prior closure verification

All twelve earlier P1 findings were independently rechecked. Review001 P1-01
through P1-09 remain closed: frozen connector/config/request reconstruction,
cache byte reparsing, pagination/truncation, expanded-name XML security,
attribute bounds, structural section paths, authoritative selection matrix,
parser-bound capture/replay, specialized persistence comparators, and immutable
self-contained migration DDL. Review002 closures also pass: full canonical query
text is bounded at 512 pre-encoding Unicode code points; response-only bytes are
cumulatively bounded at 5,242,880 with the derived stable SPL excluded from
double counting; and the generic repository rejects all four specialized
DailyMed tables before database access.

## Fresh evidence

- Focused DailyMed/ingestion/persistence: `284 passed`
- Full unit and contract suite with sockets disabled: `1118 passed`, two expected
  warnings, 78% coverage
- Ruff check: passed
- Ruff format check: 79 files formatted
- MyPy: 39 source files passed
- `git diff --check`: passed
- Candidate identity remained unchanged after validation

PostgreSQL was not rerun by the reviewer because the review node was read-only;
the candidate separately records six passing local PostgreSQL tests.

No network or medical-source request, corpus access, patient data, repository
write, Git mutation, Docker/database operation, dependency change, commit, push,
PR, merge, or DM-003 work occurred in review.

Terminal audit and Git lifecycle remain blocked pending remediation and a fresh
complete independent review with `P0/P1/P2 = 0/0/0`.
