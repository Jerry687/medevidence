from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from medevidence.tools.provider_attempt_framing import (
    APPROVED_HEADER_NAMES,
    APPROVED_HEADER_NAMES_IDENTITY,
    FRAMING_CONTRACT_IDENTITY,
    FRAMING_RULES,
    MAX_OBSERVED_BODY_BYTES_LOWER_BOUND,
    MAX_RAW_RESPONSE_BYTES,
    PERSISTED_AUTHORITY_FIELDS,
    POSTGRES_BIGINT_MAX,
    V2_EVENT_METADATA_RULES,
    V2_ONLY_LEDGER_COLUMNS,
    V2_PERSISTED_COLUMNS,
    ConsumerMutationValueKind,
    ContentLengthState,
    FramingObservation,
    FramingStatus,
    HeaderOccurrence,
    HeaderSurfaceState,
    MutationKind,
    PersistedAuthorityValueKind,
    RawEvidenceState,
    apply_persisted_mutations,
    build_framing_observation,
    build_unavailable_observation,
    canonical_approved_header_names_bytes,
    canonical_fact_free_v2_event_projection,
    canonical_framing_input_bytes,
    canonical_normalized_header_facts_bytes,
    canonical_observation_projection,
    canonical_raw_artifact_bytes,
    canonical_v2_event_metadata,
    classify_framing,
    fact_free_event_case_projection,
    fact_free_v2_event_matches,
    framing_contract_identity,
    generated_consumer_mutation_witness,
    generated_contract_cases,
    generated_mutation_witness,
    governed_primitive_fields,
    legacy_v2_raw_projection,
    matching_rule_keys,
    normalize_approved_headers,
    persisted_authority_field_specs,
    persisted_authority_value_is_canonical,
    projection_matches,
    provider_raw_relative_path_is_canonical,
    raw_body_persistence_permitted,
    reconstruct_normalized_headers,
    render_fact_free_v2_event_predicate,
    render_postgres_contract,
    render_provider_raw_relative_path_predicate,
    render_v1_immutability_predicate,
    render_v2_event_metadata_predicate,
    render_v2_facts_absent_predicate,
    v2_event_metadata_matches,
    validate_generated_mutation_case,
)

_RAW_HASH = "sha256:" + "0" * 64
_RAW_PATH = "raw/case.json"
_WINDOWS_RESERVED_NAMES = (
    "AUX",
    "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    "CON",
    *(f"LPT{index}" for index in range(1, 10)),
    "NUL",
    "PRN",
)


@pytest.mark.parametrize(
    "value",
    (
        "",
        ".",
        "..",
        "C:/outside.bin",
        "C:outside.bin",
        "raw/case.bin:stream",
        "//server/share/case.bin",
        "\\\\server\\share\\case.bin",
        "/absolute/case.bin",
        "../outside.bin",
        "raw/../outside.bin",
        "raw//case.bin",
        "raw/case.bin.",
        "raw/case.bin ",
        "raw./case.bin",
        "raw /case.bin",
        *(f"raw/{name}" for name in _WINDOWS_RESERVED_NAMES),
        *(f"raw/{name.lower()}.json" for name in _WINDOWS_RESERVED_NAMES),
    ),
)
def test_provider_raw_relative_path_rejects_drive_ads_absolute_and_traversal_forms(
    value: str,
) -> None:
    assert not provider_raw_relative_path_is_canonical(value)
    assert not persisted_authority_value_is_canonical("body_relative_path", value)
    assert not persisted_authority_value_is_canonical("raw_relative_path", value)
    with pytest.raises(ValueError, match="raw evidence binding is invalid"):
        build_framing_observation(
            disposition="response_invalid",
            http_status=200,
            http_version="HTTP/2",
            headers=normalize_approved_headers(
                (("content-type", "application/json"),), raw_header_field_count=1
            ),
            raw_header_field_count=1,
            body_complete=True,
            actual_body_byte_count=2,
            raw_body_hash=_RAW_HASH,
            raw_relative_path=value,
        )


def test_provider_raw_relative_path_canonical_form_is_bound_in_postgres_predicate() -> None:
    assert provider_raw_relative_path_is_canonical(_RAW_PATH)
    sql = render_postgres_contract().canonical_fact_shape
    assert "position(chr(92) IN raw_relative_path)=0" in sql
    assert "position(':' IN raw_relative_path)=0" in sql
    assert "raw_relative_path !~ '(^/|/$|//|(^|/)\\.{1,2}(/|$))'" in sql
    assert "[^/]*[. ](/|$)" in sql
    assert r"CLOCK\$" in sql and "COM9" in sql and "LPT9" in sql
    assert render_provider_raw_relative_path_predicate("raw_relative_path") in sql
    assert (
        render_provider_raw_relative_path_predicate("body_relative_path")
        in render_v1_immutability_predicate()
    )


@pytest.mark.parametrize(
    "value",
    (
        "raw/COM10.json",
        "raw/LPT10.json",
        "raw/CONSOLE.json",
        "raw/NUL-safe.json",
        "raw/prefix.CON",
    ),
)
def test_provider_raw_relative_path_does_not_overreject_non_device_names(value: str) -> None:
    assert provider_raw_relative_path_is_canonical(value)


def _observation(
    *,
    http_version: str | None = "HTTP/2",
    header_items: tuple[tuple[str, str], ...] = (("content-type", "application/json"),),
    body_complete: bool = True,
    byte_count: int | None = 2,
    observed_lower_bound: int | None = None,
    persist_raw: bool = True,
    disposition: str = "response_invalid",
    raw_header_field_count: int | None = None,
):
    header_count = len(header_items) if raw_header_field_count is None else raw_header_field_count
    return build_framing_observation(
        disposition=disposition,
        http_status=200,
        http_version=http_version,
        headers=normalize_approved_headers(header_items, raw_header_field_count=header_count),
        raw_header_field_count=header_count,
        body_complete=body_complete,
        actual_body_byte_count=byte_count,
        observed_body_bytes_lower_bound=(
            observed_lower_bound
            if observed_lower_bound is not None
            else byte_count
            if body_complete
            else 0
        ),
        raw_body_hash=_RAW_HASH if persist_raw else None,
        raw_relative_path=_RAW_PATH if persist_raw else None,
    )


def _code(**kwargs: object) -> str | None:
    return classify_framing(_observation(**kwargs)).rejection_code


def test_generated_cases_are_owned_by_the_ordered_rule_table() -> None:
    cases = generated_contract_cases()
    assert len(cases) == len(FRAMING_RULES)
    assert [case.rule_key for case in cases] == [rule.key for rule in FRAMING_RULES]
    for case in cases:
        assert case.expected_admitted is True
        decision = classify_framing(case.observation)
        assert (
            decision.rule_key,
            decision.status,
            decision.accepted_class,
            decision.rejection_code,
        ) == (
            case.rule_key,
            case.expected_status,
            case.expected_class,
            case.expected_code,
        )


def test_generated_positive_examples_have_every_higher_rule_absent() -> None:
    for index, case in enumerate(generated_contract_cases()):
        active = matching_rule_keys(case.observation)
        assert case.rule_key in active
        assert not {rule.key for rule in FRAMING_RULES[:index]} & set(active)


def test_generated_pairwise_overlaps_prove_first_match_precedence() -> None:
    variants = [
        variant for case in generated_contract_cases() for variant in case.precedence_variants
    ]
    assert len(variants) >= 50
    ids = {variant.case_id for variant in variants}
    assert {
        "precedence:missing_http_version+invalid_content_length",
        "precedence:missing_http_version+invalid_transfer_encoding",
        "precedence:te_and_cl+compression_not_identity",
        "precedence:compression_not_identity+response_body_incomplete",
        "precedence:content_length_mismatch+invalid_content_type",
    } <= ids
    for variant in variants:
        assert variant.expected_admitted is True
        decision = classify_framing(variant.observation)
        active = matching_rule_keys(variant.observation)
        assert set(variant.active_rule_keys) <= set(active)
        assert (
            decision.status,
            decision.accepted_class,
            decision.rejection_code,
        ) == (
            variant.expected_status,
            variant.expected_class,
            variant.expected_code,
        )
        assert decision.rule_key == variant.active_rule_keys[0]


