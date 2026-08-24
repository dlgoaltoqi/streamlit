"""Blocos da tela Comissão PVT — porta de pages/22_Comissao_PVT.py.

Parâmetros fixos do modelo (cliff 80%, aceleradores 1,15×/1,25×, OTE 3.600,
ponderação 60/40) e as mesmas 5 queries, com binds. Read-only por natureza.
"""
import pandas as pd

from webapp.core.cache import LIVE, ttl_cached
from webapp.core.periods import MESES_ABREV
from webapp.db.pool import get_pool
from webapp.presentation import brl, html_table_str, pct_fmt

CLIFF_GERAL = 0.80
MULT_115_CLIFF = 0.90
MULT_125_CLIFF = 1.00
OTE_BASE = 3_600.0
POND_NMRR = 0.60
POND_OTR = 0.40

TRIMESTRES = {"Q1": [1, 2, 3], "Q2": [4, 5, 6], "Q3": [7, 8, 9], "Q4": [10, 11, 12]}
_EQUIPE_ORDER = ["B2B Escritório", "B2B Construtora", "Farmer", "Ares"]


def _meses_in(trim):
    return ", ".join(str(m) for m in TRIMESTRES[trim])


@ttl_cached(LIVE)
def _load_fechamento_status(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            SELECT EQUIPE, MES, DATA_FECHAMENTO
            FROM SUPERSET.COMISSOES.FECHAMENTOS
            WHERE ANO = {int(ano)} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
              AND EQUIPE IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Governo', 'B2G')
            ORDER BY MES, EQUIPE
        """).to_pandas()


@ttl_cached(LIVE)
def _load_nmrr_real(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            WITH fechamentos_ativos AS (
                SELECT EQUIPE, MES, FECHAMENTO_ID
                FROM SUPERSET.COMISSOES.FECHAMENTOS
                WHERE ANO = {int(ano)} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
                  AND EQUIPE IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
            ),
            deals_fechados AS (
                SELECT DISTINCT cf.EQUIPE, cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
                FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
                JOIN fechamentos_ativos fa
                  ON fa.FECHAMENTO_ID = cf.FECHAMENTO_ID
                 AND fa.EQUIPE = cf.EQUIPE AND fa.MES = cf.MES
                WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
            ),
            nmrr_fechado AS (
                SELECT v.VERTICAL AS EQUIPE, v.MES,
                       SUM(CASE WHEN v.VERTICAL = 'Farmer'
                                THEN COALESCE(v.MRR_EXPANSAO, 0)
                                ELSE COALESCE(v.NMRR, 0) END) AS VALOR
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_fechados d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                    AND d.EQUIPE = v.VERTICAL AND d.MES = v.MES
                WHERE v.ANO = {int(ano)} AND v.MES IN ({meses_in})
                GROUP BY 1, v.MES
            ),
            deals_ok AS (
                SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
                UNION
                SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
                WHERE ANO = {int(ano)} AND MES IN ({meses_in})
                GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
            ),
            nmrr_vivo AS (
                SELECT v.VERTICAL AS EQUIPE, v.MES,
                       SUM(CASE WHEN v.VERTICAL = 'Farmer'
                                THEN COALESCE(v.MRR_EXPANSAO, 0)
                                ELSE COALESCE(v.NMRR, 0) END) AS VALOR
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                LEFT JOIN fechamentos_ativos fa
                    ON fa.EQUIPE = v.VERTICAL AND fa.MES = v.MES
                WHERE v.ANO = {int(ano)} AND v.MES IN ({meses_in})
                  AND v.VERTICAL IN ('B2B Escritório', 'B2B Construtora', 'Farmer', 'Ares')
                  AND fa.EQUIPE IS NULL
                GROUP BY 1, v.MES
            )
            SELECT EQUIPE, MES, SUM(VALOR) AS VALOR
            FROM (SELECT * FROM nmrr_fechado UNION ALL SELECT * FROM nmrr_vivo)
            GROUP BY EQUIPE, MES
        """).to_pandas()


