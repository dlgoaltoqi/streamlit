import pandas as pd


def _f(val, default=None):
    """Safe float conversion; returns default on None/NaN."""
    if val is None:
        return default
    try:
        v = float(val)
        return default if v != v else v  # v != v catches NaN
    except (TypeError, ValueError):
        return default


def _acel_b2g(pct_bk, cliff_ote_01, cliff_acel_01, mult_acel_01, cliff_acel_02, mult_acel_02):
    """Acelerador B2G baseado em %Booking."""
    if cliff_ote_01 > 0 and pct_bk < cliff_ote_01:
        return 0.0
    if cliff_acel_02 is not None and mult_acel_02 is not None and pct_bk >= cliff_acel_02:
        return mult_acel_02
    if pct_bk >= cliff_acel_01:
        return mult_acel_01
    return 1.0


def calc_acel_form_pag(forma_pagamento, parcelas) -> str:
    if "Recorrente" in str(forma_pagamento):
        return "Recorrente"
    try:
        p = int(parcelas)
    except (TypeError, ValueError):
        return ""
    if p == 1:
        return "À Vista"
    elif p <= 3:
        return "CC 3x"
    elif p <= 12:
        return "CC 12x"
    else:
        return "Recorrente"


# Gestores que gerenciam MULTIPLAS equipes (override do padrao gestor.equipe).
# A agregacao do gestor (realizado mensal e trimestral) soma os consultores
# de todas as equipes listadas. A meta continua sendo a META_MRR do gestor.
GESTOR_EQUIPES_OVERRIDE = {
    "sonia.zielinski@altoqi.com.br": ["FSB", "Farmer", "Ares"],
}

# Composicao do realizado por equipe (colunas de VENDAS somadas). Padrao = ["MRR"].
# Farmer conta New MRR + MRR de expansao (exclui renovacao), alinhado a sua meta
# (que e toda de expansao). Demais equipes usam MRR.
REALIZADO_COLUNAS = {
    "Farmer": ["NMRR", "MRR_EXPANSAO"],
}


def _valor_linha(row, equipe_fixa=None):
    """Valor de realizado de uma linha de VENDAS conforme a regra da equipe.
    equipe_fixa: usa essa equipe; senao usa a coluna _EQ da linha (gestor multi-equipe)."""
    eq = equipe_fixa if equipe_fixa is not None else row.get("_EQ")
    cols = REALIZADO_COLUNAS.get(str(eq), ["MRR"])
    return sum((_f(row.get(c), 0) or 0) for c in cols)


def _valor_sql_fixa(equipe, alias=""):
    """Expressao SQL do realizado para UMA equipe conhecida."""
    p = (alias + ".") if alias else ""
    cols = REALIZADO_COLUNAS.get(equipe, ["MRR"])
    return " + ".join(f"COALESCE({p}{c}, 0)" for c in cols)


def _valor_sql_case(alias="v", key_expr="v.VERTICAL"):
    """Expressao SQL do realizado por linha via CASE na VERTICAL do deal."""
    whens = []
    for eq, cols in REALIZADO_COLUNAS.items():
        eq_safe = eq.replace("'", "''")
        soma = " + ".join(f"COALESCE({alias}.{c}, 0)" for c in cols)
        whens.append(f"WHEN {key_expr} = '{eq_safe}' THEN {soma}")
    if whens:
        return "CASE " + " ".join(whens) + f" ELSE COALESCE({alias}.MRR, 0) END"
    return f"COALESCE({alias}.MRR, 0)"


def _b2g_deals_cte_single(ano: int, mes: int) -> str:
    """CTE block providing deals_ok(ID_NEGOCIO) for a single B2G month.
    Uses COMPOSICAO_FECHADA snapshot when fechamento exists, else live 400k filter."""
    return f"""    fec_b2g AS (
        SELECT FECHAMENTO_ID FROM SUPERSET.COMISSOES.FECHAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND STATUS = 'ATIVO'
          AND EQUIPE IN ('Governo', 'B2G')
        LIMIT 1
    ),
    deals_snap_b2g AS (
        SELECT DISTINCT cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
        FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
        JOIN fec_b2g ON fec_b2g.FECHAMENTO_ID = cf.FECHAMENTO_ID
        WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
    ),
    deals_live_b2g AS (
        SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
        UNION
        SELECT ID_NEGOCIO FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
        WHERE ANO = {ano} AND MES = {mes}
        GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
    ),
    deals_ok AS (
        SELECT ID_NEGOCIO FROM deals_snap_b2g
        WHERE (SELECT COUNT(*) FROM fec_b2g) > 0
        UNION ALL
        SELECT ID_NEGOCIO FROM deals_live_b2g
        WHERE (SELECT COUNT(*) FROM fec_b2g) = 0
    )"""


def _b2g_deals_cte_multi(ano: int, mes_in_str: str) -> str:
    """CTE block providing deals_ok_per_mes(ID_NEGOCIO, MES) for multi-month B2G.
    Uses COMPOSICAO_FECHADA for closed months, live 400k filter for open months.
    Main query must filter with EXISTS (SELECT 1 FROM deals_ok_per_mes d
    WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)."""
    return f"""    fec_b2g AS (
        SELECT MES, FECHAMENTO_ID FROM SUPERSET.COMISSOES.FECHAMENTOS
        WHERE ANO = {ano} AND MES IN ({mes_in_str}) AND STATUS = 'ATIVO'
          AND EQUIPE IN ('Governo', 'B2G')
    ),
    deals_snap_b2g AS (
        SELECT DISTINCT cf.MES, cf.LINHA:NEGOCIO::VARCHAR AS ID_NEGOCIO
        FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA cf
        JOIN fec_b2g ON fec_b2g.FECHAMENTO_ID = cf.FECHAMENTO_ID AND fec_b2g.MES = cf.MES
        WHERE cf.TIPO = 'REALIZADO' AND cf.LINHA:NEGOCIO IS NOT NULL
    ),
    deals_live_b2g AS (
        SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
        UNION
        SELECT ID_NEGOCIO FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
        WHERE ANO = {ano} AND MES IN ({mes_in_str})
        GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
    ),
    deals_ok_per_mes AS (
        SELECT ID_NEGOCIO, MES FROM deals_snap_b2g
        UNION ALL
        SELECT dl.ID_NEGOCIO, v.MES
        FROM deals_live_b2g dl
        JOIN SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
          ON v.ID_NEGOCIO = dl.ID_NEGOCIO AND v.ANO = {ano} AND v.MES IN ({mes_in_str})
        WHERE v.MES NOT IN (SELECT MES FROM fec_b2g)
        GROUP BY dl.ID_NEGOCIO, v.MES
    )"""


def _gestor_team_emails(session, email, ano, mes):
    """Consultores sob o gestor via PERMISSAO_RLS (lower). Retorna None se o gestor
    nao tiver mapeamento no periodo (nesse caso usa-se a equipe inteira)."""
    es = str(email).replace("'", "''")
    df = session.sql(f"""
        SELECT DISTINCT LOWER(CONSULTOREMAIL) AS C
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(USUARIOEMAIL) = '{es}'
          AND CONSULTOREMAIL IS NOT NULL
    """).to_pandas()
    if df.empty:
        return None
    return [str(c) for c in df["C"].tolist() if c]