def test_generated_noncanonical_matrix_carries_all_required_mutations() -> None:
    generated = generated_contract_cases()
    variants = [variant for case in generated for variant in case.noncanonical_variants]
    ids = {variant.case_id for variant in variants}
    assert {
        "accept_http_1_1_chunked:accepted_incomplete_rawless",
        "accept_http_1_1_content_length:missing_raw_artifact",
        "accept_http_2_data:accepted_incomplete_rawless",
        "content_length_mismatch:null_actual_incomplete",
        "media_drift:foreign_accepted_decision",
        "approved_header_authority_drift",
        "unapproved_header_used_in_framing",
        "framing_input_identity_drift",
        "decision_drift",
        "legacy_raw_projection:body_byte_count_drift",
        "legacy_raw_projection:body_hash_drift",
        "legacy_raw_projection:body_relative_path_drift",
        "legacy_raw_projection:observed_body_bytes_lower_bound_drift",
        "legacy_raw_projection:internally_consistent_foreign_tuple",
        "raw_header_field_count_drift",
        "event_metadata:credential_echo_false",
        "event_metadata:credential_echo_integer_zero",
        "event_metadata:credential_echo_integer_one",
        "event_metadata:non_echo_credential_true",
        "event_metadata:nonsuccess_error_null",
        "event_metadata:nonsuccess_error_foreign",
        "event_metadata:success_error_nonnull",
        "primitive:bool_for_int:actual_body_byte_count",
        "primitive:bool_for_int:body_byte_count",
        "primitive:bool_for_int:content_length_value",
        "primitive:bool_for_int:http_status",
        "primitive:bool_for_int:observed_body_bytes_lower_bound",
        "primitive:bool_for_int:raw_header_field_count",
        "primitive:int_for_bool:body_complete",
        "primitive:int_for_bool:credential_echo",
        "primitive:str_subclass:disposition",
        "primitive:str_subclass:observed_http_version",
        "primitive:str_subclass:body_hash",
        "primitive:str_subclass:body_relative_path",
        "primitive:str_subclass:approved_header_name",
        "primitive:str_subclass:normalized_header_name",
        "primitive:str_subclass:header_occurrence_value",
        "primitive:str_subclass:framing_rejection_code",
    } <= ids
    assert len(variants) == len(ids)
    assert all(variant.mutations for variant in variants)
    assert all(variant.expected_admitted is False for variant in variants)
    assert all("external" in variant.consumers for variant in variants)

    by_rule = {case.rule_key: case for case in generated}
    for case in generated:
        witness = generated_mutation_witness(case.observation)
        for variant in case.noncanonical_variants:
            validate_generated_mutation_case(variant)
            assert variant.expected_first_match_rule == case.rule_key
            assert (
                variant.expected_status,
                variant.expected_class,
                variant.expected_code,
            ) == (case.expected_status, case.expected_class, case.expected_code)
            assert type(variant.valid_witness_value) is type(
                witness[variant.target_authority_field]
            )
            assert variant.valid_witness_value == witness[variant.target_authority_field]
            mutation_fields = tuple(mutation.field for mutation in variant.mutations)
            if variant.mutation_kind is MutationKind.CROSS_CONDITION:
                assert variant.cross_condition_fields == mutation_fields
                assert variant.target_authority_field in mutation_fields
            else:
                assert mutation_fields == (variant.target_authority_field,)
                assert variant.cross_condition_fields == ()
            mutated = apply_persisted_mutations(witness, variant.mutations)
            for mutation in variant.mutations:
                if mutation.operation == "remove":
                    assert mutation.field not in mutated
                else:
                    # Prove the declared mutation reached the named authority before
                    # any rejection/admission assertion consumes this case.
                    before = witness[mutation.field]
                    assert type(before) is not type(mutation.value) or before != mutation.value
                    assert mutated[mutation.field] is mutation.value
            assert variant.expected_admitted is False
            assert tuple(target.consumer for target in variant.consumer_targets) == (
                variant.consumers
            )
            for target in variant.consumer_targets:
                assert target.authority_fields == mutation_fields
                assert len(target.direct_target_paths) == len(mutation_fields)
                assert target.mutation_operations == tuple(
                    mutation.operation for mutation in variant.mutations
                )
                assert len(target.mutation_value_kinds) == len(mutation_fields)
                assert all(
                    (
                        target.consumer == "python"
                        and path.startswith(("FramingObservation.", "NormalizedHeaderFacts."))
                    )
                    or field in path
                    or (
                        field == "observed_http_version"
                        and path == "observation.response_http_version"
                    )
                    or (
                        field == "raw_header_field_count"
                        and path == "observation.response_header_field_count"
                    )
                    or (
                        field == "accepted_framing_class"
                        and path == "projected_decision.accepted_class"
                    )
                    or (
                        field == "framing_input_identity"
                        and path == "projected_decision.input_identity"
                    )
                    or (
                        field == "framing_rejection_code"
                        and path == "projected_decision.rejection_code"
                    )
                    or (field == "framing_status" and path == "projected_decision.status")
                    for field, path in zip(
                        target.authority_fields,
                        target.direct_target_paths,
                        strict=True,
                    )
                )
                consumer_witnesses = generated_consumer_mutation_witness(variant, target.consumer)
                assert all(item.case_id == variant.case_id for item in consumer_witnesses)
                assert all(item.consumer == target.consumer for item in consumer_witnesses)
                assert all(
                    item.target_authority_field == variant.target_authority_field
                    for item in consumer_witnesses
                )
                assert tuple(item.field for item in consumer_witnesses) == mutation_fields
                assert tuple(item.direct_target_path for item in consumer_witnesses) == (
                    target.direct_target_paths
                )
                assert tuple(item.operation for item in consumer_witnesses) == (
                    target.mutation_operations
                )
                assert tuple(item.value_kind for item in consumer_witnesses) == (
                    target.mutation_value_kinds
                )
                for item in consumer_witnesses:
                    if item.operation == "remove":
                        continue
                    assert not (
                        type(item.mutated_value) is type(item.canonical_value)
                        and item.mutated_value == item.canonical_value
                    )
            external = next(
                target for target in variant.consumer_targets if target.consumer == "external"
            )
            assert external.authority_fields == mutation_fields
            assert external.direct_target_paths == tuple(
                f"provider-attempt-projection.events[*].{field}" for field in mutation_fields
            )

    external_nonexact_lists = [
        (variant, witness)
        for variant in variants
        for witness in generated_consumer_mutation_witness(variant, "external")
        if witness.value_kind is ConsumerMutationValueKind.NONEXACT_LIST_SUBCLASS
    ]
    tuple_fields = {
        spec.field
        for spec in persisted_authority_field_specs()
        if spec.value_kind is PersistedAuthorityValueKind.STR_TUPLE
    }
    assert len(external_nonexact_lists) == len(tuple_fields)
    assert {variant.target_authority_field for variant, _witness in external_nonexact_lists} == {
        *tuple_fields,
    }
    for variant, witness in external_nonexact_lists:
        assert variant.mutation_kind is MutationKind.TYPE
        assert type(witness.canonical_value) is list
        assert isinstance(witness.mutated_value, list)
        assert type(witness.mutated_value) is not list
        assert witness.mutated_value == witness.canonical_value

    primitive_variants = [
        variant for variant in variants if variant.case_id.startswith("primitive:")
    ]
    specs = persisted_authority_field_specs()
    governed = governed_primitive_fields()
    assert governed == PERSISTED_AUTHORITY_FIELDS
    assert tuple(spec.field for spec in specs) == PERSISTED_AUTHORITY_FIELDS
    assert (
        "schema_version",
        "event_kind",
        *PERSISTED_AUTHORITY_FIELDS,
    ) == V2_PERSISTED_COLUMNS
    fact_free = canonical_fact_free_v2_event_projection(event_kind="START", disposition="started")
    assert tuple(fact_free) == V2_PERSISTED_COLUMNS
    assert len(governed) == len(set(governed)) == 37
    matrix_covered_target_fields = {
        variant.target_authority_field for variant in primitive_variants
    }
    assert matrix_covered_target_fields == set(PERSISTED_AUTHORITY_FIELDS)
    by_rule = {case.rule_key: case for case in generated}
    expected_types = {
        PersistedAuthorityValueKind.BOOL: bool,
        PersistedAuthorityValueKind.INT: int,
        PersistedAuthorityValueKind.STR: str,
        PersistedAuthorityValueKind.STR_TUPLE: tuple,
    }
    for spec in specs:
        field = spec.field
        positive = generated_mutation_witness(by_rule[spec.positive_rule_key].observation)[field]
        assert type(positive) is expected_types[spec.value_kind]
        field_variants = [
            variant for variant in primitive_variants if variant.target_authority_field == field
        ]
        assert {variant.mutation_kind for variant in field_variants} == set(spec.mutation_kinds)
        assert len(field_variants) == len(spec.mutation_kinds)
        assert len({variant.case_id for variant in field_variants}) == len(spec.mutation_kinds)


