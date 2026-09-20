# ADR-031: Carry the named local catalog through PubMed persistence

Status: implementation candidate under the Owner's delegated V1 completion decision.

The local research form uses `m3.local-research-input.v1` and locally derived
input IDs. The old PubMed execution contracts accepted only `m1a-concepts-v1`.
Relabeling new inputs with the historical catalog version would make their
provenance false.

Domain catalog identities therefore admit exactly two version/hash pairs:

- `m1a-concepts-v1` with
  `sha256:eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e`;
- `m3.local-research-input.v1` with
  `sha256:60ad5de184b4ab9972ca6179e4df8fd0f56d8e6741852f48331b465772b0e4ba`.

Resolved catalog inputs, run registration inputs, report construction, journal
version fields and the PostgreSQL run constraint carry this distinction.
Mixed pairs and unknown identities fail. The local adapter admits only the
scope accepted by the local public-term safety policy and preserves its IDs
and supplied ASCII letter case. It performs no source access or ontology
mapping. The old catalog bytes and original migration remain unchanged.

The legacy `/v1/research/pubmed` API retains its original request and response
catalog restriction. Its response adapter specializes the domain report to
the historical version; the exact existing OpenAPI compatibility test remains
unchanged. The broader domain contract is for internal local-workflow use.

Migration `m3localcatalog001` follows `m3semanticcache001` and changes only
`ck_research_run_static`. It permits the exact two pairs. A downgrade with
local-catalog rows fails the historical constraint rather than deleting or
relabeling those rows. Deployment must handle that condition explicitly.

Positive synthetic fixtures now use the admitted historical catalog hash
instead of arbitrary placeholder hashes. Tests preserve the historical API
schema and exercise both real PostgreSQL CHECK branches and mixed-pair
rejection. This node adds no dependency and authorizes no source request.

Source-native DailyMed/FAERS mappings, production execution bridges, canonical
evidence material and complete application composition remain separate nodes.
