# ADR-020: Independent Stage-2 semantic-support evaluator

- Status: Accepted; Review001 through Review005 immutable
  `FAIL — P0 0 / P1 4 / P2 0`, `FAIL — P0 0 / P1 5 / P2 1`,
  `FAIL — P0 0 / P1 4 / P2 0`, `FAIL — P0 0 / P1 1 / P2 0`, and
  `FAIL — P0 0 / P1 1 / P2 0`; Round 5 closure candidate awaiting focused
  integration and fresh review; M3-008B calibration blocked on external inputs
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-30
- Approval reference: Owner Decisions L and M for
  `M3-008-INDEPENDENT-STAGE2-EVALUATOR`
- Revision: 1
- Independent review reference: M3-008A Review005
- Independent review role: Validation only; not an approving authority
- Work item: `M3-008A-INDEPENDENT-STAGE2-EVALUATOR-FRAMEWORK`
- Baseline: `fd9bd9cae3cea5e69ded92134d386487c736469d`

## Context

The M3 runtime has an application-owned deterministic Stage-1 report-validation
authority and a separately bounded M3-007 candidate-generation gateway. The
existing validation contract expects a versioned semantic-support result for
each formal citation, but no independently prompted provider gateway yet
produces that advisory Stage-2 result.

The generator must not evaluate its own work from its reasoning or receive an
answer label that converts evaluation into label reproduction. Retrieval rank
and score are selection metadata, not evidence truth. Stage 2 also cannot
replace deterministic Stage 1, source semantics, or governed human review.

Owner Decisions L and M authorize the isolated evaluator framework and freeze
its provider/model boundary. They do not provide the approved human semantic
packet or provider credential required for calibration.

## Decision

### Exact provider and request policy

M3-008A uses `POST https://api.openai.com/v1/responses` through the existing
HTTPX dependency. It adds no OpenAI SDK or other dependency. The exact model is
`gpt-5.6-terra`, with reasoning effort `medium`.

Every request sets `store=false` and `background=false`, provides no built-in
or application tool, and does not opt into extended prompt-cache retention.
The evaluator receives no credential, filesystem, database, MCP, web,
retrieval, source-connector, generation, persistence, approval, export, or
other capability. It returns only the strict structured output governed below.

