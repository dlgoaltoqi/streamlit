import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, current_email, _is_admin, compat_rerun, _is_xp_err, ano_atual, mes_atual, audit_user
from utils.ui import brl, render_banner, render_css

render_css()

render_banner("Admin — Overrides PVT")

session = get_session()

_user_email = current_email(session)
if not _is_admin(_user_email):
    st.error("Acesso restrito a administradores.")
    st.stop()

# Autoria separada do controle de acesso: _user_email pode ser o login quando ele
# mesmo esta em ADMIN_EMAILS, e a auditoria grava sempre e-mail.
_autor = audit_user(session)

from utils.connection import MESES_NOME as _MESES_NOME
_EQUIPES_NMRR = ["FSB", "B2B Escritório", "B2B Construtora", "Farmer", "Ares"]

_c1, _c2, _ = st.columns([1, 1, 4])
_ano = _c1.selectbox("Ano", list(range(ano_atual(), 2024, -1)), key="_pvtov_ano_")
_mes = _c2.selectbox(
    "Mês", list(range(1, 13)),
    format_func=lambda m: _MESES_NOME[m],
    index=mes_atual() - 1, key="_pvtov_mes_",
)


# ── Queries ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def _nmrr_vivo(ano: int, mes: int) -> pd.DataFrame:
    """NMRR puro do VENDAS (sem considerar fechamento)."""
    s = get_active_session()
    return s.sql(f"""
        WITH ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES = {mes}
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        )
        SELECT v.VERTICAL AS EQUIPE,
               SUM(CASE WHEN v.VERTICAL = 'Farmer'
                        THEN COALESCE(v.MRR_EXPANSAO,0)
                        ELSE COALESCE(v.NMRR,0) END) AS VALOR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN ok ON ok.ID_NEGOCIO = v.ID_NEGOCIO
        WHERE v.ANO = {ano} AND v.MES = {mes}
          AND v.VERTICAL IN ('FSB','B2B Escritório','B2B Construtora','Farmer','Ares')
        GROUP BY 1
    """).to_pandas()


@st.cache_data(ttl=120)
def _nmrr_snap(ano: int, mes: int) -> pd.DataFrame:
    """NMRR dos deals no snapshot de fechamento (COMPOSICAO_FECHADA)."""
    s = get_active_session()
    return s.sql(f"""
        WITH fa AS (
            SELECT EQUIPE, FECHAMENTO_ID
            FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES = {mes} AND STATUS = 'ATIVO'
              AND EQUIPE IN ('FSB','B2B Escritório','B2B Construtora','Farmer','Ares')
        ),
        deals AS (
            SELECT DISTINCT cf.EQUIPE, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fa ON fa.FECHAMENTO_ID = cf.FECHAMENTO_ID AND fa.EQUIPE = cf.EQUIPE
            WHERE cf.MES = {mes} AND cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        )
        SELECT v.VERTICAL AS EQUIPE,
               SUM(CASE WHEN v.VERTICAL = 'Farmer'
                        THEN COALESCE(v.MRR_EXPANSAO,0)
                        ELSE COALESCE(v.NMRR,0) END) AS VALOR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN deals d ON d.ID_NEGOCIO = v.ID_NEGOCIO
          AND d.EQUIPE = v.VERTICAL
        WHERE v.ANO = {ano} AND v.MES = {mes}
        GROUP BY 1
    """).to_pandas()


@st.cache_data(ttl=120)
def _nmrr_meta(ano: int, mes: int) -> pd.DataFrame:
    s = get_active_session()
    return s.sql(f"""
        SELECT m.EQUIPE, SUM(COALESCE(m.META_NMRR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES AND p.IS_GESTOR = TRUE
        WHERE m.ANO = {ano} AND m.MES = {mes}
          AND m.EQUIPE IN ('FSB','B2B Escritório','B2B Construtora')
        GROUP BY m.EQUIPE
        UNION ALL
        SELECT 'Farmer', SUM(COALESCE(META_EXPANSAO, 0))
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = 'Sonia'
    """).to_pandas()