def test_generated_cross_conditions_use_only_declared_locally_canonical_values() -> None:
    generated = generated_contract_cases()
    by_rule = {case.rule_key: case for case in generated}
    primitive_variants = [
        variant
        for case in generated
        for variant in case.noncanonical_variants
        if variant.case_id.startswith("primitive:")
    ]
    cross_by_field = {
        variant.target_authority_field: variant
        for variant in primitive_variants
        if variant.mutation_kind is MutationKind.CROSS_CONDITION
    }
    specs = persisted_authority_field_specs()
    declared_cross_fields = {spec.field for spec in specs if spec.cross_condition is not None}
    assert set(cross_by_field) == declared_cross_fields
    assert declared_cross_fields == set(PERSISTED_AUTHORITY_FIELDS) - {
        "approved_header_names",
        "approved_header_names_identity",
        "framing_contract_identity",
    }

    for spec in specs:
        canonical = generated_mutation_witness(by_rule[spec.positive_rule_key].observation)
        assert persisted_authority_value_is_canonical(spec.field, canonical[spec.field])
        expected_kinds = {
            *(
                {MutationKind.INVALID}
                if spec.value_kind is not PersistedAuthorityValueKind.BOOL
                else set()
            ),
            MutationKind.NULL,
            MutationKind.MISSING,
            MutationKind.TYPE,
            *(
                {MutationKind.CARDINALITY, MutationKind.MALFORMED}
                if spec.value_kind is PersistedAuthorityValueKind.STR_TUPLE
                else {MutationKind.MALFORMED}
                if spec.value_kind is PersistedAuthorityValueKind.STR
                else set()
            ),
            *({MutationKind.CROSS_CONDITION} if spec.cross_condition is not None else set()),
        }
        assert set(spec.mutation_kinds) == expected_kinds
        if spec.cross_condition is None:
            assert spec.field not in cross_by_field
            continue

        cross = spec.cross_condition
        variant = cross_by_field[spec.field]
        assert variant.cross_condition_fields == (spec.field, cross.companion_field)
        assert tuple(mutation.field for mutation in variant.mutations) == (
            spec.field,
            cross.companion_field,
        )
        assert tuple(mutation.value for mutation in variant.mutations) == (
            cross.target_alternative,
            cross.companion_alternative,
        )
        for mutation in variant.mutations:
            before = canonical[mutation.field]
            after = mutation.value
            assert type(before) is not type(after) or before != after
            assert persisted_authority_value_is_canonical(mutation.field, after)
            assert after not in {
                f"invalid:{mutation.field}",
                (f"invalid:{mutation.field}",),
            }
            isolated = dict(canonical)
            isolated[mutation.field] = after
            assert isolated[mutation.field] == after
            assert persisted_authority_value_is_canonical(mutation.field, isolated[mutation.field])
    python_fields = {
        variant.target_authority_field
        for variant in primitive_variants
        if "python" in variant.consumers
    }
    assert python_fields == {
        "actual_body_byte_count",
        "approved_header_names",
        "approved_header_names_identity",
        "body_complete",
        "content_encoding_state",
        "content_length_state",
        "content_length_value",
        "content_type_state",
        "disposition",
        "framing_input_identity",
        "header_surface_state",
        "http_status",
        "http_version_state",
        "normalized_header_facts_identity",
        "normalized_header_names",
        "observed_body_bytes_lower_bound",
        "observed_http_version",
        "raw_artifact_identity",
        "raw_body_hash",
        "raw_evidence_state",
        "raw_header_field_count",
        "raw_relative_path",
        "transfer_encoding_state",
    }
    assert all(
        variant.consumers == ("external",)
        for variant in primitive_variants
        if variant.mutation_kind is MutationKind.MISSING
    )
    finalizer_fields = {
        variant.target_authority_field
        for variant in primitive_variants
        if "finalizer" in variant.consumers
    }
    assert finalizer_fields == {
        "accepted_framing_class",
        "body_complete",
        "credential_echo",
        "framing_input_identity",
        "framing_rejection_code",
        "framing_status",
        "http_status",
        "observed_body_bytes_lower_bound",
        "observed_http_version",
        "raw_body_hash",
        "raw_header_field_count",
        "raw_relative_path",
    }
    assert all(
        "finalizer" not in variant.consumers
        for variant in primitive_variants
        if variant.target_authority_field
        in {
            "actual_body_byte_count",
            "approved_header_names",
            "approved_header_names_identity",
            "body_byte_count",
            "content_encoding_state",
            "content_length_state",
            "content_length_value",
            "content_type_state",
            "disposition",
            "framing_contract_identity",
            "header_surface_state",
            "http_version_state",
            "normalized_header_facts_identity",
            "raw_artifact_identity",
            "raw_evidence_state",
            "transfer_encoding_state",
        }
    )
    assert set(by_rule) == {rule.key for rule in FRAMING_RULES}


def _python_classifier_field_value(
    observation: FramingObservation, direct_target_path: str
) -> object:
    owner, field = direct_target_path.split(".", 1)
    if owner == "FramingObservation":
        return getattr(observation, field)
    if owner == "NormalizedHeaderFacts":
        return getattr(observation.headers, field)
    raise AssertionError("python consumer target is not classifier input authority")


def _replace_python_classifier_field(
    observation: FramingObservation,
    direct_target_path: str,
    value: object,
) -> FramingObservation:
    owner, field = direct_target_path.split(".", 1)
    if owner == "FramingObservation":
        return replace(observation, **{field: value})
    if owner == "NormalizedHeaderFacts":
        return replace(observation, headers=replace(observation.headers, **{field: value}))
    raise AssertionError("python consumer target is not classifier input authority")


def test_every_python_tagged_mutation_reaches_actual_classifier_input_and_fails_closed() -> None:
    tagged = [
        (case, variant)
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
        if "python" in variant.consumers
    ]
    assert len(tagged) == sum(
        "python" in variant.consumers
        for case in generated_contract_cases()
        for variant in case.noncanonical_variants
    )
    for case, variant in tagged:
        assert type(case.observation) is FramingObservation
        canonical = case.observation
        canonical_decision = classify_framing(canonical)
        assert (
            canonical_decision.rule_key,
            canonical_decision.status,
            canonical_decision.accepted_class,
            canonical_decision.rejection_code,
        ) == (
            variant.expected_first_match_rule,
            variant.expected_status,
            variant.expected_class,
            variant.expected_code,
        )
        target = next(item for item in variant.consumer_targets if item.consumer == "python")
        assert all(
            path.startswith(("FramingObservation.", "NormalizedHeaderFacts."))
            for path in target.direct_target_paths
        )
        actual_values = {
            field: _python_classifier_field_value(canonical, path)
            for field, path in zip(target.authority_fields, target.direct_target_paths, strict=True)
        }
        witnesses = generated_consumer_mutation_witness(variant, "python", actual_values)
        mutated = canonical
        for witness in witnesses:
            assert witness.operation == "set"
            assert (
                _python_classifier_field_value(mutated, witness.direct_target_path)
                is witness.canonical_value
            )
            mutated = _replace_python_classifier_field(
                mutated, witness.direct_target_path, witness.mutated_value
            )
            reached = _python_classifier_field_value(mutated, witness.direct_target_path)
            assert type(reached) is type(witness.mutated_value)
            assert reached == witness.mutated_value
        with pytest.raises(ValueError):
            classify_framing(mutated)


def test_generated_mutation_metadata_rejects_target_and_consumer_path_drift() -> None:
    all_variants = [
        variant for case in generated_contract_cases() for variant in case.noncanonical_variants
    ]
    variants = [variant for variant in all_variants if variant.case_id.startswith("primitive:")]
    direct = next(
        variant
        for variant in variants
        if variant.mutation_kind is MutationKind.TYPE and "finalizer" in variant.consumers
    )
    with pytest.raises(ValueError, match="declared target authority"):
        validate_generated_mutation_case(
            replace(direct, target_authority_field="foreign_authority")
        )
    finalizer_index = direct.consumers.index("finalizer")
    targets = list(direct.consumer_targets)
    targets[finalizer_index] = replace(
        targets[finalizer_index],
        direct_target_paths=("observation.unrelated_field",),
    )
    with pytest.raises(ValueError, match="direct authority"):
        validate_generated_mutation_case(replace(direct, consumer_targets=tuple(targets)))

    tuple_type = next(
        variant
        for variant in variants
        if variant.mutation_kind is MutationKind.TYPE
        and variant.target_authority_field == "approved_header_names"
    )
    external_index = tuple_type.consumers.index("external")
    targets = list(tuple_type.consumer_targets)
    targets[external_index] = replace(
        targets[external_index],
        mutation_value_kinds=(ConsumerMutationValueKind.DECLARED,),
    )
    with pytest.raises(ValueError, match="direct authority"):
        validate_generated_mutation_case(replace(tuple_type, consumer_targets=tuple(targets)))
    with pytest.raises(ValueError, match="does not reach"):
        generated_consumer_mutation_witness(tuple_type, "finalizer")

    cross = next(
        variant for variant in variants if variant.mutation_kind is MutationKind.CROSS_CONDITION
    )
    with pytest.raises(ValueError, match="cross-condition mutation fields"):
        validate_generated_mutation_case(
            replace(cross, cross_condition_fields=(cross.target_authority_field,))
        )


