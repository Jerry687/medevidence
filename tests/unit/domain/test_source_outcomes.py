"""Exhaustive tests for source planning and all 18 terminal triples."""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import product

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    FAERS_PT_MAPPING,
    CoverageStatus,
    DailyMedCandidateLabel,
    DailyMedMarketingState,
    DailyMedResolution,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    FaersPtTermV1,
    LabelSelectionDecision,
    LabelSelectionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ResultStatus,
    SourceOutcome,
    SourcePlanEntry,
    SourcePlanReasonCode,
    SourceType,
    classify_dailymed_selection,
    derive_identity,
    sha256_digest,
)


def faers_query() -> FaersAggregateQueryV1:
    return FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:alpha",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="ALPHA",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
            statistical_unit="provider_count_occurrence",
        )
    )


def faers_outcome(*, count: int = 3, partial: bool = False) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.FAERS,
        query_id=faers_query().query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.PARTIAL if partial else CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES if count else ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=count,
        pages_completed=1,
        truncated=partial,
        warning_codes=("source_coverage_incomplete",) if partial else (),
    )


def faers_buckets() -> tuple[FaersAggregateBucketV1, ...]:
    query = faers_query()
    return tuple(
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=ordinal,
            reaction_pt=pt,
            report_count=count,
            identity_stratum=query.identity_stratum,
        )
        for ordinal, (pt, count) in enumerate((("DIARRHOEA", 9), ("NAUSEA", 4), ("VOMITING", 4)))
    )


def faers_result(**changes: object) -> FaersAggregateResult:
    values: dict[str, object] = {
        "query": faers_query(),
        "buckets": faers_buckets(),
        "source_outcome": faers_outcome(),
        "retrieved_at_utc": datetime(2026, 8, 12, tzinfo=UTC),
        "provider_as_of_utc": None,
        "snapshot_id": "snapshot:faers",
        "manifest_id": "manifest:faers",
        "limitations": FAERS_MANDATORY_LIMITATIONS,
    }
    values.update(changes)
    return FaersAggregateResult(**values)


def test_faers_query_identity_closes_strategy_mapping_and_full_preimage() -> None:
    query = faers_query()
    assert query.identity_stratum == "harmonized_substance"
    assert query.identity_field == "patient.drug.openfda.substance_name.exact"
    assert query.pt_values == ("DIARRHOEA", "NAUSEA", "VOMITING")
    assert query.query_id == faers_query().query_id
    exact_preimage = query.model_dump(mode="python", exclude={"query_id"})
    assert query.query_id == derive_identity("faers-query", exact_preimage)
    assert exact_preimage["execution_bounds"]["max_date_difference_days"] == 365
    assert exact_preimage["execution_bounds"]["max_inclusive_calendar_dates"] == 366
    omitted_bound_preimage = dict(exact_preimage)
    omitted_bound_preimage["execution_bounds"] = dict(exact_preimage["execution_bounds"])
    del omitted_bound_preimage["execution_bounds"]["max_date_difference_days"]
    assert derive_identity("faers-query", omitted_bound_preimage) != query.query_id
    assert tuple((row.query_literal, row.display_name) for row in FAERS_PT_MAPPING) == (
        ("DIARRHOEA", "Diarrhoea"),
        ("NAUSEA", "Nausea"),
        ("VOMITING", "Vomiting"),
    )

    for changes in (
        {"identity_stratum": "native_medicinal_product"},
        {"identity_field": "patient.drug.medicinalproduct.exact"},
        {"identity_value": "BETA"},
        {"pt_values": ("NAUSEA", "DIARRHOEA", "VOMITING")},
        {"endpoint_mode": "raw_latest_report"},
        {"statistical_unit": "patient"},
        {"role_policy": "primary_suspect"},
        {"effective_total_deadline_ms": 60_000},
        {"identity_value": "e\u0301"},
        {"identity_value": "ALPHA%20DRUG"},
    ):
        with pytest.raises(ValidationError):
            FaersAggregateQueryV1(**{**query.model_dump(mode="python"), **changes})

    for field, drift in (
        ("max_date_difference_days", 364),
        ("max_inclusive_calendar_dates", 365),
    ):
        forged_bounds = query.execution_bounds.model_copy(update={field: drift})
        with pytest.raises(ValidationError):
            FaersAggregateQueryV1.model_validate(
                query.model_copy(update={"execution_bounds": forged_bounds})
            )

    for pair in (
        ("NAUSEA", "Vomiting"),
        ("Nausea", "Nausea"),
        ("VOMITING", "vomiting"),
        ("CONSTIPATION", "Constipation"),
    ):
        with pytest.raises(ValidationError):
            FaersPtTermV1(query_literal=pair[0], display_name=pair[1])


