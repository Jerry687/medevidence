# ADR-030: Generation V2 canonical claim and citation contract

Decision date: 2026-09-15. Authority: Owner delegated remaining V1 engineering
decisions and approved the bounded Generation V2 contract node.

Preserve the historical Generation V1 and DeepSeek V1 prompt, schema,
configuration and receipt identities. Add a distinct V2 candidate contract for
runtime synthesis. The new contract continues to consume the existing bounded,
source-aware `GenerationInput`; it does not reinterpret retrieved content as
instructions or grant the model validation, review or export authority.

Every V2 candidate claim selects exactly one representation:

- a `QualitativeCode` whose source, class, inference use and statement match the
  existing canonical report-validation form exactly; or
- a complete six-field `NumericalContextInput` whose statement is the exact
  canonical numerical rendering.

FAERS numerical candidates remain bounded spontaneous-report counts with the
existing mandatory limitation and cannot express incidence, risk, causality or
product ranking. CADEC numerical candidates remain forbidden. Source-specific
claim and inference permissions equal the existing canonical validation policy.
The mapper never overwrites or normalizes a generated statement into a different
claim.

Every citation identifies both a supplied canonical `EvidenceInput` and one of
its exact locators. Application code reconstructs and verifies the complete
trusted evidence tuple, including source, record, version, snapshot, content
hash, excerpt, permissions and numerical facts, before admitting the candidate.
Numeric claims require a matching authoritative fact at a supporting locator.

The pure mapper derives canonical claim and citation identities, preserves the
candidate statement and numerical context, and emits unlabelled Stage-2 plan
entries. It accepts only an exact zero-or-one comparison/conflict pair already
present in both the generation input and canonical comparison registry. Multiple
pairs or omitted membership remain unavailable until a canonical per-claim
membership contract exists. A claim selecting the single pair may cite only
evidence included in that exact generation conflict graph. The mapper does not
fabricate a semantic result, human resolution or validation receipt.

This node adds no provider transport, source access, persistence, workflow side
effect, dependency or live run. A later DeepSeek V2 gateway/service must use the
new prompt/schema/configuration identities and a separate V2 receipt family; it
must not label V2 output with historical V1 provenance. Production synthesis
also remains blocked until terminal evidence references can reload exact
canonical `EvidenceInput` material.

The frozen initial V2 identities are prompt
`sha256:b696cccb72580fa995e69043935c02bdeacec416156123067ecc7ec92ee185fc`,
response schema
`sha256:287cdb777c8935370f84ae28cb34872bfda4ca77ea2c4dfaa1f270df1a3a1d1f`,
and pure configuration
`sha256:95c8d447b9abc83f97c1a950eab19270f8c83cf077a6c8792af2aaa29e2526ac`.
