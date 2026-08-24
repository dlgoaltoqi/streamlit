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

# ── Account Manager (NRR da carteira) — medição a partir de ago/2026 ─────────
# Regras em docs/20_aba_comissoes_am.md. Sem regra de comissão ainda: o modelo
# só MEDE MRR Inicial, Evoluído e % de crescimento/redução da carteira.
AM_DESDE = (2026, 8)

# Carteira: HUBSPOT_LISTA_POTENCIAL_FARMER (dbt) já consolida cliente →
# ACCOUNT_MANAGER (por NOME — resolve-se e-mail via consultants/owners da RI).
# É a mesma base do painel PBI "Potenciais Clientes Farmer".
_AM_CARTEIRA_SQL = """
    SELECT DISTINCT LOWER(rio.EMAIL) AS GERENTE,
           TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) AS ID_CLIENTE
    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
    JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
      ON ric.NAME = l.ACCOUNT_MANAGER
    JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
      ON rio.ID = ric.HUBSPOT_OWNER_ID
    WHERE l.ACCOUNT_MANAGER IS NOT NULL AND l.ACCOUNT_MANAGER <> 'N/A'
"""

# Contratos da carteira (regras formais do Higor, 06/08/2026): tipos
# 'Assinatura'/'plano_business', cliente = contato p/ PF, empresa p/ PJ (IDs
# vêm como float serializado '..000000'). Vigência: início < 1º do mês e
# renovação >= 1º do mês. Nos dados, DATA_DE_DESATIVACAO NUNCA é nula — nos
# contratos Ativos ela é placeholder antigo (1900-01-01 ou resíduo); nos
# Inativos marca o churn real. Logo "desativação nula ou no mês" traduz-se:
# STATUS='Ativo' OU desativação >= 1º do mês.
# 13/08/2026: o dbt recriou a tabela com colunas MAIÚSCULAS sem espaço/acento
# (antes eram "Id do contrato" etc.) e NUMERO_DO_CONTRATO virou NUMBER(38,6).
_AM_EXCLUSOES_TABELA = "SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM"

_AM_CONTRATOS_BRUTA_SQL = f"""
    SELECT ca.GERENTE, ca.ID_CLIENTE,
           c.ID_DO_CONTRATO AS CONTRATO,
           TO_VARCHAR(c.NUMERO_DO_CONTRATO::NUMBER(38,0)) AS NUM_CONTRATO,
           c.MRR AS MRR,
           c.DATA_DE_INICIO AS INI, c.DATA_DE_RENOVACAO AS REN,
           c.DATA_DE_DESATIVACAO AS DESATIV, c.STATUS AS STATUS,
           c.CONTRATO_GERADO_POR_IMPULSO AS CONTRATO_GERADO_POR_IMPULSO,
           c.SUBTIPO_DA_VENDA AS SUBTIPO_DA_VENDA
    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS c
    JOIN ({_AM_CARTEIRA_SQL}) ca
      ON ca.ID_CLIENTE = CASE WHEN c.TIPO_DE_PESSOA = 'Física'
                              THEN COALESCE(SPLIT_PART(c.ID_DO_CONTATO, '.', 1),
                                            SPLIT_PART(c.ID_DA_EMPRESA, '.', 1))
                              ELSE COALESCE(SPLIT_PART(c.ID_DA_EMPRESA, '.', 1),
                                            SPLIT_PART(c.ID_DO_CONTATO, '.', 1)) END
    WHERE LOWER(c.TIPO_DE_CONTRATO) IN ('assinatura', 'plano_business')
"""

# A exclusao administrativa e aplicada uma unica vez na fonte de contratos AM.
# Assim o contrato nao entra no Inicial, no Evoluido nem nas composicoes que
# partem dessa carteira.
_AM_CONTRATOS_SQL = f"""
    SELECT contratos.*
    FROM ({_AM_CONTRATOS_BRUTA_SQL}) contratos
    WHERE NOT EXISTS (
        SELECT 1
        FROM {_AM_EXCLUSOES_TABELA} exclusao
        WHERE exclusao.ID_CONTRATO = contratos.CONTRATO
    )
"""

# Contratos elegíveis a origem de impulso SEM o vínculo de carteira: o impulso
# pode consolidar contratos de OUTRO registro de cliente (ex.: contratos PF do
# contato consolidados no contrato PJ da empresa encarteirada). Mesmos tipos e
# exclusões administrativas do _AM_CONTRATOS_SQL.
_AM_CONTRATOS_SOLTOS_SQL = f"""
    SELECT c.ID_DO_CONTRATO AS CONTRATO,
           TO_VARCHAR(c.NUMERO_DO_CONTRATO::NUMBER(38,0)) AS NUM_CONTRATO,
           c.MRR AS MRR,
           c.DATA_DE_INICIO AS INI, c.DATA_DE_RENOVACAO AS REN,
           c.DATA_DE_DESATIVACAO AS DESATIV, c.STATUS AS STATUS,
           c.CONTRATO_GERADO_POR_IMPULSO AS CONTRATO_GERADO_POR_IMPULSO
    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS c
    WHERE LOWER(c.TIPO_DE_CONTRATO) IN ('assinatura', 'plano_business')
      AND NOT EXISTS (
          SELECT 1
          FROM {_AM_EXCLUSOES_TABELA} exclusao
          WHERE exclusao.ID_CONTRATO = c.ID_DO_CONTRATO
      )
"""

# Condição de "vigente no dia 1º do mês" (compõe o MRR Inicial): m1 = 1º do mês
def _am_cond_inicial(m1):
    return (f"INI < {m1} AND REN >= {m1} "
            f"AND (STATUS = 'Ativo' OR DESATIV >= {m1})")

