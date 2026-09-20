# ADR-040: Local source runtime and verified material authority

The local V1 workflow owns a durable research job before collecting evidence.
It does not own a completed M1A research report at that point. PubMed abstract
material therefore accepts a separate, explicitly injected local job authority.
The reader reloads the canonical job row, its exact scope payload and hash,
the canonical search-progress receipt and its persisted search snapshot, and
the persisted PubMed fetch acquisition before replaying the original response,
normalized publication, snapshot membership, material selection and provenance.
The fetched PMID must belong to the exact completed search membership.
The fetch request identity is `pubmed:<pmid>`; the search query has a separate
identity. The original M1A completed-run authority remains unchanged when no
local job reader is supplied. No provisional M1A report or run is fabricated.

For local PubMed collection, every fetched publication gets one source reference
from the verified material store. Included abstract spans have claimable
permissions. Excluded publications have an actual title metadata reference with
empty permissions. Terminal source references use those exact evidence IDs;
later registry construction must include both, while generation may use only
claimable material. Every load rechecks the saved material against source and
job authority.

The local DailyMed V2 capability reconstructs executed discovery, packaging,
decision and selected current SPL records from their durable slots. Failed
selected fetches retain their actual unavailable or partial outcome. The
source-neutral terminal task contains only exact completed operation results
and admitted current-label chunks. A per-label or task-wide chunk cap is a
typed permanent collection failure. It cannot become a complete terminal task
with zero material, and the persisted child retrieval outcomes are not relabeled.

FAERS uses its existing START-before-request durable bridge for each exact
task attempt. Source material is reconstructed from persisted execution and
verified original-source provenance. FAERS bucket counts retain descriptive
permissions only; they do not establish incidence, risk, or causality.

CADEC is selected only when both configured absolute archive and manifest
paths are present as local files. Without them, its plan row remains visible
as `skipped_by_policy` with reason `local_cadec_asset_unavailable`; no source
outcome is invented. A selected CADEC task runs the existing exact approved
local search and writes a bounded metadata-only receipt containing the
retrieval time and canonical auxiliary evidence mapping. The verified reader
rechecks the receipt, approved asset and source references before admitting
them to the full registry with empty claim/use permissions. The same reader
supplies the generic provenance verification used by report review and export.
Corpus text is
neither persisted in the receipt nor sent to generation. The original
standalone CADEC collector remains unchanged.
