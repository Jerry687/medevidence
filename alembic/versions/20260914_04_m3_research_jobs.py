"""Add the bounded PostgreSQL research job and idempotency registry."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from alembic import op

revision = "m3researchjob001"
down_revision = "m3evidenceprov001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_research_jobs",)
_UPGRADE_SHA256 = "d75861737e6a2ddcac52e504a04670bdaa0b9edf192e4f650d558ee237570c68"
_UPGRADE_B85 = (
    "c-pO0S#R1v5dJHxsFIBos)SIQMCyY>T*VET)R<Ojpw`+Rii5rD`XE77`rEs^#wUUBP-"
    "!1#XTG_QhodR!8>(We$W*QdDhj}bmFEI+;C*mrMGymyoQ3sB?HI{ZGEJhCSe}c%DMtTBG34$^3+W>h>65|W7;ym84nmqR6KiV;Yb"
    "0PFPn)m^LK-DiQy0A^CU$5Dhd>rMUhHy|Aws<NDR$A9@kqaFAf9Nnocr`?zb9t_&N8GPc_U~S;>063@hI633|Z7r$UEJp9HNLumP"
    "6eV)a$nL>a9F@V!|N6#I4nN6Kw=I0oTHbl_m}{wV^sTmEj%wu9-"
    "LDi++rB6<w>JmC3+F{fS|yx@ncbdN66|{#Sebkv=vJMbk|bF0HLmyEC+*V%(!!^&ZLD$hEc<)89=+QHY7IeVwRCZVci<`q@+#CW;"
    "~5R(7_dw)o;CUc!5!_HXmR(O)F}WaQ<;N&5n~=d(ZOFYSWvzO=i==Zp!?FR(qUadP^!^YTtYihhmC<q@{U?=oKC&WB#<rPs~j#U6"
    "3A_`D82EK9y@5a&5I*Il@HBNDN$`+@Q+6RwTL0HKkAUXkv!*E%dMv5v)^*kqUOsHP)Xic>rA61D@<vBbJbJo1ZCArO~QRu&K!2_h"
    "5PK6RFv0z86~>B2MbmLOAtSJ?Bh?Ss@3X+Or4*jBO*fzIXH<!XJBsLhQW*d=j2@-*biEvZzo%H=7-"
    "GdQU@TxH}XuNv*K6tHs;dDw5TH;t)fmZi3-"
    "B|ihgS?Qu)hDKcD;&2?;N9;4h;#PTXF{RZL&j%&{?^&Aqz2{0LXOCLr{BykuYscPA342p=H2VkL7<=6"
)
_DOWNGRADE_SHA256 = "3a5b8d07253f0cb1a401c727d467e89272b2e6555c92b5c122af5e5e37461cad"
_DOWNGRADE_B85 = "c-o6ratZPePzZ5!@^MwjO-)HH%S=hlOHS3xHI6SzEly1=O3sMS%1<g*iUj~NRu0+"


def _statements(encoded: str, expected_hash: str) -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(encoded))
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError("frozen research-job DDL identity drift")
    result = json.loads(raw)
    if (
        not isinstance(result, list)
        or len(result) != 1
        or not all(isinstance(item, str) for item in result)
    ):
        raise RuntimeError("frozen research-job DDL inventory drift")
    return tuple(result)


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_UPGRADE_B85, _UPGRADE_SHA256):
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_DOWNGRADE_B85, _DOWNGRADE_SHA256):
        connection.exec_driver_sql(statement)
