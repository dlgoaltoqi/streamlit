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
render_banner("Ajustes Pontuais de Comissão")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

from utils.connection import MESES_ABREV

def _brl(v):
    if v is None:
        return "—"
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _ref_label(ref_ano, ref_mes):
    if ref_mes and ref_ano:
        return f"{MESES_ABREV.get(int(ref_mes), ref_mes)}/{int(ref_ano)}"
    return "—"

@st.cache_data(ttl=3000)
def _load_ajustes(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT ID, EMAIL, VALOR, DESCRICAO, REF_ANO, REF_MES, CREATED_BY, CREATED_AT
        FROM SUPERSET.COMISSOES.AJUSTES_PONTUAIS
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EMAIL, ID
    """).to_pandas()

ano, mes = render_period_filter()

# ── Tabela atual ──────────────────────────────────────────────────────────────

try:
    df = _load_ajustes(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

if df.empty:
    st.markdown("<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>Nenhum ajuste cadastrado para este período.</div>", unsafe_allow_html=True)
else:
    df_disp = df.copy()
    df_disp["VALOR"]      = df_disp["VALOR"].apply(_brl)
    df_disp["REF. MÊS"]   = df_disp.apply(lambda r: _ref_label(r["REF_ANO"], r["REF_MES"]), axis=1)
    df_disp["CREATED_AT"] = df_disp["CREATED_AT"].apply(lambda v: str(v)[:16] if v else "—")
    html_table(df_disp[["ID", "EMAIL", "VALOR", "DESCRICAO", "REF. MÊS", "CREATED_BY", "CREATED_AT"]].rename(columns={
        "ID": "ID", "EMAIL": "E-mail", "VALOR": "Valor", "DESCRICAO": "Descrição",
        "REF. MÊS": "Ref. Mês", "CREATED_BY": "Criado por", "CREATED_AT": "Criado em",
    }))

# ── Formulário de adição ───────────────────────────────────────────────────────

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Adicionar Ajuste</div>", unsafe_allow_html=True)

emails_df = session.sql(f"""
    SELECT DISTINCT CONSULTOR AS EMAIL
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = {ano} AND MES = {mes}
    UNION
    SELECT DISTINCT EMAIL
    FROM SUPERSET.COMISSOES.PARAMETROS
    WHERE ANO = {ano} AND MES = {mes}
    ORDER BY EMAIL
""").to_pandas()
emails = emails_df["EMAIL"].tolist() if not emails_df.empty else []

_NOVO = "-- Digitar novo e-mail --"
st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Consultor</label>", unsafe_allow_html=True)
email_dropdown = st.selectbox("", [""] + emails + [_NOVO], label_visibility="collapsed", key="aj_email_dd")
if email_dropdown == _NOVO:
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>E-mail do consultor</label>", unsafe_allow_html=True)
    email_sel = st.text_input("", placeholder="nome@empresa.com", label_visibility="collapsed", key="aj_email_txt").strip().lower()
else:
    email_sel = email_dropdown or ""

col1, col2, col3, col4 = st.columns([1.5, 1, 1, 1])
col1.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Descrição</label>", unsafe_allow_html=True)
_raw_desc   = col1.text_input("", placeholder="Ex: Correção parâmetro abr/2026", label_visibility="collapsed", key="aj_desc")
col2.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Valor (R$)</label>", unsafe_allow_html=True)
_raw_valor  = col2.text_input("", value="0,00", label_visibility="collapsed", key="aj_valor")
col3.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Ref. Ano</label>", unsafe_allow_html=True)
_raw_refano = col3.text_input("", value=str(ano), label_visibility="collapsed", key="aj_refano")
col4.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Ref. Mês</label>", unsafe_allow_html=True)
_raw_refmes = col4.text_input("", value=str(mes - 1 if mes > 1 else 12), label_visibility="collapsed", key="aj_refmes")

try:
    _valor_p   = float(_raw_valor.replace(",", "."))
    _refano_p  = int(_raw_refano) if _raw_refano.strip() else None
    _refmes_p  = int(_raw_refmes) if _raw_refmes.strip() else None
    st.caption(f"→ Valor: {_brl(_valor_p)}  |  Ref.: {_ref_label(_refano_p, _refmes_p)}")
except (ValueError, TypeError):
    pass

if email_sel and st.button("Adicionar Ajuste", type="primary"):
    try:
        valor_v  = float(_raw_valor.replace(",", "."))
        refano_v = int(_raw_refano) if _raw_refano.strip() else None
        refmes_v = int(_raw_refmes) if _raw_refmes.strip() else None
    except ValueError:
        st.error("Insira valores numéricos válidos.")
        st.stop()
    desc_v = (_raw_desc.strip() or None)
    em     = email_sel.replace("'", "''")
    desc_s = f"'{desc_v.replace(chr(39), chr(39)+chr(39))}'" if desc_v else "NULL"
    refano_s = str(refano_v) if refano_v else "NULL"
    refmes_s = str(refmes_v) if refmes_v else "NULL"
    session.sql(f"""
        INSERT INTO SUPERSET.COMISSOES.AJUSTES_PONTUAIS
            (ANO, MES, EMAIL, VALOR, DESCRICAO, REF_ANO, REF_MES, CREATED_BY, CREATED_AT)
        VALUES
            ({ano}, {mes}, '{em}', {valor_v}, {desc_s}, {refano_s}, {refmes_s},
             {_autor_sql}, CURRENT_TIMESTAMP())
    """).collect()
    st.success(f"Ajuste de {_brl(valor_v)} adicionado para **{email_sel}**.")
    st.cache_data.clear()
    compat_rerun()

# ── Remover ───────────────────────────────────────────────────────────────────

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0 0.25rem;'>Remover Ajuste</div>", unsafe_allow_html=True)

    opcoes = {
        f"ID {int(r['ID'])} | {r['EMAIL']} | {_brl(r['VALOR'])} | {r['DESCRICAO'] or '—'}": int(r["ID"])
        for _, r in df.iterrows()
    }
    st.markdown("<label style='color:#1a1a1a;font-weight:700;font-size:0.875rem;display:block;margin-bottom:4px;'>Ajuste a remover</label>", unsafe_allow_html=True)
    rm_label = st.selectbox("", list(opcoes.keys()), label_visibility="collapsed", key="aj_rm_sel")
    rm_id    = opcoes[rm_label]

    _confirm_key = "_confirm_rm_ajuste"
    if st.session_state.get(_confirm_key):
        st.warning(f"Confirma a remoção do ajuste **{rm_label}**?")
        _cy, _cn = st.columns([1, 5])
        if _cy.button("Confirmar", key="_confirm_yes_ajuste"):
            session.sql(f"DELETE FROM SUPERSET.COMISSOES.AJUSTES_PONTUAIS WHERE ID = {rm_id}").collect()
            del st.session_state[_confirm_key]
            st.success("Ajuste removido.")
            st.cache_data.clear()
            compat_rerun()
        if _cn.button("Cancelar", key="_confirm_no_ajuste"):
            del st.session_state[_confirm_key]
            compat_rerun()
    elif st.button("Remover Ajuste", type="secondary"):
        st.session_state[_confirm_key] = True
        compat_rerun()


