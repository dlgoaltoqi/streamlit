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
render_banner("Override de Realizado GD")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_realizado_gd(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        WITH ri_emails AS (
            SELECT LOWER(rio.EMAIL) AS EMAIL
            FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
                ON rio.ID = rigot.OWNER_ID
            WHERE rigot.YEAR = {ano} AND rigot.MONTH = {mes}
        ),
        gestores_gd AS (
            SELECT LOWER(p.EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS p
            WHERE p.ANO = {ano} AND p.MES = {mes}
                AND p.IS_GESTOR = TRUE AND LOWER(p.CARGO) LIKE '%demand generation%'
        ),
        membros_gd AS (
            SELECT DISTINCT
                LOWER(rls2.USUARIOEMAIL) AS GEST_EMAIL,
                LOWER(rls2.CONSULTOREMAIL) AS MEMB_EMAIL
            FROM SUPERSET.PARCIAL.PERMISSAO_RLS rls2
            JOIN gestores_gd gg ON LOWER(rls2.USUARIOEMAIL) = gg.EMAIL
            WHERE rls2.ANO = {ano} AND rls2.MES = {mes}
                AND rls2.CONSULTOREMAIL IS NOT NULL
                AND LOWER(rls2.CONSULTOREMAIL) != LOWER(rls2.USUARIOEMAIL)
        ),
        opps_gd AS (
            SELECT LOWER(PROPRIETARIO) AS EMAIL_L, COUNT(DISTINCT ID_CONTATO) AS OPPS
            FROM SUPERSET.COMISSOES.REALIZADO_GD
            WHERE YEAR(DATA_QUALIFICACAO) = {ano} AND MONTH(DATA_QUALIFICACAO) = {mes}
            GROUP BY LOWER(PROPRIETARIO)
        ),
        realizado_gest AS (
            SELECT
                mg.GEST_EMAIL,
                SUM(COALESCE(ov2.REALIZADO_MANUAL, op.OPPS, 0)) AS REALIZADO_AUTO
            FROM membros_gd mg
            LEFT JOIN opps_gd op ON op.EMAIL_L = mg.MEMB_EMAIL
            LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE ov2
                ON ov2.ANO = {ano} AND ov2.MES = {mes}
                AND LOWER(ov2.EMAIL) = mg.MEMB_EMAIL
            GROUP BY mg.GEST_EMAIL
        )

        -- Consultores com target no RI (individual)
        SELECT
            t.EMAIL,
            COUNT(DISTINCT g.ID_CONTATO) AS REALIZADO_AUTO,
            o.REALIZADO_MANUAL,
            o.MOTIVO
        FROM ri_emails t
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD g
            ON LOWER(g.PROPRIETARIO) = t.EMAIL
            AND YEAR(g.DATA_QUALIFICACAO) = {ano} AND MONTH(g.DATA_QUALIFICACAO) = {mes}
        LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
            ON o.ANO = {ano} AND o.MES = {mes} AND LOWER(o.EMAIL) = t.EMAIL
        GROUP BY t.EMAIL, o.REALIZADO_MANUAL, o.MOTIVO

        UNION ALL

        -- Membros do RLS do gestor GD que ainda nao estao no RI
        SELECT
            LOWER(rls.CONSULTOREMAIL) AS EMAIL,
            COUNT(DISTINCT g.ID_CONTATO) AS REALIZADO_AUTO,
            o.REALIZADO_MANUAL,
            o.MOTIVO
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS rls
        JOIN SUPERSET.COMISSOES.PARAMETROS p_gest
            ON LOWER(p_gest.EMAIL) = LOWER(rls.USUARIOEMAIL)
            AND p_gest.ANO = {ano} AND p_gest.MES = {mes}
            AND p_gest.IS_GESTOR = TRUE AND LOWER(p_gest.CARGO) LIKE '%demand generation%'
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD g
            ON LOWER(g.PROPRIETARIO) = LOWER(rls.CONSULTOREMAIL)
            AND YEAR(g.DATA_QUALIFICACAO) = {ano} AND MONTH(g.DATA_QUALIFICACAO) = {mes}
        LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
            ON o.ANO = {ano} AND o.MES = {mes} AND LOWER(o.EMAIL) = LOWER(rls.CONSULTOREMAIL)
        LEFT JOIN ri_emails ri_excl ON ri_excl.EMAIL = LOWER(rls.CONSULTOREMAIL)
        WHERE rls.ANO = {ano} AND rls.MES = {mes}
            AND rls.CONSULTOREMAIL IS NOT NULL
            AND LOWER(rls.CONSULTOREMAIL) != LOWER(rls.USUARIOEMAIL)
            AND ri_excl.EMAIL IS NULL
        GROUP BY rls.CONSULTOREMAIL, o.REALIZADO_MANUAL, o.MOTIVO

        UNION ALL

        -- Gestores GD: realizado = soma COALESCE(override, opps) do time (via CTEs)
        SELECT
            gg.EMAIL,
            rg.REALIZADO_AUTO,
            o.REALIZADO_MANUAL,
            o.MOTIVO
        FROM gestores_gd gg
        LEFT JOIN realizado_gest rg ON rg.GEST_EMAIL = gg.EMAIL
        LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
            ON o.ANO = {ano} AND o.MES = {mes} AND LOWER(o.EMAIL) = gg.EMAIL

        ORDER BY EMAIL
    """).to_pandas()


ano, mes = render_period_filter()
st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Por padrão o realizado GD é contado automaticamente (Opps distintos). Use esta página para sobrescrever o valor de um consultor.</div>", unsafe_allow_html=True)

# ── Realizado automatico vs override ─────────────────────────────────────────

try:
    auto_df = _load_realizado_gd(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if auto_df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum consultor GD encontrado para este período.</div>", unsafe_allow_html=True)
else:
    html_table(auto_df.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE")))

# ── Formulario ────────────────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Definir Override</div>", unsafe_allow_html=True)

consultores = auto_df["EMAIL"].tolist() if not auto_df.empty else []

col1, col2, col3 = st.columns([3, 1, 2])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Consultor</label>", unsafe_allow_html=True)
email_sel   = col1.selectbox("", [""] + consultores, label_visibility="collapsed")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Realizado Manual (Opps)</label>", unsafe_allow_html=True)
_raw_realizado = col2.text_input("", value="0", key="realizado_v", label_visibility="collapsed")
col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Motivo</label>", unsafe_allow_html=True)
motivo_v    = col3.text_input("", placeholder="ex: ajuste por cancelamento", label_visibility="collapsed")

try:
    _real_prev = max(0, int(float(_raw_realizado.replace(",", "."))))
    st.markdown(f"<span style='color:#6b7280;font-size:0.85rem;'>→ {_real_prev} Opp{'s' if _real_prev != 1 else ''}</span>", unsafe_allow_html=True)
except ValueError:
    pass

if email_sel and st.button("Salvar Override", type="primary"):
    try:
        realizado_v = max(0, int(float(_raw_realizado.replace(",", "."))))
    except ValueError:
        st.error("Insira um valor numérico válido.")
        st.stop()
    em = email_sel.replace("'", "''")
    mot = motivo_v.strip().replace("'", "''")
    session.sql(f"""
        MERGE INTO SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE AS t
        USING (SELECT {ano} AS ANO, {mes} AS MES, '{em}' AS EMAIL,
                      {realizado_v} AS REALIZADO_MANUAL,
                      '{mot}' AS MOTIVO) AS s
        ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
        WHEN MATCHED THEN UPDATE SET
            REALIZADO_MANUAL = s.REALIZADO_MANUAL, MOTIVO = s.MOTIVO,
            UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (ANO, MES, EMAIL, REALIZADO_MANUAL, MOTIVO, UPDATED_BY, UPDATED_AT)
        VALUES (s.ANO, s.MES, s.EMAIL, s.REALIZADO_MANUAL, s.MOTIVO, {_autor_sql}, CURRENT_TIMESTAMP())
    """).collect()
    st.success(f"Override de **{email_sel}** salvo: {realizado_v} Opps.")
    st.cache_data.clear()
    compat_rerun()

# ── Remover override ──────────────────────────────────────────────────────────

overrides = auto_df[auto_df["REALIZADO_MANUAL"].notna()] if not auto_df.empty else pd.DataFrame()
if not overrides.empty:
    compat_divider()
    emails_rm = overrides["EMAIL"].tolist()
    col1, col2 = st.columns([3, 1])
    col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Remover override de</label>", unsafe_allow_html=True)
    email_rm = col1.selectbox("", emails_rm, key="rm_gd", label_visibility="collapsed")
    _confirm_key = "_confirm_rm_gd"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção do override de **{email_rm}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_gd"):
            em = email_rm.replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE
                WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = LOWER('{em}')
            """).collect()
            del st.session_state[_confirm_key]
            st.success("Override removido.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_gd"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif col2.button("Remover Override", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()


