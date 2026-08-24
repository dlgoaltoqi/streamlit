import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import re
import json
import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import (
    get_session, compat_rerun, render_period_filter, require_admin,
    get_comissao, clear_comissao_cache, _is_xp_err,
)
from utils.fechamento import periodo_fechado, fechar_consultores, fechar_um, fechar_inserir, reabrir_fechamento
from utils.ui import render_css, render_banner, brl, pct_fmt, html_table, download_link

# Padrão de formatação de cargos (mesmo usado em _comissao.py e Cargos e OTEs):
# title-case mantendo as siglas II/SDR/JR/PL/SR/FSB em maiúsculo.
_SIGLAS_RE = re.compile(r'\b(II|SDR|JR|PL|SR|FSB)\b', re.IGNORECASE)

def _fmt_cargo(s):
    return _SIGLAS_RE.sub(lambda m: m.group().upper(), str(s).title())

render_css()
render_banner("Exportar Comissões")

session = get_session()
_usuario = require_admin(session)

from utils.connection import MESES_NOME as MESES


@st.cache_data(ttl=3000)
def _equipes_periodo(ano: int, mes: int) -> list:
    session = get_active_session()
    df = session.sql(f"""
        SELECT DISTINCT EQUIPE
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND EQUIPE IS NOT NULL
          AND EQUIPE NOT IN ('Sonia')
        ORDER BY EQUIPE
    """).to_pandas()
    equipes = df["EQUIPE"].tolist()
    cr = session.sql(f"""
        SELECT COUNT(*) AS N FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
    """).to_pandas()
    if not cr.empty and int(cr.iloc[0]["N"]) > 0:
        equipes.append("Cancelamento")
    if mes in (3, 6, 9, 12):
        pvt_ck = session.sql(f"""
            SELECT COUNT(*) AS N FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_PVT = TRUE
              AND COALESCE(IS_GESTOR, FALSE) = FALSE
        """).to_pandas()
        if not pvt_ck.empty and int(pvt_ck.iloc[0]["N"]) > 0:
            equipes.append("PVT")
    return equipes


@st.cache_data(ttl=3000)
def _consultores_periodo(ano: int, mes: int, equipe: str) -> list:
    session = get_active_session()
    if equipe == "PVT":
        df = session.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_PVT = TRUE
              AND COALESCE(IS_GESTOR, FALSE) = FALSE
            ORDER BY EMAIL
        """).to_pandas()
        return df["EMAIL"].tolist() if not df.empty else []
    if equipe == "Cancelamento":
        df = session.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
            ORDER BY EMAIL
        """).to_pandas()
        return df["EMAIL"].tolist() if not df.empty else []
    # Equipes do METAS varridas p/ esta equipe (config equipes_fechamento.<equipe>;
    # fallback histórico: Farmer inclui Sonia)
    from utils.commission import _config_mes, _cfg_list
    _cfgx = _config_mes(session, ano, mes)
    if _cfgx.get("config_ok"):
        _eqs = _cfg_list(_cfgx, f"equipes_fechamento.{equipe}", None) or [equipe]
    else:
        _eqs = ["Farmer", "Sonia"] if equipe == "Farmer" else [equipe]
    eq_filter = "AND EQUIPE IN (" + ", ".join(
        "'" + str(e).replace("'", "''") + "'" for e in _eqs) + ")"
    df = session.sql(f"""
        SELECT DISTINCT LOWER(CONSULTOR) AS EMAIL
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} {eq_filter}
        ORDER BY EMAIL
    """).to_pandas()
    return df["EMAIL"].tolist()


@st.cache_data(ttl=86400)
def _nomes_map() -> dict:
    session = get_active_session()
    try:
        df = session.sql("""
            SELECT LOWER(EMAIL) AS EMAIL, NAME AS NOME
            FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
            WHERE DELETED_ON IS NULL AND EMAIL IS NOT NULL
              AND LOWER(EMAIL) LIKE '%@altoqi.com.br'
        """).to_pandas()
        return {str(r["EMAIL"]): str(r["NOME"]) for _, r in df.iterrows()}
    except Exception:
        return {}


def _nome_fallback(email: str) -> str:
    return " ".join(p.capitalize() for p in email.split("@")[0].split("."))


def _nome_display(email: str, nomes: dict) -> str:
    raw = nomes.get(email.lower())
    if raw and " " in raw:
        return raw
    return _nome_fallback(email)


