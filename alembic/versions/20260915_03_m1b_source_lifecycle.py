"""Admit truthful running M1B runs before source execution."""

from __future__ import annotations

import hashlib

from alembic import op

revision = "m3sourcelifecycle001"
down_revision = "m3localcatalog001"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
ALTER TABLE medevidence.m1b_runs DROP CONSTRAINT ck_m1b_runs_status;
ALTER TABLE medevidence.m1b_runs ADD CONSTRAINT ck_m1b_runs_status CHECK (
    status IN ('running','completed','degraded','failed') AND
    (status <> 'running' OR completed_at_utc IS NULL)
)
""".strip()
_DOWNGRADE_SQL = """
ALTER TABLE medevidence.m1b_runs DROP CONSTRAINT ck_m1b_runs_status;
ALTER TABLE medevidence.m1b_runs ADD CONSTRAINT ck_m1b_runs_status CHECK (
    status IN ('completed','degraded','failed')
)
""".strip()
_UPGRADE_SHA256 = "b218251d0396d98278ffea7561ae05a930ac65b8a70c77a8389066def52ee619"
_DOWNGRADE_SHA256 = "00a134db5aeeb4f1cd6c804bade96f832ad17f2772a387ca7cfdeb0b794de944"


def _verified(value: str, expected: str) -> str:
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != expected:
        raise RuntimeError("source lifecycle DDL identity drift")
    return value


def _execute(value: str) -> None:
    connection = op.get_bind()
    for statement in value.split(";\n"):
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(_verified(_UPGRADE_SQL, _UPGRADE_SHA256))


def downgrade() -> None:
    # Running rows must be finalized explicitly before downgrade.
    _execute(_verified(_DOWNGRADE_SQL, _DOWNGRADE_SHA256))
