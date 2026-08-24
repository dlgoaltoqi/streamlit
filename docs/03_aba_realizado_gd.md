# Aba: Realizado GD

## Contexto

GD = **Geração de Demanda**. Esta aba registra o realizado de SDRs/BDRs por pessoa e por mês.
É utilizada para calcular comissões dos profissionais de Geração de Demanda.

## Fonte de Dados

View Snowflake: `SUPERSET.COMISSOES.REALIZADO_GD`

Os dados na planilha são uma **agregação** da view: a view retorna um registro por lead,
e a planilha consolida em uma linha por pessoa por mês.

## Estrutura da Planilha (aba Realizado GD)

| Coluna | Nome | Descrição |
|--------|------|-----------|
| A | Ano | Ano de referência |
| B | Mês | Mês de referência (número) |
| C | Email | E-mail do proprietário (SDR/BDR) |
| D | Realizado | Quantidade realizada no período |

- **46 linhas de dados** (ref. arquivo 2026)
- Sem fórmulas — dados importados/colados manualmente da view

> **Confirmado pelo Power BI:** *"O valor em 'Realizado' é a quantidade distinta de 'ID do Contato'."*
> Ou seja: `COUNT(DISTINCT ID_CONTATO)` — contatos únicos qualificados por SDR/BDR no período.

## Definição da View `SUPERSET.COMISSOES.REALIZADO_GD`

> **Renomeação do schema HUBSPOT_PRATA (18/08/2026):** as tabelas do schema
> passaram para o padrão `HUBSPOT_*`. `LEADS`, `CONTACTS` e `DEALS` ganharam
> views de compatibilidade com o nome antigo, então seguem funcionando; a
> `ASSOCIATIONS_LEADS_DEAL` não ganhou, e a view quebrou até ser apontada para
> `HUBSPOT_ASSOCIATIONS_LEADS_DEAL`. Nessa tabela as colunas do join também
> mudaram de acentuadas para MAIÚSCULAS (`ID_LEAD`, `ID_DEAL`). Reaplicar a view
> com `validacao/aplicar_view_realizado_gd.py` (usa `COPY GRANTS` e o role
> `DATA_ENGINEER`, dono da view).

```sql
CREATE OR REPLACE VIEW SUPERSET.COMISSOES.REALIZADO_GD AS
WITH PROPRIETARIO_PRATA_01 AS (
    -- Une owners ativos e arquivados, priorizando os ativos (PRIORIDADE 1)
    SELECT ID, EMAIL, TEAMS, 2 AS PRIORIDADE
    FROM HUBSPOT.HUBSPOT_BRONZE.OWNERS_ARCHIVED

    UNION

    SELECT ID, EMAIL, TEAMS, 1 AS PRIORIDADE
    FROM HUBSPOT.HUBSPOT_BRONZE.HUBSPOT_OWNERS
),

PROPRIETARIO_PRATA_02 AS (
    -- Mantém apenas o registro mais recente/ativo por owner
    SELECT ID, EMAIL, TEAMS AS EQUIPE
    FROM PROPRIETARIO_PRATA_01
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY PRIORIDADE ASC) = 1
),

LISTA_DE_LEADS AS (
    SELECT
        LEADS."Id do lead"                                                              AS ID_LEAD,
        LEADS."Nome do lead"                                                            AS NOME_LEAD,
        CONTATOS."Id do contato"                                                        AS ID_CONTATO,
        PROPRIETARIO_PRATA_02.EMAIL                                                     AS PROPRIETARIO,
        COALESCE(
            LEADS."Equipe original de distribuição",
            REPLACE(GET(PROPRIETARIO_PRATA_02.EQUIPE, 0):name, '"', '')
        )                                                                               AS EQUIPE,
        LEADS."Data Qualificação"                                                       AS DATA_QUALIFICACAO,
        LEADS."Reunião realizada?"                                                      AS REUNIAO_REALIZADA,
        DEALS."Id do negócio"                                                           AS ID_NEGOCIO,
        DEALS."Data de fechamento"                                                      AS DATA_DE_FECHAMENTO_NEGOCIO,
        DEALS."Estágio do negócio"                                                      AS ESTAGIO_NEGOCIO,
        DEALS."Status do negócio"                                                       AS STATUS_NEGOCIO
    FROM
        HUBSPOT.HUBSPOT_PRATA.LEADS AS LEADS
    LEFT JOIN
        HUBSPOT.HUBSPOT_PRATA.CONTACTS AS CONTATOS
            ON CONTATOS."Id do contato" = LEADS."Id do contato"
    LEFT JOIN
        PROPRIETARIO_PRATA_02
            ON PROPRIETARIO_PRATA_02.ID = LEADS."Id do proprietário"
    LEFT JOIN
        HUBSPOT.HUBSPOT_PRATA.HUBSPOT_ASSOCIATIONS_LEADS_DEAL AS ALD
            ON ALD.ID_LEAD = LEADS."Id do lead"
    LEFT JOIN
        HUBSPOT.HUBSPOT_PRATA.DEALS AS DEALS
            ON DEALS."Id do negócio" = ALD.ID_DEAL
    WHERE
        COALESCE(
            LEADS."Equipe original de distribuição",
            REPLACE(GET(PROPRIETARIO_PRATA_02.EQUIPE, 0):name, '"', '')
        ) ILIKE ANY ('%sdr%', '%bdr%')
        AND LEADS."Data Qualificação" >= '2026-01-01'
)

SELECT *
FROM LISTA_DE_LEADS
GROUP BY ALL;
```

