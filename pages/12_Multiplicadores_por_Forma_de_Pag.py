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
render_banner("Multiplicadores por Forma de Pag.")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_multiplicadores(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EQUIPE, A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE
        FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EQUIPE
    """).to_pandas()

from utils.connection import MESES_NOME as MESES

ano, mes = render_period_filter()

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_multiplicadores(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum multiplicador cadastrado para este período.</div>", unsafe_allow_html=True)
else:
    html_table(df.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE").replace("Cc", "CC")))

# ── Remover equipe ────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Equipe</div>", unsafe_allow_html=True)
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Equipe para remover</label>", unsafe_allow_html=True)
    equipe_rem = st.selectbox("", [""] + df["EQUIPE"].tolist(), key="rem_equipe", label_visibility="collapsed")
    _confirm_key = "_confirm_rm_equipe"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção de **{equipe_rem}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_equipe"):
            equipe_rem_safe = equipe_rem.replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
                WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{equipe_rem_safe}'
            """).collect()
            del st.session_state[_confirm_key]
            st.success(f"Multiplicadores de **{equipe_rem}** removidos de {MESES.get(mes, mes)}/{ano}.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_equipe"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif equipe_rem and st.button("Remover Equipe", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()

# ── Formulario de edicao ──────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar / Atualizar</div>", unsafe_allow_html=True)

equipes_metas_df = session.sql(f"""
    SELECT DISTINCT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = {ano} AND MES = {mes}
    ORDER BY EQUIPE
""").to_pandas()
equipes_cadastradas = df["EQUIPE"].tolist() if not df.empty else []
equipes = sorted(set(
    (equipes_metas_df["EQUIPE"].tolist() if not equipes_metas_df.empty else [])
    + equipes_cadastradas
))

_NOVA = "-- Digitar nova equipe --"
st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Equipe</label>", unsafe_allow_html=True)
equipe_dropdown = st.selectbox("", [""] + equipes + [_NOVA], label_visibility="collapsed")
if equipe_dropdown == _NOVA:
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Nome da nova equipe</label>", unsafe_allow_html=True)
    equipe_sel = st.text_input("", placeholder="ex: SDR", label_visibility="collapsed").strip()
else:
    equipe_sel = equipe_dropdown

if equipe_sel:
    equipe_safe = equipe_sel.replace("'", "''")
    row_df = session.sql(f"""
        SELECT A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE
        FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
        WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{equipe_safe}'
    """).to_pandas()
    r = row_df.iloc[0] if not row_df.empty else None

    def _v(col, default=1.0):
        if r is None:
            return default
        val = r[col]
        return float(val) if val is not None else default

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>À Vista</label>", unsafe_allow_html=True)
    _raw_av   = col1.text_input("", value=f"{_v('A_VISTA'):.2f}".replace(".", ","),    key="av_v", label_visibility="collapsed")
    col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>CC até 3x</label>", unsafe_allow_html=True)
    _raw_cc3  = col2.text_input("", value=f"{_v('CC_ATE_3X'):.2f}".replace(".", ","),  key="cc3_v", label_visibility="collapsed")
    col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>CC até 12x</label>", unsafe_allow_html=True)
    _raw_cc12 = col3.text_input("", value=f"{_v('CC_ATE_12X'):.2f}".replace(".", ","), key="cc12_v", label_visibility="collapsed")
    col4.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Recorrente</label>", unsafe_allow_html=True)
    _raw_rec  = col4.text_input("", value=f"{_v('RECORRENTE'):.2f}".replace(".", ","), key="rec_v", label_visibility="collapsed")

    try:
        _av_p   = float(_raw_av.replace(",", "."))
        _cc3_p  = float(_raw_cc3.replace(",", "."))
        _cc12_p = float(_raw_cc12.replace(",", "."))
        _rec_p  = float(_raw_rec.replace(",", "."))
        st.caption(
            f"→ À vista: {_av_p:.2f}×  |  CC 3×: {_cc3_p:.2f}×  |  "
            f"CC 12×: {_cc12_p:.2f}×  |  Recorrente: {_rec_p:.2f}×".replace(".", ",")
        )
    except ValueError:
        pass

    if st.button("Salvar Multiplicadores", type="primary"):
        try:
            av_v   = max(0.0, min(5.0, float(_raw_av.replace(",", "."))))
            cc3_v  = max(0.0, min(5.0, float(_raw_cc3.replace(",", "."))))
            cc12_v = max(0.0, min(5.0, float(_raw_cc12.replace(",", "."))))
            rec_v  = max(0.0, min(5.0, float(_raw_rec.replace(",", "."))))
        except ValueError:
            st.error("Insira valores numéricos válidos.")
            st.stop()
        session.sql(f"""
            MERGE INTO SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO AS t
            USING (SELECT {ano} AS ANO, {mes} AS MES,
                          '{equipe_safe}' AS EQUIPE,
                          {av_v} AS A_VISTA, {cc3_v} AS CC_ATE_3X,
                          {cc12_v} AS CC_ATE_12X, {rec_v} AS RECORRENTE) AS s
            ON t.ANO = s.ANO AND t.MES = s.MES AND t.EQUIPE = s.EQUIPE
            WHEN MATCHED THEN UPDATE SET
                A_VISTA = s.A_VISTA, CC_ATE_3X = s.CC_ATE_3X,
                CC_ATE_12X = s.CC_ATE_12X, RECORRENTE = s.RECORRENTE,
                UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (ANO, MES, EQUIPE, A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE, UPDATED_BY, UPDATED_AT)
            VALUES (s.ANO, s.MES, s.EQUIPE, s.A_VISTA, s.CC_ATE_3X, s.CC_ATE_12X, s.RECORRENTE, {_autor_sql}, CURRENT_TIMESTAMP())
        """).collect()
        st.success(f"Multiplicadores de **{equipe_sel}** salvos para {MESES.get(mes, mes)}/{ano}.")
        st.cache_data.clear()
        compat_rerun()

# ── Copiar mes anterior ───────────────────────────────────────────────────────

compat_divider()
with st.expander("Copiar do mês anterior", expanded=False):
    mes_orig = mes - 1 if mes > 1 else 12
    ano_orig = ano if mes > 1 else ano - 1

    df_orig = session.sql(f"""
        SELECT EQUIPE, A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE
        FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
        WHERE ANO = {ano_orig} AND MES = {mes_orig}
        ORDER BY EQUIPE
    """).to_pandas()

    if df_orig.empty:
        st.markdown(f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Sem dados em {MESES.get(mes_orig, mes_orig)}/{ano_orig} para copiar.</div>", unsafe_allow_html=True)
    else:
        html_table(df_orig.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE").replace("Cc", "CC")))
        btn_label = f"Copiar {len(df_orig)} equipes de {MESES.get(mes_orig, mes_orig)}/{ano_orig} para {MESES.get(mes, mes)}/{ano}"
        if st.button(btn_label):
            vals = ", ".join(
                f"({ano}, {mes}, '{str(r['EQUIPE']).replace(chr(39), chr(39)*2)}', {r['A_VISTA']}, {r['CC_ATE_3X']}, {r['CC_ATE_12X']}, {r['RECORRENTE']})"
                for _, r in df_orig.iterrows()
            )
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO AS t
                USING (
                    SELECT v.c1 AS ANO, v.c2 AS MES, v.c3 AS EQUIPE,
                           v.c4 AS A_VISTA, v.c5 AS CC_ATE_3X,
                           v.c6 AS CC_ATE_12X, v.c7 AS RECORRENTE
                    FROM (VALUES {vals}) AS v(c1, c2, c3, c4, c5, c6, c7)
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES AND t.EQUIPE = s.EQUIPE
                WHEN MATCHED THEN UPDATE SET
                    A_VISTA = s.A_VISTA, CC_ATE_3X = s.CC_ATE_3X,
                    CC_ATE_12X = s.CC_ATE_12X, RECORRENTE = s.RECORRENTE,
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (ANO, MES, EQUIPE, A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE, UPDATED_BY, UPDATED_AT)
                VALUES (s.ANO, s.MES, s.EQUIPE, s.A_VISTA, s.CC_ATE_3X, s.CC_ATE_12X, s.RECORRENTE, {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.success(f"{len(df_orig)} equipes copiadas.")
            st.cache_data.clear()
            compat_rerun()