def test_runtime_consumer_witness_adapts_to_exact_actual_prestate() -> None:
    class DictSubclass(dict[str, object]):
        pass

    class StringSubclass(str):
        pass

    all_variants = [
        variant for case in generated_contract_cases() for variant in case.noncanonical_variants
    ]
    variants = [variant for variant in all_variants if variant.case_id.startswith("primitive:")]

    tuple_type = next(
        variant
        for variant in variants
        if variant.mutation_kind is MutationKind.TYPE
        and variant.target_authority_field == "approved_header_names"
    )
    actual_headers = ["content-type", "x-request-id"]
    tuple_witness = generated_consumer_mutation_witness(
        tuple_type,
        "external",
        {"approved_header_names": actual_headers},
    )[0]
    assert tuple_witness.canonical_value is actual_headers
    assert type(tuple_witness.canonical_value) is list
    assert type(tuple_witness.mutated_value) is not list
    assert tuple_witness.mutated_value == actual_headers

    string_type = next(
        variant
        for variant in variants
        if variant.mutation_kind is MutationKind.TYPE
        and variant.target_authority_field == "body_hash"
    )
    runtime_hash = "sha256:" + "1" * 64
    string_witness = generated_consumer_mutation_witness(
        string_type, "external", {"body_hash": runtime_hash}
    )[0]
    assert string_witness.canonical_value == runtime_hash
    assert type(string_witness.canonical_value) is str
    assert type(string_witness.mutated_value) is not str
    assert string_witness.mutated_value == runtime_hash

    by_kind = {
        variant.mutation_kind: variant
        for variant in variants
        if variant.target_authority_field == "raw_header_field_count"
    }
    type_witness = generated_consumer_mutation_witness(
        by_kind[MutationKind.TYPE],
        "external",
        {"raw_header_field_count": 9},
    )[0]
    assert type_witness.canonical_value == 9
    assert type_witness.mutated_value is True
    null_witness = generated_consumer_mutation_witness(
        by_kind[MutationKind.NULL],
        "external",
        {"raw_header_field_count": 9},
    )[0]
    assert null_witness.canonical_value == 9
    assert null_witness.mutated_value is None
    missing_witness = generated_consumer_mutation_witness(
        by_kind[MutationKind.MISSING],
        "external",
        {"raw_header_field_count": 9},
    )[0]
    assert missing_witness.operation == "remove"
    assert missing_witness.canonical_value == 9
    raw_count_drift = next(
        variant for variant in all_variants if variant.case_id == "raw_header_field_count_drift"
    )
    invalid_witness = generated_consumer_mutation_witness(
        raw_count_drift,
        "external",
        {"raw_header_field_count": 2},
    )[0]
    assert invalid_witness.canonical_value == 2
    assert invalid_witness.mutated_value == 3

    cross = by_kind[MutationKind.CROSS_CONDITION]
    cross_actual = {
        "raw_header_field_count": 9,
        "normalized_header_facts_identity": ("m3-normalized-header-facts:sha256:" + "1" * 64),
    }
    cross_witnesses = generated_consumer_mutation_witness(cross, "external", cross_actual)
    assert tuple(item.canonical_value for item in cross_witnesses) == tuple(
        cross_actual[item.field] for item in cross_witnesses
    )
    assert tuple(item.mutated_value for item in cross_witnesses) == tuple(
        mutation.value for mutation in cross.mutations
    )

    for bad_mapping in (
        DictSubclass({"raw_header_field_count": 9}),
        {StringSubclass("raw_header_field_count"): 9},
    ):
        with pytest.raises(ValueError, match="mapping is noncanonical"):
            generated_consumer_mutation_witness(by_kind[MutationKind.TYPE], "external", bad_mapping)
    with pytest.raises(ValueError, match="target field is missing"):
        generated_consumer_mutation_witness(by_kind[MutationKind.MISSING], "external", {})
    with pytest.raises(ValueError, match="target type differs"):
        generated_consumer_mutation_witness(
            by_kind[MutationKind.TYPE],
            "external",
            {"raw_header_field_count": True},
        )
    cross_noop = {mutation.field: mutation.value for mutation in cross.mutations}
    with pytest.raises(ValueError, match="canonical no-op"):
        generated_consumer_mutation_witness(cross, "external", cross_noop)


def test_generated_fact_free_v2_and_v1_cases_share_exact_authority() -> None:
    cases = [event for case in generated_contract_cases() for event in case.fact_free_event_cases]
    positive_v2 = [
        case
        for case in cases
        if case.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2" and case.expected_match
    ]
    assert {case.disposition for case in positive_v2} == {
        "started",
        "interrupted_unknown_after_start",
        "transport_unavailable",
        "deadline_exceeded",
        "response_invalid",
        "response_too_large",
        "authentication_failed",
        "provider_rejected",
    }
    for case in cases:
        projection = fact_free_event_case_projection(case)
        if case.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2":
            assert fact_free_v2_event_matches(projection) is case.expected_match
        else:
            assert not fact_free_v2_event_matches(projection)
            assert all(projection[name] is None for name in V2_ONLY_LEDGER_COLUMNS)
    with pytest.raises(ValueError, match="topology"):
        canonical_fact_free_v2_event_projection(
            event_kind="TERMINAL", disposition="retryable_status"
        )
    with pytest.raises(ValueError, match="topology"):
        canonical_fact_free_v2_event_projection(
            event_kind="TERMINAL", disposition="candidate_invalid"
        )
    with pytest.raises(ValueError, match="topology"):
        canonical_fact_free_v2_event_projection(
            event_kind="TERMINAL", disposition="request_integrity"
        )


def test_v2_event_metadata_rows_own_python_credential_and_error_semantics() -> None:
    for rule in V2_EVENT_METADATA_RULES:
        projection = {
            "event_kind": rule.event_kind,
            "disposition": rule.disposition,
            **canonical_v2_event_metadata(event_kind=rule.event_kind, disposition=rule.disposition),
        }
        assert type(projection["event_kind"]) is str
        assert type(projection["disposition"]) is str
        assert type(projection["credential_echo"]) is bool
        assert projection["error_code"] is None or type(projection["error_code"]) is str
        assert v2_event_metadata_matches(projection)
        if rule.event_kind == "TERMINAL":
            assert projection["credential_echo"] is (rule.disposition == "credential_echo")
            assert projection["error_code"] == (
                None if rule.disposition == "success" else rule.disposition
            )
        for field, foreign in (
            ("credential_echo", not rule.credential_echo),
            ("error_code", "foreign" if rule.error_code is None else None),
        ):
            mutated = {**projection, field: foreign}
            assert not v2_event_metadata_matches(mutated)
    with pytest.raises(ValueError, match="metadata topology"):
        canonical_v2_event_metadata(event_kind="TERMINAL", disposition="request_integrity")


def test_v2_event_metadata_requires_exact_keys_and_builtin_types_before_equality() -> None:
    false_projection = {
        "event_kind": "START",
        "disposition": "started",
        **canonical_v2_event_metadata(event_kind="START", disposition="started"),
    }
    true_projection = {
        "event_kind": "TERMINAL",
        "disposition": "credential_echo",
        **canonical_v2_event_metadata(event_kind="TERMINAL", disposition="credential_echo"),
    }
    assert false_projection["credential_echo"] is False
    assert true_projection["credential_echo"] is True
    assert not v2_event_metadata_matches({**false_projection, "credential_echo": 0})
    assert not v2_event_metadata_matches({**true_projection, "credential_echo": 1})

    for field in ("event_kind", "disposition", "credential_echo", "error_code"):
        missing = {name: value for name, value in false_projection.items() if name != field}
        assert not v2_event_metadata_matches(missing)
    assert not v2_event_metadata_matches({**false_projection, "foreign": None})

    class StringSubclass(str):
        pass

    for field, foreign in (
        ("event_kind", StringSubclass("START")),
        ("disposition", StringSubclass("started")),
        ("credential_echo", "false"),
        ("error_code", 0),
    ):
        assert not v2_event_metadata_matches({**false_projection, field: foreign})
    assert not v2_event_metadata_matches(
        {**true_projection, "error_code": StringSubclass("credential_echo")}
    )

    fact_free = canonical_fact_free_v2_event_projection(event_kind="START", disposition="started")
    missing_error = {name: value for name, value in fact_free.items() if name != "error_code"}
    assert not fact_free_v2_event_matches(missing_error)
    assert not fact_free_v2_event_matches({**fact_free, "foreign": None})


def test_canonical_v2_event_metadata_returns_only_exact_builtin_projection() -> None:
    for rule in V2_EVENT_METADATA_RULES:
        result = canonical_v2_event_metadata(
            event_kind=rule.event_kind, disposition=rule.disposition
        )
        assert type(result) is dict
        assert tuple(result) == ("credential_echo", "error_code")
        assert all(type(key) is str for key in result)
        assert type(result["credential_echo"]) is bool
        assert result["error_code"] is None or type(result["error_code"]) is str

    class StringSubclass(str):
        pass

    with pytest.raises(ValueError, match="metadata topology"):
        canonical_v2_event_metadata(event_kind=StringSubclass("START"), disposition="started")
    with pytest.raises(ValueError, match="metadata topology"):
        canonical_v2_event_metadata(event_kind="START", disposition=StringSubclass("started"))


