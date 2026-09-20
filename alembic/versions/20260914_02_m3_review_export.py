"""Add bound report material, explicit review, and resumable local exports."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from alembic import op

revision = "m3reviewexport001"
down_revision = "m3stage1receiptv2001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_report_documents", "m3_pending_drafts", "m3_review_records", "m3_exports")
_UPGRADE_SHA256 = "02eba14e1e94f31ef58d55e619d3aaed9d32b8597dd56244cbf02ae4260e878a"
_UPGRADE_B85 = (
    "c-"
    "qZZ|8LVe5dT*!^rR+IGqJ%NFbSd1Wf17ny)*^EIwCJ|S=jQ0#2xgZ_x^V5G*03qb=)x(r2R0bcjvqF=RS9L{$L)BY(sYp;OH;M1_"
    "+UlZUY}h9@+~ZxhYEG6uW-xEkhLH3@Gzxj@i)-"
    "eDF@UN3V5T**|!y0&C&`Yc?Ja0TnBhrG&gV!qnmw%&tH#`((c<dJAs?AL1a6h+iHGl0MrV3L^U{ihPuo!S=|0U7`%T30&R8&<Ag("
    "6YFI|CQ0L46hV?op;&pJNa#yOg1B5^B=jnT>9rq!laTz3B9uamd>3MOi9O($r^eLLPtU-6(|MgA!N-YZG-"
    "E<(7GyGd$Hs|18#`b$vu(q2+)9wQIGR{f$JR~D0m-%7g}F1^Jk{+F;H~iiC^hV<Ed$H19R}DrPshwM|Ct#;DX}>O9SCe&UR-xu&Q"
    "S$UCbnU|vZ#kjCrVXd8z%<I!^oI6Ypku1QU5B{iA9n*Hb{-"
    "yB!jj&a_Fbo*|A>x)biNtOr}fk#Q|OsU>KvfTt317VDM?Jps~+K*%dta`|#-"
    "eq4o@Fi;EwJkN^8?0CejZROMai3B<drm#S93XvHszc6*?{=r*RxMoJ$NWh~Avo}rg-"
    "<*<ZSCy9tv8nrDJ?kMq%3eu@!%v0owI&|scRf6J$(qKCE`5?ahf;?RLUW&E}k4VEbg{uzXChb**)p<nz=Fx*;Pj^a4u7l{a>!)zR"
    "dJ`ik>cno_(+;Sy5im!LeBhh7k+X0w%;<G^)?%5)t5C!i8d|P#FEk_RTk(e5vw}1(Q*uDxC~L&2U*NL%CPo|oI`UAK9LRi9$3e8F"
    "v_45M$cR`abJ(toJRso!w2NVZOEp&!Wy&`X3hNM9)~ocC)gXG2A>b3bd1|O%!wm}}^P-ud$$U-CyNwK-y9`sDzxC-"
    "$;9h%e;1qvtps7E2i)gAcqh)-qYagNZFR9{->fb&0NW1v)aJYZ)gmH|p?zSPTyH8V%+LZKOmCI6D&TQyoXVU`80490k9t;O5${X"
    "--fc${;VM*)a>7mXNcj)oxJI!E0qU%EscM;t%iRtsL+-"
    "tPjyunEj@^9L7<%v4O5HB+UP3ObqBDf)QS%^xxXNMbCM+w>cUPcp=8klaqi>}eouePCeFl2E(qeR%Io>2;vAS-"
    ")C19&|a7)N$A9q|Yz+jh!(D9$++uNtF}!}%emrt~Y_rSR$x?Jfl-"
    "T5Y8w9!kvXlW=CeOBdSNDt^DchUJXkx0@{7w>59Oo$q{UW?>eLTZE~skIx5;!`2rzsmYw?yhXrigHpwd!!W>Dq*L&n+UFD{?5y5^"
    "D;lo=tJMRY&-bWYGeHt+p<i2tE`9=)F=Y1"
)
_DOWNGRADE_SHA256 = "00ab3e9c1a3c41325d4bf187257ec6dd90d4d67d841cfcd523856636af7116e9"
_DOWNGRADE_B85 = (
    "c-o6ratZPePzZ5!@^MwjO-"
    ")HH%S=hlOHS2`QOY%rPpv4(FDfaHQBu;utF8#hO)Upf$@xVogq0Vh=A~rjrN^ffC8iN&I>;6ADf!8zxv6<z4Y2^>!#&m"
)


def _statements(encoded: str, expected_hash: str) -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(encoded))
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError("frozen review/export DDL identity drift")
    result = json.loads(raw)
    if (
        not isinstance(result, list)
        or len(result) != 4
        or not all(isinstance(item, str) for item in result)
    ):
        raise RuntimeError("frozen review/export DDL inventory drift")
    return tuple(result)


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_UPGRADE_B85, _UPGRADE_SHA256):
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_DOWNGRADE_B85, _DOWNGRADE_SHA256):
        connection.exec_driver_sql(statement)
