# ADR-042: CADEC metadata-only runtime material

Decision date: 2026-09-18. Authority: Owner requested completion of the local V1
and delegated remaining engineering choices. Root selected this bounded bridge
to preserve the existing approved CADEC asset and auxiliary-only boundaries.

Local BM25 search continues to verify the exact approved archive and manifest.
Its text remains transient. Runtime collection captures an immutable metadata
receipt binding run, scope, task, attempt, original operation observations,
document references and the actual local retrieval timestamp. Canonical material
is derived only from verified document metadata, with empty claim/inference
permissions. Neither generation nor semantic evaluation receives raw CADEC posts.

The wrapper replays the original terminal collection against the same assets,
then verifies the exact canonical reference projection. Restart reuses the first
receipt and timestamp. A per-reference index supports report provenance readback;
it never replaces receipt or asset verification. No new database schema or
dependency is added. Historical loader contracts and frozen exclusions remain
unchanged; malformed corpus records are not repaired or reinterpreted.

Both approved local files must exist and pass original hash admission. Missing
files result in a visible `skipped_by_policy` plan row with
`local_cadec_asset_unavailable`, no task and no fabricated source outcome.
The historical download folder was absent at initial inspection; the lookup
record is under `.local/evidence/V1-QWEN-DELIVERY-20260918/CADEC-ASSET-LOOKUP.md`.
ADR-043 subsequently restores the exact archive and admits a distinct, reviewed
recovery manifest. The original manifest identity is not assigned to regenerated
bytes. Synthetic bridge tests and real recovered-asset validation are reported
separately in the delivery evidence.