def test_all_public_builders_reject_bool_for_int_and_str_subclass_inputs() -> None:
    class StringSubclass(str):
        pass

    facts = normalize_approved_headers(
        (("content-type", "application/json"),), raw_header_field_count=1
    )
    canonical = {
        "disposition": "response_invalid",
        "http_status": 200,
        "http_version": "HTTP/2",
        "headers": facts,
        "raw_header_field_count": 1,
        "body_complete": True,
        "actual_body_byte_count": 1,
        "observed_body_bytes_lower_bound": 1,
        "raw_body_hash": _RAW_HASH,
        "raw_relative_path": _RAW_PATH,
    }
    for field in (
        "http_status",
        "raw_header_field_count",
        "actual_body_byte_count",
        "observed_body_bytes_lower_bound",
    ):
        with pytest.raises(ValueError):
            build_framing_observation(**{**canonical, field: True})  # type: ignore[arg-type]
    for field in (
        "disposition",
        "http_version",
        "raw_body_hash",
        "raw_relative_path",
    ):
        with pytest.raises(ValueError):
            build_framing_observation(
                **{**canonical, field: StringSubclass(str(canonical[field]))}  # type: ignore[arg-type]
            )
    with pytest.raises(ValueError, match="unavailable framing path"):
        build_unavailable_observation(disposition="credential_echo", http_status=True)
    with pytest.raises(ValueError, match="unavailable framing path"):
        build_unavailable_observation(
            disposition=StringSubclass("credential_echo"), http_status=200
        )


def test_header_normalization_and_reconstruction_require_exact_tuple_and_string_shapes() -> None:
    class StringSubclass(str):
        pass

    for items in (
        ((StringSubclass("content-type"), "application/json"),),
        (("content-type", StringSubclass("application/json")),),
    ):
        facts = normalize_approved_headers(items, raw_header_field_count=1)
        assert facts.surface_state is HeaderSurfaceState.INVALID
        assert facts.occurrences == ()

    facts = normalize_approved_headers(
        (("content-type", "application/json"),), raw_header_field_count=1
    )
    canonical = {
        "approved_header_names": facts.approved_header_names,
        "approved_header_names_identity": facts.approved_header_names_identity,
        "occurrences": tuple((item.name, item.value) for item in facts.occurrences),
        "observed_names": facts.observed_names,
        "raw_header_field_count": facts.raw_header_field_count,
        "surface_state": facts.surface_state.value,
        "facts_identity": facts.facts_identity,
    }
    mutations = (
        (
            "approved_header_names",
            (StringSubclass(APPROVED_HEADER_NAMES[0]), *APPROVED_HEADER_NAMES[1:]),
        ),
        ("approved_header_names_identity", StringSubclass(facts.approved_header_names_identity)),
        ("occurrences", ((StringSubclass("content-type"), "application/json"),)),
        ("occurrences", (("content-type", StringSubclass("application/json")),)),
        ("observed_names", (StringSubclass("content-type"),)),
        ("raw_header_field_count", True),
        ("surface_state", StringSubclass(facts.surface_state.value)),
        ("facts_identity", StringSubclass(facts.facts_identity)),
    )
    for field, foreign in mutations:
        with pytest.raises(ValueError):
            reconstruct_normalized_headers(**{**canonical, field: foreign})  # type: ignore[arg-type]


def test_classification_rejects_every_noncanonical_primitive_before_identity_equality() -> None:
    class StringSubclass(str):
        pass

    observation = _observation(
        header_items=(
            ("content-type", "application/json"),
            ("content-length", "2"),
        )
    )
    for field in (
        "http_status",
        "raw_header_field_count",
        "content_length_value",
        "actual_body_byte_count",
        "observed_body_bytes_lower_bound",
    ):
        with pytest.raises(ValueError):
            classify_framing(replace(observation, **{field: True}))
    for field in (
        "disposition",
        "observed_http_version",
        "raw_body_hash",
        "raw_relative_path",
        "raw_artifact_identity",
        "input_identity",
    ):
        current = getattr(observation, field)
        assert type(current) is str
        with pytest.raises(ValueError):
            classify_framing(replace(observation, **{field: StringSubclass(current)}))

    unavailable = build_unavailable_observation(disposition="credential_echo", http_status=200)
    with pytest.raises(ValueError):
        classify_framing(replace(unavailable, http_status=True))
    with pytest.raises(ValueError):
        classify_framing(replace(unavailable, disposition=StringSubclass(unavailable.disposition)))
    with pytest.raises(ValueError):
        classify_framing(
            replace(unavailable, input_identity=StringSubclass(unavailable.input_identity))
        )


def test_classification_rejects_noncanonical_header_dataclass_primitives() -> None:
    class StringSubclass(str):
        pass

    observation = _observation()
    headers = observation.headers
    occurrence = headers.occurrences[0]
    occurrence_subclass = type("OccurrenceSubclass", (HeaderOccurrence,), {})
    header_mutations = (
        replace(
            headers,
            approved_header_names=(
                StringSubclass(headers.approved_header_names[0]),
                *headers.approved_header_names[1:],
            ),
        ),
        replace(
            headers,
            approved_header_names_identity=StringSubclass(headers.approved_header_names_identity),
        ),
        replace(
            headers,
            occurrences=(HeaderOccurrence(StringSubclass(occurrence.name), occurrence.value),),
        ),
        replace(
            headers,
            occurrences=(occurrence_subclass(occurrence.name, occurrence.value),),
        ),
        replace(
            headers,
            occurrences=(HeaderOccurrence(occurrence.name, StringSubclass(occurrence.value)),),
        ),
        replace(headers, observed_names=(StringSubclass(headers.observed_names[0]),)),
        replace(headers, raw_header_field_count=True),
        replace(headers, facts_identity=StringSubclass(headers.facts_identity)),
    )
    for mutated_headers in header_mutations:
        with pytest.raises(ValueError):
            classify_framing(replace(observation, headers=mutated_headers))


def test_projection_validation_and_outputs_use_only_exact_builtin_primitives() -> None:
    class StringSubclass(str):
        pass

    observation = _observation(disposition="success")
    decision = classify_framing(observation)
    projection = canonical_observation_projection(observation)
    assert type(projection) is dict
    assert all(type(name) is str for name in projection)
    exact_int_fields = (
        "actual_body_byte_count",
        "body_byte_count",
        "content_length_value",
        "http_status",
        "observed_body_bytes_lower_bound",
        "raw_header_field_count",
    )
    for field in exact_int_fields:
        assert projection[field] is None or type(projection[field]) is int
    assert type(projection["body_complete"]) is bool
    for field in (
        "disposition",
        "framing_contract_identity",
        "framing_input_identity",
        "framing_status",
        "observed_http_version",
        "raw_artifact_identity",
        "body_hash",
        "body_relative_path",
    ):
        assert projection[field] is None or type(projection[field]) is str
    for field in (
        "approved_header_names",
        "normalized_content_encoding_values",
        "normalized_content_length_values",
        "normalized_content_type_values",
        "normalized_header_names",
        "normalized_transfer_encoding_values",
        "normalized_x_request_id_values",
    ):
        assert type(projection[field]) is tuple
        assert all(type(item) is str for item in projection[field])

    for field, foreign in (
        ("framing_status", StringSubclass(decision.status.value)),
        ("accepted_framing_class", StringSubclass(decision.accepted_class or "")),
        ("framing_input_identity", StringSubclass(decision.input_identity)),
    ):
        supplied = {
            "framing_status": decision.status.value,
            "accepted_framing_class": decision.accepted_class,
            "framing_rejection_code": decision.rejection_code,
            "framing_input_identity": decision.input_identity,
            field: foreign,
        }
        assert not projection_matches(observation, **supplied)  # type: ignore[arg-type]

    legacy = legacy_v2_raw_projection(observation)
    with pytest.raises(ValueError, match="legacy raw projection"):
        legacy_v2_raw_projection(observation, {**legacy, "body_byte_count": True})
    with pytest.raises(ValueError, match="legacy raw projection"):
        legacy_v2_raw_projection(
            observation,
            {**legacy, "body_hash": StringSubclass(str(legacy["body_hash"]))},
        )


def test_public_mapping_validators_reject_dict_subclasses_before_value_equality() -> None:
    class DictSubclass(dict[str, object]):
        pass

    metadata = {
        "event_kind": "START",
        "disposition": "started",
        **canonical_v2_event_metadata(event_kind="START", disposition="started"),
    }
    fact_free = canonical_fact_free_v2_event_projection(event_kind="START", disposition="started")
    assert not v2_event_metadata_matches(DictSubclass(metadata))
    assert not fact_free_v2_event_matches(DictSubclass(fact_free))