@pytest.mark.parametrize(
    "term",
    [
        "Nausea",
        "nausea",
        "DIARRHEA",
        "CONSTIPATION",
        "ABDOMINAL PAIN",
        "VOMITING ",
        "VOMITING\u0301",
        "UNKNOWN",
    ],
)
def test_faers_bucket_rejects_alias_case_spelling_normalization_and_unknown(term: str) -> None:
    with pytest.raises(ValidationError):
        FaersAggregateBucketV1(
            query_id=faers_query().query_id,
            bucket_ordinal=0,
            reaction_pt=term,
            report_count=1,
            identity_stratum="harmonized_substance",
        )


def test_faers_result_preserves_all_ties_and_exact_complete_collection() -> None:
    result = faers_result()
    assert tuple(bucket.reaction_pt for bucket in result.buckets) == (
        "DIARRHOEA",
        "NAUSEA",
        "VOMITING",
    )
    assert len(result.buckets) == 3
    assert "incidence" in result.limitations[1]
    assert sha256_digest(result.model_dump_json()).startswith("sha256:")

    base = result.model_dump(mode="python")
    variants = (
        {"buckets": result.buckets[:-1]},
        {"buckets": (*result.buckets, result.buckets[-1])},
        {"buckets": (result.buckets[0], result.buckets[2], result.buckets[1])},
        {
            "buckets": (
                result.buckets[0],
                result.buckets[1].model_copy(update={"bucket_ordinal": 2}),
                result.buckets[2].model_copy(update={"bucket_ordinal": 3}),
            )
        },
        {"limitations": result.limitations[:-1]},
    )
    for changes in variants:
        with pytest.raises(ValidationError):
            FaersAggregateResult(**{**base, **changes})
    partial = FaersAggregateResult(
        **{**base, "source_outcome": faers_outcome(count=3, partial=True)}
    )
    assert partial.source_outcome.coverage_status is CoverageStatus.PARTIAL


def test_faers_complete_zero_is_no_match_but_partial_zero_is_indeterminate() -> None:
    complete = faers_outcome(count=0)
    assert complete.result_status is ResultStatus.NO_MATCH
    partial = SourceOutcome(
        **{
            **complete.model_dump(mode="python"),
            "coverage_status": CoverageStatus.PARTIAL,
            "result_status": ResultStatus.INDETERMINATE,
            "truncated": True,
            "warning_codes": ("source_coverage_incomplete",),
        }
    )
    assert partial.result_status is ResultStatus.INDETERMINATE


