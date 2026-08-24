import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import (
    get_session, current_email, _is_admin, compat_rerun, _is_xp_err,
)
from utils.ui import brl, pct_fmt, html_table, render_banner, render_css

render_css()

render_banner("Comissão PVT")

session = get_session()

# ── Acesso: admin ou IS_PVT = TRUE em qualquer período ───────────────────────
_user_email = current_email(session)
if not _is_admin(_user_email):
    _em = _user_email.replace("'", "''")
    try:
        _chk = session.sql(f"""
            SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE LOWER(EMAIL) = '{_em}' AND IS_PVT = TRUE LIMIT 1
        """).to_pandas()
        if _chk.empty:
            st.error("Acesso restrito à equipe de Pré Vendas Técnicas.")
            st.stop()
    except Exception as _ae:
        if _is_xp_err(_ae):
            compat_rerun()
        st.error("Não foi possível verificar o acesso.")
        st.stop()

# ── Parâmetros fixos do modelo PVT ────────────────────────────────────────────
_CLIFF_GERAL    = 0.80
_MULT_115_CLIFF = 0.90
_MULT_125_CLIFF = 1.00
_OTE_BASE       = 3_600.0
_POND_NMRR      = 0.60
_POND_OTR       = 0.40

from utils.connection import MESES_ABREV as _MESES_NOME
_TRIMESTRES = {"Q1": [1,2,3], "Q2": [4,5,6], "Q3": [7,8,9], "Q4": [10,11,12]}

_EQUIPE_ORDER = ["B2B Escritório", "B2B Construtora", "Farmer", "Ares"]

# ── Filtros ───────────────────────────────────────────────────────────────────
_c1, _c2, _ = st.columns([1, 1, 4])
_ano  = _c1.selectbox("Ano", list(range(datetime.date.today().year, 2024, -1)), key="_pvt_ano_")
_q_default = min((datetime.date.today().month - 1) // 3, 3)
_trim = _c2.selectbox("Trimestre", ["Q1", "Q2", "Q3", "Q4"],
                       index=_q_default, key="_pvt_trim_")

_meses     = _TRIMESTRES[_trim]
_meses_in  = ", ".join(str(m) for m in _meses)
_mes_lbls  = [_MESES_NOME[m] for m in _meses]

# ── Queries ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _load_fechamento_status(ano: int, meses_in: str) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        SELECT EQUIPE, MES, DATA_FECHAMENTO
        FROM SUPERSET.COMISSOES.FECHAMENTOS
        WHERE ANO = {ano} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
          AND EQUIPE IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Governo', 'B2G')
        ORDER BY MES, EQUIPE
    """).to_pandas()


@st.cache_data(ttl=600)
def _load_nmrr_real(ano: int, meses_in: str) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        WITH fechamentos_ativos AS (
            SELECT EQUIPE, MES, FECHAMENTO_ID
            FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
              AND EQUIPE IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
        ),
        deals_fechados AS (
            SELECT DISTINCT cf.EQUIPE, cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fechamentos_ativos fa
              ON fa.FECHAMENTO_ID = cf.FECHAMENTO_ID
             AND fa.EQUIPE = cf.EQUIPE AND fa.MES = cf.MES
            WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        ),
        nmrr_fechado AS (
            SELECT v.VERTICAL AS EQUIPE,
                   v.MES,
                   SUM(CASE WHEN v.VERTICAL = 'Farmer'
                            THEN COALESCE(v.MRR_EXPANSAO, 0)
                            ELSE COALESCE(v.NMRR, 0) END) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN deals_fechados d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                AND d.EQUIPE = v.VERTICAL
                AND d.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({meses_in})
            GROUP BY 1, v.MES
        ),
        deals_ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({meses_in})
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        ),
        nmrr_vivo AS (
            SELECT v.VERTICAL AS EQUIPE,
                   v.MES,
                   SUM(CASE WHEN v.VERTICAL = 'Farmer'
                            THEN COALESCE(v.MRR_EXPANSAO, 0)
                            ELSE COALESCE(v.NMRR, 0) END) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
            LEFT JOIN fechamentos_ativos fa
                ON fa.EQUIPE = v.VERTICAL
                AND fa.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({meses_in})
              AND v.VERTICAL IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
              AND fa.EQUIPE IS NULL
            GROUP BY 1, v.MES
        )
        SELECT EQUIPE, MES, SUM(VALOR) AS VALOR
        FROM (SELECT * FROM nmrr_fechado UNION ALL SELECT * FROM nmrr_vivo)
        GROUP BY EQUIPE, MES
    """).to_pandas()


