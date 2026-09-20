"""Frozen M3-008B DeepSeek calibration inputs, evidence, and acceptance authority."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast, final

from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
)
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_V1,
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1,
    DeepSeekRawSemanticObservation,
    DeepSeekSemanticAssessment,
    DeepSeekSemanticAssessmentV2,
    DeepSeekSemanticEvaluatorError,
    deepseek_provider_request_bytes,
    deepseek_provider_request_semantic_v2_bytes,
    deepseek_provider_request_v2_bytes,
    deepseek_provider_request_v3_bytes,
    parse_deepseek_completed_response_semantic_v2,
    parse_deepseek_completed_response_v2,
    parse_deepseek_completed_response_v3,
    parse_deepseek_completed_response_v4,
)
from medevidence.persistence import ProviderAttemptEvent, ProviderAttemptLedgerRepository
from medevidence.persistence.repositories import validate_provider_attempt_event
from medevidence.tools.provider_attempt_framing import (
    APPROVED_HEADER_NAMES_IDENTITY,
    FRAMING_CONTRACT_IDENTITY,
    normalize_approved_headers,
    provider_raw_relative_path_is_canonical,
    raw_body_persistence_permitted,
)
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_RESPONSE_WIRE_CONTRACT_IDENTITY_V2,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V2,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V3,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V4,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V2,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V4,
    DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
    DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
    DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
    DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
    REVIEW_ROUTING_POLICY_HASH,
    SEMANTIC_EVALUATION_PROMPT_HASH,
    SEMANTIC_EVALUATION_PROMPT_HASH_V2,
    SEMANTIC_EVALUATION_PROMPT_HASH_V3,
    SEMANTIC_EVALUATION_PROMPT_VERSION,
    SEMANTIC_EVALUATION_PROMPT_VERSION_V2,
    SEMANTIC_EVALUATION_PROMPT_VERSION_V3,
    SEMANTIC_EVALUATION_RUBRIC_HASH,
    SEMANTIC_EVALUATION_RUBRIC_HASH_V2,
    SEMANTIC_EVALUATION_RUBRIC_HASH_V3,
    SEMANTIC_EVALUATION_RUBRIC_VERSION,
    SEMANTIC_EVALUATION_RUBRIC_VERSION_V2,
    SEMANTIC_EVALUATION_RUBRIC_VERSION_V3,
    SEMANTIC_EVALUATION_SCHEMA_HASH,
    SEMANTIC_EVALUATION_SCHEMA_HASH_V2,
    SEMANTIC_EVALUATION_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_SCHEMA_VERSION_V2,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH,
    SEMANTIC_EVALUATION_V2_CONTRACT_HASH,
    SEMANTIC_EVALUATION_V2_CONTRACT_VERSION,
    SEMANTIC_EVALUATION_V2_PROMPT_HASH,
    SEMANTIC_EVALUATION_V2_PROMPT_VERSION,
    SEMANTIC_EVALUATION_V2_PROVIDER_CONFIGURATION_VERSION,
    SEMANTIC_EVALUATION_V2_PROVIDER_METHOD,
    SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH,
    SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_ROW_COUNT,
    SEMANTIC_EVALUATION_V2_RUBRIC_HASH,
    SEMANTIC_EVALUATION_V2_RUBRIC_VERSION,
    SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
    SEMANTIC_EVALUATION_V2_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_VERSION,
    SemanticEvaluationCandidate,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluationUsage,
    build_deepseek_semantic_evaluation_result_v2,
    build_deepseek_semantic_evaluation_result_v3,
    build_deepseek_semantic_evaluation_result_v4,
    build_semantic_evaluation_result_v2,
    parse_semantic_evaluation_request,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
    semantic_evaluation_v2_routing_matrix_bytes,
    validate_semantic_evaluation_v2_routing_matrix_bytes,
)

CALIBRATION_DATASET_IDENTITY: Final = (
    "sha256:7256269fc1828da2d86424363a7275d06e0fbee2bc5e716c66fcbe94cd03807b"
)
OWNER_RESOLUTION_IDENTITY: Final = (
    "sha256:758aaccd90e2e545af2215640426a20b2c75c038d40f0d1d2b2e0cc716aaf806"
)
MACHINE_PACKET_SHA256: Final = "c3a0823cb101007417a6a0af1ccf02dae7a40f5a8863b1dfe3e266e6ed39e6c9"
RESOLUTION_PACKET_SHA256: Final = "7b0414269b70264c0d4237c908da7b4f3422a90d22a3e1522d5b2bb871fb4c98"
CASE_COUNT: Final = 36
FROZEN_CASE_INVENTORY_IDENTITY: Final = (
    "sha256:bed7441026b4e32e2b627fa33e9c57c8e6022cc962c130be1c72b0b8ca498378"
)
FROZEN_CATEGORY_COUNTS: Final = (
    ("applicable_contradiction", 8),
    ("direct_semantic_support", 4),
    ("explicit_negation", 4),
    ("insufficient_indirect_evidence", 4),
    ("irrelevant_limitation_context", 4),
    ("legitimate_partial_evidence", 4),
    ("qualified_contradiction", 4),
    ("source_specific_limitations", 4),
)
HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:cf810656f57cd738b59abd8694b07855b4be9839b5e495a9dfe31548d35ede31"
)
HISTORICAL_ATTEMPT005_CASE1_REQUEST_BYTES: Final = 5_972
HISTORICAL_ATTEMPT005_CASE1_REQUEST_HASH: Final = (
    "sha256:6d8d309524aa47dc342bbb2226f5e31003578be915bfed6bafc57f8b39b4f9c8"
)
HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_BYTES: Final = 8_977
HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_HASH: Final = (
    "sha256:9141329b33f96df06cf6d889fa5c164c87acee8a3f0a2ac43712c8f01bb76f18"
)
HISTORICAL_ATTEMPT005_PROJECTION_HASH: Final = (
    "sha256:0dddbbb75c5d46822d1e01acfb03c6e13588d90fa4a2f2e0fe033ff881e892f6"
)
HISTORICAL_ATTEMPT005_STATUS_BINDING_HASH: Final = (
    "sha256:596b133e9468f21712ba789f6f5c41c9627957cf7b7d97dc9eb02d42db7e3a99"
)
HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_BYTES: Final = 421
HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_HASH: Final = (
    "sha256:c3fc115886cdd303a33c2288dd16fac01630c914d9a9fb972b88d3444e8bb383"
)
HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_BYTES: Final = 400
HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_HASH: Final = (
    "sha256:c3e9f566882dde1b5d3af93efe5318ee430e26a38a6cad2f653c93b4bfd7a7f5"
)
HISTORICAL_ATTEMPT006_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:00d9dbe9f56b8472a6e9e76d334ede09589c35a16af72ac9fe003d05f7a62aa8"
)
HISTORICAL_ATTEMPT006_CONFIGURATION_BINDING_HASH: Final = (
    "sha256:00d9dbe9f56b8472a6e9e76d334ede09589c35a16af72ac9fe003d05f7a62aa8"
)
HISTORICAL_ATTEMPT006_RUN_CONFIGURATION_FILE_HASH: Final = (
    "sha256:a06b25d912f784b9e0f03a53fdfa97555cecfd262ba26855b19f357f25624d8e"
)
HISTORICAL_ATTEMPT006_SUCCESS_CASE_FILE_HASHES: Final = (
    "sha256:c3cb3ace41296d4ca6ad4bf04fc75e94c8f4f6b1c195dbef582d679b36fde3cb",
    "sha256:4e4a8df1eb03daa649167e7df2cbef8c1ccb5ad7608df04d9d34aecd4bb61c51",
    "sha256:232eee64cb48744b94a612d9aec966d7761ac12b2e77d0cdc2b02a0f36635e12",
    "sha256:963df93ba88e37ac859f359bda28289a2a9a6d48a789947ebd9a5c0284d5bcba",
    "sha256:3a38c5a7797e68f52cbda37332f00cd5e8679fdd65dab8cce00ad78babf42016",
)
HISTORICAL_ATTEMPT006_PROJECTION_FILE_HASH: Final = (
    "sha256:f153da7e26350416bb48b282da334c4d5948fa6b12d7afba7c3a909a72766d8d"
)
HISTORICAL_ATTEMPT006_PROJECTION_HASH: Final = (
    "sha256:de790badf4cb8d8d5cc33dc28ee3aacde37c7ad9ee27a3b298b466b1431873ec"
)
HISTORICAL_ATTEMPT006_STATUS_FILE_HASH: Final = (
    "sha256:8f837b81346797c23a34777b54d8560601aeb8ce747aeb19aa077d7f285131b6"
)
HISTORICAL_ATTEMPT006_STATUS_BINDING_HASH: Final = (
    "sha256:51ca35dc13e0b26f1f84d713d0efa779a98752cbe8d97e1991d89433a3a210e2"
)
HISTORICAL_ATTEMPT006_CLASSIFICATION: Final = (
    "V1_PROVIDER_OUTPUT_VALID_BUT_APPLICATION_POLICY_BINDING_FAILED"
)
HISTORICAL_ATTEMPT007_MANIFEST_HASH: Final = (
    "sha256:3425e0035890dcec8f99bc305c97531c584856d9e54d5e7cd39325cd3e7269d7"
)
HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:a8c2038480addeb7255dd71592ac40888ab6ee22d1d945c44e6110cc0e7f5ce5"
)
HISTORICAL_ATTEMPT007_CONFIGURATION_FILE_HASH: Final = (
    "sha256:bb051d2244b452df3668c62b2a1694ee59d9d64711d902ed615d702d31a20376"
)
HISTORICAL_ATTEMPT007_PROJECTION_HASH: Final = (
    "sha256:67e8af93d6eda5dddd34f94ac2ac705e44af9f5fa4930d605c7ce57d98206684"
)
HISTORICAL_ATTEMPT007_STATUS_BINDING_HASH: Final = (
    "sha256:4983adfb94b9adc41778829134842af24fc54a6615359711d06b3987f5b7aa9c"
)
HISTORICAL_ATTEMPT007_SUCCESS_RAW_FACTS: Final = (
    (7202, "sha256:0fb737073cebee8b50191406fa302b8097b7d931483fb70698a5ced905168a91"),
    (7729, "sha256:7db1ff5114111c6074b92070fb4a334c962fa393bf12f29210f1f85a52fa2e49"),
    (10572, "sha256:23751854f3d9e00e496c290e6eab3f7d1541c53044ad988cb0a9a042d03f918f"),
    (13534, "sha256:711e5e8e9895cba88dfeac0cdfff00c56e435428ae3566ca8faad14237971b59"),
)
HISTORICAL_ATTEMPT007_CASE_FILE_HASHES: Final = (
    "sha256:b21621a71f2abaffe3153b337ecc5df2f4901c8a59bd899551c6958ef3cc1efd",
    "sha256:e0c39c656285a9a1f8b04a86072f46fa696e054641eeb498a9b549930f517cd8",
    "sha256:ef64eaba85ee58db5a68d7b42f5edba7853269c1fc6c7d05cdc707b072d513c0",
    "sha256:1c8d7edb3c53b9e842d24fc85f8e07245ff9078a43290b244314672ec9761e0d",
)
HISTORICAL_ATTEMPT008_MANIFEST_HASH: Final = (
    "sha256:bdbc9b07a12433b082bc6d1bec62445f9e73810f2b6ed7857c700e92526b19b2"
)
HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:0b4e918e30c511174ad12ce6b07b25312688995fb2dc46d81868e2caa40baa89"
)
HISTORICAL_ATTEMPT008_CONFIGURATION_FILE_HASH: Final = (
    "sha256:ddfa7ad1aaba6a074b32f9cbee8335cf4a57a3d717e633363375f82536ced1ad"
)
HISTORICAL_ATTEMPT008_PROJECTION_FILE_HASH: Final = (
    "sha256:1474309146977b569f6391d303f6ed1b6dada29348a25a846ea36f213de41e35"
)
HISTORICAL_ATTEMPT008_PROJECTION_HASH: Final = (
    "sha256:936ddc9e280b9ed5bda1f2b630c675d54e75e58c2a3dbb7a67cdf35b781ecbb5"
)
HISTORICAL_ATTEMPT008_STATUS_FILE_HASH: Final = (
    "sha256:1650cfb5b061d24fd78755ec623dcd3b961ba5cb2380259e46ec862226eb3eac"
)
HISTORICAL_ATTEMPT008_STATUS_BINDING_HASH: Final = (
    "sha256:ca68ddf05134464d5d1802b11b113440b63752e5f5aa809f1614a7d816448185"
)
HISTORICAL_ATTEMPT008_SUCCESS_RAW_FACTS: Final = (
    (8194, "sha256:46d6b2273db0f887680c1301ce2c0850b78342f52f380b88ad1d05763d7f4460"),
    (8575, "sha256:1efc8b9ec1b03df9b3531fe32a7c37055d63ad7ae70b33bcd74767c81a57343d"),
    (8601, "sha256:4bd3d95017a5257e09e32863c7617fbfcc65186eec1ec947ebc9e9bbcf9ed98e"),
    (11612, "sha256:4db3aef2fc0e584896ef558f794ed9723f3e78ed1150e2dffe5e377a780fad85"),
)
HISTORICAL_ATTEMPT008_CASE_FILE_HASHES: Final = (
    "sha256:4189cb59288ba9ce1b0fd16ff3496cd41930354367e2c8dcffe8d6ed9fa08564",
    "sha256:0ebd711e7427469a16bbf4951f5fd620e249bfd14461e858039f5db030f23a41",
    "sha256:cd67ed7d02364b9099349450869bb418e764dc17b876f5bd789199ef7e2d8d91",
    "sha256:c6a31f8fe7030af4fd203961d76254147ff70e693a167b13a088398fe4a23ee4",
)
HISTORICAL_ATTEMPT009_MANIFEST_HASH: Final = (
    "sha256:99af376d7cbacd0eec72c4520337f4ce73a4cfaa36455a6b99a18fda1656fa13"
)
HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:4e1d5b2cd481ae62752d1eddda33bd8acbc43679f50bada019d414c4aef6d0e6"
)
HISTORICAL_ATTEMPT009_CONFIGURATION_FILE_HASH: Final = (
    "sha256:94b1174508ca157d92517352670dc96899099eef165656d8ad84a4410ae23f67"
)
HISTORICAL_ATTEMPT009_PROJECTION_FILE_HASH: Final = (
    "sha256:06120143817b1b5cea881bd9fa00346bb66c3869511171bbc860c96062f15a87"
)
HISTORICAL_ATTEMPT009_PROJECTION_HASH: Final = (
    "sha256:c02f71b8e928ea4076af9997c4c07ebd4cb27e7c290f64ed44dadeb3c91a1b46"
)
HISTORICAL_ATTEMPT009_STATUS_FILE_HASH: Final = (
    "sha256:a4201ecc26f84ded55dfccb0e052d3bad717392b197b33a86985af388d4e1eea"
)
HISTORICAL_ATTEMPT009_STATUS_BINDING_HASH: Final = (
    "sha256:3d883dfd3dd8af63abf11b05f516477e1091179ab17b57085a12ddd18bee4b22"
)
HISTORICAL_ATTEMPT009_SUCCESS_RAW_FACTS: Final = (
    (8338, "sha256:6b015c926ca88a2f06f5f32c4f9fe9b2947c97b996d67ab3a76a758ab564ea58"),
    (8619, "sha256:912fd7eac7230a81738d2faea5941759d327ca983d2ba378b24aabe8666bc18d"),
    (11157, "sha256:a20a3a4872fc7ce290352290c02cb597233b537e01d77ba69489475a7679ce74"),
    (8258, "sha256:a496453a81b6e296c36a3cae7698bbc2b73ac7c4f30b9e9caa1e618084344a2e"),
)
HISTORICAL_ATTEMPT009_CASE_FILE_HASHES: Final = (
    "sha256:0eb31535703acb94ce9a098a4a271ca685b4dde1cb4696588a502f8f44c1d537",
    "sha256:c20ae07019c12f237026d8a6d97a6584942c888509fecdb863f8ac9b78818833",
    "sha256:0d23d74c4ead176ce6955a371c9665e2337a4f3e9e301a88cd6d10ee82e58614",
    "sha256:ac706eaa3e664479366dd183bfd9321683895e593c3206a094890ecc92381222",
)
HISTORICAL_ATTEMPT010_MANIFEST_HASH: Final = (
    "sha256:2de9fd9eeb293bd19ae860f6a4f71dbf4f9b308bd7baa0974e7426d9021a614a"
)
HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID: Final = (
    "provider-attempt-run:sha256:e85887cb2f409bc03bf1b6964b073efe78415e83bd754b9aaa4e3795a45aaa63"
)
HISTORICAL_ATTEMPT010_CONFIGURATION_FILE_HASH: Final = (
    "sha256:491f4455127037bb55477587d1093d2c75ae050260e8cb04f338f52751fd0203"
)
HISTORICAL_ATTEMPT010_PROJECTION_FILE_HASH: Final = (
    "sha256:9276fe9f3ba8a7a0a0a72e93a383514fbf5d7f45f15df3ac386d20485ffb4c79"
)
HISTORICAL_ATTEMPT010_PROJECTION_HASH: Final = (
    "sha256:ecc271a70ab6c482b32576432e690afec2da4f62dd09f46710076065db616694"
)
HISTORICAL_ATTEMPT010_STATUS_FILE_HASH: Final = (
    "sha256:84dc6e7d6fb740013b648fa01ecf589f53dd63c7e0c0b208cbee920c922f439c"
)
HISTORICAL_ATTEMPT010_STATUS_BINDING_HASH: Final = (
    "sha256:c65e2dc63e6d14cc7a10631d45b9c9af21468d2d941ee3b2af18a448b2e7ec6f"
)
HISTORICAL_ATTEMPT010_SUCCESS_RAW_FACTS: Final = (
    (11798, "sha256:84940533b7ea847a4dafc30f76d730e5c563820a62ec3d16204324ea0e7216c4"),
    (8987, "sha256:75172af385bd630faee3668a8b321367d9f3183c2e75b5672f44552684062526"),
    (7777, "sha256:82cc8f6df63428dd865f512b1b21d210c19ba0e2bf6c20227f992f8000d9b8f1"),
    (8634, "sha256:563d84c46d7c8cb7536249650d537a51ac23811d4242fc1fdc7517a8a5ca7a81"),
)
HISTORICAL_ATTEMPT010_CASE_FILE_HASHES: Final = (
    "sha256:13ed6cedd2f295697009f911c9d9a9ff04b1fc4aa9e830fe833a291abf0637d4",
    "sha256:7226a327b6cb2f1e0874728dbfd77bf6a96720ac2450c682d2d14edc0159c544",
    "sha256:f6d9ac9c9e6a89110cbeec76f92d43fb4422196368bd5a3736c0b9914bfa7fa4",
    "sha256:046c74ade23ce742667e7c0c725e7a14fd6605fb93466d235d94331e484f3ec7",
)
_HISTORICAL_PROVIDER_RUN_IDS: Final = frozenset(
    {
        HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT006_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
    }
)
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
_EXTERNAL_JSON_MAX_BYTES: Final = 40_000_000
_EXTERNAL_JSON_MAX_DEPTH: Final = 128
_PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA: Final = {
    "M3_PROVIDER_ATTEMPT_EVENT_V1": (
        "event_id",
        "schema_version",
        "provider_run_id",
        "case_id",
        "case_ordinal",
        "attempt_ordinal",
        "event_kind",
        "event_slot",
        "start_event_id",
        "start_event_kind",
        "provider",
        "endpoint",
        "model",
        "configuration_hash",
        "request_hash",
        "started_at_utc",
        "completed_at_utc",
        "http_status",
        "disposition",
        "error_code",
        "credential_echo",
        "body_complete",
        "body_byte_count",
        "body_hash",
        "body_relative_path",
        "observed_body_bytes_lower_bound",
        "approved_header_names",
    ),
    "M3_PROVIDER_ATTEMPT_EVENT_V2": (
        "event_id",
        "schema_version",
        "provider_run_id",
        "case_id",
        "case_ordinal",
        "attempt_ordinal",
        "event_kind",
        "event_slot",
        "start_event_id",
        "start_event_kind",
        "provider",
        "endpoint",
        "model",
        "configuration_hash",
        "request_hash",
        "started_at_utc",
        "completed_at_utc",
        "http_status",
        "disposition",
        "error_code",
        "credential_echo",
        "body_complete",
        "body_byte_count",
        "body_hash",
        "body_relative_path",
        "observed_body_bytes_lower_bound",
        "approved_header_names",
        "approved_header_names_identity",
        "normalized_header_names",
        "normalized_content_encoding_values",
        "normalized_content_length_values",
        "normalized_content_type_values",
        "normalized_transfer_encoding_values",
        "normalized_x_request_id_values",
        "normalized_header_facts_identity",
        "raw_header_field_count",
        "framing_contract_identity",
        "framing_input_identity",
        "http_version_state",
        "observed_http_version",
        "header_surface_state",
        "content_length_state",
        "content_length_value",
        "transfer_encoding_state",
        "content_encoding_state",
        "content_type_state",
        "actual_body_byte_count",
        "raw_evidence_state",
        "raw_body_hash",
        "raw_relative_path",
        "raw_artifact_identity",
        "framing_status",
        "accepted_framing_class",
        "framing_rejection_code",
    ),
}
_PROJECTION_SCHEMA_BY_EVENT_SCHEMA: Final = {
    "M3_PROVIDER_ATTEMPT_EVENT_V1": "m3.provider-attempt-projection.v1",
    "M3_PROVIDER_ATTEMPT_EVENT_V2": "m3.provider-attempt-projection.v2",
}


class DeepSeekCalibrationError(ValueError):
    """Fail-closed M3-008B calibration contract error."""


@dataclass(frozen=True, slots=True)
class FrozenCalibrationCase:
    ordinal: int
    case_id: str
    category: str
    source: str
    citation_relationship: str
    semantic_request_hash: str
    stage1_admission_identity: str
    request: SemanticEvaluationRequest
    human_expected_state: SemanticSupport
    human_authority: str
    human_notes: str
    immutable_projection_hash: str


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    case: FrozenCalibrationCase
    assessment: DeepSeekSemanticAssessment | DeepSeekSemanticAssessmentV2


@dataclass(frozen=True, slots=True)
class RawProviderBodyBinding:
    relative_path: str
    content_hash: str
    byte_count: int


@final
class PendingCalibrationRun:
    """One absent append-only pending run created only after every preflight gate."""

    __slots__ = (
        "attempted_case_ids",
        "configuration",
        "output_root",
        "pending_root",
        "provider_attempt_authority",
        "raw_body_paths",
        "successful_case_ids",
    )
    attempted_case_ids: list[str]
    configuration: dict[str, object]
    output_root: Path
    pending_root: Path
    raw_body_paths: list[str]
    provider_attempt_authority: dict[str, object] | None
    successful_case_ids: list[str]

    def __init__(
        self,
        *,
        configuration: dict[str, object],
        output_root: Path,
        pending_root: Path,
    ) -> None:
        object.__setattr__(self, "configuration", configuration)
        object.__setattr__(self, "output_root", output_root)
        object.__setattr__(self, "pending_root", pending_root)
        object.__setattr__(self, "successful_case_ids", [])
        object.__setattr__(self, "attempted_case_ids", [])
        object.__setattr__(self, "raw_body_paths", [])
        object.__setattr__(self, "provider_attempt_authority", None)


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _require_exact_builtin_json(value: object, *, path: str = "$", depth: int = 0) -> None:
    if depth > _EXTERNAL_JSON_MAX_DEPTH:
        raise DeepSeekCalibrationError("external JSON nesting exceeds bound")
    value_type = type(value)
    if value is None or value_type in {bool, int}:
        return
    if value_type is str:
        cast(str, value).encode("utf-8", errors="strict")
        return
    if value_type is float:
        if not math.isfinite(cast(float, value)):
            raise DeepSeekCalibrationError("external JSON contains a non-finite number")
        return
    if value_type is list:
        for index, item in enumerate(cast(list[object], value)):
            _require_exact_builtin_json(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if value_type is dict:
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                raise DeepSeekCalibrationError("external JSON object key type is invalid")
            key.encode("utf-8", errors="strict")
            _require_exact_builtin_json(item, path=f"{path}.{key}", depth=depth + 1)
        return
    raise DeepSeekCalibrationError(f"external JSON value type is invalid at {path}")


def _reject_json_constant(_value: str) -> None:
    raise _NonFiniteJsonNumberError


def _admit_external_json_bytes(
    raw: bytes, *, label: str, maximum: int = _EXTERNAL_JSON_MAX_BYTES
) -> dict[str, object]:
    """Admit one exact canonical, bounded, built-in JSON object byte sequence."""

    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise DeepSeekCalibrationError(f"{label} bytes are invalid")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekCalibrationError(f"{label} JSON is invalid") from None
    if type(value) is not dict:
        raise DeepSeekCalibrationError(f"{label} root is invalid")
    try:
        _require_exact_builtin_json(value)
        canonical = _canonical_bytes(value)
    except DeepSeekCalibrationError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekCalibrationError(f"{label} JSON is invalid") from None
    if canonical != raw:
        raise DeepSeekCalibrationError(f"{label} bytes are not canonical")
    return cast(dict[str, object], value)


def _canonical_external_json_bytes(
    value: object, *, label: str, maximum: int = _EXTERNAL_JSON_MAX_BYTES
) -> bytes:
    """Serialize exact built-in JSON through the authoritative byte admission path."""

    try:
        _require_exact_builtin_json(value)
        raw = _canonical_bytes(value)
    except DeepSeekCalibrationError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekCalibrationError(f"{label} JSON is invalid") from None
    _admit_external_json_bytes(raw, label=label, maximum=maximum)
    return raw


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load_exact(path: Path, expected_sha256: str, maximum: int) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise DeepSeekCalibrationError("frozen packet path is invalid")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if not raw or len(raw) > maximum or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DeepSeekCalibrationError("frozen packet bytes do not match approved identity")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekCalibrationError("frozen packet JSON is invalid") from None
    if type(value) is not dict:
        raise DeepSeekCalibrationError("frozen packet root is invalid")
    return value


def load_frozen_calibration_cases(
    machine_packet_path: Path, resolution_packet_path: Path
) -> tuple[FrozenCalibrationCase, ...]:
    """Load and cross-bind the immutable provider-neutral cases and Owner labels."""

    machine = _load_exact(machine_packet_path, MACHINE_PACKET_SHA256, 1_000_000)
    resolution = _load_exact(resolution_packet_path, RESOLUTION_PACKET_SHA256, 100_000)
    frozen_packet = resolution.get("frozen_owner_adjudication_packet")
    if (
        machine.get("calibration_dataset_identity") != CALIBRATION_DATASET_IDENTITY
        or machine.get("case_count") != CASE_COUNT
        or machine.get("provider_called") is not False
        or machine.get("holdout_accessed") is not False
        or resolution.get("canonical_content_identity") != OWNER_RESOLUTION_IDENTITY
        or type(frozen_packet) is not dict
        or frozen_packet.get("calibration_dataset_identity") != CALIBRATION_DATASET_IDENTITY
        or resolution.get("case_count") != CASE_COUNT
        or resolution.get("provider_called") is not False
        or resolution.get("holdout_accessed") is not False
        or resolution.get("human_authority") != "project_owner"
    ):
        raise DeepSeekCalibrationError("frozen packet authority drift")
    machine_cases = machine.get("cases")
    resolution_cases = resolution.get("cases")
    ordered_ids = machine.get("ordered_case_ids")
    if (
        type(machine_cases) is not list
        or type(resolution_cases) is not list
        or type(ordered_ids) is not list
        or len(machine_cases) != CASE_COUNT
        or len(resolution_cases) != CASE_COUNT
        or resolution.get("ordered_case_ids") != ordered_ids
    ):
        raise DeepSeekCalibrationError("frozen case sequence drift")
    results: list[FrozenCalibrationCase] = []
    resolutions: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    relationships: Counter[str] = Counter()
    categories: set[str] = set()
    request_hashes: set[str] = set()
    admission_ids: set[str] = set()
    for index, (machine_case, owner_case) in enumerate(
        zip(machine_cases, resolution_cases, strict=True), start=1
    ):
        if type(machine_case) is not dict or type(owner_case) is not dict:
            raise DeepSeekCalibrationError("frozen case shape is invalid")
        case_id = f"M3-008B-CAL-{index:03d}"
        if (
            machine_case.get("ordinal") != index
            or owner_case.get("ordinal") != index
            or machine_case.get("case_id") != case_id
            or owner_case.get("case_id") != case_id
            or ordered_ids[index - 1] != case_id
        ):
            raise DeepSeekCalibrationError("frozen case order drift")
        projection = dict(machine_case)
        projection.pop("human_resolution", None)
        projection.pop("human_notes", None)
        immutable_hash = _sha256(_canonical_bytes(projection))
        fields = (
            "case_id",
            "ordinal",
            "category",
            "source",
            "citation_relationship",
            "semantic_request_hash",
            "stage1_admission_identity",
        )
        if (
            owner_case.get("immutable_projection_hash") != immutable_hash
            or any(owner_case.get(field) != machine_case.get(field) for field in fields)
            or owner_case.get("human_resolution") != owner_case.get("human_expected_state")
            or owner_case.get("human_authority") != "project_owner"
            or type(owner_case.get("human_notes")) is not str
            or not owner_case["human_notes"]
        ):
            raise DeepSeekCalibrationError("Owner resolution binding drift")
        state = _support(owner_case["human_expected_state"])
        request_document = machine_case.get("semantic_request")
        if type(request_document) is not dict:
            raise DeepSeekCalibrationError("semantic request document is invalid")
        request_bytes = _canonical_bytes(request_document)
        if _sha256(request_bytes) != machine_case.get("semantic_request_hash"):
            raise DeepSeekCalibrationError("semantic request hash drift")
        if (
            machine_case["semantic_request_hash"] in request_hashes
            or machine_case["stage1_admission_identity"] in admission_ids
        ):
            raise DeepSeekCalibrationError("duplicate frozen case identity")
        request_hashes.add(machine_case["semantic_request_hash"])
        admission_ids.add(machine_case["stage1_admission_identity"])
        try:
            request = parse_semantic_evaluation_request(request_bytes)
        except Exception:
            raise DeepSeekCalibrationError("semantic request canonical admission failed") from None
        if semantic_evaluation_request_bytes(
            request
        ) != request_bytes or request.stage1_admission.admission_hash != machine_case.get(
            "stage1_admission_identity"
        ):
            raise DeepSeekCalibrationError("semantic request Stage-1 binding drift")
        category_value = machine_case.get("category")
        source_value = machine_case.get("source")
        relationship_value = machine_case.get("citation_relationship")
        if any(
            type(value) is not str or not value
            for value in (category_value, source_value, relationship_value)
        ):
            raise DeepSeekCalibrationError("case classification is invalid")
        category = cast(str, category_value)
        source = cast(str, source_value)
        relationship = cast(str, relationship_value)
        categories.add(category)
        resolutions[state.value] += 1
        sources[source] += 1
        relationships[relationship] += 1
        results.append(
            FrozenCalibrationCase(
                ordinal=index,
                case_id=case_id,
                category=category,
                source=source,
                citation_relationship=relationship,
                semantic_request_hash=machine_case["semantic_request_hash"],
                stage1_admission_identity=machine_case["stage1_admission_identity"],
                request=request,
                human_expected_state=state,
                human_authority="project_owner",
                human_notes=owner_case["human_notes"],
                immutable_projection_hash=immutable_hash,
            )
        )
    if resolutions != {"supported": 12, "uncertain": 12, "unsupported": 12}:
        raise DeepSeekCalibrationError("human state counts drift")
    if sources != {"pubmed": 9, "dailymed": 9, "faers": 9, "cadec": 9}:
        raise DeepSeekCalibrationError("frozen source counts drift")
    if relationships != {"supports": 12, "contradicts": 12, "context_only": 12}:
        raise DeepSeekCalibrationError("frozen relationship counts drift")
    if len(categories) < 3:
        raise DeepSeekCalibrationError("frozen category coverage is invalid")
    frozen = tuple(results)
    if tuple(sorted(Counter(case.category for case in frozen).items())) != FROZEN_CATEGORY_COUNTS:
        raise DeepSeekCalibrationError("frozen category inventory drift")
    if _case_inventory_identity(frozen) != FROZEN_CASE_INVENTORY_IDENTITY:
        raise DeepSeekCalibrationError("frozen ordered case inventory drift")
    return frozen


def calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Return the exact active Attempt011 V2 semantic profile."""

    return _semantic_v2_calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_calibration_attempt="Attempt011",
        provider_configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        provider_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    )


