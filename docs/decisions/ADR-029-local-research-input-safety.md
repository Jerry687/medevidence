# ADR-029: Closed local research input and scope safety

Decision date: 2026-09-14. The additive V1 local research form accepts only the
public display terms Semaglutide and Tirzepatide for drugs, and Nausea,
Vomiting, and Diarrhoea for adverse reactions. Matching ignores letter case
only. The existing UI identity `input-drug:` or `input-reaction:` is recomputed
from the kind, a NUL separator, and the case-folded term. The submitted term,
concept ID, and scope identity remain unchanged. This is a literal local input
catalog, not a medical ontology, synonym resolver, brand matcher, or claim that
different source vocabularies are equivalent.

The older integrity-checked M1A catalog and its hash remain unchanged and have
separate concept IDs. An M1A concept ID does not silently substitute for a
local form ID. Unknown terms, other IDs, spacing variants, and foreign source
codes fail closed. The policy accepts the existing typed V1 source codes
PubMed, DailyMed, FAERS, and CADEC as scope choices, with the domain's finite
query/result caps, and optional inclusive dates from 1900-01-01 through the
injected current day. Accepting a source choice does not establish that its
connector or verified provenance is available for a given run.

The concrete policy implements `ScopeSafetyPort` without persistence or
network access. It reconstructs an exact `ResearchScope` and returns the same
scope identity. Suspected patient identifiers or case narratives are classified
`suspected_phi`; dose, diagnosis, treatment, or individualized-advice text is
classified `unresolved_medical_boundary`; other unsupported scope values are
`unsafe_scope`. The application rejects every blocked decision before job or
checkpoint persistence and returns only the fixed redacted rejection code.
This is a restrictive local intake policy, not certified de-identification or
clinical validation.

The type-safe `LocalResearchInputCatalog` exposes immutable term-to-concept
lookups and an exact version/hash for future source composition. A production
source factory must separately bind each selected source's own query terms,
license, availability, execution bounds, and verified provenance. No source
request or provider call is authorized by this decision.
