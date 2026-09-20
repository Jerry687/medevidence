"""Add the immutable V2 provider framing fact and decision surface."""

# ruff: noqa: E501  # Immutable generated SQL snapshot and DDL remain byte-exact.

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import Final

from alembic import op

revision = "m3providerframing002"
down_revision = "m3providerattempt001"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_provider_attempt_events",)
_TABLE: Final = "medevidence.m3_provider_attempt_events"
_V1_START_BINDING_COLUMNS: Final = (
    "event_id, event_kind, provider_run_id, case_ordinal, attempt_ordinal, "
    "configuration_hash, request_hash"
)
_V1_START_REFERENCE_COLUMNS: Final = (
    "start_event_id, start_event_kind, provider_run_id, case_ordinal, attempt_ordinal, "
    "configuration_hash, request_hash"
)
_V2_START_BINDING_COLUMNS: Final = (
    "event_id, event_kind, schema_version, provider_run_id, case_ordinal, attempt_ordinal, "
    "configuration_hash, request_hash"
)
_V2_START_REFERENCE_COLUMNS: Final = (
    "start_event_id, start_event_kind, schema_version, provider_run_id, case_ordinal, "
    "attempt_ordinal, configuration_hash, request_hash"
)
_CONTRACT_SNAPSHOT_SHA256: Final = (
    "656724de18a35eb3000a4fc966ac4578e496661c0b2d71101c20facf29f04687"
)
_CONTRACT_SNAPSHOT_B85: Final[str] = (
    "c-rk<3vb&v68<Y*qk!aY(nN13*X$vey4c{-q)6TFEs|7FWV+VYk$tk9ZLaSA_9G?hL5Y+|(atu7fQ2@-XFh!-N1P$W8Gr4%jz9A~"
    "*O}TQ;Cc&h=G*QBxSzX+U0Ie#-eNvmcp?0_b9&y9B{u*g;D;WR2kvAh?MUF>gP*v-o`YcFEyC#UvExmb0g!r~(|4WW<@-VB`21C8"
    "5{7eo5jx>=(fQY4_}gG`-ck1VqwkD^15DPL&x6@L7}*oxj6h)f&K+1FiSvtL=hf-E;pzFwu=D!z;!WrH^78oiE6JVt@aEwzBrqF!"
    "{wK&S`DhCKPvIo@LHIBS@SkDe_=_<J@;YC31MuG^ScJRYNV+*Zymtb3;sjSWbXv9-^-1_Z<|j*c+HRt_8!PTciieAdqZ;O+v|2?B"
    "fE<4yL!S2_2<>nt%hJ_#x7fDp?oRe$+&b(d)V}D0QVXL`^KHED-blS2>HY9^U+Td>Cg2PFf7IA<;M_qK8=(e{8`iWFH4`<`L+xAZ"
    "?k2iPQw{CF)W+8S!Po&K-8xY8QQuL=qmgDQ3ecRs-XGt(BiD7b@z^jF#ng?lZo1$=9h;^Gq==b63+|k$_dgE%C=F!}W8H0b(n<Ec"
    "GhMFX-k+V(#N&=<6h=c*Bbp2rD~~VsdKlrrkVK>B?H)ar@To@69l*Yx-7Y{7*>X+}2Z;N2u?)rze5%V3g`TJth)7}r<u=nn7(}98"
    "E`NPH8$H00xSLNw;Tve0OE{TD0=Ew#fKp38#6$w;PdlCE%Gl`ZNPXfgCZ%rzFm*!j9!`%=SpL=tLT_ApvIs-H9tkA7APXb7M9Krx"
    "5uqW;^X&QaWymsVB@c0=z%*IOC&%vwo!@?iGyCRz#}L8E(%0*54)eN;n4DZ3pAFuf4CHWT|FM|)d5_gQJPg5?a7Xf&)2Y;3tt2@0"
    "C4CU}B*Z}9!H;vUi2|IHC<A|kYzJqs<q=D=O;K>k!bI+v6;t3a86pb#X`;Z9g)4FMb3qMiUX%qhnm*VtBhgCCY^tb1%mj&e;x<Wq"
    "xG7k5a{~DWV%D7?V6LPJ2oogYrM@S%`-MH7{Rx|M3(bE-0k6@jzEhrA9e!Sxh)SHiDX2tQDk|=2Dj;z|Dqh(qRA82ciMSM}O#!Az"
    "Q)bcgSG{sL+Us0gcCgh5@>t?45)=-uXAJBq&6X#Tn5ko0c^-dtq>ooW?f!N1^E0U`=z?_X!>YUxHMGhLRYgxEFh;RL6qOgL2s83x"
    "<$$XQLWroaK5EyB?OJh5Yehm7O&*9$H5rOXl`RsEBEd=%i08{R5UiA4&z5VS=DN!uKu-_y=U*X+L>hO5?gWAJU=yMT%9<CuPtj_a"
    "0I^ju5iYhkCa~P98G|C&Y9$_RX^ny6re29hSbAqr-?r#_F{gnW5Xr6NNJ+h#N4H%Tw#&kHS=cTM+ht+9EPNWv!iv=t@(l1{hjICi"
    "<oWSmg|#1Xfra!OINp8;6%&Bbaz6E3_&pVjx)8(g+{x1a3=rboavFMYGOlG;iI-Rn{B!9qmh<^62muW#zo?5)l6Vu121H0v>sw1P"
    "igckCFVhZGRnshWUo-oLZdpcu-@;JHAio^Rt`oo}!~2F0ED`I^HS%~sS|^>4IBBxfXp*Kt3Kt7qDp&0a6c$g(sKn#T*IP&XxOMRK"
    "9iMK#C)qTq{mQ0J>g9swCSDv??aUMgYW+;H?A26gR`1?0D3<qg$V%}x8;2q0%#i#vzdTaZe!<WgU%X-)Q+zgFn22x!@tQ7)ycpni"
    "5RD%8CM|VlF<2CAuplWt_}`I&cSyb7m2#8b9*xk<4MAdmZ0fz2M}6f$Wqk3C?iX!rc6R@|dHzf)&Q%Nusu*LHm$53$SQBHc@iNwg"
    "8S7$<bza80Fk?fEvBAsO5N2$OF*bP_o5GAOF~$}zV@sHEUyN~|mvNuQxJRX2KI+5ap70<_&^cjX0<H<iVRcNH7Oz_>D%T8K>0X>>"
    "hU=>$Tva}<svuWQgsaBKRTJc@i*VKXxaxvj4H2#eA6G+=t0}_O<l|}za<xRbT6|nBL9Trfu6;hP4IEAJm?(#v$*;EsolFi&z{TWI"
    "SRG7Ghu6K}sx<>uxDTgE<+au3EL9$sst`-9IZKU)r6$BuZ_ZNZVW|tTG@7$Ccvu=jEY0RDO&*q}5KF5$ON)o4CB(AdoMoSfC5OYP"
    "Ocr498q~ekhOUE#*T8>Jq3WCnO_9};ROnL%vFeVD_C|$J1xc&iq*Za!njmS7o3tiQS{Ed(bCcG^NgINs4Q|qgIB8Rmw8>4{6en#7"
    "lD4=>TjHeqf~5Q0q&b`yEpv^*Z;@W|HFQ}7s0QAOgi`0I2s*4jimXZ*E6RNsZHuI>HfO2wuvCRuYRy?{JS;UKmU?rRIuA=-h^5h-"
    "rNP6}5MpUIXKC`VG=*4N%~@JJEG;3H{pKwDJS^)RMmqC0c;CIV-}||-zAC7%3F_;D`i7vsDX4D=>i0SIOD~oLv{fN(O-Nf8(l&&&"
    "O(AVdNSk-O3p>4ybyWdfO+Z%{&@}{fO#xj?K$mrVtM*^S08~)`O%y;E1u#SbOi=(!6oAzZC~KU?x~hP#CZMYe=o$jLrhu*`pc{`b"
    "i~u#&GW%IH*Z2gkTt0%kT4lLpoX0|c*~fFoXvx6XiQg!Hi*OQnaQ=#e3VsBrhR8Yvc?&f1uZU|%L}||(q(FV&K;co&x85Kb(k2px"
    "2R+BTf<lk;pt#)7kdF3auIZ_7eu$U9C~J%??<0nh`KTyd=eXqk)s?b)aC5Z}FVB1H;t6uTAOq70GUXszqw?w<K|NNwCl_aD$HPJA"
    "x_ffneR(7i@>(QZsMjlGsU`>IBa_L}H)xiUmC35Ily-bJHa-luIXt}eK6!o^k72Yqk`5nNYKPo>s^ogysVLbKpJt)OK(}Gw-O0?a"
    "W6?PEj?$#Is3+2Gc4<dKX=aQtX~R;mx+i5bJzbF`#Xql>K;kEk(yJAFSFlsl%)Yu_t$;}zk%7g%n$Hz1_iSCVklZNRXw;*50J@)I"
    "I7PP3cZ}3vKkg+dkA;u^5fublfbeJ;j(7XTS_6fYNs^7`_b?0Tebl-@#mXq&Vu8Y)`WlVvbS+lkNKmnrI^?qEufyTnJ>`WWHMyhO"
    "@O~=q-7vE*R(B%ja2M)4DJC{(WXfsfskB#iGQ#!h`GQfU98iwb!h8lODSBYe#f^KJAsf0rFSx4OXQ{2F5>eS3TXIcKyhVzp>{}|{"
    "h!W)M<0wY2t@BwTN3T#-7>20AfJCl&g=IS9B|`Hrx@G)pWFYIBDk%7JcE>kgP5s-mLSK`Mi()U(bLL-?E}8zmiWfPXf^k?@+fm>|"
    "EbU2{XzHHaNgyAnJ!CiK8x}HgGoN-SF)5TAoW49tYOj?=eu6Uc$Gz3wv(?_-O8&Uo>s?>J_^Rxv-{ig3vtF-S5sF`Z+`D;x^`dhV"
    "$<xK3ujS?A_y1X)oL!v!`}+FX>g3{$f-Wk$Xy~G&i-9gCx>)GaN0$S5IbWT<9V+OeqKk$uI=UF>Vxo(ME`4-4SizxQy}dl|$yc2h"
    "H_u_iBC@@I7O0Y|%#v&Sq(!-);%=hIUhrx=#cj}YQBj^El_6KV$PZKn3T}L)DipN3gv^r#=GwPXH#ir66sNSL#L>E_9?ge3_l`Gp"
    "Zl}QZXQAy*9Y}fXf&3g-m_JJ>l({z5&(DImCf+Bh0&$)zYvN*<3no{F!2_vc2Sv`$b-_H0N_GU`58#%|Ydo<Ysq(uly~WtHT7O)3"
    "FM_kz%BEd1a&V90kIx>Bt@Lhqd^wa#Wjx8k&=PXdBwnWsZw?58Szx275x1#YK9_@&iw}d#-&rYnFv1FgC9+8yE|vY+pT6ykLsYK;"
    "k>#h#e+$Nz4F{KRPS20em^*t3pS8teo1M)|DF9*c5Y2`0oUn=BEn#knd$iqxRzr4fPTxcW$iQ1_#Rxc~spkV5d~pF}J=#PI%Ai}b"
    "A1L83fQ=XI5wxEI=C-+qvza}0f=^(h>@(CY@h_H@q>)dZM=kdv;+BXz%W#5j6Yon!buTw#_GI8KwIW$Z*lF0bffkfOw`DwzKk`N}"
    "kl*B!TL#?{`^x&M8)!&Peb%kCDeAD;aHIIdhtxONq$>DAkjb)+qSd=)o2lZ>=BlL_BXYGNFy4lL<2nY;9(+C+Y#Wyh)u2)y5lF7s"
    "_N=V^SXg#cR)4H6`bc<RK%~mCGn{)rA_`UAeS8(|vX_k;0IM0-MsFzi7$n2WIBras^`_tSZO>!YEUf7f;!i{1Nb$r??to^mNaU&$"
    "7A!voR`JsuDHhwt2;1{6Q_HqizK*Fu<=?4%dR9n#Fw?EPM{C1l+aLSp9K{C3x=0nRb1FBm5Bj^yCq5($gA|`X$ezvgC`Te<r@zXA"
    "f;uuE)P&R5@&+Q-s53SfnPzYeBhUr_We1!CX&QBA5Z`gUnUNHTG#i1?I!h?JYzjjixxX)>EO%<dSh8_zzK19>BhME<<{JHjMvjCQ"
    "3dM{WUc+ediP#w}PE4rS=~>h^UZjK~Syy3qXv4?vIDCxz+8#NflSGhl<hUbA`0s(mfh8I{`o`%G7&a#V#ExxlU=uU<5fQrarsn#e"
    "cJT)U*HBMjuM?WF<B#AfWdoa?=?COVsrlw-(#=Fzv8~YL-{l;MO>B-P#A)Dv=WgkGHlk4z-91HNVgMFV!_do(EED3%?xv<bH<_l^"
    "({<C`)%E-MNYC>V%^!WYwEznH^3Dm}$!0fSi!(-)QY*L-o7YRfd$Pgyqb?PmT6q1qyAN$7%^69@DWLfjFnj6e-=3%2v2r1>r5$`k"
    "UDzHRXb%pw2M5}N1MR_q_TWH!aG*Un&>kFU<JHGGI6&#HL@Apgx;xz{_i!8lVBf2DeAagkgVAVK=^l3Fg*yRvPED5o8_j-udGX=&"
    ")!@=T9u5a@-VW`-hr#*K{;;-)ZRK<QO}SZ*n(6as2|16IJM(yXE{~en@o4!MZLVaSE7|5swz-mRu4J1l+2%^Nxsq+JWSc9w?Oe%d"
    "d7n#^Ojf<+tvu|Ta)B;FsTAx}dbu3N5-{<ay>No2qB1q1?r#)T6Cp}vdTJ|S6J#ir9_z%*zg%A-T>SN6f@tOMP7>s4KlMfL1+=+9"
    "=`yqpnMiqHIwBZJn(_df6p%_JVN#wyUs6OUdsrpAB2{LL0cdZVD0@G(0$4r0+AXsp2!lwW^e4ksR(@az`@{LKH(u+CmW`d!re?tu"
    "wFyTZliz{EcG9{#-FwCM?(UYMbL*k9rFHvW?0a5HyeHYtAngp&&LBV93=#(i6`@M8NP1b6tzu_ckGW(g;g&TuJL@$FEiP5<B*-w9"
    "?WAf_>UI+4zrVtry&m?m<z8J+Xz{Bn+~c&~qV*Q7xA?)lMfcnP0Z$M00{"
)

