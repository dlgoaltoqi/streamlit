import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin_or_gestor, is_admin, audit_user_sql
from utils.ui import html_table, render_css, render_banner

render_css()
render_banner("Patamares Saving")

session = get_session()

require_admin_or_gestor(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)
_is_admin_user = is_admin(session)

@st.cache_data(ttl=3000)
def _load_patamares(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EQUIPE, PATAMAR, PERCENTUAL
        FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EQUIPE, PATAMAR
    """).to_pandas()

from utils.connection import MESES_NOME as MESES

ano, mes = render_period_filter()

def _pct(v):
    """Formata decimal (0.60) como percentual com 2 casas: '60,00%'."""
    return f"{float(v)*100:.2f}%".replace(".", ",")

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_patamares(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum patamar cadastrado para este período.</div>", unsafe_allow_html=True)
else:
    df_disp = df.copy()
    df_disp["PATAMAR"]    = df_disp["PATAMAR"].map(_pct)
    df_disp["PERCENTUAL"] = df_disp["PERCENTUAL"].map(_pct)
    html_table(df_disp.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE")))

# ── Formulario (apenas admin) ─────────────────────────────────────────────────

if _is_admin_user:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar / Atualizar Patamar</div>", unsafe_allow_html=True)

    equipes_df = session.sql(f"""
        SELECT DISTINCT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EQUIPE
    """).to_pandas()
    equipes = equipes_df["EQUIPE"].tolist() if not equipes_df.empty else []

    col1, col2, col3 = st.columns([2, 1, 1])
    col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Equipe</label>", unsafe_allow_html=True)
    equipe_sel = col1.selectbox("", [""] + equipes, label_visibility="collapsed")

    col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Patamar (%)</label>", unsafe_allow_html=True)
    _pat_raw = col2.text_input("", value="60,00", key="patamar_pct", label_visibility="collapsed")

    col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>% do OTE pago</label>", unsafe_allow_html=True)
    _perc_raw = col3.text_input("", value="55,00", key="percentual_pct", label_visibility="collapsed")

    try:
        _pat_p  = float(_pat_raw.replace(",", "."))
        _perc_p = float(_perc_raw.replace(",", "."))
        st.markdown(
            f"<span style='color:#6b7280;font-size:0.85rem;'>→ Atingimento de {_pat_p:.2f}% → paga {_perc_p:.2f}% do OTE</span>".replace(".", ","),
            unsafe_allow_html=True,
        )
    except ValueError:
        pass

    if equipe_sel and st.button("Salvar Patamar", type="primary"):
        try:
            patamar_pct   = max(0.0, min(200.0, float(_pat_raw.replace(",", "."))))
            percentual_pct = max(0.0, min(200.0, float(_perc_raw.replace(",", "."))))
        except ValueError:
            st.error("Insira valores numéricos válidos.")
            st.stop()
        patamar_v    = patamar_pct / 100
        percentual_v = percentual_pct / 100
        eq = equipe_sel.replace("'", "''")
        session.sql(f"""
            MERGE INTO SUPERSET.COMISSOES.PATAMARES_COMISSAO AS t
            USING (SELECT {ano} AS ANO, {mes} AS MES,
                          '{eq}' AS EQUIPE,
                          {patamar_v} AS PATAMAR,
                          {percentual_v} AS PERCENTUAL) AS s
            ON t.ANO = s.ANO AND t.MES = s.MES
               AND t.EQUIPE = s.EQUIPE AND t.PATAMAR = s.PATAMAR
            WHEN MATCHED THEN UPDATE SET PERCENTUAL = s.PERCENTUAL,
                UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (ANO, MES, EQUIPE, PATAMAR, PERCENTUAL, UPDATED_BY, UPDATED_AT)
            VALUES (s.ANO, s.MES, s.EQUIPE, s.PATAMAR, s.PERCENTUAL, {_autor_sql}, CURRENT_TIMESTAMP())
        """).collect()
        st.success(f"Patamar {patamar_pct:.2f}% de **{equipe_sel}** salvo.")
        st.cache_data.clear()
        compat_rerun()

    # ── Remover patamar ───────────────────────────────────────────────────────
    if not df.empty:
        compat_divider()
        st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Patamar</div>", unsafe_allow_html=True)
        col1, col2 = st.columns([2, 1])
        col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Equipe</label>", unsafe_allow_html=True)
        equipe_rm = col1.selectbox("", df["EQUIPE"].unique().tolist(), key="rm_eq", label_visibility="collapsed")
        df_eq = df[df["EQUIPE"] == equipe_rm]
        pat_opts = [float(p) for p in df_eq["PATAMAR"].tolist()]
        col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Patamar</label>", unsafe_allow_html=True)
        patamar_rm = col2.selectbox("", pat_opts, format_func=lambda v: f"{v*100:.2f}".replace(".", ",") + "%", key="rm_pat", label_visibility="collapsed")
        _confirm_key = "_confirm_rm_patamar"
        if st.session_state.get(_confirm_key):
            st.warning(f"Confirma a remoção do patamar **{patamar_rm*100:.2f}%** de **{equipe_rm}**?".replace(".", ","))
            _cy, _cn = st.columns([1, 5])
            if _cy.button("Confirmar", key="_confirm_yes_patamar"):
                eq = equipe_rm.replace("'", "''")
                session.sql(f"""
                    DELETE FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
                    WHERE ANO = {ano} AND MES = {mes}
                      AND EQUIPE = '{eq}' AND PATAMAR = {patamar_rm}
                """).collect()
                del st.session_state[_confirm_key]
                st.success("Patamar removido.")
                st.cache_data.clear()
                compat_rerun()
            if _cn.button("Cancelar", key="_confirm_no_patamar"):
                del st.session_state[_confirm_key]
                compat_rerun()
        elif st.button("Remover", type="secondary"):
            st.session_state[_confirm_key] = True
            compat_rerun()

    # ── Copiar mes anterior ───────────────────────────────────────────────────
    compat_divider()
    with st.expander("Copiar do mês anterior", expanded=False):
        mes_orig = mes - 1 if mes > 1 else 12
        ano_orig = ano if mes > 1 else ano - 1

        df_orig = session.sql(f"""
            SELECT EQUIPE, PATAMAR, PERCENTUAL
            FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
            WHERE ANO = {ano_orig} AND MES = {mes_orig}
            ORDER BY EQUIPE, PATAMAR
        """).to_pandas()

        if df_orig.empty:
            st.markdown(f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Sem patamares em {MESES.get(mes_orig, mes_orig)}/{ano_orig}.</div>", unsafe_allow_html=True)
        else:
            df_o = df_orig.copy()
            df_o["PATAMAR"]    = df_o["PATAMAR"].map(_pct)
            df_o["PERCENTUAL"] = df_o["PERCENTUAL"].map(_pct)
            html_table(df_o.rename(columns=lambda c: c.replace("_", " ").title().replace("Ote", "OTE")))
            lbl = f"Copiar {len(df_orig)} patamares de {MESES.get(mes_orig, mes_orig)}/{ano_orig} para {MESES.get(mes, mes)}/{ano}"
            if st.button(lbl):
                vals = ", ".join(
                    f"({ano}, {mes}, '{str(r['EQUIPE']).replace(chr(39), chr(39)*2)}', {r['PATAMAR']}, {r['PERCENTUAL']})"
                    for _, r in df_orig.iterrows()
                )
                session.sql(f"""
                    MERGE INTO SUPERSET.COMISSOES.PATAMARES_COMISSAO AS t
                    USING (
                        SELECT v.c1 AS ANO, v.c2 AS MES, v.c3 AS EQUIPE, v.c4 AS PATAMAR, v.c5 AS PERCENTUAL
                        FROM (VALUES {vals}) AS v(c1, c2, c3, c4, c5)
                    ) AS s
                    ON t.ANO = s.ANO AND t.MES = s.MES
                       AND t.EQUIPE = s.EQUIPE AND t.PATAMAR = s.PATAMAR
                    WHEN MATCHED THEN UPDATE SET PERCENTUAL = s.PERCENTUAL,
                        UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (ANO, MES, EQUIPE, PATAMAR, PERCENTUAL, UPDATED_BY, UPDATED_AT)
                    VALUES (s.ANO, s.MES, s.EQUIPE, s.PATAMAR, s.PERCENTUAL, {_autor_sql}, CURRENT_TIMESTAMP())
                """).collect()
                st.success(f"{len(df_orig)} patamares copiados.")
                st.cache_data.clear()
                compat_rerun()


