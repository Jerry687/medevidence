# M1B-CADEC-002 delivery record

- Status: `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`
- Branch: `feat/m1b-cadec-002-ingestion`
- Baseline: `af111b8efce0d2a47df4c3ba20f213a812ca12da`
- Candidate commit: none
- Independent Review001: immutable `FAIL` - `P0 0 / P1 2 / P2 0`
- Remediation: cycle 1/1 implemented and closed
- Independent closure: `PASS` - `P0 0 / P1 0 / P2 0`
- Terminal evidence audit: pending

## Behavior

Adds an offline-only, exact-asset CADEC loader and strict provider-gold brat
parser. Inputs are explicit archive and authoritative-manifest paths. Admission
streams exact hashes, validates the frozen manifest and complete safe ZIP
inventory without extraction, parses bounded rows, preserves raw-row identity,
normalizes unchanged discontinuous pairs into source order, constructs frozen
document/annotation/locator objects, and emits a content-free verification
summary. Five malformed excluded rows and 91 visible limitations remain
distinct. No vocabulary payload is emitted.

Review001 found hash/use path-reopen exposure and missing public ZIP aggregate
bounds. The single authorized remediation cycle now reads each explicit input
once into finite immutable bytes after lstat/open/fstat checks, and hashes and
parses only those retained bytes. ZIP inspection enforces finite input, entry,
aggregate compressed, aggregate uncompressed, and 1,000:1 expansion-ratio
bounds before member streaming.

The narrow Owner correction permits `text_length=0` in the unchanged
`m1b.cadec.document.v1` schema. Negative lengths reject, positive documents
are unchanged, and empty documents require zero rows in all three annotation
layers.

## Writer evidence

- Post-remediation focused Ruff/MyPy and 78 offline tests passed.
- Full Ruff, format, and MyPy passed.
- Post-remediation full unit/contract suite: 1,726 passed, 79% coverage, two
  expected warnings.
- Two exact local archive runs produced identical safe summaries and ordered
  identity digests: 1,248 documents; 24,478 annotations and locators (9,089
  original, 6,300 MedDRA, 9,089 SCT); 2 empty documents; malformed count 5;
  limitations 2/44/45; raw ordering 43/26; split counts 992/119/137; exact
  encoding exception; provider gold only; and no predicted artifact.
- The two post-remediation exact runs were identical; safe-summary digest
  `caceae0f13599b2183f056c3ccf0329a774945af107cd79375e35af57603dc1c`.

The `caceae...` value is only a writer-local serialization digest. It is not a
contract identity, audit identity, canonical candidate-manifest identity, or
gating claim. The terminal evidence audit must generate the canonical
candidate file manifest and bind its exact files and hashes.

Independent closure passed `P0 0 / P1 0 / P2 0`. Terminal audit and any commit
remain pending. No medical-source or other network request occurred. No Git
operation was performed. This record claims no terminal PASS, completion,
integration, CADEC-003, or M2 status.

## Manual verification

Run the focused and full offline commands from the repository root, then run
the bounded local exact-archive command with the Owner-provided external paths.
Inspect only the safe summary and aggregate identity/order digests; do not
persist corpus-derived evidence in Git.

## Owner interview questions

1. Why must an empty text member require all three annotation layers to have zero rows?
2. How do raw-row identities preserve provenance when discontinuous spans are source-sorted?
3. Why can the verification summary expose hashes and counts but not terms, rows, or offsets?
