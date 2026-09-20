# ADR-041: Local synthesis and final report material

The local workflow sends only the exact claimable subset of verified source
references to the existing DeepSeek Generation V2 service. The complete,
ordered source-reference inventory, including metadata-only records, remains
in the V4 validation registry. Generation receives terminal source outcomes
and their actual warning codes. No comparison or conflict artifact is invented.
The fixed Qwen semantic profile is selected by the V4 registry; generation
remains a separate provider operation.

Before generation, an immutable journal records the report, canonical
generation-input hash, trusted-evidence hash and prior report hash. A repeated
attempt with that identity fails closed, since a prior provider POST may have
completed without a checkpoint. The generation service saves and reloads its
raw response and receipt before a candidate can be mapped. Synthesis then
publishes the pre-semantic registry and exact report material under the report
content hash. An unknown attempt is unavailable; it is never resent as an
assumed failed request.

At review time, the material provider reloads the checkpoint-bound registry,
report material, source provenance, generation receipt and final validation
receipt. It reconstructs completed Stage-2 projections from the final receipt
and verifies the resulting report request and receipt with the existing
canonical binding gate. The immutable pre-semantic registry is not rewritten.
The report material codec preserves V3 child-acquisition task fields through
typed serialization. For V3/V4 PubMed child tasks, a durable locator may be
the exact `pubmed-material-locator` identity of the raw citation span. The raw
span remains in the evidence and citation. Other sources and legacy tasks keep
their original exact locator comparison.

With no claimable evidence, generation may return zero claims. Validation
requires no semantic provider call when there are no formal citations; the
source's failed or indeterminate coverage remains visible. Human approval is
still required before export.