def _am_movimentacoes_ctes(m1, m2, corte):
    """Eventos que levam o MRR Inicial ao Evoluído da carteira AM.

    Cada evento preserva os contratos substituídos e o contrato novo, para que
    o NRR seja calculado pelo delta, e não pelo MRR bruto de uma venda.
    """
    return f"""
        cc AS ({_AM_CONTRATOS_SQL}),
        carteira_inicial AS (
            SELECT *
            FROM cc
            WHERE {_am_cond_inicial(m1)}
        ),
        raut_mes AS (
            -- Vendas de RAUT ainda ganhas: a tabela de vendas retém por um
            -- tempo negócio que depois foi marcado perdido (ex.: RAUT
            -- 61694979964/ROHR ainda em VENDAS dias após perder); negócio
            -- perdido não pode alimentar o MRR novo de uma renovação.
            SELECT ca.GERENTE, ca.ID_CLIENTE,
                   TO_VARCHAR(TRY_TO_NUMBER(v.CONTRATO)) AS NUM_CONTRATO,
                   MAX(v.FECHAMENTO_NEGOCIO) AS DATA_FECHAMENTO,
                   SUM(v.MRR) AS MRR_NOVO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN ({_AM_CARTEIRA_SQL}) ca
              ON ca.ID_CLIENTE = SPLIT_PART(v.ID_DO_CLIENTE, '.', 1)
            LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON negocio."Id do negócio" = v.ID_NEGOCIO
            WHERE v.ANO = YEAR({m1}) AND v.MES = MONTH({m1}) AND {_AM_PIPE_RAUT}
              AND NOT COALESCE(negocio."Fechado perdido", FALSE)
            GROUP BY 1, 2, 3
        ),
        vendas_am_mes AS (
            -- Vendas que compõem o Evoluído: nos pipelines AM a própria AM
            -- precisa ser a consultora da venda; nos pipelines de e-commerce
            -- e saving a venda credita pela carteira, qualquer consultor
            -- (regra de 13/08/2026 — ex.: recompra e-commerce da BAMBOO,
            -- contrato 639337, conta para a dona da carteira).
            SELECT ca.GERENTE, ca.ID_CLIENTE,
                   TO_VARCHAR(TRY_TO_NUMBER(v.CONTRATO)) AS NUM_CONTRATO,
                   v.ID_NEGOCIO AS NEGOCIO,
                   MAX(v.NOME_NEGOCIO) AS NOME_NEGOCIO,
                   MAX(v.FECHAMENTO_NEGOCIO) AS DATA_FECHAMENTO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN ({_AM_CARTEIRA_SQL}) ca
              ON ca.ID_CLIENTE = SPLIT_PART(v.ID_DO_CLIENTE, '.', 1)
            WHERE v.ANO = YEAR({m1}) AND v.MES = MONTH({m1})
              AND (
                  ({_AM_PIPE_VENDA} AND ca.GERENTE = LOWER(v.CONSULTOR))
                  OR {_AM_PIPE_CARTEIRA}
              )
            GROUP BY 1, 2, 3, 4
        ),
        vendas_carteira_mes AS (
            -- Vendas do mes para clientes da carteira, em QUALQUER pipeline.
            -- Serve apenas para enriquecer substituicoes_am com o negocio;
            -- classificacao e MRR nunca dependem desta CTE.
            SELECT ca.GERENTE, ca.ID_CLIENTE,
                   TO_VARCHAR(TRY_TO_NUMBER(v.CONTRATO)) AS NUM_CONTRATO,
                   v.ID_NEGOCIO AS NEGOCIO,
                   MAX(v.NOME_NEGOCIO) AS NOME_NEGOCIO,
                   MAX(v.FECHAMENTO_NEGOCIO) AS DATA_FECHAMENTO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            JOIN ({_AM_CARTEIRA_SQL}) ca
              ON ca.ID_CLIENTE = SPLIT_PART(v.ID_DO_CLIENTE, '.', 1)
            WHERE v.ANO = YEAR({m1}) AND v.MES = MONTH({m1})
            GROUP BY 1, 2, 3, 4
        ),
        sucessores_negocio_perdido AS (
            -- Contrato cujos negócios associados estão TODOS perdidos e sem
            -- venda ganha no mês para o mesmo número: a renovação não se
            -- concretizou, mesmo que a linha do contrato (criada
            -- antecipadamente) ainda esteja Ativa. Não vira renovação nem
            -- substituição; a origem segue para o churn (correr atrás).
            -- Caso 60165725596 (nº 321378, DE MELO MARQUES, Renata,
            -- ago/2026): RAUT e negócio AM perdidos, sem venda em 2026.
            SELECT contrato.CONTRATO
            FROM cc contrato
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL associacao
              ON SPLIT_PART(associacao.ID_CONTRATO, '.', 1) = contrato.CONTRATO
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON negocio."Id do negócio" = SPLIT_PART(associacao.ID_DEAL, '.', 1)
            WHERE NOT EXISTS (
                SELECT 1
                FROM vendas_carteira_mes venda
                JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio_venda
                  ON negocio_venda."Id do negócio" = venda.NEGOCIO
                WHERE venda.GERENTE = contrato.GERENTE
                  AND venda.NUM_CONTRATO = contrato.NUM_CONTRATO
                  AND NOT COALESCE(negocio_venda."Fechado perdido", FALSE)
            )
            GROUP BY contrato.CONTRATO
            HAVING COUNT_IF(NOT COALESCE(negocio."Fechado perdido", FALSE)) = 0
        ),
        substituicoes_am AS (
            -- Substituicao de contrato (mesmo NUM_CONTRATO) cujo SUBTIPO DO
            -- CONTRATO SUCESSOR indica upsell/cross (ex.: 'upsell_cross'), nao
            -- renovacao. O subtipo do contrato e a fonte da classificacao; a
            -- venda associada so enriquece com o negocio e nao restringe por
            -- pipeline nem por consultor (na transicao Farmer->AM ha upsell
            -- vendido em pipeline legado, e ha substituicao sem venda no mes).
            -- Tratada como upsell com delta de MRR; o contrato antigo entra em
            -- contratos_substituidos para nao gerar churn falso.
            -- O sucessor pode estar em OUTRO registro de cliente, desde que da
            -- MESMA gerente (regra de 17/08/2026, como no impulso): a renovacao
            -- da ROHR (631731, Clidiani, ago/2026) criou o contrato novo na
            -- empresa 57413557115 e a origem esta na 37095448225.
            SELECT origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.GERENTE, origem.ID_CLIENTE,
                   sucessor.CONTRATO AS CONTRATO_NOVO, sucessor.NUM_CONTRATO,
                   origem.MRR AS MRR_ANTERIOR,
                   sucessor.MRR AS MRR_NOVO,
                   (sucessor.MRR - origem.MRR) AS DELTA_MRR,
                   venda.NEGOCIO, venda.NOME_NEGOCIO,
                   COALESCE(venda.DATA_FECHAMENTO, sucessor.INI) AS DATA_FECHAMENTO
            FROM carteira_inicial origem
            JOIN cc sucessor
              ON sucessor.NUM_CONTRATO = origem.NUM_CONTRATO
             AND (sucessor.ID_CLIENTE = origem.ID_CLIENTE
                  OR sucessor.GERENTE = origem.GERENTE)
             AND sucessor.CONTRATO <> origem.CONTRATO
             AND sucessor.INI >= {m1}
             AND (
                 sucessor.INI < {m2}
                 OR (origem.DESATIV < origem.REN AND sucessor.INI <= origem.REN)
             )
             AND sucessor.INI > origem.INI
             AND LOWER(COALESCE(sucessor.SUBTIPO_DA_VENDA, '')) LIKE '%upsell%'
             AND LOWER(COALESCE(sucessor.SUBTIPO_DA_VENDA, '')) NOT LIKE '%renov%'
            LEFT JOIN vendas_carteira_mes venda
              ON venda.GERENTE = origem.GERENTE
             AND venda.ID_CLIENTE = origem.ID_CLIENTE
             AND venda.NUM_CONTRATO = sucessor.NUM_CONTRATO
            WHERE origem.STATUS = 'Inativo'
              AND origem.DESATIV >= {m1} AND origem.DESATIV <= {corte}
              AND sucessor.STATUS = 'Ativo'
              AND NOT EXISTS (
                  SELECT 1 FROM sucessores_negocio_perdido perdido
                  WHERE perdido.CONTRATO = sucessor.CONTRATO
              )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY origem.CONTRATO
                ORDER BY sucessor.INI, sucessor.CONTRATO,
                         venda.DATA_FECHAMENTO, venda.NEGOCIO
            ) = 1
        ),
        renovacoes_diretas AS (
            -- A mesma numeracao identifica a renovacao. O contrato novo
            -- substitui o anterior, inclusive quando a venda veio por RAUT.
            -- Quando o contrato foi desativado antes da sua data de renovacao
            -- (DESATIV < REN), o sucessor pode comecar ate a data de renovacao
            -- do antigo (ex.: desativado em ago, novo inicia em set na data REN).
            -- Excluidos os casos cujo sucessor tem subtipo de upsell/cross
            -- (classificados como upsell via substituicoes_am).
            -- Como em substituicoes_am, o sucessor pode estar em outro registro
            -- de cliente da mesma gerente (regra de 17/08/2026, caso ROHR).
            SELECT 'Renovação' AS TIPO,
                   origem.GERENTE, origem.ID_CLIENTE,
                   origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.NUM_CONTRATO AS NUM_CONTRATO,
                   origem.MRR AS MRR_ANTERIOR,
                   sucessor.CONTRATO AS CONTRATO_NOVO,
                   sucessor.MRR AS MRR_NOVO,
                   sucessor.INI AS INICIO_NOVO,
                   1 AS N_CONTRATOS_ANTERIORES
            FROM carteira_inicial origem
            JOIN cc sucessor
              ON sucessor.NUM_CONTRATO = origem.NUM_CONTRATO
             AND (sucessor.ID_CLIENTE = origem.ID_CLIENTE
                  OR sucessor.GERENTE = origem.GERENTE)
             AND sucessor.CONTRATO <> origem.CONTRATO
             AND sucessor.INI >= {m1}
             AND (
                 sucessor.INI < {m2}
                 OR (origem.DESATIV < origem.REN AND sucessor.INI <= origem.REN)
             )
             AND sucessor.INI > origem.INI
            WHERE origem.STATUS = 'Inativo'
              AND origem.DESATIV >= {m1} AND origem.DESATIV <= {corte}
              AND sucessor.STATUS = 'Ativo'
              AND NOT EXISTS (
                  SELECT 1 FROM substituicoes_am s
                  WHERE s.CONTRATO_ANTERIOR = origem.CONTRATO
              )
              AND NOT EXISTS (
                  SELECT 1 FROM sucessores_negocio_perdido perdido
                  WHERE perdido.CONTRATO = sucessor.CONTRATO
              )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY origem.CONTRATO
                ORDER BY sucessor.INI, sucessor.CONTRATO
            ) = 1
        ),
        origens_impulso AS (
            -- Origens de impulso vigentes no dia 1º (INI < m1, REN >= m1),
            -- inativadas dentro do mes e com o campo 'Contrato gerado por
            -- impulso' preenchido. Vem de TODOS os contratos, nao so da
            -- carteira: o impulso pode consolidar contratos de OUTRO registro
            -- de cliente (ex.: contratos PF do contato consolidados no
            -- contrato PJ da empresa encarteirada — caso 63465435532/639252,
            -- Renata, ago/2026). As guardas temporais preservam a regra
            -- "origens so do Inicial": linhas historicas (REN ja vencida) e
            -- linhas criadas e desativadas no proprio mes continuam fora
            -- (ex.: 602012 tinha 2 ciclos antigos carimbados em 03/08/2026;
            -- 631608 teve renovacao criada e consolidada no mesmo dia
            -- 05/08/2026). GERENTE vem de cc quando a origem pertence a uma
            -- carteira e NULL quando esta a deriva.
            SELECT solto.*, cc.GERENTE
            FROM ({_AM_CONTRATOS_SOLTOS_SQL}) solto
            LEFT JOIN cc ON cc.CONTRATO = solto.CONTRATO
            WHERE solto.INI < {m1} AND solto.REN >= {m1}
              AND solto.STATUS = 'Inativo'
              AND solto.DESATIV >= {m1} AND solto.DESATIV <= {corte}
              AND NULLIF(TRIM(solto.CONTRATO_GERADO_POR_IMPULSO), '') IS NOT NULL
        ),
        impulsos_pares AS (
            -- Pares origem->sucessor de impulso por DUAS vias complementares:
            -- 1) associacoes do negocio 'Novo negócio - Impulso de Contrato';
            -- 2) o campo 'Contrato gerado por impulso' da origem, que carrega
            --    o NUMERO do contrato consolidado. Ha impulso sem negocio
            --    associado ao contrato novo (ex.: 638194 -> 639342, ago/2026),
            --    que so a via 2 enxerga. O UNION deduplica pares repetidos.
            -- GERENTE/ID_CLIENTE vem do SUCESSOR: o delta credita a dona do
            -- contrato consolidado. Origem de OUTRA carteira nao cruza (so
            -- entra origem sem carteira ou da mesma gerente), para nao mexer
            -- no churn de outra AM.
            SELECT sucessor.GERENTE, sucessor.ID_CLIENTE,
                   origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.NUM_CONTRATO AS NUM_CONTRATO_ANTERIOR,
                   origem.MRR AS MRR_ANTERIOR,
                   sucessor.CONTRATO AS CONTRATO_NOVO,
                   sucessor.NUM_CONTRATO,
                   sucessor.MRR AS MRR_NOVO,
                   sucessor.INI AS INICIO_NOVO
            FROM origens_impulso origem
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL associacao_origem
              ON SPLIT_PART(associacao_origem.ID_CONTRATO, '.', 1) = origem.CONTRATO
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON negocio."Id do negócio" = SPLIT_PART(associacao_origem.ID_DEAL, '.', 1)
             AND negocio."Tipo de negócio" = 'Novo negócio - Impulso de Contrato'
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL associacao_sucessor
              ON associacao_sucessor.ID_DEAL = associacao_origem.ID_DEAL
            JOIN cc sucessor
              ON sucessor.CONTRATO = SPLIT_PART(associacao_sucessor.ID_CONTRATO, '.', 1)
             AND sucessor.CONTRATO <> origem.CONTRATO
             AND (origem.GERENTE IS NULL OR sucessor.GERENTE = origem.GERENTE)
             AND sucessor.INI >= {m1} AND sucessor.INI < {m2}
             AND sucessor.STATUS = 'Ativo'
             AND NULLIF(TRIM(sucessor.CONTRATO_GERADO_POR_IMPULSO), '') IS NULL
            UNION
            SELECT sucessor.GERENTE, sucessor.ID_CLIENTE,
                   origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.NUM_CONTRATO AS NUM_CONTRATO_ANTERIOR,
                   origem.MRR AS MRR_ANTERIOR,
                   sucessor.CONTRATO AS CONTRATO_NOVO,
                   sucessor.NUM_CONTRATO,
                   sucessor.MRR AS MRR_NOVO,
                   sucessor.INI AS INICIO_NOVO
            FROM origens_impulso origem
            JOIN cc sucessor
              ON sucessor.NUM_CONTRATO =
                 TO_VARCHAR(TRY_TO_NUMBER(TRIM(origem.CONTRATO_GERADO_POR_IMPULSO)))
             AND sucessor.CONTRATO <> origem.CONTRATO
             AND (origem.GERENTE IS NULL OR sucessor.GERENTE = origem.GERENTE)
             AND sucessor.INI >= {m1} AND sucessor.INI < {m2}
             AND sucessor.STATUS = 'Ativo'
             AND NULLIF(TRIM(sucessor.CONTRATO_GERADO_POR_IMPULSO), '') IS NULL
        ),
        impulsos_contrato AS (
            -- Um impulso consolida 1-n contratos antigos no mesmo sucessor.
            SELECT 'Impulso' AS TIPO,
                   GERENTE, ID_CLIENTE,
                   LISTAGG(DISTINCT CONTRATO_ANTERIOR, ', ')
                       WITHIN GROUP (ORDER BY CONTRATO_ANTERIOR)
                       AS CONTRATO_ANTERIOR,
                   LISTAGG(DISTINCT NUM_CONTRATO_ANTERIOR, ', ')
                       WITHIN GROUP (ORDER BY NUM_CONTRATO_ANTERIOR)
                       AS NUM_CONTRATOS_ANTERIORES,
                   NUM_CONTRATO,
                   SUM(MRR_ANTERIOR) AS MRR_ANTERIOR,
                   CONTRATO_NOVO,
                   MAX(MRR_NOVO) AS MRR_NOVO,
                   INICIO_NOVO,
                   COUNT(DISTINCT CONTRATO_ANTERIOR) AS N_CONTRATOS_ANTERIORES
            FROM impulsos_pares
            GROUP BY GERENTE, ID_CLIENTE, NUM_CONTRATO, CONTRATO_NOVO,
                     INICIO_NOVO
        ),
        downgrades_contrato AS (
            -- Downgrade/downsell sem elo estrutural: o contrato novo tem OUTRO
            -- numero e nao ha venda do mes ligando os dois. O unico vinculo e o
            -- NOME do negocio que gerou o contrato novo, que carrega o numero
            -- do contrato substituido apos a palavra downgrade/downsell (ex.:
            -- '[CS - Cancelamentos] Downgrade 620616 - Gabriel Macedo'). O
            -- contrato antigo entra em contratos_substituidos (nao e churn) e o
            -- delta de MRR vai para o grupo de upsells com TIPO 'Downgrade'.
            -- O negocio liga-se ao contrato novo pelo "Número do contrato" do
            -- proprio negocio OU pela associacao; as associacoes contrato-deal
            -- (bronze/prata identicas) sao uma foto que pode ficar dias
            -- defasada da DEALS (constatado em 13/08/2026), entao nao podem
            -- ser o unico caminho.
            SELECT origem.GERENTE, origem.ID_CLIENTE,
                   origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.MRR AS MRR_ANTERIOR,
                   sucessor.CONTRATO AS CONTRATO_NOVO,
                   sucessor.NUM_CONTRATO,
                   sucessor.MRR AS MRR_NOVO,
                   (sucessor.MRR - origem.MRR) AS DELTA_MRR,
                   negocio."Id do negócio" AS NEGOCIO,
                   negocio."Nome do negócio" AS NOME_NEGOCIO,
                   COALESCE(negocio."Data de fechamento"::DATE, sucessor.INI)
                       AS DATA_FECHAMENTO
            FROM carteira_inicial origem
            JOIN cc sucessor
              ON sucessor.ID_CLIENTE = origem.ID_CLIENTE
             AND sucessor.CONTRATO <> origem.CONTRATO
             AND sucessor.NUM_CONTRATO <> origem.NUM_CONTRATO
             AND sucessor.INI >= {m1}
             AND (
                 sucessor.INI < {m2}
                 OR (origem.DESATIV < origem.REN AND sucessor.INI <= origem.REN)
             )
             AND sucessor.INI > origem.INI
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON REGEXP_LIKE(negocio."Nome do negócio",
                             '.*(downgrade|downsell).*', 'i')
             AND TO_VARCHAR(TRY_TO_NUMBER(REGEXP_SUBSTR(negocio."Nome do negócio",
                     '(downgrade|downsell)[^0-9]*([0-9]{{3,}})', 1, 1, 'ie', 2)))
                 = origem.NUM_CONTRATO
             AND (
                 TO_VARCHAR(TRY_TO_NUMBER(negocio."Número do contrato"))
                     = sucessor.NUM_CONTRATO
                 OR EXISTS (
                     SELECT 1
                     FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL associacao
                     WHERE SPLIT_PART(associacao.ID_CONTRATO, '.', 1) = sucessor.CONTRATO
                       AND SPLIT_PART(associacao.ID_DEAL, '.', 1) = negocio."Id do negócio"
                 )
             )
            WHERE origem.STATUS = 'Inativo'
              AND origem.DESATIV >= {m1} AND origem.DESATIV <= {corte}
              AND sucessor.STATUS = 'Ativo'
              AND NULLIF(TRIM(origem.CONTRATO_GERADO_POR_IMPULSO), '') IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM substituicoes_am s
                  WHERE s.CONTRATO_ANTERIOR = origem.CONTRATO
                     OR s.CONTRATO_NOVO = sucessor.CONTRATO
              )
              AND NOT EXISTS (
                  SELECT 1 FROM renovacoes_diretas r
                  WHERE r.CONTRATO_ANTERIOR = origem.CONTRATO
                     OR r.CONTRATO_NOVO = sucessor.CONTRATO
              )
              AND NOT EXISTS (
                  SELECT 1 FROM impulsos_contrato i
                  WHERE i.CONTRATO_NOVO = sucessor.CONTRATO
              )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY origem.CONTRATO
                ORDER BY sucessor.INI, sucessor.CONTRATO, negocio."Id do negócio"
            ) = 1
            AND ROW_NUMBER() OVER (
                PARTITION BY sucessor.CONTRATO
                ORDER BY origem.DESATIV, origem.CONTRATO
            ) = 1
        ),
        renovacoes_raut_sem_sucessor AS (
            -- Se a RAUT chegou antes da criacao da nova linha de contrato,
            -- ainda comparamos seu MRR com o contrato inicial. Nunca somamos
            -- o MRR bruto da RAUT ao Evoluído.
            SELECT 'Renovação' AS TIPO,
                   origem.GERENTE, origem.ID_CLIENTE,
                   origem.CONTRATO AS CONTRATO_ANTERIOR,
                   origem.NUM_CONTRATO,
                   origem.MRR AS MRR_ANTERIOR,
                   CAST(NULL AS VARCHAR) AS CONTRATO_NOVO,
                   raut.MRR_NOVO,
                   raut.DATA_FECHAMENTO AS INICIO_NOVO,
                   1 AS N_CONTRATOS_ANTERIORES
            FROM carteira_inicial origem
            JOIN raut_mes raut
              ON raut.GERENTE = origem.GERENTE
             AND raut.ID_CLIENTE = origem.ID_CLIENTE
             AND raut.NUM_CONTRATO = origem.NUM_CONTRATO
            WHERE NOT EXISTS (
                SELECT 1
                FROM renovacoes_diretas renovacao
                WHERE renovacao.CONTRATO_ANTERIOR = origem.CONTRATO
            )
              AND NOT EXISTS (
                SELECT 1
                FROM substituicoes_am s
                WHERE s.CONTRATO_ANTERIOR = origem.CONTRATO
            )
              AND NOT EXISTS (
                SELECT 1
                FROM downgrades_contrato d
                WHERE d.CONTRATO_ANTERIOR = origem.CONTRATO
            )
              AND NULLIF(TRIM(origem.CONTRATO_GERADO_POR_IMPULSO), '') IS NULL
        ),
        renovacoes_contrato AS (
            SELECT * FROM renovacoes_diretas
            UNION ALL
            SELECT * FROM renovacoes_raut_sem_sucessor
        ),
        contratos_substituidos AS (
            SELECT CONTRATO_ANTERIOR AS CONTRATO FROM renovacoes_diretas
            UNION
            SELECT f.value::VARCHAR AS CONTRATO
            FROM impulsos_contrato impulso,
                 LATERAL FLATTEN(INPUT => SPLIT(impulso.CONTRATO_ANTERIOR, ', ')) f
            UNION
            SELECT CONTRATO_ANTERIOR AS CONTRATO FROM renovacoes_raut_sem_sucessor
            UNION
            SELECT CONTRATO_ANTERIOR AS CONTRATO FROM substituicoes_am
            UNION
            SELECT CONTRATO_ANTERIOR AS CONTRATO FROM downgrades_contrato
        ),
        upsells_contrato AS (
            -- 'Novo negócio' soma o MRR cheio do contrato novo (sem contrato
            -- substituído — os que substituem outro ja foram classificados
            -- como renovação ou impulso). 'Upsell' e 'Downgrade' são
            -- substituições e entram pelo delta, com MRR anterior/novo
            -- expostos para o painel.
            SELECT 'Novo negócio' AS TIPO,
                   venda.GERENTE, venda.ID_CLIENTE,
                   novo.CONTRATO, novo.NUM_CONTRATO,
                   CAST(NULL AS NUMBER) AS MRR_ANTERIOR,
                   novo.MRR AS MRR_NOVO,
                   novo.MRR,
                   venda.NEGOCIO, venda.NOME_NEGOCIO, venda.DATA_FECHAMENTO
            FROM vendas_am_mes venda
            JOIN cc novo
              ON novo.GERENTE = venda.GERENTE
             AND novo.ID_CLIENTE = venda.ID_CLIENTE
             AND novo.NUM_CONTRATO = venda.NUM_CONTRATO
             AND novo.STATUS = 'Ativo'
             AND novo.INI >= {m1} AND novo.INI < {m2}
            WHERE NOT EXISTS (
                SELECT 1
                FROM renovacoes_contrato renovacao
                WHERE renovacao.CONTRATO_NOVO = novo.CONTRATO
            )
              AND NOT EXISTS (
                SELECT 1
                FROM impulsos_contrato impulso
                WHERE impulso.CONTRATO_NOVO = novo.CONTRATO
            )
              AND NOT EXISTS (
                SELECT 1
                FROM substituicoes_am s
                WHERE s.CONTRATO_NOVO = novo.CONTRATO
            )
              AND NOT EXISTS (
                SELECT 1
                FROM downgrades_contrato d
                WHERE d.CONTRATO_NOVO = novo.CONTRATO
            )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY novo.CONTRATO
                ORDER BY venda.DATA_FECHAMENTO, venda.NEGOCIO
            ) = 1
            UNION ALL
            SELECT 'Upsell' AS TIPO,
                   s.GERENTE, s.ID_CLIENTE,
                   s.CONTRATO_NOVO AS CONTRATO, s.NUM_CONTRATO,
                   s.MRR_ANTERIOR, s.MRR_NOVO,
                   s.DELTA_MRR AS MRR,
                   s.NEGOCIO, s.NOME_NEGOCIO, s.DATA_FECHAMENTO
            FROM substituicoes_am s
            UNION ALL
            SELECT 'Downgrade' AS TIPO,
                   d.GERENTE, d.ID_CLIENTE,
                   d.CONTRATO_NOVO AS CONTRATO, d.NUM_CONTRATO,
                   d.MRR_ANTERIOR, d.MRR_NOVO,
                   d.DELTA_MRR AS MRR,
                   d.NEGOCIO, d.NOME_NEGOCIO, d.DATA_FECHAMENTO
            FROM downgrades_contrato d
        )
    """


_AM_PIPE_VENDA = "PIPELINE ILIKE '%account manager%'"
_AM_PIPE_RAUT  = "PIPELINE ILIKE '%renova%autom%'"
# E-commerce e Saving entram no net da carteira (regra de 13/08/2026): a venda
# credita a dona da carteira do cliente, como no raut — no e-commerce o
# CONSULTOR vem 'N/A' (autosserviço) e no saving quem vende é o time de CS.
_AM_PIPE_CARTEIRA = "(PIPELINE ILIKE '%e-commerce%' OR PIPELINE ILIKE '%saving%')"


def _am_datas(ano, mes):
    """(inicio_mes, inicio_mes_seguinte) como literais SQL DATE."""
    m1 = f"DATE '{int(ano)}-{int(mes):02d}-01'"
    a2, m2 = (int(ano) + 1, 1) if int(mes) == 12 else (int(ano), int(mes) + 1)
    return m1, f"DATE '{a2}-{m2:02d}-01'"


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


# ── Config administrável (SUPERSET.COMISSOES.CONFIG) ─────────────────────────
# Regras de negócio com vigência: cada linha vale a partir de (ANO, MES) e o
# cálculo do mês M usa a vigência mais recente <= M. Chave ausente cai no
# default do código. Edição: Administração > Configurações.

def carregar_config(session, ano, meses):
    """({mes: {chave: valor}}, ok) — valores vigentes por mês do MESMO ano.
    ok=False quando a tabela não pôde ser lida (usa-se os fallbacks do código)."""
    ano = int(ano)
    try:
        df = session.sql("""
            SELECT CHAVE, ANO, MES, VALOR
            FROM SUPERSET.COMISSOES.CONFIG
        """).to_pandas()
    except Exception:
        return {int(m): {} for m in meses}, False
    linhas = [(str(r["CHAVE"]), int(r["ANO"]), int(r["MES"]),
               "" if r["VALOR"] is None else str(r["VALOR"]))
              for _, r in df.iterrows()]
    out = {}
    for m in meses:
        m = int(m)
        vig = {}
        for chave, a, mm, valor in linhas:
            if (a, mm) <= (ano, m):
                atual = vig.get(chave)
                if atual is None or (a, mm) >= atual[0]:
                    vig[chave] = ((a, mm), valor)
        out[m] = {k: v[1] for k, v in vig.items()}
    return out, True


def _config_mes(session, ano, mes):
    """Mini-contexto {config, config_ok} p/ uso fora do montar_contextos."""
    cfg, ok = carregar_config(session, ano, [mes])
    return {"config": cfg[int(mes)], "config_ok": ok}


def _cfg_f(ctx, chave, default):
    v = _f((ctx.get("config") or {}).get(chave))
    return v if v is not None else default


def _cfg_s(ctx, chave, default):
    v = (ctx.get("config") or {}).get(chave)
    return str(v) if v not in (None, "") else default


def _cfg_list(ctx, chave, default=None):
    v = (ctx.get("config") or {}).get(chave)
    if v in (None, ""):
        return default
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _gestor_equipes_cfg(ctx, email, equipe):
    """Equipes agregadas pelo gestor: da config quando legível; senão constante."""
    if ctx.get("config_ok"):
        eqs = _cfg_list(ctx, f"gestor_equipes.{email}", None)
        return eqs if eqs else [equipe]
    return GESTOR_EQUIPES_OVERRIDE.get(email, [equipe])


