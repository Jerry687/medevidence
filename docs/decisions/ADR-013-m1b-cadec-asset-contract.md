# ADR-013: M1B CADEC asset and standalone domain contracts

- Status: CADEC-001 and CADEC-002 integrated; CADEC-003 Option E amendment
  `ADDITIONAL_MECHANICAL_CORRECTION_PENDING_FRESH_REVIEW`
- Approved by: Boqi Niu, Project Owner
- Approval date: 2026-08-13
- Work items: `M1B-CADEC-001`, `M1B-CADEC-002`, `M1B-CADEC-003`
- Original CADEC-001 baseline: `46c799368e9cd1ed3f2a2c956931d921999044e1`
- Integrated CADEC-002 baseline: `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`

## Decision

CADEC-001 freezes external asset identities and additive source-neutral domain
contracts without copying archive/corpus bytes into Git. The archive SHA-256 is
`4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a`.
The manifest is 1,699,979 bytes, SHA-256
`1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa`;
the freeze audit is 6,354 bytes, SHA-256
`18928091762df33fc1fc39e9d45a55c86637a0c55c1d5cc987bc12e55a36f753`.

Of 1,250 canonical documents, 1,248 are admitted. Exact sorted exclusions are
`DICLOFENAC-SODIUM.7` and `LIPITOR.221`. Five malformed rows reject and are
never repaired, normalized, or reinterpreted. The separate 91 visible
reference-binding limitations are 2 original-term, 44 MedDRA, and 45 SCT;
they are not malformed or rejected/normalized/repaired/reinterpreted here.

All text is UTF-8 except exactly `cadec/sct/LIPITOR.253.ann`, CP1252 only at
SHA-256 `0deeb944656f03381dd8adb2914570f4759e70cd43c8a7c81a5c56cfefb0da96`.
`MEDEVIDENCE_CADEC_SPLIT_V1` is train 992
(`e533c904637a86b447ce4cee5973b4041ff8de1679fcb073e78a0525835c8329`),
development 119
(`dd219af2c42b717fb1df7d24b04de9bb031c099d4deb513091c6d49d4b2b799f`),
and test 137
(`6bf824a4fe7a708a836cf08b007734622bb02c2fecf0d1441febfb0103a3e26a`).

Only provider gold is admitted; no predicted artifact is admitted. Vocabulary
is closed to exactly the `MedDRA` and `SNOMED CT` high-level layer references.
Both have version `not stated in retained provider/archive metadata` and legal
status `reference-only`; identifiers, terms, hierarchy, and payload emission
are false. The exact licence is `CSIRO Data Licence`, ID `1061`: attribution is
required, use is non-commercial internal research only, no intellectual-
property assertion over the data is allowed, provider accuracy or endorsement
must not be implied, and raw archive/corpus redistribution is prohibited.
REDIST is raw external/no redistribution/no corpus-derived real fixtures.

Child ownership uses Option A: `source + corpus_id + corpus_version + split +
artifact identity`, additionally closed to the exact manifest, terminal audit,
and split-membership identities. Because no provider release label is retained,
the namespaced archive hash is the corpus ID and the namespaced manifest hash
is the corpus version; this does not invent a provider version. Documents admit
only canonical safe `cadec/text/<document_id>.txt` labels, reject traversal and
the exact exclusions, and bind the approved external manifest. Provider-gold
annotations bind an exact layer member path and parent document artifact;
locators bind the exact annotation artifact. Contracts are frozen,
extra-forbid, instance-revalidated, NFC-bound, identity-derived, and use bounded
half-open spans.

## Compatibility and safety

The existing `cadec_query_requests=tuple[()]` and M1B section union remain
unchanged, so CADEC execution and generated API/OpenAPI are not enabled. No
loader, ingestion, persistence, migration, tool, composition, index, search,
training, dependency, network, M2, or real fixture is included. CADEC remains
auxiliary-only and cannot support clinical, causal, incidence, regulatory,
product-risk/comparison, diagnosis, treatment, ranking, advice, dosage,
emergency-guidance, or individualized-medical-advice claims. At the CADEC-001
contract-freeze point, CADEC-002 remained separately Owner-gated; its later
approval and integration are recorded in the amendment below.

## Validation status

Independent Review 001 initially returned `FAIL` with `P0 0 / P1 5 / P2 0`.
Remediation cycle 3 of 3 closed all five original findings and the later one-P1
residual. Terminal Review 001 closure is `PASS` with `P0 0 / P1 0 / P2 0`.
The later terminal evidence audit passed at `P0 0 / P1 0 / P2 0`; feature
commit `51bbe29a94aa3a16af5d55be01b06f6aa331ab44` was integrated by merge
`af111b8efce0d2a47df4c3ba20f213a812ca12da` through PR #19.

