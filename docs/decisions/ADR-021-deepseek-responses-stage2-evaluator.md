# ADR-021: DeepSeek Responses Stage-2 evaluator

## Status

Owner accepted for `M3-008B-STAGE2-DEVELOPMENT-CALIBRATION`. Implementation,
pre-network review, calibration, and terminal evidence remain separately gated.

## Decision

Formal M3-008B calibration uses only the dedicated DeepSeek API profile below:

- endpoint: `POST https://api.deepseek.com/responses`;
- model: `deepseek-v4-pro`;
- reasoning effort: `high`;
- output: JSON Schema response format plus the existing strict application parser;
- tools: exact empty list with `tool_choice="none"`; web search is disabled;
- credential: environment-only `DEEPSEEK_API_KEY`;
- transport: existing HTTPX dependency, no SDK and no new dependency.

The exact request deliberately omits OpenAI-specific `store`, `background`,
`parallel_tool_calls`, `truncation`, `previous_response_id`, and `conversation`
fields. The official DeepSeek response-format request shape has no `strict`
boolean; strictness comes from the closed schema (`additionalProperties=false`)
and the application parser's byte, duplicate-key, canonical-JSON, type, bound,
and semantic checks. This is a dedicated adapter, not an OpenAI base-URL swap,
and there is no runtime provider selector.

The existing prompt, rubric, result schema, advisory three-state semantics, and
Stage-1 admission authority remain unchanged. DeepSeek provider identity,
endpoint, model, reasoning, credential-free request bytes, response identity,
raw response bytes, usage, and configuration hash are bound independently. The
frozen Project-Owner resolution identity remains exactly
`sha256:758aaccd90e2e545af2215640426a20b2c75c038d40f0d1d2b2e0cc716aaf806`.
The historical packet's OpenAI evaluator-identity metadata remains immutable
historical construction provenance and is not the active provider profile.
The documented response echo requires `parallel_tool_calls=true` and response
identity is a bounded nonempty printable-ASCII provider string; calibration
requires identities to be unique without inventing a UUID-only provider rule.

## Provider contract and privacy boundary

The [DeepSeek Responses API guide](https://api-docs.deepseek.com/guides/responses_api)
documents Responses as stateless for response/conversation state. Application
state is therefore not continued with a conversation or previous response ID.
That stateless interface property is distinct from provider operational and
privacy retention.

The [DeepSeek API response reference](https://api-docs.deepseek.com/api/create-response)
defines the request/response envelope used by the dedicated adapter, including
response identity, reasoning output, usage details, tools, and structured text
format. Exact raw response bytes remain append-only calibration evidence;
provider reasoning never becomes result authority or an application log field.

The [DeepSeek privacy policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
states that prompts/inputs, outputs, account information, and network/device
data may be processed or stored, that retention varies by data and purpose, and
that processing/storage may occur in the People's Republic of China. Provider
provenance must record the applicable policy identity and access date for a
real run. Owner acceptance is limited to public-research-data V1: no PHI,
identifiable patient data, credentials in model context, private clinical
records, or Holdout content may be sent. Nothing in this decision implies a
special provider accuracy, safety, privacy, or product endorsement.

## Calibration gate

No call is allowed before independent review and terminal pre-network audit
return `PASS — P0 0 / P1 0 / P2 0`. The live runner must first bind the exact
36-case machine packet and frozen Owner resolution packet, canonical Stage-1
request bytes, case order, immutable projections, and 12/12/12 human-state
counts. The exact ordered case/category inventory, audited 40-lowerhex code
revision, and SHA-256 implementation manifest are separate required bindings.
A missing or invalid input, missing key, absent explicit-live flag, or existing
output produces zero provider and output effects.

Version 1 passes only if all 36 frozen cases and all eight frozen categories are exercised,
`unsupported -> supported = 0`, `uncertain -> supported = 0`, overall exact
agreement is at least 0.85, every human state has at least eight cases, and
every human-state recall is at least 0.75. All requests, responses, usage, and
disagreements are retained in one absent external append-only directory. Human
labels are never sent to the provider and never changed by calibration.
After preflight, each successful call is fsynced to an absent pending run before
the next call. A later provider or artifact failure publishes those immutable
prior successes plus only redacted stable failure metadata and no PASS artifact.

## Consequences and exclusions

OpenAI M3-008A code remains isolated historical provider-specific behavior.
This decision adds no dependency, public API/OpenAPI or persistence schema,
medical-source traffic, source/evidence semantics, retrieval/router/qrels/
corpus/metric-contract change, generation change, or Holdout authority.
