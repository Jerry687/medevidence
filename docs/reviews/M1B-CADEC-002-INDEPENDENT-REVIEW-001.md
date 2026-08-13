# M1B-CADEC-002 independent review 001

- Status: `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`
- Initial Review001: immutable `FAIL` - `P0 0 / P1 2 / P2 0`
- Remediation cycle 1/1 closure: `PASS` - `P0 0 / P1 0 / P2 0`
- Branch: `feat/m1b-cadec-002-ingestion`
- Baseline: `af111b8efce0d2a47df4c3ba20f213a812ca12da`
- Candidate commit: none
- Reviewer: independent Review001

## Immutable Review001 findings

1. `P1`: archive and manifest hashes were calculated from one path open, then
   the same paths were reopened for ZIP and JSON use. Path replacement between
   hash and use could admit bytes other than those verified.
2. `P1`: public synthetic ZIP inspection had no finite pre-read input-size or
   entry-count bound and lacked aggregate compressed, aggregate uncompressed,
   and expansion-ratio admission bounds before member streaming.

Review001 verdict remains `FAIL` with `P0 0 / P1 2 / P2 0` and is not rewritten
by remediation.

## Remediation cycle 1/1

Both findings were remediated together. Each explicit path is lstat-checked,
opened once, fstat-revalidated as regular/non-reparse where supported, read
through a finite cap into immutable bytes, and never reopened for hashing,
JSON parsing, or ZIP use. ZIP inspection now rejects before member streaming
when the input, entry count, aggregate compressed bytes, aggregate
uncompressed bytes, or 1,000:1 expansion ratio exceeds its finite bound.

Regression coverage includes archive and manifest path replacement after the
single read, exact/one-over input bounds, the exact 5,005 entry boundary and a
10,001-entry rejection, exact/over aggregate bounds, and expansion-ratio
rejection.

Fresh remediation evidence: focused Ruff and MyPy passed; 78 focused tests
passed; full Ruff, format, and MyPy passed; the full offline suite passed 1,726
tests at 79% coverage with two expected warnings. Two exact archive admissions
again produced identical safe summaries and ordered identity digests; the safe
summary serialization produced writer-local digest
`caceae0f13599b2183f056c3ccf0329a774945af107cd79375e35af57603dc1c`.
That digest is not a contract identity, candidate-manifest identity, or audit
gate and is not used as completion evidence.

## Review boundary

Review the actual loader/parser diff, the one-field domain correction, direct
and synthetic tests, safe exact-archive summary, and authorized-path scope.
Confirm no extraction, network, import-time I/O, vocabulary payload, corpus
content in evidence, persistence, tool, API/report, CADEC-003, or M2 behavior.

## Independent closure

- Fresh independent closure verdict: `PASS` - `P0 0 / P1 0 / P2 0`.
- Both original P1 findings are closed after the single authorized remediation
  cycle; no second remediation cycle occurred.
- Independent closure reviewed the actual remediation diff and regression
  behavior for one-open immutable-byte admission and finite ZIP bounds.
- Exact field evidence remains 1,248 documents; 24,478 annotations and
  locators (9,089 original, 6,300 MedDRA, 9,089 SCT); 2 empty documents; 5
  excluded malformed rows; limitations 2/44/45; raw ordering 43 transitions
  across 26 documents; split 992/119/137; exact encoding exception; provider
  gold only; and no predicted artifact.

The terminal evidence audit must generate and bind the canonical candidate
file manifest. This independent-review PASS is not a terminal PASS and claims
no terminal audit, commit, completion, or integration.
