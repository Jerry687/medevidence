"""Disposable PostgreSQL integration for the insert-only provider attempt ledger."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from medevidence.persistence import (
    ProviderAttemptEvent,
    ProviderAttemptLedgerConflict,
    ProviderAttemptLedgerRepository,
    make_provider_attempt_event,
)
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.models import m3_provider_attempt_events
from medevidence.persistence.repositories import (
    _provider_event_payload,
    canonical_provider_attempt_event_id,
)
from medevidence.tools.provider_attempt_framing import (
    PERSISTED_AUTHORITY_FIELDS,
    Observation,
    build_framing_observation,
    fact_free_event_case_projection,
    generated_consumer_mutation_witness,
    generated_contract_cases,
    normalize_approved_headers,
    validate_generated_mutation_case,
)

RUN_ID = "provider-attempt-run:sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)
_WINDOWS_RESERVED_PROVIDER_PATH_NAMES = (
    "AUX",
    "CLOCK$",
    *(f"COM{index}" for index in range(1, 10)),
    "CON",
    *(f"LPT{index}" for index in range(1, 10)),
    "NUL",
    "PRN",
)
_NONCANONICAL_PROVIDER_PATHS = (
    "",
    ".",
    "..",
    "raw//case.bin",
    "C:/outside.bin",
    "C:outside.bin",
    "raw/case.bin:stream",
    "//server/share/case.bin",
    "\\\\server\\share\\case.bin",
    "/absolute/case.bin",
    "../outside.bin",
    "raw/../outside.bin",
    "raw/case.bin.",
    "raw/case.bin ",
    "raw./case.bin",
    "raw /case.bin",
    *(f"raw/{name}" for name in _WINDOWS_RESERVED_PROVIDER_PATH_NAMES),
    *(f"raw/{name.lower()}.json" for name in _WINDOWS_RESERVED_PROVIDER_PATH_NAMES),
)


def _repository() -> ProviderAttemptLedgerRepository:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    command.upgrade(Config("alembic.ini"), "head")
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM medevidence.m3_provider_attempt_events"))
    return ProviderAttemptLedgerRepository._from_engine_for_testing(engine)


def _start(attempt: int = 1):
    return make_provider_attempt_event(
        provider_run_id=RUN_ID,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=attempt,
        event_kind="START",
        configuration_hash=DIGEST,
        request_hash=DIGEST,
        started_at_utc=NOW,
    )


def _terminal(attempt: int = 1, disposition: str = "success"):
    start = _start(attempt)
    return make_provider_attempt_event(
        provider_run_id=RUN_ID,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=attempt,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=DIGEST,
        request_hash=DIGEST,
        started_at_utc=NOW,
        completed_at_utc=NOW,
        http_status=200,
        disposition=disposition,
        error_code=None if disposition == "success" else disposition,
        body_complete=True,
        body_byte_count=2,
        body_hash=DIGEST,
        body_relative_path="case-001-attempt-001-raw.bin",
        observed_body_bytes_lower_bound=2,
        approved_header_names=("content-type",),
    )


def _event_values(event: ProviderAttemptEvent) -> dict[str, object]:
    return {field.name: getattr(event, field.name) for field in fields(event)}


def _v2_start(
    case_ordinal: int = 1,
    attempt_ordinal: int = 1,
    *,
    provider_run_id: str = RUN_ID,
) -> ProviderAttemptEvent:
    return make_provider_attempt_event(
        provider_run_id=provider_run_id,
        case_id=f"M3-008B-CAL-{case_ordinal:03d}",
        case_ordinal=case_ordinal,
        attempt_ordinal=attempt_ordinal,
        event_kind="START",
        configuration_hash=DIGEST,
        request_hash=DIGEST,
        started_at_utc=NOW,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )


def _v2_terminal(
    observation: Observation,
    *,
    case_ordinal: int = 1,
    attempt_ordinal: int = 1,
    provider_run_id: str = RUN_ID,
) -> ProviderAttemptEvent:
    start = _v2_start(
        case_ordinal,
        attempt_ordinal,
        provider_run_id=provider_run_id,
    )
    disposition = observation.disposition
    return make_provider_attempt_event(
        provider_run_id=provider_run_id,
        case_id=f"M3-008B-CAL-{case_ordinal:03d}",
        case_ordinal=case_ordinal,
        attempt_ordinal=attempt_ordinal,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=DIGEST,
        request_hash=DIGEST,
        started_at_utc=NOW,
        completed_at_utc=NOW,
        http_status=observation.http_status,
        disposition=disposition,
        error_code=None if disposition == "success" else disposition,
        credential_echo=disposition == "credential_echo",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=observation,
    )


def _recanonical_event(event: ProviderAttemptEvent, **changes: object) -> ProviderAttemptEvent:
    changed = replace(event, **changes)
    payload = _provider_event_payload(changed)
    return replace(changed, event_id=canonical_provider_attempt_event_id(payload))


def _identity(kind: str, value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return f"{kind}:sha256:{hashlib.sha256(raw).hexdigest()}"


def _rebind_raw_path(event: ProviderAttemptEvent, relative_path: str) -> ProviderAttemptEvent:
    raw_identity = _identity(
        "m3-provider-raw-artifact",
        {
            "body_byte_count": event.actual_body_byte_count,
            "body_hash": event.raw_body_hash,
            "relative_path": relative_path,
        },
    )
    input_identity = _identity(
        "m3-framing-input",
        {
            "actual_body_byte_count": event.actual_body_byte_count,
            "body_complete": event.body_complete,
            "content_encoding_state": event.content_encoding_state,
            "content_length_state": event.content_length_state,
            "content_length_value": event.content_length_value,
            "content_type_state": event.content_type_state,
            "disposition": event.disposition,
            "header_facts_identity": event.normalized_header_facts_identity,
            "http_status": event.http_status,
            "http_version_state": event.http_version_state,
            "observed_http_version": event.observed_http_version,
            "observed_body_bytes_lower_bound": event.observed_body_bytes_lower_bound,
            "raw_artifact_identity": raw_identity,
            "raw_evidence_state": event.raw_evidence_state,
            "raw_header_field_count": event.raw_header_field_count,
            "transfer_encoding_state": event.transfer_encoding_state,
        },
    )
    return _recanonical_event(
        event,
        body_relative_path=relative_path,
        raw_relative_path=relative_path,
        raw_artifact_identity=raw_identity,
        framing_input_identity=input_identity,
    )


def _assert_composite_start_fk(error: BaseException) -> None:
    assert isinstance(error, sa.exc.IntegrityError)
    assert (
        getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        == "fk_m3_provider_attempt_event_start"
    )


def test_a_start_and_terminal_commit_in_exact_order() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        repository.append(_terminal())
        events = repository.list_events(RUN_ID)
        assert [(item.event_kind, item.event_slot) for item in events] == [
            ("START", 0),
            ("TERMINAL", 1),
        ]
    finally:
        repository.close()


def test_b_duplicate_start_is_conflict_and_never_identical_replay() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        with pytest.raises(ProviderAttemptLedgerConflict):
            repository.append(_start())
        assert len(repository.list_events(RUN_ID)) == 1
    finally:
        repository.close()


def test_c_orphan_recovery_is_idempotent() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        first = repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        second = repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        assert len(first) == 1 and second == ()
        assert [item.event_kind for item in repository.list_events(RUN_ID)] == ["START", "RECOVERY"]
    finally:
        repository.close()


def test_d_terminal_prevents_recovery() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        repository.append(_terminal())
        assert repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW) == ()
    finally:
        repository.close()


@pytest.mark.parametrize("attempt", (1, 2, 3))
def test_e_attempt_ordinals_are_distinct(attempt: int) -> None:
    repository = _repository()
    try:
        repository.append(_start(attempt))
        assert repository.list_events(RUN_ID)[0].attempt_ordinal == attempt
    finally:
        repository.close()


def test_f_closed_disposition_rejects_before_insert() -> None:
    with pytest.raises(ValueError):
        make_provider_attempt_event(
            provider_run_id=RUN_ID,
            case_id="M3-008B-CAL-001",
            case_ordinal=1,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            configuration_hash=DIGEST,
            request_hash=DIGEST,
            started_at_utc=NOW,
            completed_at_utc=NOW,
            disposition="caller_defined",
        )


def test_g_order_is_case_attempt_event_slot() -> None:
    repository = _repository()
    try:
        repository.append(_start(2))
        repository.append(_start(1))
        assert [item.attempt_ordinal for item in repository.list_events(RUN_ID)] == [1, 2]
    finally:
        repository.close()


def test_h_same_ordinal_has_at_most_one_start() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        with pytest.raises(ProviderAttemptLedgerConflict):
            repository.append(_start())
        assert sum(item.event_kind == "START" for item in repository.list_events(RUN_ID)) == 1
    finally:
        repository.close()


def test_i_recovery_never_adds_a_second_terminal_slot() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        assert [item.event_slot for item in repository.list_events(RUN_ID)] == [0, 1]
    finally:
        repository.close()


def test_j_catalog_has_no_raw_byte_column() -> None:
    repository = _repository()
    try:
        with repository._engine.connect() as connection:
            count = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='medevidence' "
                    "AND table_name='m3_provider_attempt_events' "
                    "AND data_type IN ('bytea','binary','varbinary')"
                )
            )
        assert count == 0
    finally:
        repository.close()


def test_k_two_independent_sessions_contend_for_one_run_lease() -> None:
    first = _repository()
    second = _repository()
    lease = first.acquire_run_lease(RUN_ID)
    try:
        with pytest.raises(ProviderAttemptLedgerConflict, match="already held"):
            second.acquire_run_lease(RUN_ID)
    finally:
        first.release_run_lease(lease)
        first.close()
        second.close()


def test_l_explicit_unlock_allows_independent_session_reacquire() -> None:
    first = _repository()
    second = _repository()
    first_lease = first.acquire_run_lease(RUN_ID)
    second_lease = None
    try:
        with pytest.raises(ProviderAttemptLedgerConflict, match="already held"):
            second.acquire_run_lease(RUN_ID)
        first.release_run_lease(first_lease)
        first_lease = None
        second_lease = second.acquire_run_lease(RUN_ID)
    finally:
        if first_lease is not None:
            first.release_run_lease(first_lease)
        if second_lease is not None:
            second.release_run_lease(second_lease)
        first.close()
        second.close()


def test_m_session_close_automatically_releases_run_lease() -> None:
    first = _repository()
    second = _repository()
    first_lease = first.acquire_run_lease(RUN_ID)
    second_lease = None
    try:
        first_lease.connection.invalidate()
        first_lease.connection.close()
        second_lease = second.acquire_run_lease(RUN_ID)
    finally:
        if not first_lease.connection.closed:
            first_lease.connection.invalidate()
            first_lease.connection.close()
        if second_lease is not None:
            second.release_run_lease(second_lease)
        first.close()
        second.close()


def test_n_terminal_without_start_rejects_in_repository_and_direct_database() -> None:
    repository = _repository()
    terminal = _terminal()
    try:
        with pytest.raises(
            ProviderAttemptLedgerConflict, match="requires the exact persisted START"
        ):
            repository.append(terminal)
        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            repository._engine.begin() as connection,
        ):
            connection.execute(
                m3_provider_attempt_events.insert().values(**_event_values(terminal))
            )
        _assert_composite_start_fk(direct.value)
        assert repository.list_events(RUN_ID) == ()
    finally:
        repository.close()


@pytest.mark.parametrize(
    "changes",
    (
        {"provider_run_id": "provider-attempt-run:sha256:" + "c" * 64},
        {"case_id": "M3-008B-CAL-002", "case_ordinal": 2},
        {"attempt_ordinal": 2},
    ),
    ids=("run", "case-and-ordinal", "attempt"),
)
def test_o_composite_fk_rejects_run_case_or_attempt_mismatch(
    changes: dict[str, object],
) -> None:
    repository = _repository()
    try:
        repository.append(_start())
        mismatched = _recanonical_event(_terminal(), **changes)
        with pytest.raises(
            ProviderAttemptLedgerConflict,
            match="requires the exact persisted START",
        ):
            repository.append(mismatched)
        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            repository._engine.begin() as connection,
        ):
            connection.execute(
                m3_provider_attempt_events.insert().values(**_event_values(mismatched))
            )
        _assert_composite_start_fk(direct.value)
        assert [item.event_kind for item in repository.list_events(RUN_ID)] == ["START"]
    finally:
        repository.close()


@pytest.mark.parametrize(
    "changes",
    (
        {"configuration_hash": "sha256:" + "c" * 64},
        {"request_hash": "sha256:" + "d" * 64},
    ),
    ids=("configuration", "request"),
)
def test_p_composite_fk_rejects_configuration_or_request_mismatch(
    changes: dict[str, object],
) -> None:
    repository = _repository()
    try:
        repository.append(_start())
        mismatched = _recanonical_event(_terminal(), **changes)
        with pytest.raises(
            ProviderAttemptLedgerConflict,
            match="requires the exact persisted START",
        ):
            repository.append(mismatched)
        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            repository._engine.begin() as connection,
        ):
            connection.execute(
                m3_provider_attempt_events.insert().values(**_event_values(mismatched))
            )
        _assert_composite_start_fk(direct.value)
        assert [item.event_kind for item in repository.list_events(RUN_ID)] == ["START"]
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("start_schema", "closure_schema"),
    (
        ("M3_PROVIDER_ATTEMPT_EVENT_V1", "M3_PROVIDER_ATTEMPT_EVENT_V2"),
        ("M3_PROVIDER_ATTEMPT_EVENT_V2", "M3_PROVIDER_ATTEMPT_EVENT_V1"),
    ),
    ids=("v2-terminal-to-v1-start", "v1-terminal-to-v2-start"),
)
def test_p2_cross_schema_closure_rejects_before_repository_insert_and_in_database(
    start_schema: str,
    closure_schema: str,
) -> None:
    repository = _repository()
    accepted = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_class == "http_2_data"
    )
    persisted_start = _start() if start_schema.endswith("_V1") else _v2_start()
    independent_closure = _terminal() if closure_schema.endswith("_V1") else _v2_terminal(accepted)
    closure = _recanonical_event(
        independent_closure,
        start_event_id=persisted_start.event_id,
    )
    assert closure.schema_version == closure_schema
    assert persisted_start.schema_version == start_schema
    assert closure.event_id == canonical_provider_attempt_event_id(_provider_event_payload(closure))
    try:
        repository.append(persisted_start)
        with pytest.raises(
            ProviderAttemptLedgerConflict,
            match="requires the exact persisted START",
        ):
            repository.append(closure)
        assert repository.list_events(RUN_ID) == (persisted_start,)

        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(closure)))
        _assert_composite_start_fk(direct.value)
        assert repository.list_events(RUN_ID) == (persisted_start,)
    finally:
        repository.close()


def test_q_terminal_after_recovery_conflicts_on_shared_closure_slot() -> None:
    repository = _repository()
    try:
        repository.append(_start())
        recovered = repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        assert len(recovered) == 1
        with pytest.raises(ProviderAttemptLedgerConflict, match="slot already exists"):
            repository.append(_terminal())
        closures = [item for item in repository.list_events(RUN_ID) if item.event_kind != "START"]
        assert [(item.event_kind, item.event_slot) for item in closures] == [("RECOVERY", 1)]
    finally:
        repository.close()


def test_r_concurrent_terminal_and_recovery_create_exactly_one_closure() -> None:
    terminal_repository = _repository()
    recovery_repository = _repository()
    terminal_repository.append(_start())
    barrier = threading.Barrier(2)

    def append_terminal() -> str:
        barrier.wait()
        try:
            terminal_repository.append(_terminal())
        except ProviderAttemptLedgerConflict:
            return "conflict"
        return "terminal"

    def reconcile_recovery() -> str:
        barrier.wait()
        recovered = recovery_repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        return "recovery" if recovered else "already-closed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            terminal_future = executor.submit(append_terminal)
            recovery_future = executor.submit(reconcile_recovery)
            outcomes = {terminal_future.result(), recovery_future.result()}
        closures = [
            item
            for item in terminal_repository.list_events(RUN_ID)
            if item.event_kind in {"TERMINAL", "RECOVERY"}
        ]
        assert len(closures) == 1
        assert closures[0].event_slot == 1
        assert outcomes in (
            {"terminal", "already-closed"},
            {"conflict", "recovery"},
        )
    finally:
        terminal_repository.close()
        recovery_repository.close()


@pytest.mark.parametrize(
    "first_schema",
    ("M3_PROVIDER_ATTEMPT_EVENT_V1", "M3_PROVIDER_ATTEMPT_EVENT_V2"),
    ids=("v1-first", "v2-first"),
)
def test_r2_v1_and_v2_starts_share_one_schema_independent_slot_sequentially(
    first_schema: str,
) -> None:
    repository = _repository()
    first = _start() if first_schema.endswith("_V1") else _v2_start()
    second = _v2_start() if first_schema.endswith("_V1") else _start()
    try:
        repository.append(first)
        with pytest.raises(ProviderAttemptLedgerConflict, match="slot already exists"):
            repository.append(second)
        assert repository.list_events(RUN_ID) == (first,)

        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(second)))
        assert (
            getattr(getattr(direct.value.orig, "diag", None), "constraint_name", None)
            == "uq_m3_provider_attempt_event_slot"
        )
        assert repository.list_events(RUN_ID) == (first,)
    finally:
        repository.close()


def test_r3_v1_and_v2_starts_share_one_schema_independent_slot_concurrently() -> None:
    v1_repository = _repository()
    v2_repository = _repository()
    v1_start = _start()
    v2_start = _v2_start()
    barrier = threading.Barrier(2)

    def append_start(
        repository: ProviderAttemptLedgerRepository,
        event: ProviderAttemptEvent,
    ) -> tuple[str, ProviderAttemptEvent]:
        barrier.wait()
        try:
            repository.append(event)
        except ProviderAttemptLedgerConflict:
            return "conflict", event
        return "inserted", event

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            v1_future = executor.submit(append_start, v1_repository, v1_start)
            v2_future = executor.submit(append_start, v2_repository, v2_start)
            results = (v1_future.result(), v2_future.result())

        assert [status for status, _event in results].count("inserted") == 1
        assert [status for status, _event in results].count("conflict") == 1
        winner = next(event for status, event in results if status == "inserted")
        loser = next(event for status, event in results if status == "conflict")
        assert v1_repository.list_events(RUN_ID) == (winner,)

        with (
            pytest.raises(sa.exc.IntegrityError) as direct,
            v1_repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(loser)))
        assert (
            getattr(getattr(direct.value.orig, "diag", None), "constraint_name", None)
            == "uq_m3_provider_attempt_event_slot"
        )
        assert v1_repository.list_events(RUN_ID) == (winner,)
    finally:
        v1_repository.close()
        v2_repository.close()


def test_r4_concurrent_v2_terminal_and_recovery_create_one_schema_bound_closure() -> None:
    terminal_repository = _repository()
    recovery_repository = _repository()
    accepted = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_class == "http_2_data"
    )
    start = _v2_start()
    terminal = _v2_terminal(accepted)
    terminal_repository.append(start)
    barrier = threading.Barrier(2)

    def append_terminal() -> str:
        barrier.wait()
        try:
            terminal_repository.append(terminal)
        except ProviderAttemptLedgerConflict:
            return "conflict"
        return "terminal"

    def reconcile_recovery() -> str:
        barrier.wait()
        recovered = recovery_repository.reconcile_orphan_starts(RUN_ID, recovered_at_utc=NOW)
        return "recovery" if recovered else "already-closed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            terminal_future = executor.submit(append_terminal)
            recovery_future = executor.submit(reconcile_recovery)
            outcomes = {terminal_future.result(), recovery_future.result()}
        events = terminal_repository.list_events(RUN_ID)
        assert events[0] == start
        closures = [event for event in events if event.event_kind in {"TERMINAL", "RECOVERY"}]
        assert len(closures) == 1
        closure = closures[0]
        assert closure.event_slot == 1
        assert closure.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2"
        assert closure.start_event_id == start.event_id
        assert closure.configuration_hash == start.configuration_hash == DIGEST
        assert closure.request_hash == start.request_hash == DIGEST
        assert outcomes in (
            {"terminal", "already-closed"},
            {"conflict", "recovery"},
        )
    finally:
        terminal_repository.close()
        recovery_repository.close()


def _assert_framing_constraint(error: sa.exc.IntegrityError) -> None:
    assert (
        getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        == "ck_m3_provider_attempt_events_framing_v2"
    )


def _matrix_slot(index: int) -> tuple[int, int]:
    return index // 3 + 1, index % 3 + 1


def _matrix_coordinates(index: int) -> tuple[str, int, int]:
    """Allocate an unbounded generated inventory across closed 36x3 runs."""

    run_ordinal, slot = divmod(index, 36 * 3)
    case_ordinal, attempt_ordinal = _matrix_slot(slot)
    run_id = f"provider-attempt-run:sha256:{run_ordinal + 1:064x}"
    return run_id, case_ordinal, attempt_ordinal


def test_s_every_generated_contract_case_is_admitted_by_python_and_postgres() -> None:
    repository = _repository()
    cases = generated_contract_cases()
    assert len(cases) <= 36
    try:
        for case_ordinal, case in enumerate(cases, start=1):
            repository.append(_v2_start(case_ordinal))
            repository.append(_v2_terminal(case.observation, case_ordinal=case_ordinal))
        events = repository.list_events(RUN_ID)
        assert len(events) == len(cases) * 2
        assert [item.case_ordinal for item in events[::2]] == list(range(1, len(cases) + 1))
        for case, event in zip(cases, events[1::2], strict=True):
            assert (
                event.framing_status,
                event.accepted_framing_class,
                event.framing_rejection_code,
            ) == (
                case.expected_status.value,
                case.expected_class,
                case.expected_code,
            )
            if event.disposition in {"credential_echo", "evidence_persistence_failure"}:
                assert event.framing_status == "unavailable_not_classified"
                assert event.normalized_header_names == ()
                assert event.normalized_header_facts_identity is None
                assert event.body_complete is None
                assert event.actual_body_byte_count is None
                assert event.raw_evidence_state is None
                assert event.raw_artifact_identity is None
    finally:
        repository.close()


def test_s1_v2_validation_internal_failure_round_trips_safe_raw_framing() -> None:
    repository = _repository()
    start = _v2_start()
    observation = build_framing_observation(
        disposition="validation_internal_failure",
        http_status=200,
        http_version="HTTP/2",
        headers=normalize_approved_headers(
            (("content-type", "application/json"),),
            raw_header_field_count=1,
        ),
        raw_header_field_count=1,
        body_complete=True,
        actual_body_byte_count=2,
        raw_body_hash=DIGEST,
        raw_relative_path="raw/validation-internal-failure.json",
    )
    terminal = _v2_terminal(observation)
    try:
        repository.append(start)
        repository.append(terminal)
        stored = repository.list_events(RUN_ID)
        assert stored == (start, terminal)
        assert stored[1].disposition == "validation_internal_failure"
        assert stored[1].body_hash == DIGEST
        assert stored[1].body_relative_path == "raw/validation-internal-failure.json"
        assert stored[1].framing_status == "accepted"
        assert stored[1].accepted_framing_class == "http_2_data"
        assert stored[1].framing_rejection_code is None
    finally:
        repository.close()


def test_s2_every_generated_precedence_variant_is_admitted_by_postgres() -> None:
    repository = _repository()
    variants = [
        variant for case in generated_contract_cases() for variant in case.precedence_variants
    ]
    assert len(variants) >= 50
    assert len(variants) <= 108
    try:
        for index, variant in enumerate(variants):
            case_ordinal, attempt_ordinal = _matrix_slot(index)
            repository.append(_v2_start(case_ordinal, attempt_ordinal))
            event = _v2_terminal(
                variant.observation,
                case_ordinal=case_ordinal,
                attempt_ordinal=attempt_ordinal,
            )
            repository.append(event)
            assert (
                event.framing_status,
                event.accepted_framing_class,
                event.framing_rejection_code,
            ) == (
                variant.expected_status.value,
                variant.expected_class,
                variant.expected_code,
            )
    finally:
        repository.close()


def test_s3_every_generated_noncanonical_variant_is_rejected_by_postgres() -> None:
    repository = _repository()
    cases = generated_contract_cases()
    pairs = [
        (case, variant)
        for case in cases
        for variant in case.noncanonical_variants
        if "postgres" in variant.consumers
    ]
    declared_postgres_targets = sum(
        target.consumer == "postgres"
        for case in cases
        for variant in case.noncanonical_variants
        for target in variant.consumer_targets
    )
    assert pairs
    assert {
        variant.target_authority_field
        for _case, variant in pairs
        if variant.case_id.startswith("primitive:")
    } == set(PERSISTED_AUTHORITY_FIELDS)
    assert len(pairs) == declared_postgres_targets
    assert len({variant.case_id for _case, variant in pairs}) == len(pairs)
    declared_case_ids = tuple(variant.case_id for _case, variant in pairs)
    executed_case_ids: list[str] = []
    used_run_ids: set[str] = set()
    try:
        for index, (case, variant) in enumerate(pairs):
            observation = case.observation
            validate_generated_mutation_case(variant)
            assert (
                variant.expected_first_match_rule,
                variant.expected_status,
                variant.expected_class,
                variant.expected_code,
            ) == (
                case.rule_key,
                case.expected_status,
                case.expected_class,
                case.expected_code,
            )
            mutation_fields = tuple(mutation.field for mutation in variant.mutations)
            postgres_target = next(
                target for target in variant.consumer_targets if target.consumer == "postgres"
            )
            assert postgres_target.authority_fields == mutation_fields
            assert postgres_target.direct_target_paths == tuple(
                f"m3_provider_attempt_events.{field}" for field in mutation_fields
            )
            run_id, case_ordinal, attempt_ordinal = _matrix_coordinates(index)
            used_run_ids.add(run_id)
            repository.append(
                _v2_start(
                    case_ordinal,
                    attempt_ordinal,
                    provider_run_id=run_id,
                )
            )
            event = _v2_terminal(
                observation,
                case_ordinal=case_ordinal,
                attempt_ordinal=attempt_ordinal,
                provider_run_id=run_id,
            )
            event_values = _event_values(event)
            consumer_mutations = generated_consumer_mutation_witness(
                variant,
                "postgres",
                event_values,
            )
            assert tuple(item.field for item in consumer_mutations) == mutation_fields
            assert tuple(item.direct_target_path for item in consumer_mutations) == (
                postgres_target.direct_target_paths
            )
            assert all(item.case_id == variant.case_id for item in consumer_mutations)
            assert all(item.consumer == "postgres" for item in consumer_mutations)
            assert all(
                item.target_authority_field == variant.target_authority_field
                for item in consumer_mutations
            )
            invalid_values = dict(event_values)
            for mutation in consumer_mutations:
                assert mutation.field in event_values
                assert mutation.field in m3_provider_attempt_events.c
                assert type(event_values[mutation.field]) is type(mutation.canonical_value)
                assert event_values[mutation.field] == mutation.canonical_value
                if mutation.operation == "remove":
                    del invalid_values[mutation.field]
                    assert mutation.field not in invalid_values
                else:
                    invalid_values[mutation.field] = mutation.mutated_value
                    assert invalid_values[mutation.field] is mutation.mutated_value
                    assert not (
                        type(mutation.mutated_value) is type(mutation.canonical_value)
                        and mutation.mutated_value == mutation.canonical_value
                    )
            with (
                pytest.raises(sa.exc.DBAPIError) as failure,
                repository._engine.begin() as connection,
            ):
                connection.execute(m3_provider_attempt_events.insert().values(**invalid_values))
            constraint_name = getattr(
                getattr(failure.value.orig, "diag", None),
                "constraint_name",
                None,
            )
            if constraint_name is None:
                assert getattr(failure.value.orig, "sqlstate", None) in {
                    "22001",  # exact column width rejects an overlong governed string
                    "23502",  # an exact NOT NULL column rejects the generated null
                }, variant.case_id
            elif "repository" in variant.consumers:
                assert constraint_name in {
                    "ck_m3_provider_attempt_events_framing_v2",
                    "ck_m3_provider_attempt_events_closure_binding",
                }, (variant.case_id, constraint_name)
            else:
                assert constraint_name in {
                    "ck_m3_provider_attempt_events_framing_v2",
                    "ck_m3_provider_attempt_events_closure_binding",
                }
            executed_case_ids.append(variant.case_id)
        assert tuple(executed_case_ids) == declared_case_ids
        assert sum(len(repository.list_events(run_id)) for run_id in used_run_ids) == len(pairs)
    finally:
        repository.close()


def _fact_free_event(
    *,
    event_kind: str,
    disposition: str,
    case_ordinal: int,
    attempt_ordinal: int,
) -> tuple[ProviderAttemptEvent | None, ProviderAttemptEvent]:
    if event_kind == "START":
        return None, _v2_start(case_ordinal, attempt_ordinal)
    start = _v2_start(case_ordinal, attempt_ordinal)
    event = make_provider_attempt_event(
        provider_run_id=RUN_ID,
        case_id=f"M3-008B-CAL-{case_ordinal:03d}",
        case_ordinal=case_ordinal,
        attempt_ordinal=attempt_ordinal,
        event_kind=event_kind,
        start_event=start,
        configuration_hash=DIGEST,
        request_hash=DIGEST,
        started_at_utc=NOW,
        completed_at_utc=NOW,
        disposition=disposition,
        error_code=None if event_kind == "START" else disposition,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    return start, event


def test_s4_every_generated_fact_free_case_matches_python_and_postgres() -> None:
    repository = _repository()
    cases = [event for case in generated_contract_cases() for event in case.fact_free_event_cases]
    assert cases
    try:
        for index, case in enumerate(cases):
            case_ordinal, attempt_ordinal = _matrix_slot(index)
            projection = fact_free_event_case_projection(case)
            if case.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
                event = make_provider_attempt_event(
                    provider_run_id=RUN_ID,
                    case_id=f"M3-008B-CAL-{case_ordinal:03d}",
                    case_ordinal=case_ordinal,
                    attempt_ordinal=attempt_ordinal,
                    event_kind="START",
                    configuration_hash=DIGEST,
                    request_hash=DIGEST,
                    started_at_utc=NOW,
                )
                repository.append(event)
                assert case.expected_match
                continue
            start, canonical = _fact_free_event(
                event_kind=case.event_kind,
                disposition=case.disposition,
                case_ordinal=case_ordinal,
                attempt_ordinal=attempt_ordinal,
            )
            if start is not None:
                repository.append(start)
            if case.expected_match:
                repository.append(canonical)
                continue
            changes = {mutation.field: projection[mutation.field] for mutation in case.mutations}
            invalid = _recanonical_event(canonical, **changes)
            with (
                pytest.raises(sa.exc.IntegrityError) as failure,
                repository._engine.begin() as connection,
            ):
                connection.execute(
                    m3_provider_attempt_events.insert().values(**_event_values(invalid))
                )
            _assert_framing_constraint(failure.value)
    finally:
        repository.close()


def test_s5_fact_free_legacy_claim_smuggling_is_rejected_by_postgres() -> None:
    repository = _repository()
    mutations: tuple[dict[str, object], ...] = (
        {"approved_header_names": ("content-type",)},
        {"credential_echo": True},
        {"body_complete": False},
        {"body_hash": DIGEST},
        {"observed_body_bytes_lower_bound": 0},
    )
    try:
        for index, changes in enumerate(mutations):
            case_ordinal, attempt_ordinal = _matrix_slot(index)
            invalid = _recanonical_event(
                _v2_start(case_ordinal, attempt_ordinal),
                **changes,
            )
            with (
                pytest.raises(sa.exc.IntegrityError) as failure,
                repository._engine.begin() as connection,
            ):
                connection.execute(
                    m3_provider_attempt_events.insert().values(**_event_values(invalid))
                )
            _assert_framing_constraint(failure.value)
        assert repository.list_events(RUN_ID) == ()
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("framing_status", "rejected"),
        ("framing_input_identity", "m3-framing-input:sha256:" + "f" * 64),
        (
            "normalized_header_facts_identity",
            "m3-normalized-header-facts:sha256:" + "f" * 64,
        ),
        ("raw_artifact_identity", "m3-provider-raw-artifact:sha256:" + "f" * 64),
        (
            "approved_header_names_identity",
            "m3-approved-header-names:sha256:" + "f" * 64,
        ),
        ("content_type_state", None),
    ),
)
def test_t_direct_identity_decision_and_null_mutations_fail_postgres(
    field: str,
    value: object,
) -> None:
    repository = _repository()
    accepted = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_class == "http_2_data"
    )
    try:
        start = _v2_start()
        repository.append(start)
        terminal = _recanonical_event(_v2_terminal(accepted), **{field: value})
        with (
            pytest.raises(sa.exc.IntegrityError) as failure,
            repository._engine.begin() as connection,
        ):
            connection.execute(
                m3_provider_attempt_events.insert().values(**_event_values(terminal))
            )
        _assert_framing_constraint(failure.value)
    finally:
        repository.close()


@pytest.mark.parametrize(
    "relative_path",
    _NONCANONICAL_PROVIDER_PATHS,
)
@pytest.mark.parametrize("schema_version", ("v1", "v2"))
def test_t1_direct_noncanonical_raw_paths_fail_exact_postgres_constraint(
    relative_path: str,
    schema_version: str,
) -> None:
    repository = _repository()
    accepted = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_class == "http_2_data"
    )
    try:
        if schema_version == "v1":
            repository.append(_start())
            invalid = _recanonical_event(_terminal(), body_relative_path=relative_path)
        else:
            repository.append(_v2_start())
            invalid = _rebind_raw_path(_v2_terminal(accepted), relative_path)
        with (
            pytest.raises(sa.exc.IntegrityError) as failure,
            repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(invalid)))
        if schema_version == "v1":
            constraint_name = getattr(
                getattr(failure.value.orig, "diag", None), "constraint_name", None
            )
            assert constraint_name in {
                "ck_m3_provider_attempt_events_headers",
                "ck_m3_provider_attempt_events_v1_immutable",
            }
            if ":" in relative_path:
                assert constraint_name == "ck_m3_provider_attempt_events_v1_immutable"
        else:
            _assert_framing_constraint(failure.value)
    finally:
        repository.close()


def test_u_direct_accepted_incomplete_rawless_hybrid_fails_postgres() -> None:
    repository = _repository()
    accepted = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_class == "http_1_1_chunked"
    )
    try:
        repository.append(_v2_start())
        invalid = _recanonical_event(
            _v2_terminal(accepted),
            disposition="response_invalid",
            error_code="response_invalid",
            body_complete=False,
            body_byte_count=None,
            body_hash=None,
            body_relative_path=None,
            observed_body_bytes_lower_bound=None,
            actual_body_byte_count=None,
            raw_evidence_state="missing",
            raw_body_hash=None,
            raw_relative_path=None,
            raw_artifact_identity=None,
        )
        with (
            pytest.raises(sa.exc.IntegrityError) as failure,
            repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(invalid)))
        _assert_framing_constraint(failure.value)
    finally:
        repository.close()


def test_v_content_length_mismatch_is_impossible_without_complete_body() -> None:
    repository = _repository()
    mismatch = next(
        case.observation
        for case in generated_contract_cases()
        if case.expected_code == "content_length_mismatch"
    )
    try:
        repository.append(_v2_start())
        invalid = _recanonical_event(
            _v2_terminal(mismatch),
            body_complete=False,
            body_byte_count=None,
            body_hash=None,
            body_relative_path=None,
            observed_body_bytes_lower_bound=None,
            actual_body_byte_count=None,
            raw_evidence_state="missing",
            raw_body_hash=None,
            raw_relative_path=None,
            raw_artifact_identity=None,
        )
        with (
            pytest.raises(sa.exc.IntegrityError) as failure,
            repository._engine.begin() as connection,
        ):
            connection.execute(m3_provider_attempt_events.insert().values(**_event_values(invalid)))
        _assert_framing_constraint(failure.value)
    finally:
        repository.close()


def test_w_missing_version_plus_invalid_content_length_uses_first_rule_in_postgres() -> None:
    repository = _repository()
    observation = build_framing_observation(
        disposition="response_invalid",
        http_status=200,
        http_version=None,
        headers=normalize_approved_headers(
            (("content-type", "application/json"), ("content-length", "02")),
            raw_header_field_count=2,
        ),
        raw_header_field_count=2,
        body_complete=True,
        actual_body_byte_count=2,
        raw_body_hash=DIGEST,
        raw_relative_path="raw/precedence.json",
    )
    try:
        repository.append(_v2_start())
        canonical = _v2_terminal(observation)
        assert canonical.framing_rejection_code == "missing_http_version"
        repository.append(canonical)
        assert repository.list_events(RUN_ID)[1].framing_rejection_code == "missing_http_version"
    finally:
        repository.close()


def test_x_v1_rows_are_byte_semantically_preserved_and_gain_only_null_v2_columns() -> None:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    cleanup_engine = sa.create_engine(url)
    try:
        with cleanup_engine.begin() as connection:
            connection.execute(m3_provider_attempt_events.delete())
    finally:
        cleanup_engine.dispose()
    command.downgrade(config, "m3providerattempt001")
    engine = sa.create_engine(url)
    start = _start()
    terminal = _terminal()
    try:
        old = sa.Table(
            "m3_provider_attempt_events",
            sa.MetaData(),
            schema="medevidence",
            autoload_with=engine,
        )
        original_columns = tuple(column.name for column in old.columns)
        insert_columns = tuple(name for name in original_columns if name != "persisted_at_utc")
        start_values = _event_values(start)
        terminal_values = _event_values(terminal)
        with engine.begin() as connection:
            connection.execute(old.delete())
            connection.execute(
                old.insert().values(**{name: start_values[name] for name in insert_columns})
            )
            connection.execute(
                old.insert().values(**{name: terminal_values[name] for name in insert_columns})
            )
            before = tuple(
                dict(row)
                for row in connection.execute(sa.select(old).order_by(old.c.event_slot)).mappings()
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            after = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(m3_provider_attempt_events).order_by(
                        m3_provider_attempt_events.c.event_slot
                    )
                ).mappings()
            )
        assert tuple({name: row[name] for name in original_columns} for row in after) == before
        v2_columns = set(m3_provider_attempt_events.c.keys()) - set(original_columns)
        assert v2_columns
        assert all(row[name] is None for row in after for name in v2_columns)
    finally:
        engine.dispose()
