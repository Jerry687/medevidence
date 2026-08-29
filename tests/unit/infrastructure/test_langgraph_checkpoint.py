"""Offline contract tests for strict LangGraph checkpoint infrastructure."""

from __future__ import annotations

import ast
import importlib
import json
import pickle
import re
from importlib.metadata import version
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

import psycopg
import pytest
from langchain_core.messages import human as human_messages
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel

import medevidence.infrastructure.langgraph_checkpoint as checkpoint_module
from medevidence.persistence.config import (
    PersistenceConfigurationError,
    PersistenceSettings,
)


class _UnsafeModel(BaseModel):
    value: int


class _UnsafeCustom:
    pass


class _FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def execute(self, statement: object) -> None:
        self.statements.append(statement.as_string())  # type: ignore[attr-defined]


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


class _FakeConnectionType:
    connection = _FakeConnection()
    calls: ClassVar[list[tuple[str, dict[str, object]]]] = []

    @classmethod
    def reset(cls) -> None:
        cls.connection = _FakeConnection()
        cls.calls = []

    @classmethod
    def connect(cls, uri: str, **kwargs: object) -> _FakeConnection:
        cls.calls.append((uri, kwargs))
        return cls.connection


class _FailingConnectionType:
    @classmethod
    def connect(cls, uri: str, **kwargs: object) -> _FakeConnection:
        del uri, kwargs
        raise RuntimeError("driver diagnostic leaked s@cret")


class _FakeSaver:
    instances: ClassVar[list[_FakeSaver]] = []

    def __init__(self, connection: object, serde: object) -> None:
        self.connection = connection
        self.serde = serde
        self.setup_calls = 0
        self.__class__.instances.append(self)

    def setup(self) -> None:
        self.setup_calls += 1


class _FailingSetupSaver(_FakeSaver):
    def setup(self) -> None:
        super().setup()
        raise RuntimeError("setup diagnostic leaked s@cret")


def _settings() -> PersistenceSettings:
    return PersistenceSettings(
        "postgresql+psycopg://db_user:s%40cret@localhost:5432/medevidence?sslmode=disable"
    )


@pytest.mark.parametrize(
    "database_url",
    (
        "sqlite:///checkpoint.db",
        "postgresql+psycopg://db_user:secret@/medevidence",
        "postgresql+psycopg://db_user:secret@localhost:5432",
    ),
)
def test_checkpoint_configuration_reuses_strict_postgresql_url_validation(
    database_url: str,
) -> None:
    with pytest.raises(PersistenceConfigurationError):
        PersistenceSettings(database_url)


def test_strict_serializer_roundtrips_only_primitive_channel_values() -> None:
    serializer = checkpoint_module.create_strict_checkpoint_serializer()
    value = {
        "schema_version": "m3.workflow.v1",
        "count": 3,
        "ratio": 0.25,
        "active": True,
        "missing": None,
        "items": ["one", 2, False, {"nested": "value"}],
    }

    encoded = serializer.dumps_typed(value)

    assert serializer.loads_typed(encoded) == value
    assert serializer.pickle_fallback is False
    assert serializer._allowed_json_modules is None
    assert serializer._allowed_msgpack_modules is None
    assert serializer._custom_unpack_ext_hook is True


def test_strict_serializer_rejects_pickle_and_runtime_authority() -> None:
    serializer = checkpoint_module.create_strict_checkpoint_serializer()

    with pytest.raises(NotImplementedError, match="Unknown serialization type: pickle"):
        serializer.loads_typed(("pickle", pickle.dumps(_UnsafeCustom())))
    with pytest.raises(TypeError, match="not msgpack serializable"):
        serializer.dumps_typed(_UnsafeCustom())
    with pytest.raises(TypeError, match="not msgpack serializable"):
        serializer.dumps_typed(len)