def _b2g_deals_cte_single(ano: int, mes: int, corte=400000) -> str:
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
        SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
        WHERE ANO = {ano} AND MES = {mes}
        GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < {corte}
    ),
    deals_ok AS (
        SELECT ID_NEGOCIO FROM deals_snap_b2g
        WHERE (SELECT COUNT(*) FROM fec_b2g) > 0
        UNION ALL
        SELECT ID_NEGOCIO FROM deals_live_b2g
        WHERE (SELECT COUNT(*) FROM fec_b2g) = 0
    )"""


def _b2g_deals_cte_multi(ano: int, mes_in_str: str, corte=400000) -> str:
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
        SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
        WHERE ANO = {ano} AND MES IN ({mes_in_str})
        GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < {corte}
    ),
    deals_ok_per_mes AS (
        SELECT ID_NEGOCIO, MES FROM deals_snap_b2g
        UNION ALL
        SELECT dl.ID_NEGOCIO, v.MES
        FROM deals_live_b2g dl
        JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
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
    _cfgx   = _config_mes(session, ano, mes)
    _corte  = _cfg_f(_cfgx, "corte_deal_grande", 400000)

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
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD
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
            WITH {_b2g_deals_cte_single(ano, mes, _corte)},
            cont_b2g AS (
                SELECT SPLIT_PART(NUMERO_DO_CONTRATO::VARCHAR, '.', 1) AS NUM_CONT,
                       MAX(TO_VARCHAR(ID_DO_CONTRATO)) AS ID_CONTRATO
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS
                WHERE NUMERO_DO_CONTRATO IS NOT NULL
                GROUP BY 1
            ),
            -- Link do cliente montado direto de CONTACTS (0-1) / COMPANIES (0-2):
            -- a LISTA_POTENCIAL_FARMER não cobre todos os clientes com venda.
            lk_cli AS (
                SELECT ID_CLI, MIN(LINK_CLIENTE) AS LINK_CLIENTE
                FROM (
                    SELECT SPLIT_PART("Id do contato"::VARCHAR, '.', 1) AS ID_CLI,
                           'https://app.hubspot.com/contacts/44552714/record/0-1/'
                               || SPLIT_PART("Id do contato"::VARCHAR, '.', 1) AS LINK_CLIENTE
                    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTACTS
                    WHERE "Id do contato" IS NOT NULL
                    UNION ALL
                    SELECT SPLIT_PART("Id da empresa"::VARCHAR, '.', 1),
                           'https://app.hubspot.com/contacts/44552714/record/0-2/'
                               || SPLIT_PART("Id da empresa"::VARCHAR, '.', 1)
                    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES
                    WHERE "Id da empresa" IS NOT NULL
                )
                GROUP BY ID_CLI
            ),
            -- Fallback quando a venda vem com CLIENTE='N/A': cliente pela
            -- associação do deal (empresa tem prioridade sobre contato).
            cli_assoc AS (
                SELECT ID_DEAL, NOME, LINK_CLIENTE
                FROM (
                    SELECT SPLIT_PART(a.ID_DEAL, '.', 1) AS ID_DEAL,
                           e."Nome" AS NOME,
                           'https://app.hubspot.com/contacts/44552714/record/0-2/'
                               || SPLIT_PART(a.ID_COMPANY, '.', 1) AS LINK_CLIENTE,
                           1 AS PRIORIDADE
                    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_COMPANIES_DEALS a
                    JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES e
                      ON SPLIT_PART(e."Id da empresa"::VARCHAR, '.', 1)
                       = SPLIT_PART(a.ID_COMPANY, '.', 1)
                    UNION ALL
                    SELECT SPLIT_PART(a.ID_DEAL, '.', 1),
                           c."Nome completo",
                           'https://app.hubspot.com/contacts/44552714/record/0-1/'
                               || SPLIT_PART(a.ID_CONTATO, '.', 1),
                           2
                    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTATO_DEALS a
                    JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTACTS c
                      ON SPLIT_PART(c."Id do contato"::VARCHAR, '.', 1)
                       = SPLIT_PART(a.ID_CONTATO, '.', 1)
                )
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ID_DEAL
                                           ORDER BY PRIORIDADE, NOME) = 1
            )
            SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, MAX(v.NOME_NEGOCIO) AS NOME_NEGOCIO,
                   CASE WHEN MAX(v.CLIENTE) IS NULL OR UPPER(MAX(v.CLIENTE)) IN ('N/A','NA')
                        THEN MAX(ca.NOME) ELSE MAX(v.CLIENTE) END AS CLIENTE,
                   COALESCE(MAX(l.LINK_CLIENTE), MAX(ca.LINK_CLIENTE)) AS LINK_CLIENTE,
                   SPLIT_PART(MAX(v.CONTRATO), '.', 1) AS NUM_CONTRATO,
                   MAX(cont_b2g.ID_CONTRATO) AS ID_CONTRATO,
                   MAX(v.PIPELINE) AS PIPELINE,
                   MAX(v.FORMA_DE_PAGAMENTO) AS FORMA_PAG,
                   TO_VARCHAR(MAX(v.FECHAMENTO_NEGOCIO), 'DD/MM/YYYY') AS DATA_FECH,
                   ROUND(SUM(v.BOOKING),2) AS BOOKING, ROUND(SUM(v.ARR),2) AS ARR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            LEFT JOIN lk_cli l
                   ON l.ID_CLI = SPLIT_PART(v.ID_DO_CLIENTE::VARCHAR, '.', 1)
            LEFT JOIN cli_assoc ca
                   ON ca.ID_DEAL = SPLIT_PART(v.ID_NEGOCIO::VARCHAR, '.', 1)
            LEFT JOIN cont_b2g
                   ON cont_b2g.NUM_CONT = SPLIT_PART(v.CONTRATO::VARCHAR, '.', 1)
            WHERE v.ANO={ano} AND v.MES={mes} AND {cond}
              AND v.ID_NEGOCIO IN (SELECT ID_NEGOCIO FROM deals_ok)
            GROUP BY {b2g_group}
            ORDER BY NEGOCIO
        """).to_pandas()

    # MRR / Saving
    if is_gestor:
        eqs = _gestor_equipes_cfg(_cfgx, email, equipe)
        ein = ", ".join("'" + str(e).replace("'", "''") + "'" for e in eqs)
        valor_expr   = _valor_sql_case('v', 'v.VERTICAL')
        where_clause = f"v.VERTICAL IN ({ein})"
        mrr_group    = "LOWER(v.CONSULTOR), v.ID_NEGOCIO"
    else:
        valor_expr   = _valor_sql_fixa(equipe, 'v')
        where_clause = f"LOWER(v.CONSULTOR) = '{email}'"
        mrr_group    = "v.ID_NEGOCIO"
    return session.sql(f"""
        WITH cont_mrr AS (
            SELECT SPLIT_PART(NUMERO_DO_CONTRATO::VARCHAR, '.', 1) AS NUM_CONT,
                   MAX(TO_VARCHAR(ID_DO_CONTRATO)) AS ID_CONTRATO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS
            WHERE NUMERO_DO_CONTRATO IS NOT NULL
            GROUP BY 1
        ),
        -- Link do cliente montado direto de CONTACTS (0-1) / COMPANIES (0-2):
        -- a LISTA_POTENCIAL_FARMER não cobre todos os clientes com venda.
        lk_cli AS (
            SELECT ID_CLI, MIN(LINK_CLIENTE) AS LINK_CLIENTE
            FROM (
                SELECT SPLIT_PART("Id do contato"::VARCHAR, '.', 1) AS ID_CLI,
                       'https://app.hubspot.com/contacts/44552714/record/0-1/'
                           || SPLIT_PART("Id do contato"::VARCHAR, '.', 1) AS LINK_CLIENTE
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTACTS
                WHERE "Id do contato" IS NOT NULL
                UNION ALL
                SELECT SPLIT_PART("Id da empresa"::VARCHAR, '.', 1),
                       'https://app.hubspot.com/contacts/44552714/record/0-2/'
                           || SPLIT_PART("Id da empresa"::VARCHAR, '.', 1)
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES
                WHERE "Id da empresa" IS NOT NULL
            )
            GROUP BY ID_CLI
        ),
        -- Fallback quando a venda vem com CLIENTE='N/A': cliente pela
        -- associação do deal (empresa tem prioridade sobre contato).
        cli_assoc AS (
            SELECT ID_DEAL, NOME, LINK_CLIENTE
            FROM (
                SELECT SPLIT_PART(a.ID_DEAL, '.', 1) AS ID_DEAL,
                       e."Nome" AS NOME,
                       'https://app.hubspot.com/contacts/44552714/record/0-2/'
                           || SPLIT_PART(a.ID_COMPANY, '.', 1) AS LINK_CLIENTE,
                       1 AS PRIORIDADE
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_COMPANIES_DEALS a
                JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES e
                  ON SPLIT_PART(e."Id da empresa"::VARCHAR, '.', 1)
                   = SPLIT_PART(a.ID_COMPANY, '.', 1)
                UNION ALL
                SELECT SPLIT_PART(a.ID_DEAL, '.', 1),
                       c."Nome completo",
                       'https://app.hubspot.com/contacts/44552714/record/0-1/'
                           || SPLIT_PART(a.ID_CONTATO, '.', 1),
                       2
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTATO_DEALS a
                JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTACTS c
                  ON SPLIT_PART(c."Id do contato"::VARCHAR, '.', 1)
                   = SPLIT_PART(a.ID_CONTATO, '.', 1)
            )
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ID_DEAL
                                       ORDER BY PRIORIDADE, NOME) = 1
        )
        SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, MAX(v.NOME_NEGOCIO) AS NOME_NEGOCIO,
               CASE WHEN MAX(v.CLIENTE) IS NULL OR UPPER(MAX(v.CLIENTE)) IN ('N/A','NA')
                    THEN MAX(ca.NOME) ELSE MAX(v.CLIENTE) END AS CLIENTE,
               COALESCE(MAX(l.LINK_CLIENTE), MAX(ca.LINK_CLIENTE)) AS LINK_CLIENTE,
               MAX(v.PIPELINE) AS PIPELINE,
               MAX(v.FORMA_DE_PAGAMENTO) AS FORMA_PAG,
               TO_VARCHAR(MAX(v.FECHAMENTO_NEGOCIO), 'DD/MM/YYYY') AS DATA_FECH,
               SPLIT_PART(MAX(v.CONTRATO), '.', 1) AS NUM_CONTRATO,
               MAX(cont_mrr.ID_CONTRATO) AS ID_CONTRATO,
               ROUND(SUM({valor_expr}), 2) AS VALOR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        LEFT JOIN lk_cli l
               ON l.ID_CLI = SPLIT_PART(v.ID_DO_CLIENTE::VARCHAR, '.', 1)
        LEFT JOIN cli_assoc ca
               ON ca.ID_DEAL = SPLIT_PART(v.ID_NEGOCIO::VARCHAR, '.', 1)
        LEFT JOIN cont_mrr
               ON cont_mrr.NUM_CONT = SPLIT_PART(v.CONTRATO::VARCHAR, '.', 1)
        WHERE v.ANO={ano} AND v.MES={mes} AND {where_clause}
        GROUP BY {mrr_group}
        ORDER BY NEGOCIO
    """).to_pandas()


def composicao_booking_extra(session, email, ano, mes, equipe, is_gestor):
    """Retorna itens individuais (nível de produto) de Implantação/Serviço/Curso com MRR=0."""
    email = str(email).strip().lower().replace("'", "''")
    _cfgx  = _config_mes(session, ano, mes)
    _corte = _cfg_f(_cfgx, "corte_deal_grande", 400000)
    _cats  = _cfg_list(_cfgx, "categorias_booking_extra",
                       ["Implantação", "Serviço", "Curso"])
    cats_in = ", ".join("'" + str(c).replace("'", "''") + "'" for c in _cats)

    if is_gestor:
        eqs = _gestor_equipes_cfg(_cfgx, email, equipe)
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
            SELECT ID_NEGOCIO FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO={ano} AND MES={mes} GROUP BY ID_NEGOCIO HAVING SUM(BOOKING) < {_corte}
        )
        SELECT {cons_col}v.ID_NEGOCIO AS NEGOCIO, v.CLIENTE AS CLIENTE,
               v.ITEM_DE_LINHA AS PRODUTO, v.PIPELINE AS PIPELINE,
               v.FORMA_DE_PAGAMENTO AS FORMA_PAG, ROUND(v.BOOKING, 2) AS BOOKING
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO
        WHERE v.ANO={ano} AND v.MES={mes} AND {where_clause}
          AND v.CATEGORIA_DO_ITEM IN ({cats_in})
          AND COALESCE(v.MRR, 0) = 0
        ORDER BY NEGOCIO, PRODUTO
    """).to_pandas()


def _calcular_comissao_canc_recovery(ctx, email, pr) -> dict:
    """Cálculo simplificado para consultoras de recuperação de cancelamento (sem OTE)."""
    cargo     = str(pr.get("CARGO") or "")
    is_gestor = bool(pr.get("IS_GESTOR") or False)
    pct_canc  = _f(pr.get("PERCENTUAL_CANC_RECOVERY"),
                   _cfg_f(ctx, "pct_canc_recovery_default", 0.02))

    valor_recuperado, mrr_recuperado = ctx["canc"].get(email, (0.0, 0.0))
    comissao_canc = round(valor_recuperado * pct_canc, 2)

    # Booking das vendas/renovações diretas: lê de vendas_mes (presente no contexto
    # desde sempre) em vez de canc_renovacoes, para funcionar mesmo com cache antigo.
    _vm = ctx.get("vendas_mes")
    if _vm is not None and not _vm.empty and "CONS_L" in _vm.columns:
        _mask = _vm["CONS_L"] == email
        booking_renovacoes = _f(float(_vm.loc[_mask, "BOOKING"].sum()), 0.0) or 0.0
    else:
        booking_renovacoes = _f(ctx.get("canc_renovacoes", {}).get(email), 0.0) or 0.0
    comissao_renovacoes = round(booking_renovacoes * pct_canc, 2)

    return {
        "is_canc_recovery":          True,
        "equipe":                    "Cancelamento",
        "cargo":                     cargo,
        "meta_mrr":                  0.0,
        "desconto":                  0.0,
        "realizado":                 0.0,
        "pct_atingido":              0.0,
        "ote_cheio":                 None,
        "ote_02_cheio":              None,
        "ote_prop":                  None,
        "ote_02_prop":               None,
        "ote_base":                  None,
        "ote_tier":                  1,
        "cliff_ote_01":              0,
        "cliff_ote_02":              None,
        "cliff_acel_01":             0,
        "mult_acel_01":              1.0,
        "cliff_acel_02":             None,
        "mult_acel_02":              None,
        "acelerador":                0.0,
        "acel_desc":                 "",
        "ote_ajustado":              None,
        "mrr_avista":                0.0,
        "mrr_cc3x":                  0.0,
        "mrr_cc12x":                 0.0,
        "mrr_recorrente":            0.0,
        "mult_avista":               1.0,
        "mult_cc3x":                 1.0,
        "mult_cc12x":                1.0,
        "mult_recorrente":           1.0,
        "ote_variavel":              0.0,
        "booking_extras":            0.0,
        "pct_bk_extra":              0.0,
        "comissao_bk_extra":         0.0,
        "is_saving":                 False,
        "is_gd":                     False,
        "is_b2g":                    False,
        "faixa_atingida":            None,
        "proxima_faixa":             None,
        "dividas_pagas":             0.0,
        "comissao_dividas":          0.0,
        "pct_protecao":              0.0,
        "bonificacao_protecao":      0.0,
        "ajuste_total":              0.0,
        "ajuste_n":                  0,
        "total":                     comissao_canc + comissao_renovacoes,
        "is_gestor":                 is_gestor,
        "ote_indisponivel":          False,
        "trim":                      None,
        "valor_recuperado":          valor_recuperado,
        "mrr_recuperado":            mrr_recuperado,
        "comissao_canc_recovery":    comissao_canc,
        "pct_canc_recovery":         pct_canc,
        "booking_renovacoes_canc":   booking_renovacoes,
        "comissao_renovacoes_canc":  comissao_renovacoes,
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
            cc.ANO, cc.MES,
            cc.EMAIL               AS CONSULTORA,
            cc.ID_NEGOCIO          AS NEGOCIO,
            d.NOME_NEGOCIO,
            SPLIT_PART(cc.NUMERO_CONTRATO::VARCHAR, '.', 1) AS CONTRATO,
            cont.ID_CONTRATO,
            TO_VARCHAR(cc.DATA_FECHAMENTO, 'DD/MM/YYYY') AS DATA_FECHAMENTO,
            TO_VARCHAR(cc.DATA_INICIO,    'DD/MM/YYYY') AS DATA_INICIO,
            TO_VARCHAR(cc.DATA_RENOVACAO, 'DD/MM/YYYY') AS DATA_RENOVACAO,
            cc.VALOR_ORIGINAL,
            cc.VALOR_AJUSTADO
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS cc
        LEFT JOIN (
            SELECT TO_VARCHAR("Id do negócio") AS ID_NEG,
                   MAX("Nome do negócio")       AS NOME_NEGOCIO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS
            GROUP BY 1
        ) d ON d.ID_NEG = TO_VARCHAR(cc.ID_NEGOCIO)
        LEFT JOIN (
            SELECT SPLIT_PART(NUMERO_DO_CONTRATO::VARCHAR, '.', 1) AS NUM_CONT,
                   MAX(TO_VARCHAR(ID_DO_CONTRATO))                  AS ID_CONTRATO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS
            WHERE NUMERO_DO_CONTRATO IS NOT NULL
            GROUP BY 1
        ) cont ON cont.NUM_CONT = SPLIT_PART(cc.NUMERO_CONTRATO::VARCHAR, '.', 1)
        WHERE cc.ANO = {ano} AND cc.MES = {mes} AND LOWER(cc.EMAIL) = '{email}'
          -- A tabela ouro cobre todas as consultoras do pipeline de cancelamento
          -- (inclui Saving); o flag IS_CANC_RECOVERY preserva o recorte da equipe
          -- Cancelamento que a view legada aplicava por e-mail hardcoded.
          AND EXISTS (
              SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS p
              WHERE p.ANO = cc.ANO AND p.MES = cc.MES
                AND LOWER(p.EMAIL) = LOWER(cc.EMAIL)
                AND p.IS_CANC_RECOVERY = TRUE
          )
        ORDER BY cc.ID_NEGOCIO
    """).to_pandas()


