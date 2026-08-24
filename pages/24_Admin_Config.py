import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
from utils.connection import (get_session, compat_rerun, compat_divider,
                              render_period_filter, require_admin, audit_user_sql)
from utils.ui import render_css, render_banner

render_css()
render_banner("Admin — Configurações")

session = get_session()
require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

st.markdown(
    "<div style='color:#1a1a1a;font-weight:700;font-size:1.25rem;margin:0.25rem 0;'>"
    "Configurações do cálculo (com vigência)</div>"
    "<p style='color:#4b5563;font-size:0.875rem;margin:0 0 0.5rem;'>"
    "Cada valor vale <b>a partir</b> de um mês (vigência). O cálculo de um mês usa a "
    "vigência mais recente até ele — alterar uma regra daqui para frente não reescreve "
    "meses passados, e meses fechados (snapshot) são imunes. Chave ausente usa o padrão "
    "do código. <b>Atenção:</b> vários valores alteram comissão do mês aberto.</p>",
    unsafe_allow_html=True,
)

ano, mes = render_period_filter()

from utils.connection import MESES_ABREV as _MESES_N

# ── Valores vigentes para o período selecionado ───────────────────────────────
vig_df = session.sql(f"""
    SELECT CHAVE, VALOR, DESCRICAO, ANO, MES FROM (
        SELECT c.*, ROW_NUMBER() OVER (PARTITION BY CHAVE ORDER BY ANO DESC, MES DESC) AS rn
        FROM SUPERSET.COMISSOES.CONFIG c
        WHERE ANO * 100 + MES <= {ano * 100 + mes}
    ) WHERE rn = 1
    ORDER BY CHAVE
""").to_pandas()

if vig_df.empty:
    st.info("Nenhuma configuração vigente para este período.")
    st.stop()

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
novos = {}
for _, r in vig_df.iterrows():
    chave = str(r["CHAVE"])
    c1, c2 = st.columns([2, 3])
    c1.markdown(
        f"<div style='padding-top:0.55rem;'><span style='color:#1a1a1a;font-weight:700;"
        f"font-size:0.9rem;'>{chave}</span><br>"
        f"<span style='color:#6b7280;font-size:0.78rem;'>{r['DESCRICAO'] or ''} "
        f"— vigente desde {_MESES_N.get(int(r['MES']), r['MES'])}/{int(r['ANO'])}</span></div>",
        unsafe_allow_html=True,
    )
    novos[chave] = c2.text_input(
        chave, value=str(r["VALOR"] or ""), key=f"_cfg_{chave}",
        label_visibility="collapsed",
    )

_alterados = {
    str(r["CHAVE"]): (novos[str(r["CHAVE"])], int(r["ANO"]), int(r["MES"]))
    for _, r in vig_df.iterrows()
    if novos[str(r["CHAVE"])].strip() != str(r["VALOR"] or "").strip()
}

compat_divider()
b1, b2, _sp = st.columns([1.6, 1.9, 2.5])
if b1.button("💾 Salvar na vigência atual", key="_cfg_save_atual",
             use_container_width=True,
             help="Corrige o valor da vigência já existente (ex.: erro de digitação). "
                  "Afeta todos os meses cobertos por ela."):
    if not _alterados:
        st.session_state["_cfg_msg_"] = ("info", "Nenhum valor alterado.")
    else:
        for chave, (valor, a_v, m_v) in _alterados.items():
            ch = chave.replace("'", "''")
            vl = valor.strip().replace("'", "''")
            session.sql(f"""
                UPDATE SUPERSET.COMISSOES.CONFIG
                SET VALOR = '{vl}', UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE CHAVE = '{ch}' AND ANO = {a_v} AND MES = {m_v}
            """).collect()
        st.session_state["_cfg_msg_"] = ("ok", f"{len(_alterados)} valor(es) atualizados na vigência atual.")
        st.cache_data.clear()
    compat_rerun()

