# M1A live PubMed gate readiness

Updated: `2026-08-09`

Status: **M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE;
M1A_LIVE_RUN_002_ACCEPTED; M1A_LIVE_ACCEPTANCE_PASS; M1A_COMPLETE;
READY_FOR_M1B_OWNER_PLANNING**

Current approved baseline and accepted live code revision:
`531f867006f3d01ebbc14633ad6e5509e4e70a47`

## Frozen gate

ADR-009 Section 14 and `tests/e2e/test_live_pubmed.py` define a separate
single-shot gate for the bounded PubMed smoke query. The gate is disabled by
default. The separately authorized live run could execute only when all of the
following were true:

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

## Live run 002 accepted disposition

The separately authorized live run 002 executed at
`2026-08-09T05:13:33.284549Z` on code revision
`531f867006f3d01ebbc14633ad6e5509e4e70a47`. It used schema `1.0`, connector
`m1a-002`, and retention policy `M1A-LIVE-RETENTION-v1`.

One run comprised two contiguous acquisitions and exactly two requests:

- search: `succeeded / partial / matches`, 100 valid results, one page,
  `truncated=true`;
- fetch: `succeeded / complete / matches`, one valid retained publication,
  one page, `truncated=false`.

The search is explicitly bounded and non-exhaustive. The successful fetch of
one retained publication does not upgrade search coverage to complete.

The external redacted acceptance record uses root label
`OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT` and relative label
`acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json`. It is 3,223
bytes with SHA-256
`008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`.
The closed-contract validation passed raw, manifest, linkage, and envelope
identity recomputation; containment outside Git; schema and redaction checks;
and unexpected-file checks. It found zero reparse points, zero unexpected
absolute references, no temporary or unexpected files, exact false redaction
flags, and no forbidden normalized key, complete URL, raw XML, or abstract
field.

Operator-supplied evidence reports that the exact live test exited `0` with
`1 passed`, wrote the acceptance record, cleared supplied environment values,
and left the repository clean immediately after the live run. This
documentation node did not independently rerun that command. No rerun occurred;
the medical-source authority is consumed and `rerun_authorized=false`.

See [the Run 002 acceptance record](M1A-LIVE-RUN-002-ACCEPTANCE.md). The
validated disposition is `M1A_LIVE_RUN_002_ACCEPTED` and
`M1A_LIVE_ACCEPTANCE_PASS`. With offline M1A already integrated, M1A is
`M1A_COMPLETE` and `READY_FOR_M1B_OWNER_PLANNING`. M1B has not started.

## Live run 001 recovery disposition

The separately authorized command executed one bounded ESearch request at PR
#8 merge `09cc42838475a4c1bab62050fbfeac14c5dd6761` and exited `1`. It did not
write the original acceptance record: the former
redaction assertion compared every response-header value as a substring and a
harmless numeric rate-limit value collided with unrelated safe summary text.
No rerun was performed.

The immutable evidence was recovered and validated without another source
request. Typed canonical parsing, identity recomputation, manifest replay, raw
hash/size verification, frozen request/attempt bounds, UTC ordering, and the
deterministic first-page `InvalidPubMedXmlError` establish a reconstructed
connector outcome of `failed / unavailable / indeterminate`. The persisted
manifest and envelope separately remain `failed / partial / indeterminate`
because received bytes must be retained; their coverage is not equated with
connector coverage. One retained response plus `attempts_used=1` proves exactly
one request. The failed first search returned no PMID and could not enter the
fetch branch; the exact layout also contains no `acquisition-0001`.

The exact retained bytes now parse offline under the bounded external-provider
DOCTYPE compatibility candidate as `PubMedSearchPage`, with `count=676`, 100
returned identifiers, zero socket calls, and zero external file-open calls.
The root cause is therefore `CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`, not an
NCBI outage. Live run 001 is accepted as failed interoperability evidence; its
historical connector and persisted evidence outcomes remain unchanged. This is
not a rerun or a live PASS. At that historical disposition a second live run
remained Owner-controlled; the later separately authorized Run 002 is the
accepted execution described above. See
[the interoperability record](M1A-PUBMED-DTD-INTEROPERABILITY.md).

The exclusively created recovery record is
`acceptance/pubmed-live-run-001-recovery.json` under the approved external root:
3,032 bytes, SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
It is structurally validated and contains no sensitive value, raw content,
header, complete URL, or source payload. See
[M1A-LIVE-RUN-001-RECOVERY](M1A-LIVE-RUN-001-RECOVERY.md) for the sanitized
inventory and disposition. This is not `M1A_LIVE_ACCEPTANCE_PASS`.

## Accepted redacted acceptance contract

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

Under the exceptional Owner authorization for
`M1A-LIVE-RUN-001-RECOVERY-AND-REDACTION-HARNESS-FIX`, cycle 4 changes only the
test harness and disposition documents. The live test now retains only safe
marker/opt-in gating, calls one traceback-hidden sensitive executor, and
asserts a frozen closed scalar result. The executor alone reads the Owner email
and external root, constructs and closes the connector, owns all provider/raw
values, persists evidence, and translates every ordinary failure to a new
fixed-code redacted harness exception with its original chain suppressed.

`tests/e2e/test_live_pubmed.py` also contains offline synthetic shape,
retry-bound, normalized closed-schema privacy, harmless rate-limit collision,
nested forbidden-key variants, `-vv --showlocals` pytest-output disclosure,
AST/source-contract, typed recovery, parser-failure, fetch non-execution, and
no-clobber tests. The AST gate derives the complete local-helper closure from
the sensitive executor, rejects every reference to the `pytest` module or a
propagated alias anywhere in that closure, detects imported/aliased
`pytest.fail`, and infers newly introduced raw-bearing helpers even when they
are absent from the supplementary sensitive-function registry. These tests use the existing `capture_acquisition`,
`SnapshotManifest`, `ArtifactLink`, `RunIntent`, `AcquisitionIntent`,
`AcquisitionRegistrationEnvelope`, and `replay_manifest` contracts with
synthetic data and temporary roots. Offline validation does not instantiate a
real transport, select the live marker, or contact NCBI. The live test remains
skipped by default and still requires both explicit marker selection and the
Owner environment opt-in.

The earlier readiness and recovery results remain historical evidence. The
cycle-4 privacy correction and provider-DTD interoperability work are integrated
in the accepted code revision. Their historical sockets-disabled evidence and
review records remain unchanged. Run 002 is the later separately authorized
live acceptance described above; it does not rewrite the failed Run 001
outcomes.

## Owner-controlled future boundary

The Run 002 authorization is consumed. No rerun or further live execution is
authorized, and `rerun_authorized=false`. Every future medical-source request
requires a new exact Owner authorization. M1A completion authorizes only the
transition to a separately approved M1B planning item; it does not start M1B.

The partial search is non-exhaustive and establishes no causal, incidence,
comparative-risk, diagnostic, treatment, dosage, or individualized clinical
conclusion. The draft remains research-only, non-exportable, and non-clinical.
