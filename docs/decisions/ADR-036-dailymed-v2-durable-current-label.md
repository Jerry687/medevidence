# ADR-036: Durable DailyMed V2 current-label execution

Status: implementation candidate; offline fixtures and isolated PostgreSQL only.

## Decision

The DailyMed V2 bridge records a typed acquisition START and immutable request intent before each connector call. A START without a terminal acquisition is unknown and is never resent automatically. A completed acquisition is reused only after the original response bytes, ordered response membership, manifest, PostgreSQL source graph, and typed result are replayed. Construction and imports perform no source I/O.

The current-label path uses source-native discovery, captures a packaging response for every candidate allowed by the eight-operation budget, applies the strict V2 selection contract, and fetches only the selected current SPL. Packaging failures use `enrichment_unavailable`; unsupported pagination uses `enrichment_pagination_unsupported`. Both require review. The packaging source outcome records what actually executed, even when no candidate is admitted. Historical pins remain unavailable. Ingredients come only from retained packaging products, never the query or discovery title.

If a later page fails after earlier complete pages, connector-level `value=None` does not erase those earlier observations. The bridge reparses each unique retained complete 200 page, records its authentic partial match count with failed/partial coverage, and keeps automatic selection blocked. Restart repeats the raw-page reconciliation without another request.

Each operation retains every observed response in an immutable V2 manifest, at most 20 responses (four for selected SPL). The additive `m3_dailymed_v2_members` table binds response ordinal, link, artifact, status, page, attempt, URL, size, and hash; two attempts with identical bytes remain separate members. The legacy membership uniqueness is unchanged. Original medical response bytes remain in bounded local snapshots, not PostgreSQL BYTEA. Typed V2 records and a 2 MiB journal bind discovery, packaging, decision, selected SPL, and section chunks. The source connector's per-response and operation limits are enforced; this decision does not claim a new aggregate time or byte ceiling across the whole source task.

For a selected SPL, source-native section occurrences, including no-text parents, are retained. Only text-bearing sections produce retrieval evidence. Text is divided into contiguous 4096-codepoint slices without rewriting. Every slice records source path and ordinal, start/end offsets, full-section and chunk hashes, and a canonical EvidenceInput identity. Each selected SPL is limited to 100 chunks; all selected SPLs combined are limited to 100 admitted chunks for the DailyMed source task. If the combined limit is exceeded, the completed source captures remain truthful but no partial subset is admitted. No unproven numerical facts, causal inference, incidence, dosage, or clinical advice permission is attached.

Provenance is published only after terminal acquisition persistence. A committed acquisition with a missing local proof can regenerate that proof by replaying immutable original source bytes, without repeating HTTP. Each later proof read rechecks the typed START intent, raw and stable SPL, discovery and packaging parents, strict decision, section slice, immutable files, PostgreSQL membership, and anchored envelope. The common provenance reader dispatches V2 section-chunk IDs to this source-specific verifier; existing DailyMed V1 and PubMed readers remain unchanged.

## Scope limits

The bridge is not yet wired into production composition. It depends on an immutable native discovery-query resolver and a finite, explicitly provided transport factory. Only synthetic fixtures and MockTransport have been exercised. Valid current-label evidence is not a clinical conclusion, and source unavailability is never converted into a no-result claim.