_COLUMN_DDL: Final = (
    "approved_header_names_identity varchar(128)",
    "normalized_header_names varchar(64)[]",
    "normalized_content_encoding_values varchar(8192)[]",
    "normalized_content_length_values varchar(8192)[]",
    "normalized_content_type_values varchar(8192)[]",
    "normalized_transfer_encoding_values varchar(8192)[]",
    "normalized_x_request_id_values varchar(8192)[]",
    "normalized_header_facts_identity varchar(128)",
    "raw_header_field_count bigint",
    "framing_contract_identity varchar(128)",
    "framing_input_identity varchar(128)",
    "http_version_state varchar(16)",
    "observed_http_version varchar(16)",
    "header_surface_state varchar(16)",
    "content_length_state varchar(16)",
    "content_length_value bigint",
    "transfer_encoding_state varchar(16)",
    "content_encoding_state varchar(16)",
    "content_type_state varchar(16)",
    "actual_body_byte_count bigint",
    "raw_evidence_state varchar(16)",
    "raw_body_hash char(71)",
    "raw_relative_path varchar(1024)",
    "raw_artifact_identity varchar(128)",
    "framing_status varchar(32)",
    "accepted_framing_class varchar(32)",
    "framing_rejection_code varchar(64)",
)

_V1_SHAPE_PREDICATE: Final = (
    "(event_kind='START' AND disposition='started' AND completed_at_utc IS NULL "
    "AND http_status IS NULL AND error_code IS NULL AND credential_echo=false "
    "AND body_complete IS NULL AND body_byte_count IS NULL AND body_hash IS NULL "
    "AND body_relative_path IS NULL AND observed_body_bytes_lower_bound IS NULL) OR "
    "(event_kind='RECOVERY' AND disposition='interrupted_unknown_after_start' "
    "AND completed_at_utc IS NOT NULL AND http_status IS NULL "
    "AND error_code='interrupted_unknown_after_start' AND credential_echo=false "
    "AND body_complete IS NULL AND body_byte_count IS NULL AND body_hash IS NULL "
    "AND body_relative_path IS NULL AND observed_body_bytes_lower_bound IS NULL) OR "
    "(event_kind='TERMINAL' AND completed_at_utc IS NOT NULL AND disposition IN "
    "('success','retryable_status','transport_unavailable','deadline_exceeded',"
    "'response_invalid','response_too_large','credential_echo','authentication_failed',"
    "'provider_rejected','candidate_invalid','evidence_persistence_failure') AND ((disposition='success' AND error_code IS NULL) "
    "OR (disposition<>'success' AND error_code=disposition)) AND ((credential_echo=true "
    "AND disposition='credential_echo' AND body_hash IS NULL AND body_relative_path IS NULL) "
    "OR (credential_echo=false AND ((body_hash IS NOT NULL AND body_relative_path IS NOT NULL "
    "AND body_complete=true AND body_byte_count IS NOT NULL "
    "AND observed_body_bytes_lower_bound=body_byte_count) OR "
    "(body_hash IS NULL AND body_relative_path IS NULL)))))"
)
_V2_SHAPE_PREDICATE: Final = _V1_SHAPE_PREDICATE.replace(
    "'provider_rejected','candidate_invalid','evidence_persistence_failure')",
    "'provider_rejected','candidate_invalid','evidence_persistence_failure','validation_internal_failure')",
)
_VERSIONED_SHAPE_PREDICATE: Final = (
    "((schema_version IS NOT DISTINCT FROM 'M3_PROVIDER_ATTEMPT_EVENT_V1' AND "
    f"({_V1_SHAPE_PREDICATE})) OR "
    "(schema_version IS NOT DISTINCT FROM 'M3_PROVIDER_ATTEMPT_EVENT_V2' AND "
    f"({_V2_SHAPE_PREDICATE}))) IS TRUE"
)


