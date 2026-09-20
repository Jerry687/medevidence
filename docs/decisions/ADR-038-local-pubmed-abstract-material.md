# ADR-038: Source-bound local PubMed abstract material

The delegated V1 work needs canonical current-run evidence identities rather
than treating a publication-version ID as an evidence span. The first material
producer selects at most one attributed abstract extract per persisted PubMed
publication. This is a deterministic lexical extract; M2 retrieval remains a
separate integration requirement.

`m3.pubmed.abstract-span.v1` reuses the existing smallest drug/reaction term
span and domain publication-status/use rules. ASCII case translation preserves
all original Unicode code-point offsets; emitted text is always copied from
the unchanged canonical abstract. Its locator contains the policy version,
publication version, full abstract hash and exact start/end offsets. Evidence
identity additionally binds the run, source snapshot, full publication content
hash, excerpt and permitted uses. No numerical fact is inferred from prose.

Retracted publications and corrected content without an established current
version do not produce material. Missing abstracts, missing terms, quotes over
4096 characters and selection-work overflow produce an explicit exclusion and
visible limitation; the retrieved publication count remains unchanged. To
bound the existing pairwise selector, the original abstract may contain at most
262144 code points and at most 512 total configured-term occurrences. Overflow
is excluded, never silently shortened.

Current or verified current corrected content may supply descriptive and
methodological material. Unknown status or an expression of concern is limited
to methodological context. Clinical, causal, incidence and risk permissions
are absent. Existing domain citation and attributed-extract construction run
again after selection.

Every retrieved publication still has one `source_reference`, preserving the
existing source-count/terminal-reference invariant. For an included extract,
this equals the claimable evidence. An excluded record instead has a distinct
`m3.pubmed.record-metadata.v1` reference to its actual normalized title, exact
publication version and source snapshot, with empty claim/use permissions and
no numerical facts. Its claimable `evidence` remains absent. This represents
real retrieved metadata, never a substitute abstract. Metadata references must
stay in the complete validation registry and must never enter model-generation
evidence. The runtime mapper therefore needs a separate registry-only reference
lane and must prove that generation inputs are the claimable subset. Formal
citations to zero-permission metadata must fail Stage-1 validation.

The pure selection result is a candidate, not proof of persistence or raw-source
verification. A separate material store must authenticate original response,
normalized publication, snapshot membership and current-run ownership, persist
the exact selection and rederive it on read. The local source capability must
bind that verified material into its terminal references; legacy M1A references
remain unchanged. These integration gates are not completed by this producer.