def composicao_realizado(session, email, ano, mes, equipe, is_gestor, is_gd, is_b2g):
    """Retorna um DataFrame com os negocios/itens que compoem o realizado,
    respeitando o modelo: consultor (por e-mail), gestor (por VERTICAL / RLS),
    GD (Opps) e B2G (deals com filtro 400k)."""
    email   = str(email).strip().lower().replace("'", "''")
    eq_safe = str(equipe).replace("'", "''")

    if is_gd:
        if is_gestor:
            team = _gestor_team_emails(session, email, ano, mes)
            if team:
                tin = ", ".join("'" + t.replace("'", "''") + "'" for t in team)
                cond = f"LOWER(PROPRIETARIO) IN ({tin})"
            else:
                cond = (f"LOWER(PROPRIETARIO) IN (SELECT LOWER(m.CONSULTOR) "
                        f"FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m "
                        f"JOIN SUPERSET.COMISSOES.PARAMETROS p ON p.ANO=m.ANO AND p.MES=m.MES "
                        f"AND LOWER(p.EMAIL)=LOWER(m.CONSULTOR) "
                        f"WHERE m.ANO={ano} AND m.MES={mes} AND m.EQUIPE='{eq_safe}' AND p.IS_GESTOR=FALSE)")
        else:
            cond = f"LOWER(PROPRIETARIO) = '{email}'"
        return session.sql(f"""
            SELECT LOWER(PROPRIETARIO) AS CONSULTOR, ID_CONTATO AS CONTATO,
                   TO_VARCHAR(DATA_QUALIFICACAO, 'DD/MM/YYYY') AS DATA_FMT
            FROM SUPERSET.COMISSOES.REALIZADO_GD
            WHERE YEAR(DATA_QUALIFICACAO)={ano} AND MONTH(DATA_QUALIFICACAO)={mes} AND {cond}
            ORDER BY CONSULTOR, DATA_QUALIFICACAO
        """).to_pandas()

    cons_col = "LOWER(v.CONSULTOR) AS CONSULTOR, " if is_gestor else ""

    if is_b2g:
        if is_gestor:
            cond = (f"v.CONSULTOR IN (SELECT m.CONSULTOR "
                    f"FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m "
                    f"JOIN SUPERSET.COMISSOES.PARAMETROS p ON p.ANO=m.ANO AND p.MES=m.MES AND p.EMAIL=m.CONSULTOR "
                    f"WHERE m.ANO={ano} AND m.MES={mes} AND m.EQUIPE='{eq_safe}' AND p.IS_GESTOR=FALSE)")
            b2g_group = "LOWER(v.CONSULTOR), v.ID_NEGOCIO"
        else:
            cond = f"LOWER(v.CONSULTOR) = '{email}'"
            b2g_group = "v.ID_NEGOCIO"
        return session.sql(f"""
            WITH {_b2g_deals_cte_single(ano, mes)}
            SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, MAX(v.CLIENTE) AS CLIENTE, MAX(v.PIPELINE) AS PIPELINE,
                   MAX(v.FORMA_DE_PAGAMENTO) AS FORMA_PAG,
                   ROUND(SUM(v.BOOKING),2) AS BOOKING, ROUND(SUM(v.ARR),2) AS ARR
            FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
            WHERE v.ANO={ano} AND v.MES={mes} AND {cond}
              AND v.ID_NEGOCIO IN (SELECT ID_NEGOCIO FROM deals_ok)
            GROUP BY {b2g_group}
            ORDER BY NEGOCIO
        """).to_pandas()

    # MRR / Saving
    if is_gestor:
        eqs = GESTOR_EQUIPES_OVERRIDE.get(email, [equipe])
        ein = ", ".join("'" + str(e).replace("'", "''") + "'" for e in eqs)
        valor_expr   = _valor_sql_case('v', 'v.VERTICAL')
        where_clause = f"v.VERTICAL IN ({ein})"
        mrr_group    = "LOWER(v.CONSULTOR), v.ID_NEGOCIO"
    else:
        valor_expr   = _valor_sql_fixa(equipe, 'v')
        where_clause = f"LOWER(v.CONSULTOR) = '{email}'"
        mrr_group    = "v.ID_NEGOCIO"
    return session.sql(f"""
        SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, MAX(v.CLIENTE) AS CLIENTE, MAX(v.PIPELINE) AS PIPELINE,
               MAX(v.FORMA_DE_PAGAMENTO) AS FORMA_PAG, ROUND(SUM({valor_expr}), 2) AS VALOR
        FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
        WHERE v.ANO={ano} AND v.MES={mes} AND {where_clause}
        GROUP BY {mrr_group}
        ORDER BY NEGOCIO
    """).to_pandas()


def composicao_booking_extra(session, email, ano, mes, equipe, is_gestor):
    """Retorna itens individuais (nível de produto) de Implantação/Serviço/Curso com MRR=0."""
    email = str(email).strip().lower().replace("'", "''")

    if is_gestor:
        eqs = GESTOR_EQUIPES_OVERRIDE.get(email, [equipe])
        ein = ", ".join("'" + str(e).replace("'", "''") + "'" for e in eqs)
        where_clause = f"v.VERTICAL IN ({ein})"
        cons_col = "LOWER(v.CONSULTOR) AS CONSULTOR, "
    else:
        where_clause = f"LOWER(v.CONSULTOR) = '{email}'"
        cons_col = ""

    return session.sql(f"""
        WITH deals_ok AS (
            SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
            UNION
            SELECT ID_NEGOCIO FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO={ano} AND MES={mes} GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
        )
        SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, v.CLIENTE AS CLIENTE,
               v.ITEM_DE_LINHA AS PRODUTO, v.PIPELINE AS PIPELINE,
               v.FORMA_DE_PAGAMENTO AS FORMA_PAG, ROUND(v.BOOKING, 2) AS BOOKING
        FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
        JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
        WHERE v.ANO={ano} AND v.MES={mes} AND {where_clause}
          AND v.CATEGORIA_DO_ITEM IN ('Implantação', 'Serviço', 'Curso')
          AND COALESCE(v.MRR, 0) = 0
        ORDER BY NEGOCIO, PRODUTO
    """).to_pandas()


def _calcular_comissao_canc_recovery(session, email, ano, mes, pr) -> dict:
    """Cálculo simplificado para consultoras de recuperação de cancelamento (sem OTE)."""
    cargo     = str(pr.get("CARGO") or "")
    is_gestor = bool(pr.get("IS_GESTOR") or False)
    pct_canc  = _f(pr.get("PERCENTUAL_CANC_RECOVERY"), 0.02)

    canc_df = session.sql(f"""
        SELECT
            COALESCE(SUM(VALOR_AJUSTADO), 0) AS TOTAL_VALOR,
            COALESCE(SUM(VALOR_ORIGINAL / NULLIF(DATEDIFF('month', DATA_INICIO, DATA_RENOVACAO), 0)), 0) AS TOTAL_MRR
        FROM SUPERSET.COMISSOES.CONSULTA_CANCELAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
    """).to_pandas()
    valor_recuperado    = _f(canc_df.iloc[0]["TOTAL_VALOR"], 0) if not canc_df.empty else 0.0
    mrr_recuperado      = _f(canc_df.iloc[0]["TOTAL_MRR"],   0) if not canc_df.empty else 0.0
    comissao_canc       = round(valor_recuperado * pct_canc, 2)

    return {
        "is_canc_recovery":       True,
        "equipe":                 "Cancelamento",
        "cargo":                  cargo,
        "meta_mrr":               0.0,
        "desconto":               0.0,
        "realizado":              0.0,
        "pct_atingido":           0.0,
        "ote_cheio":              None,
        "ote_02_cheio":           None,
        "ote_prop":               None,
        "ote_02_prop":            None,
        "ote_base":               None,
        "ote_tier":               1,
        "cliff_ote_01":           0,
        "cliff_ote_02":           None,
        "cliff_acel_01":          0,
        "mult_acel_01":           1.0,
        "cliff_acel_02":          None,
        "mult_acel_02":           None,
        "acelerador":             0.0,
        "acel_desc":              "",
        "ote_ajustado":           None,
        "mrr_avista":             0.0,
        "mrr_cc3x":               0.0,
        "mrr_cc12x":              0.0,
        "mrr_recorrente":         0.0,
        "mult_avista":            1.0,
        "mult_cc3x":              1.0,
        "mult_cc12x":             1.0,
        "mult_recorrente":        1.0,
        "ote_variavel":           0.0,
        "booking_extras":         0.0,
        "pct_bk_extra":           0.0,
        "comissao_bk_extra":      0.0,
        "is_saving":              False,
        "is_gd":                  False,
        "is_b2g":                 False,
        "faixa_atingida":         None,
        "proxima_faixa":          None,
        "dividas_pagas":          0.0,
        "comissao_dividas":       0.0,
        "pct_protecao":           0.0,
        "bonificacao_protecao":   0.0,
        "ajuste_total":           0.0,
        "ajuste_n":               0,
        "total":                  comissao_canc,
        "is_gestor":              is_gestor,
        "ote_indisponivel":       False,
        "trim":                   None,
        "valor_recuperado":       valor_recuperado,
        "mrr_recuperado":         mrr_recuperado,
        "comissao_canc_recovery": comissao_canc,
        "pct_canc_recovery":      pct_canc,
        # B2G-specific (unused)
        "arr_real":               0.0,
        "bk_real":                0.0,
        "meta_arr":               0.0,
        "pct_arr_b2g":            0.0,
        "pct_bk_b2g":             0.0,
        "pct_ponderado":          0.0,
        "pond_arr_b2g":           0.0,
        "pond_bk_b2g":            0.0,
        "meta_atingida_real":     0.0,
        "meta_atingida_meta":     0.8,
        "pct_meta_atingida":      0.0,
        "pond_ma":                0.0,
        "b2g_ajuste":             None,
    }


