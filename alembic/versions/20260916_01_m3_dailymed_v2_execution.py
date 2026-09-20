"""Add bounded DailyMed V2 execution records and packaging operation."""

from __future__ import annotations

import hashlib

from alembic import op

revision = "m3dailymedv2exec001"
down_revision = "m3sourcelifecycle001"
branch_labels = None
depends_on = None

_UPGRADE_SQL = (
    "\n"
    "ALTER TABLE medevidence.m1b_acquisitions DROP CONSTRAINT ck_m1b_acquisit"
    "ions_operation;\n"
    "ALTER TABLE medevidence.m1b_acquisitions ADD CONSTRAINT ck_m1b_acquisiti"
    "ons_operation CHECK (operation IN ('search','fetch') OR (source='dailyme"
    "d' AND operation='packaging'));\n"
    "ALTER TABLE medevidence.m1b_source_outcomes DROP CONSTRAINT ck_outcome_o"
    "peration;\n"
    "ALTER TABLE medevidence.m1b_source_outcomes ADD CONSTRAINT ck_outcome_op"
    "eration CHECK (operation IN ('search','fetch') OR (source='dailymed' AND"
    " operation='packaging'));\n"
    "CREATE TABLE medevidence.m3_dailymed_v2_records (\n"
    "    record_id TEXT NOT NULL,\n"
    "    schema_version TEXT NOT NULL,\n"
    "    record_kind TEXT NOT NULL,\n"
    "    run_id TEXT NOT NULL,\n"
    "    scope_id TEXT NOT NULL,\n"
    "    task_id TEXT NOT NULL,\n"
    "    attempt_id TEXT NOT NULL,\n"
    "    query_id TEXT NOT NULL,\n"
    "    acquisition_id TEXT NOT NULL,\n"
    "    acquisition_intent_id TEXT NOT NULL,\n"
    "    snapshot_id TEXT NOT NULL,\n"
    "    manifest_id TEXT NOT NULL,\n"
    "    item_ordinal INTEGER NOT NULL,\n"
    "    payload_hash TEXT NOT NULL,\n"
    "    payload_bytes INTEGER NOT NULL,\n"
    "    payload_json JSONB NOT NULL,\n"
    "    created_at_utc TIMESTAMP WITH TIME ZONE NOT NULL,\n"
    "    CONSTRAINT pk_m3_dailymed_v2_records PRIMARY KEY (record_id),\n"
    "    CONSTRAINT uq_m3_dailymed_v2_record_slot UNIQUE (run_id, attempt_id,"
    " record_kind, query_id, item_ordinal),\n"
    "    CONSTRAINT fk_m3_dailymed_v2_record_acquisition FOREIGN KEY(acquisit"
    "ion_id) REFERENCES medevidence.m1b_acquisitions (acquisition_id) ON DELE"
    "TE RESTRICT ON UPDATE RESTRICT,\n"
    "    CONSTRAINT fk_m3_dailymed_v2_record_snapshot FOREIGN KEY(snapshot_id"
    ") REFERENCES medevidence.m1b_snapshots (snapshot_id) ON DELETE RESTRICT "
    "ON UPDATE RESTRICT,\n"
    "    CONSTRAINT fk_m3_dailymed_v2_record_manifest FOREIGN KEY(manifest_id"
    ") REFERENCES medevidence.m1b_artifacts (artifact_id) ON DELETE RESTRICT "
    "ON UPDATE RESTRICT,\n"
    "    CONSTRAINT ck_m3_dailymed_v2_record_schema CHECK (schema_version='m3"
    ".dailymed-v2-record.v1'),\n"
    "    CONSTRAINT ck_m3_dailymed_v2_record_kind CHECK (record_kind IN ('dis"
    "covery','packaging','decision','selected_spl','chunk')),\n"
    "    CONSTRAINT ck_m3_dailymed_v2_record_identity CHECK (record_id ~ '^da"
    "ilymed-v2-record:sha256:[0-9a-f]{64}$' AND payload_hash ~ '^sha256:[0-9a"
    "-f]{64}$' AND manifest_id ~ '^sha256:[0-9a-f]{64}$'),\n"
    "    CONSTRAINT ck_m3_dailymed_v2_record_bounds CHECK (item_ordinal BETWE"
    "EN 0 AND 99 AND payload_bytes BETWEEN 2 AND 2097152 AND jsonb_typeof(pay"
    "load_json)='object' AND octet_length(payload_json::text) BETWEEN 2 AND 2"
    "097152)\n"
    ")\n"
).strip()
_DOWNGRADE_SQL = (
    "\n"
    "DROP TABLE medevidence.m3_dailymed_v2_records;\n"
    "ALTER TABLE medevidence.m1b_source_outcomes DROP CONSTRAINT ck_outcome_o"
    "peration;\n"
    "ALTER TABLE medevidence.m1b_source_outcomes ADD CONSTRAINT ck_outcome_op"
    "eration CHECK (operation IN ('search','fetch'));\n"
    "ALTER TABLE medevidence.m1b_acquisitions DROP CONSTRAINT ck_m1b_acquisit"
    "ions_operation;\n"
    "ALTER TABLE medevidence.m1b_acquisitions ADD CONSTRAINT ck_m1b_acquisiti"
    "ons_operation CHECK (operation IN ('search','fetch'))\n"
).strip()
_UPGRADE_SHA256 = "0a7be25a05b4aebfae53d1a0586ccec9773ce4e9a15ff4e5241aa4bbc10adf2e"
_DOWNGRADE_SHA256 = "84f81c30b59a65bedabc08ad0b93ffa754842f439e2a8a699cdaad4047d7156a"


def _verified(value: str, expected: str) -> str:
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != expected:
        raise RuntimeError("DailyMed V2 execution DDL identity drift")
    return value


def upgrade() -> None:
    for statement in _verified(_UPGRADE_SQL, _UPGRADE_SHA256).split(";\n"):
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    # Existing packaging rows block historical CHECKs; they are never deleted.
    for statement in _verified(_DOWNGRADE_SQL, _DOWNGRADE_SHA256).split(";\n"):
        op.get_bind().exec_driver_sql(statement)
