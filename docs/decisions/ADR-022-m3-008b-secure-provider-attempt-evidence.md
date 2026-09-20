# ADR-022: Secure provider-attempt evidence ledger

## DeepSeek calibration-path closure

The Owner closes the DeepSeek calibration path as
`M3-008B-DEEPSEEK-CALIBRATION_CLOSED_EXTERNAL_EXECUTION_NOT_ACCEPTED`.
Attempt009 and Attempt010 are immutable provider-attempt evidence. Each succeeded on
cases1-4, then case5 received HTTP 200 responses that did not complete within
the unchanged governed shared deadline: attempt1 closed
`transport_unavailable`, attempt2 closed `deadline_exceeded`, and no attempt3
started. Implementation review remained `P0 0 / P1 0 / P2 0`; neither attempt
established accepted 36-case metrics or an accepted calibration artifact. This
closure records external-execution non-acceptance, not implementation failure.

Attempt011, deadline/retry weakening, M3-009, and Holdout-20 access are not
authorized. All historical ledger rows, raw identities, projections, status
bindings, and hashes remain unchanged. Retained DeepSeek provider-attempt code
is historical infrastructure and is not current provider execution authority.

## Status

The original secure-attempt successor was Owner accepted at baseline
`6ac4e4ab44949e0290bab8ef7775066f2ae6cdb8`. Its failed predecessor delta is
`NONINTEGRABLE`, manifest
`sha256:3246ae79ae5d85ba9ea9627cae47450a5a333f55415dc8744cc26029b2c1dfb0`.
Later `M3-008B-SUCCESSOR-003-DECLARATIVE-FRAMING-CONTRACT` is also frozen
`FAILED / NON-INTEGRABLE`; its 26-path delta must not be staged, committed, or
integrated.

The Owner accepts the provider transport, credential handling, durable attempt
ledger, framing/media authority, V1/V2 evidence separation, and terminal
evidence architecture from
`M3-008B-SUCCESSOR-004-SINGLE-SOURCE-FRAMING-AUTHORITY` for successor reuse.
The exact Successor-004 calibration remains not accepted, and Successor-004 was
not integrated. Successor-005 mechanically reconstructs its exact audited
25-path manifest
`sha256:3764ce9a44294a0d2df1c7d9864747c1869fc4f6a88aded89d0567f387b19faa`
at baseline `26c67108bf5b8de8b05bddf7e7ec5bac61261425` as implementation input.
ADR-023 owns the new semantic-contract decision; this ADR remains the provider-
attempt infrastructure and immutable-history authority.
The active successor binds semantic contract identity
`sha256:9b97996233f6dc80091f196209b18c27b23e0eeb5c82c6e7e8c0f954df69a3bb`
and DeepSeek profile identity
`sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9`
outside this historical framing authority.

Historical attempts 001-003 and their V1 ledger/external bytes remain immutable
and are not retrofitted with V2 observations. Attempt 001 exact hashes
are configuration `sha256:9ddaf38b6cc3c466ab354038697b2bbd767861bf3d3921727958a93fa209ffc9`
and status `sha256:bdfef50a49d49d41d42f13c176a5c1e7b5981244a0f9c387f2af6b058f50b4d6`;
attempt 002 exact hashes are configuration
`sha256:deb725ef6684d90bad8b33b02c5810db7375368cecaf2d8bb222268de9e4187c`
and status `sha256:6441d08e1a4521c6375d56211c5bc62484cfed7e18e99b21a4867789031fe227`.

## Successor-004 infrastructure decision

Exactly one ordered declarative framing contract is authoritative for Python
classification, finalizer recomputation, PostgreSQL acceptance, generated
Python/SQL cases, and external projection. Rules encode first-match precedence,
required/forbidden observation facts, accepted classes, rejection codes, body
completeness, safe raw evidence, approved-header identity, and JSON media
requirements. PostgreSQL uses the generated ordered `CASE` result and explicit
null-total comparisons; unordered OR logic and SQL UNKNOWN are not authorities.

The finalizer receives raw canonical observation facts, reconstructs the exact
approved-header surface, recomputes framing and media admission, and compares
any stored/projected decision to that result before durable success. Accepted
framing requires a complete exact credential-safe raw body with byte count,
hash, and artifact/path identity. Content-Length mismatch is valid only with a
complete body plus present valid unequal actual/declared counts. JSON parsing
or envelope validation starts only after media admission; syntactically valid
JSON under `text/html` fails closed. Evidence-persistence failure remains a
separate terminal path and does not invent framing observations.