def composicao_cancelamentos(session, email, ano, mes):
    """Retorna os negócios de recuperação de cancelamento para o período (nível de deal)."""
    email = str(email).strip().lower().replace("'", "''")
    return session.sql(f"""
        SELECT
            ANO, MES,
            EMAIL               AS CONSULTORA,
            ID_NEGOCIO          AS NEGOCIO,
            NUMERO_CONTRATO     AS CONTRATO,
            TO_VARCHAR(DATA_FECHAMENTO, 'DD/MM/YYYY') AS DATA_FECHAMENTO,
            TO_VARCHAR(DATA_INICIO,    'DD/MM/YYYY') AS DATA_INICIO,
            TO_VARCHAR(DATA_RENOVACAO, 'DD/MM/YYYY') AS DATA_RENOVACAO,
            VALOR_ORIGINAL,
            VALOR_AJUSTADO
        FROM SUPERSET.COMISSOES.CONSULTA_CANCELAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
        ORDER BY NEGOCIO
    """).to_pandas()


def _pago_mensal_trimestre(email, ano, mes, ote_variavel_atual, ote_base_atual):
    """Soma o OTE Variável e o OTE Base reais dos 3 meses do trimestre B2G
    (colunas AP e AL da planilha).

    Meses anteriores vêm de get_comissao — lê o snapshot congelado quando o
    mês está fechado. O mês corrente usa os valores do cálculo em andamento:
    buscá-lo via get_comissao aqui causaria recursão infinita.
    Retorna (pago_mensal, ote_base_q)."""
    from utils.connection import get_comissao  # import tardio: evita ciclo
    pago = float(ote_variavel_atual or 0)
    base = float(ote_base_atual or 0)
    for m_ant in (mes - 2, mes - 1):
        d_m = get_comissao(email, ano, m_ant)
        if isinstance(d_m, dict) and "erro" not in d_m:
            pago += float(d_m.get("ote_variavel") or 0)
            base += float(d_m.get("ote_base") or 0)
    return pago, base


