# ADR-037: Verified local PubMed material selections

Status: implementation capability; runtime wiring and whole-worktree acceptance remain separate.

## Decision

Each persisted PubMed fetch has one deterministic material selection. The pure selector chooses a bounded exact abstract span when the publication status and local catalog permit it. It otherwise records a machine-readable exclusion. Every selection also carries one real `source_reference` tied to the fetched publication: for included material it is the claimable evidence itself; for an exclusion it is exact title metadata with no claim or inference permissions and no numerical facts. Exclusions therefore remain visible as source records without becoming citations or evidence for a formal claim.

`SnapshotPubMedMaterialStore.materialize` accepts the run, scope, local catalog, publication, and persisted publication binding. It replays the source snapshot, manifest, raw EFetch response, normalized publication, PostgreSQL membership, and lineage before deriving the selection. It writes a canonical immutable journal entry keyed by run, scope, publication version, and snapshot, anchors the `source_reference` using the existing PubMed evidence-provenance envelope and PostgreSQL insert-or-verify operation, then requires exact readback. `load_verified_selection` repeats source replay and selector derivation and compares the journal hash and provenance anchor. The journal never serves a self-asserted `EvidenceInput` as trusted material.

The record and reader are bounded: one fetch response, one publication membership, exact content-addressed parent paths and hashes, a 5 MiB parent cap, and a 2048-byte material journal. A missing, changed, cross-run, cross-snapshot, or mixed-source parent fails closed. The existing provenance and database schemas remain unchanged. No PubMed or other medical-source API request occurs during materialization or replay.

## Consequences

The typed application port exposes `materialize(...) -> PubMedMaterialSelection` and `load_verified_selection(...) -> PubMedMaterialSelection | None`. `None` means the requested selection was never published; a caller expecting a fetched publication must treat that as incomplete. The local capability must present every fetched publication's verified `source_reference` in the terminal source topology, while only claimable included evidence enters generation. This decision does not authorize clinical conclusions, source-coverage upgrades, or a semantic-provider release.
