# ADR-013: M1B CADEC asset and standalone domain contracts

- Status: Independent Review 001 closure `PASS`;
  `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`
- Approved by: Boqi Niu, Project Owner
- Approval date: 2026-08-13
- Work item: `M1B-CADEC-001`
- Baseline: `46c799368e9cd1ed3f2a2c956931d921999044e1`

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
emergency-guidance, or individualized-medical-advice claims. CADEC-002 is
separately Owner-gated.

## Validation status

Independent Review 001 initially returned `FAIL` with `P0 0 / P1 5 / P2 0`.
Remediation cycle 3 of 3 closed all five original findings and the later one-P1
residual. Terminal Review 001 closure is `PASS` with `P0 0 / P1 0 / P2 0`.
Terminal evidence audit and Git lifecycle remain pending; no terminal PASS or
commit is claimed.

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
surface. The CADEC-002 candidate is `PENDING_INDEPENDENT_REVIEW`; terminal
audit, commit, completion, and integration are not claimed.