VALID_TRIPLES = {
    (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
    (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
    (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
    (
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    ),
    (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
    (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    ),
    (
        ExecutionStatus.FAILED,
        CoverageStatus.UNAVAILABLE,
        ResultStatus.INDETERMINATE,
    ),
}


def bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )


def outcome_for(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=bounds(),
        valid_result_count=1 if result is ResultStatus.MATCHES else 0,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=(
            () if coverage is CoverageStatus.COMPLETE else ("source_coverage_incomplete",)
        ),
        failure_id="failure:test" if execution is ExecutionStatus.FAILED else None,
    )


@pytest.mark.parametrize(
    ("execution", "coverage", "result"),
    list(
        product(
            tuple(ExecutionStatus),
            tuple(CoverageStatus),
            tuple(ResultStatus),
        )
    ),
)
def test_all_eighteen_terminal_triples(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> None:
    triple = (execution, coverage, result)
    if triple in VALID_TRIPLES:
        terminal = outcome_for(*triple)
        assert (
            terminal.execution_status,
            terminal.coverage_status,
            terminal.result_status,
        ) == triple
    else:
        with pytest.raises(ValidationError):
            outcome_for(*triple)


@pytest.mark.parametrize(
    "entry",
    [
        SourcePlanEntry(
            source=SourceType.PUBMED,
            planning_status=PlanningStatus.SELECTED,
        ),
        SourcePlanEntry(
            source=SourceType.CADEC,
            planning_status=PlanningStatus.SKIPPED_NOT_APPLICABLE,
            reason_code=SourcePlanReasonCode.NOT_APPLICABLE_TO_SCOPE,
            reason="The auxiliary corpus does not apply to this scope.",
        ),
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="Only PubMed execution is authorized in M1A.",
        ),
    ],
)
def test_all_planning_statuses_are_explicit(entry: SourcePlanEntry) -> None:
    assert "source_outcome" not in type(entry).model_fields


def test_skipped_plan_cannot_contain_or_fabricate_outcome() -> None:
    with pytest.raises(ValidationError):
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="Not authorized.",
            source_outcome=outcome_for(
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.NO_MATCH,
            ),
        )
    with pytest.raises(ValidationError):
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SELECTED,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_result_count": 0},
        {"valid_result_count": 101},
        {"pages_completed": 6},
        {"warning_codes": ("duplicate_warning", "duplicate_warning")},
    ],
)
def test_matches_enforces_counts_bounds_and_unique_warnings(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"truncated": True},
        {"failure_id": "failure:unexpected"},
    ],
)
def test_complete_success_forbids_truncation_and_failure_identity(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.COMPLETE,
        ResultStatus.NO_MATCH,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"failure_id": None},
        {"warning_codes": ()},
    ],
)
def test_failed_partial_requires_failure_and_warning(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_result_count": 1},
        {"pages_completed": 1},
        {"warning_codes": ()},
    ],
)
def test_unavailable_requires_zero_progress_and_visible_warning(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.FAILED,
        CoverageStatus.UNAVAILABLE,
        ResultStatus.INDETERMINATE,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


def dailymed_matrix_outcome(
    triple: tuple[ExecutionStatus, CoverageStatus, ResultStatus],
    count: int,
) -> SourceOutcome:
    execution, coverage, result = triple
    return SourceOutcome.model_construct(
        schema_version="1.0",
        source=SourceType.DAILYMED,
        query_id="query:dailymed-discovery",
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=bounds(),
        valid_result_count=count,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=(
            () if coverage is CoverageStatus.COMPLETE else ("source_coverage_incomplete",)
        ),
        failure_id="failure:dailymed" if execution is ExecutionStatus.FAILED else None,
    )


@pytest.mark.parametrize("triple", sorted(VALID_TRIPLES, key=lambda item: str(item)))
@pytest.mark.parametrize("candidate_count", [0, 1, 2, 4])
@pytest.mark.parametrize(
    "resolution",
    [
        None,
        DailyMedResolution.RESOLVED_EQUIVALENT,
        DailyMedResolution.UNRESOLVED_NON_EQUIVALENT,
    ],
)
def test_dailymed_discovery_matrix_is_exhaustive_and_disjoint(
    triple: tuple[ExecutionStatus, CoverageStatus, ResultStatus],
    candidate_count: int,
    resolution: DailyMedResolution | None,
) -> None:
    execution, coverage, result = triple
    expected: LabelSelectionStatus | None | object = object()
    invalid = expected
    if result is ResultStatus.MATCHES and candidate_count >= 1 and resolution is not None:
        if coverage is CoverageStatus.PARTIAL:
            expected = LabelSelectionStatus.REVIEW_REQUIRED
        elif resolution is DailyMedResolution.RESOLVED_EQUIVALENT:
            expected = LabelSelectionStatus.SELECTED
        elif candidate_count >= 2:
            expected = LabelSelectionStatus.REVIEW_REQUIRED
    elif (
        execution is ExecutionStatus.SUCCEEDED
        and coverage is CoverageStatus.COMPLETE
        and result is ResultStatus.NO_MATCH
        and candidate_count == 0
        and resolution is None
    ):
        expected = LabelSelectionStatus.NO_CANDIDATE
    elif result is ResultStatus.INDETERMINATE and candidate_count == 0 and resolution is None:
        expected = None

    outcome = dailymed_matrix_outcome(triple, candidate_count)
    if expected is invalid:
        with pytest.raises(ValueError):
            classify_dailymed_selection(
                outcome=outcome,
                candidate_count=candidate_count,
                resolution=resolution,
            )
    else:
        assert (
            classify_dailymed_selection(
                outcome=outcome,
                candidate_count=candidate_count,
                resolution=resolution,
            )
            is expected
        )


@pytest.mark.parametrize(
    "triple",
    [
        (
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.PARTIAL,
            ResultStatus.MATCHES,
        ),
        (
            ExecutionStatus.FAILED,
            CoverageStatus.PARTIAL,
            ResultStatus.MATCHES,
        ),
    ],
)
@pytest.mark.parametrize("candidate_count", [1, 2, 4])
@pytest.mark.parametrize("resolution", tuple(DailyMedResolution))
def test_partial_matches_never_select_even_when_pinned(
    triple: tuple[ExecutionStatus, CoverageStatus, ResultStatus],
    candidate_count: int,
    resolution: DailyMedResolution,
) -> None:
    assert (
        classify_dailymed_selection(
            outcome=dailymed_matrix_outcome(triple, candidate_count),
            candidate_count=candidate_count,
            resolution=resolution,
            pinned_identity=True,
        )
        is LabelSelectionStatus.REVIEW_REQUIRED
    )


def test_dailymed_classifier_reconstructs_outcome_before_reading_fields() -> None:
    outcome = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        1,
    )
    with pytest.raises(ValidationError):
        classify_dailymed_selection(
            outcome=outcome.model_copy(update={"schema_version": "evil"}),
            candidate_count=1,
            resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        )