def calcular_comissao(session, email: str, ano: int, mes: int) -> dict:
    """
    Calculates the principal commission for a given user and period.
    Supports models: MRR (Ares/B2B/Farmer/FSB/Sonia), Saving, GD, B2G, CancRecovery.
    Returns a dict with all components, or {'erro': str} when data is missing.
    """
    # Normalização: e-mail sempre lowercase (todas as comparações usam LOWER(coluna))
    # e com aspas escapadas para uso seguro nos literais SQL.
    email = str(email).strip().lower().replace("'", "''")

    # ── 0. Saída antecipada para recuperação de cancelamento ──────────────────
    cr_df = session.sql(f"""
        SELECT IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY, CARGO, IS_GESTOR
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
    """).to_pandas()
    if not cr_df.empty and bool(cr_df.iloc[0].get("IS_CANC_RECOVERY") or False):
        return _calcular_comissao_canc_recovery(session, email, ano, mes, cr_df.iloc[0])

    # ── 1. Meta ──────────────────────────────────────────────────────────────
    meta_df = session.sql(f"""
        SELECT META_MRR, META_OTR, PERCENTUAL_DESCONTO_METAS, EQUIPE
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(CONSULTOR) = '{email}'
    """).to_pandas()

    if meta_df.empty:
        return {"erro": f"Sem dados de meta para este período."}

    meta_row = meta_df.iloc[0]
    equipe   = str(meta_row["EQUIPE"] or "")
    is_gd    = equipe.lower() == "gd"
    is_b2g   = equipe.lower() in ('b2g', 'governo')
    # GD usa Opps (META_OTR); Governo (B2G) usa Booking = OTR (META_OTR); demais usam META_MRR.
    meta_mrr = _f(meta_row["META_OTR"] if (is_gd or is_b2g) else meta_row["META_MRR"], 0)
    # B2G gestor: alvo de % da equipe atingindo quota (padrão = 80%)
    meta_atingida_meta = 0.8
    desconto = _f(meta_row["PERCENTUAL_DESCONTO_METAS"], 0)
    if desconto > 1:  # campo armazenado em pontos percentuais (ex: 25 = 25%), normaliza para decimal
        desconto /= 100

    # ── 2. Parâmetros ─────────────────────────────────────────────────────────
    param_df = session.sql(f"""
        SELECT CARGO, IS_GESTOR,
               CLIFF_OTE_01, CLIFF_OTE_02,
               CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
               CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
               PERCENTUAL_BOOKING_EXTRA,
               OTE_01_CHEIO, OTE_02_CHEIO,
               IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY,
               PERCENTUAL_PROTECAO,
               COALESCE(IS_TRIM_HABILITADO, TRUE) AS IS_TRIM_HABILITADO
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
    """).to_pandas()

    if param_df.empty:
        return {"erro": "Parâmetros não configurados para este período."}

    pr = param_df.iloc[0]
    cargo     = str(pr["CARGO"] or "")
    is_gestor = bool(pr["IS_GESTOR"])
    is_trim_habilitado = bool(pr.get("IS_TRIM_HABILITADO", True))

    # SDR fora do time GD (ex: B2B Escritório) segue estrutura GD: Opps / REALIZADO_GD
    is_sdr = "sales development" in cargo.lower()
    if is_sdr and not is_gd:
        is_gd    = True
        meta_mrr = _f(meta_row["META_OTR"], 0)

    # GD/SDR consultor: meta vem do Revenue Intelligence (gestores mantêm META_OTR do METAS)
    if is_gd and not is_gestor:
        _ri_meta_df = session.sql(f"""
            SELECT COALESCE(rigot.TARGET_QUALIFIED, 0) AS META
            FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = rigot.OWNER_ID
            WHERE rigot.YEAR = {ano} AND rigot.MONTH = {mes}
              AND LOWER(rio.EMAIL) = '{email}'
        """).to_pandas()
        meta_mrr = _f(_ri_meta_df.iloc[0]["META"], 0) if not _ri_meta_df.empty else 0.0

    # Equipes que o gestor agrega (padrao = sua propria equipe; override p/ multi-equipe)
    gestor_equipes = GESTOR_EQUIPES_OVERRIDE.get(email.lower(), [equipe])
    equipes_in = ", ".join("'" + str(e).replace("'", "''") + "'" for e in gestor_equipes)
    equipe_safe = equipe.replace("'", "''")
    cliff_ote_01   = _f(pr["CLIFF_OTE_01"], 0)
    cliff_ote_02   = _f(pr["CLIFF_OTE_02"])
    cliff_acel_01  = _f(pr["CLIFF_ACELERADOR_01"], 0)
    mult_acel_01   = _f(pr["MULT_ACELERADOR_01"], 1.0)
    cliff_acel_02  = _f(pr["CLIFF_ACELERADOR_02"])
    mult_acel_02   = _f(pr["MULT_ACELERADOR_02"])
    pct_bk_extra   = _f(pr["PERCENTUAL_BOOKING_EXTRA"], 0)
    pct_protecao   = _f(pr.get("PERCENTUAL_PROTECAO"), 0)
    ote_01_override = _f(pr["OTE_01_CHEIO"])
    ote_02_override = _f(pr["OTE_02_CHEIO"])

    # ── 3. OTE: override em PARAMETROS tem prioridade; fallback em CARGOS_OTES ─
    if ote_01_override is not None:
        ote_cheio    = ote_01_override
        ote_02_cheio = ote_02_override
    else:
        ote_df = session.sql(f"""
            SELECT OTE
            FROM SUPERSET.COMISSOES.CARGOS_OTES
            WHERE ANO = {ano} AND MES = {mes}
              AND UPPER(CARGO) = UPPER('{cargo}')
        """).to_pandas()
        ote_cheio    = _f(ote_df.iloc[0]["OTE"]) if not ote_df.empty else None
        ote_02_cheio = None  # tier 2 only via override

    ote_prop    = (ote_cheio    * (1 - desconto)) if ote_cheio    is not None else None
    ote_02_prop = (ote_02_cheio * (1 - desconto)) if ote_02_cheio is not None else None

    # ── 4. Realizado ──────────────────────────────────────────────────────────
    # Initialize B2G-specific variables (overwritten in B2G branch)
    arr_real = bk_real = meta_atingida_real = 0.0
    opps_override = None  # Opps adicionadas por override (GD consultor)
    meta_arr = pct_arr_b2g = pct_bk_b2g = 0.0
    pct_ponderado = pct_meta_atingida = 0.0
    pond_arr_b2g = pond_bk_b2g = pond_ma = 0.0

    if is_gd:
        # GD: realizado em Opps (REALIZADO_GD), com override manual por pessoa/mês
        if is_gestor:
            # Time do gestor: PERMISSAO_RLS se houver; senao toda a equipe GD.
            team = _gestor_team_emails(session, email, ano, mes)
            if team:
                team_in = ", ".join("'" + t.replace("'", "''") + "'" for t in team)
                gd_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS OPPS
                    FROM (
                        SELECT LOWER(PROPRIETARIO) AS EMAIL_LOWER,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) = {mes}
                        GROUP BY LOWER(PROPRIETARIO)
                    ) cnt
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = {mes}
                        AND LOWER(o.EMAIL) = cnt.EMAIL_LOWER
                    WHERE cnt.EMAIL_LOWER IN ({team_in})
                """).to_pandas()
            else:
                gd_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS OPPS
                    FROM (
                        SELECT LOWER(PROPRIETARIO) AS EMAIL_LOWER,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) = {mes}
                        GROUP BY LOWER(PROPRIETARIO)
                    ) cnt
                    INNER JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
                        ON rigot.YEAR = {ano} AND rigot.MONTH = {mes}
                    INNER JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
                        ON rio.ID = rigot.OWNER_ID
                        AND LOWER(rio.EMAIL) = cnt.EMAIL_LOWER
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                        ON p.ANO = {ano} AND p.MES = {mes}
                        AND LOWER(p.EMAIL) = cnt.EMAIL_LOWER
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = {mes}
                        AND LOWER(o.EMAIL) = cnt.EMAIL_LOWER
                    WHERE p.IS_GESTOR = FALSE
                """).to_pandas()
        else:
            gd_df = session.sql(f"""
                SELECT
                    COALESCE(
                        (SELECT REALIZADO_MANUAL FROM SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE
                         WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'),
                        (SELECT COUNT(DISTINCT ID_CONTATO)
                         FROM SUPERSET.COMISSOES.REALIZADO_GD
                         WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                           AND MONTH(DATA_QUALIFICACAO) = {mes}
                           AND LOWER(PROPRIETARIO) = '{email}'),
                        0
                    ) AS OPPS,
                    (SELECT REALIZADO_MANUAL FROM SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE
                     WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
                    ) AS OPPS_OVERRIDE,
                    (SELECT COUNT(DISTINCT ID_CONTATO)
                     FROM SUPERSET.COMISSOES.REALIZADO_GD
                     WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                       AND MONTH(DATA_QUALIFICACAO) = {mes}
                       AND LOWER(PROPRIETARIO) = '{email}'
                    ) AS OPPS_RAW
            """).to_pandas()
            _ov_val  = gd_df.iloc[0]["OPPS_OVERRIDE"] if not gd_df.empty else None
            _raw_val = gd_df.iloc[0]["OPPS_RAW"]      if not gd_df.empty else 0
            if _ov_val is not None and pd.notna(_ov_val):
                _delta = int(float(_ov_val)) - int(float(_raw_val) if _raw_val is not None and pd.notna(_raw_val) else 0)
                if _delta != 0:
                    opps_override = _delta
        realizado = float(gd_df.iloc[0]["OPPS"]) if not gd_df.empty else 0.0
        mrr_avista = mrr_cc3x = mrr_cc12x = mrr_recorrente = 0.0
        booking_extras = 0.0

    elif is_b2g:
        # B2G: realizado em ARR e Booking (VENDAS_REALIZADAS_POR_ITEM)
        # Nota: deals ≥ R$400k são excluídos por padrão (futura melhoria: DEALS_PAGOS_400K)
        if is_gestor:
            b2g_df = session.sql(f"""
                WITH {_b2g_deals_cte_single(ano, mes)}
                SELECT COALESCE(SUM(v.BOOKING), 0) AS BK_REAL
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                  ON m.ANO = v.ANO AND m.MES = v.MES AND m.CONSULTOR = v.CONSULTOR
                INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                  ON p.ANO = v.ANO AND p.MES = v.MES AND p.EMAIL = v.CONSULTOR
                WHERE v.ANO = {ano} AND v.MES = {mes}
                  AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                  AND v.ID_NEGOCIO IN (SELECT ID_NEGOCIO FROM deals_ok)
            """).to_pandas()
            bk_real = float(b2g_df.iloc[0]["BK_REAL"]) if not b2g_df.empty else 0.0

            # Meta Atingida: proporção de consultores com %Booking >= 100%
            ma_df = session.sql(f"""
                WITH {_b2g_deals_cte_single(ano, mes)},
                consultor_bk AS (
                    SELECT
                        m.CONSULTOR,
                        COALESCE(SUM(v.BOOKING), 0) / NULLIF(m.META_OTR, 0) AS pct_bk_c
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                    LEFT JOIN SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                        ON v.ANO = m.ANO AND v.MES = m.MES AND v.CONSULTOR = m.CONSULTOR
                        AND v.ID_NEGOCIO IN (SELECT ID_NEGOCIO FROM deals_ok)
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                        ON p.ANO = m.ANO AND p.MES = m.MES AND p.EMAIL = m.CONSULTOR
                    WHERE m.ANO = {ano} AND m.MES = {mes}
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                    GROUP BY m.CONSULTOR, m.META_OTR
                )
                SELECT
                    COUNT_IF(pct_bk_c >= 1.0) AS N_HIT,
                    COUNT(*)                  AS N_TOTAL
                FROM consultor_bk
            """).to_pandas()
            if not ma_df.empty and _f(ma_df.iloc[0]["N_TOTAL"], 0) > 0:
                meta_atingida_real = float(ma_df.iloc[0]["N_HIT"]) / float(ma_df.iloc[0]["N_TOTAL"])

        else:
            b2g_df = session.sql(f"""
                WITH {_b2g_deals_cte_single(ano, mes)}
                SELECT COALESCE(SUM(ARR), 0)     AS ARR_REAL,
                       COALESCE(SUM(BOOKING), 0) AS BK_REAL
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
                WHERE ANO = {ano} AND MES = {mes} AND LOWER(CONSULTOR) = '{email}'
                  AND ID_NEGOCIO IN (SELECT ID_NEGOCIO FROM deals_ok)
            """).to_pandas()
            if not b2g_df.empty:
                arr_real = float(b2g_df.iloc[0]["ARR_REAL"])
                bk_real  = float(b2g_df.iloc[0]["BK_REAL"])

        realizado      = bk_real
        mrr_avista     = mrr_cc3x = mrr_cc12x = mrr_recorrente = 0.0
        booking_extras = 0.0

    else:
        # Demais equipes (MRR/Saving): realizado pela VERTICAL do deal (book do negocio).
        # Membership pela coluna VERTICAL da VENDAS, nao pelo join com METAS — assim
        # deals em outra vertical nao contam, e quem nao tem META no mes nao some.
        if is_gestor:
            neg_df = session.sql(f"""
                WITH deals_ok AS (
                    SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
                    UNION
                    SELECT ID_NEGOCIO FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
                    WHERE ANO = {ano} AND MES = {mes}
                    GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
                )
                SELECT v.MRR, v.NMRR, v.MRR_EXPANSAO, v.BOOKING,
                       v.FORMA_DE_PAGAMENTO, v.PARCELAS, v.CATEGORIA_DO_ITEM,
                       v.VERTICAL AS _EQ
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                WHERE v.ANO = {ano} AND v.MES = {mes}
                  AND v.VERTICAL IN ({equipes_in})
            """).to_pandas()
        else:
            # Consultor individual: SEM validacao de vertical — conta todos os deals
            # do e-mail dele. A composicao segue a equipe do consultor.
            neg_df = session.sql(f"""
                WITH deals_ok AS (
                    SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K
                    UNION
                    SELECT ID_NEGOCIO FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
                    WHERE ANO = {ano} AND MES = {mes}
                    GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < 400000
                )
                SELECT v.MRR, v.NMRR, v.MRR_EXPANSAO, v.BOOKING,
                       v.FORMA_DE_PAGAMENTO, v.PARCELAS, v.CATEGORIA_DO_ITEM
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
                WHERE v.ANO = {ano} AND v.MES = {mes} AND LOWER(v.CONSULTOR) = '{email}'
            """).to_pandas()

        if not neg_df.empty:
            neg_df["ACEL_FORM_PAG"] = neg_df.apply(
                lambda r: calc_acel_form_pag(r["FORMA_DE_PAGAMENTO"], r["PARCELAS"]), axis=1
            )
            # Gestor: composicao pela VERTICAL do deal (_EQ). Consultor: pela sua equipe.
            neg_df["VALOR"] = neg_df.apply(lambda r: _valor_linha(r, None if is_gestor else equipe), axis=1)
            realizado      = float(neg_df["VALOR"].sum())
            mrr_avista     = float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "À Vista",    "VALOR"].sum())
            mrr_cc3x       = float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "CC 3x",      "VALOR"].sum())
            mrr_cc12x      = float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "CC 12x",     "VALOR"].sum())
            mrr_recorrente = float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "Recorrente", "VALOR"].sum())
            cats_bk = ["Implantação", "Serviço", "Curso"]
            mask_bk = neg_df["CATEGORIA_DO_ITEM"].isin(cats_bk) & (neg_df["MRR"].fillna(0) == 0)
            booking_extras = float(neg_df.loc[mask_bk, "BOOKING"].sum())
        else:
            realizado = mrr_avista = mrr_cc3x = mrr_cc12x = mrr_recorrente = 0.0
            booking_extras = 0.0

    # ── % Atingido ────────────────────────────────────────────────────────────
    # B2G: pct_atingido provisório baseado no eixo principal (sobrescrito na seção 6)
    if is_b2g:
        meta_arr    = (meta_mrr * 0.5) if meta_mrr > 0 else 0.0
        pct_arr_b2g = arr_real / meta_arr if meta_arr > 0 else 0.0
        pct_bk_b2g  = bk_real  / meta_mrr if meta_mrr > 0 else 0.0
        # OTE tier selection: consultores usam %ARR; gestor usa %Booking
        pct_atingido = pct_arr_b2g if not is_gestor else pct_bk_b2g
    else:
        pct_atingido = realizado / meta_mrr if meta_mrr > 0 else 0.0

    # Saving model: equipe Saving a partir de abr/2026 usa patamares escalonados
    is_saving = equipe.lower() == "saving" and (int(ano), int(mes)) >= (2026, 4)

    # ── 5. Aceleradores / Patamares / Ponderações ─────────────────────────────
    faixa_atingida = None  # Saving only
    proxima_faixa  = None  # Saving only: (patamar, percentual) da proxima faixa
    if is_saving:
        pat_df = session.sql(f"""
            SELECT PERCENTUAL
            FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
            WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{equipe}'
              AND PATAMAR <= {pct_atingido}
            ORDER BY PATAMAR DESC
            LIMIT 1
        """).to_pandas()
        faixa_atingida = _f(pat_df.iloc[0]["PERCENTUAL"]) if not pat_df.empty else None
        prox_df = session.sql(f"""
            SELECT PATAMAR, PERCENTUAL
            FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
            WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{equipe}'
              AND PATAMAR > {pct_atingido}
            ORDER BY PATAMAR ASC
            LIMIT 1
        """).to_pandas()
        if not prox_df.empty:
            proxima_faixa = (_f(prox_df.iloc[0]["PATAMAR"]), _f(prox_df.iloc[0]["PERCENTUAL"]))
        mult_avista = mult_cc3x = mult_cc12x = mult_recorrente = 1.0
    elif is_gd:
        # GD usa aceleradores de PARAMETROS, mas sem Acel Form Pag
        mult_avista = mult_cc3x = mult_cc12x = mult_recorrente = 1.0
    elif is_b2g:
        # B2G: lê ponderações por tipo de meta; sem Acel Form Pag
        pond_df = session.sql(f"""
            SELECT TIPO_META, PONDERACAO
            FROM SUPERSET.COMISSOES.PONDERACOES_META
            WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
        """).to_pandas()
        pond_map = {r["TIPO_META"]: _f(r["PONDERACAO"], 0) for _, r in pond_df.iterrows()}
        if is_gestor:
            pond_arr_b2g = 0.0
            pond_bk_b2g  = pond_map.get("Booking", 0.8)
            pond_ma      = pond_map.get("MetaAtingida", 0.2)
        else:
            pond_arr_b2g = pond_map.get("ARR", 0.4)
            pond_bk_b2g  = pond_map.get("Booking", 0.6)
            pond_ma      = 0.0
        mult_avista = mult_cc3x = mult_cc12x = mult_recorrente = 1.0
    else:
        acel_df = session.sql(f"""
            SELECT A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE
            FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
            WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{equipe}'
        """).to_pandas()
        if not acel_df.empty:
            ar = acel_df.iloc[0]
            mult_avista     = _f(ar["A_VISTA"],    1.0)
            mult_cc3x       = _f(ar["CC_ATE_3X"],  1.0)
            mult_cc12x      = _f(ar["CC_ATE_12X"], 1.0)
            mult_recorrente = _f(ar["RECORRENTE"], 1.0)
        else:
            mult_avista = mult_cc3x = mult_cc12x = mult_recorrente = 1.0

    # ── 6. Cálculo principal ──────────────────────────────────────────────────
    # OTE Base: tier 2 if cliff reached and OTE_02 is configured; otherwise tier 1
    ote_tier = 1
    ote_base = ote_prop
    if cliff_ote_02 is not None and pct_atingido >= cliff_ote_02 and ote_02_prop is not None:
        ote_base = ote_02_prop
        ote_tier = 2

    if is_saving:
        # Saving: OTE × % Atingido × Faixa Atingida (sem Acel Form Pag)
        if faixa_atingida is None:
            acelerador   = 0.0
            acel_desc    = "Abaixo do patamar mínimo (60%)"
            ote_ajustado = None
            ote_variavel = 0.0
        else:
            acelerador   = faixa_atingida
            acel_desc    = f"Patamar atingido ({faixa_atingida:.0%})"
            ote_ajustado = None  # não se aplica ao modelo Saving
            ote_variavel = (ote_base * pct_atingido * faixa_atingida) if ote_base is not None else None

    elif is_b2g:
        # B2G: OTE_base × Acelerador(%BK) × Atingimento_Ponderado
        # Tier OTE: consultores → %ARR; gestor → %Booking (já em pct_atingido)
        if is_gestor:
            pct_meta_atingida = meta_atingida_real / meta_atingida_meta if meta_atingida_meta > 0 else 0.0
            pct_ponderado = pct_bk_b2g * pond_bk_b2g + pct_meta_atingida * pond_ma
            axis_for_acel = pct_bk_b2g  # gestor: acel on %Booking
        else:
            pct_meta_atingida = 0.0
            pct_ponderado = pct_arr_b2g * pond_arr_b2g + pct_bk_b2g * pond_bk_b2g
            axis_for_acel = pct_bk_b2g  # consultores: acel on %Booking

        # Sobrescreve pct_atingido com ponderado para display
        pct_atingido  = pct_ponderado

        # Acelerador disparado por %Booking (cliff também em %Booking)
        if cliff_ote_01 > 0 and axis_for_acel < cliff_ote_01:
            acelerador = 0.0
            acel_desc  = f"Abaixo do cliff Booking ({cliff_ote_01:.0%})"
        elif cliff_acel_02 is not None and mult_acel_02 is not None and axis_for_acel >= cliff_acel_02:
            acelerador = mult_acel_02
            acel_desc  = f"Acelerador 2 (≥{cliff_acel_02:.0%})"
        elif axis_for_acel >= cliff_acel_01:
            acelerador = mult_acel_01
            acel_desc  = f"Acelerador 1 (≥{cliff_acel_01:.0%})"
        else:
            acelerador = 1.0
            acel_desc  = "Base (sem acelerador)"

        ote_ajustado = (ote_base * acelerador) if ote_base is not None else None
        ote_variavel = (ote_ajustado * pct_ponderado) if ote_ajustado is not None else None

    else:
        # Modelo principal MRR: OTE × Acelerador × % Atingido, distribuído por forma de pagamento
        if cliff_ote_01 > 0 and pct_atingido < cliff_ote_01:
            acelerador = 0.0
            acel_desc  = f"Abaixo do cliff mínimo ({cliff_ote_01:.0%})"
        elif cliff_acel_02 is not None and mult_acel_02 is not None and pct_atingido >= cliff_acel_02:
            acelerador = mult_acel_02
            acel_desc  = f"Acelerador 2 (≥{cliff_acel_02:.0%})"
        elif pct_atingido >= cliff_acel_01:
            acelerador = mult_acel_01
            acel_desc  = f"Acelerador 1 (≥{cliff_acel_01:.0%})"
        else:
            acelerador = 1.0
            acel_desc  = "Base (sem acelerador)"

        ote_ajustado = (ote_base * acelerador * pct_atingido) if ote_base is not None else None

        if is_gd:
            # GD não tem forma de pagamento — comissão direta sem distribuição
            ote_variavel = ote_ajustado
        elif ote_ajustado is not None and realizado > 0:
            pct_av   = mrr_avista     / realizado
            pct_cc3  = mrr_cc3x       / realizado
            pct_cc12 = mrr_cc12x      / realizado
            pct_rec  = mrr_recorrente / realizado
            ote_variavel = (
                  ote_ajustado * pct_av   * mult_avista
                + ote_ajustado * pct_cc3  * mult_cc3x
                + ote_ajustado * pct_cc12 * mult_cc12x
                + ote_ajustado * pct_rec  * mult_recorrente
            )
        elif ote_ajustado is not None:
            ote_variavel = ote_ajustado
        else:
            ote_variavel = None

    # Booking Extra (não se aplica ao GD nem ao B2G)
    if not is_gd and not is_b2g:
        cliff_bk_extra = cliff_ote_01
        comissao_bk_extra = (
            pct_bk_extra * booking_extras
            if (cliff_bk_extra == 0 or pct_atingido >= cliff_bk_extra) else 0.0
        )
    else:
        comissao_bk_extra = 0.0

    # ── 6b. Dívidas Pagas (apenas Saving) ────────────────────────────────────
    dividas_pagas    = 0.0
    comissao_dividas = 0.0
    if is_saving:
        div_df = session.sql(f"""
            SELECT COALESCE(VALOR, 0) AS VALOR, PERCENTUAL_COMISSAO
            FROM SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS
            WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
        """).to_pandas()
        if not div_df.empty:
            dividas_pagas = _f(div_df.iloc[0]["VALOR"], 0)
            pct_div = _f(div_df.iloc[0]["PERCENTUAL_COMISSAO"], 0.025)
            if cliff_ote_01 == 0 or pct_atingido >= cliff_ote_01:
                comissao_dividas = dividas_pagas * pct_div

    bonificacao_protecao = pct_protecao * (ote_cheio or 0) if pct_protecao > 0 else 0.0

    # ── 6c. Ajustes Pontuais ─────────────────────────────────────────────────
    aj_df = session.sql(f"""
        SELECT COALESCE(SUM(VALOR), 0) AS TOTAL, COUNT(*) AS N
        FROM SUPERSET.COMISSOES.AJUSTES_PONTUAIS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
    """).to_pandas()
    ajuste_total = _f(aj_df.iloc[0]["TOTAL"], 0) if not aj_df.empty else 0.0
    ajuste_n     = int(aj_df.iloc[0]["N"])        if not aj_df.empty else 0

    total = (ote_variavel or 0) + comissao_bk_extra + comissao_dividas + bonificacao_protecao + ajuste_total

    # ── 7. Bônus Trimestral (apenas meses 3/6/9/12) ──────────────────────────
    trim = None
    trim_bloqueado = False
    if mes in (3, 6, 9, 12) and not is_trim_habilitado:
        trim_bloqueado = True
    elif mes in (3, 6, 9, 12):
        q_str = f"{mes - 2},{mes - 1},{mes}"

        if is_gd:
            # GD: trimestral em Opps (REALIZADO_GD com overrides)
            if is_gestor and _gestor_team_emails(session, email, ano, mes) is not None:
                # Time do gestor pela PERMISSAO_RLS, por mes (a equipe pode variar no trimestre)
                real_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS VAL
                    FROM (
                        SELECT LOWER(PROPRIETARIO) AS EMAIL_LOWER,
                               MONTH(DATA_QUALIFICACAO) AS MES_R,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) IN ({q_str})
                        GROUP BY 1, 2
                    ) cnt
                    INNER JOIN SUPERSET.PARCIAL.PERMISSAO_RLS r
                        ON r.ANO = {ano} AND r.MES = cnt.MES_R
                        AND LOWER(r.USUARIOEMAIL) = '{email}'
                        AND LOWER(r.CONSULTOREMAIL) = cnt.EMAIL_LOWER
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = cnt.MES_R
                        AND LOWER(o.EMAIL) = cnt.EMAIL_LOWER
                """).to_pandas()
            elif is_gestor:
                real_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS VAL
                    FROM (
                        SELECT LOWER(PROPRIETARIO) AS EMAIL_LOWER,
                               MONTH(DATA_QUALIFICACAO) AS MES_R,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) IN ({q_str})
                        GROUP BY 1, 2
                    ) cnt
                    INNER JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
                        ON rigot.YEAR = {ano} AND rigot.MONTH = cnt.MES_R
                    INNER JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
                        ON rio.ID = rigot.OWNER_ID
                        AND LOWER(rio.EMAIL) = cnt.EMAIL_LOWER
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                        ON p.ANO = {ano} AND p.MES = cnt.MES_R
                        AND LOWER(p.EMAIL) = cnt.EMAIL_LOWER
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = cnt.MES_R
                        AND LOWER(o.EMAIL) = cnt.EMAIL_LOWER
                    WHERE p.IS_GESTOR = FALSE
                """).to_pandas()
            else:
                real_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS VAL
                    FROM (
                        SELECT MONTH(DATA_QUALIFICACAO) AS MES_R,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) IN ({q_str})
                          AND LOWER(PROPRIETARIO) = '{email}'
                        GROUP BY 1
                    ) cnt
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = cnt.MES_R
                        AND LOWER(o.EMAIL) = '{email}'
                """).to_pandas()
            if is_gestor:
                meta_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(META_OTR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                    WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
                """).to_pandas()
            else:
                meta_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(rigot.TARGET_QUALIFIED), 0) AS VAL
                    FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
                    JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
                      ON rio.ID = rigot.OWNER_ID
                    WHERE rigot.YEAR = {ano} AND rigot.MONTH IN ({q_str})
                      AND LOWER(rio.EMAIL) = '{email}'
                """).to_pandas()

        elif is_b2g:
            # B2G: trimestral baseado em Booking (com filtro DEALS_PAGOS_400K)
            if is_gestor:
                # Gestor: trimestral sobre Booking da equipe
                real_tri_df = session.sql(f"""
                    WITH {_b2g_deals_cte_multi(ano, q_str)}
                    SELECT COALESCE(SUM(v.BOOKING), 0) AS VAL
                    FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                    INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                      ON m.ANO = v.ANO AND m.MES = v.MES AND m.CONSULTOR = v.CONSULTOR
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = v.ANO AND p.MES = v.MES AND p.EMAIL = v.CONSULTOR
                    WHERE v.ANO={ano} AND v.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                      AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
                """).to_pandas()
                meta_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(META_OTR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                    WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
                """).to_pandas()
            else:
                # Consultor: trimestral sobre Booking próprio
                real_tri_df = session.sql(f"""
                    WITH {_b2g_deals_cte_multi(ano, q_str)}
                    SELECT COALESCE(SUM(v.BOOKING), 0) AS VAL
                    FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                    WHERE v.ANO={ano} AND v.MES IN ({q_str}) AND LOWER(v.CONSULTOR)='{email}'
                      AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
                """).to_pandas()
                meta_tri_df = session.sql(f"""
                    SELECT COALESCE(SUM(META_OTR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                    WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
                """).to_pandas()

        elif is_gestor:
            real_tri_df = session.sql(f"""
                SELECT COALESCE(SUM({_valor_sql_case('v', 'v.VERTICAL')}), 0) AS VAL
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                WHERE v.ANO={ano} AND v.MES IN ({q_str})
                  AND v.VERTICAL IN ({equipes_in})
            """).to_pandas()
            meta_tri_df = session.sql(f"""
                SELECT COALESCE(SUM(META_MRR), 0) AS VAL
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
            """).to_pandas()
        else:
            real_tri_df = session.sql(f"""
                SELECT COALESCE(SUM({_valor_sql_fixa(equipe)}), 0) AS VAL
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM
                WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
            """).to_pandas()
            meta_tri_df = session.sql(f"""
                SELECT COALESCE(SUM(META_MRR), 0) AS VAL
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
            """).to_pandas()

        real_tri_ind = _f(real_tri_df.iloc[0]["VAL"], 0)
        meta_tri_ind = _f(meta_tri_df.iloc[0]["VAL"], 0)
        pct_tri_ind  = real_tri_ind / meta_tri_ind if meta_tri_ind > 0 else 0.0

        # B2G gestor usa fator ×0.9; gestor MRR usa ×0.6; consultores usam ×0.3
        if is_b2g and is_gestor:
            fator_mult_ind = 0.9
        elif is_gestor:
            fator_mult_ind = 0.6
        else:
            fator_mult_ind = 0.3
        fator_ind = (pct_tri_ind * fator_mult_ind) if pct_tri_ind >= 1.0 else 0.0

        real_tri_eq = 0.0
        meta_tri_eq = 0.0
        pct_tri_eq  = 0.0
        fator_eq    = 0.0

        if not is_gestor:
            if is_gd:
                eq_real_df = session.sql(f"""
                    SELECT COALESCE(SUM(COALESCE(o.REALIZADO_MANUAL, cnt.OPPS)), 0) AS VAL
                    FROM (
                        SELECT LOWER(PROPRIETARIO) AS EMAIL_LOWER,
                               MONTH(DATA_QUALIFICACAO) AS MES_R,
                               COUNT(DISTINCT ID_CONTATO) AS OPPS
                        FROM SUPERSET.COMISSOES.REALIZADO_GD
                        WHERE YEAR(DATA_QUALIFICACAO) = {ano}
                          AND MONTH(DATA_QUALIFICACAO) IN ({q_str})
                        GROUP BY 1, 2
                    ) cnt
                    INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                        ON m.ANO = {ano} AND m.MES = cnt.MES_R
                        AND LOWER(m.CONSULTOR) = cnt.EMAIL_LOWER
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                        ON p.ANO = {ano} AND p.MES = cnt.MES_R
                        AND LOWER(p.EMAIL) = cnt.EMAIL_LOWER
                    LEFT JOIN SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE o
                        ON o.ANO = {ano} AND o.MES = cnt.MES_R
                        AND LOWER(o.EMAIL) = cnt.EMAIL_LOWER
                    WHERE m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                """).to_pandas()
                real_tri_eq = _f(eq_real_df.iloc[0]["VAL"], 0)
                eq_meta_df = session.sql(f"""
                    SELECT COALESCE(SUM(m.META_OTR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = m.ANO AND p.MES = m.MES AND p.EMAIL = m.CONSULTOR
                    WHERE m.ANO={ano} AND m.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                """).to_pandas()
                meta_tri_eq = _f(eq_meta_df.iloc[0]["VAL"], 0)

            elif is_b2g:
                # B2G consultor: equipe trimestral baseado em Booking da equipe
                eq_real_df = session.sql(f"""
                    WITH {_b2g_deals_cte_multi(ano, q_str)}
                    SELECT COALESCE(SUM(v.BOOKING), 0) AS VAL
                    FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                    INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                      ON m.ANO = v.ANO AND m.MES = v.MES AND m.CONSULTOR = v.CONSULTOR
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = v.ANO AND p.MES = v.MES AND p.EMAIL = v.CONSULTOR
                    WHERE v.ANO={ano} AND v.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                      AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
                """).to_pandas()
                real_tri_eq = _f(eq_real_df.iloc[0]["VAL"], 0)
                eq_meta_df = session.sql(f"""
                    SELECT COALESCE(SUM(m.META_OTR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = m.ANO AND p.MES = m.MES AND p.EMAIL = m.CONSULTOR
                    WHERE m.ANO={ano} AND m.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                """).to_pandas()
                meta_tri_eq = _f(eq_meta_df.iloc[0]["VAL"], 0)

            else:
                eq_real_df = session.sql(f"""
                    SELECT COALESCE(SUM({_valor_sql_fixa(equipe, 'v')}), 0) AS VAL
                    FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                    INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                      ON m.ANO = v.ANO AND m.MES = v.MES AND m.CONSULTOR = v.CONSULTOR
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = v.ANO AND p.MES = v.MES AND p.EMAIL = v.CONSULTOR
                    WHERE v.ANO={ano} AND v.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe_safe}' AND p.IS_GESTOR = FALSE
                """).to_pandas()
                real_tri_eq = _f(eq_real_df.iloc[0]["VAL"], 0)
                eq_meta_df = session.sql(f"""
                    SELECT COALESCE(SUM(m.META_MRR), 0) AS VAL
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                      ON p.ANO = m.ANO AND p.MES = m.MES AND p.EMAIL = m.CONSULTOR
                    WHERE m.ANO={ano} AND m.MES IN ({q_str})
                      AND m.EQUIPE = '{equipe}' AND p.IS_GESTOR = FALSE
                """).to_pandas()
                meta_tri_eq = _f(eq_meta_df.iloc[0]["VAL"], 0)

            pct_tri_eq = real_tri_eq / meta_tri_eq if meta_tri_eq > 0 else 0.0
            if pct_tri_eq >= 1.0 and (cliff_ote_01 == 0 or pct_tri_ind >= cliff_ote_01):
                fator_eq = pct_tri_ind * 0.3

        trim = {
            "real_ind": real_tri_ind,
            "meta_ind": meta_tri_ind,
            "pct_ind":  pct_tri_ind,
            "real_eq":  real_tri_eq,
            "meta_eq":  meta_tri_eq,
            "pct_eq":   pct_tri_eq,
            "fator_ind": fator_ind,
            "fator_eq":  fator_eq,
            "is_gestor": is_gestor,
            "is_b2g":    is_b2g,
        }

    # ── 8. Ajuste Trimestral B2G (recálculo da comissão acumulada vs. mensais) ─
    b2g_ajuste = None
    if is_b2g and mes in (3, 6, 9, 12):
        q_str = f"{mes - 2},{mes - 1},{mes}"

        if is_gestor:
            # Gestor: Booking equipe acumulado + Meta Atingida da equipe no trimestre
            bk_q_df = session.sql(f"""
                WITH {_b2g_deals_cte_multi(ano, q_str)}
                SELECT COALESCE(SUM(v.BOOKING), 0) AS BK_Q
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                INNER JOIN SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                  ON m.ANO = v.ANO AND m.MES = v.MES AND m.CONSULTOR = v.CONSULTOR
                INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                  ON p.ANO = v.ANO AND p.MES = v.MES AND p.EMAIL = v.CONSULTOR
                WHERE v.ANO={ano} AND v.MES IN ({q_str})
                  AND m.EQUIPE='{equipe}' AND p.IS_GESTOR=FALSE
                  AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
            """).to_pandas()
            bk_q = _f(bk_q_df.iloc[0]["BK_Q"], 0)

            meta_bk_q_df = session.sql(f"""
                SELECT COALESCE(SUM(META_OTR), 0) AS VAL
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
            """).to_pandas()
            meta_bk_q = _f(meta_bk_q_df.iloc[0]["VAL"], 0)

            # Meta Atingida trimestral: consultores com %BK cumulativo ≥ 100%
            ma_q_df = session.sql(f"""
                WITH {_b2g_deals_cte_multi(ano, q_str)},
                consultor_bk AS (
                    SELECT m.CONSULTOR,
                           COALESCE(SUM(v.BOOKING), 0) / NULLIF(SUM(m.META_OTR), 0) AS pct_bk_c
                    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                    LEFT JOIN SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                        ON v.ANO = m.ANO AND v.MES = m.MES AND v.CONSULTOR = m.CONSULTOR
                        AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
                    INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                        ON p.ANO = m.ANO AND p.MES = m.MES AND p.EMAIL = m.CONSULTOR
                    WHERE m.ANO={ano} AND m.MES IN ({q_str})
                      AND m.EQUIPE='{equipe}' AND p.IS_GESTOR=FALSE
                    GROUP BY m.CONSULTOR
                )
                SELECT COUNT_IF(pct_bk_c >= 1.0) AS N_HIT, COUNT(*) AS N_TOTAL FROM consultor_bk
            """).to_pandas()
            ma_q_hit   = _f(ma_q_df.iloc[0]["N_HIT"],   0)
            ma_q_total = _f(ma_q_df.iloc[0]["N_TOTAL"],  0)
            ma_q = (ma_q_hit / ma_q_total) if ma_q_total > 0 else 0.0

            pct_bk_q = bk_q / meta_bk_q if meta_bk_q > 0 else 0.0
            pct_ma_q = ma_q / meta_atingida_meta if meta_atingida_meta > 0 else 0.0
            pct_ponderado_q = pct_bk_q * pond_bk_b2g + pct_ma_q * pond_ma

            # Pago mensal (col. AP) e OTE Base trimestral (col. AL): somas dos
            # valores mensais reais — meses fechados vêm do snapshot.
            pago_mensal, ote_base_q = _pago_mensal_trimestre(
                email, ano, mes, ote_variavel, ote_base)

            acel_q = _acel_b2g(pct_bk_q, cliff_ote_01, cliff_acel_01, mult_acel_01, cliff_acel_02, mult_acel_02)
            ote_variavel_q = ote_base_q * acel_q * pct_ponderado_q
            ajuste_val = ote_variavel_q - pago_mensal
            b2g_ajuste = {
                "bk_q": bk_q, "meta_bk_q": meta_bk_q,
                "pct_bk_q": pct_bk_q, "ma_q": ma_q,
                "pct_ma_q": pct_ma_q,
                "pct_ponderado_q": pct_ponderado_q,
                "ote_base_q": ote_base_q, "acel_q": acel_q,
                "ote_variavel_q": ote_variavel_q,
                "pago_mensal": pago_mensal,
                "ajuste": ajuste_val if ajuste_val > 0 else None,
                "is_gestor": True,
            }

        else:
            # Consultor: ARR + Booking acumulados no trimestre
            real_q_df = session.sql(f"""
                WITH {_b2g_deals_cte_multi(ano, q_str)}
                SELECT COALESCE(SUM(v.ARR), 0) AS ARR_Q, COALESCE(SUM(v.BOOKING), 0) AS BK_Q
                FROM SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM v
                WHERE v.ANO={ano} AND v.MES IN ({q_str}) AND LOWER(v.CONSULTOR)='{email}'
                  AND EXISTS (SELECT 1 FROM deals_ok_per_mes d WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
            """).to_pandas()
            arr_q = _f(real_q_df.iloc[0]["ARR_Q"], 0)
            bk_q  = _f(real_q_df.iloc[0]["BK_Q"],  0)

            meta_q_df = session.sql(f"""
                SELECT COALESCE(SUM(META_OTR), 0) AS META_BK_Q
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO={ano} AND MES IN ({q_str}) AND LOWER(CONSULTOR)='{email}'
            """).to_pandas()
            meta_bk_q  = _f(meta_q_df.iloc[0]["META_BK_Q"], 0)
            meta_arr_q = meta_bk_q * 0.5

            pct_arr_q = arr_q / meta_arr_q if meta_arr_q > 0 else 0.0
            pct_bk_q  = bk_q  / meta_bk_q  if meta_bk_q  > 0 else 0.0
            pct_ponderado_q = pct_arr_q * pond_arr_b2g + pct_bk_q * pond_bk_b2g

            # Pago mensal (col. AP) e OTE Base trimestral (col. AL): somas dos
            # valores mensais reais — meses fechados vêm do snapshot.
            pago_mensal, ote_base_q = _pago_mensal_trimestre(
                email, ano, mes, ote_variavel, ote_base)

            acel_q = _acel_b2g(pct_bk_q, cliff_ote_01, cliff_acel_01, mult_acel_01, cliff_acel_02, mult_acel_02)
            ote_variavel_q = ote_base_q * acel_q * pct_ponderado_q
            ajuste_val = ote_variavel_q - pago_mensal
            b2g_ajuste = {
                "arr_q": arr_q, "bk_q": bk_q,
                "meta_arr_q": meta_arr_q, "meta_bk_q": meta_bk_q,
                "pct_arr_q": pct_arr_q, "pct_bk_q": pct_bk_q,
                "pct_ponderado_q": pct_ponderado_q,
                "ote_base_q": ote_base_q, "acel_q": acel_q,
                "ote_variavel_q": ote_variavel_q,
                "pago_mensal": pago_mensal,
                "ajuste": ajuste_val if ajuste_val > 0 else None,
                "is_gestor": False,
            }

    # Ajuste trimestral B2G (calculado após total) soma ao variável total
    if b2g_ajuste and b2g_ajuste.get("ajuste"):
        total += b2g_ajuste["ajuste"]

    return {
        "equipe": equipe,
        "cargo": cargo,
        "meta_mrr": meta_mrr,
        "desconto": desconto,
        "realizado": realizado,
        "pct_atingido": pct_atingido,
        "ote_cheio": ote_cheio,
        "ote_02_cheio": ote_02_cheio,
        "ote_prop": ote_prop,
        "ote_02_prop": ote_02_prop,
        "ote_base": ote_base,
        "ote_tier": ote_tier,
        "cliff_ote_01": cliff_ote_01,
        "cliff_ote_02": cliff_ote_02,
        "cliff_acel_01": cliff_acel_01,
        "mult_acel_01": mult_acel_01,
        "cliff_acel_02": cliff_acel_02,
        "mult_acel_02": mult_acel_02,
        "acelerador": acelerador,
        "acel_desc": acel_desc,
        "ote_ajustado": ote_ajustado,
        "mrr_avista": mrr_avista,
        "mrr_cc3x": mrr_cc3x,
        "mrr_cc12x": mrr_cc12x,
        "mrr_recorrente": mrr_recorrente,
        "mult_avista": mult_avista,
        "mult_cc3x": mult_cc3x,
        "mult_cc12x": mult_cc12x,
        "mult_recorrente": mult_recorrente,
        "ote_variavel": ote_variavel,
        "booking_extras": booking_extras,
        "pct_bk_extra": pct_bk_extra,
        "comissao_bk_extra": comissao_bk_extra,
        "is_saving": is_saving,
        "is_gd": is_gd,
        "is_b2g": is_b2g,
        "faixa_atingida": faixa_atingida,
        "proxima_faixa": proxima_faixa,
        "dividas_pagas": dividas_pagas,
        "comissao_dividas": comissao_dividas,
        "pct_protecao": pct_protecao,
        "bonificacao_protecao": bonificacao_protecao,
        "ajuste_total": ajuste_total,
        "ajuste_n": ajuste_n,
        "total": total,
        "is_gestor": is_gestor,
        "opps_override": opps_override,
        "ote_indisponivel": ote_cheio is None,
        "trim": trim,
        "trim_bloqueado": trim_bloqueado,
        # B2G-specific
        "arr_real": arr_real,
        "bk_real": bk_real,
        "meta_arr": meta_arr,
        "pct_arr_b2g": pct_arr_b2g,
        "pct_bk_b2g": pct_bk_b2g,
        "pct_ponderado": pct_ponderado,
        "pond_arr_b2g": pond_arr_b2g,
        "pond_bk_b2g": pond_bk_b2g,
        "meta_atingida_real": meta_atingida_real,
        "meta_atingida_meta": meta_atingida_meta,
        "pct_meta_atingida": pct_meta_atingida,
        "pond_ma": pond_ma,
        "b2g_ajuste": b2g_ajuste,
    }


def composicao_ajustes(session, email, ano, mes):
    """Retorna o detalhamento dos ajustes pontuais para exibição no expander."""
    email = str(email).strip().lower().replace("'", "''")
    _MESES = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
              7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}
    df = session.sql(f"""
        SELECT ID, VALOR, DESCRICAO, REF_ANO, REF_MES
        FROM SUPERSET.COMISSOES.AJUSTES_PONTUAIS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(EMAIL) = '{email}'
        ORDER BY ID
    """).to_pandas()
    if df.empty:
        return df
    def _ref(row):
        if row["REF_MES"] and row["REF_ANO"]:
            return f"{_MESES.get(int(row['REF_MES']), row['REF_MES'])}/{int(row['REF_ANO'])}"
        return "—"
    df["REF"] = df.apply(_ref, axis=1)
    return df[["VALOR", "DESCRICAO", "REF"]].rename(columns={
        "VALOR": "Valor", "DESCRICAO": "Descrição", "REF": "Ref. Mês",
    })
