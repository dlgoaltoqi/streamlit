import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin, audit_user_sql
from utils.ui import render_css, render_banner

render_css()
render_banner("Parâmetros de Comissão")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_autor_sql = audit_user_sql(session)

@st.cache_data(ttl=3000)
def _load_parametros(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EMAIL, CARGO, IS_GESTOR, IS_PVT, COALESCE(IS_TRIM_HABILITADO, TRUE) AS IS_TRIM_HABILITADO,
               CLIFF_OTE_01, CLIFF_OTE_02,
               CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
               CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
               PERCENTUAL_BOOKING_EXTRA,
               OTE_01_CHEIO, OTE_02_CHEIO,
               PERCENTUAL_PROTECAO,
               IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EMAIL
    """).to_pandas()

from utils.connection import MESES_NOME as MESES

ano, mes = render_period_filter()

# ── Tabela editável ───────────────────────────────────────────────────────────

try:
    df = _load_parametros(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

# Colunas que ficam em proporção no DB mas exibimos como % (×100 para mostrar, ÷100 para salvar)
_PCT_COLS = [
    "CLIFF_OTE_01", "CLIFF_OTE_02",
    "CLIFF_ACELERADOR_01", "CLIFF_ACELERADOR_02",
    "PERCENTUAL_BOOKING_EXTRA", "PERCENTUAL_PROTECAO", "PERCENTUAL_CANC_RECOVERY",
]

df_edit = df.copy()
for _c in _PCT_COLS:
    if _c in df_edit.columns:
        df_edit[_c] = df_edit[_c].apply(
            lambda v: round(float(v) * 100, 4) if (v is not None and pd.notna(v)) else None
        )

_orig_emails = set(df["EMAIL"].str.lower().tolist())

_data_editor = getattr(st, "data_editor", None) or getattr(st, "experimental_data_editor", None)
if _data_editor is None:
    st.error("Esta versão do Streamlit não suporta edição inline de tabelas.")
    st.stop()
edited = _data_editor(
    df_edit,
    num_rows="dynamic",
    use_container_width=True,
    key=f"parametros_editor_{ano}_{mes}",
)

if st.button("💾 Salvar alterações", type="primary"):
    edited_emails = set(edited["EMAIL"].dropna().str.lower().tolist())
    removed = _orig_emails - edited_emails

    save_df = edited.copy()
    for _c in _PCT_COLS:
        if _c in save_df.columns:
            save_df[_c] = save_df[_c].apply(
                lambda v: round(float(v) / 100, 6) if (v is not None and pd.notna(v)) else None
            )

    def _val(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "NULL"
        return str(v)

    def _bool(v, default=False):
        try:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return default
            return bool(v)
        except (TypeError, ValueError):
            return default

    # Salva só o que mudou: compara cada linha editada com a original (ambas
    # no espaço de exibição, % já ×100) e ignora as idênticas — evita um MERGE
    # por linha intocada e preserva o UPDATED_AT de quem não foi alterado.
    def _norm_cell(v):
        try:
            if v is None or pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(v, str):
            return v.strip()
        try:
            return round(float(v), 6)
        except (TypeError, ValueError):
            return str(v).strip()

    _cols_cmp = list(df_edit.columns)
    _orig_rows = {
        str(r["EMAIL"]).strip().lower(): tuple(_norm_cell(r[c]) for c in _cols_cmp)
        for _, r in df_edit.iterrows() if str(r.get("EMAIL") or "").strip()
    }
    _mudou = []
    for _, r in edited.iterrows():
        _em = str(r.get("EMAIL") or "").strip().lower()
        _mudou.append(bool(_em) and _orig_rows.get(_em)
                      != tuple(_norm_cell(r[c]) for c in _cols_cmp))
    _n_skip = sum(1 for m in _mudou if not m)

    errors = []
    saved  = 0
    _tot  = len(removed) + sum(_mudou)
    if _tot == 0:
        st.session_state["_param_save_ok_"] = "Nenhuma alteração para salvar."
        compat_rerun()
    _done = 0
    _pb = st.progress(0, text=f"Salvando alterações… 0/{_tot}")

    for em in removed:
        _done += 1
        _pb.progress(_done / _tot, text=f"Salvando alterações… {_done}/{_tot}")
        em_safe = em.replace("'", "''")
        try:
            session.sql(f"""
                DELETE FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{em_safe}'
            """).collect()
        except Exception as e:
            errors.append(f"Erro ao remover {em}: {e}")

    for _i, (_, row) in enumerate(save_df.iterrows()):
        if not _mudou[_i]:
            continue
        _done += 1
        _pb.progress(_done / _tot, text=f"Salvando alterações… {_done}/{_tot}")
        em = str(row.get("EMAIL") or "").strip()
        if not em:
            continue
        cargo = str(row.get("CARGO") or "").strip().replace("'", "''")
        if not cargo:
            errors.append(f"Cargo não informado para {em}.")
            continue
        em_safe = em.replace("'", "''")
        try:
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.PARAMETROS AS t
                USING (SELECT
                    {ano} AS ANO, {mes} AS MES, '{em_safe}' AS EMAIL,
                    '{cargo}' AS CARGO,
                    {str(_bool(row.get("IS_GESTOR"))).upper()} AS IS_GESTOR,
                    {str(_bool(row.get("IS_PVT"))).upper()} AS IS_PVT,
                    {str(_bool(row.get("IS_TRIM_HABILITADO"), default=True)).upper()} AS IS_TRIM_HABILITADO,
                    {_val(row.get("CLIFF_OTE_01"))} AS CLIFF_OTE_01,
                    {_val(row.get("CLIFF_OTE_02"))} AS CLIFF_OTE_02,
                    {_val(row.get("CLIFF_ACELERADOR_01"))} AS CLIFF_ACELERADOR_01,
                    {_val(row.get("MULT_ACELERADOR_01"))} AS MULT_ACELERADOR_01,
                    {_val(row.get("CLIFF_ACELERADOR_02"))} AS CLIFF_ACELERADOR_02,
                    {_val(row.get("MULT_ACELERADOR_02"))} AS MULT_ACELERADOR_02,
                    {_val(row.get("PERCENTUAL_BOOKING_EXTRA"))} AS PERCENTUAL_BOOKING_EXTRA,
                    {_val(row.get("OTE_01_CHEIO"))} AS OTE_01_CHEIO,
                    {_val(row.get("OTE_02_CHEIO"))} AS OTE_02_CHEIO,
                    {_val(row.get("PERCENTUAL_PROTECAO"))} AS PERCENTUAL_PROTECAO,
                    {str(_bool(row.get("IS_CANC_RECOVERY"))).upper()} AS IS_CANC_RECOVERY,
                    {_val(row.get("PERCENTUAL_CANC_RECOVERY"))} AS PERCENTUAL_CANC_RECOVERY
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
                WHEN MATCHED THEN UPDATE SET
                    CARGO = s.CARGO, IS_GESTOR = s.IS_GESTOR, IS_PVT = s.IS_PVT,
                    IS_TRIM_HABILITADO = s.IS_TRIM_HABILITADO,
                    CLIFF_OTE_01 = s.CLIFF_OTE_01, CLIFF_OTE_02 = s.CLIFF_OTE_02,
                    CLIFF_ACELERADOR_01 = s.CLIFF_ACELERADOR_01,
                    MULT_ACELERADOR_01 = s.MULT_ACELERADOR_01,
                    CLIFF_ACELERADOR_02 = s.CLIFF_ACELERADOR_02,
                    MULT_ACELERADOR_02 = s.MULT_ACELERADOR_02,
                    PERCENTUAL_BOOKING_EXTRA = s.PERCENTUAL_BOOKING_EXTRA,
                    OTE_01_CHEIO = s.OTE_01_CHEIO,
                    OTE_02_CHEIO = s.OTE_02_CHEIO,
                    PERCENTUAL_PROTECAO = s.PERCENTUAL_PROTECAO,
                    IS_CANC_RECOVERY = s.IS_CANC_RECOVERY,
                    PERCENTUAL_CANC_RECOVERY = s.PERCENTUAL_CANC_RECOVERY,
                    UPDATED_BY = {_autor_sql}, UPDATED_AT = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, EMAIL, CARGO, IS_GESTOR, IS_PVT, IS_TRIM_HABILITADO,
                     CLIFF_OTE_01, CLIFF_OTE_02,
                     CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
                     CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
                     PERCENTUAL_BOOKING_EXTRA, OTE_01_CHEIO, OTE_02_CHEIO,
                     PERCENTUAL_PROTECAO, IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY,
                     UPDATED_BY, UPDATED_AT)
                VALUES
                    (s.ANO, s.MES, s.EMAIL, s.CARGO, s.IS_GESTOR, s.IS_PVT, s.IS_TRIM_HABILITADO,
                     s.CLIFF_OTE_01, s.CLIFF_OTE_02,
                     s.CLIFF_ACELERADOR_01, s.MULT_ACELERADOR_01,
                     s.CLIFF_ACELERADOR_02, s.MULT_ACELERADOR_02,
                     s.PERCENTUAL_BOOKING_EXTRA, s.OTE_01_CHEIO, s.OTE_02_CHEIO,
                     s.PERCENTUAL_PROTECAO, s.IS_CANC_RECOVERY, s.PERCENTUAL_CANC_RECOVERY,
                     {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            saved += 1
        except Exception as e:
            errors.append(f"Erro ao salvar {em}: {e}")

    _pb.empty()
    if errors:
        for err in errors:
            st.error(err)
    else:
        st.session_state["_param_save_ok_"] = (
            f"{saved} registro(s) salvos ({_n_skip} sem alteração, ignorados). "
            f"{len(removed)} removido(s).")
        st.cache_data.clear()
        compat_rerun()

# Mensagem de sucesso persistida através do rerun (senão o rerun a engole)
_msg_ok = st.session_state.pop("_param_save_ok_", None)
if _msg_ok:
    st.markdown(
        f"<div style='color:#1a1a1a;background:#dcfce7;border-radius:6px;"
        f"padding:0.6rem 0.9rem;border-left:4px solid #16a34a;margin:0.4rem 0;'>"
        f"✓ {_msg_ok}</div>",
        unsafe_allow_html=True,
    )

# ── Copiar mês anterior ───────────────────────────────────────────────────────

compat_divider()
with st.expander("Copiar do mês anterior", expanded=False):
    mes_orig = mes - 1 if mes > 1 else 12
    ano_orig = ano if mes > 1 else ano - 1

    orig_df = session.sql(f"""
        SELECT EMAIL FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano_orig} AND MES = {mes_orig}
    """).to_pandas()

    n_orig = len(orig_df)
    ja_tem = len(df)

    st.markdown(
        f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>"
        f"Mês de origem: <b>{MESES.get(mes_orig, mes_orig)}/{ano_orig}</b> — {n_orig} registro(s). "
        f"Mês atual já tem {ja_tem} registro(s).</p>",
        unsafe_allow_html=True,
    )

    if n_orig == 0:
        st.markdown(
            "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>"
            "Nenhum parâmetro no mês anterior para copiar.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            "Copia apenas registros que <b>não existem</b> no mês atual (MERGE sem sobrescrever).</div>",
            unsafe_allow_html=True,
        )
        if st.button("Copiar do mês anterior", type="secondary"):
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.PARAMETROS AS t
                USING (
                    SELECT
                        {ano} AS ANO, {mes} AS MES,
                        EMAIL, CARGO, IS_GESTOR, IS_PVT,
                        COALESCE(IS_TRIM_HABILITADO, TRUE) AS IS_TRIM_HABILITADO,
                        CLIFF_OTE_01, CLIFF_OTE_02,
                        CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
                        CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
                        PERCENTUAL_BOOKING_EXTRA, OTE_01_CHEIO, OTE_02_CHEIO,
                        PERCENTUAL_PROTECAO, IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY
                    FROM SUPERSET.COMISSOES.PARAMETROS
                    WHERE ANO = {ano_orig} AND MES = {mes_orig}
                ) AS s
                ON LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.ANO = s.ANO AND t.MES = s.MES
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, EMAIL, CARGO, IS_GESTOR, IS_PVT, IS_TRIM_HABILITADO,
                     CLIFF_OTE_01, CLIFF_OTE_02,
                     CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
                     CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
                     PERCENTUAL_BOOKING_EXTRA, OTE_01_CHEIO, OTE_02_CHEIO,
                     PERCENTUAL_PROTECAO, IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY,
                     UPDATED_BY, UPDATED_AT)
                VALUES
                    (s.ANO, s.MES, s.EMAIL, s.CARGO, s.IS_GESTOR, s.IS_PVT, s.IS_TRIM_HABILITADO,
                     s.CLIFF_OTE_01, s.CLIFF_OTE_02,
                     s.CLIFF_ACELERADOR_01, s.MULT_ACELERADOR_01,
                     s.CLIFF_ACELERADOR_02, s.MULT_ACELERADOR_02,
                     s.PERCENTUAL_BOOKING_EXTRA, s.OTE_01_CHEIO, s.OTE_02_CHEIO,
                     s.PERCENTUAL_PROTECAO, s.IS_CANC_RECOVERY, s.PERCENTUAL_CANC_RECOVERY,
                     {_autor_sql}, CURRENT_TIMESTAMP())
            """).collect()
            st.success(f"Parâmetros copiados de {MESES.get(mes_orig, mes_orig)}/{ano_orig}.")
            st.cache_data.clear()
            compat_rerun()


