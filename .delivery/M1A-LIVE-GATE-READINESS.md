# M1A live PubMed gate readiness

Updated: `2026-08-08`

Status: **M1A_LIVE_RUN_001_EXECUTED; LIVE_GATE_ACCEPTANCE_UNRESOLVED;
NO_RERUN_AUTHORIZED;
M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE;
CLIENT_XML_DTD_INTEROPERABILITY_FAILURE; NO_LIVE_PASS;
SECOND_RUN_OWNER_CONTROLLED**

Current baseline: PR #9 merge
`e8e28ffbde7fa3994ff8aa71dd62a956250147c1`

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
not a rerun or a live PASS. Any second live run remains Owner-controlled and
requires exact new authorization. See
[the interoperability record](M1A-PUBMED-DTD-INTEROPERABILITY.md).

The exclusively created recovery record is
`acceptance/pubmed-live-run-001-recovery.json` under the approved external root:
3,032 bytes, SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
It is structurally validated and contains no sensitive value, raw content,
header, complete URL, or source payload. See
[M1A-LIVE-RUN-001-RECOVERY](M1A-LIVE-RUN-001-RECOVERY.md) for the sanitized
inventory and disposition. This is not `M1A_LIVE_ACCEPTANCE_PASS`.

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

The earlier readiness and recovery results remain historical evidence. After
reviewer-triggered mechanical rework pass 2, cycle 4 has fresh sockets-disabled
evidence of `38 passed, 8 deselected` for the privacy/static/subprocess
selection and `44 passed, 2 skipped` for the complete E2E module; one skip is
the directly unselected child probe and one is the default-disabled live test.
Ruff and format checks pass on the test file. Reviewer-triggered internal
rework passes consumed: `2` of maximum `2`.
Applicable integration validation, independent review, terminal evidence
audit, candidate identity, and any later Git action remain pending. No reviewer
PASS, audit PASS, commit, PR, merge, or live acceptance PASS is claimed here.

## Owner-controlled next live gate

The prior authorization was consumed by live run 001 and does not authorize a
rerun or second live execution. The failed interoperability disposition does
not establish live acceptance PASS. A failed/unavailable source outcome remains
indeterminate and is never a claim that PubMed has no results. Do not claim M1A
completion or begin M1B Owner planning from this record. A second live run may
occur only under a new exact Owner authorization.
