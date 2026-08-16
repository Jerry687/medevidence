# ADR-015: M2-005 MedEvidence Gold-10 V2 acquisition and corpus freeze

- Status: Accepted by Project Owner; pre-network validation pending
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-15
- Approval reference: `M2-005-MEDEVIDENCE-GOLD10-V2`
- Revision: 1
- Independent review reference: Pending

## Context

M2-003 stopped permanently after six successful logical operations because its
one-section-per-LOINC assumptions did not represent the retained OZEMPIC SPL.
Its four ESearch responses, one 50-PMID EFetch response, and provider-original
OZEMPIC response remain immutable external evidence. Its unexecuted MOUNJARO
authority is closed and non-transferable. M2-004 now provides the additive
source-native occurrence contract needed by this evaluation.

## Decision

M2-005 reconstructs all four PubMed memberships and the exact 50-record EFetch
corpus offline. It repeats no PubMed or OZEMPIC request. One PMID remains one
retrieval item and preserves every originating ESearch membership.

The authoritative 627,087-byte OZEMPIC response remains in the M2-003 external
root. Evaluation may create a `derived_for_safe_parsing` artifact by deleting
only the exact prolog `xml-stylesheet` PI at raw byte range `[38,133)` and the
one exact root `xsi:schemaLocation` attribute at raw range `[220,306)` (pipeline
range `[125,211)`). Each step binds its input, removed bytes, output, range,
hashes, and exact splice equality. There is no reserialization, normalization,
dereference, or production-parser change.

The integrated M2-004 parser must reproduce 13 OZEMPIC occurrences: 12
text-bearing occurrences enter the retrieval corpus independently, while the
one no-text container remains provenance only. Repeated codes are not
deduplicated, concatenated, or reduced to a canonical occurrence.

Only after offline reconstruction, focused/full validation, independent
pre-network review `PASS — P0 0 / P1 0 / P2 0`, and an exact CLI
acknowledgement may the new M2-005 authority be consumed for one logical GET of
the exact MOUNJARO current-SPL URL. It permits at most two attempts, zero
redirects, and no other endpoint. Provider raw bytes are retained before
parsing. At most the same two optional deletion classes may be used; a third
compatibility transformation is forbidden. Any failed operation consumes the
authority, emits STOP evidence, and cannot be rerun.

On success the frozen corpus contains exactly 50 PubMed records, 12 distinct
OZEMPIC occurrences, and every retrieval-eligible MOUNJARO source-native
occurrence. Structural DailyMed occurrences are provenance only. The ten-
question adjudication packet uses deterministic hash ordering and excludes all
rank, score, retriever, and nomination fields. It never creates authoritative
qrels. Human relevance adjudication is a new Owner decision, and no retrieval
benchmark may run first.

## Security and provenance

The strict production DailyMed parser is unchanged. DTD, entity, XInclude,
XSLT, schema-resolution, namespace, identity, depth, size, and external-
resource controls remain fail closed after deletion. Raw and derived medical
bytes remain outside Git. The cumulative retained raw-byte ceiling across the
reused stopped run and recovery is 15,728,640 bytes.

## Consequences

The pre-network code path has no import-time or fallback I/O and cannot create
a socket-capable client. Live execution requires a hash-bound independent
review record plus the exact acknowledgement. That record binds the exact
pre-network manifest bytes and sidecar, every candidate source-state hash, and
every retained artifact and sidecar, including the directly imported DailyMed
policy module; all are recomputed before client construction and the saved
PubMed/OZEMPIC inputs are rebound again before final corpus freeze.
Count-preserving edits and policy drift therefore fail closed. Client
construction occurs only after the one-shot authorization is consumed and
inside the STOP-producing transaction, so constructor failure is terminal and
cannot create request-attempt, corpus, packet, or success evidence.

Each MOUNJARO attempt transactionally retains raw or bounded partial bytes,
only the operational response headers needed for validation, retry, redirect,
and body-integrity evidence, and the current attempt ledger before header,
retry, transformation, identity, or parser finalization. Authorization,
Set-Cookie, and arbitrary non-operational response-header values are not
retained. Any failure emits a STOP record linked to available evidence and
removes incomplete corpus/packet outputs. The corpus and packet exist only
after a successful one-shot recovery; until live operation begins the new live
authorization remains unconsumed.
