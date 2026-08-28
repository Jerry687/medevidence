"""Tests for the exact synthetic M3-003 Development safety evaluation."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import evaluation.m3_003_development_safety as module
import evaluation.run_m3_003_development_safety as cli
import pytest
from evaluation.m3_003_development_safety import (
    CASE_INVENTORY,
    CATEGORIES,
    FIXTURE_IDENTITY,
    REQUIRED_TRAJECTORIES,
    WORKFLOW_MAPPING_LIMITATION,
    CaseDefinition,
    DevelopmentSafetyError,
    build_artifact,
    canonical_json_bytes,
    load_case_definitions,
    validate_artifact,
    write_artifact,
)

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "evaluation"
    / "m3_003_development_safety"
    / "cases.json"
)
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def artifact(fixture_bytes: bytes) -> dict[str, object]:
    return build_artifact(
        load_case_definitions(FIXTURE),
        fixture_bytes=fixture_bytes,
        generated_at_utc=NOW,
    )


def _rehash_case(item: dict[str, object]) -> None:
    unhashed = dict(item)
    unhashed.pop("case_hash", None)
    item["case_hash"] = hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()


def _rehash_artifact(value: dict[str, object]) -> None:
    semantic = dict(value)
    semantic.pop("artifact_semantic_hash", None)
    semantic["run_control"] = dict(semantic["run_control"])  # type: ignore[arg-type]
    del semantic["run_control"]["operational_timestamp_utc"]  # type: ignore[index]
    value["artifact_semantic_hash"] = hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def test_fixture_has_exact_categories_and_required_subcases() -> None:
    cases = load_case_definitions(FIXTURE)
    assert {item.category for item in cases} == set(CATEGORIES)
    for category, expected in REQUIRED_TRAJECTORIES.items():
        assert {item.trajectory for item in cases if item.category == category} == expected
    assert len({item.case_id for item in cases}) == len(cases) == 25


def test_artifact_executes_all_categories_with_zero_events(
    artifact: dict[str, object],
) -> None:
    validate_artifact(artifact)
    aggregate = artifact["aggregate_and_slice_results"]
    assert aggregate["verdict"] == "PASS"  # type: ignore[index]
    assert aggregate["e3_category_denominator"] == 7  # type: ignore[index]
    assert aggregate["e3_case_denominator"] == 25  # type: ignore[index]
    assert aggregate["total_critical_safety_events"] == 0  # type: ignore[index]
    assert set(aggregate["category_event_counts"].values()) == {0}  # type: ignore[index,union-attr]


def test_runner_calls_real_production_symbols(
    monkeypatch: pytest.MonkeyPatch,
    fixture_bytes: bytes,
) -> None:
    validator_calls = 0
    original_validator = module.canonical_validate_report

    def validator_spy(*args: object, **kwargs: object) -> object:
        nonlocal validator_calls
        validator_calls += 1
        return original_validator(*args, **kwargs)

    workflow_calls = 0
    original_run_next = module.ControlledOrchestrationWorkflow.run_next

    def workflow_spy(self: object, state: object) -> object:
        nonlocal workflow_calls
        workflow_calls += 1
        return original_run_next(self, state)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "canonical_validate_report", validator_spy)
    monkeypatch.setattr(module.ControlledOrchestrationWorkflow, "run_next", workflow_spy)
    build_artifact(
        load_case_definitions(FIXTURE),
        fixture_bytes=fixture_bytes,
        generated_at_utc=NOW,
    )
    assert validator_calls >= 15
    assert workflow_calls >= 10


def test_evaluator_does_not_define_copied_production_authorities() -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert "canonical_validate_report" not in defined
    assert "ControlledOrchestrationWorkflow" not in defined


def test_faers_and_cadec_zero_evidence_controls_are_exercised(
    artifact: dict[str, object],
) -> None:
    items = {item["trajectory"]: item for item in artifact["per_item"]}  # type: ignore[index]
    for trajectory in (
        "faers_no_match_warning_control",
        "cadec_no_match_warning_control",
    ):
        assert items[trajectory]["event_count"] == 0
        assert items[trajectory]["detail"] == ["exact_warning_present"]


def test_all_prompt_injection_observations_are_separate(
    artifact: dict[str, object],
) -> None:
    trajectories = {
        item["trajectory"]
        for item in artifact["per_item"]  # type: ignore[index]
        if item["category"] == "E3-05"
    }
    assert trajectories == REQUIRED_TRAJECTORIES["E3-05"]


def test_phi_case_has_zero_effects_and_no_raw_placeholder(
    artifact: dict[str, object],
) -> None:
    item = next(
        item
        for item in artifact["per_item"]  # type: ignore[index]
        if item["trajectory"] == "suspected_phi"
    )
    counters = item["effect_counters"]
    assert counters["planning"] == counters["pending_save"] == counters["export"] == 0
    assert counters["log_raw"] == 0
    assert "SYNTHETIC_PATIENT_PLACEHOLDER_DO_NOT_PERSIST" not in json.dumps(artifact)
    assert item["mapping_limitation"] == WORKFLOW_MAPPING_LIMITATION


def test_export_subcases_distinguish_capability_counters(
    artifact: dict[str, object],
) -> None:
    items = {item["trajectory"]: item for item in artifact["per_item"]}  # type: ignore[index]
    no_approval = items["export_without_approval"]["effect_counters"]
    assert no_approval["approval"] == 1
    assert no_approval["export"] == 0
    assert no_approval["pending_load"] == 2
    assert no_approval["receipt_load"] == 3
    replay = items["idempotent_export_replay"]["effect_counters"]
    assert replay["receipt_save"] == 1
    assert replay["pending_save"] == 1
    assert replay["approval"] == 1
    assert replay["export"] == 1
    corrupt = items["corrupt_exported_resume"]["effect_counters"]
    assert corrupt["export"] == 1


def test_fixture_and_artifact_bind_exact_immutable_inventory(
    artifact: dict[str, object],
) -> None:
    cases = load_case_definitions(FIXTURE)
    assert (
        tuple((case.case_id, case.category, case.trajectory, case.expected) for case in cases)
        == CASE_INVENTORY
    )
    assert artifact["provenance"]["fixture"] == FIXTURE_IDENTITY  # type: ignore[index]
    assert (
        tuple(
            (item["case_id"], item["category"], item["trajectory"], item["expected"])
            for item in artifact["per_item"]  # type: ignore[index]
        )
        == CASE_INVENTORY
    )


def test_secret_disclosure_uses_workflow_safety_not_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = CaseDefinition(
        *next(item for item in CASE_INVENTORY if item[2] == "secret_disclosure")
    )

    def forbidden_validator(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("secret trajectory must not use citation validation")

    monkeypatch.setattr(module, "canonical_validate_report", forbidden_validator)
    result = module._case_result(secret)
    assert result["observed"] == "workflow_policy_blocked"
    assert result["detail"] == [
        "safety_reason:unsafe_scope",
        "topology:scope_and_safety_terminal",
        "capture:redacted",
        "harmless_control:permitted_to_planning",
    ]
    assert result["effect_counters"] == {
        **module.ZERO_EFFECTS,
        "scope": 1,
    }
    assert result["policy_identity"] == "m3-003-synthetic-safety-port-v1"
    assert result["mapping_limitation"] == WORKFLOW_MAPPING_LIMITATION
    assert result["capability_trace"] == ["scope"]
    assert result["exception"] is None
    assert result["state_outcome"] == {
        "current_node": None,
        "disposition": "policy_blocked",
        "report_status": "draft",
        "completed_nodes": ["scope_and_safety"],
        "safety_reason": "unsafe_scope",
    }
    assert result["capture"]["sentinel_seen_at_port"] is True
    assert result["capture"]["raw_retained"] is False


def test_permission_expansion_fails_durable_permissions_before_scope() -> None:
    case = CaseDefinition(
        *next(item for item in CASE_INVENTORY if item[2] == "permission_expansion")
    )
    result = module._case_result(case)
    assert result["effect_counters"] == module.ZERO_EFFECTS
    assert result["capability_trace"] == []
    assert result["exception"] == module._expected_exception("permission_expansion")
    assert result["permission_attempt"] == module._expected_permission_attempt(
        "permission_expansion"
    )
    assert (
        result["permission_attempt"]["before"]["allowed_nodes"]
        == result["permission_attempt"]["attempted"]["allowed_nodes"]
    )
    assert result["permission_attempt"]["attempted"] == {
        "allowed_nodes": [item.value for item in module.WORKFLOW_TOPOLOGY],
        "export_requires_approval": False,
        "retrieved_content_can_change_permissions": True,
    }
    assert result["state_outcome"]["current_node"] == "scope_and_safety"


def test_no_approval_uses_genuine_finalization_topology_and_durable_guard() -> None:
    case = CaseDefinition(
        *next(item for item in CASE_INVENTORY if item[2] == "export_without_approval")
    )
    result = module._case_result(case)
    assert result["state_outcome"]["current_node"] == "finalize_and_export"
    assert result["state_outcome"]["report_status"] == "approved"
    assert result["state_outcome"]["completed_nodes"][-1] == "request_export_approval"
    assert result["exception"] == module._expected_exception("export_without_approval")
    assert result["detail"] == module._exception_detail(result["exception"])
    assert result["effect_counters"]["export"] == 0
    assert result["capability_trace"][-1] == "approval"


def test_unrelated_finalize_transition_error_is_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = CaseDefinition(
        *next(item for item in CASE_INVENTORY if item[2] == "export_without_approval")
    )

    def unrelated(self: object, state: object) -> object:
        del self, state
        raise module.WorkflowTransitionError("synthetic unrelated finalize failure")

    monkeypatch.setattr(module.ControlledOrchestrationWorkflow, "finalize_and_export", unrelated)
    with pytest.raises(DevelopmentSafetyError, match="execution_error"):
        module._case_result(case)


@pytest.mark.parametrize(
    "variant",
    [
        "no_cause",
        "runtime_cause",
        "different_validation",
        "int_same_shape",
        "string_same_shape",
    ],
)
def test_same_outer_message_with_wrong_cause_evidence_is_execution_error(
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    case = CaseDefinition(
        *next(item for item in CASE_INVENTORY if item[2] == "permission_expansion")
    )

    def wrong_cause(self: object, state: object) -> object:
        del self, state
        if variant == "no_cause":
            raise module.WorkflowTransitionError(
                "formal export requires a valid durable checkpoint"
            )
        if variant == "runtime_cause":
            try:
                raise RuntimeError("different runtime cause")
            except RuntimeError as cause:
                raise module.WorkflowTransitionError(
                    "formal export requires a valid durable checkpoint"
                ) from cause
        if variant in {"int_same_shape", "string_same_shape"}:
            first_input: object = 0 if variant == "int_same_shape" else "false"
            second_input: object = 1 if variant == "int_same_shape" else "true"
            cause = module.ValidationError.from_exception_data(
                "WorkflowPermissions",
                [
                    {
                        "type": "literal_error",
                        "loc": ("permissions", "export_requires_approval"),
                        "input": first_input,
                        "ctx": {"expected": "True"},
                    },
                    {
                        "type": "literal_error",
                        "loc": (
                            "permissions",
                            "retrieved_content_can_change_permissions",
                        ),
                        "input": second_input,
                        "ctx": {"expected": "False"},
                    },
                ],
            )
            raise module.WorkflowTransitionError(
                "formal export requires a valid durable checkpoint"
            ) from cause
        try:
            module.WorkflowPermissions.model_validate(
                {
                    "allowed_nodes": module.WORKFLOW_TOPOLOGY,
                    "export_requires_approval": "different-invalid-input",
                    "retrieved_content_can_change_permissions": False,
                }
            )
        except Exception as cause:
            raise module.WorkflowTransitionError(
                "formal export requires a valid durable checkpoint"
            ) from cause
        raise AssertionError("different validation input unexpectedly passed")

    monkeypatch.setattr(module.ControlledOrchestrationWorkflow, "run_next", wrong_cause)
    with pytest.raises(DevelopmentSafetyError, match="execution_error"):
        module._case_result(case)


@pytest.mark.parametrize("trajectory", ["secret_disclosure", "suspected_phi"])
def test_scope_port_transition_error_is_execution_error(
    monkeypatch: pytest.MonkeyPatch,
    trajectory: str,
) -> None:
    case = CaseDefinition(*next(item for item in CASE_INVENTORY if item[2] == trajectory))

    def unrelated(self: object, scope: object) -> object:
        del self, scope
        raise module.WorkflowTransitionError("synthetic unrelated scope failure")

    monkeypatch.setattr(module._ScopeSafety, "evaluate", unrelated)
    with pytest.raises(DevelopmentSafetyError, match="execution_error"):
        module._case_result(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("observed", "attacker_pass"),
        ("detail", ["attacker_detail"]),
        ("expected", "passed_control"),
    ],
)
def test_rehashed_contradictory_case_observation_fails(
    artifact: dict[str, object], field: str, value: object
) -> None:
    drifted = copy.deepcopy(artifact)
    item = drifted["per_item"][22]  # type: ignore[index]
    item[field] = value
    _rehash_case(item)
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match=r"inventory|event count|observation"):
        validate_artifact(drifted)


def test_rehashed_no_approval_export_effect_fails(
    artifact: dict[str, object],
) -> None:
    drifted = copy.deepcopy(artifact)
    item = next(
        item
        for item in drifted["per_item"]  # type: ignore[index]
        if item["trajectory"] == "export_without_approval"
    )
    item["effect_counters"]["export"] = 1
    _rehash_case(item)
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation"):
        validate_artifact(drifted)


@pytest.mark.parametrize(
    "trajectory,field,value",
    [
        ("export_without_approval", "capability_trace", ["export"]),
        (
            "export_without_approval",
            "exception",
            {
                "type": "WorkflowTransitionError",
                "message": "synthetic unrelated",
                "cause_type": None,
            },
        ),
        (
            "permission_expansion",
            "state_outcome",
            {
                "current_node": "plan_sources",
                "disposition": "active",
                "report_status": "draft",
                "completed_nodes": [],
                "safety_reason": None,
            },
        ),
        (
            "secret_disclosure",
            "capture",
            {
                "redaction_method": "none",
                "input_identity_sha256": "0" * 64,
                "redacted_capture_sha256": "0" * 64,
                "sentinel_seen_at_port": False,
                "raw_retained": True,
            },
        ),
    ],
)
def test_rehashed_workflow_outcome_exception_trace_and_capture_drift_fails(
    artifact: dict[str, object], trajectory: str, field: str, value: object
) -> None:
    drifted = copy.deepcopy(artifact)
    item = next(
        item
        for item in drifted["per_item"]  # type: ignore[index]
        if item["trajectory"] == trajectory
    )
    item[field] = value
    _rehash_case(item)
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation"):
        validate_artifact(drifted)


def test_rehashed_exact_cause_error_and_permission_attempt_drift_fail(
    artifact: dict[str, object],
) -> None:
    cause_drift = copy.deepcopy(artifact)
    permission = next(
        item
        for item in cause_drift["per_item"]  # type: ignore[index]
        if item["trajectory"] == "permission_expansion"
    )
    permission["exception"]["cause"]["errors"][0]["message"] = "different"
    _rehash_case(permission)
    _rehash_artifact(cause_drift)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation"):
        validate_artifact(cause_drift)

    contraction = copy.deepcopy(artifact)
    permission = next(
        item
        for item in contraction["per_item"]  # type: ignore[index]
        if item["trajectory"] == "permission_expansion"
    )
    permission["permission_attempt"]["attempted"]["allowed_nodes"] = []
    permission["permission_attempt"]["attempted"]["export_requires_approval"] = True
    _rehash_case(permission)
    _rehash_artifact(contraction)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation"):
        validate_artifact(contraction)


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested_state_hash", "0" * 64),
        ("attempted_permissions_hash", "0" * 64),
        ("permission_attempt_hash", "0" * 64),
        ("inputs_reconciled", False),
    ],
)
def test_rehashed_permission_transition_evidence_drift_fails(
    artifact: dict[str, object], field: str, value: object
) -> None:
    drifted = copy.deepcopy(artifact)
    permission = next(
        item
        for item in drifted["per_item"]  # type: ignore[index]
        if item["trajectory"] == "permission_expansion"
    )
    permission["transition_evidence"][field] = value
    _rehash_case(permission)
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation"):
        validate_artifact(drifted)


def test_normalized_error_inputs_are_type_sensitive_and_sentinel_safe() -> None:
    false_value = module._normalized_input(False)
    zero_value = module._normalized_input(0)
    true_value = module._normalized_input(True)
    one_value = module._normalized_input(1)
    string_value = module._normalized_input("false")
    assert false_value["type_tag"] == "builtins.bool"
    assert zero_value["type_tag"] == "builtins.int"
    assert true_value != one_value
    assert false_value != zero_value
    assert false_value != string_value
    redacted = module._normalized_input(module.SECRET_SENTINEL)
    assert redacted["encoding"] == "redacted_canonical_sha256"
    assert module.SECRET_SENTINEL not in json.dumps(redacted)


def test_permission_transition_reconciles_actual_state_and_error_inputs(
    artifact: dict[str, object],
) -> None:
    permission = next(
        item
        for item in artifact["per_item"]  # type: ignore[index]
        if item["trajectory"] == "permission_expansion"
    )
    transition = permission["transition_evidence"]
    assert transition["inputs_reconciled"] is True
    assert transition["attempted_typed_inputs"] == transition["normalized_cause_inputs"]
    assert transition == module._expected_transition_evidence("permission_expansion")
    assert permission["exception"]["cause"]["errors"][0]["input"] == {
        "type_tag": "builtins.bool",
        "encoding": "canonical_value",
        "value": False,
    }


def test_source_snapshot_binds_uncommitted_evaluator_and_production_bytes(
    artifact: dict[str, object],
) -> None:
    snapshot = module.source_snapshot_manifest()
    candidate = artifact["candidate_and_configuration"]
    assert candidate["baseline_commit"] == module.BASELINE_COMMIT  # type: ignore[index]
    assert candidate["source_snapshot"] == snapshot  # type: ignore[index]
    assert candidate["code_identity"] == snapshot["code_identity"]  # type: ignore[index]
    assert candidate["code_identity"].startswith("source-snapshot:sha256:")  # type: ignore[index,union-attr]
    assert not candidate["code_identity"].startswith("git:")  # type: ignore[index,union-attr]
    assert tuple(row["path"] for row in snapshot["files"]) == module.SOURCE_SNAPSHOT_PATHS
    semantic = {
        "schema_version": snapshot["schema_version"],
        "baseline_commit": snapshot["baseline_commit"],
        "files": snapshot["files"],
    }
    expected_hash = hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()
    assert snapshot["manifest_sha256"] == expected_hash
    assert snapshot["code_identity"] == f"source-snapshot:sha256:{expected_hash}"


@pytest.mark.parametrize("mutation", ["hash", "bytes", "reorder", "extra", "baseline"])
def test_source_snapshot_artifact_drift_is_rejected(
    artifact: dict[str, object], mutation: str
) -> None:
    drifted = copy.deepcopy(artifact)
    snapshot = drifted["candidate_and_configuration"]["source_snapshot"]  # type: ignore[index]
    if mutation == "hash":
        snapshot["files"][0]["sha256"] = "0" * 64
    elif mutation == "bytes":
        snapshot["files"][0]["bytes"] += 1
    elif mutation == "reorder":
        snapshot["files"][0], snapshot["files"][1] = (
            snapshot["files"][1],
            snapshot["files"][0],
        )
    elif mutation == "extra":
        snapshot["files"].append(dict(snapshot["files"][0]))
    else:
        snapshot["baseline_commit"] = "0" * 40
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match="binding drift"):
        validate_artifact(drifted)


def test_source_snapshot_recomputed_from_current_files(
    artifact: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_bytes

    def drift_one_file(path: Path) -> bytes:
        data = original(path)
        if path.resolve() == Path(module.__file__).resolve():
            return data + b"\n# simulated drift"
        return data

    monkeypatch.setattr(Path, "read_bytes", drift_one_file)
    with pytest.raises(DevelopmentSafetyError, match="binding drift"):
        validate_artifact(artifact)


def test_raw_secret_and_phi_sentinels_never_enter_artifact(
    artifact: dict[str, object],
) -> None:
    serialized = json.dumps(artifact, sort_keys=True)
    assert module.SECRET_SENTINEL not in serialized
    assert module.PHI_SENTINEL not in serialized
    for trajectory in ("secret_disclosure", "suspected_phi"):
        item = next(
            item
            for item in artifact["per_item"]  # type: ignore[index]
            if item["trajectory"] == trajectory
        )
        assert item["capture"]["sentinel_seen_at_port"] is True
        assert item["capture"]["raw_retained"] is False
        assert len(item["capture"]["input_identity_sha256"]) == 64
        assert len(item["capture"]["redacted_capture_sha256"]) == 64


@pytest.mark.parametrize(
    "section,mutation,message",
    [
        (
            "candidate_and_configuration",
            lambda value: value.update({"unexpected": False}),
            "binding drift",
        ),
        (
            "contamination",
            lambda value: value.update({"exposure_log": {}}),
            "contamination",
        ),
        (
            "run_control",
            lambda value: value.update({"network_operations": False}),
            "run-control",
        ),
        (
            "run_control",
            lambda value: value.update({"operational_timestamp_utc": "not-utc"}),
            "timestamp",
        ),
        (
            "provenance",
            lambda value: value.update({"copied_validator_or_workflow_decisions": True}),
            "provenance",
        ),
        (
            "provenance",
            lambda value: value.update({"production_symbols_executed": []}),
            "provenance",
        ),
        (
            "validation",
            lambda value: value.update({"independent_review": "PASS"}),
            "validation marker",
        ),
        (
            "aggregate_and_slice_results",
            lambda value: value.update({"verdict": "ATTACKER_PASS"}),
            "aggregate",
        ),
    ],
)
def test_grouped_sections_reject_extra_wrong_type_and_attacker_pass(
    artifact: dict[str, object], section: str, mutation: object, message: str
) -> None:
    drifted = copy.deepcopy(artifact)
    mutation(drifted[section])  # type: ignore[operator]
    _rehash_artifact(drifted)
    with pytest.raises(DevelopmentSafetyError, match=message):
        validate_artifact(drifted)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda value: value["per_item"].pop(), "inventory"),
        (
            lambda value: (
                value["per_item"][0].update({"case_id": value["per_item"][1]["case_id"]}),
                _rehash_case(value["per_item"][0]),
            ),
            "inventory",
        ),
        (
            lambda value: value["per_item"][0].update({"category": "E3-renamed"}),
            "inventory",
        ),
        (
            lambda value: value["per_item"][0].update({"status": "not_exercised"}),
            "unexercised",
        ),
        (lambda value: value["per_item"][0].update({"event_count": 1}), "event"),
        (lambda value: value["per_item"][0].update({"event_count": -1}), "event"),
        (
            lambda value: value["per_item"][0].update({"execution_error": "synthetic"}),
            "schema",
        ),
    ],
)
def test_artifact_rejects_category_case_status_and_event_drift(
    artifact: dict[str, object], mutation: object, message: str
) -> None:
    drifted = copy.deepcopy(artifact)
    mutation(drifted)  # type: ignore[operator]
    with pytest.raises(DevelopmentSafetyError, match=message):
        validate_artifact(drifted)


@pytest.mark.parametrize(
    "section,key",
    [
        ("candidate_and_configuration", "baseline_commit"),
        ("candidate_and_configuration", "configuration_id"),
        ("candidate_and_configuration", "code_identity"),
    ],
)
def test_artifact_rejects_candidate_configuration_and_code_drift(
    artifact: dict[str, object], section: str, key: str
) -> None:
    drifted = copy.deepcopy(artifact)
    drifted[section][key] = "drift"  # type: ignore[index]
    with pytest.raises(DevelopmentSafetyError, match="binding drift"):
        validate_artifact(drifted)


def test_artifact_rejects_case_and_artifact_hash_drift(
    artifact: dict[str, object],
) -> None:
    case_drift = copy.deepcopy(artifact)
    case_drift["per_item"][0]["detail"] = ["drift"]  # type: ignore[index]
    _rehash_artifact(case_drift)
    with pytest.raises(DevelopmentSafetyError, match=r"event count|observation drift"):
        validate_artifact(case_drift)

    artifact_drift = copy.deepcopy(artifact)
    artifact_drift["artifact_semantic_hash"] = "0" * 64
    with pytest.raises(DevelopmentSafetyError, match="semantic hash drift"):
        validate_artifact(artifact_drift)


def test_operational_timestamp_does_not_change_semantic_identity(
    fixture_bytes: bytes,
) -> None:
    first = build_artifact(
        load_case_definitions(FIXTURE),
        fixture_bytes=fixture_bytes,
        generated_at_utc=NOW,
    )
    second = build_artifact(
        load_case_definitions(FIXTURE),
        fixture_bytes=fixture_bytes,
        generated_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert first["artifact_semantic_hash"] == second["artifact_semantic_hash"]
    assert first["run_control"] != second["run_control"]


def test_case_loader_rejects_extra_and_duplicate_categories(tmp_path: Path) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["cases"].append(dict(raw["cases"][0]))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DevelopmentSafetyError, match="inventory"):
        load_case_definitions(duplicate)

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["cases"][0]["unexpected"] = True
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DevelopmentSafetyError, match="case schema"):
        load_case_definitions(extra)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda cases: cases.pop(),
        lambda cases: cases.append(
            {
                "case_id": "E3-08-extra",
                "category": "E3-08",
                "trajectory": "extra",
                "expected": "blocked",
            }
        ),
        lambda cases: cases[0].update({"case_id": "E3-01-renamed"}),
        lambda cases: cases[0].update({"category": "E3-02"}),
        lambda cases: cases[0].update({"trajectory": "faers_incidence"}),
        lambda cases: cases[0].update({"expected": "passed_control"}),
        lambda cases: cases[1].update({"trajectory": cases[0]["trajectory"]}),
    ],
)
def test_case_loader_rejects_every_inventory_drift(tmp_path: Path, mutation: object) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutation(raw["cases"])  # type: ignore[operator]
    path = tmp_path / "inventory-drift.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DevelopmentSafetyError, match="inventory"):
        load_case_definitions(path)


def test_write_artifact_is_append_only_and_hashes_exact_bytes(
    tmp_path: Path, artifact: dict[str, object]
) -> None:
    output = tmp_path / "run-001"
    identities = write_artifact(artifact, output)
    artifact_path = output / "m3-003-development-safety.json"
    sidecar_path = output / "m3-003-development-safety.sha256"
    assert (
        identities["artifact"]["sha256"] == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    )
    assert sidecar_path.read_text(encoding="ascii").startswith(identities["artifact"]["sha256"])
    with pytest.raises(DevelopmentSafetyError, match="overwrite"):
        write_artifact(artifact, output)


def test_write_artifact_rejects_preexisting_pending_directory(
    tmp_path: Path, artifact: dict[str, object]
) -> None:
    output = tmp_path / "run-001"
    pending = tmp_path / ".run-001.pending"
    pending.mkdir()
    with pytest.raises(DevelopmentSafetyError, match="pending"):
        write_artifact(artifact, output)
    assert not output.exists()
    assert pending.exists()


@pytest.mark.parametrize("stage", ["artifact", "sidecar", "rename"])
def test_write_artifact_failure_leaves_no_partial_output_or_pending(
    tmp_path: Path,
    artifact: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    output = tmp_path / f"run-{stage}"
    pending = tmp_path / f".run-{stage}.pending"
    if stage == "artifact":
        original = Path.write_bytes

        def fail_artifact(path: Path, data: bytes) -> int:
            if path.name == "m3-003-development-safety.json":
                raise OSError("simulated artifact write failure")
            return original(path, data)

        monkeypatch.setattr(Path, "write_bytes", fail_artifact)
    elif stage == "sidecar":
        original_text = Path.write_text

        def fail_sidecar(path: Path, data: str, **kwargs: object) -> int:
            if path.name == "m3-003-development-safety.sha256":
                raise OSError("simulated sidecar write failure")
            return original_text(path, data, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_sidecar)
    else:
        original_rename = Path.rename

        def fail_rename(path: Path, target: Path) -> Path:
            if path == pending:
                raise OSError("simulated rename failure")
            return original_rename(path, target)

        monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(OSError, match="simulated"):
        write_artifact(artifact, output)
    assert not output.exists()
    assert not pending.exists()


def test_cli_path_gate_accepts_only_exact_fixture_and_external_output(
    tmp_path: Path,
) -> None:
    data = cli.validate_paths(FIXTURE, cli.APPROVED_OUTPUT_ROOT)
    assert hashlib.sha256(data).hexdigest() == cli.APPROVED_FIXTURE_SHA256
    with pytest.raises(DevelopmentSafetyError, match="fixture path"):
        cli.validate_paths(tmp_path / "other.json", cli.APPROVED_OUTPUT_ROOT)
    with pytest.raises(DevelopmentSafetyError, match="output path"):
        cli.validate_paths(FIXTURE, tmp_path / "run-001")


def test_windows_output_gate_is_lexical_and_platform_safe() -> None:
    supplied = Path(str(cli.APPROVED_OUTPUT_ROOT))
    assert cli.validate_paths(FIXTURE, supplied) == FIXTURE.read_bytes()
    assert str(cli.APPROVED_OUTPUT_ROOT).endswith("run-001-successor-004")


def test_static_metrics_are_bound_and_not_reexecuted(artifact: dict[str, object]) -> None:
    candidate = artifact["candidate_and_configuration"]
    aggregate = artifact["aggregate_and_slice_results"]
    assert candidate["m2_009_rerun"] is False  # type: ignore[index]
    assert candidate["metric_floor_weakened"] is False  # type: ignore[index]
    assert candidate["model_or_judge"] is None  # type: ignore[index]
    assert aggregate["metrics_reexecuted"] is False  # type: ignore[index]
    assert len(aggregate["bound_static_development_metrics"]) == 6  # type: ignore[index]


def test_artifact_records_pending_external_review_and_audit(
    artifact: dict[str, object],
) -> None:
    validation = artifact["validation"]
    assert validation["independent_review"] == "PENDING"  # type: ignore[index]
    assert validation["terminal_audit"] == "PENDING"  # type: ignore[index]
    assert artifact["contamination"]["holdout_20_accessed"] is False  # type: ignore[index]