@st.cache_data(ttl=120)
def _otr_vivo(ano: int, mes: int) -> float:
    """Booking B2G puro do VENDAS (sem considerar fechamento)."""
    s = get_active_session()
    df = s.sql(f"""
        WITH ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES = {mes}
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        )
        SELECT SUM(COALESCE(v.BOOKING, 0)) AS VALOR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN ok ON ok.ID_NEGOCIO = v.ID_NEGOCIO
        WHERE v.ANO = {ano} AND v.MES = {mes} AND v.VERTICAL IN ('B2G', 'B2E')
    """).to_pandas()
    return float(df["VALOR"].iloc[0]) if not df.empty else 0.0


@st.cache_data(ttl=120)
def _otr_snap(ano: int, mes: int) -> float:
    """Booking B2G dos deals no snapshot de fechamento."""
    s = get_active_session()
    df = s.sql(f"""
        WITH fb AS (
            SELECT FECHAMENTO_ID
            FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES = {mes} AND STATUS = 'ATIVO'
              AND EQUIPE IN ('Governo','B2G')
        ),
        deals AS (
            SELECT DISTINCT cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fb ON fb.FECHAMENTO_ID = cf.FECHAMENTO_ID
            WHERE cf.MES = {mes} AND cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        )
        SELECT SUM(COALESCE(v.BOOKING, 0)) AS VALOR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN deals d ON d.ID_NEGOCIO = v.ID_NEGOCIO
        WHERE v.ANO = {ano} AND v.MES = {mes}
          AND v.VERTICAL IN ('B2G', 'B2E')
    """).to_pandas()
    return float(df["VALOR"].iloc[0]) if not df.empty else None


@st.cache_data(ttl=120)
def _otr_meta(ano: int, mes: int) -> float:
    s = get_active_session()
    df = s.sql(f"""
        SELECT SUM(COALESCE(m.META_OTR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES
         AND COALESCE(p.IS_GESTOR, FALSE) = FALSE
        WHERE m.ANO = {ano} AND m.MES = {mes} AND m.EQUIPE IN ('Governo','B2G')
    """).to_pandas()
    return float(df["VALOR"].iloc[0]) if not df.empty else 0.0


@st.cache_data(ttl=120)
def _fechados(ano: int, mes: int) -> set:
    """Equipes com fechamento ativo no mês."""
    s = get_active_session()
    df = s.sql(f"""
        SELECT EQUIPE FROM SUPERSET.COMISSOES.FECHAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND STATUS = 'ATIVO'
          AND EQUIPE IN ('FSB','B2B Escritório','B2B Construtora','Farmer','Ares','Governo','B2G')
    """).to_pandas()
    return set(df["EQUIPE"].tolist()) if not df.empty else set()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_overrides(ano: int, mes: int) -> dict:
    df = session.sql(f"""
        SELECT EQUIPE, REAL_NMRR, META_NMRR, REAL_OTR, META_OTR
        FROM SUPERSET.COMISSOES.PVT_OVERRIDES
        WHERE ANO = {ano} AND MES = {mes}
    """).to_pandas()
    result = {}
    for _, r in df.iterrows():
        result[str(r["EQUIPE"])] = {
            k: (None if (v is None or (isinstance(v, float) and pd.isna(v))) else float(v))
            for k, v in r.items() if k != "EQUIPE"
        }
    return result


def _parse(s: str):
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _fmt(v) -> str:
    if v is None:
        return ""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sql_f(v) -> str:
    return "NULL" if v is None else repr(float(v))


