"""Disposable PostgreSQL integration for the insert-only provider attempt ledger."""

from __future__ import annotations

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
    ProviderAttemptLedgerError,
    ProviderAttemptLedgerRepository,
    make_provider_attempt_event,
)
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.models import m3_provider_attempt_events
from medevidence.persistence.repositories import canonical_provider_attempt_event_id

RUN_ID = "provider-attempt-run:sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


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


def _recanonical_event(event: ProviderAttemptEvent, **changes: object) -> ProviderAttemptEvent:
    changed = replace(event, **changes)
    payload = {
        field.name: getattr(changed, field.name)
        for field in fields(changed)
        if field.name != "event_id"
    }
    return replace(changed, event_id=canonical_provider_attempt_event_id(payload))


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
        with pytest.raises(ProviderAttemptLedgerError, match="insert failed") as failure:
            repository.append(mismatched)
        _assert_composite_start_fk(failure.value.__cause__)
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
        with pytest.raises(ProviderAttemptLedgerError, match="insert failed") as failure:
            repository.append(mismatched)
        _assert_composite_start_fk(failure.value.__cause__)
        assert [item.event_kind for item in repository.list_events(RUN_ID)] == ["START"]
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