def test_all_three_framing_classes_require_complete_bound_raw_evidence() -> None:
    decisions = {
        classify_framing(case.observation).accepted_class
        for case in generated_contract_cases()
        if case.expected_status is FramingStatus.ACCEPTED
    }
    assert decisions == {
        "http_1_1_chunked",
        "http_1_1_content_length",
        "http_2_data",
    }
    for case in generated_contract_cases():
        if case.expected_status is FramingStatus.ACCEPTED:
            assert case.observation.body_complete is True
            assert case.observation.raw_evidence_state is RawEvidenceState.BOUND
            assert case.observation.raw_artifact_identity is not None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "http_version": None,
                "header_items": (
                    ("content-type", "application/json"),
                    ("content-length", "02"),
                ),
            },
            "missing_http_version",
        ),
        (
            {
                "http_version": None,
                "header_items": (
                    ("content-type", "application/json"),
                    ("transfer-encoding", "gzip"),
                ),
            },
            "missing_http_version",
        ),
        (
            {
                "http_version": "HTTP/1.1",
                "header_items": (
                    ("content-type", "application/json"),
                    ("content-length", "2"),
                    ("content-length", "2"),
                    ("transfer-encoding", "gzip"),
                ),
            },
            "te_and_cl",
        ),
        (
            {
                "header_items": (
                    ("content-type", "application/json"),
                    ("content-encoding", "gzip"),
                ),
                "body_complete": False,
                "byte_count": None,
                "persist_raw": False,
            },
            "compression_not_identity",
        ),
        (
            {
                "header_items": (("content-type", "text/html"),),
                "body_complete": False,
                "byte_count": None,
                "persist_raw": False,
            },
            "response_body_incomplete",
        ),
        (
            {
                "http_version": "HTTP/1.1",
                "header_items": (
                    ("content-type", "text/html"),
                    ("content-length", "3"),
                ),
            },
            "content_length_mismatch",
        ),
        (
            {"header_items": (("content-type", "text/html"),), "persist_raw": False},
            "invalid_content_type",
        ),
    ],
)
def test_first_match_precedence_with_coexisting_defects(
    kwargs: dict[str, object], expected: str
) -> None:
    assert _code(**kwargs) == expected


def test_incomplete_and_rawless_cannot_be_accepted() -> None:
    assert (
        _code(body_complete=False, byte_count=None, persist_raw=False) == "response_body_incomplete"
    )
    assert _code(persist_raw=False) == "raw_evidence_missing"


def test_content_length_mismatch_is_impossible_without_complete_exact_bytes() -> None:
    incomplete = _observation(
        http_version="HTTP/1.1",
        header_items=(("content-type", "application/json"), ("content-length", "3")),
        body_complete=False,
        byte_count=None,
        persist_raw=False,
    )
    assert classify_framing(incomplete).rejection_code == "response_body_incomplete"
    assert not projection_matches(
        incomplete,
        framing_status="rejected",
        accepted_framing_class=None,
        framing_rejection_code="content_length_mismatch",
        framing_input_identity=incomplete.input_identity,
    )
    with pytest.raises(ValueError, match="incomplete body"):
        _observation(
            body_complete=False,
            byte_count=2,
            persist_raw=False,
        )


def test_json_bytes_with_text_html_fail_media_admission() -> None:
    # Body parsing is intentionally not an input; media admission happens first.
    observation = _observation(header_items=(("content-type", "text/html"),))
    assert classify_framing(observation).rejection_code == "invalid_content_type"


def test_header_normalization_binds_exact_authority_multiplicity_and_bounds() -> None:
    items = (
        ("X-Unapproved", "ignored"),
        ("CONTENT-TYPE", "application/json"),
        ("content-length", "2"),
        ("content-length", "2"),
    )
    facts = normalize_approved_headers(items, raw_header_field_count=len(items))
    assert facts.approved_header_names == APPROVED_HEADER_NAMES
    assert facts.approved_header_names_identity == APPROVED_HEADER_NAMES_IDENTITY
    assert facts.raw_header_field_count == len(items)
    assert facts.observed_names == ("content-length", "content-type")
    assert [item.name for item in facts.occurrences] == [
        "content-length",
        "content-length",
        "content-type",
    ]
    assert facts.surface_state is HeaderSurfaceState.VALID

    maximum_items = tuple(("x-request-id", str(i)) for i in range(8))
    overflow_items = tuple(("x-request-id", str(i)) for i in range(9))
    maximum = normalize_approved_headers(maximum_items, raw_header_field_count=len(maximum_items))
    overflow = normalize_approved_headers(
        overflow_items, raw_header_field_count=len(overflow_items)
    )
    raw_surface_overflow = normalize_approved_headers((), raw_header_field_count=129)
    assert maximum.surface_state is HeaderSurfaceState.VALID
    assert overflow.surface_state is HeaderSurfaceState.INVALID
    assert raw_surface_overflow.surface_state is HeaderSurfaceState.INVALID
    assert raw_surface_overflow.raw_header_field_count == 129


def test_raw_header_field_count_is_separate_bounded_provenance() -> None:
    at_limit = _observation(raw_header_field_count=128, disposition="success")
    assert at_limit.headers.surface_state is HeaderSurfaceState.VALID
    assert at_limit.raw_header_field_count == 128
    overflow = _observation(raw_header_field_count=129)
    assert overflow.headers.surface_state is HeaderSurfaceState.INVALID
    assert overflow.headers.occurrences == ()
    assert classify_framing(overflow).rejection_code == "invalid_approved_header_surface"
    with pytest.raises(ValueError, match="raw header field count"):
        normalize_approved_headers(
            (("content-type", "application/json"),), raw_header_field_count=0
        )
    facts = normalize_approved_headers(
        (("content-type", "application/json"),), raw_header_field_count=1
    )
    with pytest.raises(ValueError, match="framing observation facts"):
        build_framing_observation(
            disposition="success",
            http_status=200,
            http_version="HTTP/2",
            headers=facts,
            raw_header_field_count=2,
            body_complete=True,
            actual_body_byte_count=2,
            raw_body_hash=_RAW_HASH,
            raw_relative_path=_RAW_PATH,
        )


@pytest.mark.parametrize(
    ("header_items", "permitted"),
    (
        ((("content-type", "application/json"),), True),
        (
            (
                ("content-type", "application/json"),
                ("content-encoding", "identity"),
            ),
            True,
        ),
        (
            (
                ("content-type", "application/json"),
                ("content-encoding", "gzip"),
            ),
            False,
        ),
        (
            (
                ("content-type", "application/json"),
                ("content-encoding", "br"),
            ),
            False,
        ),
        (
            (
                ("content-type", "application/json"),
                ("content-encoding", "identity"),
                ("content-encoding", "identity"),
            ),
            False,
        ),
    ),
)
def test_raw_body_persistence_is_derived_only_from_normalized_headers(
    header_items: tuple[tuple[str, str], ...], permitted: bool
) -> None:
    headers = normalize_approved_headers(header_items, raw_header_field_count=len(header_items))
    assert raw_body_persistence_permitted(headers) is permitted


def test_raw_body_persistence_rejects_invalid_header_surface_and_foreign_facts() -> None:
    invalid = normalize_approved_headers((), raw_header_field_count=129)
    assert raw_body_persistence_permitted(invalid) is False
    valid = normalize_approved_headers(
        (("content-type", "application/json"),), raw_header_field_count=1
    )
    with pytest.raises(ValueError, match="normalized header facts drift"):
        raw_body_persistence_permitted(
            replace(valid, facts_identity="m3-normalized-header-facts:sha256:" + "f" * 64)
        )


def test_gzip_response_that_contains_a_credential_must_not_be_persisted() -> None:
    headers = normalize_approved_headers(
        (
            ("content-type", "application/json"),
            ("content-encoding", "gzip"),
        ),
        raw_header_field_count=2,
    )
    compressed_body_containing_secret = b"gzip-bytes-with-DEEPSEEK_API_KEY-marker"
    assert compressed_body_containing_secret
    assert raw_body_persistence_permitted(headers) is False


def test_unapproved_header_cannot_be_a_secondary_framing_input() -> None:
    observation = _observation(
        header_items=(
            ("content-type", "application/json"),
            ("x-content-length", "999"),
            ("x-transfer-encoding", "gzip"),
        ),
        disposition="success",
    )
    decision = classify_framing(observation)
    assert observation.headers.observed_names == ("content-type",)
    assert decision.status is FramingStatus.ACCEPTED
    assert decision.accepted_class == "http_2_data"