def _semantic_v2_calibration_configuration(
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_calibration_attempt: str,
    provider_configuration_version: str,
    provider_configuration_hash: str,
) -> dict[str, object]:
    """Build one exact semantic-family calibration profile from explicit provider authority."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    if provider_calibration_attempt not in {
        "Attempt007",
        "Attempt008",
        "Attempt009",
        "Attempt010",
        "Attempt011",
    }:
        raise DeepSeekCalibrationError("provider calibration attempt is invalid")
    return {
        "provider": "DeepSeek API",
        "provider_calibration_attempt": provider_calibration_attempt,
        "semantic_contract": "M3_STAGE2_SEMANTIC_RESULT_V2",
        "semantic_contract_version": SEMANTIC_EVALUATION_V2_CONTRACT_VERSION,
        "semantic_contract_hash": SEMANTIC_EVALUATION_V2_CONTRACT_HASH,
        "calibration_prompt_rubric_version": 1,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": provider_configuration_version,
        "configuration_hash": provider_configuration_hash,
        "semantic_configuration_hash": SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH,
        "wire_contract_version": SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_VERSION,
        "wire_contract_identity": SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
        "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_V2_PROMPT_VERSION,
        "prompt_hash": SEMANTIC_EVALUATION_V2_PROMPT_HASH,
        "rubric_version": SEMANTIC_EVALUATION_V2_RUBRIC_VERSION,
        "rubric_hash": SEMANTIC_EVALUATION_V2_RUBRIC_HASH,
        "schema_version": SEMANTIC_EVALUATION_V2_SCHEMA_VERSION,
        "schema_hash": SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
        "routing_matrix_hash": SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH,
        "routing_matrix_row_count": SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_ROW_COUNT,
        "routing_policy_hash": REVIEW_ROUTING_POLICY_HASH,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def historical_attempt007_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt007 without consulting the active Attempt011 profile."""

    return _semantic_v2_calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_calibration_attempt="Attempt007",
        provider_configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_V1,
        provider_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1,
    )


