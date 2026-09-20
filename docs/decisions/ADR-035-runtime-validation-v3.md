# ADR-035: Closed runtime validation V3 bindings

Status: implementation capability only; runtime activation is disabled pending a separate accepted semantic-calibration certificate.

## Decision

The existing `ValidationRegistryInput`, `Stage1ReceiptV2`, and `ValidationReceiptV2` field shapes remain unchanged. A named `M3_VALIDATION_CONFIGURATION_V3` registry selects one immutable `M3_VALIDATION_POLICY_V3` code path. That path expects the final Attempt015 LOW Development-v3 provider version/hash and provider-neutral hash as one exact pair. It does not select a profile from provider output or caller-supplied arbitrary parameters. Before Stage-1 receipt persistence and any HTTP request, the workflow requires a typed runtime semantic port identity matching the fixed V3 profile. Result projection and receipt replay independently check the same pair.

V3 verifies each recorded source outcome against the fixed local execution profile and the authorized master budget. PubMed is `512 / 1 page / 100 records / 5 MiB / 30 s`; DailyMed and FAERS are `512 / 5 pages / 100 records / 5 MiB / 30 s`. CADEC is local and must exactly match the master budget. Source outcomes are never relabeled to the master budget. The source-bound table is shared with the local source-policy integration. V1 and V2 retain their original exact-bound behavior and byte-identical receipt/profile identities.

The V3 code path is a recognition and validation capability, not a release decision. Attempt015 completed all 36 provider cases but failed the frozen quality threshold: 32/36 agreement, with unsupported recall 8/12. No runtime factory may activate V3 from that result. An acceptance certificate is a separate required gate; this ADR does not create one.

## Verification and size budget

The central `report_validation.py` ceiling remains 1900 lines. The prior Stage-1/V2, dynamic-registry, and projection aggregate measured 3066 lines against 3100. V3 adds a separately counted closed provider/source policy module and source-bounds module. The bounded acceptance test now includes both new modules and uses a 3500-line ceiling; the implementation measured 3474 lines when that decision was made and 3494 after the pre-HTTP and resolution-profile guards. This is additional versioned policy code, not a relaxation of clinical, evidence, routing, quality, or runtime safety thresholds.

Validation must prove exact V1/V2 receipt hashes and replay, V3 Stage-1/registry/final receipt identities, mixed-profile rejection, source-profile rejection without outcome rewriting, provider identity rejection before Stage-1/HTTP, and cache no-resend semantics before any later activation. No medical-source or holdout calls are part of this implementation node.