def _calcular_pvt_export(s, ano: int, mes: int, nomes: dict, mes_nome: str) -> list:
    _CLIFF    = 0.80
    _ACEL_90  = 0.90
    _ACEL_100 = 1.00
    _OTE_BASE = 3_600.0
    _POND_NMRR = 0.60
    _POND_OTR  = 0.40

    q_num = (mes - 1) // 3 + 1
    meses = [(q_num - 1) * 3 + 1, (q_num - 1) * 3 + 2, (q_num - 1) * 3 + 3]
    m_in  = ", ".join(str(m) for m in meses)

    df_nm = s.sql(f"""
        SELECT m.EQUIPE, m.MES, SUM(COALESCE(m.META_NMRR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES AND p.IS_GESTOR = TRUE
        WHERE m.ANO = {ano} AND m.MES IN ({m_in})
          AND m.EQUIPE IN ('B2B Escritório', 'B2B Construtora')
        GROUP BY m.EQUIPE, m.MES
        UNION ALL
        SELECT 'Farmer' AS EQUIPE, MES, SUM(COALESCE(META_EXPANSAO, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES IN ({m_in}) AND EQUIPE = 'Sonia'
        GROUP BY MES
    """).to_pandas()

    df_om = s.sql(f"""
        SELECT m.MES, SUM(COALESCE(m.META_OTR, 0)) AS VALOR
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
         AND p.ANO = {ano} AND p.MES = m.MES
         AND COALESCE(p.IS_GESTOR, FALSE) = FALSE
        WHERE m.ANO = {ano} AND m.MES IN ({m_in}) AND m.EQUIPE IN ('Governo', 'B2G')
        GROUP BY m.MES
    """).to_pandas()

    df_nr = s.sql(f"""
        WITH fa AS (
            SELECT EQUIPE, MES, FECHAMENTO_ID FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES IN ({m_in}) AND STATUS = 'ATIVO'
              AND EQUIPE IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
        ),
        df_deals AS (
            SELECT DISTINCT cf.EQUIPE, cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fa ON fa.FECHAMENTO_ID = cf.FECHAMENTO_ID
             AND fa.EQUIPE = cf.EQUIPE AND fa.MES = cf.MES
            WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        ),
        nmrr_fec AS (
            SELECT v.VERTICAL AS EQUIPE,
                   v.MES,
                   SUM(CASE WHEN v.VERTICAL = 'Farmer'
                            THEN COALESCE(v.MRR_EXPANSAO,0)
                            ELSE COALESCE(v.NMRR,0) END) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN df_deals d ON d.ID_NEGOCIO = v.ID_NEGOCIO
             AND d.EQUIPE = v.VERTICAL
             AND d.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({m_in})
            GROUP BY 1, v.MES
        ),
        ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({m_in})
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        ),
        nmrr_viv AS (
            SELECT v.VERTICAL AS EQUIPE,
                   v.MES,
                   SUM(CASE WHEN v.VERTICAL = 'Farmer'
                            THEN COALESCE(v.MRR_EXPANSAO,0)
                            ELSE COALESCE(v.NMRR,0) END) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN ok ON ok.ID_NEGOCIO = v.ID_NEGOCIO
            LEFT JOIN fa
                ON fa.EQUIPE = v.VERTICAL
                AND fa.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({m_in})
              AND v.VERTICAL IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
              AND fa.EQUIPE IS NULL
            GROUP BY 1, v.MES
        )
        SELECT EQUIPE, MES, SUM(VALOR) AS VALOR
        FROM (SELECT * FROM nmrr_fec UNION ALL SELECT * FROM nmrr_viv)
        GROUP BY EQUIPE, MES
    """).to_pandas()

    df_or = s.sql(f"""
        WITH fb AS (
            SELECT MES, FECHAMENTO_ID FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {ano} AND MES IN ({m_in}) AND STATUS = 'ATIVO'
              AND EQUIPE IN ('Governo', 'B2G')
        ),
        df_deals AS (
            SELECT DISTINCT cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
            FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
            JOIN fb ON fb.FECHAMENTO_ID = cf.FECHAMENTO_ID AND fb.MES = cf.MES
            WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
        ),
        otr_fec AS (
            SELECT v.MES, SUM(COALESCE(v.BOOKING,0)) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN df_deals d ON d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({m_in})
              AND v.VERTICAL = 'B2G'
            GROUP BY v.MES
        ),
        ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({m_in})
            GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        ),
        otr_viv AS (
            SELECT v.MES, SUM(COALESCE(v.BOOKING,0)) AS VALOR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN ok ON ok.ID_NEGOCIO = v.ID_NEGOCIO
            LEFT JOIN fb ON fb.MES = v.MES
            WHERE v.ANO = {ano} AND v.MES IN ({m_in})
              AND v.VERTICAL = 'B2G' AND fb.MES IS NULL
            GROUP BY v.MES
        )
        SELECT MES, SUM(VALOR) AS VALOR
        FROM (SELECT * FROM otr_fec UNION ALL SELECT * FROM otr_viv)
        GROUP BY MES
    """).to_pandas()

    # ── Aplicar overrides PVT ─────────────────────────────────────────────────
    # Cópias graváveis: to_pandas() pode vir com buffers Arrow somente-leitura
    # e o .loc dos overrides falharia com "assignment destination is read-only"
    # (mesma correção já aplicada na página Comissão PVT).
    df_nr, df_nm = df_nr.copy(), df_nm.copy()
    df_or, df_om = df_or.copy(), df_om.copy()
    # Sem try/except: se os overrides não puderem ser lidos, o relatório e o
    # fechamento sairiam errados em silêncio — a exceção deve subir e aparecer.
    df_ov = s.sql(f"""
        SELECT MES, EQUIPE, REAL_NMRR, META_NMRR, REAL_OTR, META_OTR
        FROM SUPERSET.COMISSOES.PVT_OVERRIDES
        WHERE ANO = {ano} AND MES IN ({m_in})
          AND (REAL_NMRR IS NOT NULL OR META_NMRR IS NOT NULL
               OR REAL_OTR IS NOT NULL OR META_OTR IS NOT NULL)
    """).to_pandas()

    def _nn(v):
        return v is not None and not (isinstance(v, float) and pd.isna(v))

    for _, ov in df_ov.iterrows():
        ov_mes = int(ov["MES"])
        ov_eq  = str(ov["EQUIPE"])
        if ov_eq != "B2G":
            if _nn(ov["REAL_NMRR"]):
                m = (df_nr["MES"] == ov_mes) & (df_nr["EQUIPE"] == ov_eq)
                if m.any():
                    df_nr.loc[m, "VALOR"] = float(ov["REAL_NMRR"])
                else:
                    df_nr = pd.concat([df_nr, pd.DataFrame(
                        [{"EQUIPE": ov_eq, "MES": ov_mes, "VALOR": float(ov["REAL_NMRR"])}]
                    )], ignore_index=True)
            if _nn(ov["META_NMRR"]):
                m = (df_nm["MES"] == ov_mes) & (df_nm["EQUIPE"] == ov_eq)
                if m.any():
                    df_nm.loc[m, "VALOR"] = float(ov["META_NMRR"])
                else:
                    df_nm = pd.concat([df_nm, pd.DataFrame(
                        [{"EQUIPE": ov_eq, "MES": ov_mes, "VALOR": float(ov["META_NMRR"])}]
                    )], ignore_index=True)
        else:
            if _nn(ov["REAL_OTR"]):
                m = df_or["MES"] == ov_mes
                if m.any():
                    df_or.loc[m, "VALOR"] = float(ov["REAL_OTR"])
                else:
                    df_or = pd.concat([df_or, pd.DataFrame(
                        [{"MES": ov_mes, "VALOR": float(ov["REAL_OTR"])}]
                    )], ignore_index=True)
            if _nn(ov["META_OTR"]):
                m = df_om["MES"] == ov_mes
                if m.any():
                    df_om.loc[m, "VALOR"] = float(ov["META_OTR"])
                else:
                    df_om = pd.concat([df_om, pd.DataFrame(
                        [{"MES": ov_mes, "VALOR": float(ov["META_OTR"])}]
                    )], ignore_index=True)

    meta_nmrr = float(df_nm["VALOR"].sum()) if not df_nm.empty else 0.0
    real_nmrr = float(df_nr["VALOR"].sum()) if not df_nr.empty else 0.0
    meta_otr  = float(df_om["VALOR"].sum()) if not df_om.empty else 0.0
    real_otr  = float(df_or["VALOR"].sum()) if not df_or.empty else 0.0

    pct_nmrr = real_nmrr / meta_nmrr if meta_nmrr > 0 else 0.0
    pct_otr  = real_otr  / meta_otr  if meta_otr  > 0 else 0.0
    pct_pond = pct_nmrr * _POND_NMRR + pct_otr * _POND_OTR

    if pct_pond < _CLIFF:
        acel = 0.0
    elif pct_pond < _ACEL_90:
        acel = 1.00
    elif pct_pond < _ACEL_100:
        acel = 1.15
    else:
        acel = 1.25

    ote_aj = _OTE_BASE * acel
    total  = ote_aj * pct_pond if mes in (3, 6, 9, 12) else 0.0

    df_pvt = s.sql(f"""
        SELECT LOWER(EMAIL) AS EMAIL
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND IS_PVT = TRUE
          AND COALESCE(IS_GESTOR, FALSE) = FALSE
        ORDER BY EMAIL
    """).to_pandas()

    pvt_rows = []
    for _, r in df_pvt.iterrows():
        email = str(r["EMAIL"])
        nome  = _nome_display(email, nomes)
        pvt_rows.append({
            "Ano": ano, "Mês": mes_nome, "Nome": nome, "Email": email,
            "Equipe": "PVT", "Cargo": "PVT",
            "Total": total,
            "OTE Base": _OTE_BASE,
            "Acelerador OTE": acel,
            "OTE Ajustado": ote_aj,
            "% NMRR": pct_nmrr,
            "Meta NMRR": meta_nmrr,
            "Real NMRR": real_nmrr,
            "% Booking": pct_otr,
            "Meta Booking": meta_otr,
            "Real Booking": real_otr,
            "% Atingimento Pond.": pct_pond,
        })
    return pvt_rows


def _safe(dados, key, default=0.0):
    v = dados.get(key, default)
    return v if v is not None else default


# ── Filtros ───────────────────────────────────────────────────────────────────

ano, mes = render_period_filter()

equipes = _equipes_periodo(ano, mes)
equipe_sel = st.selectbox("👥 Equipe", equipes if equipes else ["—"], key="_exp_eq_")

_fk = f"{ano}-{mes}-{equipe_sel}"
if st.session_state.get("_exp_fk_") != _fk:
    st.session_state.pop("_exp_result_", None)
    st.session_state["_exp_fk_"] = _fk

