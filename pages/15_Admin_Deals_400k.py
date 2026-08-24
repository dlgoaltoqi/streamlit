import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, require_admin, audit_user_sql
from utils.ui import html_table, render_css, render_banner

render_css()
render_banner("Deals ≥ 400k")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_deals() -> pd.DataFrame:
    session = get_active_session()
    return session.sql("""
        SELECT ID_NEGOCIO, DATA_MARCACAO, USUARIO, OBSERVACAO
        FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
        ORDER BY DATA_MARCACAO DESC
    """).to_pandas()

st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Deals com Booking >= R$ 400k são excluídos do cálculo de comissão por padrão. Adicione o ID aqui para aprovar manualmente a inclusão.</div>", unsafe_allow_html=True)

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_deals()
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

st.markdown(f"<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Deals aprovados ({len(df)} registros)</div>", unsafe_allow_html=True)

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum deal aprovado.</div>", unsafe_allow_html=True)
else:
    html_table(df.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE").replace("Marcacao", "Marcação").replace("Observacao", "Observação")))

# ── Adicionar deal ────────────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Aprovar Deal</div>", unsafe_allow_html=True)

usuario = (session.get_current_user() or "").strip('"')

col1, col2 = st.columns([2, 3])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>ID do Negócio (HubSpot)</label>", unsafe_allow_html=True)
id_neg_v  = col1.text_input("", placeholder="ex: 12345678", label_visibility="collapsed")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Observação</label>", unsafe_allow_html=True)
obs_v     = col2.text_input("", placeholder="ex: aprovado por fulano", label_visibility="collapsed")

if st.button("Adicionar", type="primary"):
    if not id_neg_v.strip():
        st.error("Informe o ID do negócio.")
    else:
        id_safe  = id_neg_v.strip().replace("'", "''")
        obs_safe = obs_v.strip().replace("'", "''")
        usr_safe = usuario.replace("'", "''")
        session.sql(f"""
            MERGE INTO SUPERSET.COMISSOES.DEALS_PAGOS_400K AS t
            USING (SELECT '{id_safe}' AS ID_NEGOCIO,
                          CURRENT_DATE AS DATA_MARCACAO,
                          '{usr_safe}' AS USUARIO,
                          '{obs_safe}' AS OBSERVACAO) AS s
            ON t.ID_NEGOCIO = s.ID_NEGOCIO
            WHEN MATCHED THEN UPDATE SET
                DATA_MARCACAO = s.DATA_MARCACAO,
                USUARIO = s.USUARIO,
                OBSERVACAO = s.OBSERVACAO,
                UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (ID_NEGOCIO, DATA_MARCACAO, USUARIO, OBSERVACAO, UPDATED_BY, UPDATED_AT)
            VALUES (s.ID_NEGOCIO, s.DATA_MARCACAO, s.USUARIO, s.OBSERVACAO, {_autor_sql}, CURRENT_TIMESTAMP())
        """).collect()
        st.success(f"Deal **{id_neg_v.strip()}** aprovado.")
        st.cache_data.clear()
        compat_rerun()

# ── Remover deal ──────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Deal</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([3, 1])
    col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Deal</label>", unsafe_allow_html=True)
    id_rm = col1.selectbox("", df["ID_NEGOCIO"].tolist(), label_visibility="collapsed")
    _confirm_key = "_confirm_rm_deal"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção do deal **{id_rm}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_deal"):
            id_safe = str(id_rm).replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
                WHERE ID_NEGOCIO = '{id_safe}'
            """).collect()
            del st.session_state[_confirm_key]
            st.success(f"Deal {id_rm} removido.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_deal"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif col2.button("Remover", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()