def dailymed_candidate_for_factory(
    *, setid: str, ordinal: int, spl_versions: tuple[str, ...]
) -> DailyMedCandidateLabel:
    digit = str(ordinal + 1)
    return DailyMedCandidateLabel.create(
        run_id="run:00000000-0000-4000-8000-000000000001",
        attempt_id="attempt:00000000-0000-4000-8000-000000000001",
        acquisition_id="acquisition:dailymed-discovery",
        acquisition_ordinal=0,
        acquisition_intent_id=f"acquisition-intent:sha256:{'1' * 64}",
        setid=setid,
        spl_versions=spl_versions,
        ingredients=("ingredient",),
        brand_name=None,
        generic_name=None,
        application_number=None,
        product_id=None,
        labeler=None,
        dosage_forms=(),
        routes=(),
        strengths=(),
        ndcs=(),
        marketing_state=DailyMedMarketingState.ACTIVE,
        effective_date=None,
        published_date=None,
        available_section_codes=("34084-4",),
        discovery_query_id="query:dailymed-discovery",
        candidate_set_snapshot_id="snapshot:dailymed-discovery",
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        member_ordinal=ordinal,
        link_id=f"artifact-link:sha256:{digit * 64}",
        raw_artifact_id=f"artifact:dailymed-{ordinal}",
        raw_content_hash=f"sha256:{digit * 64}",
        candidate_ordinal=ordinal,
    )


