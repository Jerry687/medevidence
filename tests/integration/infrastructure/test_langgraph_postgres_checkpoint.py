"""Disposable PostgreSQL evidence for the official LangGraph checkpointer."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from tests.unit.orchestration.test_workflow import Harness, _initial

from medevidence.infrastructure.langgraph_checkpoint import (
    LANGGRAPH_CHECKPOINT_SCHEMA,
    OFFICIAL_CHECKPOINT_TABLES,
    _psycopg_connection_uri,
    postgres_checkpoint_saver,
    setup_postgres_checkpointing,
)
from medevidence.orchestration import WorkflowDisposition, WorkflowNode
from medevidence.orchestration.langgraph_runtime import (
    CHECKPOINT_NAMESPACE,
    LangGraphOrchestrationRuntime,
    _FixedNamespaceSaver,
)
from medevidence.persistence.config import DATABASE_URL_ENV, PersistenceSettings


class _PrimitiveState(TypedDict):
    count: int
    marker: str


def _increment(state: _PrimitiveState) -> _PrimitiveState:
    return {"count": state["count"] + 1, "marker": state["marker"]}


def _settings() -> PersistenceSettings:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    return PersistenceSettings(value)


def _connect(settings: PersistenceSettings) -> Connection[DictRow]:
    return Connection.connect(
        _psycopg_connection_uri(settings),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )


def _schema_exists(connection: Connection[DictRow]) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=%s)",
            (LANGGRAPH_CHECKPOINT_SCHEMA,),
        )
        row = cursor.fetchone()
    assert row is not None
    return bool(row["exists"])


def _application_snapshot(
    connection: Connection[DictRow],
) -> tuple[tuple[tuple[str, str, str], ...], tuple[tuple[str, str, int], ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT n.nspname AS schema_name, c.relname, c.relkind "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('medevidence','public') "
            "AND c.relkind IN ('r','p','v','m','S') "
            "ORDER BY n.nspname, c.relname, c.relkind"
        )
        relations = tuple(
            (row["schema_name"], row["relname"], row["relkind"]) for row in cursor.fetchall()
        )
        base_tables = tuple(
            (schema_name, relation_name)
            for schema_name, relation_name, relation_kind in relations
            if relation_kind in {"r", "p"}
        )
        counts: list[tuple[str, str, int]] = []
        for schema_name, table_name in base_tables:
            cursor.execute(
                sql.SQL("SELECT count(*) AS row_count FROM {}.{}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
            )
            row = cursor.fetchone()
            assert row is not None
            counts.append((schema_name, table_name, int(row["row_count"])))
    return relations, tuple(counts)


def _checkpoint_tables(connection: Connection[DictRow], schema_name: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=%s AND table_type='BASE TABLE'",
            (schema_name,),
        )
        return {row["table_name"] for row in cursor.fetchall()}


def _cleanup(
    settings: PersistenceSettings,
    *,
    schema_was_test_created: bool,
    thread_ids: tuple[str, ...],
) -> None:
    with _connect(settings) as connection, connection.cursor() as cursor:
        if schema_was_test_created:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(LANGGRAPH_CHECKPOINT_SCHEMA)
                )
            )
            return
        cursor.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(LANGGRAPH_CHECKPOINT_SCHEMA)
            )
        )
        for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            cursor.execute(
                sql.SQL("DELETE FROM {} WHERE thread_id = ANY(%s)").format(
                    sql.Identifier(table_name)
                ),
                (list(thread_ids),),
            )


@pytest.fixture
def checkpoint_database() -> Iterator[tuple[PersistenceSettings, str, str, set[str]]]:
    settings = _settings()
    thread_id = f"run:checkpoint-integration:{uuid4()}"
    other_thread_id = f"run:checkpoint-integration:{uuid4()}"
    cleanup_thread_ids = {thread_id, other_thread_id}
    with _connect(settings) as connection:
        schema_was_test_created = not _schema_exists(connection)
    try:
        yield settings, thread_id, other_thread_id, cleanup_thread_ids
    finally:
        with _connect(settings) as connection:
            schema_exists = _schema_exists(connection)
        if schema_exists:
            _cleanup(
                settings,
                schema_was_test_created=schema_was_test_created,
                thread_ids=tuple(sorted(cleanup_thread_ids)),
            )


def test_official_checkpoint_schema_setup_and_primitive_resume(
    checkpoint_database: tuple[PersistenceSettings, str, str, set[str]],
) -> None:
    settings, thread_id, other_thread_id, _ = checkpoint_database
    with _connect(settings) as connection:
        application_before = _application_snapshot(connection)

    setup_postgres_checkpointing(settings)
    setup_postgres_checkpointing(settings)

    with _connect(settings) as connection:
        assert _checkpoint_tables(connection, LANGGRAPH_CHECKPOINT_SCHEMA) == (
            OFFICIAL_CHECKPOINT_TABLES
        )
        assert _checkpoint_tables(connection, "public").isdisjoint(OFFICIAL_CHECKPOINT_TABLES)
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT v FROM {}.checkpoint_migrations ORDER BY v").format(
                    sql.Identifier(LANGGRAPH_CHECKPOINT_SCHEMA)
                )
            )
            migration_versions = tuple(row["v"] for row in cursor.fetchall())
        assert migration_versions == tuple(range(len(PostgresSaver.MIGRATIONS)))

    builder = StateGraph(_PrimitiveState)
    builder.add_node("increment", _increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    root_config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }
    stored_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }
    empty_namespace_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    other_stored_config = {
        "configurable": {
            "thread_id": other_thread_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }

    with postgres_checkpoint_saver(settings) as saver:
        with saver.conn.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            statement_timeout = cursor.fetchone()
            cursor.execute("SHOW lock_timeout")
            lock_timeout = cursor.fetchone()
        assert statement_timeout is not None
        assert statement_timeout["statement_timeout"] == "30s"
        assert lock_timeout is not None
        assert lock_timeout["lock_timeout"] == "5s"
        graph = builder.compile(checkpointer=_FixedNamespaceSaver(saver))
        assert graph.invoke({"count": 0, "marker": "primitive-only"}, root_config) == {
            "count": 1,
            "marker": "primitive-only",
        }
        assert saver.get_tuple(stored_config) is not None
        assert saver.get_tuple(empty_namespace_config) is None

    with postgres_checkpoint_saver(settings) as saver:
        reopened = builder.compile(checkpointer=_FixedNamespaceSaver(saver))
        assert reopened.invoke(None, root_config) == {
            "count": 1,
            "marker": "primitive-only",
        }
        assert saver.get_tuple(stored_config) is not None
        assert saver.get_tuple(empty_namespace_config) is None
        assert saver.get_tuple(other_stored_config) is None

    with _connect(settings) as connection:
        assert _application_snapshot(connection) == application_before


def test_real_m3_runtime_survives_postgres_reopen_and_exports_exactly_once(
    checkpoint_database: tuple[PersistenceSettings, str, str, set[str]],
) -> None:
    settings, _, other_thread_id, cleanup_thread_ids = checkpoint_database
    initial = _initial()
    cleanup_thread_ids.add(initial.run_id)
    harness = Harness()
    stored_config = {
        "configurable": {
            "thread_id": initial.run_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }
    empty_namespace_config = {
        "configurable": {
            "thread_id": initial.run_id,
            "checkpoint_ns": "",
        }
    }
    other_stored_config = {
        "configurable": {
            "thread_id": other_thread_id,
            "checkpoint_ns": CHECKPOINT_NAMESPACE,
        }
    }
    with _connect(settings) as connection:
        application_before = _application_snapshot(connection)

    setup_postgres_checkpointing(settings)
    with postgres_checkpoint_saver(settings) as saver:
        runtime = LangGraphOrchestrationRuntime(
            workflow=harness.workflow,
            checkpointer=saver,
        )
        interrupted = runtime.start(initial)
        stored = saver.get_tuple(stored_config)

        assert interrupted.terminal is False
        assert interrupted.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL
        assert interrupted.state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL
        assert stored is not None
        assert stored.config["configurable"]["thread_id"] == initial.run_id
        assert stored.config["configurable"]["checkpoint_ns"] == CHECKPOINT_NAMESPACE
        assert saver.get_tuple(empty_namespace_config) is None
        assert saver.get_tuple(other_stored_config) is None
        assert harness.approval.calls == 0
        assert harness.export.calls == 0

    events_before_reopen = tuple(harness.events)
    with postgres_checkpoint_saver(settings) as saver:
        reopened = LangGraphOrchestrationRuntime(
            workflow=harness.workflow,
            checkpointer=saver,
        )
        inspected_interrupted = reopened.inspect(initial.run_id)
        assert inspected_interrupted == interrupted
        assert tuple(harness.events) == events_before_reopen

        completed = reopened.resume(initial.run_id)
        events_after_export = tuple(harness.events)
        terminal_binding_reads = (
            "pending_draft:load",
            "validation_receipt:load",
        )
        inspected_completed = reopened.inspect(initial.run_id)
        events_after_terminal_inspect = tuple(harness.events)
        assert events_after_terminal_inspect == events_after_export + terminal_binding_reads

        repeated = reopened.resume(initial.run_id)

        assert completed == inspected_completed == repeated
        assert completed.terminal is True
        assert completed.state.disposition is WorkflowDisposition.EXPORTED
        assert tuple(harness.events) == (events_after_terminal_inspect + terminal_binding_reads)
        assert saver.get_tuple(stored_config) is not None
        assert saver.get_tuple(empty_namespace_config) is None
        assert saver.get_tuple(other_stored_config) is None

    for event in (
        "scope_and_safety",
        "plan_sources",
        "collect_evidence:pubmed",
        "synthesize_claims",
        "validate_report",
        "validation_receipt:save",
        "save_pending_draft",
        "request_export_approval",
        "finalize_and_export",
    ):
        assert harness.events.count(event) == 1
    assert harness.collector.calls == [initial.original_scope.selected_sources[0]]
    assert len(harness.synthesis.prior_hashes) == 1
    assert len(harness.semantic.calls) == 1
    assert harness.receipts.save_calls == 1
    assert harness.persistence.calls == 1
    assert harness.approval.calls == 1
    assert harness.export.calls == 1

    with _connect(settings) as connection:
        assert _application_snapshot(connection) == application_before