## Colunas da View

| Campo | Descrição |
|-------|-----------|
| ID_LEAD | Identificador do lead no HubSpot |
| NOME_LEAD | Nome do lead |
| ID_CONTATO | ID do contato associado |
| PROPRIETARIO | E-mail do SDR/BDR responsável |
| EQUIPE | Equipe (SDR ou BDR) — vem da equipe original do lead ou da equipe do proprietário |
| DATA_QUALIFICACAO | Data em que o lead foi qualificado |
| REUNIAO_REALIZADA | Flag se reunião foi realizada |
| ID_NEGOCIO | ID do negócio HubSpot associado ao lead (via associação lead→deal) |
| DATA_DE_FECHAMENTO_NEGOCIO | Data de fechamento do negócio |
| ESTAGIO_NEGOCIO | Estágio atual do negócio |
| STATUS_NEGOCIO | Status do negócio |

## Filtros Aplicados na View

- **Equipe:** apenas SDR e BDR (`ILIKE ANY ('%sdr%', '%bdr%')`)
- **Período:** apenas leads qualificados a partir de `2026-01-01`

> O comentário `-- LEADS."Data Qualificação" < '2026-02-01'` indica que o filtro de data final era usado em versões anteriores para restringir a um mês específico. No Streamlit, esse filtro deve ser dinâmico (controlado pelo usuário).

## Como Agregar para a Planilha

Para reproduzir a coluna "Realizado" da planilha a partir da view:

```sql
SELECT
    YEAR(DATA_QUALIFICACAO)      AS Ano,
    MONTH(DATA_QUALIFICACAO)     AS Mes,
    PROPRIETARIO                 AS Email,
    COUNT(DISTINCT ID_CONTATO)   AS Realizado
FROM SUPERSET.COMISSOES.REALIZADO_GD
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
```

## Requisito: Override Manual do Realizado

O CRM nem sempre reflete ajustes feitos fora do sistema. Por isso, o app deve permitir sobrescrever
o valor calculado pela view com um valor manual por pessoa/mês.

**Regra de prioridade:**
1. Se existir um valor de override cadastrado para aquele Email + Ano + Mês → usa o override
2. Caso contrário → usa o `COUNT(DISTINCT ID_CONTATO)` calculado da view

**Como implementar:**
- Tabela de overrides no Snowflake (ex: `SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE`) com colunas: `ANO`, `MES`, `EMAIL`, `REALIZADO_MANUAL`, `MOTIVO` (opcional, para rastreabilidade)
- Página de administração no app para cadastrar/editar os overrides
- No cálculo final, fazer um LEFT JOIN da view com a tabela de overrides e usar `COALESCE(override.REALIZADO_MANUAL, view.Realizado)`

## Uso nas Comissões

A coluna "Realizado" desta aba é insumo para o cálculo de comissões dos SDRs/BDRs.
Provavelmente é comparada com uma meta (definida na aba **Metas**) para calcular o percentual de atingimento.