def test_dailymed_candidate_revalidates_every_model_copy_field() -> None:
    candidate = dailymed_candidate_for_factory(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        spl_versions=("3",),
    )
    optional_fields = {
        "brand_name",
        "generic_name",
        "application_number",
        "product_id",
        "labeler",
        "effective_date",
        "published_date",
    }
    for field_name in type(candidate).model_fields:
        if field_name == "body_complete":
            drift: object = False
        elif field_name == "termination_reason":
            drift = "evil"
        elif field_name in optional_fields:
            drift = object()
        else:
            drift = None
        with pytest.raises(ValidationError):
            DailyMedCandidateLabel.model_validate(candidate.model_copy(update={field_name: drift}))


def test_decision_factory_owns_numeric_candidate_order_and_direct_validation() -> None:
    first = dailymed_candidate_for_factory(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        spl_versions=("10", "2"),
    )
    second = dailymed_candidate_for_factory(
        setid="22222222-2222-2222-2222-222222222222",
        ordinal=1,
        spl_versions=("2", "10"),
    )
    outcome = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        2,
    )
    decision = LabelSelectionDecision.selected_from_discovery(
        candidates=(second, first),
        outcome=outcome,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id="source-outcome:dailymed-discovery",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert first.spl_versions == second.spl_versions == ("2", "10")
    assert decision.candidate_ids == (first.candidate_id, second.candidate_id)
    assert decision.status is LabelSelectionStatus.SELECTED
    resolved = max(
        (first, second),
        key=lambda item: (
            item.marketing_state is DailyMedMarketingState.ACTIVE,
            item.effective_date or datetime.min.date(),
            item.published_date or datetime.min.date(),
            max(int(version) for version in item.spl_versions),
            item.candidate_id,
        ),
    )
    assert decision.selected_candidate_id == resolved.candidate_id
    assert decision.selected_setid == resolved.setid
    assert decision.selected_spl_version == "10"
    with pytest.raises(ValidationError, match="authoritative discovery context"):
        LabelSelectionDecision.model_validate(decision.model_dump(mode="python"))
    for context in (
        {"intrinsic_only": True},
        {
            "outcome": outcome,
            "candidates": (first, second),
            "source_outcome_id": "source-outcome:dailymed-discovery",
            "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
        },
    ):
        with pytest.raises(ValidationError, match="authoritative discovery context"):
            LabelSelectionDecision.model_validate(
                decision.model_dump(mode="python"), context=context
            )

    for field, drift in (
        ("selected_setid", "33333333-3333-3333-3333-333333333333"),
        ("selected_spl_version", "9"),
    ):
        payload = decision.model_dump(mode="python")
        payload[field] = drift
        payload["decision_id"] = derive_identity(
            "dailymed-selection-decision",
            {
                key: value
                for key, value in payload.items()
                if key not in {"decision_id", "decided_at_utc"}
            },
        )
        with pytest.raises(ValidationError, match="authoritative discovery context"):
            LabelSelectionDecision.model_validate(
                payload,
                context={
                    "outcome": outcome,
                    "candidates": (first, second),
                    "source_outcome_id": "source-outcome:dailymed-discovery",
                    "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
                },
            )


@pytest.mark.parametrize(
    ("field", "drift"),
    (
        ("run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("source", SourceType.PUBMED),
        ("attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("acquisition_id", "acquisition:foreign"),
        ("acquisition_ordinal", 7),
        ("acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("discovery_query_id", "query:foreign"),
        ("candidate_set_snapshot_id", "snapshot:foreign"),
        ("discovery_manifest_id", "artifact:foreign-manifest"),
    ),
)
def test_decision_rejects_each_candidate_discovery_identity_drift(
    field: str,
    drift: object,
) -> None:
    candidate = dailymed_candidate_for_factory(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        spl_versions=("3",),
    )
    outcome = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        1,
    )
    decision = LabelSelectionDecision.selected_from_discovery(
        candidates=(candidate,),
        outcome=outcome,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id="source-outcome:dailymed-discovery",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=datetime(2026, 8, 11, tzinfo=UTC),
    )

    with pytest.raises(
        ValidationError,
        match=(
            r"candidate discovery identity|bindings must equal exact candidates|"
            r"candidate_id does not match|literal_error"
        ),
    ):
        decision.validate_against(
            outcome=outcome,
            candidates=(candidate.model_copy(update={field: drift}),),
            source_outcome_id="source-outcome:dailymed-discovery",
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        )


def test_decision_recomputes_positive_and_zero_candidate_set_and_trusted_ids() -> None:
    candidate = dailymed_candidate_for_factory(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        spl_versions=("3",),
    )
    matched = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        1,
    )
    selected = LabelSelectionDecision.selected_from_discovery(
        candidates=(candidate,),
        outcome=matched,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id="source-outcome:dailymed-discovery",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=datetime(2026, 8, 11, tzinfo=UTC),
    )

    no_match = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
        0,
    )
    no_candidate = LabelSelectionDecision.no_candidate_from_discovery(
        run_id=candidate.run_id,
        attempt_id=candidate.attempt_id,
        acquisition_id=candidate.acquisition_id,
        acquisition_ordinal=candidate.acquisition_ordinal,
        acquisition_intent_id=candidate.acquisition_intent_id,
        candidate_set_snapshot_id=candidate.candidate_set_snapshot_id,
        discovery_manifest_id=candidate.discovery_manifest_id,
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        source_outcome_id="source-outcome:dailymed-discovery",
        outcome=no_match,
        decided_at_utc=datetime(2026, 8, 11, tzinfo=UTC),
    )

    for decision, outcome, candidates in (
        (selected, matched, (candidate,)),
        (no_candidate, no_match, ()),
    ):
        drifted = decision.model_copy(update={"candidate_set_id": "candidate-set:foreign"})
        payload = drifted.model_dump(mode="python", exclude={"decision_id", "decided_at_utc"})
        drifted = drifted.model_copy(
            update={"decision_id": derive_identity("dailymed-selection-decision", payload)}
        )
        with pytest.raises(ValidationError, match="candidate_set_id"):
            drifted.validate_against(
                outcome=outcome,
                candidates=candidates,
                source_outcome_id="source-outcome:dailymed-discovery",
                discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            )

        for source_outcome_id, manifest_hash in (
            ("source-outcome:foreign", f"sha256:{'f' * 64}"),
            ("source-outcome:dailymed-discovery", f"sha256:{'0' * 64}"),
        ):
            with pytest.raises(ValidationError, match="trusted outcome or manifest"):
                decision.validate_against(
                    outcome=outcome,
                    candidates=candidates,
                    source_outcome_id=source_outcome_id,
                    discovery_manifest_content_hash=manifest_hash,
                )


def test_public_candidate_projection_and_decision_factory_revalidate_instances() -> None:
    candidate = dailymed_candidate_for_factory(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        spl_versions=("3",),
    )
    outcome = dailymed_matrix_outcome(
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        1,
    )
    for field, drift in (
        ("schema_version", "evil"),
        ("setid", "not-a-uuid"),
        ("body_complete", False),
        ("termination_reason", "evil"),
    ):
        with pytest.raises(ValidationError):
            candidate.model_copy(update={field: drift}).as_binding()

    with pytest.raises(ValidationError):
        LabelSelectionDecision.selected_from_discovery(
            candidates=(candidate,),
            outcome=outcome.model_copy(update={"schema_version": "evil"}),
            resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
            source_outcome_id="source-outcome:dailymed-discovery",
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            decided_at_utc=datetime(2026, 8, 11, tzinfo=UTC),
        )


def test_source_plan_version_adds_dailymed_without_weakening_m1a() -> None:
    with pytest.raises(ValidationError):
        SourcePlanEntry(
            source=SourceType.DAILYMED,
            planning_status=PlanningStatus.SELECTED,
        )
    assert (
        M1BSourcePlanEntryV1(
            source=SourceType.DAILYMED,
            planning_status=PlanningStatus.SELECTED,
        ).source
        is SourceType.DAILYMED
    )
    schema_version = SourcePlanEntry.model_json_schema()["properties"]["schema_version"]
    assert schema_version == {"$ref": "#/$defs/SchemaVersion", "default": "1.0"}