def historical_attempt008_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt008 without consulting the active Attempt011 label."""

    return _semantic_v2_calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_calibration_attempt="Attempt008",
        provider_configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        provider_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    )


def historical_attempt009_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt009 without consulting active Attempt011 authority."""

    return _semantic_v2_calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_calibration_attempt="Attempt009",
        provider_configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        provider_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    )


def historical_attempt010_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt010 without consulting active Attempt011 authority."""

    return _semantic_v2_calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_calibration_attempt="Attempt010",
        provider_configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION,
        provider_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    )


def historical_attempt004_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct the immutable Attempt004 configuration under its exact V2 profile."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    return {
        "provider": "DeepSeek API",
        "provider_calibration_attempt": "Attempt004",
        "calibration_prompt_rubric_version": 1,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V2,
        "configuration_hash": DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V2,
        "wire_contract_identity": DEEPSEEK_RESPONSE_WIRE_CONTRACT_IDENTITY_V2,
        "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_PROMPT_VERSION,
        "prompt_hash": SEMANTIC_EVALUATION_PROMPT_HASH,
        "rubric_version": SEMANTIC_EVALUATION_RUBRIC_VERSION,
        "rubric_hash": SEMANTIC_EVALUATION_RUBRIC_HASH,
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "schema_hash": SEMANTIC_EVALUATION_SCHEMA_HASH,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def historical_attempt005_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt005 under its exact V3 prompt/rubric profile."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    return {
        "provider": "DeepSeek API",
        "provider_calibration_attempt": "Attempt005",
        "calibration_prompt_rubric_version": 2,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V3,
        "configuration_hash": DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
        "wire_contract_identity": DEEPSEEK_RESPONSE_WIRE_CONTRACT_IDENTITY_V2,
        "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_PROMPT_VERSION_V2,
        "prompt_hash": SEMANTIC_EVALUATION_PROMPT_HASH_V2,
        "rubric_version": SEMANTIC_EVALUATION_RUBRIC_VERSION_V2,
        "rubric_hash": SEMANTIC_EVALUATION_RUBRIC_HASH_V2,
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION_V2,
        "schema_hash": SEMANTIC_EVALUATION_SCHEMA_HASH_V2,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def historical_attempt006_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct immutable Attempt006 configuration without active-profile reuse."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    return {
        "provider": "DeepSeek API",
        "provider_calibration_attempt": "Attempt006",
        "calibration_prompt_rubric_version": 3,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION_V4,
        "configuration_hash": DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V4,
        "wire_contract_identity": DEEPSEEK_RESPONSE_WIRE_CONTRACT_IDENTITY_V2,
        "framing_contract_identity": FRAMING_CONTRACT_IDENTITY,
        "approved_header_names_identity": APPROVED_HEADER_NAMES_IDENTITY,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_PROMPT_VERSION_V3,
        "prompt_hash": SEMANTIC_EVALUATION_PROMPT_HASH_V3,
        "rubric_version": SEMANTIC_EVALUATION_RUBRIC_VERSION_V3,
        "rubric_hash": SEMANTIC_EVALUATION_RUBRIC_HASH_V3,
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION_V2,
        "schema_hash": SEMANTIC_EVALUATION_SCHEMA_HASH_V2,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def historical_attempt006_failure_classification() -> dict[str, object]:
    """Return the frozen truthful classification without reinterpreting provider output."""

    return {
        "classification": HISTORICAL_ATTEMPT006_CLASSIFICATION,
        "attempted_case_count": 6,
        "successful_case_ids": [f"M3-008B-CAL-{index:03d}" for index in range(1, 6)],
        "failed_case_id": "M3-008B-CAL-006",
        "provider_output_valid": True,
        "application_policy_binding_failed": True,
        "application_error_code": "human_review_binding_invalid",
        "projection_hash": HISTORICAL_ATTEMPT006_PROJECTION_HASH,
        "status_binding_hash": HISTORICAL_ATTEMPT006_STATUS_BINDING_HASH,
    }


def classify_historical_attempt006_application_binding(
    request: SemanticEvaluationRequest, raw_response: bytes
) -> str:
    """Replay V4 parsing and classify only the frozen application-binding failure."""

    candidate, _response_id_value, _usage_value, _structured = parse_deepseek_completed_response_v4(
        raw_response
    )
    try:
        build_deepseek_semantic_evaluation_result_v4(request, candidate)
    except SemanticEvaluationContractError as error:
        if str(error) == "human_review_binding_invalid":
            return HISTORICAL_ATTEMPT006_CLASSIFICATION
        raise DeepSeekCalibrationError("Attempt006 replay failed for a different reason") from None
    raise DeepSeekCalibrationError("Attempt006 replay did not reproduce application failure")


def historical_v1_calibration_configuration(
    *, code_revision: str, implementation_manifest_hash: str
) -> dict[str, object]:
    """Reconstruct the immutable Attempts001-003 configuration without V2 facts."""

    _code_revision(code_revision)
    _digest(implementation_manifest_hash, "implementation manifest")
    return {
        "provider": "DeepSeek API",
        "calibration_prompt_rubric_version": 1,
        "maximum_development_versions": 3,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "evaluator_method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "configuration_version": DEEPSEEK_SEMANTIC_EVALUATION_CONFIG_VERSION,
        "configuration_hash": DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
        "prompt_version": SEMANTIC_EVALUATION_PROMPT_VERSION,
        "prompt_hash": SEMANTIC_EVALUATION_PROMPT_HASH,
        "rubric_version": SEMANTIC_EVALUATION_RUBRIC_VERSION,
        "rubric_hash": SEMANTIC_EVALUATION_RUBRIC_HASH,
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "schema_hash": SEMANTIC_EVALUATION_SCHEMA_HASH,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
        "provider_contract_url": "https://api-docs.deepseek.com/guides/responses_api",
        "provider_privacy_policy_url": (
            "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"
        ),
        "provider_policy_review_date": "2026-08-30",
        "provider_state_model": "stateless_response_and_conversation_state",
        "operational_privacy_retention_distinct": True,
        "public_research_data_only": True,
        "calibration_dataset_identity": CALIBRATION_DATASET_IDENTITY,
        "human_resolution_identity": OWNER_RESOLUTION_IDENTITY,
        "case_inventory_identity": FROZEN_CASE_INVENTORY_IDENTITY,
        "frozen_category_counts": dict(FROZEN_CATEGORY_COUNTS),
        "code_revision": code_revision,
        "implementation_manifest_hash": implementation_manifest_hash,
    }


def provider_attempt_run_id(configuration: Mapping[str, object]) -> str:
    """Bind one durable provider run to the exact frozen calibration configuration."""

    return (
        "provider-attempt-run:sha256:"
        + hashlib.sha256(_canonical_bytes(dict(configuration))).hexdigest()
    )


def persist_safe_raw_body(
    run: PendingCalibrationRun,
    case: FrozenCalibrationCase,
    attempt_ordinal: int,
    observation: DeepSeekOneOperationObservation,
    *,
    provider_run_id: str,
) -> RawProviderBodyBinding | None:
    """Persist only credential-clean, complete, within-cap raw bytes before validation."""

    _validate_pending_run(run)
    try:
        normalized_headers = normalize_approved_headers(
            observation.response_header_items,
            raw_header_field_count=observation.response_header_field_count,
        )
    except (TypeError, ValueError):
        return None
    if not raw_body_persistence_permitted(normalized_headers):
        return None
    if observation.credential_echo or observation.raw_body is None:
        return None
    raw = observation.raw_body
    if not observation.body_complete or len(raw) > 131_072:
        return None
    name = f"case-{case.ordinal:03d}-attempt-{attempt_ordinal:03d}-raw.bin"
    run_digest = provider_run_id.removeprefix("provider-attempt-run:sha256:")
    relative = f"provider-attempt-raw/{run_digest}/{name}"
    store = run.output_root.parent / "provider-attempt-raw" / run_digest
    _validate_external_ancestry(run.output_root.parent, store)
    store.mkdir(parents=True, exist_ok=True)
    _validate_external_ancestry(run.output_root.parent, store)
    path = store / name
    _write_new_bytes(path, raw)
    digest = _sha256(raw)
    return RawProviderBodyBinding(relative, digest, len(raw))


def validate_authoritative_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind active Attempt011 events to the exact V2 provider authority."""

    if expected_provider_run_id in _HISTORICAL_PROVIDER_RUN_IDS:
        raise DeepSeekCalibrationError("historical provider run requires its immutable verifier")

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_bytes_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def validate_historical_attempt006_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt006 rows to their original V4 request/result authority."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V4,
        request_bytes_builder=deepseek_provider_request_bytes,
    )


def validate_historical_attempt007_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt007 rows to provider profile V1 and unchanged request bytes."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1,
        request_bytes_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def validate_historical_attempt008_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt008 rows to provider profile V2 and unchanged request bytes."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_bytes_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def validate_historical_attempt009_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt009 rows without consulting active Attempt011 identity."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_bytes_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def validate_historical_attempt010_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt010 rows independently of the active run."""

    if expected_provider_run_id != HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID:
        raise DeepSeekCalibrationError("expected Attempt010 immutable identity drift")

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_bytes_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def validate_historical_attempt004_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt004 events to the exact historical V2 authority."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V2,
        request_bytes_builder=deepseek_provider_request_v2_bytes,
    )


def validate_historical_attempt005_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Bind immutable Attempt005 events to the exact historical V3 authority."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
        request_bytes_builder=deepseek_provider_request_v3_bytes,
    )


def validate_historical_v1_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> tuple[ProviderAttemptEvent, ...]:
    """Reconstruct immutable V1 ledger events without introducing V2 facts."""

    return _validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
        expected_configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_bytes_builder=deepseek_provider_request_v2_bytes,
    )


def _validate_authoritative_provider_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    expected_schema_version: str,
    expected_configuration_hash: str,
    request_bytes_builder: Callable[[SemanticEvaluationRequest], bytes],
) -> tuple[ProviderAttemptEvent, ...]:

    ordered = tuple(events)
    validated_events: list[ProviderAttemptEvent] = []
    cases = {case.ordinal: case for case in frozen_cases}
    if len(cases) != len(tuple(frozen_cases)):
        raise DeepSeekCalibrationError("frozen case inventory contains duplicate ordinals")
    for event in ordered:
        try:
            event = validate_provider_attempt_event(event)
        except ValueError:
            raise DeepSeekCalibrationError("provider event canonical validation failed") from None
        validated_events.append(event)
    canonical_events = tuple(validated_events)
    starts_by_id = {item.event_id: item for item in canonical_events if item.event_kind == "START"}
    for event in canonical_events:
        case = cases.get(event.case_ordinal)
        if (
            event.provider_run_id != expected_provider_run_id
            or event.schema_version != expected_schema_version
            or event.configuration_hash != expected_configuration_hash
            or case is None
            or event.case_id != case.case_id
        ):
            raise DeepSeekCalibrationError("provider event differs from frozen authority")
        expected_request_hash = _sha256(request_bytes_builder(case.request))
        if event.request_hash != expected_request_hash:
            raise DeepSeekCalibrationError("provider event request differs from frozen case")
        if event.event_kind != "START":
            start = starts_by_id.get(cast(str, event.start_event_id))
            if (
                start is None
                or start.case_ordinal != event.case_ordinal
                or start.attempt_ordinal != event.attempt_ordinal
            ):
                raise DeepSeekCalibrationError("provider closure lacks frozen START authority")
    return canonical_events


def provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    ordered = validate_authoritative_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt004_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt004 V2 rows under their original exact profile."""

    ordered = validate_historical_attempt004_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt005_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt005 V3 rows under their original exact profile."""

    ordered = validate_historical_attempt005_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt006_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt006 rows without consulting Attempt007 authority."""

    ordered = validate_historical_attempt006_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt007_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt007 rows only through historical profile V1 authority."""

    ordered = validate_historical_attempt007_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt008_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt008 independently from the active Attempt011 label."""

    ordered = validate_historical_attempt008_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt009_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt009 independently from active Attempt011 authority."""

    ordered = validate_historical_attempt009_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_attempt010_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable Attempt010 independently from active Attempt011."""

    ordered = validate_historical_attempt010_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def historical_v1_provider_event_projection(
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path | None = None,
) -> dict[str, object]:
    """Project immutable V1 rows under their original schema and identities."""

    ordered = validate_historical_v1_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return _project_validated_events(
        ordered,
        raw_root=raw_root,
        event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
    )


def _project_validated_events(
    events: Sequence[ProviderAttemptEvent],
    *,
    raw_root: Path | None = None,
    event_schema_version: str,
) -> dict[str, object]:
    """Build the external projection strictly from authoritative ordered ledger events."""

    ordered = tuple(events)
    row_fields = _PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA[event_schema_version]
    projection_schema_version = _PROJECTION_SCHEMA_BY_EVENT_SCHEMA[event_schema_version]
    if any(event.schema_version != event_schema_version for event in ordered):
        raise DeepSeekCalibrationError("provider projection event schema drift")
    if (
        tuple(
            sorted(
                ordered, key=lambda item: (item.case_ordinal, item.attempt_ordinal, item.event_slot)
            )
        )
        != ordered
    ):
        raise DeepSeekCalibrationError("provider ledger event order drift")
    for event in ordered:
        if event.body_relative_path is None:
            continue
        if raw_root is None:
            raise DeepSeekCalibrationError("raw root is required for bound provider body")
        _read_ledger_bound_provider_body(
            raw_root,
            event,
            missing_message="ledger-bound raw provider body is missing",
            drift_message="ledger-bound raw provider body differs",
        )
    rows = [
        {
            name: (
                value.isoformat()
                if isinstance(value, datetime)
                else list(value)
                if isinstance(value, tuple)
                else value
            )
            for name in row_fields
            for value in (getattr(event, name),)
        }
        for event in ordered
    ]
    starts = [item for item in ordered if item.event_kind == "START"]
    terminal = [item for item in ordered if item.event_kind in {"TERMINAL", "RECOVERY"}]
    start_by_key = {(item.case_ordinal, item.attempt_ordinal): item for item in starts}
    closure_keys: set[tuple[int, int]] = set()
    for closure in terminal:
        key = (closure.case_ordinal, closure.attempt_ordinal)
        start = start_by_key.get(key)
        if (
            start is None
            or key in closure_keys
            or closure.start_event_id != start.event_id
            or closure.configuration_hash != start.configuration_hash
            or closure.request_hash != start.request_hash
        ):
            raise DeepSeekCalibrationError("provider ledger closure topology drift")
        closure_keys.add(key)
    terminal_keys = {(item.case_ordinal, item.attempt_ordinal) for item in terminal}
    orphan = any((item.case_ordinal, item.attempt_ordinal) not in terminal_keys for item in starts)
    case_ordinals = sorted({item.case_ordinal for item in starts})
    final_successes: set[int] = set()
    for case_ordinal in case_ordinals:
        case_starts = [item for item in starts if item.case_ordinal == case_ordinal]
        ordinals = [item.attempt_ordinal for item in case_starts]
        if ordinals != list(range(1, len(ordinals) + 1)) or len(ordinals) > 3:
            raise DeepSeekCalibrationError("provider ledger attempt ordinals are discontinuous")
        case_closures = {
            item.attempt_ordinal: item for item in terminal if item.case_ordinal == case_ordinal
        }
        for attempt in ordinals[:-1]:
            attempt_closure = case_closures.get(attempt)
            if attempt_closure is None or attempt_closure.disposition not in {
                "retryable_status",
                "transport_unavailable",
            }:
                raise DeepSeekCalibrationError("provider ledger retry transition is illegal")
        if ordinals and ordinals[-1] in case_closures:
            final = case_closures[ordinals[-1]]
            if final.disposition == "success":
                if (
                    final.body_complete is not True
                    or final.body_hash is None
                    or final.body_relative_path is None
                    or final.body_byte_count is None
                ):
                    raise DeepSeekCalibrationError(
                        "successful provider closure lacks exact raw binding"
                    )
                final_successes.add(case_ordinal)
        if any(attempt not in ordinals for attempt in case_closures):
            raise DeepSeekCalibrationError("provider ledger closure has no START ordinal")
    all_cases_complete = (
        case_ordinals == list(range(1, CASE_COUNT + 1))
        and final_successes == set(range(1, CASE_COUNT + 1))
        and not orphan
    )
    semantic = {
        "schema_version": projection_schema_version,
        "event_count": len(ordered),
        "attempt_count": len(starts),
        "status": (
            "EMPTY"
            if not ordered
            else "NONFINAL"
            if starts and not terminal
            else "INTERRUPTED"
            if orphan or any(item.event_kind == "RECOVERY" for item in ordered)
            else "FAILED"
            if not all_cases_complete
            else "COMPLETE"
        ),
        "events": rows,
    }
    return {**semantic, "projection_hash": _sha256(_canonical_bytes(semantic))}


