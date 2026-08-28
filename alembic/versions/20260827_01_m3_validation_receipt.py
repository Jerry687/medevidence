"""Add the immutable M3 validation-receipt store.

Revision ID: m3validationreceipt001
Revises: m1bfaers002001
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from alembic import op

revision = "m3validationreceipt001"
down_revision = "m1bfaers002001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_validation_receipts",)
_CREATE_ORDER = TABLE_ORDER

# Frozen PostgreSQL CREATE TABLE SQL is embedded instead of importing mutable
# application metadata. The digest makes accidental migration drift fail at
# import before any DDL is executed.
_DDL_PAYLOAD_B85 = (
    "c-oaz{coB;82(o-%@Qz~%h0y7P5J}kEoD`7c-nN;T~0XVT0JNnCT8jW_5nrk1DPZw+{g1g@5jCG`+PCsnh8||0aD"
    "vt2v*dlYi3h!(J!keUXvxWiC`|rKD8+GL;&OopNMpanGMFOsokrltTb9RVDu3%M&0gb5TgRip(}#d)DI$w4B2cP0"
    "=IIO%LU~EJ0x&Gg8il(VMG2Ovp)4)Uz`Uz$Kp;F827?*upq%Jo-uASz9<FKNH!$G_3?@d$IYF+QW~eRhq){Od+w5"
    "1n{$v+@N>2Z{g2qrAZ*{sBb%j5Z17{)H`<5hW0^ou8xw&;VF9G~;1H?30eIBWeX<3=`UV6Y_+1@!5zt1a2@QmE;J"
    "%{PH-^YmbprwK6`v@}fvNXY^9ek_Cm`qLSv!&l-%d#E*TTrqe~w@-wR?FiYMt^6fAm091W<bb@_t9$Nxdc>t6jaL"
    "BE4^56KYT&AUsy2DkkE76-+Q1Y|ZSn=U*WG&Pnz3<~DFh<LdhM`D^`#)aTPb*O%{~B%m4{koH&1i<UW}^<K}`m(g"
    "0OUrn=vW^~ZHA+!CH?OJJM;#q4Z`pK@?mnsQ}-{d&>z2}V0mBd^y49XeBGohSwJQ_~ot3;m`Qx?DF5FaloUkFE@3"
    "7@Ux!%<VKfi^^s5E?*9Jd0XA`Ik{sGZnb|gQx<ra4r?`tE6c=v(hZR1TLRpvGJ%omk;Jz?M`xMFVqrJZNj5(!Y`)"
    "(01821P5"
)
_DDL_PAYLOAD_SHA256 = "9d531079f5b73a7a4c2b32f20c6b8a07a23d77756785223e4ab5b7f59fda41c3"


def _ddl_statements() -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(_DDL_PAYLOAD_B85)).decode("utf-8")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != _DDL_PAYLOAD_SHA256:
        raise RuntimeError("frozen M3 validation-receipt migration DDL payload identity drift")
    statements = json.loads(raw)
    if not isinstance(statements, list) or len(statements) != len(_CREATE_ORDER):
        raise RuntimeError("frozen M3 validation-receipt migration DDL inventory drift")
    if not all(isinstance(statement, str) for statement in statements):
        raise RuntimeError(
            "frozen M3 validation-receipt migration DDL must contain only SQL strings"
        )
    return tuple(statements)


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _ddl_statements():
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    for name in reversed(_CREATE_ORDER):
        connection.exec_driver_sql(f'DROP TABLE medevidence."{name}"')
