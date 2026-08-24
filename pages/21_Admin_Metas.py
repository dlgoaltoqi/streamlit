import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin
from utils.ui import render_css, render_banner, html_table, brl, pct_fmt

render_css()
render_banner("Metas Consultores")

session = get_session()
require_admin(session)

from utils.connection import MESES_NOME as MESES

_PCT_COLS = ["PERCENTUAL_DESCONTO_METAS"]

@st.cache_data(ttl=3000)
def _load_metas(ano: int, mes: int) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EMAIL, EQUIPE, SENIORIDADE,
               PERCENTUAL_DESCONTO_METAS,
               META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
               META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR
        FROM SUPERSET.PARCIAL.META_CONSULTOR
        WHERE ANO = {ano} AND MES = {mes}
        ORDER BY EQUIPE, EMAIL
    """).to_pandas()

ano, mes = render_period_filter()

# ── A partir de jul/2026 as metas dos consultores vêm do Revenue Intelligence ──
# (docs/18_migracao_metas_ri.md). Para esses meses a tela é SOMENTE visualização
# da composição vigente (override + RI + complemento do form); edição segue
# válida apenas para meses anteriores.
_RI_DESDE = (2026, 7)

if (ano, mes) >= _RI_DESDE:
    st.markdown(
        "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
        "padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>"
        "A partir de <b>julho/2026</b> as metas dos consultores vêm de "
        "<b>Revenue Intelligence</b>, com complemento do formulário para quem não "
        "está lá (ver coluna <b>Fonte</b>).<br>"
        "Esta tela é somente visualização e edições devem ser feitas na origem "
        "(RI). Correções administrativas ficam em "
        "<b>SUPERSET.COMISSOES.METAS_OVERRIDE</b> e aparecem aqui com a fonte "
        "<b>Override</b>, vencendo o RI e o formulário.</div>",
        unsafe_allow_html=True,
    )

    @st.cache_data(ttl=3000)
    def _load_composicao(ano: int, mes: int) -> pd.DataFrame:
        session = get_active_session()
        return session.sql(f"""
            SELECT CONSULTOR, EQUIPE, FONTE,
                   PERCENTUAL_DESCONTO_METAS,
                   META_MRR_BRUTO, META_MRR, META_OTR_BRUTO, META_OTR
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = {ano} AND MES = {mes}
            ORDER BY EQUIPE, CONSULTOR
        """).to_pandas()

    @st.cache_data(ttl=3000)
    def _pendencias_cadastro(ano: int, mes: int) -> pd.DataFrame:
        session = get_active_session()
        return session.sql(f"""
            WITH metas AS (
                SELECT DISTINCT LOWER(CONSULTOR) AS EMAIL, EQUIPE
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = {ano} AND MES = {mes} AND CONSULTOR IS NOT NULL
            ),
            par AS (
                SELECT DISTINCT LOWER(EMAIL) AS EMAIL FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE ANO = {ano} AND MES = {mes}
            ),
            rls AS (
                SELECT DISTINCT LOWER(CONSULTOREMAIL) AS EMAIL
                FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            )
            SELECT m.EMAIL, m.EQUIPE,
                   IFF(p.EMAIL IS NULL, '✗', '') AS SEM_PARAMETROS,
                   IFF(r.EMAIL IS NULL, '✗', '') AS SEM_RLS
            FROM metas m
            LEFT JOIN par p ON p.EMAIL = m.EMAIL
            LEFT JOIN rls r ON r.EMAIL = m.EMAIL
            WHERE p.EMAIL IS NULL OR r.EMAIL IS NULL
            ORDER BY m.EQUIPE, m.EMAIL
        """).to_pandas()

    try:
        _comp = _load_composicao(ano, mes)
        _pend = _pendencias_cadastro(ano, mes)
    except Exception as _qe:
        if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
            compat_rerun()
        st.error(f"Erro ao carregar dados: {_qe}")
        st.stop()

    if not _pend.empty:
        st.markdown(
            f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            f"padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            f"⚠️ <b>{len(_pend)} pessoa(s) com meta cadastrada mas com cadastro "
            f"incompleto.</b><br>"
            f"Sem Parâmetros a comissão não calcula; sem RLS a pessoa não acessa "
            f"o painel.</div>",
            unsafe_allow_html=True,
        )
        html_table(pd.DataFrame({
            "Consultor":      _pend["EMAIL"],
            "Equipe":         _pend["EQUIPE"],
            "Sem Parâmetros": _pend["SEM_PARAMETROS"],
            "Sem RLS":        _pend["SEM_RLS"],
        }))
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    if _comp.empty:
        st.info("Nenhuma meta encontrada para este período.")
    else:
        def _fmt_otr(row):
            v = row["META_OTR"]
            if v is None or pd.isna(v) or not v:
                return "—"
            # GD usa Opps (contagem), demais equipes valor em R$
            if str(row["EQUIPE"]).strip().upper() == "GD":
                return f"{int(v):,}".replace(",", ".")
            return brl(v)

        _d = pd.DataFrame({
            "Consultor":  _comp["CONSULTOR"],
            "Equipe":     _comp["EQUIPE"],
            "Fonte":      _comp["FONTE"],
            "% Desconto": _comp["PERCENTUAL_DESCONTO_METAS"].apply(
                lambda v: pct_fmt(float(v) / 100) if pd.notna(v) and float(v) > 0 else "—"),
            "Meta Bruta (MRR)": _comp["META_MRR_BRUTO"].apply(
                lambda v: brl(v) if pd.notna(v) and v else "—"),
            "Meta Líquida (MRR)": _comp["META_MRR"].apply(
                lambda v: brl(v) if pd.notna(v) and v else "—"),
            "Meta (OTR/Booking)": _comp.apply(_fmt_otr, axis=1),
        })
        st.markdown(
            f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>"
            f"{len(_comp)} registro(s) em {MESES.get(mes, mes)}/{ano}.</p>",
            unsafe_allow_html=True,
        )
        html_table(_d)

    st.stop()

try:
    df = _load_metas(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

df_edit = df.copy()
for _c in _PCT_COLS:
    if _c in df_edit.columns:
        df_edit[_c] = df_edit[_c].apply(
            lambda v: round(float(v) * 100, 4) if (v is not None and pd.notna(v)) else None
        )

_data_editor = getattr(st, "data_editor", None) or getattr(st, "experimental_data_editor", None)
if _data_editor is None:
    st.error("Esta versão do Streamlit não suporta edição inline de tabelas.")
    st.stop()

edited = _data_editor(
    df_edit,
    num_rows="dynamic",
    use_container_width=True,
    key=f"metas_editor_{ano}_{mes}",
)

if st.button("💾 Salvar alterações", type="primary"):
    save_df = edited.copy()
    for _c in _PCT_COLS:
        if _c in save_df.columns:
            save_df[_c] = save_df[_c].apply(
                lambda v: round(float(v) / 100, 6) if (v is not None and pd.notna(v)) else None
            )

    def _val(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "NULL"
        try:
            return str(float(v))
        except (TypeError, ValueError):
            return "NULL"

    def _str(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    errors = []
    saved  = 0

    for _, row in save_df.iterrows():
        em = str(row.get("EMAIL") or "").strip()
        if not em:
            continue
        em_safe = em.replace("'", "''")
        equipe   = _str(row.get("EQUIPE"))
        senior   = _str(row.get("SENIORIDADE"))
        try:
            session.sql(f"""
                MERGE INTO SUPERSET.PARCIAL.META_CONSULTOR AS t
                USING (SELECT
                    {ano} AS ANO, {mes} AS MES,
                    '{em_safe}' AS EMAIL,
                    {equipe} AS EQUIPE,
                    {senior} AS SENIORIDADE,
                    {_val(row.get("PERCENTUAL_DESCONTO_METAS"))} AS PERCENTUAL_DESCONTO_METAS,
                    {_val(row.get("META_NMRR_BRUTO"))}     AS META_NMRR_BRUTO,
                    {_val(row.get("META_EXPANSAO_BRUTO"))}  AS META_EXPANSAO_BRUTO,
                    {_val(row.get("META_RENOVACAO_BRUTO"))} AS META_RENOVACAO_BRUTO,
                    {_val(row.get("META_OTR_BRUTO"))}       AS META_OTR_BRUTO,
                    {_val(row.get("META_NMRR"))}     AS META_NMRR,
                    {_val(row.get("META_EXPANSAO"))}  AS META_EXPANSAO,
                    {_val(row.get("META_RENOVACAO"))} AS META_RENOVACAO,
                    {_val(row.get("META_OTR"))}       AS META_OTR
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
                WHEN MATCHED THEN UPDATE SET
                    EQUIPE = s.EQUIPE,
                    SENIORIDADE = s.SENIORIDADE,
                    PERCENTUAL_DESCONTO_METAS = s.PERCENTUAL_DESCONTO_METAS,
                    META_NMRR_BRUTO   = s.META_NMRR_BRUTO,
                    META_EXPANSAO_BRUTO  = s.META_EXPANSAO_BRUTO,
                    META_RENOVACAO_BRUTO = s.META_RENOVACAO_BRUTO,
                    META_OTR_BRUTO    = s.META_OTR_BRUTO,
                    META_NMRR         = s.META_NMRR,
                    META_EXPANSAO     = s.META_EXPANSAO,
                    META_RENOVACAO    = s.META_RENOVACAO,
                    META_OTR          = s.META_OTR
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, EMAIL, EQUIPE, SENIORIDADE,
                     PERCENTUAL_DESCONTO_METAS,
                     META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
                     META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR)
                VALUES
                    (s.ANO, s.MES, s.EMAIL, s.EQUIPE, s.SENIORIDADE,
                     s.PERCENTUAL_DESCONTO_METAS,
                     s.META_NMRR_BRUTO, s.META_EXPANSAO_BRUTO, s.META_RENOVACAO_BRUTO, s.META_OTR_BRUTO,
                     s.META_NMRR, s.META_EXPANSAO, s.META_RENOVACAO, s.META_OTR)
            """).collect()
            saved += 1
        except Exception as e:
            errors.append(f"Erro ao salvar {em}: {e}")

    if errors:
        for err in errors:
            st.error(err)
    else:
        st.success(f"{saved} registro(s) salvos.")
        st.cache_data.clear()
        compat_rerun()

# ── Copiar mês anterior ───────────────────────────────────────────────────────

compat_divider()
with st.expander("Copiar do mês anterior", expanded=False):
    mes_orig = mes - 1 if mes > 1 else 12
    ano_orig = ano if mes > 1 else ano - 1

    orig_df = session.sql(f"""
        SELECT EMAIL FROM SUPERSET.PARCIAL.META_CONSULTOR
        WHERE ANO = {ano_orig} AND MES = {mes_orig}
    """).to_pandas()

    n_orig  = len(orig_df)
    ja_tem  = len(df)

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
            "Nenhuma meta no mês anterior para copiar.</div>",
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
                MERGE INTO SUPERSET.PARCIAL.META_CONSULTOR AS t
                USING (
                    SELECT
                        {ano} AS ANO, {mes} AS MES,
                        EMAIL, EQUIPE, SENIORIDADE,
                        PERCENTUAL_DESCONTO_METAS,
                        META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
                        META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR
                    FROM SUPERSET.PARCIAL.META_CONSULTOR
                    WHERE ANO = {ano_orig} AND MES = {mes_orig}
                ) AS s
                ON LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.ANO = s.ANO AND t.MES = s.MES
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, EMAIL, EQUIPE, SENIORIDADE,
                     PERCENTUAL_DESCONTO_METAS,
                     META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
                     META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR)
                VALUES
                    (s.ANO, s.MES, s.EMAIL, s.EQUIPE, s.SENIORIDADE,
                     s.PERCENTUAL_DESCONTO_METAS,
                     s.META_NMRR_BRUTO, s.META_EXPANSAO_BRUTO, s.META_RENOVACAO_BRUTO, s.META_OTR_BRUTO,
                     s.META_NMRR, s.META_EXPANSAO, s.META_RENOVACAO, s.META_OTR)
            """).collect()
            st.success(f"Metas copiadas de {MESES.get(mes_orig, mes_orig)}/{ano_orig}.")
            st.cache_data.clear()
            compat_rerun()