@ttl_cached(LIVE)
def _load_otr_real(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            WITH fechamentos_b2g AS (
                SELECT MES, FECHAMENTO_ID
                FROM SUPERSET.COMISSOES.FECHAMENTOS
                WHERE ANO = {int(ano)} AND MES IN ({meses_in}) AND STATUS = 'ATIVO'
                  AND EQUIPE IN ('Governo', 'B2G')
            ),
            deals_fechados AS (
                SELECT DISTINCT cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
                FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
                JOIN fechamentos_b2g fb ON fb.FECHAMENTO_ID = cf.FECHAMENTO_ID AND fb.MES = cf.MES
                WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
            ),
            otr_fechado AS (
                SELECT v.MES, SUM(COALESCE(v.BOOKING, 0)) AS VALOR
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_fechados d ON d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES
                WHERE v.ANO = {int(ano)} AND v.MES IN ({meses_in})
                  AND v.VERTICAL = 'B2G'
                GROUP BY v.MES
            ),
            deals_ok AS (
                SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
                UNION
                SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
                WHERE ANO = {int(ano)} AND MES IN ({meses_in})
                GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
            ),
            otr_vivo AS (
                SELECT v.MES, SUM(COALESCE(v.BOOKING, 0)) AS VALOR
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                LEFT JOIN fechamentos_b2g fb ON fb.MES = v.MES
                WHERE v.ANO = {int(ano)} AND v.MES IN ({meses_in}) AND v.VERTICAL = 'B2G'
                  AND fb.MES IS NULL
                GROUP BY v.MES
            )
            SELECT MES, SUM(VALOR) AS VALOR
            FROM (SELECT * FROM otr_fechado UNION ALL SELECT * FROM otr_vivo)
            GROUP BY MES
        """).to_pandas()


@ttl_cached(LIVE)
def _load_nmrr_meta(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            SELECT m.EQUIPE, m.MES, SUM(COALESCE(m.META_NMRR, 0)) AS VALOR
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
            JOIN SUPERSET.COMISSOES.PARAMETROS p
              ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
             AND p.ANO = {int(ano)} AND p.MES = m.MES
             AND p.IS_GESTOR = TRUE
            WHERE m.ANO = {int(ano)} AND m.MES IN ({meses_in})
              AND m.EQUIPE IN ('B2B Escritório', 'B2B Construtora')
            GROUP BY m.EQUIPE, m.MES

            UNION ALL

            SELECT 'Farmer' AS EQUIPE, MES, SUM(COALESCE(META_EXPANSAO, 0)) AS VALOR
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = {int(ano)} AND MES IN ({meses_in}) AND EQUIPE = 'Sonia'
            GROUP BY MES
        """).to_pandas()


