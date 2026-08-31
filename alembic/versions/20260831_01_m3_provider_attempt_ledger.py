"""Add the isolated insert-only M3 provider-attempt event ledger."""

# ruff: noqa: E501  # Frozen DDL literals remain exact.

from __future__ import annotations

from alembic import op

revision = "m3providerattempt001"
down_revision = "m3validationreceipt001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_provider_attempt_events",)

_DDL = r"""CREATE TABLE medevidence.m3_provider_attempt_events (
 event_id VARCHAR(96) NOT NULL,
 schema_version VARCHAR(40) NOT NULL,
 provider_run_id VARCHAR(96) NOT NULL,
 case_id VARCHAR(32) NOT NULL,
 case_ordinal SMALLINT NOT NULL,
 attempt_ordinal SMALLINT NOT NULL,
 event_kind VARCHAR(16) NOT NULL,
 event_slot SMALLINT NOT NULL,
 start_event_id VARCHAR(96),
 start_event_kind VARCHAR(16),
 provider VARCHAR(32) NOT NULL,
 endpoint VARCHAR(256) NOT NULL,
 model VARCHAR(128) NOT NULL,
 configuration_hash CHAR(71) NOT NULL,
 request_hash CHAR(71) NOT NULL,
 started_at_utc TIMESTAMP WITH TIME ZONE NOT NULL,
 completed_at_utc TIMESTAMP WITH TIME ZONE,
 http_status SMALLINT,
 disposition VARCHAR(64) NOT NULL,
 error_code VARCHAR(64),
 credential_echo BOOLEAN NOT NULL,
 body_complete BOOLEAN,
 body_byte_count BIGINT,
 body_hash CHAR(71),
 body_relative_path VARCHAR(1024),
 observed_body_bytes_lower_bound BIGINT,
 approved_header_names VARCHAR(64)[] NOT NULL,
 persisted_at_utc TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
 CONSTRAINT pk_m3_provider_attempt_events PRIMARY KEY (event_id),
 CONSTRAINT uq_m3_provider_attempt_event_slot UNIQUE (provider_run_id, case_ordinal, attempt_ordinal, event_slot),
 CONSTRAINT uq_m3_provider_attempt_event_start_binding UNIQUE (event_id, event_kind, provider_run_id, case_ordinal, attempt_ordinal, configuration_hash, request_hash),
 CONSTRAINT fk_m3_provider_attempt_event_start FOREIGN KEY(start_event_id, start_event_kind, provider_run_id, case_ordinal, attempt_ordinal, configuration_hash, request_hash) REFERENCES medevidence.m3_provider_attempt_events (event_id, event_kind, provider_run_id, case_ordinal, attempt_ordinal, configuration_hash, request_hash) MATCH SIMPLE ON DELETE RESTRICT ON UPDATE RESTRICT,
 CONSTRAINT ck_m3_provider_attempt_events_schema CHECK (schema_version='M3_PROVIDER_ATTEMPT_EVENT_V1'),
 CONSTRAINT ck_m3_provider_attempt_events_identity CHECK (event_id ~ '^provider-attempt-event:sha256:[0-9a-f]{64}$' AND provider_run_id ~ '^provider-attempt-run:sha256:[0-9a-f]{64}$' AND case_id ~ '^M3-008B-CAL-[0-9]{3}$'),
 CONSTRAINT ck_m3_provider_attempt_events_ordinals CHECK (case_ordinal BETWEEN 1 AND 36 AND attempt_ordinal BETWEEN 1 AND 3 AND event_slot BETWEEN 0 AND 1 AND (event_kind,event_slot) IN (('START',0),('TERMINAL',1),('RECOVERY',1))),
 CONSTRAINT ck_m3_provider_attempt_events_bindings CHECK (provider='DeepSeek API' AND endpoint='https://api.deepseek.com/responses' AND model='deepseek-v4-pro' AND configuration_hash ~ '^sha256:[0-9a-f]{64}$' AND request_hash ~ '^sha256:[0-9a-f]{64}$' AND case_id='M3-008B-CAL-' || lpad(case_ordinal::text,3,'0')),
 CONSTRAINT ck_m3_provider_attempt_events_shape CHECK ((event_kind='START' AND disposition='started' AND completed_at_utc IS NULL AND http_status IS NULL AND error_code IS NULL AND credential_echo=false AND body_complete IS NULL AND body_byte_count IS NULL AND body_hash IS NULL AND body_relative_path IS NULL AND observed_body_bytes_lower_bound IS NULL) OR (event_kind='RECOVERY' AND disposition='interrupted_unknown_after_start' AND completed_at_utc IS NOT NULL AND http_status IS NULL AND error_code='interrupted_unknown_after_start' AND credential_echo=false AND body_complete IS NULL AND body_byte_count IS NULL AND body_hash IS NULL AND body_relative_path IS NULL AND observed_body_bytes_lower_bound IS NULL) OR (event_kind='TERMINAL' AND completed_at_utc IS NOT NULL AND disposition IN ('success','retryable_status','transport_unavailable','deadline_exceeded','response_invalid','response_too_large','credential_echo','authentication_failed','provider_rejected','candidate_invalid') AND ((disposition='success' AND error_code IS NULL) OR (disposition<>'success' AND error_code=disposition)) AND ((credential_echo=true AND disposition='credential_echo' AND body_hash IS NULL AND body_relative_path IS NULL) OR (credential_echo=false AND ((body_hash IS NOT NULL AND body_relative_path IS NOT NULL AND body_complete=true AND body_byte_count IS NOT NULL AND observed_body_bytes_lower_bound=body_byte_count) OR (body_hash IS NULL AND body_relative_path IS NULL)))))),
 CONSTRAINT ck_m3_provider_attempt_events_headers CHECK (cardinality(approved_header_names)<=5 AND array_position(approved_header_names,NULL) IS NULL AND approved_header_names <@ ARRAY['content-type','content-length','transfer-encoding','content-encoding','x-request-id']::varchar[] AND (completed_at_utc IS NULL OR completed_at_utc>=started_at_utc) AND (http_status IS NULL OR http_status BETWEEN 100 AND 599) AND (body_byte_count IS NULL OR body_byte_count BETWEEN 0 AND 131072) AND (observed_body_bytes_lower_bound IS NULL OR observed_body_bytes_lower_bound>=0) AND (body_hash IS NULL OR body_hash ~ '^sha256:[0-9a-f]{64}$') AND (body_relative_path IS NULL OR (char_length(body_relative_path) BETWEEN 1 AND 1024 AND left(body_relative_path,1)<>'/' AND position(chr(92) IN body_relative_path)=0 AND body_relative_path !~ '(^|/)\.{1,2}(/|$)')))
)"""

_DDL = _DDL.replace(
    "'provider_rejected','candidate_invalid')",
    "'provider_rejected','candidate_invalid','evidence_persistence_failure')",
)
_DDL = (
    _DDL.removesuffix("\n)")
    + r""",
 CONSTRAINT ck_m3_provider_attempt_events_closure_binding CHECK (((event_kind='START' AND start_event_id IS NULL AND start_event_kind IS NULL) OR (event_kind IN ('TERMINAL','RECOVERY') AND start_event_id IS NOT NULL AND start_event_kind='START')) AND (event_kind<>'TERMINAL' OR (((disposition='success' AND error_code IS NULL) OR (disposition<>'success' AND error_code=disposition)) AND (disposition<>'success' OR (body_complete=true AND body_hash IS NOT NULL AND body_relative_path IS NOT NULL AND body_byte_count IS NOT NULL)))))
)"""
)


def _ddl_statements() -> tuple[str, ...]:
    return (_DDL,)


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_DDL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql('DROP TABLE medevidence."m3_provider_attempt_events"')