def _merge(ano, mes, equipe, real_nmrr, meta_nmrr, real_otr, meta_otr, usuario):
    eq  = equipe.replace("'", "''")
    usr = (usuario or "").replace("'", "''")
    session.sql(f"""
        MERGE INTO SUPERSET.COMISSOES.PVT_OVERRIDES AS t
        USING (SELECT {ano} AS ANO, {mes} AS MES, '{eq}' AS EQUIPE,
                      {_sql_f(real_nmrr)} AS REAL_NMRR, {_sql_f(meta_nmrr)} AS META_NMRR,
                      {_sql_f(real_otr)}  AS REAL_OTR,  {_sql_f(meta_otr)}  AS META_OTR) AS s
        ON t.ANO = s.ANO AND t.MES = s.MES AND t.EQUIPE = s.EQUIPE
        WHEN MATCHED THEN UPDATE SET
            REAL_NMRR = s.REAL_NMRR, META_NMRR = s.META_NMRR,
            REAL_OTR  = s.REAL_OTR,  META_OTR  = s.META_OTR,
            UPDATED_BY = '{usr}', UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED AND (s.REAL_NMRR IS NOT NULL OR s.META_NMRR IS NOT NULL
                           OR s.REAL_OTR  IS NOT NULL OR s.META_OTR  IS NOT NULL)
        THEN INSERT (ANO, MES, EQUIPE, REAL_NMRR, META_NMRR, REAL_OTR, META_OTR, UPDATED_BY, UPDATED_AT)
             VALUES (s.ANO, s.MES, s.EQUIPE, s.REAL_NMRR, s.META_NMRR, s.REAL_OTR, s.META_OTR,
                     '{usr}', CURRENT_TIMESTAMP())
    """).collect()


# ── Carregar dados ────────────────────────────────────────────────────────────

try:
    df_nv  = _nmrr_vivo(_ano, _mes)
    df_ns  = _nmrr_snap(_ano, _mes)
    df_nm  = _nmrr_meta(_ano, _mes)
    ov_r   = _otr_vivo(_ano, _mes)
    os_r   = _otr_snap(_ano, _mes)
    om_r   = _otr_meta(_ano, _mes)
    fec    = _fechados(_ano, _mes)
    ovr    = _get_overrides(_ano, _mes)
except Exception as _e:
    if _is_xp_err(_e):
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_e}")
    st.stop()


def _eq_val(df: pd.DataFrame, equipe: str) -> float | None:
    sub = df[df["EQUIPE"] == equipe]
    if sub.empty:
        return None
    v = float(sub["VALOR"].sum())
    return v


def _is_fec(equipe: str) -> bool:
    return equipe in fec or ("Governo" in fec and equipe == "B2G") or ("B2G" in fec and equipe == "Governo")


# ── Feedback ──────────────────────────────────────────────────────────────────
if st.session_state.get("_pvtov_ok_"):
    st.success(st.session_state.pop("_pvtov_ok_"))
if st.session_state.get("_pvtov_err_"):
    st.error(st.session_state.pop("_pvtov_err_"))

# ── Estilos da tabela ─────────────────────────────────────────────────────────
_TH = (
    "font-size:.72rem;font-weight:700;color:#1a1a1a;"
    "text-transform:uppercase;letter-spacing:.03em;"
)
_TD = "font-size:.85rem;color:#1a1a1a;padding-top:.25rem;"
_TD_MUTED = "font-size:.85rem;color:#6b7280;padding-top:.25rem;"  # só para "—"
_COLS = [1.8, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3]


def _header_row(labels):
    cols = st.columns(_COLS)
    for col, lbl in zip(cols, labels):
        col.markdown(f"<div style='{_TH}'>{lbl}</div>", unsafe_allow_html=True)


