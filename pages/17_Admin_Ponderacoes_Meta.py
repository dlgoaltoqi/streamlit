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
render_banner("Ponderações de Meta")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_ponderacoes(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EMAIL, TIPO_META, PONDERACAO
        FROM SUPERSET.COMISSOES.PONDERACOES_META
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EMAIL, TIPO_META
    """).to_pandas()

from utils.connection import MESES_NOME as MESES

TIPOS = ["ARR", "Booking", "MetaAtingida"]

ano, mes = render_period_filter()
st.markdown(
    "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:1rem;"
    "border-left:4px solid #0c5a93;margin:0.5rem 0 1.5rem;line-height:1.7;'>"
    "Define o peso de cada eixo no cálculo de atingimento ponderado.<br><br>"
    "<strong>Consultores B2G:</strong> ARR + Booking<br>"
    "<strong>Gestores B2G:</strong> Booking + MetaAtingida<br><br>"
    "Se não houver registro, os padrões são aplicados:<br>"
    "&nbsp;&nbsp;• ARR = 40% &nbsp;|&nbsp; Booking = 60%<br>"
    "&nbsp;&nbsp;• Booking = 80% &nbsp;|&nbsp; MetaAtingida = 20%"
    "</div>",
    unsafe_allow_html=True,
)

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_ponderacoes(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhuma ponderação cadastrada — padrões em uso.</div>", unsafe_allow_html=True)
else:
    df_disp = df.copy()
    df_disp["PONDERACAO"] = df_disp["PONDERACAO"].map(lambda v: f"{float(v)*100:.2f}%".replace(".", ","))
    html_table(df_disp.rename(columns={"EMAIL": "Email", "TIPO_META": "Tipo de Meta", "PONDERACAO": "Ponderação"}))

# ── Remover ponderacao ────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Ponderação</div>", unsafe_allow_html=True)
    opcoes_rem = [f"{r['EMAIL']} — {r['TIPO_META']}" for _, r in df.iterrows()]
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Registro para remover</label>", unsafe_allow_html=True)
    sel_rem = st.selectbox("", [""] + opcoes_rem, key="rem_pond", label_visibility="collapsed")
    _confirm_key = "_confirm_rm_pond"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção de **{sel_rem}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_pond"):
            email_rem, tipo_rem = [x.strip() for x in sel_rem.split("—")]
            email_rem_safe = email_rem.replace("'", "''")
            tipo_rem_safe  = tipo_rem.replace("'", "''")
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.PONDERACOES_META
                WHERE ANO = {ano} AND MES = {mes}
                  AND LOWER(EMAIL) = '{email_rem_safe.lower()}'
                  AND TIPO_META = '{tipo_rem_safe}'
            """).collect()
            del st.session_state[_confirm_key]
            st.success(f"Ponderação **{tipo_rem}** de **{email_rem}** removida.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_pond"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif sel_rem and st.button("Remover", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()

# ── Formulario ────────────────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar / Atualizar</div>", unsafe_allow_html=True)

consultores_df = session.sql(f"""
    SELECT DISTINCT CONSULTOR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = {ano} AND MES = {mes}
      AND LOWER(EQUIPE) IN ('b2g', 'governo')
    ORDER BY CONSULTOR
""").to_pandas()
consultores = consultores_df["CONSULTOR"].tolist() if not consultores_df.empty else []

col1, col2, col3 = st.columns([3, 1, 1])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Consultor/Gestor</label>", unsafe_allow_html=True)
email_sel = col1.selectbox("", [""] + consultores, label_visibility="collapsed")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Tipo</label>", unsafe_allow_html=True)
tipo_sel  = col2.selectbox("", TIPOS, label_visibility="collapsed", key="tipo_sel")
col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Ponderação (%)</label>", unsafe_allow_html=True)
_raw_pond_pct = col3.text_input("", value="50,00", key="pond_pct", label_visibility="collapsed")

try:
    pond_pct = max(0.0, min(100.0, float(_raw_pond_pct.replace(",", "."))))
except ValueError:
    pond_pct = 50.0
pond_v = pond_pct / 100
st.markdown(f"<span style='color:#6b7280;font-size:0.85rem;'>→ {pond_pct:.2f}%</span>".replace(".", ","), unsafe_allow_html=True)

if email_sel and st.button("Salvar", type="primary"):
    try:
        pond_pct = max(0.0, min(100.0, float(_raw_pond_pct.replace(",", "."))))
    except ValueError:
        st.error("Insira um valor numérico válido.")
        st.stop()
    pond_v = pond_pct / 100
    em = email_sel.replace("'", "''")
    session.sql(f"""
        MERGE INTO SUPERSET.COMISSOES.PONDERACOES_META AS t
        USING (SELECT {ano} AS ANO, {mes} AS MES, '{em}' AS EMAIL,
                      '{tipo_sel}' AS TIPO_META, {pond_v} AS PONDERACAO) AS s
        ON t.ANO = s.ANO AND t.MES = s.MES
           AND LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.TIPO_META = s.TIPO_META
        WHEN MATCHED THEN UPDATE SET PONDERACAO = s.PONDERACAO,
            UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (ANO, MES, EMAIL, TIPO_META, PONDERACAO, UPDATED_BY, UPDATED_AT)
        VALUES (s.ANO, s.MES, s.EMAIL, s.TIPO_META, s.PONDERACAO, {_autor_sql}, CURRENT_TIMESTAMP())
    """).collect()
    st.success(f"{tipo_sel} de **{email_sel}** salvo: {pond_pct:.2f}%".replace(".", ",") + ".")
    st.cache_data.clear()
    compat_rerun()

# ── Copiar mes anterior ───────────────────────────────────────────────────────

compat_divider()
with st.expander("Copiar do mês anterior", expanded=False):
    mes_orig = mes - 1 if mes > 1 else 12
    ano_orig = ano if mes > 1 else ano - 1

    df_orig = session.sql(f"""
        SELECT EMAIL, TIPO_META, PONDERACAO
        FROM SUPERSET.COMISSOES.PONDERACOES_META
        WHERE ANO = {ano_orig} AND MES = {mes_orig}
        ORDER BY EMAIL, TIPO_META
    """).to_pandas()

    if df_orig.empty:
        st.markdown(f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Sem ponderações em {MESES.get(mes_orig, mes_orig)}/{ano_orig}.</div>", unsafe_allow_html=True)
    else:
        df_o = df_orig.copy()
        df_o["PONDERACAO"] = df_o["PONDERACAO"].map(lambda v: f"{float(v)*100:.0f}".replace(".", ",") + "%")
        html_table(df_o.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE")))
        lbl = f"Copiar {len(df_orig)} registros de {MESES.get(mes_orig, mes_orig)}/{ano_orig} para {MESES.get(mes, mes)}/{ano}"
        if st.button(lbl):
            vals = ", ".join(
                "({}, {}, '{}', '{}', {})".format(
                    ano, mes,
                    str(r["EMAIL"]).replace("'", "''"),
                    str(r["TIPO_META"]).replace("'", "''"),
                    float(r["PONDERACAO"]),
                )
                for _, r in df_orig.iterrows()
            )
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.PONDERACOES_META AS t
                USING (
                    SELECT v.c1 AS ANO, v.c2 AS MES, v.c3 AS EMAIL,
                           v.c4 AS TIPO_META, v.c5 AS PONDERACAO
                    FROM (VALUES {vals}) AS v(c1, c2, c3, c4, c5)
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES
                   AND LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.TIPO_META = s.TIPO_META
                WHEN MATCHED THEN UPDATE SET PONDERACAO = s.PONDERACAO,
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (ANO, MES, EMAIL, TIPO_META, PONDERACAO, UPDATED_BY, UPDATED_AT)
                VALUES (s.ANO, s.MES, s.EMAIL, s.TIPO_META, s.PONDERACAO, {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.success(f"{len(df_orig)} ponderações copiadas.")
            st.cache_data.clear()
            compat_rerun()


