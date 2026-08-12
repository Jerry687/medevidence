"""Add the frozen M1B base and DailyMed metadata tables.

Revision ID: m1bdm002001
Revises: m1a003b0001
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

import sqlalchemy as sa
from alembic import op

revision = "m1bdm002001"
down_revision = "m1a003b0001"
branch_labels = None
depends_on = None

TABLE_ORDER = (
    "m1b_artifacts",
    "m1b_artifact_lineage",
    "m1b_acquisitions",
    "m1b_source_outcomes",
    "m1b_snapshots",
    "m1b_snapshot_artifacts",
    "m1b_runs",
    "m1b_run_sources",
    "m1b_reports",
    "m1b_report_sections",
    "m1b_report_source_outcomes",
    "m1b_dailymed_selection_decisions",
    "m1b_dailymed_label_versions",
    "m1b_dailymed_sections",
    "m1b_dailymed_label_supersession",
)
_CREATE_ORDER = (
    "m1b_artifacts",
    "m1b_artifact_lineage",
    "m1b_runs",
    "m1b_acquisitions",
    "m1b_snapshots",
    "m1b_source_outcomes",
    "m1b_snapshot_artifacts",
    "m1b_run_sources",
    "m1b_reports",
    "m1b_report_sections",
    "m1b_report_source_outcomes",
    "m1b_dailymed_selection_decisions",
    "m1b_dailymed_label_versions",
    "m1b_dailymed_sections",
    "m1b_dailymed_label_supersession",
)

# Frozen PostgreSQL CREATE TABLE statements are embedded instead of importing
# mutable application metadata. The digest makes accidental migration drift
# fail at import before any DDL is executed.
_DDL_PAYLOAD_B85 = (
    "c-rk94RhPJ^{;Tf-buP+8z*bKHW&KNNz~SBVt0<Su8UJ1O+hwmid0F;iMMXQefTB-K7b%4CEjkkc9w+4hllqb-WM"
    "L&H=kS-&(7vY=kwtF=;@1jutE!Tn=Me0qR&?kFXN<YvSpGsbuhgsE*kMQ&KAM>{BP&M$tnK#^@|r_pbg(-1qe`=n"
    "<_=|ngBLgSwJvpSv06<;_IZohQ=@N8Wh*rKTz=W_`Bm1a~Q86OXB8kji84slqXGgixD(sm0Y1XPcBgolA2zlRTAH"
    "#s<shYp`<~JIBDWdlLqI<FXyk$k6!*5{B(T&J^dQ|{q$tsSzfi?)PjN9Z|Yo}h;^Pd%J*ldC$G-Wj>xLlH?c0DAJ"
    "2|o9-aLh{4oDHm@0yrbspXPrawx>)e41i{`JZ6UtZ4@Oav$lObLd8DzENbsX=Be#TOT4QJ^a-j^Nq%^JhN<(^j^J"
    "QE=daP0EwWk)uhklPb<pan)Q;VTsQU4}znU=Rw_6>$0{0h4aY;{@-L4`2bHIOF)a3{o&ui<jtGMY0*^q<F{`o6gE"
    "f8#)k6Y?8)Ke0fVcut7|X79x5L^@F8>h%kK|n(~FDGf5-pge`eDMzkfQLI3A0Vs!HzSro=y2S#dRGf5;DX#7@v;M"
    "*q)4+C;_T`Z`%lh0%-!ru!E>`smBA9=|#G?3?7X<=cOL^~JwFop@}4Y!P>iQ)dfgzy<(uw|LWJfzp_g`M!}Dp<Tq"
    "yg8ay>K^XMyWpgrWG`5?PqUfKw!$K|&m~(DJ;gATU&QBbUWsR7V@p9{#IYT`(Tvr#a<kODuq6r0L`?2*X$FHQbQA"
    "dPdF^8wRaSx79g6V`mlhie8CZYJcN{VcW>Si)yHioi=;KR6P!ReXdC+Iw5&~fr+GltY$H@0%tg*z54hIF!LgA{@;"
    "%Tp0FUW`$@A(Q!7j<IwwQ?es!OrtV_D2H_!8kqEmdgx?En54~pQQ&_ricdn{Xgkic0$~@)f^IwuLDds`r`K7&=mX"
    "+-t>Lj4FRMjXBst!~=kxF8XM;myPBLSYom%@iM*s!O`cOA!7IPb+Gn)~NzSWT~K2EBE&J>C*<1xfy1G5MAQWv!Nz"
    "N-^h=S&R<16AJEEg*n6P68_xKxjWSpNhQw#-FtMIs*>M0!%G*<^lq^z=0>qmoZvgNkqWTd2-n0Qy2I02I7qB3BEl"
    "&n;(C7LZksQM|(tm)oovJHve{hHa~ebf8|QN2RWPI^dxvbe=)~4<_xE!XUEUZ$xp9;e14?-)VE-Ddv@0gD4O~}M-"
    "%V)Vs(SEg>)6)2O6ops)2VHuuBcG@yt_0RGI-JyiY~?!0b|;(g#s79&CLag##nKomwWCkGoYnzKV~cgS+IQ;V3)F"
    "<y2EOEw$`~VP*;m2V>nt6AYL96GSbh)6z~5@v!W(gWO0$HTLKkD9E3F-WU)@TFP0bYObE|8<A`$>xbgmu1KKB)Sq"
    "c;RICXELOV<zCTc?*DqoCx0Kk}Drsx1>g}^^|t2PBcB*C97=~sn*+u(ItM(ec1k+)^6Nt#W)%TtKeI!7MQ`DT3G1"
    "cow1OIjFXta%7|Am%KRiAT#aYX(4{;|$_Pjep}h$Cru~Zh@{UtS{u_GRboMVdh5LWGg&-vRad51XXR>*<hd0B&?v"
    "FF`T~WLK;vINPpX8HFX!_1g`xh&RC7Xau%lmy3_fjY0zqI!(-QGjTFamA2fnBy-I8+fUV5&^0MX*g252gon>0|9;"
    "F*f*19T}Sj_fKRo%<2qlsNV*VA}zFDNSrM3qHs4fc(0jrHbo#r6f>40kKOFEFLVHdDJg^P8d-C!eMLflgGTq)M*|"
    "cGTd%o>(a<LWVm1*zhw#$&Q2M9ZkMHnxDOjUp{;q%W3A%<G((f_)Wf}ov-VdCpY<a<x@gC`RV-pr}_LOU<Y{*57^"
    "(9IZ~j6E&#!k=ueLFw@S<<cHmiY)f!}K4@5YNLsV%!!a&!~5SrKk5*92B#D*S3m7;k2rccf^lvMPd#6cc}ehlIW5"
    "j-(5OMWi;tVKR(4o;_}F{UK?@nN@1%od*9w^jsA%v$=%;~Q6U$f866=#|fT2McwPtn2Gi^y;`g<UNWa1l4;8GDKd"
    "{cPdh$rpnOmh)AF)P}-E0%e#;9|E(l7=dZBJs`~O#RaM(VEWhxfMY7}Ap+jV^cQK5jP-+Y@h#86zP*Dm1@A;jxE^"
    "q82kSpyPj6M2NXPrvRE%r~!R^`8zr`=7>wNhm)wDZN<c2c|>yPS?<N=kRK6T$#mxqrSXLV*p*au9bU`j6wxxZVDH"
    "yQzW3e-AFsnY6Y^h@)0hVmCl)uy&9N)tkI=0IZVtEP#qhmm?N1Hn|ph3FsP6=Nhk2iWlw1aF>_Kf;Mi}mY!P-)|5"
    "?>$2CS*Skc`kdA5l864P>1G!{Tgbu9BK3l!0+l+;y%r>Cbc=0_*SI4SXLDx{zGze}ouWDaS$z{~mbtJ9OGyYSe?#"
    "?k$@xq(2(D~5NUt_#dN$<ig6IAD^9rl$6XhN_2}UeD-!c*0GZBE;%(LfH7@D#6pE8Yk*jkfMw!R0oDy=p=VwX(6!"
    "1#n`G9-trhJf#XF%8yaBPfn!r7xA=2%nWHYCo4JfzlDiu7B1sa>`MZ1SFnY);<+?4QB9?sX5M)6X9k?kKGHL50n%"
    "qf&UPz75B)4p|O!68zQS<F<)v-v{aHFZR)wLr77k))PcIs6j^3x#AH1SsI;f&*UNX-0eT^5(Lm8M)yH5)aHCbWT?"
    "iQ6QxJzHsYQl*({0z=Lkw0T>+KE+`Vv6py73t3$UU680qJ)~rQ`S20_+qxiQT#gC{q>qb=7T|z%JdeJ3^!3**tnP"
    "($*sl)wp_}eo^io<&Ff3L8oUfoqm;FkaAaA1%H=_>!A}hxtCy$~(9>95;bQ(J<3mN!)YcVpv@NlBaEb{1JPgN#!9"
    "`DkUb1L6e0ujgP`~gg3#r$dw!I`-3xOTZk-nwf_MyIVZP!ctUAq<4;94@vf)xVL*_fw7RTp`>dryE^Gbmw(>R^0U"
    "6XtXq4_uW-27k6!l1ZOEC1|tlqP*TGw$92=J+enVCf-mi|M%C?yy@oijommQJg;tlSf|>%nDsFg(+8hii6H(;jw%"
    "Z;y+3>B^S1eNQDzLTI*V%eZ<<jF~7vm*8x*9iww6%P5X>;oLBf>!2CSlOs5pboN3w-y-+YGUB49mYBMhC8ks3q9)"
    "a$<{3;e<d6m<z4Vg+!}s>>3eGQ&}9CXRD0#Th$GIVilvRDl6IzlPpMAAeJ-Fj-CAAGbprZa*F`cB7iLC9IBb)lW3"
    "N&J#1HhmT^9hfxrCb8}~x=4oIlS?tlGG-EMEvIqY$#Nf)TAcN$&q*IfZcYl^0SE!y3$U3ChpD7Rk;y-(}05Z@m8|"
    "C*M3?lP$MZnJ*4Kl>hcg%9at<u0|ioz-!DFHZ_uUUD6D5C=i)PfBE|1i-%Kda(0UF2NCNS`ToQ=RZ)72jr|;Ds~y"
    "$5UfNx()k&piY7J6QA*ln`O6+!F{utfgdSQieh1Y}wq7Grhl<x_o~3s%PSt-Zc%|R+*Il$OE0JijFN4n``C~napI"
    "xufd-6OjD#Q8SxQ1<?JGU&@v*n_|KH==r_lRJdeS5ISKGxO{-Qo%rdWJIVdql`qX)-ruZtn``I2Kj1Y{=zRMc#Vz"
    "c@#`25Yu@DEDG#rAL<m{x1DGr9{#oyftZxERjvt%hk=cOhU6s!HSu?tNUoo?1dno$BLbg+)`AqmmHzr(!!V}6WOt"
    "N&a%&+aFVloHnE7via@GU-$+7mKWe{v9990=j?<5}WH4B~Ng%+&{!&DwQCL_*Go5;xTLKTlVftGHReZZM=Lu$aAi"
    "k;;u&Q*M5uPx#yz0BXT!=2>nsv;NJ*^|r%b6*@MoA+6sCDonn;8&-7VClhlm<t*_SyZ)T7EQ{_U-3f|AFOI&W2_x"
    "ocCfOqkR4IXk<+6Hmk&I)A9De<NR5m&{JNKXY)emfmcF++wQ#dahmXUL`gHu-(U={%$H~{yB>f(!j}MV;AaAcp_k"
    "~SuPG&y0D>C_C@4C6;WY$?iH}}ujId;3drFm!R51AYr?yPPj1Mzj2yWH6`-+xjzpgZ5U8`9b1=<3x>lVXuA67v2="
    ")WkjKarX47W&dSTXSL%cqFOspW$yxHnWwWwpJ%*ry9VuCOpfD~5o7lH__;Z-&f7AndOD|Kgv%E#1V6!t!B!|Csr7"
    "P`$BS%*3Z|G4q^OwKChV`M5KUhU&rrSEgmoa7LV3J^Ra3b>wRH8HF0z{TRo%7y*f2T(u=g+&c&6{%SSprr6s75w1"
    "X9nhjiD-e*C}NHART%P81Nk1fU%roTeldvCOuGDtfUdvgA~OUgR!gfAXr0-lnat1JC{~35>2pR^r51~7WISN<=An"
    "1%s#0a9f@e-+OA#3>W1z^^Gx5`hlXIVKrA+PuYua|zP9m&aZOvSuYHhZ>~K=yb)k3k)e>1ne<{k=5LpW4>MSzUkQ"
    "3=qN;F{**uF_)&tJxDiB%#TFCrDflvZT#&ohW4sXXiLt-+LE3qkZ|VhfxIL>$0iIO2d;f)WoXz3;h~1I)9FrVHKS"
    "AMyrmpat4sj2S8PKGm|xcy#8cwR&xL3ZK7pmcx3P;gHolOfdpi`>-0m+JMYZ#0Dp#5i5WhlQ;pj$ixb%H=?wA%O0"
    "CRohdfX0!!wt6kKGcff*+`htzr{<|8eqq`ai$Cn2|VU=XOQ34()#(h-Pe-yvyuTZMxmcEAd3F_#Db*NFXT1O?MPN"
    ";G+M@rkM$7oWVHJbp~&WeoyE&L-@1Uk2Ew7I7C8KATfr!_YQ<YrGo<N|FQwU?Hq`p`mOcsA0D3NU~&KQ9NE1l&bG"
    "FxVK!Y-YVqpVAL1|uCb-MPX$4UJ#?kH-g&+icMO{~NQoS(V=;wc$Nq&@qZisOU1%|Hq06RuDXuD#kJ*I1uaY}GQ5"
    "B{|d+7jN8xuuX^Q>G&V=F3l3$>lQ?9~mPfp;;16rkmjWPi6PCVCc-)$>yG<}%OfYhwEKf!=x_CabUGXyC1Myp1GB"
    "f!pXrE2()mxn}cF0vT}w#(z{s;&OTj6AeG4x1ch~(vY(+eeF8!Y<)GrzQ@-k*<tMq>J?HB5BeV7(TxBFqp70uTCV"
    ";xErTRfQ77SqR5kG@b}{{?DBl&6naz!hi9qLMu>QXFJ&!r@QyYLjn&B~fKip83S@@{zsx|MLWliq-?`;^^+1UG4j"
    "%Ct-hKt;zU^Ok<J30seDi*Hc4{H_ScBX;mN0*gt!wRsG=Eu?vWc+OF3Q`aV_6#v!a+c*1^Q3OC9|?hr%9@byVLQ}"
    "^Q#FaL1`KN?0+y#)sjb|J%X(SEmMy0o-3_a7f^FlmK2>i1K8EvY#`C*lZu~gjTI$g&+iwh8Z`OEDR8w^v>rU1co+"
    "QOc$}0A9E#&1k-q7;Cu+p$%-X!ieo;V=Db6gmg)_7t7>WwGHpw=f~jG3(_#;|#yKi+SsvUT|mm;5l0Ra#c7xml0)"
    "AmmY$FJ<GVgS01y<49wi*6yfIO(j!HayB*Vg@NjOJ$eR$DsR1lhNZ57qpG%n0II%ewP}ba>S2b9FTHTKQyCBbfZ$"
    "3)1bZ2ngGV3&lTRR!$t(M7o0d}DunM~zk4wY%;?}pUbde3ZNnI;)?8^JO9<wvXQ2aJwv}k<jRPnG!r$a!A!>;E3P"
    "rPDAC=gU^--7FH6&%{mA-I3<Zv|e&a&P|wjQ$@L"
)
_DDL_PAYLOAD_SHA256 = "f1cf2ff8da12563a73b205ff6e2f2344d13fc976b2b44af406f1979e377f044f"


def _ddl_statements() -> tuple[str, ...]:
    raw = zlib.decompress(base64.b85decode(_DDL_PAYLOAD_B85)).decode("utf-8")
    encoded = raw.encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != _DDL_PAYLOAD_SHA256:
        raise RuntimeError("frozen DM002 migration DDL payload identity drift")
    statements = json.loads(raw)
    if not isinstance(statements, list) or len(statements) != len(_CREATE_ORDER):
        raise RuntimeError("frozen DM002 migration DDL inventory drift")
    if not all(isinstance(statement, str) for statement in statements):
        raise RuntimeError("frozen DM002 migration DDL must contain only SQL strings")
    return tuple(statements)


def upgrade() -> None:
    for statement in _ddl_statements():
        op.execute(sa.text(statement))


def downgrade() -> None:
    for name in reversed(_CREATE_ORDER):
        op.execute(sa.text(f'DROP TABLE medevidence."{name}"'))
