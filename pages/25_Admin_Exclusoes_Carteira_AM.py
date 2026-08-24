import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session

from utils.connection import get_session, compat_rerun, compat_divider, require_admin, audit_user_sql
from utils.commission import _AM_CONTRATOS_BRUTA_SQL
from utils.ui import html_table, render_css, render_banner


_TABELA = "SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM"


render_css()
render_banner("Exclusões da Carteira AM")

session = get_session()
require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)


@st.cache_data(ttl=3000)
def _load_exclusoes() -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT ID_CONTRATO, SOLICITADO_POR, MOTIVO, CREATED_BY,
               CONVERT_TIMEZONE('America/Sao_Paulo', CREATED_AT) AS CREATED_AT
        FROM {_TABELA}
        ORDER BY CREATED_AT DESC, ID_CONTRATO
    """).to_pandas()


try:
    df = _load_exclusoes()
except Exception as exc:
    st.error(f"Erro ao carregar exclusões da carteira AM: {exc}")
    st.stop()

st.markdown(
    "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
    "padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0 1rem;'>"
    "Contratos cadastrados aqui são retirados da carteira AM ao vivo: não "
    "entram no MRR Inicial, no MRR Evoluído ou no churn. Períodos já fechados "
    "precisam ser reabertos e fechados novamente para refletir a mudança.</div>",
    unsafe_allow_html=True,
)

if df.empty:
    st.markdown(
        "<div style='color:#1a1a1a;margin:0.5rem 0 1rem;'>"
        "Nenhuma exclusão cadastrada.</div>",
        unsafe_allow_html=True,
    )
else:
    d = df.copy()
    d["CREATED_AT"] = d["CREATED_AT"].apply(lambda value: str(value)[:16] if value else "")
    html_table(d.rename(columns={
        "ID_CONTRATO": "ID do Contrato",
        "SOLICITADO_POR": "Solicitado por",
        "MOTIVO": "Motivo",
        "CREATED_BY": "Cadastrado por",
        "CREATED_AT": "Cadastrado em",
    }))

compat_divider()
st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0;'>Adicionar Exclusão</div>", unsafe_allow_html=True)

with st.form("form_exclusao_carteira_am", clear_on_submit=True):
    id_contrato = st.text_input("ID do contrato", placeholder="Ex.: 39476989771").strip()
    solicitado_por = st.text_input("Quem solicitou a exclusão", placeholder="Nome ou área solicitante").strip()
    motivo = st.text_area("Motivo", placeholder="Descreva por que o contrato não deve compor a carteira AM.").strip()
    submitted = st.form_submit_button("Adicionar Exclusão", type="primary")

if submitted:
    if not re.fullmatch(r"\d+", id_contrato):
        st.error("Informe um ID de contrato numérico válido.")
        st.stop()
    if not solicitado_por or not motivo:
        st.error("Informe quem solicitou a exclusão e o motivo.")
        st.stop()

    id_sql = id_contrato.replace("'", "''")
    solicitado_sql = solicitado_por.replace("'", "''")
    motivo_sql = motivo.replace("'", "''")

    contrato_df = session.sql(f"""
        WITH contratos AS ({_AM_CONTRATOS_BRUTA_SQL})
        SELECT CONTRATO AS ID_CONTRATO, NUM_CONTRATO, GERENTE
        FROM contratos
        WHERE CONTRATO = '{id_sql}'
        LIMIT 1
    """).to_pandas()
    if contrato_df.empty:
        st.error("O ID não pertence a uma carteira AM ativa no mapeamento atual.")
        st.stop()

    existe_df = session.sql(f"""
        SELECT 1
        FROM {_TABELA}
        WHERE ID_CONTRATO = '{id_sql}'
        LIMIT 1
    """).to_pandas()
    if not existe_df.empty:
        st.warning("Esse contrato já está excluído da carteira AM.")
        st.stop()

    session.sql(f"""
        INSERT INTO {_TABELA}
            (ID_CONTRATO, SOLICITADO_POR, MOTIVO, CREATED_BY, CREATED_AT)
        VALUES
            ('{id_sql}', '{solicitado_sql}', '{motivo_sql}',
             {_autor_sql}, CURRENT_TIMESTAMP())
    """).collect()
    st.cache_data.clear()
    st.success(
        f"Contrato {contrato_df.iloc[0]['NUM_CONTRATO']} excluído da carteira "
        f"de {contrato_df.iloc[0]['GERENTE']}."
    )
    compat_rerun()

if not df.empty:
    compat_divider()
    st.markdown("<div style='font-size:1.17rem;color:#1a1a1a;font-weight:700;margin:0.5rem 0;'>Remover Exclusão</div>", unsafe_allow_html=True)
    opcoes = {
        f"{row['ID_CONTRATO']} | {row['SOLICITADO_POR']} | {row['MOTIVO']}": row["ID_CONTRATO"]
        for _, row in df.iterrows()
    }
    escolha = st.selectbox("Contrato excluído", list(opcoes), key="exclusao_am_remover")
    id_remover = opcoes[escolha]
    confirm_key = "_confirmar_remocao_exclusao_am"

    if st.session_state.get(confirm_key):
        st.warning(f"Confirma a remoção da exclusão do contrato {id_remover}?")
        confirmar, cancelar = st.columns([1, 5])
        if confirmar.button("Confirmar", key="confirmar_exclusao_am"):
            _id_rem_sql = str(id_remover).replace("'", "''")
            session.sql(f"DELETE FROM {_TABELA} WHERE ID_CONTRATO = '{_id_rem_sql}'").collect()
            del st.session_state[confirm_key]
            st.cache_data.clear()
            st.success("Exclusão removida.")
            compat_rerun()
        if cancelar.button("Cancelar", key="cancelar_exclusao_am"):
            del st.session_state[confirm_key]
            compat_rerun()
    elif st.button("Remover Exclusão", type="secondary"):
        st.session_state[confirm_key] = True
        compat_rerun()


