# ADR-023: M3-008B Stage-2 semantic contract V2

## Status

Owner accepted the semantic-contract decision for
`M3-008B-SUCCESSOR-005-APPLICATION-DERIVED-HUMAN-REVIEW`. The DeepSeek
calibration path is now closed as
`M3-008B-DEEPSEEK-CALIBRATION_CLOSED_EXTERNAL_EXECUTION_NOT_ACCEPTED`.
Attempt009 and Attempt010 are immutable external-execution non-acceptance evidence
with implementation review `P0 0 / P1 0 / P2 0`, not implementation failures.
No accepted 36-case calibration metrics or artifact exists. Attempt011 is not
authorized, M3-009 must not start, and Holdout-20 remains sealed.

## Context

Attempts001-006 and V1 Development prompt/rubric versions 1 through 3 are
immutable. Attempt006 completed five successful cases. Its case006 provider
output was valid, but the V1 application-policy binding failed as
`human_review_binding_invalid`. The governed historical classification is
`V1_PROVIDER_OUTPUT_VALID_BUT_APPLICATION_POLICY_BINDING_FAILED`, not a model
semantic failure. Attempt006 is incomplete calibration evidence and does not
establish semantic acceptance.

The Owner accepts Successor-004 provider transport, credential handling,
durable attempt ledger, framing/media authority, V1/V2 evidence separation, and
terminal evidence architecture for successor reuse. The exact Successor-004
25-path manifest
`sha256:3764ce9a44294a0d2df1c7d9864747c1869fc4f6a88aded89d0567f387b19faa`
is mechanically reconstructed at baseline
`26c67108bf5b8de8b05bddf7e7ec5bac61261425` as implementation input. This does
not mean Successor-004 was integrated or calibration-passed.

## Decision

The provider-neutral contract is `M3_STAGE2_SEMANTIC_RESULT_V2`. Its provider
candidate contains only:

- one semantic state: `supported`, `uncertain`, or `unsupported`;
- one to eight bounded canonical rationale codes; and
- one bounded explanation.

The exact structured output also carries its contract schema version. It has no
`human_review_required` field. Provider-authored workflow-review decisions are
unknown fields and fail closed; they are never accepted, persisted, or used as
application authority. Rationale codes explain semantic classification and do
not control routing.

The semantic contract declares one allowed-code set, one required-any-code set,
and one forbidden-code set for each of the three semantic states. This mapping
is part of the canonical contract bytes and identity. A candidate whose codes
are not canonical or violate its state's mapping fails before any application
routing decision.

The durable semantic family version is exactly
`m3.stage2-semantic-result.contract.v2`. This version and its canonical content
hash are independent from the response-schema, prompt, rubric, and wire
identities. Every V2 result, validation receipt, and calibration record binds
that semantic-family authority plus exact evaluator method
`deepseek.responses.independent_semantic_evaluation`, provider configuration
version `m3.semantic-evaluation.v2.deepseek-responses.v2`, and the exact
DeepSeek profile hash. An arbitrary evaluator, method, or provider-profile
substitution fails closed.

After canonical Stage-2 reconstruction, the application derives one versioned,
canonical, deterministic routing disposition:

1. `unsupported` rejects the formal citation and cannot enter the formal
   report;
2. `uncertain` requires recorded human adjudication or removal;
3. ordinary `supported` with a `supports` relationship and no governed
   conflict or safety escalation requires no human review;
4. `supported` with a `contradicts` relationship requires human review; and
5. an applicable non-consistent comparability/conflict outcome or a
   policy-designated safety-sensitive inference requires human review.

These requirements are encoded once as an ordered declarative six-rule decision
table. The table drives canonical policy bytes/hash, runtime rule selection,
and the complete deterministic routing matrix. No separate executable branch
list or handwritten expected-rule inventory is authoritative.

Every report-level result also binds its exact comparability participation.
The only valid shapes are an exactly empty registry, or one exact comparison
and its matching conflict with exact identifiers, artifact hashes, and outcome.
Routing considers only that bound participant, not unrelated conflicts present
elsewhere in the report. Foreign, stale, missing, partial, or swapped
comparison/conflict bindings fail closed through result, receipt, resolution,
and replay reconstruction.

Stage-1 failure is terminal before any provider execution and can never become
a Stage-2 or human-review success. The routing policy version/hash and derived
disposition are bound into semantic result, validation receipt, and calibration
provenance. Routing correctness is evaluated by an exhaustive deterministic
matrix independently from provider semantic agreement.