The authoritative API references are OpenAI's
[Responses create reference](https://platform.openai.com/docs/api-reference/responses/create)
and
[gpt-5.6-terra model reference](https://platform.openai.com/docs/models/gpt-5.6-terra).

### Independent prompt and exact evaluation unit

Stage 2 uses a static prompt and rubric that are separate from the M3-007
generation prompt. A provider request requires a mandatory canonical Stage-1
admission constructed by the application with marker
`M3_CANONICAL_STAGE1_ADMISSION_V1`. The admission binds the current validation
request, exact registry, source task and outcome, Stage-1 result, and explicit
canonical comparability/conflict metadata. A bare
`SemanticEvaluationInput` is data only and cannot invoke the
provider.

The admission also binds the complete ordered citation topology for the formal
claim. Every topology entry contains a complete Stage-1-valid
claim/citation/evidence tuple plus exact receipt, registry, task, outcome, and
Stage-1 result bindings. At least one citation in that topology must support the claim; a
contradiction citation may be evaluated only when the same admitted topology
contains a supporting citation. Comparability is not an identifier-only caller
assertion: it is either the exact full governed comparison/conflict graph and
all dimensions, relations, classifications, and artifact hashes, or an exact
empty-registry proof. Its canonical registry hash is part of the Stage-1
admission identity, so the same admission cannot be reused with different
comparability metadata.

After that admission succeeds, each request evaluates exactly one current-run
tuple:

- one material claim;
- one formal citation;
- the one exact cited evidence object; and
- only the source-policy, citation-relationship, comparability, conflict, and
  safety metadata required to interpret that tuple.

The application supplies the exact bounded tuple and reconstructs all
admission, identity, validation, registry, task/outcome, topology, policy, and
comparability bindings before invoking the provider and again before accepting
the result. The model never receives generator reasoning, chain of thought,
retrieval scores or ranks as truth, expected semantic results, answer labels,
Development labels, qrels, or Holdout content. Evidence and claim text are
explicitly delimited as untrusted data and cannot alter the rubric, schema,
model configuration, or capability boundary.

Stage 1 is terminal: a tuple that fails deterministic structural or policy
validation is not admitted or sent to Stage 2. It produces zero evaluator
attempts, provider responses, or parsed Stage-2 outputs. Stage 2 cannot repair,
waive, reinterpret, or downgrade a Stage-1 failure.

### Result and decision authority

The structured output uses the existing semantic-support states exactly:

- `supported`;
- `uncertain`; or
- `unsupported`.

The model emits semantic fields only: the state, bounded rationale codes,
bounded explanation, and human-review indication. It does not emit authoritative
hashes, tuple identity, prompt/rubric/schema/configuration identity, or receipt
provenance. Application code derives every content hash and binds the exact
claim/citation/evidence tuple, admission, prompt, rubric, schema, model,
reasoning policy, configuration, and provider execution. Provider reasoning
text is neither requested as an application contract nor stored as authority.

The evaluator is advisory evidence, never the sole ground truth. `unsupported`
cannot enter a formal report. `uncertain` requires recorded human adjudication
or removal. A nominally `supported` result also requires human adjudication or
removal when the citation relationship is a contradiction or the tuple is
material to a governed safety or cross-source conflict decision. Human review
may not convert a failed Stage-1 tuple into an accepted citation.

### Calibration and evidence boundary

Calibration may use only Owner-approved adjudicated Development data or
synthetic adjudicated fixtures. Test, final, release, and Holdout splits are
never calibration inputs. Holdout-20 questions, expected results, answer
labels, and artifacts remain sealed. Calibration never uses generator reasoning
or retrieval score as truth and never tunes source, retrieval, router, qrels,
corpus, or metric semantics.

Raw calibration inputs and provider response bytes are append-only, versioned
artifacts. Every case contains the byte-exact canonical
`SemanticEvaluationRequest`, separately identified evaluator-input and provider
request hashes, the exact credential-free provider request bytes, provider
response ID and hash, the complete bounded Responses
envelope, and the exact inner structured output. On read and before metric
computation, the request and both provider byte surfaces are strictly re-parsed
and cross-bound to the stored parsed semantic fields, rationale, trace, usage,
and response identity. Every case has an adjudicated human expected state,
authority, notes, and packet binding; unresolved cases are not admitted. Every derived metric
or threshold must be reproducible from those raw artifacts and requires the
exact current evaluator method/version, model, prompt hash, rubric hash,
response-schema hash, configuration hash, reasoning policy, 40-hex code
revision, implementation-manifest hash, and approved dataset/packet identities.
Arbitrary or stale calibration configuration is rejected. The judge is not
permitted to overwrite an expected label or silently discard disagreements.

The exact Round 4 closure-candidate evaluator identities are:

- prompt SHA-256:
  `sha256:36958196b5de6f21c73d05957564da6cb8887338686e748bbdb9db85365b5ba1`;
- rubric SHA-256:
  `sha256:78a83aaba18982a45879feb6a5850d86f73525fac9618e00a791c5c32501f562`;
- response-schema SHA-256:
  `sha256:4b13f6eec4a043e6b0a5e83f95e76b430565da206af2f342277f9b2e3465596c`;
  and
- configuration SHA-256:
  `sha256:603e5cc567c3e0bb6ec006de6835ab5309adf39dc333912b18622cbfe6ed1934`.

Calibration must match these identities with model `gpt-5.6-terra` and
reasoning effort `medium`; any later byte change requires a new exact binding.

No Owner-approved human semantic packet and no provider key are currently
available. M3-008A therefore implements and validates the offline framework
only. M3-008B calibration is `BLOCKED_EXTERNAL_INPUTS` until both inputs are
provided through their authorized boundaries. Missing inputs are not replaced
with synthetic success evidence or reported as a calibration PASS.

### Work-item boundary

M3-008A owns the provider-neutral canonical-admission and one-tuple evaluation
contracts, exact separate prompt/rubric/schema, bounded HTTPX Responses gateway,
deterministic result reconstruction, provenance/receipt contract, and offline
tests. It does not integrate Stage 2 into the controlled workflow.

The existing canonical validator has a precommitted `SemanticExpectation`
contract. Resolving that composition and expectation-handoff boundary is not an
M3-008A mechanical change; M3-009 owns workflow composition and contract
resolution. M3-008A does not modify the M3-007 generator, source/evidence
semantics, public API/OpenAPI, persistence schema, retrieval/router/qrels/
corpus/metric contracts, or Holdout access.

## Alternatives considered

- Reusing the generation prompt or generator reasoning: rejected because the
  evaluator must be independent of candidate-generation reasoning and policy.
- Evaluating multiple citations in one request: rejected because the exact
  one-claim/one-citation/one-evidence unit provides auditable identity and
  failure isolation.
- Supplying retrieval rank, score, expected label, or answer key: rejected
  because these values could bias the evaluator or be mistaken for evidence
  truth.
- Treating model output as sole acceptance authority: rejected because Stage 1
  and governed human adjudication remain authoritative safety gates.
- Changing the existing expectation contract during M3-008A: deferred to
  M3-009 because it is a workflow-composition decision, not evaluator
  implementation.
- Calibrating without the approved human packet or provider key: rejected
  because that would fabricate required evidence.

## Consequences

- Semantic evaluation is independently prompted, bounded to one exact citation
  tuple, and reproducible from versioned identities.
- Provider output cannot bypass Stage 1, establish source truth, or eliminate
  required human adjudication.
- Framework validation can complete offline while calibration remains honestly
  blocked on explicit external inputs.
- M3-009 must resolve the precommitted-expectation composition before the
  evaluator can enter the controlled workflow.

## Validation

M3-008A requires focused contract, prompt, gateway, reconstruction, provenance,
and negative tests; the full socket-disabled suite; Ruff; format; strict MyPy;
offline lock, dependency, scope, diff, and secret checks; independent review;
exact-byte rebind; and terminal audit. Tests must prove exact tuple binding,
Stage-1 terminality, prompt separation, absence of answer labels/retrieval-score
truth/generator reasoning/Holdout data, strict three-state output, rationale and
provenance binding, malformed/oversized/provider-failure closure, and required
human-review routing. Review001 through Review005 are preserved as immutable
`FAIL — P0 0 / P1 4 / P2 0`, `FAIL — P0 0 / P1 5 / P2 1`, and
`FAIL — P0 0 / P1 4 / P2 0`, `FAIL — P0 0 / P1 1 / P2 0`, and
`FAIL — P0 0 / P1 1 / P2 0`. The Round 5 closure candidate adds complete
same-run per-citation Stage-1 topology,
canonical full comparability binding, truthful gateway-observation persistence,
mandatory adjudicated resolutions, request reparse, and exact evaluator code
identity, plus production-equivalent envelope/result revalidation, exact raw
provider-request binding, and a shared response-ID/usage/byte-cap authority for
production and calibration. Focused integration validation and fresh
independent review remain pending.

Calibration, agreement metrics, threshold claims, and provider execution remain
unperformed while M3-008B is `BLOCKED_EXTERNAL_INPUTS`. This accepted ADR and
the pending remediation text are authorization/design evidence only; they do
not claim implementation PASS, calibration PASS, provider execution, fresh
review, audit, commit, push, PR, or merge.

## Supersedes / Superseded by

ADR-020 does not supersede ADR-002, ADR-005, ADR-006, ADR-007, ADR-016,
ADR-017, ADR-018, or ADR-019. It supplies the independent Stage-2 evaluator
decision required by the existing citation gate. No later ADR currently
supersedes it.
