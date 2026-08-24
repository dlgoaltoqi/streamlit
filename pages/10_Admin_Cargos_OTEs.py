import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin, audit_user_sql
from utils.ui import brl, html_table, render_css, render_banner

render_css()
render_banner("Cargos e OTEs")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_cargos_otes(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT CARGO, OTE
        FROM SUPERSET.COMISSOES.CARGOS_OTES
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY CARGO
    """).to_pandas()

_SIGLAS_RE = re.compile(r'\b(II|SDR|JR|PL|SR|FSB)\b', re.IGNORECASE)

def _fmt_cargo(s):
    return _SIGLAS_RE.sub(lambda m: m.group().upper(), str(s).title())

from utils.connection import MESES_NOME as MESES

ano, mes = render_period_filter()

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_cargos_otes(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.info("Nenhum cargo cadastrado para este período.")
else:
    df_disp = df.copy()
    df_disp["CARGO"] = df_disp["CARGO"].apply(_fmt_cargo)
    df_disp["OTE"] = df_disp["OTE"].apply(lambda v: brl(float(v)) if pd.notna(v) else "—")
    html_table(df_disp.rename(columns={"CARGO": "Cargo"}))

    # ── Copiar tabela inteira para outro mês ──────────────────────────────────
    _col1, _col2 = st.columns([3, 1])
    _col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Copiar tabela para</label>", unsafe_allow_html=True)
    _mes_dest = _col1.selectbox(
        "",
        [m for m in MESES.keys() if m != mes],
        format_func=lambda m: MESES[m],
        key="_copy_dest_",
        label_visibility="collapsed",
    )
    _col2.markdown("<br>", unsafe_allow_html=True)
    if _col2.button("Copiar Tabela"):
        _vals = ", ".join(
            f"({ano}, {_mes_dest}, '{str(r['CARGO']).replace(chr(39), chr(39)*2)}', {float(r['OTE'])})"
            for _, r in df.iterrows()
            if pd.notna(r['OTE'])
        )
        session.sql(f"""
            MERGE INTO SUPERSET.COMISSOES.CARGOS_OTES AS t
            USING (
                SELECT v.c1 AS ANO, v.c2 AS MES, v.c3 AS CARGO, v.c4 AS OTE
                FROM (VALUES {_vals}) AS v(c1, c2, c3, c4)
            ) AS s
            ON t.ANO = s.ANO AND t.MES = s.MES AND UPPER(t.CARGO) = UPPER(s.CARGO)
            WHEN MATCHED THEN UPDATE SET OTE = s.OTE,
                UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (ANO, MES, CARGO, OTE, UPDATED_BY, UPDATED_AT) VALUES (s.ANO, s.MES, s.CARGO, s.OTE, {_autor_sql}, CURRENT_TIMESTAMP())
        """).collect()
        st.success(f"{len(df)} cargo(s) copiado(s) para {MESES.get(_mes_dest, _mes_dest)}/{ano}.")
        st.cache_data.clear()
        compat_rerun()

# ── Remover cargo ─────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Cargo</div>", unsafe_allow_html=True)
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Cargo para remover</label>", unsafe_allow_html=True)
    cargo_rem = st.selectbox("", [""] + df["CARGO"].tolist(), key="rem_cargo", label_visibility="collapsed")
    _confirm_key = "_confirm_rm_cargo"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção de **{cargo_rem}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_cargo"):
            cargo_rem_safe = cargo_rem.replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.CARGOS_OTES
                WHERE ANO = {ano} AND MES = {mes} AND UPPER(CARGO) = UPPER('{cargo_rem_safe}')
            """).collect()
            del st.session_state[_confirm_key]
            st.success(f"Cargo **{cargo_rem}** removido de {MESES.get(mes, mes)}/{ano}.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_cargo"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif cargo_rem and st.button("Remover Cargo", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()

# ── Adicionar / atualizar cargo ───────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar / Atualizar</div>", unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Cargo</label>", unsafe_allow_html=True)
cargo_input = col1.text_input("", placeholder="ex: Consultor B2B", label_visibility="collapsed")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>OTE (R$)</label>", unsafe_allow_html=True)
ote_str = col2.text_input("", placeholder="ex: 15000,00", label_visibility="collapsed", key="ote_val")

try:
    _ote_prev = float(ote_str.strip().replace(",", ".")) if ote_str.strip() else None
    if _ote_prev and _ote_prev > 0:
        st.caption(f"→ {brl(_ote_prev)}")
except ValueError:
    pass

if st.button("Salvar", type="primary"):
    if not cargo_input.strip():
        st.error("Informe o cargo.")
    else:
        try:
            ote_input = float(ote_str.strip().replace(",", ".")) if ote_str.strip() else 0.0
        except ValueError:
            ote_input = 0.0
        if ote_input <= 0:
            st.error("OTE deve ser maior que zero.")
        else:
            cargo_safe = cargo_input.strip().replace("'", "''")
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.CARGOS_OTES AS t
                USING (SELECT {ano} AS ANO, {mes} AS MES,
                              '{cargo_safe}' AS CARGO, {ote_input} AS OTE) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES AND UPPER(t.CARGO) = UPPER(s.CARGO)
                WHEN MATCHED THEN UPDATE SET OTE = s.OTE,
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (ANO, MES, CARGO, OTE, UPDATED_BY, UPDATED_AT)
                VALUES (s.ANO, s.MES, s.CARGO, s.OTE, {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.success(f"OTE de **{cargo_input}** salvo: R$ {ote_input:,.2f}")
            st.cache_data.clear()
            compat_rerun()



