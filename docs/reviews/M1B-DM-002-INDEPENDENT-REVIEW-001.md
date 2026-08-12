# M1B-DM-002 Independent Review 001

Verdict: `FAIL — P0 0 / P1 9 / P2 0`

## Reviewed identity

- Branch: `feat/m1b-dm-002-connector`
- HEAD/baseline: `6eecfd9da033ccf56f05ea59f0a636b463d6a2b9`
- Owner-freeze SHA-256: `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- ADR-011 SHA-256: `4b1a0f24d69882c10ac476a43008262ad6845e69f93af9295e0f3dae2b429471`
- Exact 35-path Ordinal/no-terminal-LF manifest:
  `e09983b71ea59a25b91db637d3f5b0ffa1b0c3ba5a48c19a0688d81b7fbf6149`
- Index: empty. Scope contained only the authorized 35 paths.

## Findings

### P1-01 — Frozen trust policy and request objects remain weakenable

`DailyMedConnector.__init__` accepted an already-created configuration without
revalidating the frozen tuple. After `object.__setattr__(cfg, "max_attempts", 99)`,
the connector accepted and used `99`. Exported `DailyMedRequest` instances could
also carry arbitrary path/query text and be treated as their own policy oracle.

Acceptance: construct policy internally or revalidate every security field at the
connector boundary; independently require each request to match exactly one of the
six frozen request designs; add exhaustive one-field drift tests.

### P1-02 — Caller-controlled cache can return foreign unverified identity

A caller-seeded cache entry under SETID/version `1111…/3` returned a
`ParsedSplDocument` containing `2222…/99` with zero transport calls.

Acceptance: own immutable cache state internally; reject caller-prepopulated trusted
objects and post-construction mutation; reparse/revalidate cached evidence and require
exact key, SETID, SPL version, and content parity.

### P1-03 — Pagination contradictions and bounded truncation are treated as complete

The parser accepted observed rows greater than page size or total; explicit total zero
was replaced via `or observed`; and page five with total 100 returned `next_page=None`,
causing `truncated=False` despite more provider pages.

Acceptance: preserve explicit zero metadata, reject contradictory page/size/total/row
tuples, retain provider-more-pages state past the five-page ceiling, and emit
partial/truncated when page or candidate bounds prevent completeness for discovery and
history.

### P1-04 — Forbidden XML constructs and decoded-character limits are bypassable

Namespace aliases for XInclude/XSLT were accepted because rejection relied on literal
prefix bytes. A safe additional attribute with 5,000,001 decoded characters was also
accepted because attribute values were excluded from the decoded-character count.

Acceptance: reject forbidden constructs by expanded namespace/name independent of
prefix; reject XInclude, XSLT, schema-resolution and equivalent constructs; include
decoded attribute values in the exact bound; add alias and boundary tests.

### P1-05 — Nested SPL sections receive fabricated XML paths

Flattened `root.iter(section)` traversal assigned nested sections top-level component
paths, making recorded provenance paths non-replayable.

Acceptance: derive exact structural paths with nested component/section ancestry and
sibling ordinals, preserve exact parent-section identity, and test nested path/parent
drift.

### P1-06 — Structured discovery response does not enforce the exhaustive matrix

`DailyMedDiscoveryResponse` accepted `review_required` for both
`succeeded/complete/no_match` with zero candidates and
`succeeded/complete/matches` with one candidate.

Acceptance: enforce the frozen disjoint matrix: complete no-match maps only to
`no_candidate`; complete-match review requires the frozen unresolved non-equivalent
shape; every partial match maps to review; the three indeterminate zero-result triples
have no decision; use authoritative candidate/decision context where required.

### P1-07 — Snapshot capture/replay can bless arbitrary bytes as authoritative SPL

`stable_spl_bytes=b"not xml"` with selected identity was published under the stable
`.xml` path and replayed successfully because capture/replay checked hash/path/member
identity but did not parse the SPL or verify selected SETID/version.

Acceptance: apply the exact frozen SPL parser before publication and during replay;
require exact selected SETID/version and a successful complete retained fetch/usable
normalization; reject malformed, foreign, partial, or unclassified stable content.

### P1-08 — Persistence omits frozen semantic and identity-preimage validation

Complete-column insert-or-verify exists, but a forged `label_version_id` passed the
repository validator. Equivalent gaps covered stable SPL artifact kind/schema/hash/path,
label-version preimage, section identity/title/code/text hash/artifact binding, and
selection/outcome/candidate/manifest/member comparators.

Acceptance: revalidate through existing domain models and trusted comparators; derive
and verify label-version/section identities; require exact stable artifact identity;
close decision/outcome/candidate/manifest/member joins; test one-field mutations while
retaining immutable complete-column replay.

### P1-09 — Migration is coupled to mutable application metadata

Revision `m1bdm002001` imports `M1B_TABLE_ORDER` and `metadata` from live application
models, so future model drift could change historical migration DDL.

Acceptance: make the migration metadata/DDL self-contained and immutable; add an exact
equivalence test against the frozen catalog; assert no `medevidence.persistence` import;
retain revision/down-revision and upgrade/downgrade/upgrade behavior.

## Validation evidence

- Focused connector/tool/ingestion/persistence: `219 passed`.
- Ruff: passed. Format: 79 files already formatted.
- MyPy: 39 source files passed.
- Full unit/contract: `1053 passed`, two expected warnings.
- Disposable local PostgreSQL: `4 passed`.
- `git diff --check`: passed.
- Exact schema: 15 ordered tables, 201 columns, exact types/nullability, no server
  defaults, exact named CHECK/PK/UQ/FK inventories, and all FKs RESTRICT.

The green suites do not override the reproducible counterexamples.

## Boundaries and lifecycle

- Medical-source or internet requests: none.
- Only local loopback PostgreSQL validation occurred.
- Corpus/patient data: none.
- Reviewer writes and Git mutations: none.
- Dependencies, API/report integration and DM-003: unchanged/not started.

Terminal audit and the Git lifecycle are blocked until all nine findings are remediated
and a fresh complete independent review returns `P0/P1/P2 = 0/0/0`.
