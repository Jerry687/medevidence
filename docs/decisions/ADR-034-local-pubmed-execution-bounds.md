# ADR-034: Preserve PubMed execution limits within a local research budget

The delegated V1 completion work needs one scope for several sources. Its
budget may exceed PubMed's frozen 512-character, one-page, 100-record, 5-MiB,
30-second execution profile. Replacing the actual source bounds with the
larger scope would misdescribe execution and break trustworthy replay.

The default `PubMedBoundsPolicy.EXACT_SCOPE` retains the M1A request validators
and exact-scope behavior. The explicitly selected `LOCAL_PUBLIC_V1` policy
admits named local search, fetch and collection request contracts. Those
contracts preserve the caller's scope identity and require the budget to
contain the fixed profile; they do not relax or rewrite legacy requests.
The service also requires the exact admitted local catalog identity, enforces
the effective query-length limit before execution, and checks every returned
search/fetch outcome against the fixed profile. Composite outcomes retain
those actual limits and reject mixed child profiles.

The composition seam accepts a closed enum and rejects a local PubMed policy
when PubMed is not requested. Source capability planning, collection and
terminal replay reconstruct only named request types. Planning and replay
cannot trigger source calls. Existing API request schemas remain unchanged.

This node enables source collection, not full report acceptance. Runtime
validation still needs its separately versioned per-source policy and an
accepted semantic model profile. No model acceptance, live-source permission,
or human report-export approval is implied by this change.
