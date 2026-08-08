# M1A live PubMed gate readiness

Updated: `2026-08-08`

Status: **CANDIDATE - offline constructibility validated; post-remediation PR-head review and final audit pending**

## Frozen gate

ADR-009 §14 and the current `tests/e2e/test_live_pubmed.py` define a separate
single-shot gate for the bounded PubMed smoke query. The gate remains disabled
unless all of the following are true:

- the `-m live_api` pytest marker expression is explicitly selected (the live
  test also carries the `live_api` marker);
- `MEDEVIDENCE_RUN_LIVE_PUBMED=1` is explicitly supplied;
- the Owner supplies a nonblank `NCBI_EMAIL`;
- `MEDEVIDENCE_LIVE_SNAPSHOT_ROOT` resolves outside the Git repository;
- the HTTPS origin is exactly `https://eutils.ncbi.nlm.nih.gov`;
- only `/entrez/eutils/esearch.fcgi` and `/entrez/eutils/efetch.fcgi` are used;
- `tool=medevidence` is enforced by `PubMedClientIdentity`;
- one search page and at most one fetched record are permitted;
- HTTP transport retries, connector attempts, redirects, and concurrency remain
  bounded with no default retry expansion; request attempts are recorded
  separately from logical pages; and
- raw source bytes are never committed to Git.

The executable query derived from the frozen `REQUEST_EXAMPLE` is:

```text
("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])
```

## Required redacted acceptance record

An authorized run must write its raw response bytes, journal records, and
canonical manifests beneath the Owner-supplied external root. It must also
write a redacted acceptance record containing, at minimum:

| Field | Required meaning |
|---|---|
| `query` | Exact query sent to ESearch |
| `executed_at_utc` | UTC execution timestamp |
| `code_revision` | Exact 40-character code revision |
| `connector_version` / `schema_version` | `m1a-002` / `1.0` |
| search/fetch outcomes | Terminal source outcomes, with fetch explicitly marked not executed when no PMID was returned |
| request counts | Per-operation and total bounded request counts |
| raw artifact IDs | SHA-256 identities of retained raw responses only |
| snapshot/manifest IDs | Canonical manifest identity, never fabricated from a raw artifact hash |
| storage locations | External snapshot root and manifest/acceptance paths |
| redaction proof | No raw abstract/body, credential, header, or source payload in the summary |

The current merged contract treats a persisted acquisition snapshot identity
and its manifest identity as the same canonical manifest identity. The raw
artifact IDs remain separate and are listed independently.

When a failed/unavailable connector operation has received response bytes, the
test-only readiness path preserves those bytes under a failed/partial manifest
because the frozen unavailable manifest is zero-file only. A completely
unavailable operation with no bytes remains a zero-file unavailable manifest.
The acceptance summary retains the terminal connector outcome separately, so
partial retained evidence is not converted into a successful or exhaustive
no-result claim.

## Offline constructibility

`tests/e2e/test_live_pubmed.py` contains no-live synthetic shape and retry-bound
tests. It
uses the existing `capture_acquisition`, `SnapshotManifest`, `ArtifactLink`,
`AcquisitionIntent`, and `AcquisitionRegistrationEnvelope` contracts and a
temporary external root. It does not instantiate a real transport, select the
live marker, or contact NCBI. The actual live test remains skipped by default.

The final evidence decision must bind to the exact candidate and must include
fresh focused no-live tests, the sockets-disabled unit/contract suite, Ruff,
format, MyPy, diff-check, and changed-path checks. No live acceptance result is
claimed here. The focused suite completed with `43 passed, 1 skipped`; the
full offline unit/contract suite completed with `713 passed` and 79% reported
coverage. Ruff, format, MyPy, lock, diff-check, exact baseline/ancestor, and
authorized-path checks passed. The earlier worktree review passed before the
marker-gate remediation; post-remediation PR-head review and terminal audit
remain pending.

## Owner gate still required

This record does not authorize a live request. Before any live execution, the
Project Owner must approve the exact query, NCBI email, execution UTC window,
external snapshot root, command, and final acceptance review. A source outage
or unavailable live response must remain unavailable/partial evidence, never a
claim that no PubMed result exists.