@st.cache_data(ttl=600)
def _load_otr_real(ano: int, meses_in: str) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        WITH fechamentos_b2g AS (
            SELECT MES, FECHAMENTO_ID
            FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
              AND EQUIPE IN ('Governo', 'B2G')
        ),
        deals_fechados AS (
            SELECT DISTINCT cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fechamentos_b2g fb ON fb.FECHAMENTO_ID = cf.FECHAMENTO_ID AND fb.MES = cf.MES
            WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        ),
        otr_fechado AS (
            SELECT v.MES, SUM(COALESCE(v.BOOKING, 0)) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN deals_fechados d ON d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({meses_in})
              AND v.VERTICAL = 'B2G'
            GROUP BY v.MES
        ),
        deals_ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({meses_in})
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        ),
        otr_vivo AS (
            SELECT v.MES, SUM(COALESCE(v.BOOKING, 0)) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
            LEFT JOIN fechamentos_b2g fb ON fb.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({meses_in}) AND v.VERTICAL = 'B2G'
              AND fb.MES IS NULL
            GROUP BY v.MES
        )
        SELECT MES, SUM(VALOR) AS VALOR
        FROM (SELECT * FROM otr_fechado UNION ALL SELECT * FROM otr_vivo)
        GROUP BY MES
    """).to_pandas()


@st.cache_data(ttl=600)
def _load_nmrr_meta(ano: int, meses_in: str) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        SELECT m.EQUIPE, m.MES, SUM(COALESCE(m.META_NMRR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES
         AND p.IS_GESTOR = TRUE
        WHERE m.ANO = {ano} AND m.MES IN ({meses_in})
          AND m.EQUIPE IN ('B2B Escritório', 'B2B Construtora')
        GROUP BY m.EQUIPE, m.MES

        UNION ALL

        SELECT 'Farmer' AS EQUIPE, MES, SUM(COALESCE(META_EXPANSAO, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES IN ({meses_in}) AND EQUIPE = 'Sonia'
        GROUP BY MES
    """).to_pandas()


