import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin, audit_user_sql
from utils.ui import html_table, render_css, render_banner

render_css()
render_banner("Controle de Acesso")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_rls(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT USUARIOEMAIL, CONSULTOREMAIL, TIPOUSUARIO
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY USUARIOEMAIL, CONSULTOREMAIL
    """).to_pandas()

from utils.connection import MESES_NOME as MESES

TIPOS = ["Consultor", "Gestor"]

ano, mes = render_period_filter()
st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Usuários <b>sem</b> registro aqui e que não são Admin <b>não têm acesso</b> ao painel. Adicione um registro para liberar o acesso de cada usuário.</div>", unsafe_allow_html=True)

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_rls(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum acesso configurado para este período — somente Admins conseguem acessar o painel.</div>", unsafe_allow_html=True)
else:
    html_table(df.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE")))

# ── Adicionar acesso ──────────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar Acesso</div>", unsafe_allow_html=True)

consultores_df = session.sql(f"""
    SELECT DISTINCT CONSULTOR AS EMAIL
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = {ano} AND MES = {mes}
    ORDER BY CONSULTOR
""").to_pandas()
consultores = consultores_df["EMAIL"].tolist() if not consultores_df.empty else []

col1, col2, col3 = st.columns(3)
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>E-mail do usuário (quem acessa)</label>", unsafe_allow_html=True)
usuario_email = col1.text_input("", label_visibility="collapsed", key="usuario_email")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Consultor visível para este usuário</label>", unsafe_allow_html=True)
consultor_sel = col2.selectbox("", [""] + consultores, label_visibility="collapsed", key="consultor_sel")
col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Tipo de usuário</label>", unsafe_allow_html=True)
tipo_sel      = col3.selectbox("", TIPOS, label_visibility="collapsed", key="tipo_sel")

if st.button("Adicionar Acesso", type="primary"):
    if not usuario_email.strip():
        st.error("Informe o e-mail do usuário.")
    elif not consultor_sel:
        st.error("Selecione o consultor.")
    else:
        u = usuario_email.strip().lower().replace("'", "''")
        c = consultor_sel.strip().replace("'", "''")
        session.sql(f"""
            MERGE INTO SUPERSET.PARCIAL.PERMISSAO_RLS AS t
            USING (
                SELECT {ano} AS ANO, {mes} AS MES,
                       '{u}' AS USUARIOEMAIL,
                       '{c}' AS CONSULTOREMAIL,
                       '{tipo_sel}' AS TIPOUSUARIO
            ) AS s
            ON t.ANO = s.ANO AND t.MES = s.MES
           AND LOWER(t.USUARIOEMAIL)    = LOWER(s.USUARIOEMAIL)
           AND LOWER(t.CONSULTOREMAIL)  = LOWER(s.CONSULTOREMAIL)
            WHEN MATCHED THEN UPDATE SET TIPOUSUARIO = s.TIPOUSUARIO,
                UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT
                (ANO, MES, USUARIOEMAIL, CONSULTOREMAIL, TIPOUSUARIO, UPDATED_BY, UPDATED_AT)
            VALUES (s.ANO, s.MES, s.USUARIOEMAIL, s.CONSULTOREMAIL, s.TIPOUSUARIO, {_autor_sql}, CURRENT_TIMESTAMP())
        """).collect()
        st.success(f"Acesso de **{u}** ao consultor **{c}** configurado.")
        st.cache_data.clear()
        compat_rerun()

# ── Remover acesso ────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Acesso</div>", unsafe_allow_html=True)

    opcoes = [
        f"{r['USUARIOEMAIL']} → {r['CONSULTOREMAIL']}"
        for _, r in df.iterrows()
    ]
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Selecione o vínculo para remover</label>", unsafe_allow_html=True)
    sel = st.selectbox("", [""] + opcoes, label_visibility="collapsed", key="sel_rem")

    _confirm_key = "_confirm_rm_rls"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção de **{sel}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_rls"):
            usuario_rem, consultor_rem = [x.strip() for x in sel.split("→")]
            _u_safe = usuario_rem.lower().replace("'", "''")
            _c_safe = consultor_rem.lower().replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.PARCIAL.PERMISSAO_RLS
                WHERE ANO = {ano} AND MES = {mes}
                  AND LOWER(USUARIOEMAIL)   = '{_u_safe}'
                  AND LOWER(CONSULTOREMAIL) = '{_c_safe}'
            """).collect()
            del st.session_state[_confirm_key]
            st.success(f"Acesso removido: **{usuario_rem}** → **{consultor_rem}**.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_rls"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif sel and st.button("Remover Acesso Selecionado", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()

# ── Copiar mes anterior ───────────────────────────────────────────────────────

compat_divider()
with st.expander("Copiar do mês anterior", expanded=False):
    mes_orig = mes - 1 if mes > 1 else 12
    ano_orig = ano if mes > 1 else ano - 1

    orig_count_df = session.sql(f"""
        SELECT COUNT(*) AS N FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano_orig} AND MES = {mes_orig}
    """).to_pandas()
    n_orig = int(orig_count_df.iloc[0]["N"]) if not orig_count_df.empty else 0

    st.markdown(f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>Mês de origem: <b>{MESES.get(mes_orig, mes_orig)}/{ano_orig}</b> — {n_orig} registro(s). Mês atual já tem {len(df)} registro(s).</p>", unsafe_allow_html=True)

    if n_orig == 0:
        st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum acesso configurado no mês anterior.</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>Copia apenas vínculos que não existem no mês atual.</div>", unsafe_allow_html=True)
        if st.button("Copiar acessos do mês anterior", type="secondary"):
            session.sql(f"""
                MERGE INTO SUPERSET.PARCIAL.PERMISSAO_RLS AS t
                USING (
                    SELECT {ano} AS ANO, {mes} AS MES,
                           USUARIOEMAIL, CONSULTOREMAIL, TIPOUSUARIO
                    FROM SUPERSET.PARCIAL.PERMISSAO_RLS
                    WHERE ANO = {ano_orig} AND MES = {mes_orig}
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES
               AND LOWER(t.USUARIOEMAIL)   = LOWER(s.USUARIOEMAIL)
               AND LOWER(t.CONSULTOREMAIL) = LOWER(s.CONSULTOREMAIL)
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, USUARIOEMAIL, CONSULTOREMAIL, TIPOUSUARIO, UPDATED_BY, UPDATED_AT)
                VALUES (s.ANO, s.MES, s.USUARIOEMAIL, s.CONSULTOREMAIL, s.TIPOUSUARIO, {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.success(f"Acessos copiados de {MESES.get(mes_orig, mes_orig)}/{ano_orig}.")
            st.cache_data.clear()
            compat_rerun()