def validate_provider_event_projection(
    projection: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    expected_event_schema_version: str | None = None,
    raw_root: Path | None = None,
) -> None:
    """Reject caller-recomputed projections that differ from authoritative ledger truth."""

    validated_events: list[ProviderAttemptEvent] = []
    for event in events:
        try:
            validated_event = validate_provider_attempt_event(event)
        except ValueError:
            raise DeepSeekCalibrationError("provider event canonical validation failed") from None
        validated_events.append(validated_event)
    canonical_events = tuple(validated_events)
    event_schema_versions = {event.schema_version for event in canonical_events}
    if expected_event_schema_version is not None and (
        type(expected_event_schema_version) is not str
        or expected_event_schema_version not in _PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA
    ):
        raise DeepSeekCalibrationError("expected provider event schema authority is invalid")
    if not event_schema_versions:
        if expected_event_schema_version is None:
            raise DeepSeekCalibrationError(
                "empty provider projection requires expected event schema authority"
            )
        authoritative_event_schema_version = expected_event_schema_version
    elif len(event_schema_versions) != 1:
        raise DeepSeekCalibrationError("provider projection event schema drift")
    else:
        observed_event_schema_version = next(iter(event_schema_versions))
        if (
            expected_event_schema_version is not None
            and observed_event_schema_version != expected_event_schema_version
        ):
            raise DeepSeekCalibrationError("provider projection event schema authority mismatch")
        authoritative_event_schema_version = (
            expected_event_schema_version or observed_event_schema_version
        )
    if authoritative_event_schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2":
        expected = provider_event_projection(
            canonical_events,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
            raw_root=raw_root,
        )
    elif authoritative_event_schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        expected = historical_v1_provider_event_projection(
            canonical_events,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
            raw_root=raw_root,
        )
    else:
        raise DeepSeekCalibrationError("provider projection event schema drift")
    observed_bytes = _canonical_external_json_bytes(
        projection, label="external provider-attempt projection"
    )
    expected_bytes = _canonical_external_json_bytes(
        expected, label="authoritative provider-attempt projection"
    )
    if observed_bytes != expected_bytes:
        raise DeepSeekCalibrationError("external provider-attempt projection differs from ledger")


def expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
    artifact: Mapping[str, object] | None,
    artifact_bytes: bytes | None,
) -> dict[str, object]:
    """Build the sole closed run-status object from configuration, ledger, and artifact."""

    projection = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=artifact,
        artifact_bytes=artifact_bytes,
    )


def historical_attempt004_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct the failed Attempt004 status from immutable V2 authority."""

    projection = historical_attempt004_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt005_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct the failed Attempt005 status from immutable V3 authority."""

    projection = historical_attempt005_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt006_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct immutable failed Attempt006 status from exact historical authority."""

    projection = historical_attempt006_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt007_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct immutable failed Attempt007 status from historical ledger authority."""

    projection = historical_attempt007_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt008_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct immutable failed Attempt008 status from its exact ledger authority."""

    projection = historical_attempt008_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt009_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct immutable failed Attempt009 status from exact historical authority."""

    projection = historical_attempt009_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def historical_attempt010_expected_run_status(
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    raw_root: Path,
) -> dict[str, object]:
    """Reconstruct immutable failed Attempt010 status from historical authority."""

    projection = historical_attempt010_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=raw_root,
    )
    return _expected_run_status_from_projection(
        projection,
        configuration=configuration,
        events=events,
        artifact=None,
        artifact_bytes=None,
    )


def _expected_run_status_from_projection(
    projection: Mapping[str, object],
    *,
    configuration: Mapping[str, object],
    events: Sequence[ProviderAttemptEvent],
    artifact: Mapping[str, object] | None,
    artifact_bytes: bytes | None,
) -> dict[str, object]:
    starts = [item for item in events if item.event_kind == "START"]
    closures = [item for item in events if item.event_kind in {"TERMINAL", "RECOVERY"}]
    attempted_ids = tuple(
        f"M3-008B-CAL-{ordinal:03d}" for ordinal in sorted({item.case_ordinal for item in starts})
    )
    successful_ids = tuple(
        f"M3-008B-CAL-{ordinal:03d}"
        for ordinal in sorted(
            {
                item.case_ordinal
                for item in closures
                if item.event_kind == "TERMINAL" and item.disposition == "success"
            }
        )
    )
    artifact_present = artifact is not None and artifact_bytes is not None
    metrics = artifact.get("metrics") if artifact is not None else None
    metrics_accepted = type(metrics) is dict and metrics.get("accepted") is True
    accepted = projection["status"] == "COMPLETE" and artifact_present and metrics_accepted
    status = (
        "PASS"
        if accepted
        else "INTERRUPTED"
        if projection["status"] in {"INTERRUPTED", "NONFINAL"}
        else "FAILED"
    )
    authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    semantic = {
        "schema_version": "m3.stage2.deepseek-run-status.v3",
        "status": status,
        "accepted": accepted,
        "calibration_artifact_present": artifact_present,
        "artifact_sha256": _sha256(artifact_bytes) if artifact_bytes is not None else None,
        "artifact_sidecar_present": artifact_present,
        "provider_attempt_authority": authority,
        "configuration_binding_hash": _sha256(_canonical_bytes(dict(configuration))),
        "total_http_attempts": len(starts),
        "attempted_case_count": len(attempted_ids),
        "attempted_case_ids": list(attempted_ids),
        "successful_case_count": len(successful_ids),
        "successful_case_ids": list(successful_ids),
    }
    return {**semantic, "status_binding_hash": _sha256(_canonical_bytes(semantic))}


