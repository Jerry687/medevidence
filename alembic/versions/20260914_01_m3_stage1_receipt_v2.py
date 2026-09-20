"""Add immutable Stage-1 V2 receipts and permit canonical final V2 receipts."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from alembic import op

revision = "m3stage1receiptv2001"
down_revision = "m3providerframing002"
branch_labels = None
depends_on = None

TABLE_ORDER = ("m3_stage1_receipts",)
_UPGRADE_SHA256 = "327782452bafd96a4524c392dff46ce0e26ce3a23fdd3f3eca633c76b098b18b"
_UPGRADE_B85 = (
    "c-pm9+isgc5dD==R0)vcDv(Q)NO>T5+tAqHl69gqPFEOj>`iT;u(o7X>9-eyF*X-"
    "N9wJ%tE_>$8nc3m+bf9)HvH+{s9RxEvq6;>nu0uc1j>*EFvXRZ1=aPUrl=(b_wq^D}GmSfJsk(u|`Ay1^By=WpW*;1WT!s}7XPnX"
    "S{aMs@`#oiVc7wEA5R)BQ&>)OZpc^0x-D7gEcJ#K2b<-"
    "dg(vaT6<X#pItBw>wl0Hy!)|XVam=k_gEgDp#4Qr~13I2ibD@)Q^pIn9$TRA<ud^&1f*sYi6zh@_Jp9Bd^3!0`<8m4M3l!|OpLNI"
    "sJ;Aoj)&fi*_^+~jrTc^*P2glKa^9y^p`y^e<N<_a_=X=3MT(YZB6J6-"
    "Q)hwi9RDP!+x5re@?o%AN1HM)My=rMUswK+GxdeuZ!RU87hp<BB#x6yk9OZ#2o#VMY8Uix0!wJOLFLD8!G;VKN&!;t*tV8vnCaSg"
    "unz{bGrUW`>ArF>h$lMWg$9uut4u3ZSZZ0aEPwOi4y(x2+g_}8*l{_*k{)LU_K~h_Tfb=eXdpY&&5q!Thjq7~+6-"
    "~(Lh}fLWxdT}5qC2d1d+?y+n|KR9O#?w2eO3D%3|il^kby}C+-2Ny7(aHH{Mhy^y{lS}aEl&6%*IzLgwOw!gzwHk-_U>bQAV?USR"
    "{1H^z1e0*nFZYzahEGh#O`pdTO<CC9$>s_3`etd4E^*@n)Zr##Wbb=U<YlCalgYEVE(nSJP1J`_3T61=f}Jj)-"
    "y>s>@PlM*Cxmo>Yl%+O75IZ~Em-"
    "?0`(EJLVH{$OASLcRefmj9w%BfRF)ltSPdh_`eufYGGyZO|_=hwwC%DdhU?$rBA&VF=v0$mEa9uslx?n;6}fJd+_`pL%NAN"
)
_DOWNGRADE_SHA256 = "965ac55787fe3596be7d4a7090c4d51aeeae4d15493d2f24fdbd479357ed4f3d"
_DOWNGRADE_B85 = (
    "c-pm3(MrQW5d4)T2(jRaY1+~jd^nSU!I+eI^rgh(Ojdhn(vmy#BK6yiwn-53(n8;6cV>2HR)!l#3t;pv@F2$wE16-"
    "D;&pCwrNtXsyu=jcRx9JmpaJvZesLu}WG1xS6s-aNPCHTf#A51)4AOVrujDFSV=m75;rEV~TH*;ksOuh61Dt!$d4S9P#49XSt-"
    "3WIZN8*|?^5PRA&))B^B0USEpu?jNL}wH)`6-"
    "S_y+U2Gm!%`S8FjGPv)x|G85!A`I?M&7beiqh4Qm#d^PM8(;aE?sKyo<C+)(n7t@(|`M+tfHEfULc2l;w_EUeBfsy<GgyieP"
)


def _statements(encoded: str, expected_hash: str) -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(encoded))
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError("frozen V2 receipt DDL identity drift")
    result = json.loads(raw)
    if (
        not isinstance(result, list)
        or len(result) != 5
        or not all(isinstance(item, str) for item in result)
    ):
        raise RuntimeError("frozen V2 receipt DDL inventory drift")
    return tuple(result)


def upgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_UPGRADE_B85, _UPGRADE_SHA256):
        connection.exec_driver_sql(statement)


def downgrade() -> None:
    connection = op.get_bind()
    for statement in _statements(_DOWNGRADE_B85, _DOWNGRADE_SHA256):
        connection.exec_driver_sql(statement)
