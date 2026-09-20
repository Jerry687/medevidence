"""Retain every ordered DailyMed V2 response, including repeated raw bytes."""

from __future__ import annotations

import hashlib

from alembic import op

revision = "m3dailymedv2members001"
down_revision = "m3dailymedv2exec001"
branch_labels = None
depends_on = None

_UPGRADE_SQL = (
    "\n"
    "CREATE TABLE medevidence.m3_dailymed_v2_members (\n"
    "    run_id TEXT NOT NULL,\n"
    "    acquisition_id TEXT NOT NULL,\n"
    "    snapshot_id TEXT NOT NULL,\n"
    "    ordinal INTEGER NOT NULL,\n"
    "    link_id TEXT NOT NULL,\n"
    "    artifact_id TEXT NOT NULL,\n"
    "    content_hash TEXT NOT NULL,\n"
    "    relative_path TEXT NOT NULL,\n"
    "    byte_size INTEGER NOT NULL,\n"
    "    media_type TEXT NOT NULL,\n"
    "    http_status INTEGER NOT NULL,\n"
    "    observed_at_utc TIMESTAMP WITH TIME ZONE NOT NULL,\n"
    "    body_complete BOOLEAN NOT NULL,\n"
    "    termination_reason TEXT NOT NULL,\n"
    "    page_number INTEGER NOT NULL,\n"
    "    attempt_count INTEGER NOT NULL,\n"
    "    request_url TEXT NOT NULL,\n"
    "    final_url TEXT NOT NULL,\n"
    "    CONSTRAINT pk_m3_dailymed_v2_members PRIMARY KEY (acquisition_id, or"
    "dinal),\n"
    "    CONSTRAINT uq_m3_dailymed_v2_member_link UNIQUE (acquisition_id, lin"
    "k_id),\n"
    "    CONSTRAINT fk_m3_dailymed_v2_member_snapshot FOREIGN KEY(snapshot_id"
    ") REFERENCES medevidence.m1b_snapshots (snapshot_id) ON DELETE RESTRICT "
    "ON UPDATE RESTRICT,\n"
    "    CONSTRAINT fk_m3_dailymed_v2_member_artifact FOREIGN KEY(artifact_id"
    ") REFERENCES medevidence.m1b_artifacts (artifact_id) ON DELETE RESTRICT "
    "ON UPDATE RESTRICT,\n"
    "    CONSTRAINT ck_m3_dailymed_v2_member_bounds CHECK (ordinal BETWEEN 0 "
    "AND 19 AND byte_size BETWEEN 0 AND 5242880 AND page_number BETWEEN 1 AND"
    " 5 AND attempt_count BETWEEN 1 AND 2 AND http_status BETWEEN 100 AND 599"
    "),\n"
    "    CONSTRAINT ck_m3_dailymed_v2_member_identity CHECK (content_hash ~ '"
    "^sha256:[0-9a-f]{64}$' AND artifact_id=content_hash AND (body_complete=("
    "termination_reason='complete_response')))\n"
    ")\n"
).strip()
_DOWNGRADE_SQL = "DROP TABLE medevidence.m3_dailymed_v2_members"
_UPGRADE_SHA256 = "1e2db83e292faadc1cf284df6fd19968b6725dc41b2fbf8e8b08990940a42d05"
_DOWNGRADE_SHA256 = "09b2981b7269221f0b4b6108a5ace5a2321bf8849b9692db83e2e532e117ed3d"


def _verified(value: str, expected: str) -> str:
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != expected:
        raise RuntimeError("DailyMed V2 ordered-members DDL identity drift")
    return value


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_verified(_UPGRADE_SQL, _UPGRADE_SHA256))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(_verified(_DOWNGRADE_SQL, _DOWNGRADE_SHA256))