## Frozen candidate identities

The current implementation-candidate identities are:

| Authority | SHA-256 identity |
|---|---|
| Semantic contract `m3.stage2-semantic-result.contract.v2` | `sha256:9b97996233f6dc80091f196209b18c27b23e0eeb5c82c6e7e8c0f954df69a3bb` |
| V2 prompt | `sha256:df32692d5a8afb7df0b7339403889b92a51472b52c3fae9009030d0ac0336a0b` |
| V2 rubric | `sha256:48e9a1fc96ae0a5460bbce36164ba297c621f26f509e19a4d3a618342335a4b3` |
| V2 response schema | `sha256:8275ff6de6cbed0fc2412d2a191217f1d486cb4359ee28011aacd4ae3c0cbdf0` |
| V2 wire contract | `sha256:20e4cc7427c7e4d082ea47ba48b706f51f8a41e1b6873415e18300e5e3ed6593` |
| Provider-neutral configuration | `sha256:fd3e9bda090c92b0c83244d521cb3163f4c3e43bda74b1132efaad7ffbb7f491` |
| Review-routing policy | `sha256:cfeaf63c84f4b2e207519b45a2181d40f97d98479391dd1b66af12d9be790dd1` |
| Review-routing matrix | `sha256:4fdca5d8b856452f89fb07748f83521b3dee530e42613bddc859d29bd8160a77` |
| Attempt007 DeepSeek provider v1 profile | `sha256:2798cf926eb197b746fd3c321d50047c28dea5061d2f4613adb5c81b30c80b35` |
| Attempt008/009/010 historical DeepSeek provider v2 profile | `sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9` |

These are candidate identities subject to final exact-byte rebind. They do not
claim pre-network PASS, provider execution, calibration acceptance, integration,
or release. The final implementation manifest and code revision must be bound
after the candidate is frozen; no V1 identity may be overwritten.

## Calibration authority

The same ordered 36-case Project-Owner packet remains frozen at
`sha256:758aaccd90e2e545af2215640426a20b2c75c038d40f0d1d2b2e0cc716aaf806`.
Its labels are semantic-state ground truth only and must not be treated as
labels for human review. Acceptance remains:

- unsupported to supported equals zero;
- uncertain to supported equals zero;
- overall exact semantic agreement is at least 0.85;
- each human semantic state has at least eight cases;
- each human-state recall is at least 0.75; and
- all frozen categories are exercised.

The V2 family permits at most three globally applicable Development
prompt/rubric versions. Version 1 is current. A passing version is frozen
immediately. Human labels, case order, case inclusion, and category inventory
cannot be changed or tuned. Review-routing correctness is reported separately
and cannot raise or lower semantic agreement.

Attempt007 is immutable failed evidence: cases1-4 succeeded, and case5 closed
`response_invalid` after valid HTTP/1.1 chunked headers but an incomplete body
with no raw artifact. Attempts008 and 009 are also immutable failed evidence:
cases1-4 succeeded with exact raw evidence; case5 attempt1 closed
`transport_unavailable`, attempt2 closed `deadline_exceeded` under the same
absolute deadline, neither retained raw bytes, and no attempt3 occurred. These
attempts produced no quality result. Attempt009 is bound to manifest
`sha256:99af376d7cbacd0eec72c4520337f4ce73a4cfaa36455a6b99a18fda1656fa13`,
run `sha256:4e1d5b2cd481ae62752d1eddda33bd8acbc43679f50bada019d414c4aef6d0e6`,
projection
`sha256:c02f71b8e928ea4076af9997c4c07ebd4cb27e7c290f64ed44dadeb3c91a1b46`,
and status
`sha256:3d883dfd3dd8af63abf11b05f516477e1091179ab17b57085a12ddd18bee4b22`.
Its terminal result `FAIL — P0 0 / P1 0 / P2 0` is an exact external provider-
availability/deadline outcome, not a code or semantic defect. Attempt010 is
also immutable: manifest
`sha256:2de9fd9eeb293bd19ae860f6a4f71dbf4f9b308bd7baa0974e7426d9021a614a`,
run `sha256:e85887cb2f409bc03bf1b6964b073efe78415e83bd754b9aaa4e3795a45aaa63`,
projection
`sha256:ecc271a70ab6c482b32576432e690afec2da4f62dd09f46710076065db616694`,
and status
`sha256:c65e2dc63e6d14cc7a10631d45b9c9af21468d2d941ee3b2af18a448b2e7ec6f`.
It repeated the same frozen-policy outcome: cases1-4 succeeded, then case5
closed `transport_unavailable` and `deadline_exceeded` after incomplete HTTP 200
responses under the shared deadline. No quality result exists. The
DeepSeek path is closed; partial continuation and Attempt011 are prohibited.

