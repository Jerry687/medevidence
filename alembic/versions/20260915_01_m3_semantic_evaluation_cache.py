"""Add the append-only runtime semantic-evaluation event cache."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib

from alembic import op

revision = "m3semanticcache001"
down_revision = "m3researchjob001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_semantic_evaluation_events",)
_UPGRADE_SQL = """
CREATE TABLE medevidence.m3_semantic_evaluation_events (
    event_id text PRIMARY KEY,
    schema_version text NOT NULL,
    operation_id text NOT NULL,
    run_id text NOT NULL,
    citation_id text NOT NULL,
    request_content_hash text NOT NULL,
    provider_configuration_version text NOT NULL,
    provider_configuration_hash text NOT NULL,
    attempt_ordinal smallint NOT NULL,
    event_slot smallint NOT NULL,
    event_kind text NOT NULL,
    start_event_id text NULL REFERENCES medevidence.m3_semantic_evaluation_events(event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    raw_event_id text NULL REFERENCES medevidence.m3_semantic_evaluation_events(event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    result_event_id text NULL REFERENCES medevidence.m3_semantic_evaluation_events(event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    payload_hash text NOT NULL,
    payload_json jsonb NOT NULL,
    raw_body_hash text NULL,
    raw_body_bytes bytea NULL,
    started_at_utc timestamptz NOT NULL,
    completed_at_utc timestamptz NULL,
    disposition text NULL,
    error_code text NULL,
    persisted_at_utc timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_semantic_cache_event_slot UNIQUE (operation_id, attempt_ordinal, event_slot),
    CONSTRAINT ck_semantic_cache_schema CHECK (schema_version = 'M3_RUNTIME_SEMANTIC_CACHE_EVENT_V1'),
    CONSTRAINT ck_semantic_cache_identity CHECK (
        event_id ~ '^semantic-cache-event:sha256:[0-9a-f]{64}$' AND
        operation_id ~ '^semantic-evaluation-operation:sha256:[0-9a-f]{64}$' AND
        run_id ~ '^run:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' AND
        citation_id ~ '^citation:sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_semantic_cache_hashes CHECK (
        request_content_hash ~ '^sha256:[0-9a-f]{64}$' AND
        provider_configuration_hash ~ '^sha256:[0-9a-f]{64}$' AND
        payload_hash ~ '^sha256:[0-9a-f]{64}$' AND
        (raw_body_hash IS NULL OR raw_body_hash ~ '^sha256:[0-9a-f]{64}$')
    ),
    CONSTRAINT ck_semantic_cache_bounds CHECK (
        attempt_ordinal BETWEEN 1 AND 3 AND
        jsonb_typeof(payload_json) = 'object' AND
        octet_length(payload_json::text) BETWEEN 2 AND 600000 AND
        (raw_body_bytes IS NULL OR octet_length(raw_body_bytes) BETWEEN 1 AND 131072)
    ),
    CONSTRAINT ck_semantic_cache_slot CHECK (
        (event_kind = 'START' AND event_slot = 0) OR
        (event_kind = 'RAW' AND event_slot = 1) OR
        (event_kind = 'RESULT' AND event_slot = 2) OR
        (event_kind = 'TERMINAL' AND event_slot = 3)
    ),
    CONSTRAINT ck_semantic_cache_raw CHECK (
        (event_kind = 'RAW' AND raw_body_hash IS NOT NULL AND raw_body_bytes IS NOT NULL) OR
        (event_kind <> 'RAW' AND raw_body_hash IS NULL AND raw_body_bytes IS NULL)
    ),
    CONSTRAINT ck_semantic_cache_terminal CHECK (
        (event_kind = 'TERMINAL' AND completed_at_utc IS NOT NULL AND disposition IS NOT NULL) OR
        (event_kind <> 'TERMINAL' AND completed_at_utc IS NULL AND disposition IS NULL AND error_code IS NULL)
    )
);
CREATE INDEX ix_semantic_cache_run_citation
ON medevidence.m3_semantic_evaluation_events (run_id, citation_id, operation_id);
""".strip()
_UPGRADE_SHA256 = "872a6a347e7ba70ca6752b2aa2b0908c47cc798beda40daadf976f7b53a94575"
_DOWNGRADE_SQL = "DROP TABLE medevidence.m3_semantic_evaluation_events"
_DOWNGRADE_SHA256 = "1306afe829daf7a5af10e9803995ee6967035fa72cff8f70863f3aea7299ece9"


def _verified(value: str, expected: str) -> str:
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != expected:
        raise RuntimeError("semantic-cache DDL identity drift")
    return value


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _verified(_UPGRADE_SQL, _UPGRADE_SHA256).split(";\n"):
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(_verified(_DOWNGRADE_SQL, _DOWNGRADE_SHA256))