if b2.button(f"📅 Nova vigência a partir de {_MESES_N.get(mes, mes)}/{ano}",
             key="_cfg_save_nova", use_container_width=True,
             help="Cria novas linhas valendo do mês selecionado em diante; "
                  "os meses anteriores continuam com a vigência antiga."):
    if not _alterados:
        st.session_state["_cfg_msg_"] = ("info", "Nenhum valor alterado.")
    else:
        for chave, (valor, _a, _m) in _alterados.items():
            ch = chave.replace("'", "''")
            vl = valor.strip().replace("'", "''")
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.CONFIG AS t
                USING (SELECT '{ch}' AS CHAVE, {ano} AS ANO, {mes} AS MES) AS s
                ON t.CHAVE = s.CHAVE AND t.ANO = s.ANO AND t.MES = s.MES
                WHEN MATCHED THEN UPDATE SET VALOR = '{vl}',
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (CHAVE, ANO, MES, VALOR, DESCRICAO, UPDATED_BY, UPDATED_AT)
                VALUES ('{ch}', {ano}, {mes}, '{vl}',
                        (SELECT MAX(DESCRICAO) FROM SUPERSET.COMISSOES.CONFIG WHERE CHAVE = '{ch}'),
                        {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
        st.session_state["_cfg_msg_"] = ("ok", f"Nova vigência {_MESES_N.get(mes, mes)}/{ano} criada para {len(_alterados)} chave(s).")
        st.cache_data.clear()
    compat_rerun()

_msg = st.session_state.pop("_cfg_msg_", None)
if _msg:
    if _msg[0] == "ok":
        st.markdown(
            f"<div style='color:#1a1a1a;background:#dcfce7;border-radius:6px;"
            f"padding:0.6rem 0.9rem;border-left:4px solid #16a34a;margin:0.4rem 0;'>"
            f"✓ {_msg[1]}</div>", unsafe_allow_html=True)
    else:
        st.info(_msg[1])

# ── Nova chave (ex.: gestor_equipes.<email> de um novo gestor multi-equipe) ───
compat_divider()
with st.expander("Adicionar nova chave"):
    n1, n2 = st.columns([2, 3])
    _n_chave = n1.text_input("Chave", key="_cfg_nova_chave",
                             placeholder="ex.: gestor_equipes.fulano@altoqi.com.br")
    _n_valor = n2.text_input("Valor", key="_cfg_novo_valor",
                             placeholder="ex.: FSB,Farmer")
    _n_desc = st.text_input("Descrição", key="_cfg_nova_desc",
                            placeholder="O que esta chave controla")
    if st.button(f"Criar com vigência {_MESES_N.get(mes, mes)}/{ano}", key="_cfg_criar"):
        if not _n_chave.strip() or not _n_valor.strip():
            st.warning("Informe chave e valor.")
        else:
            ch = _n_chave.strip().replace("'", "''")
            vl = _n_valor.strip().replace("'", "''")
            dsc = _n_desc.strip().replace("'", "''")
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.CONFIG AS t
                USING (SELECT '{ch}' AS CHAVE, {ano} AS ANO, {mes} AS MES) AS s
                ON t.CHAVE = s.CHAVE AND t.ANO = s.ANO AND t.MES = s.MES
                WHEN MATCHED THEN UPDATE SET VALOR = '{vl}', DESCRICAO = '{dsc}',
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (CHAVE, ANO, MES, VALOR, DESCRICAO, UPDATED_BY, UPDATED_AT)
                VALUES ('{ch}', {ano}, {mes}, '{vl}', '{dsc}', {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.cache_data.clear()
            st.session_state["_cfg_msg_"] = ("ok", f"Chave '{_n_chave.strip()}' criada.")
            compat_rerun()

# ── Histórico de vigências ────────────────────────────────────────────────────
with st.expander("Histórico de vigências (todas as linhas)"):
    hist_df = session.sql("""
        SELECT CHAVE, ANO, MES, VALOR, DESCRICAO,
               UPDATED_BY, TO_VARCHAR(UPDATED_AT, 'DD/MM/YYYY HH24:MI') AS ATUALIZADO_EM
        FROM SUPERSET.COMISSOES.CONFIG
        ORDER BY CHAVE, ANO, MES
    """).to_pandas()
    from utils.ui import html_table
    hist_df["VIGÊNCIA"] = hist_df.apply(
        lambda r: f"{_MESES_N.get(int(r['MES']), r['MES'])}/{int(r['ANO'])}", axis=1)
    html_table(hist_df[["CHAVE", "VIGÊNCIA", "VALOR", "UPDATED_BY", "ATUALIZADO_EM"]].rename(
        columns={"CHAVE": "Chave", "VALOR": "Valor",
                 "UPDATED_BY": "Alterado por", "ATUALIZADO_EM": "Em"}), scrollable=True)
