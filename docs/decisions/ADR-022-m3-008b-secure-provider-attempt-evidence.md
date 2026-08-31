# ADR-022: Secure provider-attempt evidence ledger

## Status

Owner accepted for the clean M3-008B secure-attempt successor at baseline
`6ac4e4ab44949e0290bab8ef7775066f2ae6cdb8`. The failed predecessor delta is
`NONINTEGRABLE`, manifest
`sha256:3246ae79ae5d85ba9ea9627cae47450a5a333f55415dc8744cc26029b2c1dfb0`;
it was not inspected or copied. Historical attempts 001 and 002 remain
immutable external evidence and are not retrofitted. Attempt 001 exact hashes
are configuration `sha256:9ddaf38b6cc3c466ab354038697b2bbd767861bf3d3921727958a93fa209ffc9`
and status `sha256:bdfef50a49d49d41d42f13c176a5c1e7b5981244a0f9c387f2af6b058f50b4d6`;
attempt 002 exact hashes are configuration
`sha256:deb725ef6684d90bad8b33b02c5810db7375368cecaf2d8bb222268de9e4187c`
and status `sha256:6441d08e1a4521c6375d56211c5bc62484cfed7e18e99b21a4867789031fe227`.

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
plus `x-request-id`; values are never authoritative ledger content.

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