Only normalized facts from the exact approved header names may influence the
classifier. Their names, approved-name identity/hash, and classifier input
identity remain mutually bound. Generated cases cover every isolated rule,
multi-defect precedence, each accepted class, noncanonical projected tuples,
raw/body/media/header negatives, credential echo, persistence failure, and V1
reconstruction.

The only exceptional layer edge permits exactly
`persistence/models.py` and `persistence/repositories.py` to import the exact
standard-library-only `medevidence.tools.provider_attempt_framing` module. It is
not a prefix allowance: other persistence consumers and tools siblings or
submodules remain prohibited and AST-tested.

Attempt004 is immutable failed evidence. It executed exactly two HTTP
operations and persisted four ledger events: case 1 succeeded; case 2 failed
closed as `candidate_invalid`. Its configuration/run binding is
`sha256:9f10f1f340227b01355f72bf2bae64ff1072fbeece5eb4af573cbfd92c2e81ca`,
status binding is
`sha256:11773259f0f73c71c06589947b54e38bce4bcd8576628b59c4fd626b9ec4206d`,
and projection identity is
`sha256:0a0421855b6ec235e5526c8c97b5226a5635ae98b67b92de5a7fb386ad92a5bf`.
Case 1 raw evidence is 7,475 bytes with SHA-256
`bbadba0b99e76e6955029e7f4c508484240ae28b723df9394f0bdda7be61b6f5`;
case 2 raw evidence is 7,918 bytes with SHA-256
`f783c278245b192b644cf9c2061289d61df9a4e79e953e4730e43a01fe5e5e0b`.
No raw explanation or provider reasoning is reproduced here.

The first diagnosis was a globally applicable rationale-order ambiguity. It was
closed by Development prompt/rubric version 2 and result.v2 while retaining the
exact parser. Attempt005 then executed exactly one HTTP/2 operation. Its framing
and provider envelope were valid, but its 421-byte structured result contained
six line feeds and 15 indentation spaces. The exact parser correctly rejected
that noncanonical wire as `candidate_invalid`; the 400-byte minified form is a
test-only diagnostic witness and was never accepted as provider output.

Attempt006 is immutable historical V1 evidence under Development prompt/rubric
version 3 of 3 and DeepSeek configuration version 4. Its first five cases
succeeded. Case006 produced valid provider output, but the V1 application-
policy binding failed as `human_review_binding_invalid`. The governed
classification is
`V1_PROVIDER_OUTPUT_VALID_BUT_APPLICATION_POLICY_BINDING_FAILED`; this is not a
model semantic failure. Attempt006 did not complete the 36-case calibration and
does not satisfy calibration acceptance. No ledger row, raw provider byte, or
historical V1 identity is rewritten or relabeled.

The new Attempt007-009 authorization belongs only to the distinct Stage2
Semantic Contract V2 decision in ADR-023. It does not reopen the exhausted V1
prompt/rubric family. Every attempt remains separately numbered and immutable,
and Holdout-20 remains sealed.

Attempt007 is immutable failed Semantic Contract V2 Development-version-1
evidence under provider configuration v1
`sha256:2798cf926eb197b746fd3c321d50047c28dea5061d2f4613adb5c81b30c80b35`.
Run identity
`sha256:a8c2038480addeb7255dd71592ac40888ab6ee22d1d945c44e6110cc0e7f5ce5`
contains exactly 10 ledger events and five HTTP attempts. Cases1-4 succeeded.
Case5 received HTTP 200 over HTTP/1.1 with one `chunked` transfer coding and
valid headers, but its bounded observation was `body_complete=false`, body
lower bound zero, no raw artifact, and framing `response_body_incomplete`; the
terminal disposition is `response_invalid`. No quality result or accepted
calibration artifact exists.

The exact ledger-derived projection identity is
`sha256:67e8af93d6eda5dddd34f94ac2ac705e44af9f5fa4930d605c7ce57d98206684`,
status identity is
`sha256:4983adfb94b9adc41778829134842af24fc54a6615359711d06b3987f5b7aa9c`,
and external configuration-file identity is
`sha256:bb051d2244b452df3668c62b2a1694ee59d9d64711d902ed615d702d31a20376`.
No raw response content, credential, explanation, or provider reasoning is
reproduced here.

The bounded defect was that a pre-deadline stream `TransportError` mapped to
permanent `response_invalid`, suppressing the authorized transport retry.
Attempt008 provider configuration v2 maps that class to retryable
`transport_unavailable`, while preserving the original coordinator absolute
deadline, maximum three attempts, a fresh closed response per attempt, and no
partial raw artifact. A failure at or after the exact deadline remains
`deadline`; credential failures and complete invalid responses remain
nonretryable.