def composicao_renovacoes_canc(session, email, ano, mes):
    """Renovações/vendas diretas das consultoras de cancelamento no período.

    Valor base da comissão = BOOKING (valor integral da venda), distinto da
    recuperação de cancelamentos que usa VALOR_AJUSTADO proporcional ao período restante."""
    email = str(email).strip().lower().replace("'", "''")
    return session.sql(f"""
        SELECT v.ID_NEGOCIO AS NEGOCIO,
               MAX(v.NOME_NEGOCIO)                                        AS NOME_NEGOCIO,
               MAX(v.CLIENTE)                                             AS CLIENTE,
               MAX(l.LINK_CLIENTE)                                        AS LINK_CLIENTE,
               SPLIT_PART(MAX(v.CONTRATO), '.', 1)                       AS CONTRATO,
               MAX(cont.ID_CONTRATO)                                      AS ID_CONTRATO,
               MAX(v.PIPELINE)                                            AS PIPELINE,
               MAX(v.FORMA_DE_PAGAMENTO)                                  AS FORMA_PAG,
               TO_VARCHAR(MAX(v.FECHAMENTO_NEGOCIO), 'DD/MM/YYYY')        AS DATA_FECH,
               ROUND(SUM(v.MRR), 2)                                       AS MRR,
               ROUND(SUM(v.BOOKING), 2)                                   AS BOOKING
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
               ON SPLIT_PART(l.ID_CLIENTE::VARCHAR, '.', 1)
                = SPLIT_PART(v.ID_DO_CLIENTE::VARCHAR, '.', 1)
        LEFT JOIN (
            SELECT SPLIT_PART(NUMERO_DO_CONTRATO::VARCHAR, '.', 1) AS NUM_CONT,
                   MAX(TO_VARCHAR(ID_DO_CONTRATO))                  AS ID_CONTRATO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS
            WHERE NUMERO_DO_CONTRATO IS NOT NULL
            GROUP BY 1
        ) cont ON cont.NUM_CONT = SPLIT_PART(v.CONTRATO::VARCHAR, '.', 1)
        WHERE v.ANO = {ano} AND v.MES = {mes}
          AND LOWER(v.CONSULTOR) = '{email}'
        GROUP BY v.ID_NEGOCIO
        ORDER BY BOOKING DESC
    """).to_pandas()


# ══ Contexto em lote ═══════════════════════════════════════════════════════════
# montar_contexto busca, em ~15 queries por (ano, mes), tudo que calcular_comissao
# precisa para QUALQUER pessoa do mês. O cálculo em si lê apenas do contexto —
# assim Minha Equipe / Exportar / fechamento pagam o custo do banco uma vez por
# mês, não uma vez por pessoa. Cacheado em connection.get_contexto_cached.

def _map1(df, key, cols=None):
    """{key_lower: primeira_linha} — replica o iloc[0] das queries por pessoa."""
    out = {}
    if df is None or df.empty:
        return out
    for _, r in df.iterrows():
        k = str(r[key])
        if k not in out:
            out[k] = r if cols is None else {c: r[c] for c in cols}
    return out


def _lote_pandas(session, consultas: dict) -> dict:
    """{chave: sql} -> {chave: DataFrame}, disparando as queries de uma vez.

    Usa o modo assíncrono do Snowpark (to_pandas(block=False)): as queries
    correm em paralelo no warehouse e o tempo do lote vira ~o da query mais
    lenta, não a soma (14/08/2026 — a primeira carga de um mês caía de ~12s).
    Qualquer falha (Snowpark antigo sem block=False, erro na coleta, retorno
    inesperado) derruba o LOTE INTEIRO para o caminho sequencial, idêntico ao
    comportamento original; as queries são leituras idempotentes."""
    try:
        jobs = {k: session.sql(q).to_pandas(block=False)
                for k, q in consultas.items()}
        out = {}
        for k, job in jobs.items():
            df = job.result()
            if not isinstance(df, pd.DataFrame):
                raise TypeError("resultado assíncrono não é DataFrame")
            out[k] = df
        return out
    except Exception:
        return {k: session.sql(q).to_pandas() for k, q in consultas.items()}