## M1B-CADEC-002 narrow correction

Owner-authorized CADEC-002 inspection established that two approved document
text members are exactly zero bytes and that each corresponding original,
MedDRA, and SCT annotation member is also zero bytes with zero rows. The
existing `m1b.cadec.document.v1` contract therefore permits `text_length=0`;
negative lengths still reject, positive behavior is unchanged, and identity,
release, split, and provenance validation remain content-derived and exact.

The loader must fail closed if any zero-length document has a row in any of
its three annotation layers. This correction changes no schema version,
approved subset, split, evidence meaning, persistence, tool, API, or reporting
surface. Immutable initial review remains `FAIL` at `P0 0 / P1 2 / P2 0`;
one remediation batch closed both findings, independent closure and terminal
audit each passed at `0/0/0`, and feature commit
`03fffef7ad8f68a9ca36c4961a5264b2e0b295ff` was integrated by merge
`a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a` through PR #20.

## M1B-CADEC-003 integrated evidence and Option E amendment

The exact integration record is:

- CADEC-001: feature `51bbe29a94aa3a16af5d55be01b06f6aa331ab44`,
  merge `af111b8efce0d2a47df4c3ba20f213a812ca12da`, PR #19, review closure
  `PASS` at `P0 0 / P1 0 / P2 0` after immutable failure history, terminal
  audit `PASS` at `0/0/0`, audited aggregate
  `35a4d2349410c16209197c24e1900ca28067de993276d2c865be082c61548482`, PR
  quality run `31726952106` with `windows-quality` and `compose-config` both
  `SUCCESS`, and merged-main quality run `31727139728` `SUCCESS`;
- CADEC-002: feature `03fffef7ad8f68a9ca36c4961a5264b2e0b295ff`,
  merge `a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a`, PR #20, immutable initial
  review `FAIL` at `P0 0 / P1 2 / P2 0`, one remediation batch, independent
  closure `PASS` at `0/0/0`, terminal audit `PASS` at `0/0/0`, audited
  aggregate
  `d307456bcfb4b5cf20392d93e922fb75d0d5684d9e5064c8a811ac960f973d9a`, PR
  run `31748194823` with both checks `SUCCESS`, and merged-main run
  `31748381436` with both checks `SUCCESS`.

Owner-frozen Option E makes the CADEC-002 exact external loader/parser the
final executable M1B CADEC surface. M1B ends at exact approved external archive
and manifest input, one-open immutable-byte verification, safe bounded
loader/parser behavior, approved metadata-only documents, provider-gold
annotations, exact locators, and Option-A provenance with visible limitations.
The output is not directly retrieval-consumable.

The exact `cadec_query_requests` value remains `tuple[()]` and
`M1BSourceSection` remains unchanged. Exactly one visible CADEC M1B source plan
entry has `planning_status=skipped_by_policy`,
`reason_code=source_execution_not_authorized`, and reason `CADEC remains
visible in the M1B source plan, but source execution is not authorized under
Option E.` Visibility is distinct from execution and creates no executable
request, research-request connector invocation, `SourceOutcome`, report
section, or API/OpenAPI execution. M1B therefore prohibits CADEC structured
retrieval or search tools, persistence, migration, database ingestion,
indexing, chunking, training, and retrieval evaluation.

Future M2 owns `search_local_adr_corpus` and a text-bearing materializer,
subject to `ME-000C`. It must reread the exact approved external archive,
verify the same immutable identity, preserve document, annotation, locator,
split, and Option-A lineage, and create exact text-bearing chunks with bounded
offsets and content hashes. Raw text stays outside Git. This amendment neither
implements nor authorizes M2, and
`READY_FOR_M2-CADEC-RETRIEVAL-CONSUMPTION` is explicitly prohibited.

Immutable Review001 remains `FAIL` at `P0 0 / P1 1 / P2 2`. Remediation batch
1/1 was followed by closure-review `FAIL` at `P0 0 / P1 1 / P2 1` for no-plan
overreach and Review001 transcription fidelity. The Owner-authorized additional
mechanical correction is
`ADDITIONAL_MECHANICAL_CORRECTION_PENDING_FRESH_REVIEW`. It claims no
fresh-review PASS, terminal audit, commit, completion, or achieved post-
terminal marker. The exact post-terminal targets are
`M1B-CADEC-003_COMPLETE`, `M1B-CADEC_VERTICAL_SLICE_COMPLETE`, and
`READY_FOR_M2-CADEC-RETRIEVAL-PLANNING`.