if st.button("Gerar Relatório", type="primary"):
    consultores = _consultores_periodo(ano, mes, equipe_sel)
    nomes = _nomes_map()
    mes_nome = MESES.get(mes, str(mes))
    rows = []
    erros = []

    pb = st.progress(0, text="Calculando…")
    rows_gd = []  # GD team / SDR consultants (Opps-based, second table)
    if equipe_sel == "PVT":
        try:
            rows = _calcular_pvt_export(session, ano, mes, nomes, mes_nome)
        except Exception as _pe:
            if _is_xp_err(_pe): compat_rerun()
            erros.append(str(_pe))
        consultores = []  # pula o loop principal
    for i, email in enumerate(consultores):
        pb.progress((i + 1) / max(len(consultores), 1),
                    text=f"Calculando {i + 1}/{len(consultores)}…")
        try:
            dados = get_comissao(email, ano, mes)
        except Exception as _e:
            if "terminated" in str(_e).lower() or "xp process" in str(_e).lower():
                compat_rerun()
            erros.append(email)
            continue

        if "erro" in dados:
            continue
        if _safe(dados, "is_gd", False):
            _eq_dados = dados.get("equipe", "").lower()
            # GD team members only appear in GD export; SDR of other teams only in their team's export
            if _eq_dados == "gd" and equipe_sel != "GD":
                continue
            if _eq_dados != "gd" and equipe_sel == "GD":
                continue
            nome = _nome_display(email, nomes)
            trim = dados.get("trim")
            _fator_trim = (trim["fator_ind"] + trim.get("fator_eq", 0)) if trim else None
            _leader = _safe(dados, "is_gestor", False)
            rows_gd.append({
                "Ano": ano, "Mês": mes_nome, "Nome": nome,
                "Equipe": dados.get("equipe", ""), "Cargo": dados.get("cargo", ""),
                "Total": _safe(dados, "total"),
                "Comissão Trimestral": _fator_trim,
                "Realizado (Opps)": int(_safe(dados, "realizado")),
                "Meta (Opps)":      int(_safe(dados, "meta_mrr")),
                "% Atingido": _safe(dados, "pct_atingido"),
                "OTE Cheio":      _safe(dados, "ote_cheio"),
                "Desconto":       _safe(dados, "desconto"),
                "OTE Base":       _safe(dados, "ote_base"),
                "Acelerador OTE": _safe(dados, "acelerador"),
                "OTE Ajustado":   _safe(dados, "ote_ajustado"),
                "OTE Variável":   _safe(dados, "ote_variavel"),
                f"Ajuste de {mes_nome}": _safe(dados, "ajuste_total"),
                "Trim. Realizado Ind.": trim["real_ind"]  if trim else None,
                "Trim. Meta Ind.":      trim["meta_ind"]  if trim else None,
                "Trim. % Ating. Ind.":  trim["pct_ind"]   if trim else None,
                "Trim. Fator Ind.":     trim["fator_ind"] if trim else None,
                "Trim. Realizado Eq.":  trim.get("real_eq")  if (trim and not _leader) else None,
                "Trim. Meta Eq.":       trim.get("meta_eq")  if (trim and not _leader) else None,
                "Trim. % Ating. Eq.":   trim.get("pct_eq")   if (trim and not _leader) else None,
                "Trim. Fator Eq.":      trim.get("fator_eq") if (trim and not _leader) else None,
            })
            continue
        if _safe(dados, "is_canc_recovery", False):
            rows.append({
                "Ano": ano, "Mês": mes_nome,
                "Nome": _nome_display(email, nomes),
                "Email": email,
                "Equipe": dados.get("equipe", ""),
                "Total": _safe(dados, "total"),
            })
            continue

        nome = _nome_display(email, nomes)
        trim = dados.get("trim")
        _fator_trim = (trim["fator_ind"] + trim.get("fator_eq", 0)) if trim else None
        _leader = _safe(dados, "is_gestor", False)  # líder: trimestral de equipe fica em branco

        if _safe(dados, "is_b2g", False):
            is_gest = _safe(dados, "is_gestor", False)
            b2g_aj = dados.get("b2g_ajuste") or {}
            b2g_ajuste_val = b2g_aj.get("ajuste") or 0
            row = {
                "Ano": ano, "Mês": mes_nome, "Nome": nome,
                "Equipe": dados.get("equipe", ""), "Cargo": dados.get("cargo", ""),
                # Variável OTE = total SEM o Ajuste Trimestral (que é somado ao
                # total em commission.py; aqui é apresentado só na coluna própria)
                "Variável OTE":           _safe(dados, "total") - (b2g_ajuste_val or 0),
                "Comissão Trimestral":    _fator_trim,
                "Ajuste Trimestral B2G":  b2g_ajuste_val,
                # Mensal
                "Realizado (Booking)":    _safe(dados, "bk_real"),
                "Meta (Booking)":         _safe(dados, "meta_mrr"),
                "% Ating. (Booking)":     _safe(dados, "pct_bk_b2g"),
                "Realizado (ARR)":        _safe(dados, "arr_real")           if not is_gest else None,
                "Meta (ARR)":             _safe(dados, "meta_arr")           if not is_gest else None,
                "% Ating. (ARR)":         _safe(dados, "pct_arr_b2g")        if not is_gest else None,
                "% Equipe c/ Meta":       _safe(dados, "meta_atingida_real")  if is_gest else None,
                "Meta Eq. c/ Meta":       _safe(dados, "meta_atingida_meta")  if is_gest else None,
                "% Ating. (Meta Eq.)":    _safe(dados, "pct_meta_atingida")   if is_gest else None,
                "% Atingido Pond.":       _safe(dados, "pct_ponderado"),
                "OTE Cheio":      _safe(dados, "ote_cheio"),
                "Desconto":       _safe(dados, "desconto"),
                "OTE Base":       _safe(dados, "ote_base"),
                "Acelerador OTE": _safe(dados, "acelerador"),
                "OTE Ajustado":   _safe(dados, "ote_ajustado"),
                "OTE Variável":   _safe(dados, "ote_variavel"),
                # Acumulado trimestral
                "Aj. Trim. Realizado (Booking)": b2g_aj.get("bk_q"),
                "Aj. Trim. Meta (Booking)":      b2g_aj.get("meta_bk_q"),
                "Aj. Trim. % Ating. (Booking)":  b2g_aj.get("pct_bk_q"),
                "Aj. Trim. Realizado (ARR)":     b2g_aj.get("arr_q")     if not is_gest else None,
                "Aj. Trim. Meta (ARR)":          b2g_aj.get("meta_arr_q") if not is_gest else None,
                "Aj. Trim. % Ating. (ARR)":      b2g_aj.get("pct_arr_q") if not is_gest else None,
                "Aj. Trim. % Equipe c/ Meta":    b2g_aj.get("ma_q")      if is_gest else None,
                "Aj. Trim. % Ating. (Meta Eq.)": b2g_aj.get("pct_ma_q")  if is_gest else None,
                "Aj. Trim. % Atingido Pond.":    b2g_aj.get("pct_ponderado_q"),
                "Aj. Trim. OTE Base":            b2g_aj.get("ote_base_q"),
                "Aj. Trim.Acelerador OTE":      b2g_aj.get("acel_q"),
                "Aj. Trim. OTE Variável":        b2g_aj.get("ote_variavel_q"),
                "Pago nos 3 Meses":          b2g_aj.get("pago_mensal"),
                # Bônus trimestral individual/equipe
                "Trim. Realizado Ind.": trim["real_ind"]  if trim else None,
                "Trim. Meta Ind.":      trim["meta_ind"]  if trim else None,
                "Trim. % Ating. Ind.":  trim["pct_ind"]   if trim else None,
                "Trim. Fator Ind.":     trim["fator_ind"] if trim else None,
                "Trim. Realizado Eq.":  trim.get("real_eq")  if (trim and not _leader) else None,
                "Trim. Meta Eq.":       trim.get("meta_eq")  if (trim and not _leader) else None,
                "Trim. % Ating. Eq.":   trim.get("pct_eq")   if (trim and not _leader) else None,
                "Trim. Fator Eq.":      trim.get("fator_eq") if (trim and not _leader) else None,
                "_marcelo": "marcelo.maestro" in email.lower(),
            }
        else:
            real = _safe(dados, "realizado")

            def _pct(v):
                return v / real if real > 0 else 0.0

            row = {
                # Identificação
                "Ano":              ano,
                "Mês":              mes_nome,
                "Nome":             nome,
                "Equipe":           dados.get("equipe", ""),
                "Cargo":            dados.get("cargo", ""),
                # Resultado
                "Total":            _safe(dados, "total"),
                "Comissão Trimestral": _fator_trim,
                "Realizado":        real,
                "Meta":             _safe(dados, "meta_mrr"),
                "% Atingido":       _safe(dados, "pct_atingido"),
                # Forma de pagamento — participação no realizado
                "% À Vista":        _pct(_safe(dados, "mrr_avista")),
                "% CC até 3x":      _pct(_safe(dados, "mrr_cc3x")),
                "% CC até 12x":     _pct(_safe(dados, "mrr_cc12x")),
                "% Recorrente":     _pct(_safe(dados, "mrr_recorrente")),
                # Forma de pagamento — multiplicadores aplicados
                "Mult. À Vista":    _safe(dados, "mult_avista"),
                "Mult. CC até 3x":  _safe(dados, "mult_cc3x"),
                "Mult. CC até 12x": _safe(dados, "mult_cc12x"),
                "Mult. Recorrente": _safe(dados, "mult_recorrente"),
                # OTE
                "OTE Cheio":        _safe(dados, "ote_cheio"),
                "Desconto":         _safe(dados, "desconto"),
                "OTE Base":         _safe(dados, "ote_base"),
                "Acelerador OTE":   _safe(dados, "acelerador"),
                "OTE Ajustado":     _safe(dados, "ote_ajustado"),
                "OTE Variável":     _safe(dados, "ote_variavel"),
                # Extras opcionais
                "Booking Extra":         _safe(dados, "booking_extras"),
                "% Comissão Extra":      _safe(dados, "pct_bk_extra"),
                "Comissão Extra":        _safe(dados, "comissao_bk_extra"),
                "Dívidas Pagas":         _safe(dados, "dividas_pagas"),
                "Comissão Dívidas":      _safe(dados, "comissao_dividas"),
                f"Ajuste de {mes_nome}": _safe(dados, "ajuste_total"),
                "% Proteção":            _safe(dados, "pct_protecao"),
                "Premiação":             _safe(dados, "bonificacao_protecao"),
                # Trimestral individual
                "Trim. Realizado Ind.":  trim["real_ind"]  if trim else None,
                "Trim. Meta Ind.":       trim["meta_ind"]  if trim else None,
                "Trim. % Ating. Ind.":   trim["pct_ind"]   if trim else None,
                "Trim. Fator Ind.":      trim["fator_ind"] if trim else None,
                # Trimestral equipe (em branco para líderes/gestores)
                "Trim. Realizado Eq.":   trim.get("real_eq")  if (trim and not _leader) else None,
                "Trim. Meta Eq.":        trim.get("meta_eq")  if (trim and not _leader) else None,
                "Trim. % Ating. Eq.":    trim.get("pct_eq")   if (trim and not _leader) else None,
                "Trim. Fator Eq.":       trim.get("fator_eq") if (trim and not _leader) else None,
                "_is_saving":            _safe(dados, "is_saving", False),
            }
        rows.append(row)

    pb.empty()
    st.session_state["_exp_result_"] = (rows, rows_gd, erros, mes_nome)

