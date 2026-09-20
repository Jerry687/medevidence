"""Closed runtime V3 provider and source-policy bindings for report validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from medevidence.domain import SourceType

from .runtime_source_bounds import SourceBoundsTuple, expected_runtime_source_bounds_v3

M3_VALIDATION_CONFIGURATION_V2 = "M3_VALIDATION_CONFIGURATION_V2"
M3_VALIDATION_POLICY_V2 = "M3_VALIDATION_POLICY_V2"
M3_VALIDATION_CONFIGURATION_V3 = "M3_VALIDATION_CONFIGURATION_V3"
M3_VALIDATION_POLICY_V3 = "M3_VALIDATION_POLICY_V3"
M3_VALIDATION_CONFIGURATION_V4 = "M3_VALIDATION_CONFIGURATION_V4"
M3_VALIDATION_POLICY_V4 = "M3_VALIDATION_POLICY_V4"

M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V2 = (
    "m3.semantic-evaluation.v2.deepseek-responses.v2"
)
M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V2 = (
    "sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9"
)
M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V2 = (
    "sha256:fd3e9bda090c92b0c83244d521cb3163f4c3e43bda74b1132efaad7ffbb7f491"
)
M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V3 = (
    "m3.semantic-evaluation.v2.deepseek-responses.v5-low-prompt-v3"
)
M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3 = (
    "sha256:c85008ab71e6bf721fc36689108190e62c0cf9af853fdbf7f575cd105c8f0c9c"
)
M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3 = (
    "sha256:33a2e029e12c5de9001b2aa0f4c167f519a5926bb992c2f7e6e9ae4a625597b6"
)
M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V4 = (
    "m3.semantic-evaluation.v2.qwen-chat-completions.v1-prompt-v3"
)
M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V4 = (
    "sha256:3aba865da8cb8eb7ed80ebd9f6140624924215ae60423b5d4cea1c6b7482ea92"
)
M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V4 = M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3

ValidationProfile = tuple[str, str, str, str]


def provider_method_for_validation_configuration(version: str) -> str:
    """Keep provider identity explicit across DeepSeek and Qwen receipts."""

    validation_profile(version)
    if version == M3_VALIDATION_CONFIGURATION_V4:
        return "qwen.chat-completions.independent_semantic_evaluation"
    return "deepseek.responses.independent_semantic_evaluation"


def provider_method_for_pair(provider_version: str, provider_hash: str) -> str:
    """Resolve a method only from an exact known provider version/hash pair."""

    if (provider_version, provider_hash) == validation_profile(M3_VALIDATION_CONFIGURATION_V4)[2:]:
        return provider_method_for_validation_configuration(M3_VALIDATION_CONFIGURATION_V4)
    # Callers independently require an exact known pair. An unknown pair keeps
    # the legacy method only long enough to raise its stable contract error.
    return "deepseek.responses.independent_semantic_evaluation"


def validation_profile(version: str) -> ValidationProfile:
    """Return policy, neutral hash and exact provider pair for a known version."""

    if version == M3_VALIDATION_CONFIGURATION_V2:
        return (
            M3_VALIDATION_POLICY_V2,
            M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V2,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V2,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V2,
        )
    if version == M3_VALIDATION_CONFIGURATION_V3:
        return (
            M3_VALIDATION_POLICY_V3,
            M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V3,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3,
        )
    if version == M3_VALIDATION_CONFIGURATION_V4:
        return (
            M3_VALIDATION_POLICY_V4,
            M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V4,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V4,
            M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V4,
        )
    raise ValueError("semantic validation configuration is not a known closed profile")


def known_provider_pair(neutral_hash: str, provider_version: str, provider_hash: str) -> bool:
    observed = neutral_hash, provider_version, provider_hash
    return observed in (
        validation_profile(M3_VALIDATION_CONFIGURATION_V2)[1:],
        validation_profile(M3_VALIDATION_CONFIGURATION_V3)[1:],
        validation_profile(M3_VALIDATION_CONFIGURATION_V4)[1:],
    )


class ReceiptPolicyView(Protocol):
    @property
    def marker(self) -> str: ...

    @property
    def policy_version(self) -> str: ...

    @property
    def configuration_version(self) -> str: ...

    @property
    def semantic_contract(self) -> str: ...


def v2_receipt_policy_pair_valid(value: ReceiptPolicyView) -> bool:
    try:
        expected_policy = validation_profile(value.configuration_version)[0]
    except ValueError:
        return False
    return (
        value.marker == "M3_VALIDATION_RECEIPT_V2"
        and value.policy_version == expected_policy
        and value.semantic_contract == "M3_STAGE2_SEMANTIC_RESULT_V2"
    )


@dataclass(frozen=True, slots=True)
class RuntimeSemanticProfileIdentityV3:
    method: str
    semantic_configuration_hash: str
    provider_configuration_version: str
    provider_configuration_hash: str


class DeclaredRuntimeSemanticProfileV3(Protocol):
    @property
    def profile_identity(self) -> RuntimeSemanticProfileIdentityV3: ...


def require_v3_port_profile(port: DeclaredRuntimeSemanticProfileV3 | None, *, method: str) -> None:
    """Fail before Stage-1 persistence or HTTP when a port has the wrong identity."""

    try:
        declared = port.profile_identity  # type: ignore[union-attr]
    except Exception as error:
        raise ValueError("semantic V3 port identity is unavailable") from error
    expected = RuntimeSemanticProfileIdentityV3(
        method=method,
        semantic_configuration_hash=M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3,
        provider_configuration_version=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V3,
        provider_configuration_hash=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3,
    )
    if type(declared) is not RuntimeSemanticProfileIdentityV3 or declared != expected:
        raise ValueError("semantic V3 port identity differs from the fixed profile")


def require_v4_port_profile(port: DeclaredRuntimeSemanticProfileV3 | None, *, method: str) -> None:
    """Fail before persistence or HTTP unless the port is the exact Qwen profile."""

    try:
        declared = port.profile_identity  # type: ignore[union-attr]
    except Exception as error:
        raise ValueError("semantic V4 port identity is unavailable") from error
    expected = RuntimeSemanticProfileIdentityV3(
        method=method,
        semantic_configuration_hash=M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V4,
        provider_configuration_version=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V4,
        provider_configuration_hash=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V4,
    )
    if type(declared) is not RuntimeSemanticProfileIdentityV3 or declared != expected:
        raise ValueError("semantic V4 port identity differs from the fixed Qwen profile")


def port_declares_v3_profile(port: object, *, method: str) -> bool:
    """Detect a named V3 port so legacy V2 cannot send it an HTTP request."""

    try:
        declared = cast(DeclaredRuntimeSemanticProfileV3, port).profile_identity
    except AttributeError:
        return False
    except Exception as error:
        raise ValueError("semantic port identity is unavailable") from error
    if type(declared) is not RuntimeSemanticProfileIdentityV3:
        raise ValueError("semantic port identity has a foreign type")
    require_v3_port_profile(cast(DeclaredRuntimeSemanticProfileV3, port), method=method)
    return True


def require_port_for_validation_configuration(version: str, port: object, *, method: str) -> None:
    if version == M3_VALIDATION_CONFIGURATION_V3:
        require_v3_port_profile(cast(DeclaredRuntimeSemanticProfileV3, port), method=method)
    elif version == M3_VALIDATION_CONFIGURATION_V4:
        require_v4_port_profile(cast(DeclaredRuntimeSemanticProfileV3, port), method=method)
    elif version == M3_VALIDATION_CONFIGURATION_V2:
        try:
            declared = cast(DeclaredRuntimeSemanticProfileV3, port).profile_identity
        except AttributeError:
            return
        except Exception as error:
            raise ValueError("semantic port identity is unavailable") from error
        if type(declared) is not RuntimeSemanticProfileIdentityV3:
            raise ValueError("semantic port identity has a foreign type")
        raise ValueError("named semantic port cannot serve the legacy V2 registry")
    else:
        raise ValueError("semantic validation configuration is unknown")


class SourceBoundsView(Protocol):
    @property
    def max_query_characters(self) -> int: ...

    @property
    def max_pages(self) -> int: ...

    @property
    def max_records(self) -> int: ...

    @property
    def max_payload_bytes(self) -> int: ...

    @property
    def max_total_seconds(self) -> int: ...


def source_profile_matches_v3(
    source: SourceType, actual: SourceBoundsView, master: SourceBoundsView
) -> bool:
    """Compare recorded execution truth to its fixed source and master budgets."""

    master_values: SourceBoundsTuple = (
        master.max_query_characters,
        master.max_pages,
        master.max_records,
        master.max_payload_bytes,
        master.max_total_seconds,
    )
    actual_values: SourceBoundsTuple = (
        actual.max_query_characters,
        actual.max_pages,
        actual.max_records,
        actual.max_payload_bytes,
        actual.max_total_seconds,
    )
    return actual_values == expected_runtime_source_bounds_v3(source, master_values)