def montar_contextos(session, ano: int, meses) -> dict:
    """Contextos de vários meses do MESMO ano em uma única passada de queries.

    Retorna {mes: ctx}. Cada query cobre todos os meses pedidos (MES IN ...),
    então o histórico de 4 meses paga ~15 round-trips no total, não por mês.
    As queries são disparadas em paralelo via _lote_pandas."""
    ano = int(ano)
    meses = sorted({int(m) for m in meses})
    m_in = ",".join(str(m) for m in meses)
    ctxs = {m: {"ano": ano, "mes": m,
                "params": {}, "metas": {}, "otes": {}, "ri_metas": {},
                "gd_opps": {}, "gd_override": {}, "rls_teams": {},
                "b2g_real": {}, "patamares": {}, "ponderacoes": {},
                "acel_fp": {}, "dividas": {}, "ajustes": {}, "canc": {},
                "canc_renovacoes": {}, "am": {}}
            for m in meses}

    def _dist(df, destino, key_col, val=None):
        """Distribui linhas por MES; primeira linha vence por chave (iloc[0])."""
        for _, r in df.iterrows():
            d = ctxs[int(r["MES"])][destino]
            k = str(r[key_col])
            if k not in d:
                d[k] = r if val is None else r[val]

    # Config administrável (vigência por mês)
    cfg_por_mes, cfg_ok = carregar_config(session, ano, meses)
    for m in meses:
        ctxs[m]["config"] = cfg_por_mes.get(m, {})
        ctxs[m]["config_ok"] = cfg_ok
    _cortes = {m: _cfg_f(ctxs[m], "corte_deal_grande", 400000) for m in meses}
    if len(set(_cortes.values())) == 1:
        corte_expr = str(list(_cortes.values())[0])
    else:  # corte mudou dentro da janela: aplica o vigente de cada mês
        corte_expr = ("CASE MES " +
                      " ".join(f"WHEN {m} THEN {_cortes[m]}" for m in meses) + " END")
    corte_ult = _cortes[max(meses)]

    # As queries abaixo são independentes entre si (dependem só da config,
    # já resolvida acima): dispara todas de uma vez via _lote_pandas.
    _q = {}
    _q["params"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L, CARGO, IS_GESTOR,
               CLIFF_OTE_01, CLIFF_OTE_02,
               CLIFF_ACELERADOR_01, MULT_ACELERADOR_01,
               CLIFF_ACELERADOR_02, MULT_ACELERADOR_02,
               PERCENTUAL_BOOKING_EXTRA,
               OTE_01_CHEIO, OTE_02_CHEIO,
               IS_CANC_RECOVERY, PERCENTUAL_CANC_RECOVERY,
               PERCENTUAL_PROTECAO,
               COALESCE(IS_TRIM_HABILITADO, TRUE) AS IS_TRIM_HABILITADO
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["metas"] = f"""
        SELECT MES, LOWER(CONSULTOR) AS EMAIL_L, META_MRR, META_OTR,
               PERCENTUAL_DESCONTO_METAS, EQUIPE
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES IN ({m_in}) AND CONSULTOR IS NOT NULL
    """
    _q["otes"] = f"""
        SELECT MES, UPPER(CARGO) AS CARGO_U, OTE
        FROM SUPERSET.COMISSOES.CARGOS_OTES
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["ri_metas"] = f"""
        SELECT rigot.MONTH AS MES, LOWER(rio.EMAIL) AS EMAIL_L,
               COALESCE(rigot.TARGET_QUALIFIED, 0) AS META
        FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
        JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
          ON rio.ID = rigot.OWNER_ID
        WHERE rigot.YEAR = {ano} AND rigot.MONTH IN ({m_in})
    """
    _q["gd_opps"] = f"""
        SELECT MONTH(DATA_QUALIFICACAO) AS MES,
               LOWER(PROPRIETARIO) AS EMAIL_L, COUNT(DISTINCT ID_CONTATO) AS OPPS
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD
        WHERE YEAR(DATA_QUALIFICACAO) = {ano} AND MONTH(DATA_QUALIFICACAO) IN ({m_in})
        GROUP BY 1, 2
    """
    _q["gd_override"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L, REALIZADO_MANUAL
        FROM SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["rls"] = f"""
        SELECT DISTINCT MES, LOWER(USUARIOEMAIL) AS U, LOWER(CONSULTOREMAIL) AS C
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano} AND MES IN ({m_in}) AND CONSULTOREMAIL IS NOT NULL
    """
    # Vendas (nível de item, filtro 400k ao vivo por mês) — modelo MRR/Saving
    _q["vendas"] = f"""
        WITH deals_ok AS (
            SELECT ID_NEGOCIO, MES FROM (
                SELECT ID_NEGOCIO, MES, SUM(BOOKING) AS BK
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
                WHERE ANO = {ano} AND MES IN ({m_in})
                GROUP BY ID_NEGOCIO, MES
            ) WHERE BK < {corte_expr}
            UNION
            SELECT DISTINCT v.ID_NEGOCIO, v.MES
            FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K d
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
              ON v.ID_NEGOCIO = d.ID_NEGOCIO
            WHERE v.ANO = {ano} AND v.MES IN ({m_in})
        )
        SELECT v.MES, LOWER(v.CONSULTOR) AS CONS_L, v.VERTICAL,
               v.MRR, v.NMRR, v.MRR_EXPANSAO, v.BOOKING,
               v.FORMA_DE_PAGAMENTO, v.PARCELAS, v.CATEGORIA_DO_ITEM
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        JOIN deals_ok d ON d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES
        WHERE v.ANO = {ano} AND v.MES IN ({m_in})
    """
    # B2G: ARR/Booking por consultor/mês (filtro 400k snapshot-aware)
    _q["b2g_real"] = f"""
        WITH {_b2g_deals_cte_multi(ano, m_in, corte_ult)}
        SELECT v.MES, LOWER(v.CONSULTOR) AS EMAIL_L,
               COALESCE(SUM(v.ARR), 0) AS ARR, COALESCE(SUM(v.BOOKING), 0) AS BK
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
        WHERE v.ANO = {ano} AND v.MES IN ({m_in})
          AND EXISTS (SELECT 1 FROM deals_ok_per_mes d
                      WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
        GROUP BY 1, 2
    """
    _q["patamares"] = f"""
        SELECT MES, EQUIPE, PATAMAR, PERCENTUAL
        FROM SUPERSET.COMISSOES.PATAMARES_COMISSAO
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["ponderacoes"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L, TIPO_META, PONDERACAO
        FROM SUPERSET.COMISSOES.PONDERACOES_META
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["acel_fp"] = f"""
        SELECT MES, EQUIPE, A_VISTA, CC_ATE_3X, CC_ATE_12X, RECORRENTE
        FROM SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["dividas"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L, COALESCE(VALOR, 0) AS VALOR, PERCENTUAL_COMISSAO
        FROM SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS
        WHERE ANO = {ano} AND MES IN ({m_in})
    """
    _q["ajustes"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L, COALESCE(SUM(VALOR), 0) AS TOTAL, COUNT(*) AS N
        FROM SUPERSET.COMISSOES.AJUSTES_PONTUAIS
        WHERE ANO = {ano} AND MES IN ({m_in})
        GROUP BY 1, 2
    """
    _q["canc"] = f"""
        SELECT MES, LOWER(EMAIL) AS EMAIL_L,
               COALESCE(SUM(VALOR_AJUSTADO), 0) AS TOTAL_VALOR,
               COALESCE(SUM(VALOR_ORIGINAL / NULLIF(DATEDIFF('month', DATA_INICIO, DATA_RENOVACAO), 0)), 0) AS TOTAL_MRR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS cc
        WHERE ANO = {ano} AND MES IN ({m_in})
          -- Recorte da equipe Cancelamento via IS_CANC_RECOVERY (ver nota acima).
          AND EXISTS (
              SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS p
              WHERE p.ANO = cc.ANO AND p.MES = cc.MES
                AND LOWER(p.EMAIL) = LOWER(cc.EMAIL)
                AND p.IS_CANC_RECOVERY = TRUE
          )
        GROUP BY 1, 2
    """
    _r = _lote_pandas(session, _q)

    _dist(_r["params"], "params", "EMAIL_L")
    _dist(_r["metas"], "metas", "EMAIL_L")
    _dist(_r["otes"], "otes", "CARGO_U", val="OTE")
    _dist(_r["ri_metas"], "ri_metas", "EMAIL_L", val="META")
    _dist(_r["gd_opps"], "gd_opps", "EMAIL_L", val="OPPS")
    _dist(_r["gd_override"], "gd_override", "EMAIL_L", val="REALIZADO_MANUAL")

    for _, r in _r["rls"].iterrows():
        ctxs[int(r["MES"])]["rls_teams"].setdefault(str(r["U"]), []).append(str(r["C"]))

    vm_df = _r["vendas"]
    for m in meses:
        ctxs[m]["vendas_mes"] = vm_df[vm_df["MES"] == m]

    _dist(_r["b2g_real"], "b2g_real", "EMAIL_L")

    for _, r in _r["patamares"].iterrows():
        ctxs[int(r["MES"])]["patamares"].setdefault(str(r["EQUIPE"]), []).append(
            (_f(r["PATAMAR"], 0), _f(r["PERCENTUAL"])))

    for _, r in _r["ponderacoes"].iterrows():
        ctxs[int(r["MES"])]["ponderacoes"].setdefault(
            str(r["EMAIL_L"]), {})[r["TIPO_META"]] = _f(r["PONDERACAO"], 0)

    _dist(_r["acel_fp"], "acel_fp", "EQUIPE")
    _dist(_r["dividas"], "dividas", "EMAIL_L")

    for _, r in _r["ajustes"].iterrows():
        ctxs[int(r["MES"])]["ajustes"][str(r["EMAIL_L"])] = (_f(r["TOTAL"], 0), int(r["N"]))

    for _, r in _r["canc"].iterrows():
        ctxs[int(r["MES"])]["canc"][str(r["EMAIL_L"])] = (
            _f(r["TOTAL_VALOR"], 0), _f(r["TOTAL_MRR"], 0))

    # Vendas (renovações) das consultoras de cancelamento — BOOKING integral.
    # Distinto de CONSULTA_CANCELAMENTOS, que usa valor proporcional ao período restante.
    for m in meses:
        canc_emails = {e for e, row in ctxs[m]["params"].items()
                       if bool(row.get("IS_CANC_RECOVERY") or False)}
        vm_m = ctxs[m].get("vendas_mes", pd.DataFrame())
        if canc_emails and not vm_m.empty and "CONS_L" in vm_m.columns:
            cv = vm_m[vm_m["CONS_L"].isin(canc_emails)]
            ctxs[m]["canc_renovacoes"] = {
                em: _f(float(grp["BOOKING"].sum()), 0) or 0.0
                for em, grp in cv.groupby("CONS_L")
            }
        else:
            ctxs[m]["canc_renovacoes"] = {}

    # ── Trimestral (somente meses 3/6/9/12) ──────────────────────────────────
    for mes in [m for m in meses if m in (3, 6, 9, 12)]:
        ctx = ctxs[mes]
        q_meses = [mes - 2, mes - 1, mes]
        q_str = ",".join(str(m) for m in q_meses)

        # As 9 queries do trimestre também são independentes — mesmo lote.
        _qt = {}
        _qt["mt"] = f"""
            SELECT LOWER(CONSULTOR) AS EMAIL_L, MES, META_MRR, META_OTR, EQUIPE
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = {ano} AND MES IN ({q_str}) AND CONSULTOR IS NOT NULL
        """
        _qt["pt"] = f"""
            SELECT LOWER(EMAIL) AS EMAIL_L, MES, IS_GESTOR
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES IN ({q_str})
        """
        _qt["ri"] = f"""
            SELECT LOWER(rio.EMAIL) AS EMAIL_L, rigot.MONTH AS MES,
                   COALESCE(rigot.TARGET_QUALIFIED, 0) AS META
            FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_GD_OWNER_TARGETS rigot
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = rigot.OWNER_ID
            WHERE rigot.YEAR = {ano} AND rigot.MONTH IN ({q_str})
        """
        _qt["go"] = f"""
            SELECT LOWER(PROPRIETARIO) AS EMAIL_L, MONTH(DATA_QUALIFICACAO) AS MES,
                   COUNT(DISTINCT ID_CONTATO) AS OPPS
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD
            WHERE YEAR(DATA_QUALIFICACAO) = {ano} AND MONTH(DATA_QUALIFICACAO) IN ({q_str})
            GROUP BY 1, 2
        """
        _qt["gv"] = f"""
            SELECT LOWER(EMAIL) AS EMAIL_L, MES, REALIZADO_MANUAL
            FROM SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE
            WHERE ANO = {ano} AND MES IN ({q_str})
        """
        _qt["rt"] = f"""
            SELECT DISTINCT LOWER(USUARIOEMAIL) AS U, MES, LOWER(CONSULTOREMAIL) AS C
            FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE ANO = {ano} AND MES IN ({q_str}) AND CONSULTOREMAIL IS NOT NULL
        """
        _qt["vc"] = f"""
            SELECT LOWER(CONSULTOR) AS EMAIL_L, MES,
                   COALESCE(SUM(MRR), 0) AS S_MRR,
                   COALESCE(SUM(NMRR), 0) AS S_NMRR,
                   COALESCE(SUM(MRR_EXPANSAO), 0) AS S_EXP
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({q_str})
            GROUP BY 1, 2
        """
        _qt["vv"] = f"""
            SELECT VERTICAL,
                   COALESCE(SUM(MRR), 0) AS S_MRR,
                   COALESCE(SUM(NMRR), 0) AS S_NMRR,
                   COALESCE(SUM(MRR_EXPANSAO), 0) AS S_EXP
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            WHERE ANO = {ano} AND MES IN ({q_str})
            GROUP BY 1
        """
        _qt["bt"] = f"""
            WITH {_b2g_deals_cte_multi(ano, q_str, _cfg_f(ctx, "corte_deal_grande", 400000))}
            SELECT LOWER(v.CONSULTOR) AS EMAIL_L, v.MES,
                   COALESCE(SUM(v.ARR), 0) AS ARR, COALESCE(SUM(v.BOOKING), 0) AS BK
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM v
            WHERE v.ANO = {ano} AND v.MES IN ({q_str})
              AND EXISTS (SELECT 1 FROM deals_ok_per_mes d
                          WHERE d.ID_NEGOCIO = v.ID_NEGOCIO AND d.MES = v.MES)
            GROUP BY 1, 2
        """
        _rt = _lote_pandas(session, _qt)

        metas_tri = {}
        for _, r in _rt["mt"].iterrows():
            metas_tri.setdefault((str(r["EMAIL_L"]), int(r["MES"])), r)
        ctx["metas_tri"] = metas_tri

        ctx["params_tri"] = {(str(r["EMAIL_L"]), int(r["MES"])): bool(r["IS_GESTOR"])
                             for _, r in _rt["pt"].iterrows()}

        ri_tri = {}
        for _, r in _rt["ri"].iterrows():
            ri_tri.setdefault((str(r["EMAIL_L"]), int(r["MES"])), _f(r["META"], 0))
        ctx["ri_tri"] = ri_tri

        ctx["gd_opps_tri"] = {(str(r["EMAIL_L"]), int(r["MES"])): r["OPPS"]
                              for _, r in _rt["go"].iterrows()}

        ctx["gd_ov_tri"] = {(str(r["EMAIL_L"]), int(r["MES"])): r["REALIZADO_MANUAL"]
                            for _, r in _rt["gv"].iterrows()}

        rls_tri = {}
        for _, r in _rt["rt"].iterrows():
            rls_tri.setdefault((str(r["U"]), int(r["MES"])), []).append(str(r["C"]))
        ctx["rls_tri"] = rls_tri

        ctx["vendas_tri_cons"] = {
            (str(r["EMAIL_L"]), int(r["MES"])):
                (_f(r["S_MRR"], 0), _f(r["S_NMRR"], 0), _f(r["S_EXP"], 0))
            for _, r in _rt["vc"].iterrows()
        }

        ctx["vendas_tri_vert"] = {
            str(r["VERTICAL"]): (_f(r["S_MRR"], 0), _f(r["S_NMRR"], 0), _f(r["S_EXP"], 0))
            for _, r in _rt["vv"].iterrows()
        }

        ctx["b2g_real_tri"] = {
            (str(r["EMAIL_L"]), int(r["MES"])): (_f(r["ARR"], 0), _f(r["BK"], 0))
            for _, r in _rt["bt"].iterrows()
        }

    # ── Account Manager (NRR): 1 query por mês AM, meses em lote (ago/2026+) ─
    _q_am = {m: _am_sql(ano, m) for m in meses if (ano, m) >= AM_DESDE}
    if _q_am:
        _r_am = _lote_pandas(session, _q_am)
        for m, _df_am in _r_am.items():
            _am_processar(_df_am, ctxs[m])

    return ctxs


def _am_sql(ano, mes):
    """SQL única com as 5 medidas de NRR do mês, numa passada só das CTEs.

    As CTEs de movimentação (_am_movimentacoes_ctes) são o custo dominante e
    o Snowflake NÃO as reaproveita entre queries separadas: no formato antigo
    (5 queries) a classificação de contratos era recomputada 4 vezes. Aqui as
    medidas saem por UNION ALL com colunas padronizadas e a coluna MEDIDA
    identifica cada bloco (14/08/2026)."""
    m1, m2 = _am_datas(ano, mes)
    corte = f"LEAST(CURRENT_DATE, DATEADD(day, -1, {m2}))"
    return f"""
        WITH {_am_movimentacoes_ctes(m1, m2, corte)}
        -- 1. MRR Inicial: contratos da carteira vigentes no dia 1º do mês
        SELECT 'inicial' AS MEDIDA, GERENTE,
               COUNT(DISTINCT CONTRATO) AS N, SUM(MRR) AS MRR,
               NULL AS DELTA, NULL AS MRR_ANTERIOR, NULL AS MRR_NOVO,
               NULL AS N_NOVOS, NULL AS MRR_NOVOS, NULL AS N_UPSELLS,
               NULL AS MRR_UPSELLS, NULL AS UPS_MRR_ANTERIOR, NULL AS UPS_MRR_NOVO
        FROM cc
        WHERE {_am_cond_inicial(m1)}
        GROUP BY 1, 2
        UNION ALL
        -- 2. Novos negócios (MRR cheio) e upsells de substituição (delta)
        SELECT 'movs', GERENTE,
               NULL, NULL, NULL, NULL, NULL,
               COUNT(DISTINCT IFF(TIPO = 'Novo negócio', CONTRATO, NULL)),
               SUM(IFF(TIPO = 'Novo negócio', MRR, 0)),
               COUNT(DISTINCT IFF(TIPO <> 'Novo negócio', CONTRATO, NULL)),
               SUM(IFF(TIPO <> 'Novo negócio', MRR, 0)),
               SUM(IFF(TIPO <> 'Novo negócio', MRR_ANTERIOR, 0)),
               SUM(IFF(TIPO <> 'Novo negócio', MRR_NOVO, 0))
        FROM upsells_contrato
        GROUP BY 1, 2
        UNION ALL
        -- 3. Renovações, inclusive RAUT: novo MRR menos o substituído
        SELECT 'renov', GERENTE,
               COUNT(DISTINCT CONTRATO_ANTERIOR), NULL,
               SUM(MRR_NOVO - MRR_ANTERIOR), SUM(MRR_ANTERIOR), SUM(MRR_NOVO),
               NULL, NULL, NULL, NULL, NULL, NULL
        FROM renovacoes_contrato
        GROUP BY 1, 2
        UNION ALL
        -- 4. Impulsos: origens consolidadas num único contrato novo
        SELECT 'impulso', GERENTE,
               COUNT(DISTINCT CONTRATO_NOVO), NULL,
               SUM(MRR_NOVO - MRR_ANTERIOR), SUM(MRR_ANTERIOR), SUM(MRR_NOVO),
               NULL, NULL, NULL, NULL, NULL, NULL
        FROM impulsos_contrato
        GROUP BY 1, 2
        UNION ALL
        -- 5. Churn: contratos iniciais encerrados sem substituição
        SELECT 'churn', GERENTE,
               COUNT(DISTINCT CONTRATO), SUM(MRR),
               NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
        FROM cc
        WHERE INI < {m1} AND REN >= {m1}
          AND STATUS = 'Inativo'
          AND DESATIV >= {m1} AND DESATIV <= {corte}
          AND NOT EXISTS (
              SELECT 1
              FROM contratos_substituidos substituido
              WHERE substituido.CONTRATO = cc.CONTRATO
          )
        GROUP BY 1, 2
    """


def _am_processar(df, ctx):
    """Popula ctx['am'][gerente] a partir do resultado de _am_sql."""
    am = {}

    def _acum(email, campo, valor, n_campo=None, n=0):
        d = am.setdefault(str(email).lower(), {
            "mrr_inicial": 0.0, "n_inicial": 0,
            "novos_negocios": 0.0, "n_novos_negocios": 0,
            "upsells": 0.0, "n_upsells": 0,
            "upsells_mrr_anterior": 0.0, "upsells_mrr_novo": 0.0,
            "renovacoes_delta": 0.0, "renovacoes_contratos": 0,
            "renovacoes_mrr_anterior": 0.0, "renovacoes_mrr_novo": 0.0,
            "impulsos_delta": 0.0, "impulsos_contratos": 0,
            "impulsos_mrr_anterior": 0.0, "impulsos_mrr_novo": 0.0,
            "churn_mrr": 0.0, "churn_clientes": 0,
        })
        d[campo] = _f(valor, 0) or 0.0
        if n_campo:
            d[n_campo] = int(n or 0)

    for _, r in df.iterrows():
        medida = str(r["MEDIDA"])
        if medida == "inicial":
            _acum(r["GERENTE"], "mrr_inicial", r["MRR"], "n_inicial", r["N"])
        elif medida == "movs":
            _acum(r["GERENTE"], "novos_negocios", r["MRR_NOVOS"], "n_novos_negocios", r["N_NOVOS"])
            _acum(r["GERENTE"], "upsells", r["MRR_UPSELLS"], "n_upsells", r["N_UPSELLS"])
            _acum(r["GERENTE"], "upsells_mrr_anterior", r["UPS_MRR_ANTERIOR"])
            _acum(r["GERENTE"], "upsells_mrr_novo", r["UPS_MRR_NOVO"])
        elif medida == "renov":
            _acum(r["GERENTE"], "renovacoes_delta", r["DELTA"], "renovacoes_contratos", r["N"])
            _acum(r["GERENTE"], "renovacoes_mrr_anterior", r["MRR_ANTERIOR"])
            _acum(r["GERENTE"], "renovacoes_mrr_novo", r["MRR_NOVO"])
        elif medida == "impulso":
            _acum(r["GERENTE"], "impulsos_delta", r["DELTA"], "impulsos_contratos", r["N"])
            _acum(r["GERENTE"], "impulsos_mrr_anterior", r["MRR_ANTERIOR"])
            _acum(r["GERENTE"], "impulsos_mrr_novo", r["MRR_NOVO"])
        elif medida == "churn":
            _acum(r["GERENTE"], "churn_mrr", r["MRR"], "churn_clientes", r["N"])

    ctx["am"] = am


def montar_contexto(session, ano: int, mes: int) -> dict:
    """Contexto em lote de um único (ano, mes) — atalho de montar_contextos."""
    return montar_contextos(session, ano, [mes])[int(mes)]


def _valor_tri(sums, equipe):
    """Valor de realizado a partir de (S_MRR, S_NMRR, S_EXP) conforme a equipe."""
    if sums is None:
        return 0.0
    idx = {"MRR": 0, "NMRR": 1, "MRR_EXPANSAO": 2}
    cols = REALIZADO_COLUNAS.get(str(equipe), ["MRR"])
    return sum(_f(sums[idx[c]], 0) or 0 for c in cols)


def _gd_val(ctx, email, m):
    """COALESCE(override, opps) de GD para (email, mes) — None se sem opps no mes."""
    if (email, m) not in ctx["gd_opps_tri"]:
        return None
    ov = _f(ctx["gd_ov_tri"].get((email, m)))
    return ov if ov is not None else (_f(ctx["gd_opps_tri"][(email, m)], 0) or 0)


def _membros_equipe_tri(ctx, equipe, m):
    """Consultores (nao-gestores) da equipe no mes m, via METAS+PARAMETROS."""
    eq = str(equipe)
    return [e for (e, mm), row in ctx["metas_tri"].items()
            if mm == m and str(row["EQUIPE"] or "") == eq
            and ctx["params_tri"].get((e, mm)) is False]


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


# ══ Cálculo por modelo ═══════════════════════════════════════════════════════
# calcular_comissao é um despachante fino: resolve a base comum (_base_comissao:
# meta, parâmetros, OTE) e delega ao modelo — _calcular_gd / _calcular_b2g /
# _calcular_saving / _calcular_mrr (canc-recovery já tem função própria).
# Cada modelo devolve um dict parcial; _montar_resultado completa com os campos
# comuns (ajustes, proteção, total, rótulo) e os defaults dos demais modelos,
# produzindo o mesmo dict de sempre.

def calcular_comissao(session, email: str, ano: int, mes: int, ctx: dict = None) -> dict:
    """
    Calculates the principal commission for a given user and period.
    Supports models: MRR (Ares/B2B/Farmer/FSB/Sonia), Saving, GD, B2G, CancRecovery.
    Returns a dict with all components, or {'erro': str} when data is missing.

    ctx: contexto em lote de montar_contexto(session, ano, mes). Se None, é
    montado aqui; passe o contexto cacheado para amortizar as queries por mês.
    """
    # Normalização: e-mail sempre lowercase (o contexto é indexado assim).
    email = str(email).strip().lower().replace("'", "''")
    if ctx is None or ctx.get("ano") != int(ano) or ctx.get("mes") != int(mes):
        ctx = montar_contexto(session, ano, mes)

    # Recuperação de cancelamento: modelo próprio, sem OTE
    pr0 = ctx["params"].get(email)
    if pr0 is not None and bool(pr0.get("IS_CANC_RECOVERY") or False):
        return _calcular_comissao_canc_recovery(ctx, email, pr0)

    # Account Manager (ago/2026+): modelo de MEDICAO por NRR para quem e AM
    # no RI (equipe 'Account Manager') E tem carteira em HUBSPOT_LISTA_POTENCIAL_FARMER.
    # Restringir ao RI evita classificar como AM quem aparece na lista de
    # potenciais apenas como gerente HubSpot (ex.: consultor FSB com clientes AM).
    _meta_row = (ctx.get("metas") or {}).get(email)
    _meta_equipe = str(
        _meta_row["EQUIPE"] if _meta_row is not None else ""
    ).lower()
    if (int(ano), int(mes)) >= AM_DESDE \
            and _meta_equipe in ("account manager", "am gdc", "am escritório") \
            and email in (ctx.get("am") or {}):
        return _calcular_am(ctx, email, ano, mes)

    b = _base_comissao(ctx, email, ano, mes)
    if "erro" in b:
        return b

    if b["is_gd"]:
        m = _calcular_gd(ctx, b)
    elif b["is_b2g"]:
        m = _calcular_b2g(ctx, b)
    elif b["is_saving"]:
        m = _calcular_saving(ctx, b)
    else:
        m = _calcular_mrr(ctx, b)
    return _montar_resultado(ctx, b, m)


def _calcular_am(ctx, email, ano, mes):
    """Account Manager: mede NRR da carteira (sem regra de comissão ainda).

    MRR Evoluído = Inicial + Novos negócios (MRR cheio) + Upsells (delta das
                   substituições) + delta das renovações e impulsos − churn.
    NRR = Evoluído / Inicial. Contratos são de ciclo mensal: "Data de
    desativação" preenchida é fim de ciclo, não churn — churn real é vencer
    sem renovar (ver docs/20_aba_comissoes_am.md)."""
    am = ctx["am"][email]
    mrr_inicial = am["mrr_inicial"]
    novos_negocios = am["novos_negocios"]
    upsells     = am["upsells"]
    renovacoes_delta = am["renovacoes_delta"]
    impulsos_delta = am["impulsos_delta"]
    churn_mrr   = am["churn_mrr"]
    mrr_evoluido = (mrr_inicial + novos_negocios + upsells
                    + renovacoes_delta + impulsos_delta - churn_mrr)
    nrr = (mrr_evoluido / mrr_inicial) if mrr_inicial > 0 else None

    # Meta NRR: target_value na RI é o NRC alvo em p.p. (ex.: -0,72 → NRR meta = 99,28%)
    meta_row = ctx["metas"].get(email)
    am_meta_nrr = None
    if meta_row is not None:
        _meta_nrc = float(meta_row.get("META_MRR") or 0)
        if _meta_nrc != 0:
            am_meta_nrr = round(1 + _meta_nrc / 100, 6)

    pr = ctx["params"].get(email)
    cargo = str(pr["CARGO"]) if pr is not None and pr.get("CARGO") else "Account Manager"
    equipe_am = (
        str(meta_row["EQUIPE"])
        if meta_row is not None and meta_row.get("EQUIPE")
        else "Account Manager"
    )

    ajuste_total, ajuste_n = ctx["ajustes"].get(email, (0.0, 0))

    return {
        # medidas AM
        "am_mrr_inicial": mrr_inicial, "am_n_inicial": am["n_inicial"],
        "am_novos_negocios": novos_negocios,
        "am_n_novos_negocios": am["n_novos_negocios"],
        "am_upsells": upsells, "am_n_upsells": am["n_upsells"],
        "am_upsells_mrr_anterior": am["upsells_mrr_anterior"],
        "am_upsells_mrr_novo": am["upsells_mrr_novo"],
        "am_renovacoes_delta": renovacoes_delta,
        "am_renovacoes_contratos": am["renovacoes_contratos"],
        "am_renovacoes_mrr_anterior": am["renovacoes_mrr_anterior"],
        "am_renovacoes_mrr_novo": am["renovacoes_mrr_novo"],
        "am_impulsos_delta": impulsos_delta,
        "am_impulsos_contratos": am["impulsos_contratos"],
        "am_impulsos_mrr_anterior": am["impulsos_mrr_anterior"],
        "am_impulsos_mrr_novo": am["impulsos_mrr_novo"],
        "am_churn_mrr": churn_mrr, "am_churn_clientes": am["churn_clientes"],
        "am_mrr_evoluido": mrr_evoluido, "am_nrr": nrr, "am_meta_nrr": am_meta_nrr,
        # contrato padrão do painel (Minha Equipe/Export/Histórico leem estes)
        "equipe": equipe_am, "cargo": cargo,
        "realizado": mrr_evoluido, "meta_mrr": mrr_inicial,
        "pct_atingido": (nrr or 0.0), "desconto": 0.0,
        "ote_base": None, "ote_tier": 1, "acelerador": 0.0, "acel_desc": "",
        "ote_ajustado": None, "ote_variavel": 0.0,
        "ote_cheio": None, "ote_02_cheio": None,
        "ote_prop": None, "ote_02_prop": None,
        "cliff_ote_01": 0.0, "cliff_ote_02": None,
        "cliff_acel_01": 0.0, "mult_acel_01": 1.0,
        "cliff_acel_02": None, "mult_acel_02": None,
        "mrr_avista": 0.0, "mrr_cc3x": 0.0, "mrr_cc12x": 0.0, "mrr_recorrente": 0.0,
        "mult_avista": 1.0, "mult_cc3x": 1.0, "mult_cc12x": 1.0, "mult_recorrente": 1.0,
        "booking_extras": 0.0, "comissao_bk_extra": 0.0, "pct_bk_extra": 0.0,
        "faixa_atingida": None, "proxima_faixa": None,
        "dividas_pagas": 0.0, "comissao_dividas": 0.0,
        "pct_protecao": 0.0, "bonificacao_protecao": 0.0,
        "opps_override": None, "trim": None, "b2g_ajuste": None,
        "arr_real": 0.0, "bk_real": 0.0, "meta_arr": 0.0,
        "pct_arr_b2g": 0.0, "pct_bk_b2g": 0.0,
        "pct_ponderado": 0.0, "pct_meta_atingida": 0.0,
        "pond_arr_b2g": 0.0, "pond_bk_b2g": 0.0, "pond_ma": 0.0,
        "meta_atingida_real": 0.0, "rotulo_aproveitamento": False,
        "ajuste_total": ajuste_total, "ajuste_n": ajuste_n,
        "total": ajuste_total,
        "is_saving": False, "is_gd": False, "is_b2g": False, "is_am": True,
        "is_gestor": False,
        "ote_indisponivel": False, "trim_bloqueado": False,
        "meta_atingida_meta": 0.0,
    }


def composicao_carteira_am(session, email, ano, mes):
    """Contratos que compõem o MRR Inicial da carteira do AM no mês."""
    em = str(email).strip().lower().replace("'", "''")
    m1, _ = _am_datas(ano, mes)
    return session.sql(f"""
        WITH cc AS ({_AM_CONTRATOS_SQL})
        SELECT cc.ID_CLIENTE, MAX(l.NOME_CLIENTE) AS CLIENTE,
               MAX(l.LINK_CLIENTE) AS LINK_CLIENTE,
               cc.CONTRATO, MAX(cc.NUM_CONTRATO) AS NUM_CONTRATO,
               TO_VARCHAR(MAX(cc.INI), 'DD/MM/YYYY') AS DATA_INICIO,
               TO_VARCHAR(MAX(cc.REN), 'DD/MM/YYYY') AS PROX_RENOVACAO,
               ROUND(SUM(cc.MRR), 2) AS MRR
        FROM cc
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = cc.ID_CLIENTE
        WHERE LOWER(cc.GERENTE) = '{em}'
          AND {_am_cond_inicial(m1)}
        GROUP BY cc.ID_CLIENTE, cc.CONTRATO
        ORDER BY MRR DESC
    """).to_pandas()


def composicao_exclusoes_carteira_am(session, email):
    """Exclusoes administrativas ativas que pertencem a carteira da AM."""
    em = str(email).strip().lower().replace("'", "''")
    return session.sql(f"""
        WITH contratos AS ({_AM_CONTRATOS_BRUTA_SQL})
        SELECT contratos.CONTRATO,
               MAX(contratos.NUM_CONTRATO) AS NUM_CONTRATO,
               MAX(l.NOME_CLIENTE) AS CLIENTE,
               ROUND(MAX(contratos.MRR), 2) AS MRR,
               exclusao.SOLICITADO_POR,
               exclusao.MOTIVO,
               TO_VARCHAR(CONVERT_TIMEZONE('America/Sao_Paulo', exclusao.CREATED_AT), 'DD/MM/YYYY HH24:MI') AS CADASTRADO_EM
        FROM contratos
        JOIN {_AM_EXCLUSOES_TABELA} exclusao
          ON exclusao.ID_CONTRATO = contratos.CONTRATO
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = contratos.ID_CLIENTE
        WHERE LOWER(contratos.GERENTE) = '{em}'
        GROUP BY contratos.CONTRATO, exclusao.SOLICITADO_POR,
                 exclusao.MOTIVO, exclusao.CREATED_AT
        ORDER BY exclusao.CREATED_AT DESC, contratos.CONTRATO
    """).to_pandas()


def composicao_movim_am(session, email, ano, mes):
    """Novos negócios (MRR cheio) e upsells/downgrades de substituição (delta,
    com MRR anterior e novo) da carteira AM no mês, separados pelo TIPO."""
    em = str(email).strip().lower().replace("'", "''")
    m1, m2 = _am_datas(ano, mes)
    corte = f"LEAST(CURRENT_DATE, DATEADD(day, -1, {m2}))"
    return session.sql(f"""
        WITH {_am_movimentacoes_ctes(m1, m2, corte)}
        SELECT upsell.TIPO,
               upsell.ID_CLIENTE,
               MAX(l.NOME_CLIENTE) AS CLIENTE,
               MAX(l.LINK_CLIENTE) AS LINK_CLIENTE,
               MAX(upsell.NEGOCIO) AS NEGOCIO,
               MAX(upsell.NOME_NEGOCIO) AS NOME_NEGOCIO,
               MAX(upsell.CONTRATO) AS CONTRATO,
               MAX(upsell.NUM_CONTRATO) AS NUM_CONTRATO,
               TO_VARCHAR(MAX(upsell.DATA_FECHAMENTO), 'DD/MM/YYYY') AS DATA_FECH,
               ROUND(SUM(upsell.MRR_ANTERIOR), 2) AS MRR_ANTERIOR,
               ROUND(SUM(upsell.MRR_NOVO), 2) AS MRR_NOVO,
               ROUND(SUM(upsell.MRR), 2) AS MRR
        FROM upsells_contrato upsell
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = upsell.ID_CLIENTE
        WHERE LOWER(upsell.GERENTE) = '{em}'
        GROUP BY upsell.TIPO, upsell.ID_CLIENTE, COALESCE(upsell.NEGOCIO, upsell.CONTRATO)
        ORDER BY MRR DESC, CLIENTE
    """).to_pandas()


def composicao_churn_am(session, email, ano, mes):
    """Contratos da carteira que churnaram no mês (desativados; correr atrás)."""
    em = str(email).strip().lower().replace("'", "''")
    m1, m2 = _am_datas(ano, mes)
    corte = f"LEAST(CURRENT_DATE, DATEADD(day, -1, {m2}))"
    return session.sql(f"""
        WITH {_am_movimentacoes_ctes(m1, m2, corte)}
        SELECT cc.ID_CLIENTE, MAX(l.NOME_CLIENTE) AS CLIENTE,
               MAX(l.LINK_CLIENTE) AS LINK_CLIENTE,
               cc.CONTRATO, MAX(cc.NUM_CONTRATO) AS NUM_CONTRATO,
               TO_VARCHAR(MAX(cc.DESATIV), 'DD/MM/YYYY') AS DATA_DESATIVACAO,
               TO_VARCHAR(MAX(cc.REN), 'DD/MM/YYYY') AS DATA_RENOVACAO,
               ROUND(SUM(cc.MRR), 2) AS MRR_PERDIDO
        FROM cc
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = cc.ID_CLIENTE
        WHERE LOWER(cc.GERENTE) = '{em}'
          AND cc.INI < {m1} AND cc.REN >= {m1}
          AND cc.STATUS = 'Inativo'
          AND cc.DESATIV >= {m1} AND cc.DESATIV <= {corte}
          AND NOT EXISTS (
              SELECT 1
              FROM contratos_substituidos substituido
              WHERE substituido.CONTRATO = cc.CONTRATO
          )
        GROUP BY cc.ID_CLIENTE, cc.CONTRATO
        ORDER BY MRR_PERDIDO DESC
    """).to_pandas()


# Tipo do negócio aceito ao buscar o deal pela associação com o contrato.
_AM_TIPO_NEG_RENOVACAO = "negocio.\"Tipo de negócio\" ILIKE '%renova%'"
# Negócio perdido nunca é exibido como origem de uma movimentação.
_NEG_PERDIDO = "COALESCE(negocio.\"Fechado perdido\", FALSE)"
# Só negócio FECHADO GANHO aparece na coluna Negócio (17/08/2026): perdido e
# aberto (em negociação) ficam de fora; a célula preenche quando ele ganhar.
_NEG_GANHO = "COALESCE(negocio.\"Fechado ganho\", FALSE)"
_AM_TIPO_NEG_IMPULSO = (
    "negocio.\"Tipo de negócio\" = 'Novo negócio - Impulso de Contrato'"
)


def _am_negocio_ctes(filtro_tipo, m1):
    """CTEs de apoio para exibir o negócio de uma movimentação de contrato.

    Só enriquecem a exibição: nenhum cálculo depende delas.
    - negocio_venda: negócio da venda do mês para o número do contrato, a mesma
      fonte que alimenta o Evoluído.
    - negocio_contrato: negócio associado ao contrato no HubSpot, restrito ao
      tipo da movimentação. Cobre o que a venda do mês não alcança (renovação
      fechada com início em mês futuro, por exemplo).
    - negocio_numero: negócio cujo campo "Número do contrato" aponta o número,
      com fechamento a partir do mês. Último recurso: cobre o negócio ganho
      sem venda no mês e sem associação (as associações atrasam dias). O corte
      por {m1} evita casar a renovação de ciclos anteriores do mesmo número.

    As três exibem SÓ negócio fechado ganho (regra de 17/08/2026): perdido
    nunca aparece (caso 61694979964, contrato 631731, ROHR, Clidiani,
    ago/2026, sucedido pelo ganho 63788756251) e aberto também não (caso
    62829127210, contrato 631937, LTRINDADE, ago/2026, em Negociação); a
    célula fica vazia e preenche quando o negócio ganhar.
    """
    return f"""
        negocio_venda AS (
            -- Chaveado por gerente + número do contrato, sem o id do cliente: a
            -- venda que renova pode estar em outro registro de cliente da mesma
            -- carteira (caso 631731, ROHR, Clidiani, ago/2026, cujo negócio
            -- ganho está no cliente 57413557115 e não no 37095448225).
            SELECT venda.GERENTE, venda.NUM_CONTRATO,
                   venda.NEGOCIO, venda.NOME_NEGOCIO
            FROM vendas_carteira_mes venda
            LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON negocio."Id do negócio" = venda.NEGOCIO
            WHERE {_NEG_GANHO}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY venda.GERENTE, venda.NUM_CONTRATO
                ORDER BY venda.DATA_FECHAMENTO DESC NULLS LAST, venda.NEGOCIO DESC
            ) = 1
        ),
        negocio_contrato AS (
            SELECT SPLIT_PART(associacao.ID_CONTRATO, '.', 1) AS CONTRATO,
                   negocio."Id do negócio" AS NEGOCIO,
                   negocio."Nome do negócio" AS NOME_NEGOCIO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL associacao
            JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
              ON negocio."Id do negócio" = SPLIT_PART(associacao.ID_DEAL, '.', 1)
             AND {filtro_tipo}
             AND {_NEG_GANHO}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY SPLIT_PART(associacao.ID_CONTRATO, '.', 1)
                ORDER BY negocio."Data de fechamento" DESC NULLS LAST,
                         negocio."Id do negócio" DESC
            ) = 1
        ),
        negocio_numero AS (
            SELECT TO_VARCHAR(TRY_TO_NUMBER(negocio."Número do contrato"))
                       AS NUM_CONTRATO,
                   negocio."Id do negócio" AS NEGOCIO,
                   negocio."Nome do negócio" AS NOME_NEGOCIO
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS negocio
            WHERE {filtro_tipo}
              AND {_NEG_GANHO}
              AND TRY_TO_NUMBER(negocio."Número do contrato") IS NOT NULL
              AND negocio."Data de fechamento" >= {m1}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY TO_VARCHAR(TRY_TO_NUMBER(negocio."Número do contrato"))
                ORDER BY negocio."Data de fechamento" DESC NULLS LAST,
                         negocio."Id do negócio" DESC
            ) = 1
        )
    """


def composicao_renovacoes_am(session, email, ano, mes):
    """Renovações que substituem o contrato inicial pelo novo MRR."""
    em = str(email).strip().lower().replace("'", "''")
    m1, m2 = _am_datas(ano, mes)
    corte = f"LEAST(CURRENT_DATE, DATEADD(day, -1, {m2}))"
    return session.sql(f"""
        WITH {_am_movimentacoes_ctes(m1, m2, corte)},
        {_am_negocio_ctes(_AM_TIPO_NEG_RENOVACAO, m1)}
        SELECT renovacao.TIPO, renovacao.ID_CLIENTE, MAX(l.NOME_CLIENTE) AS CLIENTE,
               MAX(l.LINK_CLIENTE) AS LINK_CLIENTE,
               CASE WHEN assoc.NEGOCIO IS NOT NULL THEN assoc.NEGOCIO
                    WHEN venda.NEGOCIO IS NOT NULL THEN venda.NEGOCIO
                    ELSE numero.NEGOCIO END AS NEGOCIO,
               CASE WHEN assoc.NEGOCIO IS NOT NULL THEN assoc.NOME_NEGOCIO
                    WHEN venda.NEGOCIO IS NOT NULL THEN venda.NOME_NEGOCIO
                    ELSE numero.NOME_NEGOCIO END AS NOME_NEGOCIO,
               renovacao.CONTRATO_ANTERIOR,
               renovacao.CONTRATO_NOVO,
               renovacao.NUM_CONTRATO,
               TO_VARCHAR(renovacao.INICIO_NOVO, 'DD/MM/YYYY') AS DATA_INICIO_NOVO,
               ROUND(renovacao.MRR_ANTERIOR, 2) AS MRR_ANTERIOR,
               ROUND(renovacao.MRR_NOVO, 2) AS MRR_NOVO,
               ROUND(renovacao.MRR_NOVO - renovacao.MRR_ANTERIOR, 2) AS DELTA_MRR
        FROM renovacoes_contrato renovacao
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = renovacao.ID_CLIENTE
        LEFT JOIN negocio_venda venda
          ON venda.GERENTE = renovacao.GERENTE
         AND venda.NUM_CONTRATO = renovacao.NUM_CONTRATO
        LEFT JOIN negocio_contrato assoc
          ON assoc.CONTRATO = renovacao.CONTRATO_NOVO
        LEFT JOIN negocio_numero numero
          ON numero.NUM_CONTRATO = renovacao.NUM_CONTRATO
        WHERE LOWER(renovacao.GERENTE) = '{em}'
        GROUP BY renovacao.TIPO, renovacao.ID_CLIENTE, renovacao.CONTRATO_ANTERIOR,
                 renovacao.CONTRATO_NOVO, renovacao.NUM_CONTRATO,
                 renovacao.INICIO_NOVO, renovacao.MRR_ANTERIOR, renovacao.MRR_NOVO,
                 venda.NEGOCIO, venda.NOME_NEGOCIO, assoc.NEGOCIO, assoc.NOME_NEGOCIO,
                 numero.NEGOCIO, numero.NOME_NEGOCIO
        ORDER BY DELTA_MRR, CLIENTE
    """).to_pandas()


def composicao_impulsos_am(session, email, ano, mes):
    """Impulsos que consolidam vários contratos iniciais em um novo contrato."""
    em = str(email).strip().lower().replace("'", "''")
    m1, m2 = _am_datas(ano, mes)
    corte = f"LEAST(CURRENT_DATE, DATEADD(day, -1, {m2}))"
    return session.sql(f"""
        WITH {_am_movimentacoes_ctes(m1, m2, corte)},
        {_am_negocio_ctes(_AM_TIPO_NEG_IMPULSO, m1)}
        SELECT impulso.ID_CLIENTE, MAX(l.NOME_CLIENTE) AS CLIENTE,
               MAX(l.LINK_CLIENTE) AS LINK_CLIENTE,
               CASE WHEN assoc.NEGOCIO IS NOT NULL THEN assoc.NEGOCIO
                    WHEN venda.NEGOCIO IS NOT NULL THEN venda.NEGOCIO
                    ELSE numero.NEGOCIO END AS NEGOCIO,
               CASE WHEN assoc.NEGOCIO IS NOT NULL THEN assoc.NOME_NEGOCIO
                    WHEN venda.NEGOCIO IS NOT NULL THEN venda.NOME_NEGOCIO
                    ELSE numero.NOME_NEGOCIO END AS NOME_NEGOCIO,
               impulso.NUM_CONTRATOS_ANTERIORES AS CONTRATOS_ANTERIORES,
               impulso.CONTRATO_NOVO,
               impulso.NUM_CONTRATO,
               impulso.N_CONTRATOS_ANTERIORES,
               TO_VARCHAR(impulso.INICIO_NOVO, 'DD/MM/YYYY') AS DATA_INICIO_NOVO,
               ROUND(impulso.MRR_ANTERIOR, 2) AS MRR_ANTERIOR,
               ROUND(impulso.MRR_NOVO, 2) AS MRR_NOVO,
               ROUND(impulso.MRR_NOVO - impulso.MRR_ANTERIOR, 2) AS DELTA_MRR
        FROM impulsos_contrato impulso
        LEFT JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
          ON TO_VARCHAR(TO_NUMBER(l.ID_CLIENTE)) = impulso.ID_CLIENTE
        LEFT JOIN negocio_contrato assoc
          ON assoc.CONTRATO = impulso.CONTRATO_NOVO
        LEFT JOIN negocio_venda venda
          ON venda.GERENTE = impulso.GERENTE
         AND venda.NUM_CONTRATO = impulso.NUM_CONTRATO
        LEFT JOIN negocio_numero numero
          ON numero.NUM_CONTRATO = impulso.NUM_CONTRATO
        WHERE LOWER(impulso.GERENTE) = '{em}'
        GROUP BY impulso.ID_CLIENTE, impulso.CONTRATO_ANTERIOR,
                 impulso.CONTRATO_NOVO, impulso.NUM_CONTRATO,
                 impulso.NUM_CONTRATOS_ANTERIORES, impulso.N_CONTRATOS_ANTERIORES,
                 impulso.INICIO_NOVO,
                 impulso.MRR_ANTERIOR, impulso.MRR_NOVO,
                 assoc.NEGOCIO, assoc.NOME_NEGOCIO, venda.NEGOCIO, venda.NOME_NEGOCIO,
                 numero.NEGOCIO, numero.NOME_NEGOCIO
        ORDER BY DELTA_MRR, CLIENTE
    """).to_pandas()


def _base_comissao(ctx, email, ano, mes):
    """Resolve o que é comum a todos os modelos: meta, parâmetros e OTE.
    Retorna o dict-base ('b') ou {'erro': ...} quando falta cadastro."""
    # ── 1. Meta ──────────────────────────────────────────────────────────────
    meta_row = ctx["metas"].get(email)
    if meta_row is None:
        return {"erro": f"Sem dados de meta para este período."}
    equipe   = str(meta_row["EQUIPE"] or "")
    is_gd    = equipe.lower() == "gd"
    is_b2g   = equipe.lower() in ('b2g', 'governo')
    # GD usa Opps (META_OTR); Governo (B2G) usa Booking = OTR (META_OTR); demais usam META_MRR.
    meta_mrr = _f(meta_row["META_OTR"] if (is_gd or is_b2g) else meta_row["META_MRR"], 0)
    # B2G gestor: alvo de % da equipe atingindo quota (padrão = 80%)
    meta_atingida_meta = _cfg_f(ctx, "meta_atingida_gestor_b2g", 0.8)
    desconto = _f(meta_row["PERCENTUAL_DESCONTO_METAS"], 0)
    if desconto > 1:  # campo armazenado em pontos percentuais (ex: 25 = 25%), normaliza para decimal
        desconto /= 100

    # ── 2. Parâmetros ─────────────────────────────────────────────────────────
    pr = ctx["params"].get(email)
    if pr is None:
        return {"erro": "Parâmetros não configurados para este período."}

    cargo     = str(pr["CARGO"] or "")
    is_gestor = bool(pr["IS_GESTOR"])
    is_trim_habilitado = bool(pr.get("IS_TRIM_HABILITADO", True))

    # SDR fora do time GD (ex: B2B Escritório) segue estrutura GD: Opps / REALIZADO_GD
    is_sdr = _cfg_s(ctx, "cargo_sdr_contem", "sales development").lower() in cargo.lower()
    if is_sdr and not is_gd:
        is_gd    = True
        meta_mrr = _f(meta_row["META_OTR"], 0)

    # GD/SDR consultor: meta vem do Revenue Intelligence (gestores mantêm META_OTR do METAS)
    if is_gd and not is_gestor:
        _ri_meta = ctx["ri_metas"].get(email)
        meta_mrr = _f(_ri_meta, 0) if _ri_meta is not None else 0.0

    # Equipes que o gestor agrega (padrao = sua propria equipe; override p/ multi-equipe)
    gestor_equipes = _gestor_equipes_cfg(ctx, email, equipe)
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
        ote_cheio    = _f(ctx["otes"].get(str(cargo).upper()))
        ote_02_cheio = None  # tier 2 only via override

    ote_prop    = (ote_cheio    * (1 - desconto)) if ote_cheio    is not None else None
    ote_02_prop = (ote_02_cheio * (1 - desconto)) if ote_02_cheio is not None else None


    # Saving model: equipe Saving a partir de abr/2026 usa patamares escalonados
    is_saving = equipe.lower() == "saving" and (int(ano), int(mes)) >= (2026, 4)
    quarter = int(mes) in (3, 6, 9, 12)

    return {
        "email": email, "ano": int(ano), "mes": int(mes),
        "equipe": equipe, "cargo": cargo,
        "is_gd": is_gd, "is_b2g": is_b2g, "is_saving": is_saving,
        "is_gestor": is_gestor,
        "meta_mrr": meta_mrr, "desconto": desconto,
        "meta_atingida_meta": meta_atingida_meta,
        "gestor_equipes": gestor_equipes,
        "cliff_ote_01": cliff_ote_01, "cliff_ote_02": cliff_ote_02,
        "cliff_acel_01": cliff_acel_01, "mult_acel_01": mult_acel_01,
        "cliff_acel_02": cliff_acel_02, "mult_acel_02": mult_acel_02,
        "pct_bk_extra": pct_bk_extra, "pct_protecao": pct_protecao,
        "ote_cheio": ote_cheio, "ote_02_cheio": ote_02_cheio,
        "ote_prop": ote_prop, "ote_02_prop": ote_02_prop,
        "calc_trim": quarter and is_trim_habilitado,
        "trim_bloqueado": quarter and not is_trim_habilitado,
    }


# ── Helpers compartilhados entre os modelos ───────────────────────────────────

def _ote_base_tier(b, pct_atingido):
    """OTE Base: tier 2 se cliff atingido e OTE_02 configurado; senão tier 1."""
    if (b["cliff_ote_02"] is not None and pct_atingido >= b["cliff_ote_02"]
            and b["ote_02_prop"] is not None):
        return b["ote_02_prop"], 2
    return b["ote_prop"], 1


def _acelerador_cliffs(b, eixo, desc_cliff):
    """Acelerador por cliffs de PARAMETROS, aplicado ao eixo dado."""
    if b["cliff_ote_01"] > 0 and eixo < b["cliff_ote_01"]:
        return 0.0, desc_cliff
    if (b["cliff_acel_02"] is not None and b["mult_acel_02"] is not None
            and eixo >= b["cliff_acel_02"]):
        return b["mult_acel_02"], f"Acelerador 2 (≥{b['cliff_acel_02']:.0%})"
    if eixo >= b["cliff_acel_01"]:
        return b["mult_acel_01"], f"Acelerador 1 (≥{b['cliff_acel_01']:.0%})"
    return 1.0, "Base (sem acelerador)"


def _meta_tri_own(ctx, email, q_meses, campo):
    """Soma META_MRR/META_OTR do próprio e-mail nos meses do trimestre."""
    return float(sum(
        _f(ctx["metas_tri"][(email, m)][campo], 0) or 0
        for m in q_meses if (email, m) in ctx["metas_tri"]))


def _b2g_tri_val(ctx, e, m, i):
    """ARR (i=0) ou Booking (i=1) de (email, mes) no trimestre B2G."""
    _v = ctx["b2g_real_tri"].get((e, m))
    return (_v[i] or 0.0) if _v is not None else 0.0


def _trim_fatores(ctx, b, real_ind, meta_ind, real_eq, meta_eq):
    """Fecha o dict 'trim': percentuais e fatores individual/equipe."""
    pct_ind = real_ind / meta_ind if meta_ind > 0 else 0.0
    # B2G gestor usa fator ×0.9; gestor MRR usa ×0.6; consultores usam ×0.3
    if b["is_b2g"] and b["is_gestor"]:
        fator_mult_ind = _cfg_f(ctx, "fator_trim_gestor_b2g", 0.9)
    elif b["is_gestor"]:
        fator_mult_ind = _cfg_f(ctx, "fator_trim_gestor", 0.6)
    else:
        fator_mult_ind = _cfg_f(ctx, "fator_trim_consultor", 0.3)
    fator_ind = (pct_ind * fator_mult_ind) if pct_ind >= 1.0 else 0.0

    pct_eq = real_eq / meta_eq if meta_eq > 0 else 0.0
    fator_eq = 0.0
    if (not b["is_gestor"] and pct_eq >= 1.0
            and (b["cliff_ote_01"] == 0 or pct_ind >= b["cliff_ote_01"])):
        fator_eq = pct_ind * _cfg_f(ctx, "fator_trim_equipe", 0.3)

    return {
        "real_ind": real_ind,
        "meta_ind": meta_ind,
        "pct_ind":  pct_ind,
        "real_eq":  real_eq,
        "meta_eq":  meta_eq,
        "pct_eq":   pct_eq,
        "fator_ind": fator_ind,
        "fator_eq":  fator_eq,
        "is_gestor": b["is_gestor"],
        "is_b2g":    b["is_b2g"],
    }


def _calcular_gd(ctx, b):
    """GD/SDR: realizado em Opps (REALIZADO_GD + overrides), sem Acel Form Pag."""
    email, equipe, is_gestor = b["email"], b["equipe"], b["is_gestor"]
    opps_override = None  # Opps adicionadas por override (GD consultor)

    def _gd_mes(e):
        """COALESCE(override, opps) do mês — None se a pessoa não tem opps."""
        if e not in ctx["gd_opps"]:
            return None
        _ov = _f(ctx["gd_override"].get(e))
        return _ov if _ov is not None else (_f(ctx["gd_opps"][e], 0) or 0)

    if is_gestor:
        _ov_gestor = _f(ctx["gd_override"].get(email))
        if _ov_gestor is not None:
            # Override direto definido na pagina de admin substitui a agregacao do time.
            realizado = float(_ov_gestor)
        else:
            # Time do gestor: PERMISSAO_RLS se houver; senao toda a equipe GD
            # (quem tem meta no Revenue Intelligence e parametro nao-gestor).
            team = ctx["rls_teams"].get(email)
            if not team:
                team = [e for e in ctx["gd_opps"]
                        if e in ctx["ri_metas"]
                        and e in ctx["params"] and not bool(ctx["params"][e]["IS_GESTOR"])]
            _vals = [_gd_mes(t) for t in team]
            realizado = float(sum(v for v in _vals if v is not None))
    else:
        _ov_val  = _f(ctx["gd_override"].get(email))
        _raw_val = _f(ctx["gd_opps"].get(email), 0) or 0
        realizado = float(_ov_val if _ov_val is not None else _raw_val)
        if _ov_val is not None:
            _delta = int(_ov_val) - int(_raw_val)
            if _delta != 0:
                opps_override = _delta

    pct_atingido = realizado / b["meta_mrr"] if b["meta_mrr"] > 0 else 0.0
    ote_base, ote_tier = _ote_base_tier(b, pct_atingido)
    acelerador, acel_desc = _acelerador_cliffs(
        b, pct_atingido, f"Abaixo do cliff mínimo ({b['cliff_ote_01']:.0%})")
    ote_ajustado = (ote_base * acelerador * pct_atingido) if ote_base is not None else None
    # GD não tem forma de pagamento — comissão direta sem distribuição
    ote_variavel = ote_ajustado

    # Trimestral em Opps (REALIZADO_GD com overrides)
    trim = None
    if b["calc_trim"]:
        q_meses = [b["mes"] - 2, b["mes"] - 1, b["mes"]]
        if is_gestor and ctx["rls_teams"].get(email):
            # Time do gestor pela PERMISSAO_RLS, por mes; override direto tem precedencia.
            _vals = []
            for _m in q_meses:
                _ov_m = _f(ctx["gd_ov_tri"].get((email, _m)))
                if _ov_m is not None:
                    _vals.append(_ov_m)
                else:
                    _vals.extend([_gd_val(ctx, t, _m) for t in ctx["rls_tri"].get((email, _m), [])])
        elif is_gestor:
            # Equipe GD inteira por mes; override direto do gestor tem precedencia no mes.
            _vals = []
            for _m in q_meses:
                _ov_m = _f(ctx["gd_ov_tri"].get((email, _m)))
                if _ov_m is not None:
                    _vals.append(_ov_m)
                else:
                    _vals.extend([_gd_val(ctx, e, m2)
                                   for (e, m2) in ctx["gd_opps_tri"]
                                   if m2 == _m and (e, m2) in ctx["ri_tri"]
                                   and ctx["params_tri"].get((e, m2)) is False])
        else:
            _vals = [_gd_val(ctx, email, m) for m in q_meses]
        real_tri_ind = float(sum(v for v in _vals if v is not None))
        if is_gestor:
            meta_tri_ind = _meta_tri_own(ctx, email, q_meses, "META_OTR")
        else:
            meta_tri_ind = float(sum(
                _f(ctx["ri_tri"].get((email, m)), 0) or 0 for m in q_meses))

        real_tri_eq = meta_tri_eq = 0.0
        if not is_gestor:
            _membros_m = {m: _membros_equipe_tri(ctx, equipe, m) for m in q_meses}
            _vals_eq = [_gd_val(ctx, e, m)
                        for m in q_meses for e in _membros_m[m]]
            real_tri_eq = float(sum(v for v in _vals_eq if v is not None))
            meta_tri_eq = float(sum(
                _f(ctx["metas_tri"][(e, m)]["META_OTR"], 0) or 0
                for m in q_meses for e in _membros_m[m]))
        trim = _trim_fatores(ctx, b, real_tri_ind, meta_tri_ind, real_tri_eq, meta_tri_eq)

    return {
        "realizado": realizado, "opps_override": opps_override,
        "pct_atingido": pct_atingido,
        "ote_base": ote_base, "ote_tier": ote_tier,
        "acelerador": acelerador, "acel_desc": acel_desc,
        "ote_ajustado": ote_ajustado, "ote_variavel": ote_variavel,
        "trim": trim,
    }


def _calcular_b2g(ctx, b):
    """B2G/Governo: dois eixos (consultor: ARR+Booking; gestor: Booking+Meta
    Atingida), acelerador por %Booking e ajuste trimestral acumulado."""
    email, equipe, is_gestor = b["email"], b["equipe"], b["is_gestor"]
    mes = b["mes"]

    # ── Realizado em ARR e Booking (VENDAS, filtro 400k snapshot-aware) ──────
    def _b2g_val(e, col):
        _r = ctx["b2g_real"].get(e)
        return (_f(_r[col], 0) or 0.0) if _r is not None else 0.0

    arr_real = bk_real = meta_atingida_real = 0.0
    if is_gestor:
        _membros = [e for e, mrow in ctx["metas"].items()
                    if str(mrow["EQUIPE"] or "") == equipe
                    and e in ctx["params"] and not bool(ctx["params"][e]["IS_GESTOR"])]
        bk_real = float(sum(_b2g_val(e, "BK") for e in _membros))

        # Meta Atingida: proporção de consultores com %Booking >= 100%
        _n_hit = 0
        for e in _membros:
            _mo = _f(ctx["metas"][e]["META_OTR"], 0) or 0
            if _mo > 0 and (_b2g_val(e, "BK") / _mo) >= 1.0:
                _n_hit += 1
        if _membros:
            meta_atingida_real = _n_hit / float(len(_membros))
    else:
        arr_real = _b2g_val(email, "ARR")
        bk_real  = _b2g_val(email, "BK")

    meta_arr    = (b["meta_mrr"] * _cfg_f(ctx, "meta_arr_pct_booking", 0.5)) if b["meta_mrr"] > 0 else 0.0
    pct_arr_b2g = arr_real / meta_arr if meta_arr > 0 else 0.0
    pct_bk_b2g  = bk_real  / b["meta_mrr"] if b["meta_mrr"] > 0 else 0.0
    # Tier do OTE: consultores usam %ARR; gestor usa %Booking
    ote_base, ote_tier = _ote_base_tier(b, pct_arr_b2g if not is_gestor else pct_bk_b2g)

    # ── Ponderações por tipo de meta (sem Acel Form Pag) ─────────────────────
    pond_map = ctx["ponderacoes"].get(email, {})
    if is_gestor:
        pond_arr_b2g = 0.0
        pond_bk_b2g  = pond_map.get("Booking", 0.8)
        pond_ma      = pond_map.get("MetaAtingida", 0.2)
        pct_meta_atingida = meta_atingida_real / b["meta_atingida_meta"] if b["meta_atingida_meta"] > 0 else 0.0
        pct_ponderado = pct_bk_b2g * pond_bk_b2g + pct_meta_atingida * pond_ma
    else:
        pond_arr_b2g = pond_map.get("ARR", 0.4)
        pond_bk_b2g  = pond_map.get("Booking", 0.6)
        pond_ma      = 0.0
        pct_meta_atingida = 0.0
        pct_ponderado = pct_arr_b2g * pond_arr_b2g + pct_bk_b2g * pond_bk_b2g

    # ── OTE: acelerador disparado por %Booking (cliff também em %Booking) ────
    acelerador, acel_desc = _acelerador_cliffs(
        b, pct_bk_b2g, f"Abaixo do cliff Booking ({b['cliff_ote_01']:.0%})")
    ote_ajustado = (ote_base * acelerador) if ote_base is not None else None
    ote_variavel = (ote_ajustado * pct_ponderado) if ote_ajustado is not None else None

    # ── Bônus trimestral (Booking, com filtro DEALS_PAGOS_400K) ──────────────
    trim = None
    if b["calc_trim"]:
        q_meses = [mes - 2, mes - 1, mes]
        if is_gestor:
            # Gestor: trimestral sobre Booking da equipe (membership por mes)
            real_tri_ind = float(sum(
                _b2g_tri_val(ctx, e, m, 1) for m in q_meses
                for e in _membros_equipe_tri(ctx, equipe, m)))
        else:
            # Consultor: trimestral sobre Booking próprio
            real_tri_ind = float(sum(_b2g_tri_val(ctx, email, m, 1) for m in q_meses))
        meta_tri_ind = _meta_tri_own(ctx, email, q_meses, "META_OTR")

        real_tri_eq = meta_tri_eq = 0.0
        if not is_gestor:
            _membros_m = {m: _membros_equipe_tri(ctx, equipe, m) for m in q_meses}
            real_tri_eq = float(sum(
                _b2g_tri_val(ctx, e, m, 1) for m in q_meses for e in _membros_m[m]))
            meta_tri_eq = float(sum(
                _f(ctx["metas_tri"][(e, m)]["META_OTR"], 0) or 0
                for m in q_meses for e in _membros_m[m]))
        trim = _trim_fatores(ctx, b, real_tri_ind, meta_tri_ind, real_tri_eq, meta_tri_eq)

    # ── Ajuste trimestral (recálculo da comissão acumulada vs. mensais) ──────
    b2g_ajuste = None
    if mes in (3, 6, 9, 12):
        q_meses = [mes - 2, mes - 1, mes]

        def _meta_q_own():
            return float(sum(
                _f(ctx["metas_tri"][(email, m)]["META_OTR"], 0) or 0
                for m in q_meses if (email, m) in ctx["metas_tri"]))

        if is_gestor:
            # Gestor: Booking equipe acumulado + Meta Atingida da equipe no trimestre
            _membros_m = {m: _membros_equipe_tri(ctx, equipe, m) for m in q_meses}
            bk_q = float(sum(
                _b2g_tri_val(ctx, e, m, 1) for m in q_meses for e in _membros_m[m]))
            meta_bk_q = _meta_q_own()

            # Meta Atingida trimestral: consultores com %BK cumulativo ≥ 100%
            # (por membro: Σ Booking ÷ Σ META_OTR dos meses em que teve meta)
            _membros_q = sorted({e for m in q_meses for e in _membros_m[m]})
            _n_hit_q = 0
            for e in _membros_q:
                _meses_e = [m for m in q_meses if e in _membros_m[m]]
                _bk_e   = sum(_b2g_tri_val(ctx, e, m, 1) for m in _meses_e)
                _meta_e = sum(_f(ctx["metas_tri"][(e, m)]["META_OTR"], 0) or 0
                              for m in _meses_e)
                if _meta_e > 0 and (_bk_e / _meta_e) >= 1.0:
                    _n_hit_q += 1
            ma_q = (_n_hit_q / float(len(_membros_q))) if _membros_q else 0.0

            pct_bk_q = bk_q / meta_bk_q if meta_bk_q > 0 else 0.0
            pct_ma_q = ma_q / b["meta_atingida_meta"] if b["meta_atingida_meta"] > 0 else 0.0
            pct_ponderado_q = pct_bk_q * pond_bk_b2g + pct_ma_q * pond_ma

            # Pago mensal (col. AP) e OTE Base trimestral (col. AL): somas dos
            # valores mensais reais — meses fechados vêm do snapshot.
            pago_mensal, ote_base_q = _pago_mensal_trimestre(
                email, b["ano"], mes, ote_variavel, ote_base)

            acel_q = _acel_b2g(pct_bk_q, b["cliff_ote_01"], b["cliff_acel_01"],
                               b["mult_acel_01"], b["cliff_acel_02"], b["mult_acel_02"])
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
            arr_q = float(sum(_b2g_tri_val(ctx, email, m, 0) for m in q_meses))
            bk_q  = float(sum(_b2g_tri_val(ctx, email, m, 1) for m in q_meses))

            meta_bk_q  = _meta_q_own()
            meta_arr_q = meta_bk_q * _cfg_f(ctx, "meta_arr_pct_booking", 0.5)

            pct_arr_q = arr_q / meta_arr_q if meta_arr_q > 0 else 0.0
            pct_bk_q  = bk_q  / meta_bk_q  if meta_bk_q  > 0 else 0.0
            pct_ponderado_q = pct_arr_q * pond_arr_b2g + pct_bk_q * pond_bk_b2g

            # Pago mensal (col. AP) e OTE Base trimestral (col. AL): somas dos
            # valores mensais reais — meses fechados vêm do snapshot.
            pago_mensal, ote_base_q = _pago_mensal_trimestre(
                email, b["ano"], mes, ote_variavel, ote_base)

            acel_q = _acel_b2g(pct_bk_q, b["cliff_ote_01"], b["cliff_acel_01"],
                               b["mult_acel_01"], b["cliff_acel_02"], b["mult_acel_02"])
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

    return {
        "realizado": bk_real, "arr_real": arr_real, "bk_real": bk_real,
        "meta_arr": meta_arr, "pct_arr_b2g": pct_arr_b2g, "pct_bk_b2g": pct_bk_b2g,
        "pct_atingido": pct_ponderado, "pct_ponderado": pct_ponderado,
        "pct_meta_atingida": pct_meta_atingida,
        "pond_arr_b2g": pond_arr_b2g, "pond_bk_b2g": pond_bk_b2g, "pond_ma": pond_ma,
        "meta_atingida_real": meta_atingida_real,
        "ote_base": ote_base, "ote_tier": ote_tier,
        "acelerador": acelerador, "acel_desc": acel_desc,
        "ote_ajustado": ote_ajustado, "ote_variavel": ote_variavel,
        "trim": trim, "b2g_ajuste": b2g_ajuste,
    }


def _realizado_vendas(ctx, b):
    """Realizado MRR/Saving pelas vendas do mês (nível de item, filtro 400k).
    Membership pela coluna VERTICAL da VENDAS (gestor) ou pelo e-mail
    (consultor, SEM validação de vertical) — quem não tem META não some."""
    _vm = ctx["vendas_mes"]
    if b["is_gestor"]:
        neg_df = _vm[_vm["VERTICAL"].isin([str(e) for e in b["gestor_equipes"]])].copy()
        neg_df["_EQ"] = neg_df["VERTICAL"]
    else:
        neg_df = _vm[_vm["CONS_L"] == b["email"]].copy()

    if neg_df.empty:
        return {"realizado": 0.0, "mrr_avista": 0.0, "mrr_cc3x": 0.0,
                "mrr_cc12x": 0.0, "mrr_recorrente": 0.0, "booking_extras": 0.0}

    neg_df["ACEL_FORM_PAG"] = neg_df.apply(
        lambda r: calc_acel_form_pag(r["FORMA_DE_PAGAMENTO"], r["PARCELAS"]), axis=1
    )
    # Gestor: composicao pela VERTICAL do deal (_EQ). Consultor: pela sua equipe.
    neg_df["VALOR"] = neg_df.apply(
        lambda r: _valor_linha(r, None if b["is_gestor"] else b["equipe"]), axis=1)
    cats_bk = _cfg_list(ctx, "categorias_booking_extra",
                        ["Implantação", "Serviço", "Curso"])
    mask_bk = neg_df["CATEGORIA_DO_ITEM"].isin(cats_bk) & (neg_df["MRR"].fillna(0) == 0)
    return {
        "realizado":      float(neg_df["VALOR"].sum()),
        "mrr_avista":     float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "À Vista",    "VALOR"].sum()),
        "mrr_cc3x":       float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "CC 3x",      "VALOR"].sum()),
        "mrr_cc12x":      float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "CC 12x",     "VALOR"].sum()),
        "mrr_recorrente": float(neg_df.loc[neg_df["ACEL_FORM_PAG"] == "Recorrente", "VALOR"].sum()),
        "booking_extras": float(neg_df.loc[mask_bk, "BOOKING"].sum()),
    }


def _comissao_bk_extra(b, pct_atingido, booking_extras):
    """Comissão sobre Booking Extra (MRR/Saving), sujeita ao cliff mínimo."""
    if b["cliff_ote_01"] == 0 or pct_atingido >= b["cliff_ote_01"]:
        return b["pct_bk_extra"] * booking_extras
    return 0.0


def _trim_vendas(ctx, b):
    """Bônus trimestral dos modelos MRR/Saving (realizado pelas vendas)."""
    email, equipe = b["email"], b["equipe"]
    q_meses = [b["mes"] - 2, b["mes"] - 1, b["mes"]]
    if b["is_gestor"]:
        real_tri_ind = float(sum(
            _valor_tri(ctx["vendas_tri_vert"].get(str(e)), e)
            for e in b["gestor_equipes"]))
    else:
        real_tri_ind = float(sum(
            _valor_tri(ctx["vendas_tri_cons"].get((email, m)), equipe)
            for m in q_meses))
    meta_tri_ind = _meta_tri_own(ctx, email, q_meses, "META_MRR")

    real_tri_eq = meta_tri_eq = 0.0
    if not b["is_gestor"]:
        _membros_m = {m: _membros_equipe_tri(ctx, equipe, m) for m in q_meses}
        real_tri_eq = float(sum(
            _valor_tri(ctx["vendas_tri_cons"].get((e, m)), equipe)
            for m in q_meses for e in _membros_m[m]))
        meta_tri_eq = float(sum(
            _f(ctx["metas_tri"][(e, m)]["META_MRR"], 0) or 0
            for m in q_meses for e in _membros_m[m]))
    return _trim_fatores(ctx, b, real_tri_ind, meta_tri_ind, real_tri_eq, meta_tri_eq)


def _calcular_saving(ctx, b):
    """Saving (abr/2026+): OTE × %Atingido × Faixa (patamares), sem Acel Form
    Pag; inclui comissão sobre dívidas recuperadas."""
    m = _realizado_vendas(ctx, b)
    pct_atingido = m["realizado"] / b["meta_mrr"] if b["meta_mrr"] > 0 else 0.0
    ote_base, ote_tier = _ote_base_tier(b, pct_atingido)

    # Faixa atingida e próxima faixa (patamares escalonados da equipe)
    _faixas = ctx["patamares"].get(b["equipe"], [])
    _abaixo = [fx for fx in _faixas if fx[0] <= pct_atingido]
    faixa_atingida = max(_abaixo, key=lambda fx: fx[0])[1] if _abaixo else None
    _acima = [fx for fx in _faixas if fx[0] > pct_atingido]
    proxima_faixa = min(_acima, key=lambda fx: fx[0]) if _acima else None

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

    # Dívidas pagas (apenas Saving), sujeitas ao cliff mínimo
    dividas_pagas = comissao_dividas = 0.0
    _drow = ctx["dividas"].get(b["email"])
    if _drow is not None:
        dividas_pagas = _f(_drow["VALOR"], 0)
        pct_div = _f(_drow["PERCENTUAL_COMISSAO"],
                     _cfg_f(ctx, "pct_dividas_default", 0.025))
        if b["cliff_ote_01"] == 0 or pct_atingido >= b["cliff_ote_01"]:
            comissao_dividas = dividas_pagas * pct_div

    m.update(
        pct_atingido=pct_atingido, ote_base=ote_base, ote_tier=ote_tier,
        acelerador=acelerador, acel_desc=acel_desc,
        ote_ajustado=ote_ajustado, ote_variavel=ote_variavel,
        faixa_atingida=faixa_atingida, proxima_faixa=proxima_faixa,
        comissao_bk_extra=_comissao_bk_extra(b, pct_atingido, m["booking_extras"]),
        dividas_pagas=dividas_pagas, comissao_dividas=comissao_dividas,
        trim=_trim_vendas(ctx, b) if b["calc_trim"] else None,
    )
    return m


def _calcular_mrr(ctx, b):
    """Modelo principal MRR (Ares/B2B/Farmer/FSB/Sonia): OTE × Acelerador ×
    % Atingido, distribuído por forma de pagamento (Acel Form Pag)."""
    m = _realizado_vendas(ctx, b)
    realizado = m["realizado"]
    pct_atingido = realizado / b["meta_mrr"] if b["meta_mrr"] > 0 else 0.0
    ote_base, ote_tier = _ote_base_tier(b, pct_atingido)

    # Multiplicadores por forma de pagamento da equipe
    ar = ctx["acel_fp"].get(b["equipe"])
    if ar is not None:
        mult_avista     = _f(ar["A_VISTA"],    1.0)
        mult_cc3x       = _f(ar["CC_ATE_3X"],  1.0)
        mult_cc12x      = _f(ar["CC_ATE_12X"], 1.0)
        mult_recorrente = _f(ar["RECORRENTE"], 1.0)
    else:
        mult_avista = mult_cc3x = mult_cc12x = mult_recorrente = 1.0

    acelerador, acel_desc = _acelerador_cliffs(
        b, pct_atingido, f"Abaixo do cliff mínimo ({b['cliff_ote_01']:.0%})")
    ote_ajustado = (ote_base * acelerador * pct_atingido) if ote_base is not None else None

    if ote_ajustado is not None and realizado > 0:
        ote_variavel = (
              ote_ajustado * (m["mrr_avista"]     / realizado) * mult_avista
            + ote_ajustado * (m["mrr_cc3x"]       / realizado) * mult_cc3x
            + ote_ajustado * (m["mrr_cc12x"]      / realizado) * mult_cc12x
            + ote_ajustado * (m["mrr_recorrente"] / realizado) * mult_recorrente
        )
    elif ote_ajustado is not None:
        ote_variavel = ote_ajustado
    else:
        ote_variavel = None

    m.update(
        pct_atingido=pct_atingido, ote_base=ote_base, ote_tier=ote_tier,
        mult_avista=mult_avista, mult_cc3x=mult_cc3x,
        mult_cc12x=mult_cc12x, mult_recorrente=mult_recorrente,
        acelerador=acelerador, acel_desc=acel_desc,
        ote_ajustado=ote_ajustado, ote_variavel=ote_variavel,
        comissao_bk_extra=_comissao_bk_extra(b, pct_atingido, m["booking_extras"]),
        trim=_trim_vendas(ctx, b) if b["calc_trim"] else None,
    )
    return m


def _montar_resultado(ctx, b, m):
    """Defaults + campos comuns (ajustes, proteção, total, rótulo) → dict final."""
    r = {
        "realizado": 0.0, "pct_atingido": 0.0,
        "ote_base": b["ote_prop"], "ote_tier": 1,
        "acelerador": 0.0, "acel_desc": "",
        "ote_ajustado": None, "ote_variavel": None,
        "mrr_avista": 0.0, "mrr_cc3x": 0.0, "mrr_cc12x": 0.0, "mrr_recorrente": 0.0,
        "mult_avista": 1.0, "mult_cc3x": 1.0, "mult_cc12x": 1.0, "mult_recorrente": 1.0,
        "booking_extras": 0.0, "comissao_bk_extra": 0.0,
        "faixa_atingida": None, "proxima_faixa": None,
        "dividas_pagas": 0.0, "comissao_dividas": 0.0,
        "opps_override": None,
        "trim": None, "b2g_ajuste": None,
        "arr_real": 0.0, "bk_real": 0.0,
        "meta_arr": 0.0, "pct_arr_b2g": 0.0, "pct_bk_b2g": 0.0,
        "pct_ponderado": 0.0, "pct_meta_atingida": 0.0,
        "pond_arr_b2g": 0.0, "pond_bk_b2g": 0.0, "pond_ma": 0.0,
        "meta_atingida_real": 0.0,
    }
    r.update(m)

    # Proteção é classificada como PREMIAÇÃO (exibição/rubrica próprias),
    # mas soma no total do mês normalmente.
    bonificacao_protecao = (b["pct_protecao"] * (b["ote_cheio"] or 0)
                            if b["pct_protecao"] > 0 else 0.0)
    ajuste_total, ajuste_n = ctx["ajustes"].get(b["email"], (0.0, 0))
    total = ((r["ote_variavel"] or 0) + r["comissao_bk_extra"]
             + r["comissao_dividas"] + bonificacao_protecao + ajuste_total)
    # Ajuste trimestral B2G soma ao variável total
    if r["b2g_ajuste"] and r["b2g_ajuste"].get("ajuste"):
        total += r["b2g_ajuste"]["ajuste"]

    # Rótulo alternativo do eixo Meta Atingida (gestores B2G configurados)
    if ctx.get("config_ok"):
        rotulo_aproveitamento = bool(b["is_b2g"] and b["is_gestor"] and b["email"] in (
            _cfg_list(ctx, "gestor_b2g_rotulo_aproveitamento", []) or []))
    else:
        rotulo_aproveitamento = bool(b["is_b2g"] and b["is_gestor"]
                                     and "marcelo.maestro" in b["email"])

    r.update({
        "rotulo_aproveitamento": rotulo_aproveitamento,
        "equipe": b["equipe"], "cargo": b["cargo"],
        "meta_mrr": b["meta_mrr"], "desconto": b["desconto"],
        "ote_cheio": b["ote_cheio"], "ote_02_cheio": b["ote_02_cheio"],
        "ote_prop": b["ote_prop"], "ote_02_prop": b["ote_02_prop"],
        "cliff_ote_01": b["cliff_ote_01"], "cliff_ote_02": b["cliff_ote_02"],
        "cliff_acel_01": b["cliff_acel_01"], "mult_acel_01": b["mult_acel_01"],
        "cliff_acel_02": b["cliff_acel_02"], "mult_acel_02": b["mult_acel_02"],
        "pct_bk_extra": b["pct_bk_extra"], "pct_protecao": b["pct_protecao"],
        "bonificacao_protecao": bonificacao_protecao,
        "ajuste_total": ajuste_total, "ajuste_n": ajuste_n,
        "total": total,
        "is_saving": b["is_saving"], "is_gd": b["is_gd"], "is_b2g": b["is_b2g"],
        "is_gestor": b["is_gestor"],
        "ote_indisponivel": b["ote_cheio"] is None,
        "trim_bloqueado": b["trim_bloqueado"],
        "meta_atingida_meta": b["meta_atingida_meta"],
    })
    return r




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