def verify_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify the whole external run only from independent expected inputs and ledger."""

    expected_configuration = calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(expected_configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    expected = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    projection, _projection_raw = _load_external_json(
        output_root / "provider-attempt-projection.json"
    )
    validate_provider_event_projection(
        projection,
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        raw_root=output_root.parent,
    )
    run_configuration, _configuration_raw = _load_external_json(
        output_root / "run-configuration.json"
    )
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": expected_configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(expected_configuration)),
    }
    if _canonical_external_json_bytes(
        run_configuration, label="external run configuration"
    ) != _canonical_external_json_bytes(
        expected_run_configuration, label="authoritative run configuration"
    ):
        raise DeepSeekCalibrationError("external run configuration differs")
    artifact_path = output_root / "m3-008b-deepseek-calibration.json"
    artifact: dict[str, object] | None = None
    artifact_raw: bytes | None = None
    if artifact_path.exists():
        artifact, artifact_raw = _load_external_json(artifact_path)
        validate_calibration_artifact(
            artifact,
            code_revision=expected_code_revision,
            implementation_manifest_hash=expected_implementation_manifest_hash,
            provider_attempt_events=events,
            provider_raw_root=output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        sidecar = output_root / "m3-008b-deepseek-calibration.json.sha256"
        expected_sidecar = (
            f"{hashlib.sha256(artifact_raw).hexdigest()}  m3-008b-deepseek-calibration.json\n"
        ).encode("ascii")
        if not sidecar.is_file() or sidecar.read_bytes() != expected_sidecar:
            raise DeepSeekCalibrationError("external artifact/status binding drift")
    status, _status_raw = _load_external_json(output_root / "run-status.json")
    expected_status = expected_run_status(
        configuration=expected_configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
        artifact=artifact,
        artifact_bytes=artifact_raw,
    )
    if status != expected_status:
        raise DeepSeekCalibrationError("external run status differs from ledger")
    cases_by_id = {case.case_id: case for case in frozen_cases}
    for case_id in cast(list[str], status["successful_case_ids"]):
        case = cases_by_id.get(case_id)
        if case is None:
            raise DeepSeekCalibrationError("external successful case is not frozen")
        observed_case, _case_raw = _load_external_json(
            output_root / f"case-{case.ordinal:03d}-evidence.json"
        )
        expected_case = canonical_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if observed_case != expected_case:
            raise DeepSeekCalibrationError("external case evidence differs from ledger")
    expected_names = {
        "run-configuration.json",
        "run-status.json",
        "provider-attempt-projection.json",
    } | {
        f"case-{ordinal:03d}-evidence.json"
        for ordinal in range(1, cast(int, status["successful_case_count"]) + 1)
    }
    if artifact is not None:
        expected_names |= {
            "m3-008b-deepseek-calibration.json",
            "m3-008b-deepseek-calibration.json.sha256",
        }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external run file inventory differs")
    return expected


def verify_historical_attempt004_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt004 without consulting active Attempt005 bytes."""

    expected_configuration = historical_attempt004_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(expected_configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt004 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    expected = historical_attempt004_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    projection, _ = _load_external_json(output_root / "provider-attempt-projection.json")
    if _canonical_external_json_bytes(
        projection, label="external Attempt004 projection"
    ) != _canonical_external_json_bytes(expected, label="authoritative Attempt004 projection"):
        raise DeepSeekCalibrationError("external Attempt004 projection differs from ledger")
    run_configuration, _ = _load_external_json(output_root / "run-configuration.json")
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": expected_configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(expected_configuration)),
    }
    if _canonical_external_json_bytes(
        run_configuration, label="external Attempt004 run configuration"
    ) != _canonical_external_json_bytes(
        expected_run_configuration, label="authoritative Attempt004 run configuration"
    ):
        raise DeepSeekCalibrationError("external Attempt004 run configuration differs")
    status, _ = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt004_expected_run_status(
        configuration=expected_configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if status != expected_status:
        raise DeepSeekCalibrationError("external Attempt004 status differs from ledger")
    cases_by_id = {case.case_id: case for case in frozen_cases}
    for case_id in cast(list[str], status["successful_case_ids"]):
        case = cases_by_id.get(case_id)
        if case is None:
            raise DeepSeekCalibrationError("external Attempt004 successful case is not frozen")
        observed_case, _ = _load_external_json(
            output_root / f"case-{case.ordinal:03d}-evidence.json"
        )
        expected_case = historical_attempt004_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if observed_case != expected_case:
            raise DeepSeekCalibrationError("external Attempt004 case evidence differs from ledger")
    expected_names = {
        "run-configuration.json",
        "run-status.json",
        "provider-attempt-projection.json",
    } | {
        f"case-{ordinal:03d}-evidence.json"
        for ordinal in range(1, cast(int, status["successful_case_count"]) + 1)
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt004 file inventory differs")
    return expected


def verify_historical_attempt005_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt005 without consulting active Attempt006 bytes."""

    if expected_provider_run_id != HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID:
        raise DeepSeekCalibrationError("expected Attempt005 provider run identity drift")
    expected_configuration = historical_attempt005_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    historical_request = deepseek_provider_request_v3_bytes(frozen_cases[0].request)
    if (
        expected_configuration["configuration_hash"]
        != DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3
        or len(historical_request) != HISTORICAL_ATTEMPT005_CASE1_REQUEST_BYTES
        or _sha256(historical_request) != HISTORICAL_ATTEMPT005_CASE1_REQUEST_HASH
    ):
        raise DeepSeekCalibrationError("immutable Attempt005 request authority drift")
    if provider_attempt_run_id(expected_configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt005 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    if (
        len(events) != 2
        or events[0].event_kind != "START"
        or events[0].case_ordinal != 1
        or events[0].attempt_ordinal != 1
        or events[0].request_hash != HISTORICAL_ATTEMPT005_CASE1_REQUEST_HASH
        or events[1].event_kind != "TERMINAL"
        or events[1].start_event_id != events[0].event_id
        or events[1].disposition != "candidate_invalid"
        or events[1].body_byte_count != HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_BYTES
        or events[1].body_hash != HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_HASH
    ):
        raise DeepSeekCalibrationError("immutable Attempt005 ledger facts drift")
    expected = historical_attempt005_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if expected["projection_hash"] != HISTORICAL_ATTEMPT005_PROJECTION_HASH:
        raise DeepSeekCalibrationError("immutable Attempt005 projection identity drift")
    projection, _ = _load_external_json(output_root / "provider-attempt-projection.json")
    if _canonical_external_json_bytes(
        projection, label="external Attempt005 projection"
    ) != _canonical_external_json_bytes(expected, label="authoritative Attempt005 projection"):
        raise DeepSeekCalibrationError("external Attempt005 projection differs from ledger")
    run_configuration, _ = _load_external_json(output_root / "run-configuration.json")
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": expected_configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(expected_configuration)),
    }
    if _canonical_external_json_bytes(
        run_configuration, label="external Attempt005 run configuration"
    ) != _canonical_external_json_bytes(
        expected_run_configuration, label="authoritative Attempt005 run configuration"
    ):
        raise DeepSeekCalibrationError("external Attempt005 run configuration differs")
    status, _ = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt005_expected_run_status(
        configuration=expected_configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if expected_status["status_binding_hash"] != HISTORICAL_ATTEMPT005_STATUS_BINDING_HASH:
        raise DeepSeekCalibrationError("immutable Attempt005 status identity drift")
    if status != expected_status:
        raise DeepSeekCalibrationError("external Attempt005 status differs from ledger")
    cases_by_id = {case.case_id: case for case in frozen_cases}
    for case_id in cast(list[str], status["successful_case_ids"]):
        case = cases_by_id.get(case_id)
        if case is None:
            raise DeepSeekCalibrationError("external Attempt005 successful case is not frozen")
        observed_case, _ = _load_external_json(
            output_root / f"case-{case.ordinal:03d}-evidence.json"
        )
        expected_case = historical_attempt005_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if observed_case != expected_case:
            raise DeepSeekCalibrationError("external Attempt005 case evidence differs from ledger")
    expected_names = {
        "run-configuration.json",
        "run-status.json",
        "provider-attempt-projection.json",
    } | {
        f"case-{ordinal:03d}-evidence.json"
        for ordinal in range(1, cast(int, status["successful_case_count"]) + 1)
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt005 file inventory differs")
    return expected


def verify_historical_attempt007_case_evidence(
    case: FrozenCalibrationCase,
    document: Mapping[str, object],
    document_raw: bytes,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Verify one immutable Attempt007 success without current result-profile authority."""

    validate_historical_attempt007_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    if not 1 <= case.ordinal <= len(HISTORICAL_ATTEMPT007_CASE_FILE_HASHES):
        raise DeepSeekCalibrationError("historical Attempt007 case ordinal is invalid")
    if _sha256(document_raw) != HISTORICAL_ATTEMPT007_CASE_FILE_HASHES[case.ordinal - 1]:
        raise DeepSeekCalibrationError("immutable Attempt007 case file identity drift")
    admitted = _admit_external_json_bytes(document_raw, label="Attempt007 case evidence")
    if dict(document) != admitted:
        raise DeepSeekCalibrationError("Attempt007 case document differs from exact bytes")
    if (
        document.get("schema_version") != "m3.stage2.deepseek-case-evidence.v3"
        or document.get("ordinal") != case.ordinal
        or type(document.get("evidence")) is not dict
    ):
        raise DeepSeekCalibrationError("Attempt007 case evidence shape drift")
    evidence = cast(dict[str, object], document["evidence"])
    if document.get("evidence_binding_hash") != _sha256(_canonical_bytes(evidence)):
        raise DeepSeekCalibrationError("Attempt007 case evidence binding drift")
    successes = [
        event
        for event in events
        if event.case_ordinal == case.ordinal
        and event.event_kind == "TERMINAL"
        and event.disposition == "success"
    ]
    if len(successes) != 1 or successes[0].body_relative_path is None:
        raise DeepSeekCalibrationError("Attempt007 case lacks one successful closure")
    terminal = successes[0]
    raw_response = _read_ledger_bound_provider_body(
        raw_root,
        terminal,
        missing_message="Attempt007 case raw response path is invalid",
        drift_message="Attempt007 case raw response differs from ledger",
    )
    candidate, response_id, usage, structured = parse_deepseek_completed_response_semantic_v2(
        raw_response
    )
    request_bytes = deepseek_provider_request_semantic_v2_bytes(case.request)
    semantic_request = semantic_evaluation_request_bytes(case.request)
    if (
        evidence.get("case_id") != case.case_id
        or evidence.get("semantic_request_hash") != _sha256(semantic_request)
        or evidence.get("semantic_request_hex") != semantic_request.hex()
        or evidence.get("provider_request_hash") != _sha256(request_bytes)
        or evidence.get("raw_provider_request_hex") != request_bytes.hex()
        or evidence.get("provider_response_hash") != _sha256(raw_response)
        or evidence.get("raw_provider_response_hex") != raw_response.hex()
        or evidence.get("provider_response_id") != response_id
        or evidence.get("structured_output_hash") != _sha256(structured)
        or evidence.get("structured_output_hex") != structured.hex()
        or evidence.get("provider_result") != candidate.result.value
        or evidence.get("usage") != BaseModel.model_dump(usage, mode="json")
        or evidence.get("provider_configuration_version")
        != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_V1
        or evidence.get("provider_configuration_hash")
        != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1
    ):
        raise DeepSeekCalibrationError("Attempt007 case evidence differs from immutable authority")


def verify_historical_attempt007_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt007 separately from active Attempt011 authority."""

    if (
        expected_provider_run_id != HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID
        or expected_implementation_manifest_hash != HISTORICAL_ATTEMPT007_MANIFEST_HASH
    ):
        raise DeepSeekCalibrationError("expected Attempt007 immutable identity drift")
    configuration = historical_attempt007_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt007 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    if len(events) != 10:
        raise DeepSeekCalibrationError("immutable Attempt007 event count drift")
    projection = historical_attempt007_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        projection.get("projection_hash") != HISTORICAL_ATTEMPT007_PROJECTION_HASH
        or projection.get("event_count") != 10
        or projection.get("attempt_count") != 5
        or projection.get("status") != "FAILED"
    ):
        raise DeepSeekCalibrationError("immutable Attempt007 projection facts drift")
    observed_projection, observed_projection_raw = _load_external_json(
        output_root / "provider-attempt-projection.json"
    )
    if observed_projection != projection or _sha256(observed_projection_raw) != (
        "sha256:9f81632a55aadee919aefe39a4304535e0812fb1da5acdfc633d2051f973f8d0"
    ):
        raise DeepSeekCalibrationError("external Attempt007 projection differs")
    run_configuration, run_configuration_raw = _load_external_json(
        output_root / "run-configuration.json"
    )
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
    }
    if (
        run_configuration != expected_run_configuration
        or _sha256(run_configuration_raw) != HISTORICAL_ATTEMPT007_CONFIGURATION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt007 configuration differs")
    status, _status_raw = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt007_expected_run_status(
        configuration=configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        status != expected_status
        or status.get("status_binding_hash") != HISTORICAL_ATTEMPT007_STATUS_BINDING_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt007 status differs")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    for ordinal in range(1, 5):
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("Attempt007 successful case is not frozen")
        document, document_raw = _load_external_json(
            output_root / f"case-{ordinal:03d}-evidence.json"
        )
        verify_historical_attempt007_case_evidence(
            case,
            document,
            document_raw,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
    final = events[-1]
    if (
        final.case_ordinal != 5
        or final.event_kind != "TERMINAL"
        or final.disposition != "response_invalid"
        or final.error_code != "response_invalid"
        or final.http_status != 200
        or final.body_complete is not False
        or final.body_hash is not None
        or final.body_relative_path is not None
        or final.observed_body_bytes_lower_bound != 0
        or final.framing_status != "rejected"
        or final.framing_rejection_code != "response_body_incomplete"
    ):
        raise DeepSeekCalibrationError("immutable Attempt007 case5 failure facts drift")
    expected_names = {
        "provider-attempt-projection.json",
        "run-configuration.json",
        "run-status.json",
        *(f"case-{ordinal:03d}-evidence.json" for ordinal in range(1, 5)),
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt007 file inventory differs")
    return projection


def verify_historical_attempt008_case_evidence(
    case: FrozenCalibrationCase,
    document: Mapping[str, object],
    document_raw: bytes,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Verify one immutable Attempt008 success from exact ledger/raw/file identities."""

    validate_historical_attempt008_provider_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    if not 1 <= case.ordinal <= len(HISTORICAL_ATTEMPT008_CASE_FILE_HASHES):
        raise DeepSeekCalibrationError("historical Attempt008 case ordinal is invalid")
    if _sha256(document_raw) != HISTORICAL_ATTEMPT008_CASE_FILE_HASHES[case.ordinal - 1]:
        raise DeepSeekCalibrationError("immutable Attempt008 case file identity drift")
    admitted = _admit_external_json_bytes(document_raw, label="Attempt008 case evidence")
    if dict(document) != admitted:
        raise DeepSeekCalibrationError("Attempt008 case document differs from exact bytes")
    if (
        document.get("schema_version") != "m3.stage2.deepseek-case-evidence.v3"
        or document.get("ordinal") != case.ordinal
        or type(document.get("evidence")) is not dict
    ):
        raise DeepSeekCalibrationError("Attempt008 case evidence shape drift")
    evidence = cast(dict[str, object], document["evidence"])
    if document.get("evidence_binding_hash") != _sha256(_canonical_bytes(evidence)):
        raise DeepSeekCalibrationError("Attempt008 case evidence binding drift")
    successes = [
        event
        for event in events
        if event.case_ordinal == case.ordinal
        and event.event_kind == "TERMINAL"
        and event.disposition == "success"
    ]
    if len(successes) != 1 or successes[0].body_relative_path is None:
        raise DeepSeekCalibrationError("Attempt008 case lacks one successful closure")
    raw_response = _read_ledger_bound_provider_body(
        raw_root,
        successes[0],
        missing_message="Attempt008 case raw response path is invalid",
        drift_message="Attempt008 case raw response differs from ledger",
    )
    candidate, response_id, usage, structured = parse_deepseek_completed_response_semantic_v2(
        raw_response
    )
    request_bytes = deepseek_provider_request_semantic_v2_bytes(case.request)
    semantic_request = semantic_evaluation_request_bytes(case.request)
    if (
        evidence.get("case_id") != case.case_id
        or evidence.get("semantic_request_hash") != _sha256(semantic_request)
        or evidence.get("semantic_request_hex") != semantic_request.hex()
        or evidence.get("provider_request_hash") != _sha256(request_bytes)
        or evidence.get("raw_provider_request_hex") != request_bytes.hex()
        or evidence.get("provider_response_hash") != _sha256(raw_response)
        or evidence.get("raw_provider_response_hex") != raw_response.hex()
        or evidence.get("provider_response_id") != response_id
        or evidence.get("structured_output_hash") != _sha256(structured)
        or evidence.get("structured_output_hex") != structured.hex()
        or evidence.get("provider_result") != candidate.result.value
        or evidence.get("usage") != BaseModel.model_dump(usage, mode="json")
        or evidence.get("provider_configuration_version")
        != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION
        or evidence.get("provider_configuration_hash")
        != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH
    ):
        raise DeepSeekCalibrationError("Attempt008 case evidence differs from immutable authority")


def verify_historical_attempt008_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt008 without using the active Attempt011 label."""

    if (
        expected_provider_run_id != HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID
        or expected_implementation_manifest_hash != HISTORICAL_ATTEMPT008_MANIFEST_HASH
    ):
        raise DeepSeekCalibrationError("expected Attempt008 immutable identity drift")
    configuration = historical_attempt008_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt008 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    if len(events) != 12:
        raise DeepSeekCalibrationError("immutable Attempt008 event count drift")
    projection = historical_attempt008_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        projection.get("projection_hash") != HISTORICAL_ATTEMPT008_PROJECTION_HASH
        or projection.get("event_count") != 12
        or projection.get("attempt_count") != 6
        or projection.get("status") != "FAILED"
    ):
        raise DeepSeekCalibrationError("immutable Attempt008 projection facts drift")
    observed_projection, observed_projection_raw = _load_external_json(
        output_root / "provider-attempt-projection.json"
    )
    if (
        observed_projection != projection
        or _sha256(observed_projection_raw) != HISTORICAL_ATTEMPT008_PROJECTION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt008 projection differs")
    run_configuration, run_configuration_raw = _load_external_json(
        output_root / "run-configuration.json"
    )
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
    }
    if (
        run_configuration != expected_run_configuration
        or _sha256(run_configuration_raw) != HISTORICAL_ATTEMPT008_CONFIGURATION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt008 configuration differs")
    status, status_raw = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt008_expected_run_status(
        configuration=configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        status != expected_status
        or _sha256(status_raw) != HISTORICAL_ATTEMPT008_STATUS_FILE_HASH
        or status.get("status_binding_hash") != HISTORICAL_ATTEMPT008_STATUS_BINDING_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt008 status differs")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    for ordinal in range(1, 5):
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("Attempt008 successful case is not frozen")
        document, document_raw = _load_external_json(
            output_root / f"case-{ordinal:03d}-evidence.json"
        )
        verify_historical_attempt008_case_evidence(
            case,
            document,
            document_raw,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
    case5 = [event for event in events if event.case_ordinal == 5]
    if (
        len(case5) != 4
        or [event.attempt_ordinal for event in case5] != [1, 1, 2, 2]
        or [event.event_kind for event in case5] != ["START", "TERMINAL", "START", "TERMINAL"]
        or case5[1].disposition != "transport_unavailable"
        or case5[3].disposition != "deadline_exceeded"
        or any(
            event.http_status != 200
            or event.body_complete is not False
            or event.body_hash is not None
            or event.body_relative_path is not None
            or event.observed_body_bytes_lower_bound != 0
            or event.framing_status != "rejected"
            or event.framing_rejection_code != "response_body_incomplete"
            for event in (case5[1], case5[3])
        )
    ):
        raise DeepSeekCalibrationError("immutable Attempt008 case5 retry facts drift")
    expected_names = {
        "provider-attempt-projection.json",
        "run-configuration.json",
        "run-status.json",
        *(f"case-{ordinal:03d}-evidence.json" for ordinal in range(1, 5)),
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt008 file inventory differs")
    return projection


def verify_historical_attempt009_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt009 independently from active Attempt011."""

    if (
        expected_provider_run_id != HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID
        or expected_implementation_manifest_hash != HISTORICAL_ATTEMPT009_MANIFEST_HASH
    ):
        raise DeepSeekCalibrationError("expected Attempt009 immutable identity drift")
    configuration = historical_attempt009_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt009 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    if len(events) != 12:
        raise DeepSeekCalibrationError("immutable Attempt009 event count drift")
    projection = historical_attempt009_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        projection.get("projection_hash") != HISTORICAL_ATTEMPT009_PROJECTION_HASH
        or projection.get("event_count") != 12
        or projection.get("attempt_count") != 6
        or projection.get("status") != "FAILED"
    ):
        raise DeepSeekCalibrationError("immutable Attempt009 projection facts drift")
    observed_projection, observed_projection_raw = _load_external_json(
        output_root / "provider-attempt-projection.json"
    )
    if (
        observed_projection != projection
        or _sha256(observed_projection_raw) != HISTORICAL_ATTEMPT009_PROJECTION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt009 projection differs")
    run_configuration, run_configuration_raw = _load_external_json(
        output_root / "run-configuration.json"
    )
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
    }
    if (
        run_configuration != expected_run_configuration
        or _sha256(run_configuration_raw) != HISTORICAL_ATTEMPT009_CONFIGURATION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt009 configuration differs")
    status, status_raw = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt009_expected_run_status(
        configuration=configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        status != expected_status
        or _sha256(status_raw) != HISTORICAL_ATTEMPT009_STATUS_FILE_HASH
        or status.get("status_binding_hash") != HISTORICAL_ATTEMPT009_STATUS_BINDING_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt009 status differs")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    successes = [
        event
        for event in events
        if event.event_kind == "TERMINAL" and event.disposition == "success"
    ]
    if tuple((event.body_byte_count, event.body_hash) for event in successes) != (
        HISTORICAL_ATTEMPT009_SUCCESS_RAW_FACTS
    ):
        raise DeepSeekCalibrationError("immutable Attempt009 raw success facts drift")
    for ordinal in range(1, 5):
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("Attempt009 successful case is not frozen")
        document, document_raw = _load_external_json(
            output_root / f"case-{ordinal:03d}-evidence.json"
        )
        if _sha256(document_raw) != HISTORICAL_ATTEMPT009_CASE_FILE_HASHES[ordinal - 1]:
            raise DeepSeekCalibrationError("immutable Attempt009 case file identity drift")
        expected_document = historical_attempt009_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if document != expected_document:
            raise DeepSeekCalibrationError(
                "Attempt009 case evidence differs from immutable authority"
            )
    case5 = [event for event in events if event.case_ordinal == 5]
    if (
        len(case5) != 4
        or [event.attempt_ordinal for event in case5] != [1, 1, 2, 2]
        or [event.event_kind for event in case5] != ["START", "TERMINAL", "START", "TERMINAL"]
        or case5[1].disposition != "transport_unavailable"
        or case5[3].disposition != "deadline_exceeded"
        or any(
            event.http_status != 200
            or event.body_complete is not False
            or event.body_hash is not None
            or event.body_relative_path is not None
            or event.observed_body_bytes_lower_bound != 0
            or event.framing_status != "rejected"
            or event.framing_rejection_code != "response_body_incomplete"
            for event in (case5[1], case5[3])
        )
    ):
        raise DeepSeekCalibrationError("immutable Attempt009 case5 retry facts drift")
    expected_names = {
        "provider-attempt-projection.json",
        "run-configuration.json",
        "run-status.json",
        *(f"case-{ordinal:03d}-evidence.json" for ordinal in range(1, 5)),
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt009 file inventory differs")
    return projection


def verify_historical_attempt010_external_run(
    repository: ProviderAttemptLedgerRepository,
    output_root: Path,
    *,
    expected_provider_run_id: str,
    expected_code_revision: str,
    expected_implementation_manifest_hash: str,
    frozen_cases: Sequence[FrozenCalibrationCase],
) -> dict[str, object]:
    """Verify immutable failed Attempt010 independently from active Attempt011."""

    if (
        expected_provider_run_id != HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID
        or expected_implementation_manifest_hash != HISTORICAL_ATTEMPT010_MANIFEST_HASH
    ):
        raise DeepSeekCalibrationError("expected Attempt010 immutable identity drift")
    configuration = historical_attempt010_calibration_configuration(
        code_revision=expected_code_revision,
        implementation_manifest_hash=expected_implementation_manifest_hash,
    )
    if provider_attempt_run_id(configuration) != expected_provider_run_id:
        raise DeepSeekCalibrationError("expected Attempt010 provider run identity drift")
    events = repository.list_events(expected_provider_run_id)
    if len(events) != 12:
        raise DeepSeekCalibrationError("immutable Attempt010 event count drift")
    projection = historical_attempt010_provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        projection.get("projection_hash") != HISTORICAL_ATTEMPT010_PROJECTION_HASH
        or projection.get("event_count") != 12
        or projection.get("attempt_count") != 6
        or projection.get("status") != "FAILED"
    ):
        raise DeepSeekCalibrationError("immutable Attempt010 projection facts drift")
    observed_projection, observed_projection_raw = _load_external_json(
        output_root / "provider-attempt-projection.json"
    )
    if (
        observed_projection != projection
        or _sha256(observed_projection_raw) != HISTORICAL_ATTEMPT010_PROJECTION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt010 projection differs")
    run_configuration, run_configuration_raw = _load_external_json(
        output_root / "run-configuration.json"
    )
    expected_run_configuration = {
        "schema_version": "m3.stage2.deepseek-run-configuration.v2",
        "status": "PENDING",
        "configuration": configuration,
        "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
    }
    if (
        run_configuration != expected_run_configuration
        or _sha256(run_configuration_raw) != HISTORICAL_ATTEMPT010_CONFIGURATION_FILE_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt010 configuration differs")
    status, status_raw = _load_external_json(output_root / "run-status.json")
    expected_status = historical_attempt010_expected_run_status(
        configuration=configuration,
        events=events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=output_root.parent,
    )
    if (
        status != expected_status
        or _sha256(status_raw) != HISTORICAL_ATTEMPT010_STATUS_FILE_HASH
        or status.get("status_binding_hash") != HISTORICAL_ATTEMPT010_STATUS_BINDING_HASH
    ):
        raise DeepSeekCalibrationError("external Attempt010 status differs")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    successes = [
        event
        for event in events
        if event.event_kind == "TERMINAL" and event.disposition == "success"
    ]
    if tuple((event.body_byte_count, event.body_hash) for event in successes) != (
        HISTORICAL_ATTEMPT010_SUCCESS_RAW_FACTS
    ):
        raise DeepSeekCalibrationError("immutable Attempt010 raw success facts drift")
    for ordinal in range(1, 5):
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("Attempt010 successful case is not frozen")
        document, document_raw = _load_external_json(
            output_root / f"case-{ordinal:03d}-evidence.json"
        )
        if _sha256(document_raw) != HISTORICAL_ATTEMPT010_CASE_FILE_HASHES[ordinal - 1]:
            raise DeepSeekCalibrationError("immutable Attempt010 case file identity drift")
        expected_document = historical_attempt010_case_evidence_document(
            case,
            events,
            output_root.parent,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        if document != expected_document:
            raise DeepSeekCalibrationError(
                "Attempt010 case evidence differs from immutable authority"
            )
    case5 = [event for event in events if event.case_ordinal == 5]
    if (
        len(case5) != 4
        or [event.attempt_ordinal for event in case5] != [1, 1, 2, 2]
        or [event.event_kind for event in case5] != ["START", "TERMINAL", "START", "TERMINAL"]
        or case5[1].disposition != "transport_unavailable"
        or case5[3].disposition != "deadline_exceeded"
        or any(
            event.http_status != 200
            or event.body_complete is not False
            or event.body_hash is not None
            or event.body_relative_path is not None
            or event.observed_body_bytes_lower_bound != 0
            or event.framing_status != "rejected"
            or event.framing_rejection_code != "response_body_incomplete"
            for event in (case5[1], case5[3])
        )
    ):
        raise DeepSeekCalibrationError("immutable Attempt010 case5 retry facts drift")
    expected_names = {
        "provider-attempt-projection.json",
        "run-configuration.json",
        "run-status.json",
        *(f"case-{ordinal:03d}-evidence.json" for ordinal in range(1, 5)),
    }
    if {path.name for path in output_root.iterdir()} != expected_names:
        raise DeepSeekCalibrationError("external Attempt010 file inventory differs")
    return projection


def _load_external_json(path: Path) -> tuple[dict[str, object], bytes]:
    if not path.is_file() or path.is_symlink():
        raise DeepSeekCalibrationError("external run evidence file is missing")
    with path.open("rb") as handle:
        raw = handle.read(_EXTERNAL_JSON_MAX_BYTES + 1)
    value = _admit_external_json_bytes(raw, label="external run evidence")
    return value, raw


def persist_provider_event_projection(
    run: PendingCalibrationRun,
    events: Sequence[ProviderAttemptEvent],
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    projection = provider_event_projection(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=run.output_root.parent,
    )
    name = "provider-attempt-projection.json"
    _write_new_json(run.pending_root / name, projection)
    run.raw_body_paths.append(name)
    run.provider_attempt_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    return projection


def acceptance_metrics(observations: Sequence[CalibrationObservation]) -> dict[str, object]:
    """Recompute the frozen zero-tolerance and agreement acceptance criteria."""

    if type(observations) not in {list, tuple} or len(observations) != CASE_COUNT:
        raise DeepSeekCalibrationError("calibration requires exactly 36 observations")
    expected_ids = [f"M3-008B-CAL-{index:03d}" for index in range(1, CASE_COUNT + 1)]
    if [item.case.case_id for item in observations] != expected_ids:
        raise DeepSeekCalibrationError("observation order drift")
    confusion = {
        expected.value: {predicted.value: 0 for predicted in SemanticSupport}
        for expected in SemanticSupport
    }
    categories: Counter[str] = Counter()
    agreements = 0
    for item in observations:
        if type(item) is not CalibrationObservation:
            raise DeepSeekCalibrationError("observation type is invalid")
        predicted = item.assessment.result.result
        expected = item.case.human_expected_state
        confusion[expected.value][predicted.value] += 1
        categories[item.case.category] += 1
        agreements += predicted is expected
    state_metrics: dict[str, object] = {}
    recalls_pass = True
    state_counts_pass = True
    for state in SemanticSupport:
        denominator = sum(confusion[state.value].values())
        recall = confusion[state.value][state.value] / denominator if denominator else 0.0
        state_metrics[state.value] = {"n": denominator, "recall": recall}
        state_counts_pass &= denominator >= 8
        recalls_pass &= recall >= 0.75
    rate = agreements / CASE_COUNT
    zero_tolerance = (
        confusion["unsupported"]["supported"] == 0 and confusion["uncertain"]["supported"] == 0
    )
    passed = zero_tolerance and rate >= 0.85 and state_counts_pass and recalls_pass
    return {
        "semantic_contract_version": SEMANTIC_EVALUATION_V2_CONTRACT_VERSION,
        "semantic_contract_hash": SEMANTIC_EVALUATION_V2_CONTRACT_HASH,
        "routing_policy_hash": REVIEW_ROUTING_POLICY_HASH,
        "routing_matrix_hash": SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH,
        "agreement_count": agreements,
        "denominator": CASE_COUNT,
        "agreement_rate": rate,
        "confusion_matrix": confusion,
        "human_state_metrics": state_metrics,
        "categories_exercised": sorted(categories),
        "category_counts": dict(sorted(categories.items())),
        "zero_tolerance_passed": zero_tolerance,
        "human_state_counts_passed": state_counts_pass,
        "human_state_recall_passed": recalls_pass,
        "accepted": passed,
    }


def _case_evidence_payload(item: CalibrationObservation) -> dict[str, object]:
    if type(item) is not CalibrationObservation or type(item.assessment) is not (
        DeepSeekSemanticAssessmentV2
    ):
        raise DeepSeekCalibrationError("semantic V2 observation type is invalid")
    assessment = item.assessment
    expected_request = deepseek_provider_request_semantic_v2_bytes(item.case.request)
    expected_input = semantic_evaluation_input_bytes(item.case.request)
    semantic_request = semantic_evaluation_request_bytes(item.case.request)
    if (
        item.case.semantic_request_hash != _sha256(semantic_request)
        or item.case.stage1_admission_identity != item.case.request.stage1_admission.admission_hash
        or item.case.source != item.case.request.source.value
        or item.case.citation_relationship != item.case.request.citation.relationship.value
        or assessment.raw_provider_request_bytes != expected_request
        or assessment.provider_request_hash != _sha256(expected_request)
        or assessment.evaluator_input_hash != _sha256(expected_input)
        or assessment.result.input_digest != item.case.request.input_digest
        or assessment.result.configuration_hash != SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH
        or assessment.result.semantic_contract_version != SEMANTIC_EVALUATION_V2_CONTRACT_VERSION
        or assessment.result.semantic_contract_hash != SEMANTIC_EVALUATION_V2_CONTRACT_HASH
        or assessment.result.method != SEMANTIC_EVALUATION_V2_PROVIDER_METHOD
        or assessment.result.provider_configuration_version
        != SEMANTIC_EVALUATION_V2_PROVIDER_CONFIGURATION_VERSION
        or assessment.result.provider_configuration_hash
        != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH
    ):
        raise DeepSeekCalibrationError("provider observation binding drift")
    candidate, response_id, usage, structured = parse_deepseek_completed_response_semantic_v2(
        assessment.raw_response_envelope_bytes
    )
    expected_result = build_semantic_evaluation_result_v2(item.case.request, candidate)
    if (
        response_id != assessment.provider_response_id
        or _sha256(assessment.raw_response_envelope_bytes) != assessment.provider_response_hash
        or structured != assessment.structured_output_bytes
        or _sha256(structured) != assessment.structured_output_hash
        or usage != assessment.usage
        or expected_result != assessment.result
    ):
        raise DeepSeekCalibrationError("provider response evidence drift")
    routing = expected_result.routing_disposition
    return {
        "case_id": item.case.case_id,
        "category": item.case.category,
        "source": item.case.source,
        "citation_relationship": item.case.citation_relationship,
        "semantic_request_hash": item.case.semantic_request_hash,
        "semantic_request_hex": semantic_request.hex(),
        "stage1_admission_identity": item.case.stage1_admission_identity,
        "immutable_projection_hash": item.case.immutable_projection_hash,
        "human_expected_state": item.case.human_expected_state.value,
        "human_authority": item.case.human_authority,
        "human_notes": item.case.human_notes,
        "provider_result": expected_result.result.value,
        "parsed_result": BaseModel.model_dump(expected_result, mode="json"),
        "semantic_contract": expected_result.semantic_contract,
        "semantic_contract_version": expected_result.semantic_contract_version,
        "semantic_contract_hash": expected_result.semantic_contract_hash,
        "semantic_result_content_hash": expected_result.semantic_result_content_hash,
        "application_provenance_method": expected_result.method,
        "provider_configuration_version": expected_result.provider_configuration_version,
        "provider_configuration_hash": expected_result.provider_configuration_hash,
        "routing_policy_version": routing.routing_policy_version,
        "routing_policy_hash": routing.routing_policy_hash,
        "routing_disposition": routing.disposition.value,
        "routing_human_review_required": routing.human_review_required,
        "routing_content_hash": routing.content_hash,
        "disagreement": expected_result.result is not item.case.human_expected_state,
        "evaluator_input_hash": assessment.evaluator_input_hash,
        "provider_request_hash": assessment.provider_request_hash,
        "raw_provider_request_hex": assessment.raw_provider_request_bytes.hex(),
        "provider_response_id": assessment.provider_response_id,
        "provider_response_hash": assessment.provider_response_hash,
        "raw_provider_response_hex": assessment.raw_response_envelope_bytes.hex(),
        "structured_output_hash": assessment.structured_output_hash,
        "structured_output_hex": assessment.structured_output_bytes.hex(),
        "usage": BaseModel.model_dump(assessment.usage, mode="json"),
        "attempts": assessment.attempts,
        "started_at_utc": assessment.started_at_utc.isoformat(),
        "completed_at_utc": assessment.completed_at_utc.isoformat(),
    }


def _historical_attempt004_case_evidence_payload(
    item: CalibrationObservation,
) -> dict[str, object]:
    return _case_evidence_payload_with_authority(
        item,
        request_bytes_builder=deepseek_provider_request_v2_bytes,
        response_parser=parse_deepseek_completed_response_v2,
        result_builder=build_deepseek_semantic_evaluation_result_v2,
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V2,
    )


def _historical_attempt005_case_evidence_payload(
    item: CalibrationObservation,
) -> dict[str, object]:
    return _case_evidence_payload_with_authority(
        item,
        request_bytes_builder=deepseek_provider_request_v3_bytes,
        response_parser=parse_deepseek_completed_response_v3,
        result_builder=build_deepseek_semantic_evaluation_result_v3,
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
    )


def _case_evidence_payload_with_authority(
    item: CalibrationObservation,
    *,
    request_bytes_builder: Callable[[SemanticEvaluationRequest], bytes],
    response_parser: Callable[
        [bytes], tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]
    ],
    result_builder: Callable[
        [SemanticEvaluationRequest, SemanticEvaluationCandidate], SemanticEvaluationResult
    ],
    configuration_hash: str,
) -> dict[str, object]:
    if type(item) is not CalibrationObservation:
        raise DeepSeekCalibrationError("calibration observation type is invalid")
    assessment = item.assessment
    expected_request = request_bytes_builder(item.case.request)
    expected_input = semantic_evaluation_input_bytes(item.case.request)
    semantic_request = semantic_evaluation_request_bytes(item.case.request)
    if (
        item.case.semantic_request_hash != _sha256(semantic_request)
        or item.case.stage1_admission_identity != item.case.request.stage1_admission.admission_hash
        or item.case.source != item.case.request.source.value
        or item.case.citation_relationship != item.case.request.citation.relationship.value
        or assessment.raw_provider_request_bytes != expected_request
        or assessment.provider_request_hash != _sha256(expected_request)
        or assessment.evaluator_input_hash != _sha256(expected_input)
        or assessment.result.input_digest != item.case.request.input_digest
        or assessment.result.configuration_hash != configuration_hash
    ):
        raise DeepSeekCalibrationError("provider observation binding drift")
    candidate, response_id, usage, structured = response_parser(
        assessment.raw_response_envelope_bytes
    )
    expected_result = result_builder(item.case.request, candidate)
    if (
        response_id != assessment.provider_response_id
        or _sha256(assessment.raw_response_envelope_bytes) != assessment.provider_response_hash
        or structured != assessment.structured_output_bytes
        or _sha256(structured) != assessment.structured_output_hash
        or usage != assessment.usage
        or expected_result != assessment.result
    ):
        raise DeepSeekCalibrationError("provider response evidence drift")
    return {
        "case_id": item.case.case_id,
        "category": item.case.category,
        "source": item.case.source,
        "citation_relationship": item.case.citation_relationship,
        "semantic_request_hash": item.case.semantic_request_hash,
        "semantic_request_hex": semantic_request.hex(),
        "stage1_admission_identity": item.case.stage1_admission_identity,
        "immutable_projection_hash": item.case.immutable_projection_hash,
        "human_expected_state": item.case.human_expected_state.value,
        "human_authority": item.case.human_authority,
        "human_notes": item.case.human_notes,
        "provider_result": assessment.result.result.value,
        "parsed_result": BaseModel.model_dump(assessment.result, mode="json"),
        "disagreement": assessment.result.result is not item.case.human_expected_state,
        "evaluator_input_hash": assessment.evaluator_input_hash,
        "provider_request_hash": assessment.provider_request_hash,
        "raw_provider_request_hex": assessment.raw_provider_request_bytes.hex(),
        "provider_response_id": assessment.provider_response_id,
        "provider_response_hash": assessment.provider_response_hash,
        "raw_provider_response_hex": assessment.raw_response_envelope_bytes.hex(),
        "structured_output_hash": assessment.structured_output_hash,
        "structured_output_hex": assessment.structured_output_bytes.hex(),
        "usage": BaseModel.model_dump(assessment.usage, mode="json"),
        "attempts": assessment.attempts,
        "started_at_utc": assessment.started_at_utc.isoformat(),
        "completed_at_utc": assessment.completed_at_utc.isoformat(),
    }


def canonical_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct one active Attempt011 success from frozen input and exact raw bytes."""

    return _semantic_v2_case_evidence_document(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        event_validator=validate_authoritative_provider_events,
    )


def historical_attempt009_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct one immutable Attempt009 success without active Attempt011 authority."""

    return _semantic_v2_case_evidence_document(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        event_validator=validate_historical_attempt009_provider_events,
    )


def historical_attempt010_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct immutable Attempt010 success from frozen input and raw bytes."""

    return _semantic_v2_case_evidence_document(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        event_validator=validate_historical_attempt010_provider_events,
    )


def _semantic_v2_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    event_validator: Callable[..., tuple[ProviderAttemptEvent, ...]],
) -> dict[str, object]:

    event_validator(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    starts = sorted(
        (
            item
            for item in events
            if item.case_ordinal == case.ordinal and item.event_kind == "START"
        ),
        key=lambda item: item.attempt_ordinal,
    )
    successes = [
        item
        for item in events
        if item.case_ordinal == case.ordinal
        and item.event_kind == "TERMINAL"
        and item.disposition == "success"
    ]
    if (
        not starts
        or len(successes) != 1
        or successes[0].attempt_ordinal != starts[-1].attempt_ordinal
    ):
        raise DeepSeekCalibrationError("case lacks one final successful ledger closure")
    terminal = successes[0]
    if terminal.body_relative_path is None or terminal.completed_at_utc is None:
        raise DeepSeekCalibrationError("case success lacks raw/timestamp binding")
    raw = _read_ledger_bound_provider_body(
        raw_root,
        terminal,
        missing_message="case raw response path is invalid",
        drift_message="case raw response differs from ledger",
    )
    candidate, response_id, usage, structured = parse_deepseek_completed_response_semantic_v2(raw)
    result = build_semantic_evaluation_result_v2(case.request, candidate)
    request_bytes = deepseek_provider_request_semantic_v2_bytes(case.request)
    assessment = DeepSeekSemanticAssessmentV2(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(case.request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=structured,
        structured_output_hash=_sha256(structured),
        attempts=len(starts),
        usage=usage,
        started_at_utc=starts[0].started_at_utc,
        completed_at_utc=terminal.completed_at_utc,
    )
    payload = _case_evidence_payload(CalibrationObservation(case, assessment))
    return {
        "schema_version": "m3.stage2.deepseek-case-evidence.v3",
        "ordinal": case.ordinal,
        "evidence": payload,
        "evidence_binding_hash": _sha256(_canonical_bytes(payload)),
    }


def historical_attempt004_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct one immutable Attempt004 successful-case projection."""

    return _canonical_case_evidence_document_with_authority(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        validate_events=validate_historical_attempt004_provider_events,
        response_parser=parse_deepseek_completed_response_v2,
        result_builder=build_deepseek_semantic_evaluation_result_v2,
        request_bytes_builder=deepseek_provider_request_v2_bytes,
        payload_builder=_historical_attempt004_case_evidence_payload,
    )


def historical_attempt005_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct one immutable Attempt005 successful-case projection if present."""

    return _canonical_case_evidence_document_with_authority(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        validate_events=validate_historical_attempt005_provider_events,
        response_parser=parse_deepseek_completed_response_v3,
        result_builder=build_deepseek_semantic_evaluation_result_v3,
        request_bytes_builder=deepseek_provider_request_v3_bytes,
        payload_builder=_historical_attempt005_case_evidence_payload,
    )


def historical_attempt006_case_evidence_document(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Reconstruct immutable Attempt006 successes under their exact V4 authority."""

    return _canonical_case_evidence_document_with_authority(
        case,
        events,
        raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        validate_events=validate_historical_attempt006_provider_events,
        response_parser=parse_deepseek_completed_response_v4,
        result_builder=build_deepseek_semantic_evaluation_result_v4,
        request_bytes_builder=deepseek_provider_request_bytes,
        payload_builder=lambda item: _case_evidence_payload_with_authority(
            item,
            request_bytes_builder=deepseek_provider_request_bytes,
            response_parser=parse_deepseek_completed_response_v4,
            result_builder=build_deepseek_semantic_evaluation_result_v4,
            configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V4,
        ),
    )


def _canonical_case_evidence_document_with_authority(
    case: FrozenCalibrationCase,
    events: Sequence[ProviderAttemptEvent],
    raw_root: Path,
    *,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
    validate_events: Callable[..., tuple[ProviderAttemptEvent, ...]],
    response_parser: Callable[
        [bytes], tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]
    ],
    result_builder: Callable[
        [SemanticEvaluationRequest, SemanticEvaluationCandidate], SemanticEvaluationResult
    ],
    request_bytes_builder: Callable[[SemanticEvaluationRequest], bytes],
    payload_builder: Callable[[CalibrationObservation], dict[str, object]],
) -> dict[str, object]:

    validate_events(
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    starts = sorted(
        (
            item
            for item in events
            if item.case_ordinal == case.ordinal and item.event_kind == "START"
        ),
        key=lambda item: item.attempt_ordinal,
    )
    successes = [
        item
        for item in events
        if item.case_ordinal == case.ordinal
        and item.event_kind == "TERMINAL"
        and item.disposition == "success"
    ]
    if not starts or len(successes) != 1:
        raise DeepSeekCalibrationError("case lacks one final successful ledger closure")
    terminal = successes[0]
    if terminal.attempt_ordinal != starts[-1].attempt_ordinal:
        raise DeepSeekCalibrationError("case success is not the final attempt")
    if terminal.body_relative_path is None or terminal.completed_at_utc is None:
        raise DeepSeekCalibrationError("case success lacks raw/timestamp binding")
    raw = _read_ledger_bound_provider_body(
        raw_root,
        terminal,
        missing_message="case raw response path is invalid",
        drift_message="case raw response differs from ledger",
    )
    candidate, response_id, usage, structured = response_parser(raw)
    result = result_builder(case.request, candidate)
    request_bytes = request_bytes_builder(case.request)
    assessment = DeepSeekSemanticAssessment(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(case.request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=structured,
        structured_output_hash=_sha256(structured),
        attempts=len(starts),
        usage=usage,
        started_at_utc=starts[0].started_at_utc,
        completed_at_utc=terminal.completed_at_utc,
    )
    payload = payload_builder(CalibrationObservation(case, assessment))
    return {
        "schema_version": "m3.stage2.deepseek-case-evidence.v2",
        "ordinal": case.ordinal,
        "evidence": payload,
        "evidence_binding_hash": _sha256(_canonical_bytes(payload)),
    }


def build_calibration_artifact(
    observations: Sequence[CalibrationObservation],
    *,
    completed_at_utc: datetime,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> dict[str, object]:
    """Build one exact append-only raw-evidence artifact after all calls finish."""

    if completed_at_utc.tzinfo is None or completed_at_utc.utcoffset() != UTC.utcoffset(
        completed_at_utc
    ):
        raise DeepSeekCalibrationError("completion timestamp must be UTC")
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    starts = [item for item in provider_attempt_events if item.event_kind == "START"]
    closed_cases = {
        item.case_ordinal
        for item in provider_attempt_events
        if item.event_kind == "TERMINAL" and item.disposition == "success"
    }
    if (
        projection["status"] != "COMPLETE"
        or not provider_attempt_events
        or closed_cases != set(range(1, CASE_COUNT + 1))
    ):
        raise DeepSeekCalibrationError("provider attempt authority is not complete")
    attempts_by_case = Counter(item.case_ordinal for item in starts)
    normalized = tuple(
        CalibrationObservation(
            item.case,
            replace(item.assessment, attempts=attempts_by_case[item.case.ordinal]),
        )
        for item in observations
    )
    metrics = acceptance_metrics(normalized)
    cases = [
        cast(
            dict[str, object],
            canonical_case_evidence_document(
                item.case,
                provider_attempt_events,
                provider_raw_root,
                frozen_cases=frozen_cases,
                expected_provider_run_id=expected_provider_run_id,
            )["evidence"],
        )
        for item in normalized
    ]
    semantic = {
        "schema_version": "m3.stage2.deepseek-calibration.v2",
        "work_item": "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION",
        "holdout_accessed": False,
        "public_data_only": True,
        "configuration": calibration_configuration(
            code_revision=code_revision,
            implementation_manifest_hash=implementation_manifest_hash,
        ),
        "ordered_case_ids": [item.case.case_id for item in normalized],
        "cases": cases,
        "metrics": metrics,
        "routing_matrix": json.loads(semantic_evaluation_v2_routing_matrix_bytes().decode("utf-8")),
        "provider_attempt_authority": {
            "projection_hash": projection["projection_hash"],
            "event_count": projection["event_count"],
            "attempt_count": projection["attempt_count"],
            "status": projection["status"],
        },
    }
    artifact = {
        **semantic,
        "completed_at_utc": completed_at_utc.isoformat(),
        "artifact_semantic_identity": _sha256(_canonical_bytes(semantic)),
    }
    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    return artifact


def validate_calibration_artifact(
    artifact: Mapping[str, object],
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Reparse every byte surface and recompute the saved acceptance evidence."""

    _canonical_external_json_bytes(artifact, label="calibration artifact")
    top = {
        "schema_version",
        "work_item",
        "holdout_accessed",
        "public_data_only",
        "configuration",
        "ordered_case_ids",
        "cases",
        "metrics",
        "routing_matrix",
        "completed_at_utc",
        "artifact_semantic_identity",
        "provider_attempt_authority",
    }
    if type(artifact) is not dict or set(artifact) != top:
        raise DeepSeekCalibrationError("calibration artifact shape is invalid")
    configuration = artifact["configuration"]
    if type(configuration) is not dict:
        raise DeepSeekCalibrationError("calibration configuration is invalid")
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    expected_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    routing_matrix = artifact["routing_matrix"]
    routing_matrix_raw = _canonical_external_json_bytes(
        routing_matrix, label="semantic routing matrix"
    )
    try:
        validate_semantic_evaluation_v2_routing_matrix_bytes(routing_matrix_raw)
    except (SemanticEvaluationContractError, TypeError, ValueError):
        raise DeepSeekCalibrationError("semantic routing matrix drift") from None
    if routing_matrix_raw != semantic_evaluation_v2_routing_matrix_bytes():
        raise DeepSeekCalibrationError("semantic routing matrix drift")
    if (
        artifact["schema_version"] != "m3.stage2.deepseek-calibration.v2"
        or artifact["work_item"] != "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION"
        or artifact["holdout_accessed"] is not False
        or artifact["public_data_only"] is not True
        or _canonical_bytes(artifact["provider_attempt_authority"])
        != _canonical_bytes(expected_authority)
        or _canonical_bytes(configuration)
        != _canonical_bytes(
            calibration_configuration(
                code_revision=code_revision,
                implementation_manifest_hash=implementation_manifest_hash,
            )
        )
    ):
        raise DeepSeekCalibrationError("calibration artifact boundary drift")
    semantic = dict(artifact)
    identity = semantic.pop("artifact_semantic_identity")
    semantic.pop("completed_at_utc")
    if identity != _sha256(_canonical_bytes(semantic)):
        raise DeepSeekCalibrationError("calibration artifact identity drift")
    _utc(artifact["completed_at_utc"])
    cases = artifact["cases"]
    ordered = artifact["ordered_case_ids"]
    if type(cases) is not list or type(ordered) is not list or len(cases) != CASE_COUNT:
        raise DeepSeekCalibrationError("calibration artifact cases are invalid")
    expected_ids = [f"M3-008B-CAL-{index:03d}" for index in range(1, CASE_COUNT + 1)]
    if ordered != expected_ids:
        raise DeepSeekCalibrationError("calibration artifact order drift")
    minimal: list[tuple[str, str, str]] = []
    attempts_by_case = Counter(
        item.case_ordinal for item in provider_attempt_events if item.event_kind == "START"
    )
    starts_by_case = {
        ordinal: [
            item
            for item in provider_attempt_events
            if item.event_kind == "START" and item.case_ordinal == ordinal
        ]
        for ordinal in range(1, CASE_COUNT + 1)
    }
    success_by_case = {
        item.case_ordinal: item
        for item in provider_attempt_events
        if item.event_kind == "TERMINAL" and item.disposition == "success"
    }
    inventory: list[dict[str, object]] = []
    response_ids: set[str] = set()
    semantic_request_hashes: set[str] = set()
    case_fields = {
        "case_id",
        "category",
        "source",
        "citation_relationship",
        "semantic_request_hash",
        "semantic_request_hex",
        "stage1_admission_identity",
        "immutable_projection_hash",
        "human_expected_state",
        "human_authority",
        "human_notes",
        "provider_result",
        "parsed_result",
        "semantic_contract",
        "semantic_contract_version",
        "semantic_contract_hash",
        "semantic_result_content_hash",
        "application_provenance_method",
        "provider_configuration_version",
        "provider_configuration_hash",
        "routing_policy_version",
        "routing_policy_hash",
        "routing_disposition",
        "routing_human_review_required",
        "routing_content_hash",
        "disagreement",
        "evaluator_input_hash",
        "provider_request_hash",
        "raw_provider_request_hex",
        "provider_response_id",
        "provider_response_hash",
        "raw_provider_response_hex",
        "structured_output_hash",
        "structured_output_hex",
        "usage",
        "attempts",
        "started_at_utc",
        "completed_at_utc",
    }
    for index, value in enumerate(cases, start=1):
        if type(value) is not dict or set(value) != case_fields:
            raise DeepSeekCalibrationError("calibration case evidence shape is invalid")
        case_id = expected_ids[index - 1]
        if value["case_id"] != case_id:
            raise DeepSeekCalibrationError("calibration case identity drift")
        if value["attempts"] != attempts_by_case[index]:
            raise DeepSeekCalibrationError("calibration case attempts differ from ledger")
        if any(
            item.request_hash != value["provider_request_hash"] for item in starts_by_case[index]
        ):
            raise DeepSeekCalibrationError("calibration provider request differs from ledger")
        if value["semantic_request_hash"] in semantic_request_hashes:
            raise DeepSeekCalibrationError("duplicate calibration semantic request")
        semantic_request_hashes.add(cast(str, value["semantic_request_hash"]))
        request_raw = _hex_bytes(value["semantic_request_hex"], 1_000_000)
        request = parse_semantic_evaluation_request(request_raw)
        if (
            semantic_evaluation_request_bytes(request) != request_raw
            or _sha256(request_raw) != value["semantic_request_hash"]
            or request.stage1_admission.admission_hash != value["stage1_admission_identity"]
            or value["source"] != request.source.value
            or value["citation_relationship"] != request.citation.relationship.value
        ):
            raise DeepSeekCalibrationError("calibration semantic request drift")
        provider_request = _hex_bytes(value["raw_provider_request_hex"], 262_144)
        if (
            _sha256(semantic_evaluation_input_bytes(request)) != value["evaluator_input_hash"]
            or provider_request != deepseek_provider_request_semantic_v2_bytes(request)
            or _sha256(provider_request) != value["provider_request_hash"]
        ):
            raise DeepSeekCalibrationError("calibration provider request drift")
        response_raw = _hex_bytes(value["raw_provider_response_hex"], 131_072)
        success = success_by_case.get(index)
        ledger_raw = (
            None
            if success is None or success.body_relative_path is None
            else _read_ledger_bound_provider_body(
                provider_raw_root,
                success,
                missing_message="calibration provider response path is invalid",
                drift_message="calibration provider response differs from ledger",
            )
        )
        if (
            success is None
            or success.body_hash != value["provider_response_hash"]
            or success.body_relative_path is None
            or ledger_raw != response_raw
        ):
            raise DeepSeekCalibrationError("calibration provider response differs from ledger")
        candidate, response_id, usage, structured = parse_deepseek_completed_response_semantic_v2(
            response_raw
        )
        stored_structured = _hex_bytes(value["structured_output_hex"], 16_384)
        expected_result = build_semantic_evaluation_result_v2(request, candidate)
        result_document = value["parsed_result"]
        expected_result_document = BaseModel.model_dump(expected_result, mode="json")
        if type(result_document) is not dict or result_document != expected_result_document:
            raise DeepSeekCalibrationError("calibration parsed result is invalid")
        try:
            stored_usage = SemanticEvaluationUsage.model_validate(value["usage"])
        except ValueError:
            raise DeepSeekCalibrationError("calibration parsed usage is invalid") from None
        if (
            value["provider_result"] != expected_result.result.value
            or value["semantic_contract"] != expected_result.semantic_contract
            or value["semantic_contract_version"] != expected_result.semantic_contract_version
            or value["semantic_contract_hash"] != expected_result.semantic_contract_hash
            or value["semantic_result_content_hash"] != expected_result.semantic_result_content_hash
            or value["application_provenance_method"] != expected_result.method
            or value["provider_configuration_version"]
            != expected_result.provider_configuration_version
            or value["provider_configuration_hash"] != expected_result.provider_configuration_hash
            or value["routing_policy_version"]
            != expected_result.routing_disposition.routing_policy_version
            or value["routing_policy_hash"]
            != expected_result.routing_disposition.routing_policy_hash
            or value["routing_disposition"] != expected_result.routing_disposition.disposition.value
            or value["routing_human_review_required"]
            is not expected_result.routing_disposition.human_review_required
            or value["routing_content_hash"] != expected_result.routing_disposition.content_hash
            or response_id != value["provider_response_id"]
            or _sha256(response_raw) != value["provider_response_hash"]
            or _sha256(structured) != value["structured_output_hash"]
            or stored_structured != structured
            or stored_usage != usage
            or type(value["attempts"]) is not int
            or not 1 <= value["attempts"] <= 3
        ):
            raise DeepSeekCalibrationError("calibration provider response drift")
        if response_id in response_ids:
            raise DeepSeekCalibrationError("duplicate provider response identity")
        response_ids.add(response_id)
        human = _support(value["human_expected_state"])
        if (
            value["human_authority"] != "project_owner"
            or type(value["human_notes"]) is not str
            or not value["human_notes"]
            or value["disagreement"] is not (expected_result.result is not human)
        ):
            raise DeepSeekCalibrationError("calibration human binding drift")
        started = _utc(value["started_at_utc"])
        completed = _utc(value["completed_at_utc"])
        if completed < started:
            raise DeepSeekCalibrationError("calibration timestamps are reversed")
        category = value["category"]
        if type(category) is not str or not category:
            raise DeepSeekCalibrationError("calibration category is invalid")
        minimal.append((human.value, expected_result.result.value, category))
        inventory.append(
            {
                "case_id": value["case_id"],
                "category": value["category"],
                "source": value["source"],
                "citation_relationship": value["citation_relationship"],
                "semantic_request_hash": value["semantic_request_hash"],
                "stage1_admission_identity": value["stage1_admission_identity"],
                "immutable_projection_hash": value["immutable_projection_hash"],
                "human_expected_state": value["human_expected_state"],
            }
        )
    if _sha256(_canonical_bytes(inventory)) != FROZEN_CASE_INVENTORY_IDENTITY:
        raise DeepSeekCalibrationError("calibration ordered case inventory drift")
    if tuple(sorted(Counter(item["category"] for item in inventory).items())) != (
        FROZEN_CATEGORY_COUNTS
    ):
        raise DeepSeekCalibrationError("calibration frozen category counts drift")
    if artifact["metrics"] != _artifact_metrics(minimal):
        raise DeepSeekCalibrationError("calibration metrics drift")


def begin_pending_calibration_run(
    output_root: Path,
    *,
    code_revision: str,
    implementation_manifest_hash: str,
) -> PendingCalibrationRun:
    """Create the sole pending run after caller completes every zero-effect preflight."""

    configuration = calibration_configuration(
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
    )
    validate_output_target(output_root)
    pending = output_root.parent / f".{output_root.name}.pending"
    pending.mkdir()
    run = PendingCalibrationRun(
        configuration=configuration,
        output_root=output_root,
        pending_root=pending,
    )
    try:
        _write_new_json(
            pending / "run-configuration.json",
            {
                "schema_version": "m3.stage2.deepseek-run-configuration.v2",
                "status": "PENDING",
                "configuration": configuration,
                "configuration_binding_hash": _sha256(_canonical_bytes(configuration)),
            },
        )
    except Exception:
        if pending.exists() and not pending.is_symlink() and not any(pending.iterdir()):
            pending.rmdir()
        raise
    return run


def persist_successful_calibration_case(
    run: PendingCalibrationRun,
    observation: CalibrationObservation,
    *,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Fsync one successful exact case before the next provider call begins."""

    _validate_pending_run(run)
    expected_ordinal = len(run.successful_case_ids) + 1
    if observation.case.ordinal != expected_ordinal:
        raise DeepSeekCalibrationError("pending case order drift")
    run.attempted_case_ids.append(observation.case.case_id)
    document = canonical_case_evidence_document(
        observation.case,
        provider_attempt_events,
        provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    try:
        _write_new_json(
            run.pending_root / f"case-{expected_ordinal:03d}-evidence.json",
            document,
        )
    except Exception:
        run.attempted_case_ids.pop()
        raise
    run.successful_case_ids.append(observation.case.case_id)


def reconcile_case_evidence(
    run: PendingCalibrationRun,
    frozen_cases: Sequence[FrozenCalibrationCase],
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    *,
    expected_provider_run_id: str,
) -> None:
    """Rebuild only deterministic case projections from ledger/raw, never resend."""

    successful_ordinals = sorted(
        {
            item.case_ordinal
            for item in provider_attempt_events
            if item.event_kind == "TERMINAL" and item.disposition == "success"
        }
    )
    if successful_ordinals != list(range(1, len(successful_ordinals) + 1)):
        raise DeepSeekCalibrationError("successful case projections are not a prefix")
    by_ordinal = {case.ordinal: case for case in frozen_cases}
    for ordinal in successful_ordinals:
        case = by_ordinal.get(ordinal)
        if case is None:
            raise DeepSeekCalibrationError("ledger success has no frozen case")
        document = canonical_case_evidence_document(
            case,
            provider_attempt_events,
            provider_raw_root,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )
        _write_new_json(run.pending_root / f"case-{ordinal:03d}-evidence.json", document)
        run.attempted_case_ids.append(case.case_id)
        run.successful_case_ids.append(case.case_id)


def persist_raw_calibration_attempt(
    run: PendingCalibrationRun,
    case: FrozenCalibrationCase,
    observation: DeepSeekRawSemanticObservation,
) -> None:
    """Fsync exact raw request/response evidence before strict provider parsing."""

    _validate_pending_run(run)
    expected_ordinal = len(run.attempted_case_ids) + 1
    if case.ordinal != expected_ordinal:
        raise DeepSeekCalibrationError("pending raw attempt order drift")
    payload = _raw_attempt_payload(case, observation)
    _write_new_json(
        run.pending_root / f"case-{expected_ordinal:03d}-raw-observation.json",
        {
            "schema_version": "m3.stage2.deepseek-raw-observation.v1",
            "ordinal": expected_ordinal,
            "observation": payload,
            "observation_binding_hash": _sha256(_canonical_bytes(payload)),
        },
    )
    run.attempted_case_ids.append(case.case_id)


def _raw_attempt_payload(
    case: FrozenCalibrationCase,
    observation: DeepSeekRawSemanticObservation,
) -> dict[str, object]:
    if type(case) is not FrozenCalibrationCase or type(observation) is not (
        DeepSeekRawSemanticObservation
    ):
        raise DeepSeekCalibrationError("raw observation type is invalid")
    semantic_request = semantic_evaluation_request_bytes(case.request)
    evaluator_input = semantic_evaluation_input_bytes(case.request)
    provider_request = deepseek_provider_request_bytes(case.request)
    if (
        case.semantic_request_hash != _sha256(semantic_request)
        or case.stage1_admission_identity != case.request.stage1_admission.admission_hash
        or case.source != case.request.source.value
        or case.citation_relationship != case.request.citation.relationship.value
        or observation.evaluator_input_hash != _sha256(evaluator_input)
        or observation.provider_request_hash != _sha256(provider_request)
        or observation.raw_provider_request_bytes != provider_request
        or type(observation.raw_response_envelope_bytes) is not bytes
        or not observation.raw_response_envelope_bytes
        or len(observation.raw_response_envelope_bytes) > 131_072
        or observation.provider_response_hash != _sha256(observation.raw_response_envelope_bytes)
        or type(observation.status_code) is not int
        or observation.status_code != 200
        or type(observation.attempts) is not int
        or not 1 <= observation.attempts <= 3
        or not isinstance(observation.started_at_utc, datetime)
        or observation.started_at_utc.tzinfo is None
        or observation.started_at_utc.utcoffset() != UTC.utcoffset(observation.started_at_utc)
        or not isinstance(observation.completed_at_utc, datetime)
        or observation.completed_at_utc.tzinfo is None
        or observation.completed_at_utc.utcoffset() != UTC.utcoffset(observation.completed_at_utc)
        or observation.completed_at_utc < observation.started_at_utc
    ):
        raise DeepSeekCalibrationError("raw observation binding drift")
    return {
        "case_id": case.case_id,
        "semantic_request_hash": case.semantic_request_hash,
        "stage1_admission_identity": case.stage1_admission_identity,
        "evaluator_input_hash": observation.evaluator_input_hash,
        "provider_request_hash": observation.provider_request_hash,
        "raw_provider_request_hex": observation.raw_provider_request_bytes.hex(),
        "provider_response_hash": observation.provider_response_hash,
        "raw_provider_response_hex": observation.raw_response_envelope_bytes.hex(),
        "http_status_code": observation.status_code,
        "attempts": observation.attempts,
        "started_at_utc": observation.started_at_utc.isoformat(),
        "completed_at_utc": observation.completed_at_utc.isoformat(),
        "provider_usage_validated": False,
        "provider_result_validated": False,
    }


def publish_failed_calibration_run(
    run: PendingCalibrationRun,
    *,
    failed_case: FrozenCalibrationCase | None,
    error: Exception,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Publish retained prior successes and redacted failure metadata, never a PASS."""

    _validate_pending_run(run)
    projection = provider_event_projection(
        provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
    )
    run.provider_attempt_authority = {
        "projection_hash": projection["projection_hash"],
        "event_count": projection["event_count"],
        "attempt_count": projection["attempt_count"],
        "status": projection["status"],
    }
    del failed_case, error
    status = expected_run_status(
        configuration=run.configuration,
        events=provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
        artifact=None,
        artifact_bytes=None,
    )
    _write_new_json(run.pending_root / "run-status.json", status)
    run.pending_root.rename(run.output_root)


def publish_successful_calibration_run(
    run: PendingCalibrationRun,
    artifact: Mapping[str, object],
    *,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Publish a fully reparsed 36-case artifact and its prior per-case evidence."""

    _validate_pending_run(run)
    code_revision = run.configuration["code_revision"]
    implementation_manifest_hash = run.configuration["implementation_manifest_hash"]
    if type(code_revision) is not str or type(implementation_manifest_hash) is not str:
        raise DeepSeekCalibrationError("pending code identity drift")
    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    ordered = artifact["ordered_case_ids"]
    if (
        ordered != run.successful_case_ids
        or run.attempted_case_ids != run.successful_case_ids
        or len(run.successful_case_ids) != CASE_COUNT
    ):
        raise DeepSeekCalibrationError("pending successes differ from final artifact")
    metrics = artifact["metrics"]
    if type(metrics) is not dict or type(metrics.get("accepted")) is not bool:
        raise DeepSeekCalibrationError("final acceptance evidence is invalid")
    raw = _canonical_external_json_bytes(artifact, label="calibration artifact")
    artifact_path = run.pending_root / "m3-008b-deepseek-calibration.json"
    sidecar = f"{hashlib.sha256(raw).hexdigest()}  {artifact_path.name}\n".encode("ascii")
    sidecar_path = run.pending_root / f"{artifact_path.name}.sha256"
    status_path = run.pending_root / "run-status.json"
    status = expected_run_status(
        configuration=run.configuration,
        events=provider_attempt_events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
        raw_root=provider_raw_root,
        artifact=artifact,
        artifact_bytes=raw,
    )
    created: list[Path] = []
    try:
        _write_new_bytes(artifact_path, raw)
        created.append(artifact_path)
        _write_new_bytes(sidecar_path, sidecar)
        created.append(sidecar_path)
        _write_new_json(status_path, status)
        created.append(status_path)
        run.pending_root.rename(run.output_root)
    except Exception:
        if run.pending_root.exists() and not run.pending_root.is_symlink():
            for path in reversed(created):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        raise


def write_calibration_artifact(
    artifact: Mapping[str, object],
    output_root: Path,
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    provider_attempt_events: Sequence[ProviderAttemptEvent],
    provider_raw_root: Path,
    frozen_cases: Sequence[FrozenCalibrationCase],
    expected_provider_run_id: str,
) -> None:
    """Atomically publish one absent external directory; overwrite is impossible."""

    validate_calibration_artifact(
        artifact,
        code_revision=code_revision,
        implementation_manifest_hash=implementation_manifest_hash,
        provider_attempt_events=provider_attempt_events,
        provider_raw_root=provider_raw_root,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    validate_output_target(output_root)
    parent = output_root.parent
    pending = parent / f".{output_root.name}.pending"
    pending.mkdir()
    raw = _canonical_external_json_bytes(artifact, label="calibration artifact")
    try:
        artifact_path = pending / "m3-008b-deepseek-calibration.json"
        with artifact_path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        sidecar = f"{hashlib.sha256(raw).hexdigest()}  {artifact_path.name}\n".encode("ascii")
        with (pending / f"{artifact_path.name}.sha256").open("xb") as handle:
            handle.write(sidecar)
            handle.flush()
            os.fsync(handle.fileno())
        pending.rename(output_root)
    except Exception:
        if pending.exists() and not pending.is_symlink():
            for child in pending.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            pending.rmdir()
        raise


def validate_output_target(output_root: Path) -> None:
    """Fail before provider effects when append-only output cannot be safely created."""

    if not output_root.is_absolute() or output_root.resolve(strict=False).is_relative_to(
        REPOSITORY_ROOT
    ):
        raise DeepSeekCalibrationError("calibration output must be external")
    if output_root.exists() or output_root.is_symlink():
        raise DeepSeekCalibrationError("calibration output already exists")
    parent = output_root.parent
    _validate_external_ancestry(parent, output_root)
    ancestor = parent
    while True:
        if ancestor.exists() and ancestor.is_symlink():
            raise DeepSeekCalibrationError("symlinked output ancestry is forbidden")
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if not parent.is_dir():
        raise DeepSeekCalibrationError("calibration output parent must already exist")
    pending = parent / f".{output_root.name}.pending"
    if pending.exists() or pending.is_symlink():
        raise DeepSeekCalibrationError("calibration pending output already exists")


def _validate_external_ancestry(root: Path, target: Path) -> None:
    if not root.is_absolute() or not target.is_absolute():
        raise DeepSeekCalibrationError("external path must be absolute")
    resolved_root = root.resolve(strict=True)
    resolved_target = target.resolve(strict=False)
    if not resolved_target.is_relative_to(resolved_root):
        raise DeepSeekCalibrationError("external path escapes intended root")
    current = target
    while True:
        if current.exists() or current.is_symlink():
            info = os.lstat(current)
            attributes = getattr(info, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if current.is_symlink() or attributes & reparse_flag:
                raise DeepSeekCalibrationError("external path ancestry is reparse-backed")
        if current == current.parent:
            break
        current = current.parent


def _validated_provider_raw_path(raw_root: Path, relative_path: str) -> Path:
    """Resolve one canonical raw binding beneath an exact non-reparse root."""

    if not provider_raw_relative_path_is_canonical(relative_path):
        raise DeepSeekCalibrationError("provider raw relative path is noncanonical")
    path = raw_root / relative_path
    try:
        if not raw_root.is_absolute() or not raw_root.is_dir():
            raise DeepSeekCalibrationError("provider raw root is invalid")
        _validate_external_ancestry(raw_root, path)
        if not path.is_file():
            raise DeepSeekCalibrationError("provider raw evidence file is missing")
        current = raw_root
        for component in relative_path.split("/"):
            exact_entry = next(
                (entry for entry in current.iterdir() if entry.name == component),
                None,
            )
            if exact_entry is None:
                raise DeepSeekCalibrationError("provider raw path casing differs from directory")
            current = exact_entry
        if current != path:
            raise DeepSeekCalibrationError("provider raw path entry reconstruction drift")
    except DeepSeekCalibrationError:
        raise
    except (OSError, RuntimeError):
        raise DeepSeekCalibrationError("provider raw evidence path is invalid") from None
    return path


def _read_ledger_bound_provider_body(
    raw_root: Path,
    event: ProviderAttemptEvent,
    *,
    missing_message: str,
    drift_message: str,
) -> bytes:
    """Read one bounded body only after canonical containment/topology admission."""

    relative_path = event.body_relative_path
    if relative_path is None:
        raise DeepSeekCalibrationError(missing_message)
    try:
        path = _validated_provider_raw_path(raw_root, relative_path)
    except DeepSeekCalibrationError:
        raise DeepSeekCalibrationError(missing_message) from None
    try:
        with path.open("rb") as handle:
            raw = handle.read(131_073)
    except OSError:
        raise DeepSeekCalibrationError(missing_message) from None
    if len(raw) > 131_072 or event.body_byte_count != len(raw) or event.body_hash != _sha256(raw):
        raise DeepSeekCalibrationError(drift_message)
    return raw


def _validate_pending_run(run: PendingCalibrationRun) -> None:
    if type(run) is not PendingCalibrationRun:
        raise DeepSeekCalibrationError("pending run type is invalid")
    if run.output_root.exists() or run.output_root.is_symlink():
        raise DeepSeekCalibrationError("pending run output target is no longer absent")
    if not run.pending_root.is_dir() or run.pending_root.is_symlink():
        raise DeepSeekCalibrationError("pending run directory is invalid")
    if run.pending_root != run.output_root.parent / f".{run.output_root.name}.pending":
        raise DeepSeekCalibrationError("pending run path drift")
    expected_attempted = [
        f"M3-008B-CAL-{index:03d}" for index in range(1, len(run.attempted_case_ids) + 1)
    ]
    expected_successful = expected_attempted[: len(run.successful_case_ids)]
    if run.attempted_case_ids != expected_attempted:
        raise DeepSeekCalibrationError("pending attempted case identity drift")
    if run.successful_case_ids != expected_successful:
        raise DeepSeekCalibrationError("pending successful case identity drift")
    expected_files = (
        {"run-configuration.json"}
        | {
            f"case-{index:03d}-evidence.json"
            for index in range(1, len(run.successful_case_ids) + 1)
        }
        | set(run.raw_body_paths)
    )
    children = tuple(run.pending_root.iterdir())
    if {child.name for child in children} != expected_files or any(
        not child.is_file() or child.is_symlink() for child in children
    ):
        raise DeepSeekCalibrationError("pending run file inventory drift")


def _redacted_failure(error: Exception) -> dict[str, object]:
    code = "internal_failure"
    status: int | None = None
    if type(error) is DeepSeekSemanticEvaluatorError:
        observed_code = object.__getattribute__(error, "code")
        observed_status = object.__getattribute__(error, "status_code")
        if hasattr(observed_code, "value") and type(observed_code.value) is str:
            code = observed_code.value
        if type(observed_status) is int and 100 <= observed_status <= 599:
            status = observed_status
    elif type(error) is DeepSeekCalibrationError:
        code = "calibration_contract_error"
    return {"code": code, "status_code": status}


def _write_new_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_new_bytes(path, _canonical_external_json_bytes(payload, label="run evidence"))


def _write_new_bytes(path: Path, raw: bytes) -> None:
    if type(raw) is not bytes or len(raw) > 40_000_000:
        raise DeepSeekCalibrationError("run evidence bytes are invalid")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        raise


def _support(value: object) -> SemanticSupport:
    if type(value) is not str:
        raise DeepSeekCalibrationError("human state is invalid")
    try:
        return SemanticSupport(value)
    except ValueError:
        raise DeepSeekCalibrationError("human state is invalid") from None


def _case_inventory_identity(cases: Sequence[FrozenCalibrationCase]) -> str:
    inventory = [
        {
            "case_id": case.case_id,
            "category": case.category,
            "source": case.source,
            "citation_relationship": case.citation_relationship,
            "semantic_request_hash": case.semantic_request_hash,
            "stage1_admission_identity": case.stage1_admission_identity,
            "immutable_projection_hash": case.immutable_projection_hash,
            "human_expected_state": case.human_expected_state.value,
        }
        for case in cases
    ]
    return _sha256(_canonical_bytes(inventory))


def _code_revision(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DeepSeekCalibrationError("code revision must be exact lowercase 40-hex")
    return value


def _digest(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise DeepSeekCalibrationError(f"{field} must be a lowercase sha256 digest")
    return value


def _artifact_metrics(cases: Sequence[tuple[str, str, str]]) -> dict[str, object]:
    confusion = {
        human.value: {predicted.value: 0 for predicted in SemanticSupport}
        for human in SemanticSupport
    }
    categories: Counter[str] = Counter()
    agreements = 0
    for human, predicted, category in cases:
        confusion[human][predicted] += 1
        categories[category] += 1
        agreements += human == predicted
    state_metrics: dict[str, object] = {}
    counts_pass = True
    recalls_pass = True
    for state in SemanticSupport:
        denominator = sum(confusion[state.value].values())
        recall = confusion[state.value][state.value] / denominator if denominator else 0.0
        state_metrics[state.value] = {"n": denominator, "recall": recall}
        counts_pass &= denominator >= 8
        recalls_pass &= recall >= 0.75
    zero = confusion["unsupported"]["supported"] == 0 and confusion["uncertain"]["supported"] == 0
    rate = agreements / CASE_COUNT
    return {
        "semantic_contract_version": SEMANTIC_EVALUATION_V2_CONTRACT_VERSION,
        "semantic_contract_hash": SEMANTIC_EVALUATION_V2_CONTRACT_HASH,
        "routing_policy_hash": REVIEW_ROUTING_POLICY_HASH,
        "routing_matrix_hash": SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH,
        "agreement_count": agreements,
        "denominator": CASE_COUNT,
        "agreement_rate": rate,
        "confusion_matrix": confusion,
        "human_state_metrics": state_metrics,
        "categories_exercised": sorted(categories),
        "category_counts": dict(sorted(categories.items())),
        "zero_tolerance_passed": zero,
        "human_state_counts_passed": counts_pass,
        "human_state_recall_passed": recalls_pass,
        "accepted": zero and rate >= 0.85 and counts_pass and recalls_pass,
    }


def _hex_bytes(value: object, maximum: int) -> bytes:
    if type(value) is not str or len(value) > maximum * 2:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid")
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid") from None
    if len(raw) > maximum or raw.hex() != value:
        raise DeepSeekCalibrationError("calibration byte evidence is invalid")
    return raw


def _utc(value: object) -> datetime:
    if type(value) is not str:
        raise DeepSeekCalibrationError("calibration timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise DeepSeekCalibrationError("calibration timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DeepSeekCalibrationError("calibration timestamp must be UTC")
    return parsed


class _DuplicateKeyError(ValueError):
    pass


class _NonFiniteJsonNumberError(ValueError):
    pass


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError
        value[key] = item
    return value
