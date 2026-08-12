# M1B-DM-002 Independent Review 002

Verdict: `FAIL — P0 0 / P1 3 / P2 0`

## Reviewed identity

- Branch: `feat/m1b-dm-002-connector`
- HEAD/baseline: `6eecfd9da033ccf56f05ea59f0a636b463d6a2b9`
- Owner-freeze SHA-256: `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- ADR-011 SHA-256: `4b1a0f24d69882c10ac476a43008262ad6845e69f93af9295e0f3dae2b429471`
- Review001: 6,482 bytes, SHA-256
  `31211409c6f51a812ed35066363959dfe9cb7c85cd0b564597f13579825cb766`
- Exact 36-path Ordinal/no-terminal-LF manifest:
  `dd14c2b59a27817cd1d4892f75999fc0d68f0e3f6a4f26b5dda0f8079ab56d64`
- Index empty; scope remained inside the authorized paths; strict UTF-8/LF and
  `git diff --check` passed.

## Findings

### P1-01 — Typed discovery permits queries beyond the frozen 512-character bound

`build_dailymed_request(DISCOVERY, query={"drug_name": "a" * 513})` succeeded.
Typed query construction checked nonblank/control constraints but did not enforce the
frozen cumulative pre-encoding canonical-query-character ceiling.

Acceptance: enforce exact cumulative canonical query length at construction and
revalidation, and add 512-positive, 513-negative, multi-field cumulative, Unicode, and
mutated-request tests.

### P1-02 — Snapshot capture/replay omit the cumulative 5,242,880-byte bound

A `DailyMedSnapshotManifest` containing two complete response members of 3,000,000 bytes
each was accepted (`6,000,000 > 5,242,880`). Member-local bounds did not enforce the
acquisition-level response-body ceiling.

Acceptance: enforce cumulative exact response bytes in manifest validation, before any
publication, and during replay; specify stable-SPL duplication accounting consistently;
add exact-bound, plus-one, multi-page, partial-prefix and zero-file tests proving failed
preflight writes nothing.

### P1-03 — Public generic persistence bypasses specialized DailyMed comparators

`insert_or_verify_m1b()` remained public for specialized DailyMed tables. It could insert
a valid label-version row backed by a `dailymed_http_response` artifact because the SQL FK
does not include artifact kind/path/schema, and generic supersession A→B/B→A bypassed
the specialized cycle check.

Acceptance: reject specialized DailyMed tables from the generic entry or route them
through the full authoritative comparator; add direct public-API negatives for wrong
artifact kind/path/schema, missing parent, cycles, and decision-comparator bypass.

## Review001 closure and validation

Review001 P1-01 through P1-07 and P1-09 were verified closed. P1-08 remained open only
through P1-03 above. The self-contained migration embeds 15 immutable PostgreSQL DDL
statements, hashes its payload, imports no application persistence metadata, and matches
the frozen 201-column catalog.

Fresh reviewer evidence:

- Ruff: passed; format: 79 files formatted.
- MyPy: 39 source files passed.
- Unit/contract, sockets disabled: `1104 passed`, two expected warnings.
- `git diff --check`: passed.
- PostgreSQL candidate evidence: six passing tests; reviewer did not rerun it because the
  review node was read-only and prohibited database writes.

No medical-source/internet access, corpus/patient data, dependency, repository write,
Git mutation, API/report expansion or DM-003 work occurred.

Terminal audit and the Git lifecycle remain blocked pending remediation and a fresh
complete `P0/P1/P2 = 0/0/0` review.