def _contract_snapshot() -> dict[str, str]:
    raw = zlib.decompress(base64.b85decode(_CONTRACT_SNAPSHOT_B85))
    if hashlib.sha256(raw).hexdigest() != _CONTRACT_SNAPSHOT_SHA256:
        raise RuntimeError("provider framing contract snapshot hash drift")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "canonical_decision_check",
        "fact_free_v2_event_predicate",
        "v1_immutability_predicate",
        "v2_facts_absent_predicate",
    }:
        raise RuntimeError("provider framing contract snapshot shape drift")
    return {str(key): str(item) for key, item in value.items()}


def _upgrade_statements() -> tuple[str, ...]:
    snapshot = _contract_snapshot()
    add_columns = tuple(f"ALTER TABLE {_TABLE} ADD COLUMN {item}" for item in _COLUMN_DDL)
    return (
        *add_columns,
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT fk_m3_provider_attempt_event_start",
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT uq_m3_provider_attempt_event_start_binding",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT uq_m3_provider_attempt_event_start_binding UNIQUE ({_V2_START_BINDING_COLUMNS})",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT fk_m3_provider_attempt_event_start FOREIGN KEY ({_V2_START_REFERENCE_COLUMNS}) REFERENCES {_TABLE} ({_V2_START_BINDING_COLUMNS}) MATCH SIMPLE ON DELETE RESTRICT ON UPDATE RESTRICT",
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_schema",
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_shape",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_schema CHECK (schema_version IN ('M3_PROVIDER_ATTEMPT_EVENT_V1','M3_PROVIDER_ATTEMPT_EVENT_V2'))",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_shape CHECK ({_VERSIONED_SHAPE_PREDICATE})",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_v1_immutable CHECK ({snapshot['v1_immutability_predicate']})",
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_framing_v2 CHECK ((schema_version IS DISTINCT FROM 'M3_PROVIDER_ATTEMPT_EVENT_V2' OR ({snapshot['fact_free_v2_event_predicate']} OR (event_kind IS NOT DISTINCT FROM 'TERMINAL' AND {snapshot['canonical_decision_check']}))) IS TRUE)",
    )


def upgrade() -> None:
    for statement in _upgrade_statements():
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT fk_m3_provider_attempt_event_start"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT uq_m3_provider_attempt_event_start_binding"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_framing_v2"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_v1_immutable"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_shape"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_m3_provider_attempt_events_schema"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_schema CHECK (schema_version='M3_PROVIDER_ATTEMPT_EVENT_V1')"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_m3_provider_attempt_events_shape CHECK ({_V1_SHAPE_PREDICATE})"
    )
    for item in reversed(_COLUMN_DDL):
        connection.exec_driver_sql(f"ALTER TABLE {_TABLE} DROP COLUMN {item.split()[0]}")
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT uq_m3_provider_attempt_event_start_binding UNIQUE ({_V1_START_BINDING_COLUMNS})"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT fk_m3_provider_attempt_event_start FOREIGN KEY ({_V1_START_REFERENCE_COLUMNS}) REFERENCES {_TABLE} ({_V1_START_BINDING_COLUMNS}) MATCH SIMPLE ON DELETE RESTRICT ON UPDATE RESTRICT"
    )