def test_strict_serializer_rejects_legacy_lc1_before_human_message_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serializer = checkpoint_module.create_strict_checkpoint_serializer()
    construction_calls = 0

    class _ConstructionTrap:
        def __init__(self, **_: object) -> None:
            nonlocal construction_calls
            construction_calls += 1

    monkeypatch.setattr(human_messages, "HumanMessage", _ConstructionTrap)
    legacy_payload = json.dumps(
        {
            "lc": 1,
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "HumanMessage"],
            "kwargs": {"content": "must-not-construct"},
        }
    ).encode()

    with pytest.raises(
        checkpoint_module.CheckpointDeserializationError,
        match="JSON constructor envelopes are prohibited",
    ):
        serializer.loads_typed(("json", legacy_payload))

    assert construction_calls == 0


def test_strict_serializer_rejects_lc2_and_custom_msgpack_construction() -> None:
    serializer = checkpoint_module.create_strict_checkpoint_serializer()
    constructor_payload = json.dumps(
        {
            "lc": 2,
            "type": "constructor",
            "id": [__name__, "_UnsafeCustom"],
            "method": "constructor",
            "kwargs": {},
        }
    ).encode()
    model_payload = serializer.dumps_typed(_UnsafeModel(value=7))

    with pytest.raises(
        checkpoint_module.CheckpointDeserializationError,
        match="JSON constructor envelopes are prohibited",
    ):
        serializer.loads_typed(("json", constructor_payload))
    with pytest.raises(
        checkpoint_module.CheckpointDeserializationError,
        match="msgpack payload is invalid or contains a prohibited extension",
    ):
        serializer.loads_typed(model_payload)


def test_strict_serializer_rejects_unknown_msgpack_extension() -> None:
    serializer = checkpoint_module.create_strict_checkpoint_serializer()
    import ormsgpack

    payload = ormsgpack.packb(ormsgpack.Ext(42, b"untrusted"))

    with pytest.raises(
        checkpoint_module.CheckpointDeserializationError,
        match="msgpack payload is invalid or contains a prohibited extension",
    ):
        serializer.loads_typed(("msgpack", payload))


def test_schema_is_constant_and_identifier_quoted() -> None:
    assert checkpoint_module.LANGGRAPH_CHECKPOINT_SCHEMA == ("medevidence_langgraph_checkpoint_v1")
    assert checkpoint_module.CHECKPOINT_CONNECT_TIMEOUT_SECONDS == 5
    assert checkpoint_module.CHECKPOINT_STATEMENT_TIMEOUT_MILLISECONDS == 30_000
    assert checkpoint_module.CHECKPOINT_LOCK_TIMEOUT_MILLISECONDS == 5_000
    assert {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    } == checkpoint_module.OFFICIAL_CHECKPOINT_TABLES
    assert tuple(statement.as_string() for statement in checkpoint_module._schema_statements()) == (
        'CREATE SCHEMA IF NOT EXISTS "medevidence_langgraph_checkpoint_v1"',
        'SET search_path TO "medevidence_langgraph_checkpoint_v1", public',
    )


def test_exact_official_package_migrations_create_only_the_four_frozen_tables() -> None:
    assert version("langgraph-checkpoint-postgres") == "3.1.2"
    created_tables = {
        match.group(1)
        for migration in PostgresSaver.MIGRATIONS
        if (match := re.search(r"CREATE TABLE IF NOT EXISTS ([a-z_]+)", migration))
    }

    assert created_tables == checkpoint_module.OFFICIAL_CHECKPOINT_TABLES
    assert len(PostgresSaver.MIGRATIONS) == 10