@st.cache_data(ttl=600)
def _load_otr_meta(ano: int, meses_in: str) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        SELECT m.MES, SUM(COALESCE(m.META_OTR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES
         AND COALESCE(p.IS_GESTOR, FALSE) = FALSE
        WHERE m.ANO = {ano} AND m.MES IN ({meses_in}) AND m.EQUIPE IN ('Governo', 'B2G')
        GROUP BY m.MES
    """).to_pandas()


# ── Carregar dados ─────────────────────────────────────────────────────────────
try:
    df_nr     = _load_nmrr_real(_ano, _meses_in).copy()
    df_or     = _load_otr_real(_ano, _meses_in).copy()
    df_nm     = _load_nmrr_meta(_ano, _meses_in).copy()
    df_om     = _load_otr_meta(_ano, _meses_in).copy()
    df_status = _load_fechamento_status(_ano, _meses_in)
except Exception as _e:
    if _is_xp_err(_e):
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_e}")
    st.stop()

# ── Aplicar overrides PVT ─────────────────────────────────────────────────────
try:
    _df_ov = session.sql(f"""
        SELECT MES, EQUIPE, REAL_NMRR, META_NMRR, REAL_OTR, META_OTR
        FROM SUPERSET.COMISSOES.PVT_OVERRIDES
        WHERE ANO = {_ano} AND MES IN ({_meses_in})
          AND (REAL_NMRR IS NOT NULL OR META_NMRR IS NOT NULL
               OR REAL_OTR IS NOT NULL OR META_OTR IS NOT NULL)
    """).to_pandas()
except Exception as _e:
    # Sem os overrides o cálculo fica errado silenciosamente — melhor parar.
    if _is_xp_err(_e):
        compat_rerun()
    st.error(f"Erro ao carregar os overrides PVT: {_e}")
    st.stop()

for _, _ov in _df_ov.iterrows():
    _om_mes = int(_ov["MES"])
    _ov_eq  = str(_ov["EQUIPE"])

    def _notnull(v):
        return v is not None and not (isinstance(v, float) and pd.isna(v))

    if _ov_eq != "B2G":
        if _notnull(_ov["REAL_NMRR"]):
            _m = (df_nr["MES"] == _om_mes) & (df_nr["EQUIPE"] == _ov_eq)
            if _m.any():
                df_nr.loc[_m, "VALOR"] = float(_ov["REAL_NMRR"])
            else:
                df_nr = pd.concat([df_nr, pd.DataFrame(
                    [{"EQUIPE": _ov_eq, "MES": _om_mes, "VALOR": float(_ov["REAL_NMRR"])}]
                )], ignore_index=True)
        if _notnull(_ov["META_NMRR"]):
            _m = (df_nm["MES"] == _om_mes) & (df_nm["EQUIPE"] == _ov_eq)
            if _m.any():
                df_nm.loc[_m, "VALOR"] = float(_ov["META_NMRR"])
            else:
                df_nm = pd.concat([df_nm, pd.DataFrame(
                    [{"EQUIPE": _ov_eq, "MES": _om_mes, "VALOR": float(_ov["META_NMRR"])}]
                )], ignore_index=True)
    else:
        if _notnull(_ov["REAL_OTR"]):
            _m = df_or["MES"] == _om_mes
            if _m.any():
                df_or.loc[_m, "VALOR"] = float(_ov["REAL_OTR"])
            else:
                df_or = pd.concat([df_or, pd.DataFrame(
                    [{"MES": _om_mes, "VALOR": float(_ov["REAL_OTR"])}]
                )], ignore_index=True)
        if _notnull(_ov["META_OTR"]):
            _m = df_om["MES"] == _om_mes
            if _m.any():
                df_om.loc[_m, "VALOR"] = float(_ov["META_OTR"])
            else:
                df_om = pd.concat([df_om, pd.DataFrame(
                    [{"MES": _om_mes, "VALOR": float(_ov["META_OTR"])}]
                )], ignore_index=True)

# ── Cálculo ───────────────────────────────────────────────────────────────────
meta_nmrr = float(df_nm["VALOR"].sum()) if not df_nm.empty else 0.0
real_nmrr = float(df_nr["VALOR"].sum()) if not df_nr.empty else 0.0
meta_otr  = float(df_om["VALOR"].sum()) if not df_om.empty else 0.0
real_otr  = float(df_or["VALOR"].sum()) if not df_or.empty else 0.0

pct_nmrr = real_nmrr / meta_nmrr if meta_nmrr > 0 else 0.0
pct_otr  = real_otr  / meta_otr  if meta_otr  > 0 else 0.0
pct_pond = (pct_nmrr * _POND_NMRR) + (pct_otr * _POND_OTR)

if pct_pond < _CLIFF_GERAL:
    acelerador = 0.0
    acel_label = f"0× (abaixo do cliff de {pct_fmt(_CLIFF_GERAL)})"
    acel_cor   = "#dc2626"
elif pct_pond < _MULT_115_CLIFF:
    acelerador = 1.00
    acel_label = "1,00×"
    acel_cor   = "#374151"
elif pct_pond < _MULT_125_CLIFF:
    acelerador = 1.15
    acel_label = "1,15×"
    acel_cor   = "#059669"
else:
    acelerador = 1.25
    acel_label = "1,25×"
    acel_cor   = "#059669"

ote_ajustado      = _OTE_BASE * acelerador
total_atingimento = pct_pond
comissao          = ote_ajustado * pct_pond

# ── Helpers de HTML ───────────────────────────────────────────────────────────
_cor_comissao = "#16a34a" if comissao > 0 else "#374151"


def _card_comissao() -> str:
    _sub = "#9ca3af"
    _td3 = f"style='text-align:right;font-size:.7rem;color:{_sub};padding-left:10px;white-space:nowrap;'"
    _calc_pond = (
        f"60% × {pct_fmt(pct_nmrr)}&nbsp;+&nbsp;40% × {pct_fmt(pct_otr)}"
    )
    if acelerador == 0.0:
        _calc_acel = f"pond. &lt; {pct_fmt(_CLIFF_GERAL)}"
    elif acelerador == 1.15:
        _calc_acel = f"pond. ≥ {pct_fmt(_MULT_115_CLIFF)}"
    elif acelerador == 1.25:
        _calc_acel = f"pond. ≥ {pct_fmt(_MULT_125_CLIFF)}"
    else:
        _calc_acel = f"{pct_fmt(_CLIFF_GERAL)} ≤ pond. &lt; {pct_fmt(_MULT_115_CLIFF)}"
    _acel_str = "0×" if acelerador == 0.0 else f"{acelerador:.2f}×".replace(".", ",")
    _calc_ote = f"{brl(_OTE_BASE)} × {_acel_str}"
    return (
        f"<div style='background:#f0fdf4;border-radius:8px;padding:1rem 1.2rem;"
        f"border:1px solid #d1fae5;border-left:5px solid {_cor_comissao};'>"
        f"<div style='font-size:0.78rem;font-weight:700;color:#1a1a1a;"
        f"text-transform:uppercase;letter-spacing:.04em;margin-bottom:.5rem;'>"
        f"Comissão {_trim}/{_ano}</div>"
        f"<div style='font-size:2rem;font-weight:700;color:{_cor_comissao};line-height:1.1;'>"
        f"{brl(comissao)}</div>"
        f"<div style='font-size:0.82rem;color:{_sub};margin-top:.3rem;margin-bottom:.9rem;'>"
        f"{brl(ote_ajustado)} × {pct_fmt(total_atingimento)}</div>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.84rem;'>"
        f"<tr>"
        f"<td style='padding:3px 0;color:#1a1a1a;'>Atingimento ponderado</td>"
        f"<td {_td3}>{_calc_pond}</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{pct_fmt(total_atingimento)}</td>"
        f"</tr>"
        f"<tr>"
        f"<td style='padding:3px 0;color:#1a1a1a;'>OTE Base</td>"
        f"<td></td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{brl(_OTE_BASE)}</td>"
        f"</tr>"
        f"<tr>"
        f"<td style='padding:3px 0;color:#1a1a1a;'>Acelerador</td>"
        f"<td {_td3}>{_calc_acel}</td>"
        f"<td style='text-align:right;font-weight:700;color:{acel_cor};padding-left:10px;'>{acel_label}</td>"
        f"</tr>"
        f"<tr>"
        f"<td style='padding:3px 0;color:#1a1a1a;'>OTE Ajustado</td>"
        f"<td {_td3}>{_calc_ote}</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{brl(ote_ajustado)}</td>"
        f"</tr>"
        f"</table>"
        f"</div>"
    )


def _card_eixo(titulo: str, subtitulo: str, meta: float, real: float, pct: float, pond: float) -> str:
    cor = "#16a34a" if pct >= 1.0 else "#dc2626" if pct < _CLIFF_GERAL else "#374151"
    return (
        f"<div style='background:#f9fafb;border-radius:8px;padding:1rem 1.2rem;"
        f"border:1px solid #e5e7eb;'>"
        f"<div style='font-size:0.78rem;font-weight:700;color:#1a1a1a;"
        f"text-transform:uppercase;letter-spacing:.05em;margin-bottom:.15rem;'>{titulo}</div>"
        f"<div style='font-size:0.72rem;color:#6b7280;margin-bottom:.55rem;'>{subtitulo}</div>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.88rem;'>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Meta</td>"
        f"    <td style='text-align:right;font-weight:600;color:#1a1a1a;'>{brl(meta)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Realizado</td>"
        f"    <td style='text-align:right;font-weight:600;color:#1a1a1a;'>{brl(real)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>% Atingido</td>"
        f"    <td style='text-align:right;font-weight:700;color:{cor};'>{pct_fmt(pct)}</td></tr>"
        f"<tr><td style='padding:3px 0;font-size:.8rem;color:#374151;'>Ponderação</td>"
        f"    <td style='text-align:right;font-size:.8rem;color:#374151;'>{pct_fmt(pond)}</td></tr>"
        f"</table>"
        f"</div>"
    )


# ── Render: 3 cards em uma linha com altura igual ─────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;"
    "align-items:stretch;margin-bottom:1rem;'>"
    + _card_comissao()
    + _card_eixo(
        "NMRR",
        "Escritórios · Construtoras · Farmer",
        meta_nmrr, real_nmrr, pct_nmrr, _POND_NMRR,
    )
    + _card_eixo(
        "BOOKING",
        "B2G",
        meta_otr, real_otr, pct_otr, _POND_OTR,
    )
    + "</div>",
    unsafe_allow_html=True,
)


# ── Status de Fechamento ──────────────────────────────────────────────────────
def _fmt_dt(dt) -> str:
    try:
        if hasattr(dt, "strftime"):
            return dt.strftime("%d/%m")
        s = str(dt)
        return s[8:10] + "/" + s[5:7] if len(s) >= 10 else s
    except Exception:
        return "—"


_fechados = {}
for _, _sr in df_status.iterrows():
    _fechados[(str(_sr["EQUIPE"]), int(_sr["MES"]))] = _sr["DATA_FECHAMENTO"]

_eq_nmrr_status = ["B2B Escritório", "B2B Construtora", "Farmer"]
_eq_b2g_alts    = ["Governo", "B2G"]

_th_cols = "".join(
    f"<th style='text-align:center;padding:2px 8px;color:#9ca3af;"
    f"font-weight:400;font-size:.7rem;'>{lbl}</th>"
    for lbl in _mes_lbls
)

def _cell(eq, mes):
    if (eq, mes) in _fechados:
        return (
            f"<td style='text-align:center;padding:2px 8px;font-size:.72rem;'>"
            f"<span style='color:#059669;'>🔒 {_fmt_dt(_fechados[(eq, mes)])}</span></td>"
        )
    return (
        f"<td style='text-align:center;padding:2px 8px;font-size:.72rem;'>"
        f"<span style='color:#d1d5db;'>·</span></td>"
    )

_tr_nmrr = "".join(
    f"<tr><td style='padding:2px 0;color:#6b7280;font-size:.72rem;"
    f"padding-right:12px;'>{eq}</td>"
    + "".join(_cell(eq, m) for m in _meses)
    + "</tr>"
    for eq in _eq_nmrr_status
)

_b2g_cells_list = []
for _bm in _meses:
    _bdt = next((_fechados.get((eq, _bm)) for eq in _eq_b2g_alts if (eq, _bm) in _fechados), None)
    if _bdt is not None:
        _bc = f"<span style='color:#059669;font-weight:600;'>🔒 {_fmt_dt(_bdt)}</span>"
    else:
        _bc = "<span style='color:#9ca3af;'>Aberto</span>"
    _b2g_cells_list.append(
        f"<td style='text-align:center;padding:4px 8px;font-size:.8rem;"
        f"border-top:1px solid #f0f0f0;'>{_bc}</td>"
    )
_tr_b2g = (
    f"<tr><td style='padding:2px 0;color:#6b7280;font-size:.72rem;"
    f"padding-right:12px;'>B2G (Booking)</td>"
    + "".join(_b2g_cells_list) + "</tr>"
)

# ── Helper: pivot para tabelas ────────────────────────────────────────────────
def _build_pivot(df_eq: pd.DataFrame, df_b2g: pd.DataFrame) -> pd.DataFrame:
    cols = ["Equipe"] + _mes_lbls + ["Total"]
    rows = []
    for eq in _EQUIPE_ORDER:
        sub  = df_eq[df_eq["EQUIPE"] == eq]
        vals = [float(sub.loc[sub["MES"] == m, "VALOR"].sum()) for m in _meses]
        rows.append([eq] + [brl(v) for v in vals] + [brl(sum(vals))])
    vals_tot = [float(df_eq.loc[df_eq["MES"] == m, "VALOR"].sum()) for m in _meses]
    rows.append(["Total NMRR"] + [brl(v) for v in vals_tot] + [brl(sum(vals_tot))])
    vals_b2g = [float(df_b2g.loc[df_b2g["MES"] == m, "VALOR"].sum()) for m in _meses]
    rows.append(["B2G (Booking)"] + [brl(v) for v in vals_b2g] + [brl(sum(vals_b2g))])
    return pd.DataFrame(rows, columns=cols)


# ── Tabelas detalhadas ────────────────────────────────────────────────────────
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Metas</div>",
    unsafe_allow_html=True,
)
html_table(_build_pivot(df_nm, df_om), scrollable=False)

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Realizado</div>",
    unsafe_allow_html=True,
)
html_table(_build_pivot(df_nr, df_or), scrollable=False)

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='margin-bottom:.75rem;'>"
    "<table style='border-collapse:collapse;'>"
    f"<tr><th style='text-align:left;padding:2px 12px 2px 0;color:#9ca3af;"
    f"font-weight:400;font-size:.68rem;text-transform:uppercase;'>Fechamento</th>{_th_cols}</tr>"
    f"{_tr_nmrr}{_tr_b2g}"
    "</table></div>",
    unsafe_allow_html=True,
)


