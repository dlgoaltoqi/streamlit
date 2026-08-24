# Aba: Negócios

## Fonte de Dados

Tabela Snowflake: `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`
(migrado de `SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM` em 03/08/2026 — mesmo
contrato de colunas; ver `docs/19_migracao_vendas_ouro.md`)

## Colunas

| Coluna | Campo Snowflake | Tipo | Descrição |
|--------|----------------|------|-----------|
| A — ANO | ANO | int | Ano da venda |
| B — MES | MES | int | Mês da venda |
| C — ID_DO_CLIENTE | ID_DO_CLIENTE | string | Identificador do cliente |
| D — CLIENTE | CLIENTE | string | Nome do cliente |
| E — ID_NEGOCIO | ID_NEGOCIO | string | Identificador do negócio |
| F — CONTRATO | CONTRATO | string | Número/código do contrato |
| G — ID_ITEM_DE_LINHA | ID_ITEM_DE_LINHA | string | Identificador do item de linha |
| H — CATEGORIA_DO_ITEM | CATEGORIA_DO_ITEM | string | Categoria do item vendido |
| I — BOOKING | BOOKING | decimal | Valor de booking |
| J — ARR | ARR | decimal | Annual Recurring Revenue |
| K — RESTANTE_ARR | RESTANTE_ARR | decimal | ARR restante |
| L — MRR | MRR | decimal | Monthly Recurring Revenue |
| M — NMRR | NMRR | decimal | Net MRR |
| N — MRR_EXPANSAO | MRR_EXPANSAO | decimal | MRR de expansão |
| O — MRR_RENOVACAO | MRR_RENOVACAO | decimal | MRR de renovação |
| P — CONSULTOR | CONSULTOR | string | Nome do consultor/vendedor |
| Q — EQUIPE | EQUIPE | string | Equipe do vendedor |
| R — VERTICAL | VERTICAL | string | Vertical de negócio |
| S — FECHAMENTO_NEGOCIO | FECHAMENTO_NEGOCIO | date | Data de fechamento do negócio |
| T — FECHAMENTO_AJUSTADO | FECHAMENTO_AJUSTADO | date | Data de fechamento ajustada |
| U — DATA_DE_INICIO | DATA_DE_INICIO | date | Data de início do contrato |
| V — DATA_DE_RENOVACAO | DATA_DE_RENOVACAO | date | Data de renovação |
| W — VIGENCIA | VIGENCIA | int/string | Vigência do contrato |
| X — DURACAO | DURACAO | int | Duração em meses |
| Y — TIPO_DO_CONTRATO | TIPO_DO_CONTRATO | string | Tipo do contrato |
| Z — TIPO_DA_VENDA | TIPO_DA_VENDA | string | Tipo da venda |
| AA — FORMA_DE_PAGAMENTO | FORMA_DE_PAGAMENTO | string | Forma de pagamento |
| AB — PARCELAS | PARCELAS | string | Número de parcelas (VARCHAR na view — cast para int no cálculo de Acel Form Pag) |
| AC — PIPELINE | PIPELINE | string | Stage/etapa do pipeline |
| AD — ITEM_DE_LINHA | ITEM_DE_LINHA | string | Descrição do item de linha |
| AE — FAMILIA_DO_ITEM_DE_LINHA | FAMILIA_DO_ITEM_DE_LINHA | string | Família do item |
| AF — APLICACAO_DO_ITEM_DE_LINHA | APLICACAO_DO_ITEM_DE_LINHA | string | Aplicação do item |

## Colunas Calculadas

Estas colunas **não existem na tabela Snowflake** e devem ser calculadas no app:

### AG — Acel Form Pag (Acelerador de Forma de Pagamento)

**Lógica (tradução da fórmula Excel):**

```
SE FORMA_DE_PAGAMENTO contém "Recorrente" → "Recorrente"
SENÃO SE PARCELAS = 1                      → "À Vista"
SENÃO SE PARCELAS <= 3                     → "CC 3x"
SENÃO SE PARCELAS <= 12                    → "CC 12x"
SENÃO SE PARCELAS > 12                     → "Recorrente"
SENÃO                                      → ""
```

**Fórmula Excel original:**
```
=SE(SEERRO(LOCALIZAR("Recorrente";AA2);0)>0;"Recorrente";
  SE(AB2=1;"À Vista";
    SE(AB2<=3;"CC 3x";
      SE(AB2<=12;"CC 12x";
        SE(AB2>12;"Recorrente";"")))))
```

**Implementação Python:**
```python
def calc_acel_form_pag(forma_pagamento: str, parcelas) -> str:
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
```

---

### AH — Pago >400k

Marca com `"n"` os negócios com BOOKING total acumulado ≥ R$ 400.000 **que ainda não foram
quitados**. Deals marcados como pagos em `SUPERSET.COMISSOES.DEALS_PAGOS_400K` têm a flag
removida e voltam ao cálculo regular de comissão B2G.

**Lógica completa:**
```
Pago >400k = "n"  se  SUM(BOOKING por ID_NEGOCIO) >= 400.000
                      E  ID_NEGOCIO não está em DEALS_PAGOS_400K
             ""   caso contrário
```

**Implementação SQL (Snowflake):**
```sql
CASE
    WHEN SUM(BOOKING) OVER (PARTITION BY ID_NEGOCIO) >= 400000
     AND ID_NEGOCIO NOT IN (SELECT ID_NEGOCIO FROM SUPERSET.COMISSOES.DEALS_PAGOS_400K)
    THEN 'n'
    ELSE ''
END AS "Pago >400k"
```

**Implementação Python (via Pandas):**
```python
pagos = set(deals_pagos_400k["ID_NEGOCIO"])
booking_total = df.groupby("ID_NEGOCIO")["BOOKING"].transform("sum")
df["Pago >400k"] = (
    (booking_total >= 400_000) & (~df["ID_NEGOCIO"].isin(pagos))
).map({True: "n", False: ""})
```

**Tabela de controle:** `SUPERSET.COMISSOES.DEALS_PAGOS_400K`

```sql
CREATE TABLE SUPERSET.COMISSOES.DEALS_PAGOS_400K (
    ID_NEGOCIO      VARCHAR(100)  NOT NULL PRIMARY KEY,
    DATA_MARCACAO   DATE          NOT NULL,
    USUARIO         VARCHAR(200),   -- e-mail de quem marcou
    OBSERVACAO      VARCHAR(500)
);
```

**Página de administração:**
Lista todos os `ID_NEGOCIO` com booking ≥ R$ 400k e seu status (pendente / pago).
O gestor pode marcar um deal como pago — a partir daí, a flag desaparece e o deal
entra no cálculo regular de comissão B2G na próxima atualização.

## Notas

- `Pago >400k` é exclusivo do cálculo B2G — nenhuma outra equipe usa esse filtro.
- `Acel Form Pag` classifica o tipo de pagamento para aplicar diferentes aceleradores de comissão.
- Ambas as colunas calculadas servem de insumo para as abas de **Comissões**.
