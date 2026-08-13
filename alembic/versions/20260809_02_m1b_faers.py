"""Add the frozen M1B FAERS aggregate metadata tables.

Revision ID: m1bfaers002001
Revises: m1bdm002001
"""

# ruff: noqa: E501  # Frozen compressed DDL payload is intentionally indivisible.

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from alembic import op

revision = "m1bfaers002001"
down_revision = "m1bdm002001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m1b_faers_queries", "m1b_faers_buckets")
_CREATE_ORDER = TABLE_ORDER

# Frozen PostgreSQL CREATE TABLE statements are embedded instead of importing
# mutable application metadata. The digest makes migration drift fail at import.
# Regenerated exact retry-evidence check projection followed by the two frozen
# additive FAERS tables.
_DDL_PAYLOAD_B85 = "c-p;JZExE)5dJGfzSzc$G)~u|4dwxkt)yNPIg^!j-8>MqL_1t1QX#1<?y&#9BlS{SmTV`%76eF0p6-s%-92~w{b+FIJ09`}=T{DjX-FSfNO?ey<K7%AP7-w|G$vBB1qrl5BX4qph7)({dxNp-qu>jUX*{PAYbs;LiDrU#(O@*%D}{z1oZ&~*UfaTw5(Ot?7qwe~h?9tF3Y#hsT+vpym5@~=NQfgAGYxB{;fokkDTRb3EJCbVOhsx=Ls&+PQ%oNN3U>=zoz7ABXvT-0Gw_{;TQ3Ne3g4$xGOAE}#%Fp-IjjP#g(eX$)drNo-zAO}c<eiu0Hizdk$Zb})kWqzx>(Ravj<xJviXZg8l)DAM2ZEAC}tt@onQTm99$6aq1Me+gA57oQ>K{JRxhDMDg#<~BGaaCc3CVFrokblu?p^JOz;C>Y;vGZ2|!IE_7$>ahZN;uA{f^=7GdoT06!B|i4&sl>I6*4HPb5$NknuS@03|E8ihM09!QkdI|7%cO_0DLN%ftORz>r5LCzXb=%?w#J+GXG1j?k*MWvyBv5`R|llEIcHl9fV37Ck81*_U5vB#2zEHDoIX-e0+SBXFbrx5yPMRSqzP^~Gb8loDC@qvbzXbhQ;{PDFj^#|8C=+oH$V3+8(iCgu5je-)OpsnJ*@y6E!?=$-7d`9go<+~^=iZ0qLpDrpAzq6$~sL_psNGNdFMnx4|SIH;KbC915c8^1uE{{b*`6498DxE{vfRZpLF+HY_z`mCM)?{M?JTPYjK!<6dbEys*xFfWd64r{Oz*c}DY+Is)Rbuldm*1?X>=W`=5jsf|A*};NOalm+#v%w(DGhbzYBsB`k6N#ctFIt-;I)Zw>p=KQq+*gJK(Ymb?P}TfTX#gpf&*cMxP+}`z1f7j{{*NzXyTz7Tc%F|otMz#9Qy<8HHGUyKx{x&Ldw2b7VeLIv{vGIFtf!E8%N)v*Kgk(XwKGl75jBQfY_!SIux{T0KSa75m6Z$b@VWv+Vafct*Bc_@s;wD4|Ak57j|pRi~dk3flPG@vqf>QZww7yT#oULkEf20uY2eCmtJPsn3`j~N~l=0OET`54~UdxwJv2ha76i1->u7@JN_rfaZ%68_D)W=-A(Un+?_KXnkd}5<DYMxmk`yW4vn&D7j`Zto-@954J#gO3naev{toh-3&(TZp)+k9DiwOJ@`;N^&Xoh*%7Z50jfcM3y1lUttk^p2?!_4OoU2zyu-&(|N(y^VxchUjTbua#yqBkazA}|(qz+}~d@wC(sAgjAw=M>bH?<X1s&htVHSL&-`>#*n$4c#;y8Ca9?9=*jHfj{kuMZx8!{4)`m^|hY4WO?8L4%Ij(b=2cX*WAe$dcL}SeyT`g3beLsOMY)rj=B3uw@!3bXp-pRT0P@G<d$!nXc3CPv5;Oj)OE#qm2Ew1$ICOauz(0+6x`XTJZj9ot;_M>dZL&&iJA4qj?&9p*nvb{r@kG%sd8YO-F5bOu=(7$TCycTDC(?Hp!s#@uf+ft;tz4rJ>tIIOR+~_ZhKgj&2%L3yhyNrgqULMtizJZY$6Im$ZVNJXm>L|JN+I(NBvjLN+|Lm3GluF6|+l!pw`vwosCd*<5f=mzEL=eH+OO6X3~#3X6&<2ynBGiV-Cv;P>wjy=t{iic44bvj<P*U8u-{LjB}7$_R7!Q==rSKmG;qLxV{"
_DDL_PAYLOAD_SHA256 = "b8e265e8641d91cc85927ac4aa06b70c45325844ab637325ac0ea4a2fcd464a5"


def _ddl_statements() -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(_DDL_PAYLOAD_B85)).decode("utf-8")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != _DDL_PAYLOAD_SHA256:
        raise RuntimeError("frozen FAERS002 migration DDL payload identity drift")
    statements = json.loads(raw)
    if not isinstance(statements, list) or len(statements) != len(_CREATE_ORDER) + 1:
        raise RuntimeError("frozen FAERS002 migration DDL inventory drift")
    if not all(isinstance(statement, str) for statement in statements):
        raise RuntimeError("frozen FAERS002 migration DDL must contain only SQL strings")
    return tuple(statements)


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _ddl_statements():
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    for name in reversed(_CREATE_ORDER):
        connection.exec_driver_sql(f'DROP TABLE medevidence."{name}"')
    connection.exec_driver_sql(
        "ALTER TABLE medevidence.m1b_snapshot_artifacts "
        "DROP CONSTRAINT ck_member_termination, "
        "ADD CONSTRAINT ck_member_termination CHECK (termination_reason IN "
        "('complete_response','payload_limit','stream_error','deadline_exceeded'))"
    )