# ── Exibição ──────────────────────────────────────────────────────────────────

if "_exp_result_" in st.session_state:
    rows, rows_gd, erros, mes_nome = st.session_state["_exp_result_"]

    if erros:
        st.warning(f"Não foi possível calcular: {', '.join(erros)}")

    if not rows and not rows_gd:
        st.info("Nenhum dado encontrado para este período/equipe.")
    else:
        is_b2g_export = equipe_sel == "Governo"
        is_gd_export  = equipe_sel == "GD"
        is_pvt_export = equipe_sel == "PVT"

        # For GD export, main data comes from rows_gd; otherwise from rows
        _src = rows_gd if is_gd_export else rows
        _sort_col = "Nome" if _src and "Nome" in _src[0] else "Email"
        df_raw = pd.DataFrame(_src).sort_values(_sort_col).reset_index(drop=True) if _src else pd.DataFrame()

        # Formata siglas dos cargos no mesmo padrão das demais páginas
        if "Cargo" in df_raw.columns:
            df_raw["Cargo"] = df_raw["Cargo"].apply(
                lambda v: _fmt_cargo(v) if isinstance(v, str) and v else v
            )
        _GD_INT_COLS  = {"Realizado (Opps)", "Meta (Opps)"}
        # Para GD/SDR o trimestral é em Opps, não BRL
        _GD_TRIM_INT  = {"Trim. Realizado Ind.", "Trim. Meta Ind.",
                          "Trim. Realizado Eq.",  "Trim. Meta Eq."}
        if is_gd_export:
            _GD_INT_COLS |= _GD_TRIM_INT

        # ── Mapeamento coluna → categoria (linha 1 para VBA) ─────────────────
        _CAT_MAP = {
            "Ano":                        "Identificadores",
            "Mês":                        "Identificadores",
            "Nome":                       "Identificadores",
            "Email":                      "Identificadores",
            "Equipe":                     "Identificadores",
            "Cargo":                      "Identificadores",
            "Total":                      "Totalizações",
            "Variável OTE":               "Totalizações",
            "Comissão Trimestral":        "Totalizações",
            "Ajuste Trimestral B2G":      "Totalizações",
            "Realizado":                  "Resultado Mês",
            "Realizado (Opps)":           "Resultado Mês",
            "Meta (Opps)":               "Resultado Mês",
            "Meta":                       "Resultado Mês",
            "% Atingido":                 "Resultado Mês",
            "Realizado (Booking)":        "Resultado Booking",
            "Meta (Booking)":             "Resultado Booking",
            "% Ating. (Booking)":         "Resultado Booking",
            "% Atingido Pond.":           "Resultado Booking",
            "Realizado (ARR)":            "Resultado ARR",
            "Meta (ARR)":                 "Resultado ARR",
            "% Ating. (ARR)":             "Resultado ARR",
            "% Equipe c/ Meta":           "Resultado Equipe",
            "Meta Eq. c/ Meta":           "Resultado Equipe",
            "% Ating. (Meta Eq.)":        "Resultado Equipe",
            "Aj. Trim. Realizado (Booking)":  "Ajuste Trimestral",
            "Aj. Trim. Meta (Booking)":       "Ajuste Trimestral",
            "Aj. Trim. % Ating. (Booking)":   "Ajuste Trimestral",
            "Aj. Trim. Realizado (ARR)":      "Ajuste Trimestral",
            "Aj. Trim. Meta (ARR)":           "Ajuste Trimestral",
            "Aj. Trim. % Ating. (ARR)":       "Ajuste Trimestral",
            "Aj. Trim. % Equipe c/ Meta":     "Ajuste Trimestral",
            "Aj. Trim. % Ating. (Meta Eq.)":  "Ajuste Trimestral",
            "Aj. Trim. % Atingido Pond.":     "Ajuste Trimestral",
            "Aj. Trim. OTE Base":             "Ajuste Trimestral",
            "Aj. Trim.Acelerador OTE":       "Ajuste Trimestral",
            "Aj. Trim. OTE Variável":         "Ajuste Trimestral",
            "Pago nos 3 Meses":           "Ajuste Trimestral",
            # marcelo renamed
            "Aproveit. Equipe":           "Resultado Equipe",
            "Meta Aproveit.":             "Resultado Equipe",
            "% Ating. (Aproveit.)":       "Resultado Equipe",
            "Aj. Trim. Aproveit. Equipe":     "Ajuste Trimestral",
            "Aj. Trim. % Ating. (Aproveit.)": "Ajuste Trimestral",
            "% À Vista":                  "Aceleradores Forma de Pagamento",
            "% CC até 3x":               "Aceleradores Forma de Pagamento",
            "% CC até 12x":              "Aceleradores Forma de Pagamento",
            "% Recorrente":              "Aceleradores Forma de Pagamento",
            "Mult. À Vista":             "Aceleradores Forma de Pagamento",
            "Mult. CC até 3x":           "Aceleradores Forma de Pagamento",
            "Mult. CC até 12x":          "Aceleradores Forma de Pagamento",
            "Mult. Recorrente":          "Aceleradores Forma de Pagamento",
            "OTE Cheio":                  "OTE",
            "Desconto":                   "OTE",
            "OTE Base":                   "OTE",
            "Acelerador OTE":             "OTE",
            "OTE Ajustado":               "OTE",
            "OTE Variável":               "OTE",
            "Booking Extra":              "Booking Extra",
            "% Comissão Extra":           "Booking Extra",
            "Comissão Extra":             "Booking Extra",
            "Dívidas Pagas":              "Dívidas",
            "Comissão Dívidas":           "Dívidas",
            "% Proteção":                 "Premiação",
            "Premiação":                  "Premiação",
            "Trim. Realizado Ind.":       "Trimestral Individual",
            "Trim. Meta Ind.":            "Trimestral Individual",
            "Trim. % Ating. Ind.":        "Trimestral Individual",
            "Trim. Fator Ind.":           "Trimestral Individual",
            "Trim. Realizado Eq.":        "Trimestral Equipe",
            "Trim. Meta Eq.":             "Trimestral Equipe",
            "Trim. % Ating. Eq.":         "Trimestral Equipe",
            "Trim. Fator Eq.":            "Trimestral Equipe",
            # PVT
            "Meta NMRR":                  "NMRR",
            "Real NMRR":                  "NMRR",
            "% NMRR":                     "NMRR",
            "Meta Booking":               "Booking B2G",
            "Real Booking":               "Booking B2G",
            "% Booking":                  "Booking B2G",
            "% Atingimento Pond.":        "Totalizações",
        }

        def _cat(col):
            c = _CAT_MAP.get(col)
            if c:
                return c
            if col.startswith("Ajuste de "):
                return "Ajuste"
            return ""

        _TRIM = [
            "Trim. Realizado Ind.", "Trim. Meta Ind.",
            "Trim. % Ating. Ind.", "Trim. Fator Ind.",
            "Trim. Realizado Eq.", "Trim. Meta Eq.",
            "Trim. % Ating. Eq.", "Trim. Fator Eq.",
        ]

        def _col_has_data(col):
            if col not in df_raw.columns:
                return False
            s = df_raw[col].dropna()
            return bool(len(s) > 0 and (s != 0).any())

        def _col_has_any(col):
            """Retorna True se a coluna existe e tem pelo menos um valor não-nulo."""
            return col in df_raw.columns and bool(df_raw[col].notna().any())

        _DESCONTO_GROUP = ["OTE Cheio", "Desconto"]
        _desconto_cols  = _DESCONTO_GROUP if _col_has_data("Desconto") else []

        if is_b2g_export:
            # Split marcelo from the rest (he has a different second metric)
            _df_reg  = df_raw[~df_raw["_marcelo"]].drop(columns=["_marcelo"]).reset_index(drop=True)
            _df_marc = df_raw[df_raw["_marcelo"]].drop(columns=["_marcelo"]).reset_index(drop=True)

            def _b2g_cols_show(df_sub):
                def _has_data(col):
                    if col not in df_sub.columns: return False
                    s = df_sub[col].dropna()
                    return bool(len(s) > 0 and (s != 0).any())
                def _has_any(col):
                    return col in df_sub.columns and bool(df_sub[col].notna().any())
                _B2G_FIXED = ["Ano", "Mês", "Nome", "Equipe", "Cargo", "Variável OTE"]
                _tot_cols  = (
                    ["Comissão Trimestral"] if _has_data("Comissão Trimestral") else []
                )
                _desc = _DESCONTO_GROUP if _has_data("Desconto") else []
                _arr  = ["Realizado (ARR)", "Meta (ARR)", "% Ating. (ARR)"] if _has_any("Realizado (ARR)") else []
                _gest = ["% Equipe c/ Meta", "Meta Eq. c/ Meta", "% Ating. (Meta Eq.)"] if _has_any("% Equipe c/ Meta") else []
                _acum_arr  = ["Aj. Trim. Realizado (ARR)", "Aj. Trim. Meta (ARR)", "Aj. Trim. % Ating. (ARR)"] if _has_any("Aj. Trim. Realizado (ARR)") else []
                _acum_gest = ["Aj. Trim. % Equipe c/ Meta", "Aj. Trim. % Ating. (Meta Eq.)"] if _has_any("Aj. Trim. % Equipe c/ Meta") else []
                _acum_base = [c for c in [
                    "Aj. Trim. Realizado (Booking)", "Aj. Trim. Meta (Booking)", "Aj. Trim. % Ating. (Booking)",
                ] if c in df_sub.columns]
                _acum_ote = [c for c in [
                    "Aj. Trim. % Atingido Pond.", "Aj. Trim. OTE Base", "Aj. Trim. Acelerador OTE",
                    "Aj. Trim. OTE Variável", "Pago nos 3 Meses",
                ] if c in df_sub.columns]
                _aj_final = ["Ajuste Trimestral B2G"] if _has_data("Ajuste Trimestral B2G") else []
                return (
                    # Totalizações juntas no início: Total + Comissão Trim. + Ajuste Trim. B2G
                    _B2G_FIXED + _tot_cols + _aj_final
                    + ["Realizado (Booking)", "Meta (Booking)", "% Ating. (Booking)"]
                    + _arr + _gest
                    + ["% Atingido Pond."]
                    + _desc
                    + ["OTE Base", "Acelerador OTE", "OTE Ajustado", "OTE Variável"]
                    + [c for c in _TRIM if _has_any(c)]
                    # Ajuste Trimestral (detalhe acumulado) = último grupo
                    + _acum_base + _acum_arr + _acum_gest + _acum_ote
                )

            _cols_reg  = _b2g_cols_show(_df_reg)
            _cols_marc = _b2g_cols_show(_df_marc)
            # For marcelo, rename gestor-specific columns to his labels
            _marc_rename = {
                "% Equipe c/ Meta":           "Aproveit. Equipe",
                "Meta Eq. c/ Meta":           "Meta Aproveit.",
                "% Ating. (Meta Eq.)":        "% Ating. (Aproveit.)",
                "Aj. Trim. % Equipe c/ Meta":     "Aj. Trim. Aproveit. Equipe",
                "Aj. Trim. % Ating. (Meta Eq.)":  "Aj. Trim. % Ating. (Aproveit.)",
            }

            # Build display DataFrames (will be used for table + download)
            # Use df_raw for _col_has_data/_col_has_any defined above (reset to _df_reg)
            df_raw = _df_reg  # switch reference for the shared formatting below
            cols_show = _cols_reg
        elif is_gd_export:
            _GD_FIXED = ["Ano", "Mês", "Nome", "Equipe", "Cargo", "Total"]
            if _col_has_data("Comissão Trimestral"):
                _GD_FIXED.insert(_GD_FIXED.index("Total") + 1, "Comissão Trimestral")
            cols_show = (
                _GD_FIXED
                + ["Realizado (Opps)", "Meta (Opps)", "% Atingido"]
                + _desconto_cols
                + ["OTE Base", "Acelerador OTE", "OTE Ajustado", "OTE Variável"]
                + [c for c in [f"Ajuste de {mes_nome}"] if _col_has_data(c)]
                + [c for c in _TRIM if _col_has_any(c)]
            )
            cols_show = [c for c in cols_show if c in df_raw.columns]
        elif is_pvt_export:
            cols_show = [c for c in [
                "Ano", "Mês", "Nome", "Email", "Equipe", "Total",
                "OTE Base", "Acelerador OTE", "OTE Ajustado",
                "% NMRR", "Meta NMRR", "Real NMRR",
                "% Booking", "Meta Booking", "Real Booking",
                "% Atingimento Pond.",
            ] if c in df_raw.columns]
        else:
            _BK_EXTRA_GROUP = ["Booking Extra", "% Comissão Extra", "Comissão Extra"]
            _OPT = [
                "Comissão Trimestral",
                "Dívidas Pagas", "Comissão Dívidas",
                f"Ajuste de {mes_nome}",
                "% Proteção", "Premiação",
            ]
            _is_saving_export = "_is_saving" in df_raw.columns and bool(df_raw["_is_saving"].any())
            _all_groups = _OPT + _BK_EXTRA_GROUP + _DESCONTO_GROUP + _TRIM + ["_is_saving"]
            _non_opt = [c for c in df_raw.columns if c not in _all_groups]
            if _col_has_data("Comissão Trimestral") and "Total" in _non_opt:
                _tidx = _non_opt.index("Total") + 1
                _non_opt = _non_opt[:_tidx] + ["Comissão Trimestral"] + _non_opt[_tidx:]
            _bk_extra_cols = _BK_EXTRA_GROUP if _col_has_data("Comissão Extra") else []
            if _desconto_cols and "OTE Base" in _non_opt:
                _ote_idx = _non_opt.index("OTE Base")
                _non_opt = _non_opt[:_ote_idx] + _desconto_cols + _non_opt[_ote_idx:]
                _desconto_cols = []
            cols_show = (
                _non_opt
                + _desconto_cols
                + _bk_extra_cols
                + [c for c in _OPT if c != "Comissão Trimestral" and _col_has_data(c)]
                + [c for c in _TRIM if _col_has_any(c)]
            )
            if _is_saving_export and mes >= 6:
                cols_show = [c for c in cols_show if c != "OTE Ajustado"]
        df_show = df_raw[cols_show].copy()

        # ── Formatação para exibição ──────────────────────────────────────────
        _BRL_COLS = {
            "Total", "Variável OTE", "Realizado", "Meta", "OTE Cheio", "OTE Base", "OTE Ajustado",
            "Meta NMRR", "Real NMRR", "Meta Booking", "Real Booking",
            "OTE Variável", "Booking Extra", "Comissão Extra", "Dívidas Pagas",
            "Comissão Dívidas", "Premiação",
            f"Ajuste de {mes_nome}",
            "Trim. Realizado Ind.", "Trim. Meta Ind.",
            "Trim. Realizado Eq.",  "Trim. Meta Eq.",
            # B2G
            "Ajuste Trimestral B2G",
            "Realizado (Booking)", "Meta (Booking)",
            "Realizado (ARR)",     "Meta (ARR)",
            "Aj. Trim. Realizado (Booking)", "Aj. Trim. Meta (Booking)",
            "Aj. Trim. Realizado (ARR)",     "Aj. Trim. Meta (ARR)",
            "Aj. Trim. OTE Base", "Aj. Trim. OTE Variável",
            "Pago nos 3 Meses",
        }
        _PCT_COLS = {
            "% NMRR", "% Booking", "% Atingimento Pond.",
            "% Atingido", "% À Vista", "% CC até 3x", "% CC até 12x", "% Recorrente",
            "Mult. À Vista", "Mult. CC até 3x", "Mult. CC até 12x", "Mult. Recorrente",
            "Desconto", "Acelerador OTE", "% Comissão Extra",
            "% Proteção",
            "Trim. % Ating. Ind.", "Trim. Fator Ind.",
            "Trim. % Ating. Eq.",  "Trim. Fator Eq.",
            # B2G
            "% Ating. (Booking)", "% Ating. (ARR)", "% Atingido Pond.",
            "% Equipe c/ Meta", "Meta Eq. c/ Meta", "% Ating. (Meta Eq.)",
            "Aj. Trim. % Ating. (Booking)", "Aj. Trim. % Ating. (ARR)", "Aj. Trim. % Atingido Pond.",
            "Aj. Trim. % Equipe c/ Meta", "Aj. Trim. % Ating. (Meta Eq.)", "Aj. Trim.Acelerador OTE",
            # marcelo renamed
            "Aproveit. Equipe", "Meta Aproveit.", "% Ating. (Aproveit.)",
            "Aj. Trim. Aproveit. Equipe", "Aj. Trim. % Ating. (Aproveit.)",
        }

        # Trimestral de equipe fica EM BRANCO (não "—") para líderes — que têm
        # esses campos como None (ver montagem das linhas). Só líderes produzem
        # "—" nessas colunas (consultores sempre têm número), então é seguro.
        _TRIM_EQ_COLS = ("Trim. Realizado Eq.", "Trim. Meta Eq.",
                         "Trim. % Ating. Eq.", "Trim. Fator Eq.")
        def _blank_trim_eq(d):
            for _c in _TRIM_EQ_COLS:
                if _c in d.columns:
                    d[_c] = d[_c].replace("—", "")
            return d

        df_disp = df_show.copy()
        if "Comissão Trimestral" in df_disp.columns:
            df_disp["Comissão Trimestral"] = df_disp["Comissão Trimestral"].apply(
                lambda v: f"{pct_fmt(v)} de um Salário" if pd.notna(v) and v != 0 else "—"
            )
        for col in df_disp.columns:
            if col == "Comissão Trimestral":
                continue
            if col in _GD_INT_COLS:
                df_disp[col] = df_disp[col].apply(
                    lambda v: f"{int(v):,}".replace(",", ".") if pd.notna(v) and v not in (None, "") else "—"
                )
            elif col in _BRL_COLS:
                df_disp[col] = df_disp[col].apply(
                    lambda v: brl(v) if pd.notna(v) and v not in (None, "") else "—"
                )
            elif col in _PCT_COLS:
                df_disp[col] = df_disp[col].apply(
                    lambda v: pct_fmt(v) if pd.notna(v) and v not in (None, "") else "—"
                )
        _blank_trim_eq(df_disp)

        subheader_dict = {col: _cat(col) for col in df_disp.columns}

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        html_table(df_disp, scrollable=True, subheader=subheader_dict)

        # ── Segunda tabela: SDR (Escritório e outras equipes com SDR) ─────────
        if not is_b2g_export and not is_gd_export and rows_gd:
            df_sdr = pd.DataFrame(rows_gd).sort_values("Nome").reset_index(drop=True)
            if "Cargo" in df_sdr.columns:
                df_sdr["Cargo"] = df_sdr["Cargo"].apply(
                    lambda v: _fmt_cargo(v) if isinstance(v, str) and v else v
                )
            _sdr_fixed = ["Ano", "Mês", "Nome", "Equipe", "Cargo", "Total"]
            if "Comissão Trimestral" in df_sdr.columns and (df_sdr["Comissão Trimestral"].fillna(0) != 0).any():
                _sdr_fixed.insert(_sdr_fixed.index("Total") + 1, "Comissão Trimestral")
            _sdr_cols = (
                _sdr_fixed
                + ["Realizado (Opps)", "Meta (Opps)", "% Atingido"]
                + (["OTE Cheio", "Desconto"] if "Desconto" in df_sdr.columns and (df_sdr["Desconto"].fillna(0) != 0).any() else [])
                + ["OTE Base", "Acelerador OTE", "OTE Ajustado", "OTE Variável"]
                + [c for c in [f"Ajuste de {mes_nome}"] if c in df_sdr.columns and (df_sdr[c].fillna(0) != 0).any()]
                + [c for c in _TRIM if c in df_sdr.columns and df_sdr[c].notna().any()]
            )
            _sdr_cols = [c for c in _sdr_cols if c in df_sdr.columns]
            _sdr_disp = df_sdr[_sdr_cols].copy()
            if "Comissão Trimestral" in _sdr_disp.columns:
                _sdr_disp["Comissão Trimestral"] = _sdr_disp["Comissão Trimestral"].apply(
                    lambda v: f"{pct_fmt(v)} de um Salário" if pd.notna(v) and v != 0 else "—"
                )
            for _sc in _sdr_disp.columns:
                if _sc == "Comissão Trimestral": continue
                if _sc in (_GD_INT_COLS | _GD_TRIM_INT):
                    _sdr_disp[_sc] = _sdr_disp[_sc].apply(lambda v: f"{int(v):,}".replace(",", ".") if pd.notna(v) and v not in (None, "") else "—")
                elif _sc in _BRL_COLS:
                    _sdr_disp[_sc] = _sdr_disp[_sc].apply(lambda v: brl(v) if pd.notna(v) and v not in (None, "") else "—")
                elif _sc in _PCT_COLS:
                    _sdr_disp[_sc] = _sdr_disp[_sc].apply(lambda v: pct_fmt(v) if pd.notna(v) and v not in (None, "") else "—")
            _blank_trim_eq(_sdr_disp)
            _sdr_sub = {col: _cat(col) for col in _sdr_disp.columns}
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            html_table(_sdr_disp, scrollable=True, subheader=_sdr_sub)

        if is_b2g_export and not _df_marc.empty:
            _marc_disp = _df_marc[_cols_marc].rename(columns=_marc_rename).copy()
            if "Comissão Trimestral" in _marc_disp.columns:
                _marc_disp["Comissão Trimestral"] = _marc_disp["Comissão Trimestral"].apply(
                    lambda v: f"{pct_fmt(v)} de um Salário" if pd.notna(v) and v != 0 else "—"
                )
            for _col in _marc_disp.columns:
                if _col == "Comissão Trimestral":
                    continue
                if _col in _BRL_COLS:
                    _marc_disp[_col] = _marc_disp[_col].apply(lambda v: brl(v) if pd.notna(v) and v not in (None, "") else "—")
                elif _col in _PCT_COLS:
                    _marc_disp[_col] = _marc_disp[_col].apply(lambda v: pct_fmt(v) if pd.notna(v) and v not in (None, "") else "—")
            _blank_trim_eq(_marc_disp)
            _marc_sub = {col: _cat(col) for col in _marc_disp.columns}
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            html_table(_marc_disp, scrollable=True, subheader=_marc_sub)

        # ── Download ─────────────────────────────────────────────────────────
        _eq_slug = equipe_sel.replace(" ", "_").replace("/", "-")

        def _dl_link(data: bytes, filename: str, label: str, mime: str) -> None:
            st.markdown(download_link(data, filename, label, mime),
                        unsafe_allow_html=True)

        def _fmt_df(df_s):
            """Formata um DataFrame de exibição (BRL/PCT) e prepende linha de categoria."""
            d = df_s.copy()
            if "Comissão Trimestral" in d.columns:
                d["Comissão Trimestral"] = d["Comissão Trimestral"].apply(
                    lambda v: f"{pct_fmt(v)} de um Salário" if pd.notna(v) and v != 0 else "—"
                )
            for col in d.columns:
                if col == "Comissão Trimestral":
                    continue
                if col in _BRL_COLS:
                    d[col] = d[col].apply(lambda v: brl(v) if pd.notna(v) and v not in (None, "") else "—")
                elif col in _PCT_COLS:
                    d[col] = d[col].apply(lambda v: pct_fmt(v) if pd.notna(v) and v not in (None, "") else "—")
            _blank_trim_eq(d)
            cat_row = pd.DataFrame([{col: _cat(col) for col in d.columns}])
            return pd.concat([cat_row, d], ignore_index=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        try:
            import openpyxl  # noqa: F401
            buf = io.BytesIO()
            if is_b2g_export:
                # Two sheets: Consultores (regular B2G) + Gestão (marcelo)
                _df_show_reg  = _df_reg[_cols_reg].copy()
                _df_show_marc = _df_marc[_cols_marc].rename(columns=_marc_rename).copy() if not _df_marc.empty else pd.DataFrame()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    _fmt_df(_df_show_reg).to_excel(writer, index=False, sheet_name="Consultores")
                    if not _df_show_marc.empty:
                        _fmt_df(_df_show_marc).to_excel(writer, index=False, sheet_name="Gestão")
            else:
                _cat_row_df = pd.DataFrame([{col: _cat(col) for col in df_disp.columns}])
                df_export = pd.concat([_cat_row_df, df_disp], ignore_index=True)
                _sheet_name = "GD" if is_gd_export else mes_nome[:31]
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_export.to_excel(writer, index=False, sheet_name=_sheet_name)
                    if rows_gd and not is_gd_export:
                        _sdr_raw = pd.DataFrame(rows_gd).sort_values("Nome").reset_index(drop=True)
                        _xls_fixed = ["Ano", "Mês", "Nome", "Equipe", "Cargo", "Total"]
                        if "Comissão Trimestral" in _sdr_raw.columns and (_sdr_raw["Comissão Trimestral"].fillna(0) != 0).any():
                            _xls_fixed.insert(_xls_fixed.index("Total") + 1, "Comissão Trimestral")
                        _xls_sdr = (
                            _xls_fixed
                            + ["Realizado (Opps)", "Meta (Opps)", "% Atingido"]
                            + (["OTE Cheio", "Desconto"] if "Desconto" in _sdr_raw.columns and (_sdr_raw["Desconto"].fillna(0) != 0).any() else [])
                            + ["OTE Base", "Acelerador OTE", "OTE Ajustado", "OTE Variável"]
                            + [c for c in [f"Ajuste de {mes_nome}"] if c in _sdr_raw.columns and (_sdr_raw[c].fillna(0) != 0).any()]
                            + [c for c in _TRIM if c in _sdr_raw.columns and _sdr_raw[c].notna().any()]
                        )
                        _xls_sdr = [c for c in _xls_sdr if c in _sdr_raw.columns]
                        _sdr_fmtd = _sdr_raw[_xls_sdr].copy()
                        if "Comissão Trimestral" in _sdr_fmtd.columns:
                            _sdr_fmtd["Comissão Trimestral"] = _sdr_fmtd["Comissão Trimestral"].apply(
                                lambda v: f"{pct_fmt(v)} de um Salário" if pd.notna(v) and v != 0 else "—"
                            )
                        for _xc in _sdr_fmtd.columns:
                            if _xc == "Comissão Trimestral": continue
                            if _xc in (_GD_INT_COLS | _GD_TRIM_INT):
                                _sdr_fmtd[_xc] = _sdr_fmtd[_xc].apply(
                                    lambda v: int(float(v)) if pd.notna(v) and v not in (None, "") else None
                                )
                            elif _xc in _BRL_COLS:
                                _sdr_fmtd[_xc] = _sdr_fmtd[_xc].apply(lambda v: brl(v) if pd.notna(v) and v not in (None, "") else "—")
                            elif _xc in _PCT_COLS:
                                _sdr_fmtd[_xc] = _sdr_fmtd[_xc].apply(lambda v: pct_fmt(v) if pd.notna(v) and v not in (None, "") else "—")
                        _blank_trim_eq(_sdr_fmtd)
                        _sdr_cat = pd.DataFrame([{col: _cat(col) for col in _sdr_fmtd.columns}])
                        pd.concat([_sdr_cat, _sdr_fmtd], ignore_index=True).to_excel(
                            writer, index=False, sheet_name="SDR"
                        )
            _dl_link(
                buf.getvalue(),
                f"comissoes_{ano}_{mes:02d}_{_eq_slug}.xlsx",
                "Exportar",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception:
            # Sem openpyxl: fallback CSV. No B2G as duas tabelas têm colunas
            # diferentes (ARR vs. Aproveitamento) e não cabem numa mesma planilha,
            # então geramos um link por tabela — ambas ficam disponíveis.
            if is_b2g_export:
                _reg_csv = _fmt_df(_df_reg[_cols_reg].copy()).to_csv(
                    index=False, sep=";").encode("utf-8-sig")
                _links = [(_reg_csv,
                           f"comissoes_{ano}_{mes:02d}_{_eq_slug}_Consultores.csv",
                           "Exportar Consultores")]
                if not _df_marc.empty:
                    _marc_csv = _fmt_df(
                        _df_marc[_cols_marc].rename(columns=_marc_rename).copy()
                    ).to_csv(index=False, sep=";").encode("utf-8-sig")
                    _links.append((_marc_csv,
                                   f"comissoes_{ano}_{mes:02d}_{_eq_slug}_Gestao.csv",
                                   "Exportar Gestão"))
                _html = " ".join(
                    f"<span style='margin-right:8px;'>"
                    f"{download_link(_d, _fn, _lbl, 'text/csv')}</span>"
                    for _d, _fn, _lbl in _links
                )
                st.markdown(_html, unsafe_allow_html=True)
            else:
                _cat_row_df = pd.DataFrame([{col: _cat(col) for col in df_disp.columns}])
                df_export = pd.concat([_cat_row_df, df_disp], ignore_index=True)
                csv_bytes = df_export.to_csv(index=False, sep=";").encode("utf-8-sig")
                _dl_link(
                    csv_bytes,
                    f"comissoes_{ano}_{mes:02d}_{_eq_slug}.csv",
                    "Exportar",
                    "text/csv",
                )
                if rows_gd and not is_gd_export:
                    _sdr_csv_df = pd.DataFrame(rows_gd).sort_values("Nome").reset_index(drop=True)
                    _sdr_cat2 = pd.DataFrame([{col: _cat(col) for col in _sdr_csv_df.columns}])
                    _sdr_csv_bytes = pd.concat([_sdr_cat2, _sdr_csv_df], ignore_index=True).to_csv(
                        index=False, sep=";"
                    ).encode("utf-8-sig")
                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                    _dl_link(
                        _sdr_csv_bytes,
                        f"comissoes_{ano}_{mes:02d}_{_eq_slug}_SDR.csv",
                        "Exportar SDR",
                        "text/csv",
                    )

        # ── Fechar comissão (snapshot) ─────────────────────────────────────────
        st.markdown(
            "<hr style='margin:14px 0 8px;border:none;border-top:2px solid #b0b0b0;'>",
            unsafe_allow_html=True,
        )

        # Resultado do fechamento (gravado antes do rerun para limpar os botões)
        if "_fechar_ok_" in st.session_state:
            st.markdown(
                f"<div style='color:#1a1a1a;background:#dcfce7;border-radius:6px;"
                f"padding:0.6rem 0.9rem;border-left:4px solid #16a34a;margin:0.4rem 0;'>"
                f"✓ {st.session_state.pop('_fechar_ok_')}</div>",
                unsafe_allow_html=True,
            )
        if "_fechar_warn_" in st.session_state:
            st.warning(st.session_state.pop("_fechar_warn_"))
        if "_fechar_err_" in st.session_state:
            st.error(st.session_state.pop("_fechar_err_"))
        if "_abrir_ok_" in st.session_state:
            st.markdown(
                f"<div style='color:#1a1a1a;background:#dcfce7;border-radius:6px;"
                f"padding:0.6rem 0.9rem;border-left:4px solid #16a34a;margin:0.4rem 0;'>"
                f"✓ {st.session_state.pop('_abrir_ok_')}</div>",
                unsafe_allow_html=True,
            )
        if "_abrir_err_" in st.session_state:
            st.error(st.session_state.pop("_abrir_err_"))

        # ── Máquina de estados: fechar em chunks ──────────────────────────────
        if "_fechar_state_" in st.session_state:
            _fs  = st.session_state["_fechar_state_"]
            _idx = _fs["idx"]
            _tot = len(_fs["emails"])
            if _idx < _tot:
                st.progress(
                    _idx / _tot,
                    text=f"Calculando {_idx + 1}/{_tot}: {_fs['emails'][_idx].split('@')[0]}…",
                )
                _em = _fs["emails"][_idx]
                try:
                    _rr, _cr, _err = fechar_um(_em, _fs["ano"], _fs["mes"], _fs["equipe"])
                    if _err:
                        _fs["erros"].append(_em)
                    else:
                        _fs["res_rows"].append(_rr)
                        _fs["comp_rows"].extend(_cr)
                except Exception as _fe:
                    if _is_xp_err(_fe):
                        compat_rerun()
                    _fs["erros"].append(_em)
                _fs["idx"] += 1
                compat_rerun()
            else:
                st.progress(1.0, text="Gravando snapshot…")
                try:
                    _r = fechar_inserir(
                        session, _fs["ano"], _fs["mes"], _fs["equipe"],
                        _fs["usuario"], _fs["res_rows"], _fs["comp_rows"],
                    )
                    st.session_state["_fechar_ok_"] = (
                        f"Comissão fechada: {_r['fechamento_id']} — "
                        f"{_r['n_pessoas']} pessoa(s), {_r['n_composicao']} linha(s) de composição."
                    )
                    if _fs["erros"]:
                        st.session_state["_fechar_warn_"] = (
                            "Não calculados: " + ", ".join(_fs["erros"])
                        )
                    # Sem isso, _get_snapshot_fid (ttl longo) seguiria
                    # roteando o período recém-fechado para o cálculo ao vivo.
                    clear_comissao_cache()
                except Exception as _fe:
                    if _is_xp_err(_fe):
                        compat_rerun()
                    st.session_state["_fechar_err_"] = f"Falha ao gravar: {_fe}"
                del st.session_state["_fechar_state_"]
                compat_rerun()

        try:
            _ja = periodo_fechado(session, ano, mes, equipe_sel)
        except Exception as _qe:
            if _is_xp_err(_qe):
                compat_rerun()
            st.error(f"Erro ao verificar fechamento: {_qe}")
            st.stop()
        if _ja:
            st.markdown(
                f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
                f"padding:0.6rem 0.9rem;border-left:4px solid #0c5a93;margin:0.4rem 0;'>"
                f"Já existe fechamento ativo desta equipe/período (v{_ja['versao']}). "
                f"Fechar de novo cria a v{_ja['versao'] + 1} e substitui a anterior.</div>",
                unsafe_allow_html=True,
            )
            if not st.session_state.get("_abrir_confirmar_") and not st.session_state.get("_fechar_confirmar_"):
                if st.button("🔓 Abrir Comissão", key="_btn_abrir_"):
                    st.session_state["_abrir_confirmar_"] = True
                    compat_rerun()
            elif st.session_state.get("_abrir_confirmar_"):
                st.markdown(
                    f"<div style='color:#1a1a1a;font-weight:700;font-size:1.02rem;margin:2px 0 6px;'>"
                    f"Abrir a comissão de {equipe_sel} — {mes_nome}/{ano}? "
                    f"O período voltará a calcular ao vivo; o snapshot v{_ja['versao']} ficará preservado mas inativo.</div>",
                    unsafe_allow_html=True,
                )
                _ab1, _ab2, _ab3 = st.columns([1, 1, 4])
                if _ab1.button("✓ Confirmar", key="_btn_abrir_ok_", use_container_width=True):
                    try:
                        reabrir_fechamento(session, equipe_sel, ano, mes)
                        clear_comissao_cache()
                        st.session_state["_abrir_ok_"] = (
                            f"Comissão de {equipe_sel} — {mes_nome}/{ano} reaberta. "
                            f"Os cálculos voltaram a ser ao vivo."
                        )
                    except Exception as _ae:
                        st.session_state["_abrir_err_"] = f"Falha ao reabrir: {_ae}"
                    st.session_state.pop("_abrir_confirmar_", None)
                    compat_rerun()
                if _ab2.button("Cancelar", key="_btn_abrir_cancel_", use_container_width=True):
                    st.session_state.pop("_abrir_confirmar_", None)
                    compat_rerun()

        if not st.session_state.get("_fechar_confirmar_"):
            if st.button("🔒 Fechar comissão", key="_btn_fechar_"):
                st.session_state["_fechar_confirmar_"] = True
                compat_rerun()
        else:
            st.markdown(
                f"<div style='color:#1a1a1a;font-weight:700;font-size:1.02rem;margin:2px 0 6px;'>"
                f"Fechar a comissão de {equipe_sel} — {mes_nome}/{ano}? "
                f"Isso congela os números atuais num snapshot imutável.</div>",
                unsafe_allow_html=True,
            )
            _cf1, _cf2, _cf3 = st.columns([1, 1, 4])
            if _cf1.button("✓ Confirmar", key="_btn_fechar_ok_", use_container_width=True):
                try:
                    if equipe_sel == "PVT":
                        _pvt_rows = _calcular_pvt_export(
                            session, ano, mes, {}, MESES.get(mes, str(mes))
                        )
                        if not _pvt_rows:
                            st.session_state["_fechar_err_"] = (
                                f"Nenhum consultor em 'PVT' para {mes:02d}/{ano}."
                            )
                        else:
                            _res_pvt = [
                                [r["Email"], "PVT", r["Total"], json.dumps(r, default=str)]
                                for r in _pvt_rows
                            ]
                            _r = fechar_inserir(
                                session, ano, mes, "PVT", _usuario, _res_pvt, []
                            )
                            st.session_state["_fechar_ok_"] = (
                                f"Comissão fechada: {_r['fechamento_id']} — "
                                f"{_r['n_pessoas']} pessoas."
                            )
                    else:
                        _emails_fechar = fechar_consultores(session, ano, mes, equipe_sel)
                        if not _emails_fechar:
                            st.session_state["_fechar_err_"] = (
                                f"Nenhum consultor em '{equipe_sel}' para {mes:02d}/{ano}."
                            )
                        else:
                            clear_comissao_cache()
                            st.session_state["_fechar_state_"] = {
                                "emails":    _emails_fechar,
                                "idx":       0,
                                "res_rows":  [],
                                "comp_rows": [],
                                "erros":     [],
                                "ano":       ano,
                                "mes":       mes,
                                "equipe":    equipe_sel,
                                "usuario":   _usuario,
                            }
                except Exception as _e:
                    st.session_state["_fechar_err_"] = f"Erro ao iniciar fechamento: {_e}"
                st.session_state.pop("_fechar_confirmar_", None)
                compat_rerun()
            if _cf2.button("Cancelar", key="_btn_fechar_cancel_", use_container_width=True):
                st.session_state.pop("_fechar_confirmar_", None)
                compat_rerun()