def test_persisted_header_authority_and_facts_drift_fail_closed() -> None:
    facts = normalize_approved_headers(
        (("content-type", "application/json"),), raw_header_field_count=1
    )
    occurrences = tuple((item.name, item.value) for item in facts.occurrences)
    rebuilt = reconstruct_normalized_headers(
        approved_header_names=facts.approved_header_names,
        approved_header_names_identity=facts.approved_header_names_identity,
        occurrences=occurrences,
        observed_names=facts.observed_names,
        raw_header_field_count=1,
        surface_state=facts.surface_state.value,
        facts_identity=facts.facts_identity,
    )
    assert rebuilt == facts
    with pytest.raises(ValueError, match="authority drift"):
        reconstruct_normalized_headers(
            approved_header_names=("content-type",),
            approved_header_names_identity=facts.approved_header_names_identity,
            occurrences=occurrences,
            observed_names=facts.observed_names,
            raw_header_field_count=1,
            surface_state=facts.surface_state.value,
            facts_identity=facts.facts_identity,
        )
    with pytest.raises(ValueError, match="facts drift"):
        reconstruct_normalized_headers(
            approved_header_names=facts.approved_header_names,
            approved_header_names_identity=facts.approved_header_names_identity,
            occurrences=occurrences,
            observed_names=("content-type", "x-foreign"),
            raw_header_field_count=1,
            surface_state=facts.surface_state.value,
            facts_identity=facts.facts_identity,
        )


def test_foreign_decision_and_input_identity_have_no_authority() -> None:
    observation = _observation(persist_raw=False)
    assert not projection_matches(
        observation,
        framing_status="accepted",
        accepted_framing_class="http_2_data",
        framing_rejection_code=None,
        framing_input_identity=observation.input_identity,
    )
    with pytest.raises(ValueError, match="input identity drift"):
        classify_framing(replace(observation, input_identity="m3-framing-input:sha256:" + "f" * 64))
    with pytest.raises(ValueError, match="header binding drift"):
        classify_framing(
            replace(
                observation,
                headers=replace(
                    observation.headers,
                    approved_header_names_identity="m3-approved-header-names:sha256:" + "f" * 64,
                ),
            )
        )

    rejected_success = replace(observation, disposition="success", input_identity="")
    rejected_success = replace(
        rejected_success,
        input_identity=_observation(persist_raw=False, disposition="success").input_identity,
    )
    assert not projection_matches(
        rejected_success,
        framing_status="rejected",
        accepted_framing_class=None,
        framing_rejection_code="raw_evidence_missing",
        framing_input_identity=rejected_success.input_identity,
    )


def test_credential_and_persistence_failures_are_fact_free_and_total() -> None:
    for disposition in ("credential_echo", "evidence_persistence_failure"):
        observation = build_unavailable_observation(disposition=disposition, http_status=200)
        decision = classify_framing(observation)
        assert decision.status is FramingStatus.UNAVAILABLE
        assert decision.accepted_class is None
        assert decision.rejection_code is None
        projection = canonical_observation_projection(observation)
        assert projection["approved_header_names"] == APPROVED_HEADER_NAMES
        assert projection["normalized_header_names"] == ()
        assert projection["normalized_header_facts_identity"] is None
    with pytest.raises(ValueError, match="framing observation facts"):
        _observation(disposition="credential_echo")


def test_validation_internal_failure_is_v2_only_exact_metadata_with_safe_response_facts() -> None:
    metadata = canonical_v2_event_metadata(
        event_kind="TERMINAL", disposition="validation_internal_failure"
    )
    assert metadata == {
        "credential_echo": False,
        "error_code": "validation_internal_failure",
    }
    assert v2_event_metadata_matches(
        {
            "event_kind": "TERMINAL",
            "disposition": "validation_internal_failure",
            **metadata,
        }
    )
    observation = _observation(
        disposition="validation_internal_failure",
        persist_raw=True,
    )
    projection = canonical_observation_projection(observation)
    assert projection["raw_evidence_state"] == "bound"
    assert projection["body_hash"] == _RAW_HASH
    assert projection["framing_status"] == "accepted"
    assert projection["accepted_framing_class"] == "http_2_data"
    assert projection["framing_rejection_code"] is None
    assert "validation_internal_failure" not in {
        case.disposition
        for generated in generated_contract_cases()
        for case in generated.fact_free_event_cases
        if case.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1"
    }


def test_content_length_and_body_exact_maximum_bounds() -> None:
    maximum = _observation(
        header_items=(
            ("content-type", "application/json"),
            ("content-length", str(POSTGRES_BIGINT_MAX)),
        )
    )
    over = _observation(
        header_items=(
            ("content-type", "application/json"),
            ("content-length", str(POSTGRES_BIGINT_MAX + 1)),
        )
    )
    assert maximum.content_length_state is ContentLengthState.VALID
    assert classify_framing(maximum).rejection_code == "content_length_mismatch"
    assert over.content_length_state is ContentLengthState.INVALID
    assert classify_framing(over).rejection_code == "invalid_content_length"

    exact_body = _observation(
        http_version="HTTP/1.1",
        header_items=(
            ("content-type", "application/json"),
            ("content-length", str(MAX_RAW_RESPONSE_BYTES)),
        ),
        byte_count=MAX_RAW_RESPONSE_BYTES,
        disposition="success",
    )
    assert classify_framing(exact_body).status is FramingStatus.ACCEPTED
    with pytest.raises(ValueError, match="byte count"):
        _observation(byte_count=MAX_RAW_RESPONSE_BYTES + 1)


def test_contract_and_fact_identities_are_deterministic_and_typed() -> None:
    assert APPROVED_HEADER_NAMES_IDENTITY == (
        "m3-approved-header-names:sha256:"
        "691b174956a9e0525d007f30953c2f7eaf8eeb5e9f18e5cc51db6e657695cf9b"
    )
    assert framing_contract_identity() == framing_contract_identity()
    assert framing_contract_identity() == FRAMING_CONTRACT_IDENTITY
    assert FRAMING_CONTRACT_IDENTITY == (
        "m3-provider-framing-contract:sha256:"
        "53963f709faed47914d8a2fdd3711e3a848fbcdcca3ff5511645f46ce92f663e"
    )
    first = _observation()
    second = _observation()
    assert first.input_identity == second.input_identity
    assert first.headers.facts_identity == second.headers.facts_identity
    assert first.raw_artifact_identity == second.raw_artifact_identity
    assert canonical_observation_projection(first) == canonical_observation_projection(second)
    assert "header_occurrences" not in canonical_observation_projection(first)


def test_generated_python_identity_bytes_are_exactly_the_persisted_authority() -> None:
    def digest(kind: str, raw: bytes) -> str:
        return f"{kind}:sha256:{hashlib.sha256(raw).hexdigest()}"

    assert (
        digest("m3-approved-header-names", canonical_approved_header_names_bytes())
        == APPROVED_HEADER_NAMES_IDENTITY
    )
    for case in generated_contract_cases():
        observation = case.observation
        projection = canonical_observation_projection(observation)
        assert (
            digest("m3-framing-input", canonical_framing_input_bytes(observation))
            == observation.input_identity
        )
        if not hasattr(observation, "headers"):
            assert projection["normalized_header_facts_identity"] is None
            continue
        assert (
            digest(
                "m3-normalized-header-facts",
                canonical_normalized_header_facts_bytes(observation.headers),
            )
            == observation.headers.facts_identity
        )
        raw = canonical_raw_artifact_bytes(observation)
        if raw is None:
            assert observation.raw_artifact_identity is None
        else:
            assert digest("m3-provider-raw-artifact", raw) == observation.raw_artifact_identity
        assert projection["normalized_content_encoding_values"] == tuple(
            item.value
            for item in observation.headers.occurrences
            if item.name == "content-encoding"
        )
        assert projection["normalized_content_length_values"] == tuple(
            item.value for item in observation.headers.occurrences if item.name == "content-length"
        )


def test_representative_canonical_serializations_are_byte_exact() -> None:
    observation = _observation()
    headers = observation.headers
    assert canonical_approved_header_names_bytes() == (
        b'["content-encoding","content-length","content-type","transfer-encoding","x-request-id"]'
    )
    assert canonical_normalized_header_facts_bytes(headers) == (
        b'{"approved_header_names_identity":"'
        + APPROVED_HEADER_NAMES_IDENTITY.encode()
        + b'","occurrences":{"content-encoding":[],"content-length":[],'
        b'"content-type":["application/json"],"transfer-encoding":[],'
        b'"x-request-id":[]},"raw_header_field_count":1,"surface_state":"valid"}'
    )
    assert canonical_raw_artifact_bytes(observation) == (
        b'{"body_byte_count":2,"body_hash":"'
        + _RAW_HASH.encode()
        + b'","relative_path":"raw/case.json"}'
    )
    assert canonical_framing_input_bytes(observation) == (
        b'{"actual_body_byte_count":2,"body_complete":true,'
        b'"content_encoding_state":"absent","content_length_state":"absent",'
        b'"content_length_value":null,"content_type_state":"approved_json",'
        b'"disposition":"response_invalid","header_facts_identity":"'
        + headers.facts_identity.encode()
        + b'","http_status":200,"http_version_state":"http_2",'
        b'"observed_body_bytes_lower_bound":2,"observed_http_version":"HTTP/2",'
        b'"raw_artifact_identity":"'
        + observation.raw_artifact_identity.encode()
        + b'","raw_evidence_state":"bound","raw_header_field_count":1,'
        b'"transfer_encoding_state":"absent"}'
    )
    unavailable = build_unavailable_observation(
        disposition="evidence_persistence_failure", http_status=200
    )
    assert canonical_framing_input_bytes(unavailable) == (
        b'{"disposition":"evidence_persistence_failure","framing_facts":null,"http_status":200}'
    )


