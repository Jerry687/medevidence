"""Tests for the closed four-source application capability dispatcher."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast

import pytest

import medevidence.orchestration.source_capabilities as capabilities
from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    M1BResearchRequestV1,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourcePlanReasonCode,
    SourceType,
)
from medevidence.infrastructure.cadec_local_search import CanonicalCadecEvidenceCollection
from medevidence.orchestration.contracts import (
    ExportDestinationRef,
    OrchestrationState,
    SafetyDecision,
    SafetyOutcome,
    SafetyReason,
    SourceTaskAttemptRef,
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.dailymed_faers_capability import (
    CanonicalDailyMedProjectionAuthority,
    CanonicalFaersProjectionAuthority,
)
from medevidence.orchestration.source_capabilities import (
    SourceCapabilities,
    collect_cadec_capability,
    plan_cadec_operations,
    terminal_source_task,
)
from medevidence.tools.cadec_runtime import (
    CADEC_LIMITATION_WARNING,
    CadecRuntimeError,
    CadecRuntimeErrorCode,
    CadecSearchResult,
    CadecVerifiedCorpus,
    plan_cadec_local_search,
)
from medevidence.tools.contracts import ResearchPubMedRequest

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"


def _scope(*sources: SourceType) -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test reaction"),
        ),
        date_range=None,
        selected_sources=sources or (SourceType.CADEC,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _pending(source: SourceType) -> tuple[SourceTaskState, SourceTaskAttemptRef]:
    task = SourceTaskState(task_id=source_task_id(RUN_ID, source), source=source)
    return task, source_task_attempt(task.task_id, 1)


def _running_cadec() -> tuple[SourceTaskState, ResearchScope, SourceTaskAttemptRef]:
    scope = _scope(SourceType.CADEC)
    pending, attempt = _pending(SourceType.CADEC)
    operations = plan_cadec_operations(task=pending, scope=scope, attempt=attempt)
    running = SourceTaskState(
        task_id=pending.task_id,
        source=SourceType.CADEC,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    return running, scope, attempt


def _request(scope: ResearchScope) -> ResearchPubMedRequest:
    return ResearchPubMedRequest(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        run_id=RUN_ID,
        created_at_utc=datetime(2026, 8, 28, tzinfo=UTC),
        code_revision="a" * 40,
        scope=scope,
    )


def test_source_plan_identity_binds_skip_reason_and_missing_permitted_decision_fails() -> None:
    scope = _scope(SourceType.CADEC)
    selected = (
        M1BSourcePlanEntryV1(
            source=SourceType.CADEC,
            planning_status=PlanningStatus.SELECTED,
        ),
    )
    skipped = (
        M1BSourcePlanEntryV1(
            source=SourceType.CADEC,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="deterministic skip",
        ),
    )
    initial = OrchestrationState(
        workflow_id="workflow:test",
        checkpoint_id="checkpoint:test",
        run_id=RUN_ID,
        report_id="report:sha256:" + "a" * 64,
        original_scope=scope,
        destination=ExportDestinationRef(destination_id="destination:test"),
    )
    state = initial.model_copy(update={"interpreted_scope": scope, "source_plan": selected})
    authority = capabilities.CanonicalSourcePlanningAuthority(scope, selected)

    assert capabilities.source_plan_identity(selected) != capabilities.source_plan_identity(skipped)
    with pytest.raises(
        capabilities.SourceCapabilityContractError,
        match="requires a permitted decision",
    ):
        capabilities.replay_source_plan(authority, state)


def test_canonical_source_planning_authority_is_exact_final_slotted_and_immutable() -> None:
    scope = _scope(SourceType.CADEC)
    plan = (
        M1BSourcePlanEntryV1(
            source=SourceType.CADEC,
            planning_status=PlanningStatus.SELECTED,
        ),
    )
    authority = capabilities.CanonicalSourcePlanningAuthority(scope, plan)
    permitted = SafetyDecision(
        outcome=SafetyOutcome.PERMITTED,
        reason=SafetyReason.PERMITTED_RESEARCH_SCOPE,
        policy_version="policy:test",
    )

    assert not hasattr(authority, "__dict__")
    assert capabilities.CanonicalSourcePlanningAuthority.plan(authority, scope, permitted) == plan
    with pytest.raises(AttributeError, match="immutable"):
        authority.plan = lambda *_: ()  # type: ignore[method-assign]
    with pytest.raises(AttributeError, match="immutable"):
        authority._plan = ()  # type: ignore[misc]
    with pytest.raises(TypeError, match="authority is final"):

        class Subclass(capabilities.CanonicalSourcePlanningAuthority):  # type: ignore[misc]
            pass


def test_workflow_authority_rejects_ordinary_replaceable_planner_port() -> None:
    replaceable = SimpleNamespace(plan=lambda *_: ())

    with pytest.raises(
        capabilities.SourceCapabilityContractError,
        match="requires canonical source planning authority",
    ):
        capabilities.exact_source_planning_authority(replaceable)


def _canonical_projection_authorities(
    scope: ResearchScope,
) -> tuple[CanonicalDailyMedProjectionAuthority, CanonicalFaersProjectionAuthority]:
    selection = DailyMedSelectionRequestV1(
        drug_concept_id="rxnorm:1",
        requested_section_codes=("34084-4",),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )
    faers = FaersAggregateRequestV1(
        drug_concept_id="rxnorm:1",
        identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
        identity_exact_value="SYNTHETIC INGREDIENT",
        pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
        inclusive_date_range=FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        statistical_unit="provider_count_occurrence",
        execution_bounds=FaersExecutionBoundsV1(
            max_date_difference_days=365,
            max_inclusive_calendar_dates=366,
        ),
    )
    envelope = M1BResearchRequestV1(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        scope=scope,
        requested_sources=scope.selected_sources,
        dailymed_selection_requests=(selection,),
        faers_query_requests=(faers,),
    )

    class DailyProvenance:
        def load_discovery(self, **_values: object) -> object:
            raise AssertionError("production reachability smoke performs no discovery I/O")

        def load_fetch(self, **_values: object) -> object:
            raise AssertionError("production reachability smoke performs no fetch I/O")

    class FaersProvenance:
        def load_aggregate(self, **_values: object) -> object:
            raise AssertionError("production reachability smoke performs no FAERS I/O")

    return (
        CanonicalDailyMedProjectionAuthority(
            request=envelope,
            run_id=RUN_ID,
            limitations=("Synthetic DailyMed limitation.",),
            provenance=cast(object, DailyProvenance()),
            replay_store=cast(object, object()),
        ),
        CanonicalFaersProjectionAuthority(
            request=envelope,
            run_id=RUN_ID,
            provenance=cast(object, FaersProvenance()),
            replay_store=cast(object, object()),
        ),
    )


def _verified_corpus() -> CadecVerifiedCorpus:
    return CadecVerifiedCorpus(
        archive_sha256="4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a",
        archive_bytes=1_870_497,
        manifest_sha256="1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa",
        manifest_bytes=1_699_979,
        inventory_sha256="eabcff5564e2266bb8b749bf4b68c164d36aeb0b511fb775674baf762b9b10b8",
        inventory_entry_count=5_005,
        inventory_file_count=5_000,
        inventory_directory_count=5,
        inventory_uncompressed_bytes=1_627_015,
        canonical_document_count=1_250,
        canonical_document_sha256="0007626fa17053350628a9d3a619bceaada9db9a6e660e113fa6c4cd8681fb2a",
        approved_document_count=1_248,
        approved_document_sha256="7f168cc7496d2b140182e30d96afdf4367ce67f122e30447e0ecbbb17358cfa6",
        excluded_document_count=2,
        excluded_document_sha256="14b01844c6471d597e1b0c5e9a9483a32992b3c0a5158ef7966e171f42aa84dd",
        train_count=992,
        train_membership_sha256="e533c904637a86b447ce4cee5973b4041ff8de1679fcb073e78a0525835c8329",
        development_count=119,
        development_membership_sha256="dd219af2c42b717fb1df7d24b04de9bb031c099d4deb513091c6d49d4b2b799f",
        test_count=137,
        test_membership_sha256="6bf824a4fe7a708a836cf08b007734622bb02c2fecf0d1441febfb0103a3e26a",
        encoding_exception_verified=True,
        empty_document_count=2,
        malformed_row_count=5,
        original_reference_binding_limitation_count=2,
        meddra_reference_binding_limitation_count=44,
        sct_reference_binding_limitation_count=45,
        raw_out_of_order_transition_count=43,
        raw_out_of_order_document_count=26,
        provider_gold_only=True,
        predicted_artifact_admitted=False,
        output_document_count=1248,
        output_annotation_count=24_478,
        output_original_annotation_count=9_089,
        output_meddra_annotation_count=6_300,
        output_sct_annotation_count=9_089,
        output_locator_count=24_478,
        all_validation_passed=True,
    )


def _no_match_result(scope: ResearchScope) -> CadecSearchResult:
    plan = plan_cadec_local_search(scope)
    bounds = ExecutionBounds.from_scope(scope)
    return CadecSearchResult(
        scope_id=scope.scope_id,
        query=plan.query,
        query_id=plan.query_id,
        scope_bounds=bounds,
        documents_scored=1_246,
        verification=_verified_corpus(),
        evidence_refs=(),
        outcome=SourceOutcome(
            source=SourceType.CADEC,
            query_id=plan.query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.NO_MATCH,
            configured_bounds=bounds,
            valid_result_count=0,
            pages_completed=1,
            truncated=False,
            warning_codes=(CADEC_LIMITATION_WARNING,),
        ),
        limitations=tuple(CADEC_MANDATORY_LIMITATIONS),
    )


def test_static_dispatch_is_exact_sealed_and_uses_each_explicit_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(
        SourceType.PUBMED,
        SourceType.DAILYMED,
        SourceType.FAERS,
        SourceType.CADEC,
    )
    daily_authority, faers_authority = _canonical_projection_authorities(scope)
    dependencies = [object() for _ in range(7)]
    dispatcher = SourceCapabilities(
        pubmed_request=_request(scope),
        pubmed_service=cast(object, dependencies[0]),
        dailymed_projection=daily_authority,
        dailymed_execution=cast(object, dependencies[2]),
        faers_projection=faers_authority,
        faers_execution=cast(object, dependencies[4]),
        faers_persistence=cast(object, dependencies[5]),
    )
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def recorder(name: str, returned: object):
        def recorded(*args: object, **kwargs: object) -> object:
            calls.append((name, args, kwargs))
            return returned

        return recorded

    sentinels = {source: object() for source in SourceType}
    monkeypatch.setattr(capabilities, "plan_pubmed_operations", recorder("plan:pubmed", ()))
    monkeypatch.setattr(capabilities, "plan_dailymed_operations", recorder("plan:dailymed", ()))
    monkeypatch.setattr(capabilities, "plan_faers_operations", recorder("plan:faers", ()))
    monkeypatch.setattr(
        capabilities, "collect_pubmed", recorder("collect:pubmed", sentinels[SourceType.PUBMED])
    )
    monkeypatch.setattr(
        capabilities,
        "collect_dailymed_capability",
        recorder("collect:dailymed", sentinels[SourceType.DAILYMED]),
    )
    monkeypatch.setattr(
        capabilities,
        "collect_faers_capability",
        recorder("collect:faers", sentinels[SourceType.FAERS]),
    )

    for source in (SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS):
        task, attempt = _pending(source)
        assert dispatcher.plan_operations(task, scope, attempt) == ()
        assert dispatcher.collect(task, scope, attempt) is sentinels[source]

    assert [name for name, _args, _kwargs in calls] == [
        "plan:pubmed",
        "collect:pubmed",
        "plan:dailymed",
        "collect:dailymed",
        "plan:faers",
        "collect:faers",
    ]
    routed = {name: kwargs for name, _args, kwargs in calls}
    assert type(routed["plan:dailymed"]["projection"]) is (CanonicalDailyMedProjectionAuthority)
    assert type(routed["collect:dailymed"]["projection"]) is (CanonicalDailyMedProjectionAuthority)
    assert type(routed["plan:faers"]["projection"]) is CanonicalFaersProjectionAuthority
    assert type(routed["collect:faers"]["projection"]) is CanonicalFaersProjectionAuthority
    assert not hasattr(dispatcher, "__dict__")
    with pytest.raises(TypeError, match="sealed"):

        class ForbiddenSubclass(SourceCapabilities):
            pass


def test_three_source_dispatcher_has_no_cadec_or_concrete_path_surface() -> None:
    scope = _scope(
        SourceType.PUBMED,
        SourceType.DAILYMED,
        SourceType.FAERS,
        SourceType.CADEC,
    )
    daily_authority, faers_authority = _canonical_projection_authorities(scope)
    dispatcher = SourceCapabilities(
        pubmed_request=_request(scope),
        pubmed_service=cast(object, object()),
        dailymed_projection=daily_authority,
        dailymed_execution=cast(object, object()),
        faers_projection=faers_authority,
        faers_execution=cast(object, object()),
        faers_persistence=cast(object, object()),
    )
    task, attempt = _pending(SourceType.CADEC)
    with pytest.raises(ValueError, match="three-source"):
        dispatcher.plan_operations(task, scope, attempt)
    assert not hasattr(dispatcher, "_cadec_archive_path")
    assert not hasattr(dispatcher, "_cadec_manifest_path")
    assert not hasattr(dispatcher, "_cadec_search")


@pytest.mark.parametrize(
    "attribute",
    [
        "_pubmed_request",
        "_pubmed_service",
        "_dailymed_projection",
        "_dailymed_execution",
        "_faers_projection",
        "_faers_execution",
        "_faers_persistence",
        "plan_operations",
        "collect",
        "validate_terminal_task",
    ],
)
def test_dispatcher_rejects_normal_field_and_method_replacement(attribute: str) -> None:
    scope = _scope(SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS)
    daily, faers = _canonical_projection_authorities(scope)
    dispatcher = SourceCapabilities(
        pubmed_request=_request(scope),
        pubmed_service=cast(object, object()),
        dailymed_projection=daily,
        dailymed_execution=cast(object, object()),
        faers_projection=faers,
        faers_execution=cast(object, object()),
        faers_persistence=cast(object, object()),
    )
    original = getattr(dispatcher, attribute)

    with pytest.raises(AttributeError, match="frozen"):
        setattr(dispatcher, attribute, object())
    current = getattr(dispatcher, attribute)
    assert current == original if callable(original) else current is original


def test_dispatcher_rejects_structural_projection_fake_at_composition() -> None:
    scope = _scope(
        SourceType.PUBMED,
        SourceType.DAILYMED,
        SourceType.FAERS,
        SourceType.CADEC,
    )
    _daily_authority, faers_authority = _canonical_projection_authorities(scope)

    class StructuralFake:
        def project_terminal(self, **_values: object) -> object:
            return object()

    with pytest.raises(TypeError, match="canonical DailyMed"):
        SourceCapabilities(
            pubmed_request=_request(scope),
            pubmed_service=cast(object, object()),
            dailymed_projection=cast(CanonicalDailyMedProjectionAuthority, StructuralFake()),
            dailymed_execution=cast(object, object()),
            faers_projection=faers_authority,
            faers_execution=cast(object, object()),
            faers_persistence=cast(object, object()),
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pubmed_request": None, "pubmed_service": object()}, "PubMed"),
        ({"dailymed_projection": None, "dailymed_execution": object()}, "DailyMed"),
        ({"faers_projection": None, "faers_execution": object()}, "FAERS"),
    ],
)
def test_dispatcher_rejects_every_partial_source_dependency_group(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        SourceCapabilities(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "source",
    (SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS),
)
def test_absent_source_group_fails_plan_collect_and_terminal_validation_before_io(
    monkeypatch: pytest.MonkeyPatch,
    source: SourceType,
) -> None:
    dispatcher = SourceCapabilities()
    scope = _scope(source)
    task, attempt = _pending(source)
    calls: list[str] = []

    def forbidden(*_args: object, **_kwargs: object) -> object:
        calls.append("effect")
        raise AssertionError("an absent source dependency was invoked")

    for name in (
        "plan_pubmed_operations",
        "plan_dailymed_operations",
        "plan_faers_operations",
        "collect_pubmed",
        "collect_dailymed_capability",
        "collect_faers_capability",
        "validate_pubmed_terminal_task",
    ):
        monkeypatch.setattr(capabilities, name, forbidden)
    monkeypatch.setattr(
        capabilities.CanonicalDailyMedProjectionAuthority,
        "validate_terminal_task",
        forbidden,
    )
    monkeypatch.setattr(
        capabilities.CanonicalFaersProjectionAuthority,
        "validate_terminal_task",
        forbidden,
    )

    with pytest.raises(ValueError, match="capability group is absent"):
        dispatcher.plan_operations(task, scope, attempt)
    with pytest.raises(ValueError, match="capability group is absent"):
        dispatcher.collect(task, scope, attempt)

    terminal = SourceTaskState.model_construct(
        task_id=task.task_id,
        source=source,
        required_operations=(SimpleNamespace(scope_id=scope.scope_id),),
        status=SourceTaskStatus.TERMINAL,
    )

    def reconstructed(_cls: object, _value: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            source=source,
            status=SourceTaskStatus.TERMINAL,
            required_operations=(SimpleNamespace(scope_id=scope.scope_id),),
        )

    monkeypatch.setattr(
        capabilities.SourceTaskState,
        "model_validate",
        classmethod(reconstructed),
    )
    with pytest.raises(ValueError, match="capability group is absent"):
        dispatcher.validate_terminal_task(terminal, scope)
    assert calls == []


def test_terminal_replay_uses_each_exact_source_specific_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS)
    daily, faers = _canonical_projection_authorities(scope)
    dispatcher = SourceCapabilities(
        pubmed_request=_request(scope),
        pubmed_service=cast(object, object()),
        dailymed_projection=daily,
        dailymed_execution=cast(object, object()),
        faers_projection=faers,
        faers_execution=cast(object, object()),
        faers_persistence=cast(object, object()),
    )
    calls: list[tuple[str, object, object]] = []

    def reconstruct_task(_cls: object, value: dict[str, object], **_kwargs: object) -> object:
        payload = dict(value)
        payload["required_operations"] = tuple(
            SimpleNamespace(**item)
            for item in cast(tuple[dict[str, object], ...], payload["required_operations"])
        )
        return SimpleNamespace(**payload)

    monkeypatch.setattr(
        capabilities.SourceTaskState,
        "model_validate",
        classmethod(reconstruct_task),
    )
    monkeypatch.setattr(
        capabilities,
        "validate_pubmed_terminal_task",
        lambda *, task, scope, request, service: calls.append(("pubmed", task, scope)),
    )
    monkeypatch.setattr(
        capabilities.CanonicalDailyMedProjectionAuthority,
        "validate_terminal_task",
        lambda _self, task, scope: calls.append(("dailymed", task, scope)),
    )
    monkeypatch.setattr(
        capabilities.CanonicalFaersProjectionAuthority,
        "validate_terminal_task",
        lambda _self, task, scope: calls.append(("faers", task, scope)),
    )

    for source in (SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS):
        task = SourceTaskState.model_construct(
            task_id=source_task_id(RUN_ID, source),
            source=source,
            required_operations=(SimpleNamespace(scope_id=scope.scope_id),),
            status=SourceTaskStatus.TERMINAL,
        )
        dispatcher.validate_terminal_task(task, scope)

    assert [item[0] for item in calls] == ["pubmed", "dailymed", "faers"]


def test_cadec_integrity_failure_fails_both_operations_with_no_partial_refs() -> None:
    task, scope, attempt = _running_cadec()

    class FailingSearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            raise CadecRuntimeError(CadecRuntimeErrorCode.ASSET_INTEGRITY, "synthetic failure")

    result = collect_cadec_capability(
        task=task,
        scope=scope,
        attempt=attempt,
        search=FailingSearch(),
    )

    outcomes = tuple(item.outcome for item in result.operation_results)
    assert len(outcomes) == 2
    assert all(item.execution_status is ExecutionStatus.FAILED for item in outcomes)
    assert all(item.coverage_status is CoverageStatus.UNAVAILABLE for item in outcomes)
    assert all(item.result_status is ResultStatus.INDETERMINATE for item in outcomes)
    assert len({item.failure_id for item in outcomes}) == 1
    assert all(item.warning_codes == (CADEC_LIMITATION_WARNING,) for item in outcomes)
    assert result.terminal_outcome_ref.outcome.failure_id is not None
    assert result.terminal_outcome_ref.outcome.failure_id != outcomes[0].failure_id
    assert result.evidence_refs == ()
    assert result.limitations == tuple(CADEC_MANDATORY_LIMITATIONS)
    assert all(not item.observations for item in result.operation_results)


def test_cadec_port_is_not_invoked_before_running_checkpoint() -> None:
    scope = _scope(SourceType.CADEC)
    task, attempt = _pending(SourceType.CADEC)

    class ForbiddenSearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            raise AssertionError("CADEC port ran before the RUNNING checkpoint")

    with pytest.raises(ValueError, match="running task"):
        collect_cadec_capability(
            task=task,
            scope=scope,
            attempt=attempt,
            search=ForbiddenSearch(),
        )


def test_cadec_operation_input_identities_bind_the_exact_scope_subject() -> None:
    first_scope = _scope(SourceType.CADEC)
    second_scope = ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:2", preferred_term="Other drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:2", preferred_term="Other reaction"),
        ),
        date_range=None,
        selected_sources=(SourceType.CADEC,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=first_scope.query_bounds,
        result_bounds=first_scope.result_bounds,
    )
    task, attempt = _pending(SourceType.CADEC)
    first = plan_cadec_operations(task=task, scope=first_scope, attempt=attempt)
    second = plan_cadec_operations(task=task, scope=second_scope, attempt=attempt)

    assert tuple(item.input_identity for item in first) != tuple(
        item.input_identity for item in second
    )


def test_cadec_fake_hash_complete_no_match_is_mapped_to_failed_zero_ref_collection() -> None:
    task, scope, attempt = _running_cadec()
    exact = _no_match_result(scope)
    fake_verification = exact.verification.model_copy(update={"archive_sha256": "0" * 64})
    foreign = exact.model_copy(update={"verification": fake_verification})

    class ForeignSearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            return foreign

    result = collect_cadec_capability(
        task=task,
        scope=scope,
        attempt=attempt,
        search=ForeignSearch(),
    )
    assert result.terminal_outcome_ref.outcome.execution_status is ExecutionStatus.FAILED
    assert result.terminal_outcome_ref.outcome.coverage_status is CoverageStatus.UNAVAILABLE
    assert result.terminal_outcome_ref.outcome.result_status is ResultStatus.INDETERMINATE
    assert result.evidence_refs == ()
    assert all(not item.observations for item in result.operation_results)
    assert result.limitations == tuple(CADEC_MANDATORY_LIMITATIONS)


def test_cadec_top_twenty_cannot_replace_exact_scope_execution_bounds() -> None:
    task, scope, attempt = _running_cadec()
    exact = _no_match_result(scope)
    wrong_bounds = exact.scope_bounds.model_copy(update={"max_records": 20})
    wrong = exact.model_copy(
        update={
            "scope_bounds": wrong_bounds,
            "outcome": exact.outcome.model_copy(update={"configured_bounds": wrong_bounds}),
        }
    )

    class WrongBoundsSearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            return wrong

    result = collect_cadec_capability(
        task=task,
        scope=scope,
        attempt=attempt,
        search=WrongBoundsSearch(),
    )
    assert result.terminal_outcome_ref.outcome.execution_status is ExecutionStatus.FAILED
    assert all(
        item.outcome.configured_bounds == ExecutionBounds.from_scope(scope)
        for item in result.operation_results
    )
    assert result.evidence_refs == ()


def test_cadec_malformed_port_object_is_mapped_not_raised() -> None:
    task, scope, attempt = _running_cadec()

    class MalformedSearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            return cast(CadecSearchResult, object())

    result = collect_cadec_capability(
        task=task,
        scope=scope,
        attempt=attempt,
        search=MalformedSearch(),
    )
    assert result.terminal_outcome_ref.outcome.execution_status is ExecutionStatus.FAILED
    assert result.evidence_refs == ()
    assert result.limitations == tuple(CADEC_MANDATORY_LIMITATIONS)


def test_missing_configured_asset_cannot_validate_fabricated_terminal_success() -> None:
    running, cadec_scope, attempt = _running_cadec()
    expected = _no_match_result(cadec_scope)

    class ContractOnlySearch:
        def search(self, *, plan: object, scope: object) -> CadecSearchResult:
            del plan, scope
            return expected

    collected = collect_cadec_capability(
        task=running,
        scope=cadec_scope,
        attempt=attempt,
        search=ContractOnlySearch(),
    )
    terminal = terminal_source_task(running, collected, RUN_ID)
    delegate_scope = _scope(
        SourceType.PUBMED,
        SourceType.DAILYMED,
        SourceType.FAERS,
        SourceType.CADEC,
    )
    daily, faers = _canonical_projection_authorities(delegate_scope)
    delegate = SourceCapabilities(
        pubmed_request=_request(delegate_scope),
        pubmed_service=cast(object, object()),
        dailymed_projection=daily,
        dailymed_execution=cast(object, object()),
        faers_projection=faers,
        faers_execution=cast(object, object()),
        faers_persistence=cast(object, object()),
    )
    wrapper = CanonicalCadecEvidenceCollection(
        archive_path="C:/missing/CADEC.v2.zip",
        manifest_path="C:/missing/manifest.json",
        delegate=delegate,
    )

    with pytest.raises(ValueError, match="differs from exact concrete asset replay"):
        wrapper.validate_terminal_task(terminal, cadec_scope)


def test_dispatcher_source_contains_no_mutable_dispatch_table_or_provider_native_surface() -> None:
    source = inspect.getsource(capabilities)
    assert "_dispatch" not in source
    assert "provider" not in source.casefold()
    assert "requests." not in source
    assert "httpx." not in source
    assert "socket" not in source
    assert "pathlib" not in source
    assert "medevidence.infrastructure" not in source
    assert "medevidence.connectors" not in source
    assert "medevidence.retrieval" not in source