def _val_cell(col, v):
    """Exibe valor formatado; '—' em cinza quando sem dado."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        col.markdown(f"<div style='{_TD_MUTED}'>—</div>", unsafe_allow_html=True)
    else:
        col.markdown(f"<div style='{_TD}'>{brl(v)}</div>", unsafe_allow_html=True)


# ══ NMRR ════════════════════════════════════════════════════════════════════
st.markdown(
    "<div style='font-size:1.05rem;font-weight:700;color:#1a1a1a;"
    "margin-top:1rem;margin-bottom:.4rem;'>"
    "NMRR (FSB · Escritório · Construtora · Farmer · Ares)</div>",
    unsafe_allow_html=True,
)

_header_row([
    "Equipe",
    "Realizado Vivo", "Realizado Snap", "Override Realizado",
    "Meta Vivo",      "Meta Snap",      "Override Meta",
])

for _eq in _EQUIPES_NMRR:
    _ov  = ovr.get(_eq, {})
    _nv  = _eq_val(df_nv, _eq)
    _ns  = _eq_val(df_ns, _eq) if _is_fec(_eq) else None
    _nm  = _eq_val(df_nm, _eq)
    _nm_snap = _nm if _is_fec(_eq) else None

    _c = st.columns(_COLS)
    _c[0].markdown(f"<div style='{_TD}font-weight:600;'>{_eq}</div>", unsafe_allow_html=True)
    _val_cell(_c[1], _nv)
    _val_cell(_c[2], _ns)
    _c[3].text_input(
        "ovr_r", value=_fmt(_ov.get("REAL_NMRR")),
        placeholder="0,00", key=f"_nr_{_eq}_", label_visibility="collapsed",
    )
    _val_cell(_c[4], _nm)
    _val_cell(_c[5], _nm_snap)
    _c[6].text_input(
        "ovr_m", value=_fmt(_ov.get("META_NMRR")),
        placeholder="0,00", key=f"_nm_{_eq}_", label_visibility="collapsed",
    )

st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

# ══ Booking B2G ═════════════════════════════════════════════════════════════
st.markdown(
    "<div style='font-size:1.05rem;font-weight:700;color:#1a1a1a;"
    "margin-bottom:.4rem;'>Booking B2G</div>",
    unsafe_allow_html=True,
)

_header_row([
    "Equipe",
    "Realizado Vivo", "Realizado Snap", "Override Realizado",
    "Meta Vivo",      "Meta Snap",      "Override Meta",
])

_ovb     = ovr.get("B2G", {})
_b2g_fec = _is_fec("B2G")
_om_snap = om_r if _b2g_fec else None

_cb = st.columns(_COLS)
_cb[0].markdown(f"<div style='{_TD}font-weight:600;'>B2G</div>", unsafe_allow_html=True)
_val_cell(_cb[1], ov_r)
_val_cell(_cb[2], os_r if _b2g_fec else None)
_cb[3].text_input(
    "ovr_r", value=_fmt(_ovb.get("REAL_OTR")),
    placeholder="0,00", key="_or_B2G_", label_visibility="collapsed",
)
_val_cell(_cb[4], om_r)
_val_cell(_cb[5], _om_snap)
_cb[6].text_input(
    "ovr_m", value=_fmt(_ovb.get("META_OTR")),
    placeholder="0,00", key="_om_B2G_", label_visibility="collapsed",
)

# ── Salvar ────────────────────────────────────────────────────────────────────
st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

if st.button("💾 Salvar Overrides", type="primary"):
    _erros = []
    for _eq in _EQUIPES_NMRR:
        try:
            _merge(
                _ano, _mes, _eq,
                _parse(st.session_state.get(f"_nr_{_eq}_", "")),
                _parse(st.session_state.get(f"_nm_{_eq}_", "")),
                None, None,
                _autor,
            )
        except Exception as _e:
            _erros.append(f"{_eq}: {_e}")

    try:
        _merge(
            _ano, _mes, "B2G",
            None, None,
            _parse(st.session_state.get("_or_B2G_", "")),
            _parse(st.session_state.get("_om_B2G_", "")),
            _autor,
        )
    except Exception as _e:
        _erros.append(f"B2G: {_e}")

    if _erros:
        st.session_state["_pvtov_err_"] = "Erros: " + "; ".join(_erros)
    else:
        st.session_state["_pvtov_ok_"] = (
            f"Overrides salvos para {_MESES_NOME[_mes]}/{_ano}. "
            "Campo vazio = sem override (usa cálculo ao vivo)."
        )
    compat_rerun()


