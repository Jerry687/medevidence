"""Strict, schema-isolated PostgreSQL checkpoint infrastructure for M3."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection, sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from medevidence.persistence.config import PersistenceSettings

LANGGRAPH_CHECKPOINT_SCHEMA = "medevidence_langgraph_checkpoint_v1"
CHECKPOINT_CONNECT_TIMEOUT_SECONDS = 5
CHECKPOINT_STATEMENT_TIMEOUT_MILLISECONDS = 30_000
CHECKPOINT_LOCK_TIMEOUT_MILLISECONDS = 5_000
OFFICIAL_CHECKPOINT_TABLES = frozenset(
    {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    }
)


class LangGraphCheckpointInfrastructureError(RuntimeError):
    """Checkpoint infrastructure could not be prepared within the frozen boundary."""


class CheckpointDeserializationError(ValueError):
    """Checkpoint bytes requested construction outside the primitive contract."""


class _StrictCheckpointSerializer(JsonPlusSerializer):
    """JsonPlus encoding with all constructor-bearing decode paths closed."""

    def _reviver(self, value: dict[str, object]) -> object:
        if value.get("lc") in {1, 2} and value.get("type") == "constructor":
            raise CheckpointDeserializationError(
                "checkpoint JSON constructor envelopes are prohibited"
            )
        return value

    def loads_typed(self, data: tuple[str, bytes]) -> object:
        try:
            return super().loads_typed(data)
        except ValueError:
            if data[0] != "msgpack":
                raise
            raise CheckpointDeserializationError(
                "checkpoint msgpack payload is invalid or contains a prohibited extension"
            ) from None


def _reject_msgpack_extension(code: int, data: bytes) -> object:
    del data
    raise CheckpointDeserializationError(f"checkpoint msgpack extension code {code} is prohibited")


def create_strict_checkpoint_serializer() -> JsonPlusSerializer:
    """Create the no-pickle serializer for primitive-only M3 checkpoint state."""

    return _StrictCheckpointSerializer(
        pickle_fallback=False,
        allowed_json_modules=None,
        allowed_msgpack_modules=None,
        __unpack_ext_hook__=_reject_msgpack_extension,
    )


def _psycopg_connection_uri(settings: PersistenceSettings) -> str:
    """Translate the validated SQLAlchemy driver URL for psycopg without logging it."""

    return (
        make_url(settings.database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


def _schema_statements() -> tuple[sql.Composed, sql.Composed]:
    identifier = sql.Identifier(LANGGRAPH_CHECKPOINT_SCHEMA)
    return (
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(identifier),
        sql.SQL("SET search_path TO {}, public").format(identifier),
    )


def _connection_options() -> str:
    return (
        f"-c statement_timeout={CHECKPOINT_STATEMENT_TIMEOUT_MILLISECONDS} "
        f"-c lock_timeout={CHECKPOINT_LOCK_TIMEOUT_MILLISECONDS}"
    )


def _prepare_schema(connection: Connection[dict[str, object]]) -> None:
    with connection.cursor() as cursor:
        for statement in _schema_statements():
            cursor.execute(statement)


@contextmanager
def postgres_checkpoint_saver(
    settings: PersistenceSettings,
    *,
    setup: bool = False,
) -> Iterator[PostgresSaver]:
    """Own one isolated synchronous checkpointer connection and close it on exit."""

    try:
        connection = Connection.connect(
            _psycopg_connection_uri(settings),
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
            connect_timeout=CHECKPOINT_CONNECT_TIMEOUT_SECONDS,
            options=_connection_options(),
        )
    except Exception:
        raise LangGraphCheckpointInfrastructureError(
            f"unable to connect to checkpoint PostgreSQL at {settings.redacted_database_url}"
        ) from None

    try:
        try:
            _prepare_schema(connection)
            saver = PostgresSaver(
                connection,
                serde=create_strict_checkpoint_serializer(),
            )
            if setup:
                saver.setup()
        except Exception:
            raise LangGraphCheckpointInfrastructureError(
                "unable to prepare isolated checkpoint infrastructure at "
                f"{settings.redacted_database_url}"
            ) from None
        yield saver
    finally:
        connection.close()


def setup_postgres_checkpointing(settings: PersistenceSettings) -> None:
    """Run the official idempotent PostgresSaver setup in the isolated schema."""

    with postgres_checkpoint_saver(settings, setup=True):
        pass