Attempt008 is immutable failed evidence under provider configuration v2,
identity
`sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9`.
Its exact implementation manifest is
`sha256:bdbc9b07a12433b082bc6d1bec62445f9e73810f2b6ed7857c700e92526b19b2`.
Run `sha256:0b4e918e30c511174ad12ce6b07b25312688995fb2dc46d81868e2caa40baa89`
contains exactly 12 ledger events and six HTTP attempts. Cases1-4 succeeded
with exact raw evidence. Case5 attempt1 closed `transport_unavailable` after
HTTP 200 with an incomplete zero-byte-lower-bound body and no raw artifact;
attempt2 closed `deadline_exceeded` under the same absolute deadline with no
raw artifact. No attempt3 occurred.

The exact projection identity is
`sha256:936ddc9e280b9ed5bda1f2b630c675d54e75e58c2a3dbb7a67cdf35b781ecbb5`
and status identity is
`sha256:ca68ddf05134464d5d1802b11b113440b63752e5f5aa809f1614a7d816448185`.
This is truthful provider-availability/deadline evidence, not a code or semantic
defect. It yields no quality result or accepted calibration artifact, and no
raw response content or provider reasoning is reproduced here.

The immutable Attempt004 DeepSeek V2 profile hash is
`sha256:35b8411e401f32f974dd1d795770b4db73e622165ead9e83bc3356190b50b377`.
The immutable Attempt005 exact authorities are prompt
`sha256:a038f2e5136bf1b81e34571fc305ea421f3377898debbba3b90169dcc2d42f1e`,
rubric
`sha256:8ead4e58a6828611c8c0d65b7c72e050bf339dee601ef2d861791b43513dc1c3`,
result schema
`sha256:4cd8f7293f98a63398a585adaf8285bc1b9230b94284417816d96549a4bfdf25`,
and DeepSeek V3 configuration
`sha256:b625eacd4439ea08b141c79ab79de4ed348610b3a9ace4be80977e73a704e8ef`.
Its provider-run identity is
`provider-attempt-run:sha256:cf810656f57cd738b59abd8694b07855b4be9839b5e495a9dfe31548d35ede31`.
Case 1 request bytes are 5,972 bytes with SHA-256
`6d8d309524aa47dc342bbb2226f5e31003578be915bfed6bafc57f8b39b4f9c8`.
The ledger has exactly one START and one bound `candidate_invalid` terminal.
The exact raw response is 8,977 bytes with SHA-256
`9141329b33f96df06cf6d889fa5c164c87acee8a3f0a2ac43712c8f01bb76f18`;
the ledger-derived projection and status identities are respectively
`sha256:0dddbbb75c5d46822d1e01acfb03c6e13588d90fa4a2f2e0fe033ff881e892f6`
and
`sha256:596b133e9468f21712ba789f6f5c41c9627957cf7b7d97dc9eb02d42db7e3a99`.
The rejected structured output is 421 bytes with SHA-256
`c3fc115886cdd303a33c2288dd16fac01630c914d9a9fb972b88d3444e8bb383`;
the test-only canonical diagnostic is 400 bytes with SHA-256
`c3e9f566882dde1b5d3af93efe5318ee430e26a38a6cad2f653c93b4bfd7a7f5`.
Neither explanation text nor encrypted/provider reasoning is surfaced.

The immutable Attempt006 exact V1 authorities are prompt
`sha256:d74952ab1caa01f8a6149a25b1bdf4de2c4ded4146530b2e4a14004ded6dca57`,
rubric
`sha256:3ba1fc8ca4ce26a7513c2acb27498800e383ff1d0e6d0c8ed3aa763a6b06819e`,
unchanged result schema
`sha256:4cd8f7293f98a63398a585adaf8285bc1b9230b94284417816d96549a4bfdf25`,
and DeepSeek V4 configuration
`sha256:44252c496d5aa0b45053e4b328c6cedee15bb17dbedc093f9e1fd1dd80b3b5ae`.
The frozen case-1 credential-free request is 6,329 bytes with SHA-256
`aac343cfae2a75877b3461485097c9fb9592d9f89e8be91ffc685601db197392`.
Historical Attempt004 and Attempt005 request/config/result reconstruction uses
only its original profile and cannot be silently rebuilt from Attempt006 or
active Successor-005 bytes.

## Decision