@ttl_cached(LIVE)
def _load_otr_meta(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            SELECT m.MES, SUM(COALESCE(m.META_OTR, 0)) AS VALOR
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
            JOIN SUPERSET.COMISSOES.PARAMETROS p
              ON LOWER(m.CONSULTOR) = LOWER(p.EMAIL)
             AND p.ANO = {int(ano)} AND p.MES = m.MES
             AND COALESCE(p.IS_GESTOR, FALSE) = FALSE
            WHERE m.ANO = {int(ano)} AND m.MES IN ({meses_in}) AND m.EQUIPE IN ('Governo', 'B2G')
            GROUP BY m.MES
        """).to_pandas()


@ttl_cached(LIVE)
def _load_overrides(ano: int, meses_in: str) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql(f"""
            SELECT MES, EQUIPE, REAL_NMRR, META_NMRR, REAL_OTR, META_OTR
            FROM SUPERSET.COMISSOES.PVT_OVERRIDES
            WHERE ANO = {int(ano)} AND MES IN ({meses_in})
              AND (REAL_NMRR IS NOT NULL OR META_NMRR IS NOT NULL
                   OR REAL_OTR IS NOT NULL OR META_OTR IS NOT NULL)
        """).to_pandas()


def _notnull(v):
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def _aplicar_overrides(df_nr, df_nm, df_or, df_om, df_ov):
    for _, ov in df_ov.iterrows():
        m, eq = int(ov["MES"]), str(ov["EQUIPE"])
        if eq != "B2G":
            if _notnull(ov["REAL_NMRR"]):
                msk = (df_nr["MES"] == m) & (df_nr["EQUIPE"] == eq)
                if msk.any():
                    df_nr.loc[msk, "VALOR"] = float(ov["REAL_NMRR"])
                else:
                    df_nr = pd.concat([df_nr, pd.DataFrame(
                        [{"EQUIPE": eq, "MES": m, "VALOR": float(ov["REAL_NMRR"])}])],
                        ignore_index=True)
            if _notnull(ov["META_NMRR"]):
                msk = (df_nm["MES"] == m) & (df_nm["EQUIPE"] == eq)
                if msk.any():
                    df_nm.loc[msk, "VALOR"] = float(ov["META_NMRR"])
                else:
                    df_nm = pd.concat([df_nm, pd.DataFrame(
                        [{"EQUIPE": eq, "MES": m, "VALOR": float(ov["META_NMRR"])}])],
                        ignore_index=True)
        else:
            if _notnull(ov["REAL_OTR"]):
                msk = df_or["MES"] == m
                if msk.any():
                    df_or.loc[msk, "VALOR"] = float(ov["REAL_OTR"])
                else:
                    df_or = pd.concat([df_or, pd.DataFrame(
                        [{"MES": m, "VALOR": float(ov["REAL_OTR"])}])], ignore_index=True)
            if _notnull(ov["META_OTR"]):
                msk = df_om["MES"] == m
                if msk.any():
                    df_om.loc[msk, "VALOR"] = float(ov["META_OTR"])
                else:
                    df_om = pd.concat([df_om, pd.DataFrame(
                        [{"MES": m, "VALOR": float(ov["META_OTR"])}])], ignore_index=True)
    return df_nr, df_nm, df_or, df_om


def _card_comissao(trim, ano, comissao, ote_ajustado, total_atingimento,
                   pct_nmrr, pct_otr, acelerador, acel_label, acel_cor):
    cor = "#16a34a" if comissao > 0 else "#374151"
    sub = "#9ca3af"
    td3 = f"style='text-align:right;font-size:.7rem;color:{sub};padding-left:10px;white-space:nowrap;'"
    calc_pond = f"60% × {pct_fmt(pct_nmrr)}&nbsp;+&nbsp;40% × {pct_fmt(pct_otr)}"
    if acelerador == 0.0:
        calc_acel = f"pond. &lt; {pct_fmt(CLIFF_GERAL)}"
    elif acelerador == 1.15:
        calc_acel = f"pond. ≥ {pct_fmt(MULT_115_CLIFF)}"
    elif acelerador == 1.25:
        calc_acel = f"pond. ≥ {pct_fmt(MULT_125_CLIFF)}"
    else:
        calc_acel = f"{pct_fmt(CLIFF_GERAL)} ≤ pond. &lt; {pct_fmt(MULT_115_CLIFF)}"
    acel_str = "0×" if acelerador == 0.0 else f"{acelerador:.2f}×".replace(".", ",")
    return (
        f"<div style='background:#f0fdf4;border-radius:8px;padding:1rem 1.2rem;"
        f"border:1px solid #d1fae5;border-left:5px solid {cor};'>"
        f"<div style='font-size:0.78rem;font-weight:700;color:#1a1a1a;"
        f"text-transform:uppercase;letter-spacing:.04em;margin-bottom:.5rem;'>"
        f"Comissão {trim}/{ano}</div>"
        f"<div style='font-size:2rem;font-weight:700;color:{cor};line-height:1.1;'>"
        f"{brl(comissao)}</div>"
        f"<div style='font-size:0.82rem;color:{sub};margin-top:.3rem;margin-bottom:.9rem;'>"
        f"{brl(ote_ajustado)} × {pct_fmt(total_atingimento)}</div>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.84rem;'>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Atingimento ponderado</td>"
        f"<td {td3}>{calc_pond}</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{pct_fmt(total_atingimento)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>OTE Base</td><td></td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{brl(OTE_BASE)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Acelerador</td>"
        f"<td {td3}>{calc_acel}</td>"
        f"<td style='text-align:right;font-weight:700;color:{acel_cor};padding-left:10px;'>{acel_label}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>OTE Ajustado</td>"
        f"<td {td3}>{brl(OTE_BASE)} × {acel_str}</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;padding-left:10px;'>{brl(ote_ajustado)}</td></tr>"
        f"</table></div>"
    )


def _card_eixo(titulo, subtitulo, meta, real, pct, pond):
    cor = "#16a34a" if pct >= 1.0 else "#dc2626" if pct < CLIFF_GERAL else "#374151"
    return (
        f"<div style='background:#f9fafb;border-radius:8px;padding:1rem 1.2rem;"
        f"border:1px solid #e5e7eb;'>"
        f"<div style='font-size:0.78rem;font-weight:700;color:#1a1a1a;"
        f"text-transform:uppercase;letter-spacing:.05em;margin-bottom:.15rem;'>{titulo}</div>"
        f"<div style='font-size:0.72rem;color:#6b7280;margin-bottom:.55rem;'>{subtitulo}</div>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.88rem;'>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Meta</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;'>{brl(meta)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>Realizado</td>"
        f"<td style='text-align:right;font-weight:600;color:#1a1a1a;'>{brl(real)}</td></tr>"
        f"<tr><td style='padding:3px 0;color:#1a1a1a;'>% Atingido</td>"
        f"<td style='text-align:right;font-weight:700;color:{cor};'>{pct_fmt(pct)}</td></tr>"
        f"<tr><td style='padding:3px 0;font-size:.8rem;color:#374151;'>Ponderação</td>"
        f"<td style='text-align:right;font-size:.8rem;color:#374151;'>{pct_fmt(pond)}</td></tr>"
        f"</table></div>"
    )


def _build_pivot(df_eq, df_b2g, meses, mes_lbls):
    cols = ["Equipe"] + mes_lbls + ["Total"]
    rows = []
    for eq in _EQUIPE_ORDER:
        sub = df_eq[df_eq["EQUIPE"] == eq]
        vals = [float(sub.loc[sub["MES"] == m, "VALOR"].sum()) for m in meses]
        rows.append([eq] + [brl(v) for v in vals] + [brl(sum(vals))])
    vals_tot = [float(df_eq.loc[df_eq["MES"] == m, "VALOR"].sum()) for m in meses]
    rows.append(["Total NMRR"] + [brl(v) for v in vals_tot] + [brl(sum(vals_tot))])
    vals_b2g = [float(df_b2g.loc[df_b2g["MES"] == m, "VALOR"].sum()) for m in meses]
    rows.append(["B2G (Booking)"] + [brl(v) for v in vals_b2g] + [brl(sum(vals_b2g))])
    return pd.DataFrame(rows, columns=cols)


def _fmt_dt(dt):
    try:
        if hasattr(dt, "strftime"):
            return dt.strftime("%d/%m")
        s = str(dt)
        return s[8:10] + "/" + s[5:7] if len(s) >= 10 else s
    except Exception:
        return "—"


def montar_pvt(ano: int, trim: str):
    meses = TRIMESTRES[trim]
    mi = _meses_in(trim)
    mes_lbls = [MESES_ABREV[m] for m in meses]

    df_nr = _load_nmrr_real(ano, mi).copy()
    df_or = _load_otr_real(ano, mi).copy()
    df_nm = _load_nmrr_meta(ano, mi).copy()
    df_om = _load_otr_meta(ano, mi).copy()
    df_status = _load_fechamento_status(ano, mi)
    df_ov = _load_overrides(ano, mi)
    df_nr, df_nm, df_or, df_om = _aplicar_overrides(df_nr, df_nm, df_or, df_om, df_ov)

    meta_nmrr = float(df_nm["VALOR"].sum()) if not df_nm.empty else 0.0
    real_nmrr = float(df_nr["VALOR"].sum()) if not df_nr.empty else 0.0
    meta_otr = float(df_om["VALOR"].sum()) if not df_om.empty else 0.0
    real_otr = float(df_or["VALOR"].sum()) if not df_or.empty else 0.0
    pct_nmrr = real_nmrr / meta_nmrr if meta_nmrr > 0 else 0.0
    pct_otr = real_otr / meta_otr if meta_otr > 0 else 0.0
    pct_pond = (pct_nmrr * POND_NMRR) + (pct_otr * POND_OTR)

    if pct_pond < CLIFF_GERAL:
        acelerador, acel_label, acel_cor = 0.0, f"0× (abaixo do cliff de {pct_fmt(CLIFF_GERAL)})", "#dc2626"
    elif pct_pond < MULT_115_CLIFF:
        acelerador, acel_label, acel_cor = 1.00, "1,00×", "#374151"
    elif pct_pond < MULT_125_CLIFF:
        acelerador, acel_label, acel_cor = 1.15, "1,15×", "#059669"
    else:
        acelerador, acel_label, acel_cor = 1.25, "1,25×", "#059669"

    ote_ajustado = OTE_BASE * acelerador
    comissao = ote_ajustado * pct_pond

    b = []
    b.append(
        "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;"
        "align-items:stretch;margin-bottom:1rem;'>"
        + _card_comissao(trim, ano, comissao, ote_ajustado, pct_pond,
                         pct_nmrr, pct_otr, acelerador, acel_label, acel_cor)
        + _card_eixo("NMRR", "Escritórios · Construtoras · Farmer",
                     meta_nmrr, real_nmrr, pct_nmrr, POND_NMRR)
        + _card_eixo("BOOKING", "B2G", meta_otr, real_otr, pct_otr, POND_OTR)
        + "</div>")

    b.append("<div class='titulo-secao'>Metas</div>")
    b.append(html_table_str(_build_pivot(df_nm, df_om, meses, mes_lbls)))
    b.append("<div class='titulo-secao'>Realizado</div>")
    b.append(html_table_str(_build_pivot(df_nr, df_or, meses, mes_lbls)))

    # Status de fechamento
    fechados = {(str(r["EQUIPE"]), int(r["MES"])): r["DATA_FECHAMENTO"]
                for _, r in df_status.iterrows()}
    th_cols = "".join(
        f"<th style='text-align:center;padding:2px 8px;color:#9ca3af;"
        f"font-weight:400;font-size:.7rem;'>{lbl}</th>" for lbl in mes_lbls)

    def _cell(eq, m):
        if (eq, m) in fechados:
            return (f"<td style='text-align:center;padding:2px 8px;font-size:.72rem;'>"
                    f"<span style='color:#059669;'>🔒 {_fmt_dt(fechados[(eq, m)])}</span></td>")
        return ("<td style='text-align:center;padding:2px 8px;font-size:.72rem;'>"
                "<span style='color:#d1d5db;'>·</span></td>")

    tr_nmrr = "".join(
        f"<tr><td style='padding:2px 0;color:#6b7280;font-size:.72rem;padding-right:12px;'>{eq}</td>"
        + "".join(_cell(eq, m) for m in meses) + "</tr>"
        for eq in ["B2B Escritório", "B2B Construtora", "Farmer"])
    b2g_cells = []
    for m in meses:
        bdt = next((fechados.get((eq, m)) for eq in ("Governo", "B2G") if (eq, m) in fechados), None)
        bc = (f"<span style='color:#059669;font-weight:600;'>🔒 {_fmt_dt(bdt)}</span>"
              if bdt is not None else "<span style='color:#9ca3af;'>Aberto</span>")
        b2g_cells.append(f"<td style='text-align:center;padding:4px 8px;font-size:.8rem;"
                         f"border-top:1px solid #f0f0f0;'>{bc}</td>")
    tr_b2g = (f"<tr><td style='padding:2px 0;color:#6b7280;font-size:.72rem;"
              f"padding-right:12px;'>B2G (Booking)</td>" + "".join(b2g_cells) + "</tr>")
    b.append(
        "<div style='margin:.75rem 0;'><table style='border-collapse:collapse;'>"
        f"<tr><th style='text-align:left;padding:2px 12px 2px 0;color:#9ca3af;"
        f"font-weight:400;font-size:.68rem;text-transform:uppercase;'>Fechamento</th>{th_cols}</tr>"
        f"{tr_nmrr}{tr_b2g}</table></div>")
    return b