def test_identity_only_mutations_are_noncanonical() -> None:
    observation = _observation(disposition="success")
    mutated_header = replace(
        observation.headers,
        facts_identity="m3-normalized-header-facts:sha256:" + "f" * 64,
    )
    with pytest.raises(ValueError, match="header binding drift"):
        classify_framing(replace(observation, headers=mutated_header))
    with pytest.raises(ValueError, match="input identity drift"):
        classify_framing(
            replace(
                observation,
                raw_artifact_identity="m3-provider-raw-artifact:sha256:" + "f" * 64,
            )
        )
    assert not projection_matches(
        observation,
        framing_status="accepted",
        accepted_framing_class="http_2_data",
        framing_rejection_code=None,
        framing_input_identity="m3-framing-input:sha256:" + "f" * 64,
    )


def test_legacy_raw_projection_is_exact_for_all_canonical_raw_states() -> None:
    complete = _observation(disposition="success")
    expected_complete = {
        "body_byte_count": 2,
        "body_hash": _RAW_HASH,
        "body_relative_path": _RAW_PATH,
        "observed_body_bytes_lower_bound": 2,
    }
    assert legacy_v2_raw_projection(complete) == expected_complete
    complete_projection = canonical_observation_projection(complete)
    assert all(complete_projection[name] == value for name, value in expected_complete.items())
    incomplete = _observation(
        body_complete=False,
        byte_count=None,
        observed_lower_bound=MAX_OBSERVED_BODY_BYTES_LOWER_BOUND,
        persist_raw=False,
    )
    assert legacy_v2_raw_projection(incomplete) == {
        "body_byte_count": None,
        "body_hash": None,
        "body_relative_path": None,
        "observed_body_bytes_lower_bound": MAX_OBSERVED_BODY_BYTES_LOWER_BOUND,
    }
    unavailable = build_unavailable_observation(disposition="credential_echo", http_status=200)
    assert legacy_v2_raw_projection(unavailable) == {
        "body_byte_count": None,
        "body_hash": None,
        "body_relative_path": None,
        "observed_body_bytes_lower_bound": None,
    }
    for field, foreign in (
        ("body_byte_count", 3),
        ("body_hash", "sha256:" + "f" * 64),
        ("body_relative_path", "raw/foreign.json"),
        ("observed_body_bytes_lower_bound", 3),
    ):
        supplied = legacy_v2_raw_projection(complete)
        supplied[field] = foreign
        with pytest.raises(ValueError, match="legacy raw projection"):
            legacy_v2_raw_projection(complete, supplied)
    with pytest.raises(ValueError, match="lower bound"):
        _observation(
            body_complete=False,
            byte_count=None,
            observed_lower_bound=MAX_OBSERVED_BODY_BYTES_LOWER_BOUND + 1,
            persist_raw=False,
        )


def test_postgres_renderer_is_ordered_null_total_and_binds_canonical_shape() -> None:
    sql = render_postgres_contract()
    assert sql.expected_status_case.startswith("CASE WHEN")
    assert sql.expected_rejection_case.index("missing_http_version") < (
        sql.expected_rejection_case.index("invalid_content_length")
    )
    assert sql.expected_rejection_case.index("response_body_incomplete") < (
        sql.expected_rejection_case.index("content_length_mismatch")
    )
    assert sql.expected_rejection_case.index("content_length_mismatch") < (
        sql.expected_rejection_case.index("invalid_content_type")
    )
    assert "IS NOT DISTINCT FROM" in sql.expected_status_case
    assert "invalid_unclassified" in sql.expected_rejection_case
    assert "sha256(convert_to" in sql.approved_header_names_identity_sql
    assert "sha256(convert_to" in sql.normalized_header_facts_identity_sql
    assert "sha256(convert_to" in sql.raw_artifact_identity_sql
    assert "sha256(convert_to" in sql.framing_input_identity_sql
    assert "normalized_content_type_values IS NULL" in sql.v2_facts_absent_predicate
    assert '"raw_header_field_count":' in (sql.normalized_header_facts_serialization_sql)
    assert "raw_header_field_count" in sql.framing_input_serialization_sql
    assert "body_byte_count IS NOT DISTINCT FROM actual_body_byte_count" in (
        sql.legacy_raw_projection_predicate
    )
    assert "body_hash IS NOT DISTINCT FROM raw_body_hash" in (sql.legacy_raw_projection_predicate)
    assert "body_relative_path IS NOT DISTINCT FROM raw_relative_path" in (
        sql.legacy_raw_projection_predicate
    )
    assert str(MAX_OBSERVED_BODY_BYTES_LOWER_BOUND) in (sql.legacy_raw_projection_predicate)
    assert sql.legacy_raw_projection_predicate in sql.canonical_decision_check
    assert sql.fact_free_v2_event_predicate == render_fact_free_v2_event_predicate()
    assert sql.v2_event_metadata_predicate == render_v2_event_metadata_predicate()
    assert "credential_echo IS TRUE" in sql.v2_event_metadata_predicate
    assert "credential_echo IS FALSE" in sql.v2_event_metadata_predicate
    assert "error_code IS NULL" in sql.v2_event_metadata_predicate
    assert "error_code IS NOT DISTINCT FROM 'credential_echo'" in (sql.v2_event_metadata_predicate)
    assert sql.v2_event_metadata_predicate in sql.canonical_decision_check
    assert sql.v2_event_metadata_predicate in sql.fact_free_v2_event_predicate
    for disposition in (
        "transport_unavailable",
        "deadline_exceeded",
        "response_invalid",
        "response_too_large",
        "authentication_failed",
        "provider_rejected",
    ):
        assert disposition in sql.fact_free_v2_event_predicate
    assert "credential_echo IS FALSE" in sql.fact_free_v2_event_predicate
    assert "approved_header_names IS NOT DISTINCT FROM ARRAY[]::varchar[]" in (
        sql.fact_free_v2_event_predicate
    )
    assert "array_to_json(normalized_content_type_values)::text" in (
        sql.normalized_header_facts_serialization_sql
    )
    assert "'UTF8'" in sql.canonical_fact_shape
    assert FRAMING_CONTRACT_IDENTITY in sql.canonical_fact_shape
    assert str(POSTGRES_BIGINT_MAX) in sql.canonical_fact_shape
    assert str(MAX_RAW_RESPONSE_BYTES) in sql.canonical_fact_shape
    assert "normalized_header_names IS NOT DISTINCT FROM ARRAY[]::varchar[]" in (
        sql.canonical_fact_shape
    )
    assert "cardinality(normalized_content_length_values)" in sql.canonical_fact_shape
    assert "framing_status IS NOT DISTINCT FROM" in sql.canonical_decision_check
    assert "accepted_framing_class IS NOT DISTINCT FROM" in sql.canonical_decision_check
    assert "framing_rejection_code IS NOT DISTINCT FROM" in sql.canonical_decision_check
    assert "NULL <>" not in sql.canonical_decision_check


def test_v1_rows_are_not_reinterpreted_as_v2_facts() -> None:
    predicate = render_v1_immutability_predicate()
    assert render_v2_facts_absent_predicate() in predicate
    assert "M3_PROVIDER_ATTEMPT_EVENT_V1" in predicate
    for column in V2_ONLY_LEDGER_COLUMNS:
        assert f"{column} IS NULL" in predicate
    assert "approved_header_names IS NULL" not in predicate
    assert set(V2_PERSISTED_COLUMNS) >= {
        "actual_body_byte_count",
        "raw_evidence_state",
        "raw_body_hash",
        "raw_relative_path",
        "raw_header_field_count",
        "framing_contract_identity",
        "normalized_content_encoding_values",
        "normalized_content_length_values",
        "normalized_content_type_values",
        "normalized_transfer_encoding_values",
        "normalized_x_request_id_values",
    }


def test_rule_table_contains_no_replaceable_callable_authority() -> None:
    for rule in FRAMING_RULES:
        assert not callable(rule.condition)
        assert not callable(rule.example)