Provider-attempt truth is an isolated PostgreSQL
`m3_provider_attempt_events` insert-only ledger. It does not reuse validation
receipts. Every actual HTTP operation requires a committed `START`; exactly one
`TERMINAL` or later `RECOVERY` closes that run/case/attempt ordinal. A unique
run/case/attempt/event-slot constraint prevents concurrent duplicate sending.
The repository exposes insert, ordered read, and orphan recovery only—no update
or delete API.
`TERMINAL` and `RECOVERY` share the same closure slot and bind the exact START
through a composite self-reference over event/run/case/attempt/config/request;
both closures therefore cannot coexist. A session-level PostgreSQL advisory
lease is held for the whole provider run without keeping a transaction open
across network I/O. A second process cannot recover or send while that lease is
held; crash release permits the next holder to recover before any send.
All preflight, recovery, transport, persistence, publication, and cleanup paths
sit beneath lease release; transport-close or publication failure cannot return
a pooled connection with the advisory lock held. Every handled post-START path
receives one closure, including normalized provider-envelope failures and the
safe `evidence_persistence_failure` disposition. Only uncertain TERMINAL insert
leaves START for later RECOVERY and never triggers an immediate retry.

The DeepSeek transport performs exactly one operation. Retry coordination is
static application composition. Before startup sends anything, orphan STARTs
are recovered as `interrupted_unknown_after_start`; existing authoritative
events are reprojected and never resent.

Credential representations are detected in memory before response values are
hashed or persisted: literal ASCII; standard Base64 padded/unpadded; URL-safe
Base64 padded/unpadded; lowercase/uppercase hexadecimal; and distinct
JSON-escaped content; full-byte percent encoding in upper/lower hex; and
RFC3986 quote-from-bytes percent encoding in upper/lower hex. Detection spans
stream chunk boundaries. A credential-bearing body or admitted header is cleared and
produces only a safe `credential_echo` terminal event—no body/header value,
hash, or raw file.

Safe complete bodies within 131,072 bytes are fsynced to the absent external
run before framing, content-type, UTF-8, JSON, or provider-envelope validation.
Only then is `TERMINAL` committed with exact hash/count/path binding and final
closed disposition. Overflow and incomplete bodies have no raw file/hash and
retain bounded facts only. Allowed header names are the four protocol headers
plus `x-request-id`; raw values are never authoritative ledger content. Only
canonical normalized facts bound to the exact approved-name identity may feed
the Successor-004 classifier.

External JSON is a projection. Verification reloads ordered ledger events,
recomputes attempt count/status/dispositions, and verifies every bound raw file.
Caller-edited projection bytes remain invalid even with a recomputed JSON hash.
Final run status and calibration artifacts bind that authoritative projection
identity and inventory. Empty and START-only ledgers are nonfinal; terminal-only,
mismatched, or dual-closure topologies reject.
Each case begins at attempt 1 and uses contiguous ordinals through at most 3.
Only `retryable_status` or an actually retried `transport_unavailable` may
precede another attempt; success or any nonretryable closure is final. COMPLETE
requires all 36 cases to end in success. Every START request hash must equal the
case's exact credential-free request, and final success requires a complete raw
body whose ledger hash/count/path equals the artifact response bytes.

External verification takes independent expected code revision, implementation
manifest, and provider-run ID. It reconstructs the expected run configuration,
reloads ledger rows, checks run configuration/status binding, artifact presence,
artifact sidecar, metrics acceptance, attempts, dispositions, and raw files.
Artifact fields are never recycled as expected authority.
Publishing and verification share one closed run-status builder derived only
from the trusted configuration, reconstructed ledger, exact artifact bytes,
metrics, and file inventory. Every field, ordered ID/count, attempt total,
artifact SHA/sidecar flag, accepted value, status, and binding hash must match.

Retry timing remains frozen at the application coordinator: one monotonic
45-second deadline spans all attempts for a case; each operation receives only
the remaining budget. Backoff is exponential from 0.25 seconds with
request-hash/attempt deterministic jitter. Numeric or HTTP-date Retry-After is
used only in memory and capped at 2 seconds; it is never added to the diagnostic
header allowlist. No sleep or new START occurs if the delay would exhaust the
total deadline.

Each successful case file is a deterministic ledger projection rebuilt from
the frozen case/request, all START rows, final successful TERMINAL, and exact
bound raw response. Provider result/usage and human disagreement are re-parsed
before whole-object and binding-hash checks. A post-TERMINAL case-file failure
never creates another closure or resends; startup repairs only the missing or
corrupt projection from authoritative ledger/raw evidence, publishes a
reconciled FAILED run, and stops. Retry-After is nonpersistent but is scanned
in memory for credential representations before timing use; a match closes as
`credential_echo` with no retry, value/body hash, or persistence.

Every existing external/output ancestor is checked for symbolic links and,
on Windows, reparse-point/junction attributes before writes; resolved paths
must stay inside the intended external root.

## Boundaries

This adds one table and no dependency, public API, medical-source traffic,
source/evidence semantics, retrieval change, provider selection, or Holdout
authority. DeepSeek remains advisory and public-research-data-only.
