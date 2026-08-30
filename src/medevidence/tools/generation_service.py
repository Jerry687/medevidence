"""Provider-neutral application service for durable report generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, final

from .generation import (
    GenerationCandidate,
    GenerationGatewayError,
    GenerationGatewayPort,
    GenerationInput,
    GenerationProviderResult,
    GenerationReceipt,
    GenerationReceiptRef,
    build_generation_receipt,
    generation_candidate_hash,
    generation_receipt_ref,
    reconstruct_generation_input,
    reconstruct_generation_provider_result,
    reconstruct_generation_receipt,
    reconstruct_generation_receipt_ref,
    validate_generation_candidate,
    verify_generation_receipt,
)


class GenerationReceiptStorePort(Protocol):
    """Consumer-owned exact immutable receipt persistence capability."""

    def save(self, receipt: GenerationReceipt) -> GenerationReceiptRef: ...

    def load(self, reference: GenerationReceiptRef) -> GenerationReceipt: ...


class GenerationServiceErrorCode(StrEnum):
    """Stable redacted application-boundary failure classes."""

    INPUT_INVALID = "generation_input_invalid"
    GATEWAY_EXECUTION_INVALID = "generation_gateway_execution_invalid"
    GATEWAY_RESULT_INVALID = "generation_gateway_result_invalid"
    RECEIPT_STORE_INVALID = "generation_receipt_store_invalid"


class GenerationServiceError(RuntimeError):
    """Stable generation-service error without research or candidate material."""

    def __init__(self, code: GenerationServiceErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class DurableGenerationResult:
    """Candidate returned only after exact receipt publication and replay."""

    candidate: GenerationCandidate
    receipt_ref: GenerationReceiptRef


@final
class GenerationService:
    """Generate once and fail closed until the exact receipt replays."""

    _gateway: GenerationGatewayPort
    _receipts: GenerationReceiptStorePort
    _zdr_active: bool | None
    __slots__ = ("_gateway", "_receipts", "_zdr_active")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("GenerationService is a sealed application authority")

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("GenerationService is frozen after construction")

    def __init__(
        self,
        *,
        gateway: GenerationGatewayPort,
        receipts: GenerationReceiptStorePort,
        zdr_active: bool | None,
    ) -> None:
        object.__setattr__(self, "_gateway", gateway)
        object.__setattr__(self, "_receipts", receipts)
        object.__setattr__(self, "_zdr_active", zdr_active)

    def generate(self, generation_input: GenerationInput) -> DurableGenerationResult:
        """Return a candidate only after durable receipt round-trip verification."""

        provider_code: str | None = None
        failure_code: GenerationServiceErrorCode | None = None
        try:
            return GenerationService._generate(self, generation_input)
        except GenerationGatewayError as error:
            provider_code = _validated_gateway_error_code(error)
            if provider_code is None:
                failure_code = GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID
        except GenerationServiceError as error:
            if type(error) is GenerationServiceError:
                failure_code = object.__getattribute__(error, "code")
            else:
                failure_code = GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID
        if provider_code is not None:
            raise GenerationGatewayError(provider_code)
        if failure_code is None:
            failure_code = GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID
        raise GenerationServiceError(failure_code)

    def _generate(self, generation_input: GenerationInput) -> DurableGenerationResult:
        """Execute behind the fresh stable public error boundary."""

        exact_input = _validated_input(generation_input)
        provider_result = _execute_gateway(self._gateway, exact_input)
        candidate, exact_provider_result, receipt, expected_ref = _validated_provider_material(
            exact_input,
            provider_result,
            zdr_active=self._zdr_active,
        )
        persisted_ref = _save_exact_receipt(self._receipts, receipt, expected_ref)
        reloaded = _load_exact_receipt(
            self._receipts,
            persisted_ref,
            generation_input=exact_input,
            provider_result=exact_provider_result,
        )
        if generation_receipt_ref(reloaded) != expected_ref:
            raise GenerationServiceError(GenerationServiceErrorCode.RECEIPT_STORE_INVALID)
        if generation_candidate_hash(candidate) != expected_ref.candidate_hash:
            raise GenerationServiceError(GenerationServiceErrorCode.GATEWAY_RESULT_INVALID)
        return DurableGenerationResult(candidate=candidate, receipt_ref=expected_ref)


def _validated_input(generation_input: GenerationInput) -> GenerationInput:
    try:
        return reconstruct_generation_input(generation_input)
    except (TypeError, ValueError) as error:
        raise GenerationServiceError(GenerationServiceErrorCode.INPUT_INVALID) from error


def _validated_gateway_error_code(error: GenerationGatewayError) -> str | None:
    if type(error) is not GenerationGatewayError:
        return None
    try:
        code = object.__getattribute__(error, "code")
        if type(code) is not str:
            return None
        GenerationGatewayError(code)
        return code
    except Exception:
        return None


def _execute_gateway(
    gateway: GenerationGatewayPort,
    generation_input: GenerationInput,
) -> GenerationProviderResult:
    try:
        return gateway.generate(generation_input)
    except GenerationGatewayError:
        raise
    except Exception as error:
        raise GenerationServiceError(
            GenerationServiceErrorCode.GATEWAY_EXECUTION_INVALID
        ) from error


def _validated_provider_material(
    generation_input: GenerationInput,
    provider_result: GenerationProviderResult,
    *,
    zdr_active: bool | None,
) -> tuple[
    GenerationCandidate,
    GenerationProviderResult,
    GenerationReceipt,
    GenerationReceiptRef,
]:
    try:
        exact_provider_result = reconstruct_generation_provider_result(provider_result)
        candidate = validate_generation_candidate(
            generation_input,
            exact_provider_result.candidate,
        )
        receipt = build_generation_receipt(
            generation_input,
            exact_provider_result,
            zdr_active=zdr_active,
        )
        expected_ref = generation_receipt_ref(receipt)
        return candidate, exact_provider_result, receipt, expected_ref
    except (TypeError, ValueError) as error:
        raise GenerationServiceError(GenerationServiceErrorCode.GATEWAY_RESULT_INVALID) from error


def _save_exact_receipt(
    receipts: GenerationReceiptStorePort,
    receipt: GenerationReceipt,
    expected_ref: GenerationReceiptRef,
) -> GenerationReceiptRef:
    try:
        exact_receipt = reconstruct_generation_receipt(receipt)
        exact_expected_ref = reconstruct_generation_receipt_ref(expected_ref)
        persisted_ref = receipts.save(exact_receipt)
        exact_persisted_ref = reconstruct_generation_receipt_ref(persisted_ref)
        if exact_persisted_ref != exact_expected_ref:
            raise ValueError("generation receipt reference mismatch")
        return exact_persisted_ref
    except Exception as error:
        raise GenerationServiceError(GenerationServiceErrorCode.RECEIPT_STORE_INVALID) from error


def _load_exact_receipt(
    receipts: GenerationReceiptStorePort,
    expected_ref: GenerationReceiptRef,
    *,
    generation_input: GenerationInput,
    provider_result: GenerationProviderResult,
) -> GenerationReceipt:
    try:
        exact_expected_ref = reconstruct_generation_receipt_ref(expected_ref)
        reloaded = receipts.load(exact_expected_ref)
        exact_receipt = reconstruct_generation_receipt(reloaded)
        exact_reloaded = verify_generation_receipt(
            exact_receipt,
            generation_input=generation_input,
            provider_result=provider_result,
        )
        if generation_receipt_ref(exact_reloaded) != exact_expected_ref:
            raise ValueError("generation receipt replay mismatch")
        return exact_reloaded
    except Exception as error:
        raise GenerationServiceError(GenerationServiceErrorCode.RECEIPT_STORE_INVALID) from error
