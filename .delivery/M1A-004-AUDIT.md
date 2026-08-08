# M1A-004 Implementation Audit

- Work item: `M1A-004`
- Branch: `feat/m1a-004-pubmed-tools-report`
- Approved baseline: `5102d56c73b6714d3608a93a47aa31f70ffa1097`
- Initial reviewed candidate:
  `26165f0ab763416bf76df462589117d22f78921c2e6a9f0c277bbbfe1956b909`
- Initial review: **FAIL — P0 0 / P1 5 / P2 1**
- Cycle-1 reviewed candidate:
  `144d213fd92896735c88564ef589cd95d3b99bd548b0a6de927fa546c3f0203a`
- Cycle-1 re-review: **FAIL — P0 0 / P1 2 / P2 0**
- Cycle-2 reviewed candidate:
  `a560ee33410c3d99221e899f5a07eb136f1556b857d8860d758360674f745c0f`
- Cycle-2 re-review: **FAIL — P0 0 / P1 1 / P2 0**
- Cycle-3 reviewed candidate:
  `a76c538e50c17e4a5dee7cb49d4edfd8807d8e04b9dd63c2f918b58ba72307eb`
- Cycle-3 re-review: **FAIL — P0 0 / P1 2 / P2 1**
- Cycle-4 authorization artifact SHA-256:
  `5a589571cfabd35f0187865381be1766204525df61c5208be2b735a3edf9d1ca`
  over 14,165 raw bytes
- Final pre-commit candidate:
  `7bacedd2e2f4361d550f0772cfd6914a20852c15f5c447210b0e2cabbd5abb36`
