# ADR-028: additive DeepSeek generation profile

Decision date: 2026-09-14. Authority: Owner delegates remaining V1 engineering
decisions. The current process has DeepSeek credentials; no OpenAI credential
was present in process/user/machine environments. Never substitute DeepSeek
results into an OpenAI-labelled receipt.

Add a distinct generation path using the official DeepSeek Responses API and
requested model alias `deepseek-flash`, separate from Pro semantic evaluation.
Existing OpenAI generation types, gateway and receipt replay remain unchanged.
New provider/configuration/receipt identities explicitly identify DeepSeek.
The requested alias is recorded as an alias, not an attestation of immutable
weights. Actual reported model metadata is retained with the bounded response.

Use no thinking (`reasoning.effort=none`) for bounded source-grounded structured
draft generation; preserve existing provider-neutral GenerationInput and
GenerationCandidate permission/citation validators and schema. No tools, web,
continuation, patient data, background run or server-side response storage.
Never accept a provider-authored approval or validation decision. Same public
data-use boundary as already-approved DeepSeek evaluation, with stateless API
behavior distinguished from provider retention policy.

Sources checked on the decision date:
[DeepSeek V4.1 Flash release](https://www.deepseek.com/en/news/deepseek-v4-1-flash/),
[Responses API](https://api-docs.deepseek.com/guides/responses_api/), and
[thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/).
These document supported interfaces, not account-specific execution success.

Require deterministic offline malformed/refusal/provenance/credential/bounds
tests, durable receipt and candidate replay, independent review, and a
separately recorded bounded generation smoke before enabling live composition.
No generation request may compete with the current calibration batch; the
supervisor schedules explicit live tests serially. No new library is needed.

This decision does not claim generation quality, calibration acceptance,
clinical validation, or provider availability. The application continues to
require canonical citation/safety gates, independently evaluated support and
explicit human export confirmation for any generated draft.
