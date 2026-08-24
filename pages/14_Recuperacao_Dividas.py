import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import (
    get_session, compat_rerun, compat_divider, render_period_filter,
    current_email, require_admin_or_gestor, audit_user_sql,
)
from utils.ui import html_table, render_css, render_banner

render_css()
render_banner("Recuperação de Dívidas")

session = get_session()

require_admin_or_gestor(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_recuperacao(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EMAIL, VALOR, PERCENTUAL_COMISSAO,
               VALOR * PERCENTUAL_COMISSAO AS COMISSAO
        FROM SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EMAIL
    """).to_pandas()

tipo_usuario = st.session_state.get("tipo_usuario", "Admin")
user_email   = current_email(session)

def _brl(v):
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _pct(v):
    return f"{float(v)*100:.2f}%".replace(".", ",")

ano, mes = render_period_filter()

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_recuperacao(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum registro para este período.</div>", unsafe_allow_html=True)
else:
    df_disp = df.copy()
    df_disp["VALOR"]               = df_disp["VALOR"].map(_brl)
    df_disp["PERCENTUAL_COMISSAO"] = df_disp["PERCENTUAL_COMISSAO"].map(_pct)
    df_disp["COMISSAO"]            = df_disp["COMISSAO"].map(_brl)
    html_table(df_disp.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE").replace("Comissao", "Comissão")))

# ── Formulario ────────────────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar / Atualizar</div>", unsafe_allow_html=True)

# Admin vê todas as consultoras Saving do período.
# Gestor vê apenas as consultoras vinculadas a ele no RLS deste período.
if tipo_usuario == "Gestor":
    u_safe = user_email.replace("'", "''")
    consultores_df = session.sql(f"""
        SELECT DISTINCT r.CONSULTOREMAIL AS CONSULTOR
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS r
        WHERE r.ANO = {ano} AND r.MES = {mes}
          AND LOWER(r.USUARIOEMAIL) = '{u_safe}'
          AND UPPER(r.TIPOUSUARIO)  = 'GESTOR'
        ORDER BY r.CONSULTOREMAIL
    """).to_pandas()
else:
    consultores_df = session.sql(f"""
        SELECT DISTINCT m.CONSULTOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        WHERE m.ANO = {ano} AND m.MES = {mes}
          AND LOWER(m.EQUIPE) = 'saving'
        ORDER BY m.CONSULTOR
    """).to_pandas()

consultores = consultores_df["CONSULTOR"].tolist() if not consultores_df.empty else []

if not consultores:
    st.markdown("<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>Nenhuma consultora disponível para este período.</div>", unsafe_allow_html=True)
    st.stop()

col1, col2, col3 = st.columns([3, 1, 1])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Consultora</label>", unsafe_allow_html=True)
email_sel   = col1.selectbox("", [""] + consultores, label_visibility="collapsed")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Valor Recuperado (R$)</label>", unsafe_allow_html=True)
_raw_valor   = col2.text_input("", value="0,00", key="valor_v", label_visibility="collapsed")
col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>% Comissão</label>", unsafe_allow_html=True)
_raw_pct_display = col3.text_input("", value="2,50", key="pct_display", label_visibility="collapsed")

try:
    valor_v     = max(0.0, float(_raw_valor.replace(",", ".")))
    pct_display = max(0.0, min(100.0, float(_raw_pct_display.replace(",", "."))))
except ValueError:
    valor_v     = 0.0
    pct_display = 2.5
pct_v = pct_display / 100

if email_sel:
    st.markdown(f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>Comissão calculada: <b>{_brl(valor_v * pct_v)}</b></p>", unsafe_allow_html=True)

if email_sel and st.button("Salvar", type="primary"):
    try:
        valor_v     = max(0.0, float(_raw_valor.replace(",", ".")))
        pct_display = max(0.0, min(100.0, float(_raw_pct_display.replace(",", "."))))
    except ValueError:
        st.error("Insira valores numéricos válidos.")
        st.stop()
    pct_v = pct_display / 100
    em = email_sel.replace("'", "''")
    session.sql(f"""
        MERGE INTO SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS AS t
        USING (SELECT {ano} AS ANO, {mes} AS MES, '{em}' AS EMAIL,
                      {valor_v} AS VALOR, {pct_v} AS PERCENTUAL_COMISSAO) AS s
        ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
        WHEN MATCHED THEN UPDATE SET VALOR = s.VALOR, PERCENTUAL_COMISSAO = s.PERCENTUAL_COMISSAO,
            UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (ANO, MES, EMAIL, VALOR, PERCENTUAL_COMISSAO, UPDATED_BY, UPDATED_AT)
        VALUES (s.ANO, s.MES, s.EMAIL, s.VALOR, s.PERCENTUAL_COMISSAO, {_autor_sql}, CURRENT_TIMESTAMP())
    """).collect()
    st.success(f"Registro de **{email_sel}** salvo.")
    st.cache_data.clear()
    compat_rerun()

# ── Remover ───────────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    emails_rm = df["EMAIL"].tolist()
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Remover registro de</label>", unsafe_allow_html=True)
    email_rm = st.selectbox("", emails_rm, key="rm_email", label_visibility="collapsed")
    _confirm_key = "_confirm_rm_divida"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção do registro de **{email_rm}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_divida"):
            em = email_rm.replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS
                WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = LOWER('{em}')
            """).collect()
            del st.session_state[_confirm_key]
            st.success("Registro removido.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_divida"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif st.button("Remover", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()