- Final PR-head review: **PASS — P0 0 / P1 0 / P2 0**
- Terminal audit: **PASS — P0 0 / P1 0 / P2 0**
- Implementation commit: `2f6cb0a2aa65c5c9e2292fb6e3010d5d14d767a0`
- Draft PR: [#6](https://github.com/Jerry687/medevidence/pull/6),
  `M1A-004: expose PubMed tools and draft reports`
- Hosted CI: `compose-config` **SUCCESS**; `windows-quality` **SUCCESS**
- Current lifecycle: **COMMITTED, PUSHED, DRAFT PR; NOT MERGED OR INTEGRATED**
- Evidence-finalization Git operations: none
- Network operations: none
- Medical-source requests: none
- Docker/database operations: none

## Scope and behavior

The local candidate implements the three frozen operations:

```text
search_pubmed(request: SearchPubMedRequest, *, service: PubMedResearchService)
fetch_pubmed_article(request: FetchPubMedArticleRequest, *, service: PubMedResearchService)
research_pubmed_draft(request: ResearchPubMedRequest, *, service: PubMedResearchService)
```

Tools own strict source-neutral contracts and injected protocols. They import no
connector, ingestion, persistence, HTTPX, SQLAlchemy, filesystem, or provider
DTO. A future composition adapter must map these consumer-owned inputs to the
already merged connector, capture/journal, and persistence registration
contracts; that adapter is outside this work item's allowlist.

The complete draft path validates exact case-sensitive catalog terms, builds
quoted Title/Abstract groups and an optional inclusive publication-date range,
searches first, numerically sorts and bounds at most 100 returned PMIDs, fetches
only those PMIDs one at a time, and persists each acquisition before starting
the next. The final injected call persists the report artifact, run row, and
run envelope last. A persistence exception propagates and prevents final run
persistence.

Remediation cycle 1 rejects nonexhaustive complete search claims, binds
standalone fetches to the exact resolved query before execution, preserves
composite warnings/failure provenance on degraded matched publications without
changing publication content identity, and validates every consumer-owned
execution/finalization DTO before persistence. Observation limits mirror the
merged manifest contract, and report artifacts are capped at 2,097,152 bytes.

Remediation cycle 2 requires every persisted singular fetch publication to
return one exact source-neutral PMID/version/snapshot/manifest/artifact/lineage
binding. The service rejects absent, extra, or mismatched bindings before the
next fetch or finalization, and report publications preserve their content
identity while gaining exact current-run persisted provenance. Report aggregate
validation makes citations and claims transitively current-run bound. Failure
diagnostics are trimmed, bounded, single-line, control-free, and reject the
frozen credential-like marker set case-insensitively.

Remediation cycle 3 replaces opaque lineage assertions with one strict,
source-neutral `publication_to_manifest` edge. Its parent is the exact
publication content artifact encoded by the publication-version identity, its
child is the current acquisition manifest/snapshot, and its ordinal is zero.
The service rejects missing or cross-wired endpoints before continuation, and
the report independently requires both endpoints in provenance plus the exact
ordered `(publication content, current manifest)` transformation lineage.

Owner-authorized remediation cycle 4 makes the application service own the
exact ADR-010 acquisition-intent identity. The consumer contract mirrors the
merged journal preimage using the frozen profile, source, PubMed request shape,
execution limits, namespace, and terminal-LF identity recipe without importing
ingestion. Every persisted acquisition must echo that exact intent identity.
Persistence-port results are treated as untrusted: root, binding, and lineage
models are recursively reconstructed through the strict closed contract before
any value is used. Wrong types, unknown or missing fields, malformed or reused
identities, cross-acquisition ownership, and forged edge cardinality/type/
ordinal/endpoints fail before the next acquisition or final run persistence.

Claims use the smallest exact canonical-abstract span containing one resolved
drug term and one resolved event term, with deterministic tie-breaking and
zero-based half-open Python/Unicode code-point offsets. Missing abstracts or
terms produce no claim. Retracted and corrected-context-only records produce no
positive claim; expression-of-concern and unknown records are limited and keep
visible warnings. No generic exception is swallowed during claim construction.

`ResearchReport` remains `draft` and `exportable=false`. Its logical identity
now binds the exact run, catalog version/hash, run-intent ID, ordered acquisition
snapshot/manifest/envelope identities, and report-artifact identity. Canonical
report artifact bytes omit only the artifact self-field; their SHA-256 must
equal `report_artifact_id`.

## Exact authorized paths

The candidate is limited to the 18 Owner-authorized paths:

1. `src/medevidence/tools/__init__.py`
2. `src/medevidence/tools/contracts.py`
3. `src/medevidence/tools/ports.py`
4. `src/medevidence/tools/pubmed.py`
5. `src/medevidence/tools/research.py`
6. `src/medevidence/domain/reports.py`
7. `src/medevidence/domain/__init__.py`
8. `tests/unit/tools/test_contracts.py`
9. `tests/unit/tools/test_pubmed.py`
10. `tests/unit/tools/test_research.py`
11. `tests/unit/domain/test_reports.py`
12. `tests/unit/test_dependency_boundaries.py`
13. `tests/contract/tools/test_pubmed_tools.py`
14. `tests/integration/tools/test_pubmed_research.py`
15. `.delivery/M1A-004-AUDIT.md`
16. `docs/reviews/M1A-004-INDEPENDENT-REVIEW-001.md`
17. `README.md`
18. `docs/TRACEABILITY_MATRIX.md`

## Initial review and remediation evidence

Independent review of exact initial candidate
`26165f0ab763416bf76df462589117d22f78921c2e6a9f0c277bbbfe1956b909`
returned FAIL with P0 0 / P1 5 / P2 1. The snapshot-versus-manifest concern was
withdrawn because merged persistence freezes equality. Cycle 1 addresses the
five P1 findings and one P2 evidence/status finding within the original
18-path allowlist. Independent re-review of exact cycle-1 candidate
`144d213fd92896735c88564ef589cd95d3b99bd548b0a6de927fa546c3f0203a`
then returned FAIL with P0 0 / P1 2 / P2 0. Cycle 2 addresses those two
source-traceability and redacted-diagnostic findings within the same allowlist.
Independent re-review of exact cycle-2 candidate
`a560ee33410c3d99221e899f5a07eb136f1556b857d8860d758360674f745c0f`
then returned FAIL with P0 0 / P1 1 / P2 0 because persisted publication
artifact and lineage values did not prove exact publication-to-manifest
endpoint ownership. Cycle 3 addresses that final finding within the same
allowlist. Independent review of exact cycle-3 candidate
`a76c538e50c17e4a5dee7cb49d4edfd8807d8e04b9dd63c2f918b58ba72307eb`
found that acquisition-intent ownership and untrusted persistence-output
revalidation still required closure and returned FAIL with P0 0 / P1 2 / P2 1.
The Owner authorized cycle 4 solely for that same-class correction within the
unchanged 18-path allowlist. Final PR-head review and terminal audit both
returned PASS with P0 0 / P1 0 / P2 0 on the corrected implementation.

## Validation evidence

Fresh implementation-owned evidence from the approved baseline worktree:

- `uv lock --check`: resolved 59 packages; exit 0.
- `uv run --locked --no-sync ruff check .`: all checks passed.
- `uv run --locked --no-sync ruff format --check .`: 53 files already formatted.
- `uv run --locked --no-sync mypy src`: success; 27 source files.
- focused unit/domain/boundary/contract selection with `--disable-socket`: 205
  passed in 0.82 seconds.
- dedicated tool-contract/unit/integration selection with `--disable-socket`:
  119 passed in 0.51 seconds.
- injectable integration selection with `--disable-socket`: 1 passed in 0.21
  seconds.
- full `tests/unit tests/contract` sockets-disabled coverage run: 667 passed in
  6.20 seconds, 81% total coverage, one expected pytest-socket warning, and
  `coverage.xml` emitted without changing its tracked content.
- `git diff --check`: exit 0.

These are fresh cycle-4 implementation results. Exact final pre-commit
candidate `7bacedd2e2f4361d550f0772cfd6914a20852c15f5c447210b0e2cabbd5abb36`
received final PR-head review PASS and terminal-audit PASS, each with
P0 0 / P1 0 / P2 0. The implementation was committed at
`2f6cb0a2aa65c5c9e2292fb6e3010d5d14d767a0`, pushed to Draft PR `#6`, and its
hosted `compose-config` and `windows-quality` checks succeeded.

## Remaining risks and manual verification

- The concrete M1A-005 composition adapter does not yet exist, so exact mapping
  to merged connector/capture/persistence implementations is unverified here.
- No live PubMed, NCBI, TLS, database, Docker, or API behavior was exercised.
- Historical FAIL ledgers remain preserved; final PR-head review and terminal
  audit passed.
- The implementation is committed, pushed, and green in Draft PR `#6`, but it
  is not merged or integrated into approved `main`.

Manual release review should confirm Draft PR `#6` points to
`82eebbeb00b189765f9ea3a5f254a20f6aa73a0c`, whose parent implementation commit
is `2f6cb0a2aa65c5c9e2292fb6e3010d5d14d767a0`; both hosted checks remain green,
and merge/integration receive separate Owner authorization. Live PubMed remains
a separate opt-in gate.

## Owner interview questions

1. Why does the service persist each singular acquisition before starting the
   next and reserve run/report/envelope persistence for the final action?
2. How do complete, partial, unavailable, `no_match`, and `indeterminate`
   remain distinct when search or one fetch fails?
3. Why are report artifact bytes self-field-excluded, and which exact identities
   remain bound into the deterministic report?
