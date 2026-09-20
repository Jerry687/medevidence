# ADR-039: Fixed Qwen runtime semantic profile

Status: local implementation capability; development comparison is not a formal release certificate.

## Decision

The Owner selected `qwen3.8-max-0902` after the frozen 36-case Development comparison (`33/36` agreement). Runtime semantic validation therefore has a separate `M3_VALIDATION_CONFIGURATION_V4` and `M3_VALIDATION_POLICY_V4`. The exact provider method is `qwen.chat-completions.independent_semantic_evaluation`, with provider version `m3.semantic-evaluation.v2.qwen-chat-completions.v1-prompt-v3` and hash `sha256:3aba865da8cb8eb7ed80ebd9f6140624924215ae60423b5d4cea1c6b7482ea92`. The provider-neutral V3 semantic configuration, prompt bytes, local response schema, rationale constraints, review routing, and source bounds remain authoritative. Earlier DeepSeek profiles and receipts retain their original identities.

The provider request uses ChatCompletions, `temperature=0`, nonthinking, search disabled, no tools, a 4096 completion-token cap, and exactly the V3 system/user input bytes. Qwen's wire JSON Schema omits only `rationale_codes.uniqueItems`; the local candidate validator still enforces the original unique, exact-one base-code rule. The runtime endpoint must be an Owner-configured HTTPS Beijing workspace URL ending in `/compatible-mode/v1/chat/completions`; the API key comes from `DASHSCOPE_API_KEY`. Neither value is saved in receipts, code, or logs.

The Qwen cache gives this profile its own operation identity, including a hash of the configured workspace endpoint. A durable START precedes each POST, a safe complete raw response is persisted before parsing, and a successful result is independently reconstructed from the raw bytes on replay. Only a complete `429/500/502/503/504` status permits bounded retry, using capped exponential backoff, deterministic jitter, and a capped `Retry-After` value. A partial body, transport uncertainty, missing terminal event, invalid response, or credential echo cannot be resent automatically. The pooled async transport enforces a 95-second whole-operation deadline, with 20-second connection and 90-second read limits; request and response bounds remain 256 KiB and 128 KiB.

## Evidence and limit

The Qwen comparison was an offline-scored Development set, not a runtime acceptance or clinical safety certificate. Runtime V4 may be exercised only with the separately recorded deployment and source-access gates applicable to the exact run. Any report still requires the existing human review and provenance checks. This decision does not authorize live medical-source calls, public deployment, Git remote changes, or a generation-model switch.