def test_context_uses_exact_connection_policy_without_implicit_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnectionType.reset()
    _FakeSaver.instances = []
    monkeypatch.setattr(checkpoint_module, "Connection", _FakeConnectionType)
    monkeypatch.setattr(checkpoint_module, "PostgresSaver", _FakeSaver)

    with checkpoint_module.postgres_checkpoint_saver(_settings()) as saver:
        assert saver is _FakeSaver.instances[0]
        assert not _FakeConnectionType.connection.closed

    assert _FakeConnectionType.connection.closed
    assert _FakeConnectionType.connection.cursor_instance.statements == [
        'CREATE SCHEMA IF NOT EXISTS "medevidence_langgraph_checkpoint_v1"',
        'SET search_path TO "medevidence_langgraph_checkpoint_v1", public',
    ]
    assert len(_FakeConnectionType.calls) == 1
    uri, kwargs = _FakeConnectionType.calls[0]
    assert uri == "postgresql://db_user:s%40cret@localhost:5432/medevidence?sslmode=disable"
    assert kwargs == {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": checkpoint_module.dict_row,
        "connect_timeout": 5,
        "options": "-c statement_timeout=30000 -c lock_timeout=5000",
    }
    assert _FakeSaver.instances[0].setup_calls == 0
    serializer = _FakeSaver.instances[0].serde
    assert serializer.pickle_fallback is False
    assert serializer._allowed_json_modules is None
    assert serializer._allowed_msgpack_modules is None


def test_setup_is_explicit_idempotent_and_connections_are_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnectionType.reset()
    _FakeSaver.instances = []
    monkeypatch.setattr(checkpoint_module, "Connection", _FakeConnectionType)
    monkeypatch.setattr(checkpoint_module, "PostgresSaver", _FakeSaver)

    checkpoint_module.setup_postgres_checkpointing(_settings())
    first_connection = _FakeConnectionType.connection
    _FakeConnectionType.connection = _FakeConnection()
    checkpoint_module.setup_postgres_checkpointing(_settings())

    assert len(_FakeSaver.instances) == 2
    assert [instance.setup_calls for instance in _FakeSaver.instances] == [1, 1]
    assert first_connection.closed
    assert _FakeConnectionType.connection.closed


def test_connection_failure_exposes_only_redacted_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkpoint_module, "Connection", _FailingConnectionType)

    with (
        pytest.raises(
            checkpoint_module.LangGraphCheckpointInfrastructureError,
            match=r"postgresql\+psycopg://localhost:5432/medevidence",
        ) as captured,
        checkpoint_module.postgres_checkpoint_saver(_settings()),
    ):
        raise AssertionError("unreachable")

    assert "s@cret" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_setup_failure_closes_connection_and_exposes_only_redacted_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnectionType.reset()
    _FailingSetupSaver.instances = []
    monkeypatch.setattr(checkpoint_module, "Connection", _FakeConnectionType)
    monkeypatch.setattr(checkpoint_module, "PostgresSaver", _FailingSetupSaver)

    with pytest.raises(
        checkpoint_module.LangGraphCheckpointInfrastructureError,
        match=r"postgresql\+psycopg://localhost:5432/medevidence",
    ) as captured:
        checkpoint_module.setup_postgres_checkpointing(_settings())

    assert "s@cret" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert _FakeConnectionType.connection.closed


def test_import_has_no_connection_or_setup_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ImportTrap:
        @classmethod
        def connect(cls, *_: object, **__: object) -> None:
            raise AssertionError("module import must not connect")

    real_connection = psycopg.Connection
    monkeypatch.setattr(psycopg, "Connection", _ImportTrap)
    importlib.reload(checkpoint_module)
    monkeypatch.setattr(psycopg, "Connection", real_connection)
    importlib.reload(checkpoint_module)


def test_infrastructure_dependency_direction_and_table_access_are_closed() -> None:
    infrastructure_path = Path("src/medevidence/infrastructure/langgraph_checkpoint.py")
    source = infrastructure_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(infrastructure_path))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }

    assert "medevidence.persistence.config" in imports
    assert "medevidence.persistence.models" not in imports
    assert "medevidence.persistence.repositories" not in imports
    assert "PostgresStore" not in source
    assert "SELECT " not in source.upper()
    assert "INSERT " not in source.upper()
    assert "UPDATE " not in source.upper()
    assert "DELETE " not in source.upper()
    for inner_layer in ("domain", "tools", "orchestration"):
        for path in Path("src/medevidence", inner_layer).rglob("*.py"):
            assert "medevidence.infrastructure" not in path.read_text(encoding="utf-8")