## Provider-replacement readiness package

1. **Stable provider-neutral authority.** The exact contract remains
   `M3_STAGE2_SEMANTIC_RESULT_V2`, version
   `m3.stage2-semantic-result.contract.v2`, identity
   `sha256:9b97996233f6dc80091f196209b18c27b23e0eeb5c82c6e7e8c0f954df69a3bb`.
   It returns only semantic state, one to eight canonical rationale codes, and
   a bounded explanation. The application, not the provider, owns the six-rule
   deterministic review-routing policy at
   `sha256:cfeaf63c84f4b2e207519b45a2181d40f97d98479391dd1b66af12d9be790dd1`.
2. **Frozen human truth.** The ordered 36-case Project-Owner resolution remains
   unchanged at
   `sha256:758aaccd90e2e545af2215640426a20b2c75c038d40f0d1d2b2e0cc716aaf806`,
   with 12 cases in each semantic state. Labels, order, categories, and
   acceptance thresholds cannot be tuned or relabeled.
3. **Transport, evidence, and security requirements.** A replacement must keep
   bounded credential-free request bytes, in-memory credential screening before
   hashing or persistence, committed START-before-send, insert-only terminal/
   recovery accounting, one governed shared deadline, bounded retries, exact
   HTTP framing/media/body admission, strict closed provider-envelope and V2
   output validation, tool prohibition, raw/projection/status binding,
   same-run topology, immutable external artifacts, and exact-byte replay.
   Public research data is the only allowed input; medical-source traffic,
   PHI, private records, credentials, and Holdout-20 remain prohibited.
4. **Minimum provider-specific replacement surface.** The discovered minimum
   repository surface is
   `src/medevidence/infrastructure/deepseek_responses_transport.py`,
   `src/medevidence/infrastructure/deepseek_semantic_evaluator.py`, the provider
   constants and profile in `src/medevidence/tools/semantic_evaluation.py`,
   `evaluation/stage2_deepseek_calibration.py` and
   `evaluation/run_stage2_deepseek_calibration.py`, the hard-coded provider
   ledger constraints and projections in
   `src/medevidence/persistence/models.py` and
   `src/medevidence/persistence/repositories.py` plus any required migration,
   and the exact V2 provenance binding in
   `src/medevidence/tools/report_validation.py`, together with corresponding
   tests and historical verifier. A replacement must newly bind its provider
   identity, endpoint/model/reasoning/tool configuration, credential variable,
   request/response envelopes, transport/profile, evaluator method/version,
   configuration hash, ledger projections, and receipt provenance. Durable
   ledger semantics remain unchanged, but provider-specific identities and
   constraints require a separate exact rebind. This inventory neither proves
   compatibility nor authorizes any change.
5. **Repository-present candidates.** No provider/model currently in the
   repository is directly compatible with the V2 contract. OpenAI Responses
   with `gpt-5.6-terra` is the sole repository-present alternate, but its code
   is V1 and includes provider-authored review behavior. It is only a possible
   separately authorized starting point, not a compatible active provider or
   execution authority.
6. **Owner decisions still required.** Before any implementation or call, the
   Owner must select the replacement provider, endpoint, model, reasoning and
   structured-output profile; approve its credential variable and data-policy
   provenance; decide the persistence constraint and migration strategy;
   decide whether V2 receipt provenance may name the replacement provider;
   authorize the bounded provider-specific adaptation paths and remediation
   budget; and separately authorize the exact live Development calibration
   attempt and Git lifecycle. Until then, no provider execution, compatibility
   claim, provider-specific rebind, or persistence/provenance change is
   permitted.

## Consequences and exclusions

Provider semantics and application workflow policy remain separate durable
authorities. This change adds no dependency, public API/OpenAPI redesign,
persistence migration, source/evidence semantic change, retrieval/router/qrels/
corpus/metric change, medical-source traffic, model confidence, majority vote,
or Holdout authority. The retained DeepSeek code and evidence are historical;
their presence is not execution authority. Holdout-20 remains sealed.
