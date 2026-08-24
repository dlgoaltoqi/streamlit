# Aba: Recuperação de Canc e Divs

## Contexto

Registra dois tipos de comissão por recuperação, além de uma equipe dedicada exclusivamente
a cancelamentos:

1. **Recuperação de Dívidas** — exclusiva da equipe Saving; clientes inadimplentes que pagaram.
2. **Recuperação de Cancelamentos (equipe Saving)** — contratos cancelados reativados por
   consultoras do Saving (Barbara Oliveira).
3. **Equipe Cancelamento** — Raquel Zanatta e Jessica Souza; atuam exclusivamente em
   recuperação de cancelamentos com modelo próprio de comissão (sem OTE, sem meta).

A aba da planilha tem duas tabelas lado a lado (coluna E vazia como separador).
A equipe Cancelamento surgiu após a planilha original e está implementada apenas no app.

---

## Tabela 1 — Recuperação de Dívidas

### Estrutura

| Campo | Tipo | Descrição |
|-------|------|-----------|
| Ano | int | Ano de referência |
| Mês | int | Mês de referência |
| Email | string | E-mail da consultora responsável |
| Valor | decimal | Valor total das dívidas recuperadas no período |
| Percentual Comissão | decimal | Percentual aplicado sobre o valor (padrão 2,5%) — armazenado por registro |
| Comissão | decimal | **Calculado:** `Valor × Percentual_Comissao` — exibido na tela, não armazenado |

- Um registro por consultora por mês
- Chave: `Ano + Mês + Email`

### Implementação — Form no Streamlit

A gestora preenche um formulário com **Ano, Mês, Email e Valor**. A coluna Comissão
é calculada automaticamente na exibição como `Valor × 2,5%`.

> O pagamento efetivo da comissão ainda depende do Cliff OTE01 ser atingido — essa
> verificação é feita em Comissões Saving (doc 11), não nesta tela. O valor exibido
> aqui é o potencial bruto caso o cliff seja cumprido.

**Tabela Snowflake:** `SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS`

```sql
CREATE TABLE SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS (
    ANO                 INT            NOT NULL,
    MES                 INT            NOT NULL,
    EMAIL               VARCHAR(200)   NOT NULL,
    VALOR               DECIMAL(12, 2) NOT NULL,
    PERCENTUAL_COMISSAO DECIMAL(5, 4)  NOT NULL DEFAULT 0.025,
    PRIMARY KEY (ANO, MES, EMAIL)
);
```

---

## Tabela 2 — Recuperação de Cancelamentos (cols F–P)

### Estrutura

| Coluna | Campo | Tipo | Descrição |
|--------|-------|------|-----------|
| F | Ano | int | Ano de referência da comissão |
| G | Mês | int | Mês de referência da comissão |
| H | Consultora | string (email) | E-mail da consultora responsável |
| I | Link | string (URL) | Link do registro no HubSpot |
| J | Contrato | int | ID do contrato no sistema |
| K | Fechamento | date | Data em que o cancelamento foi recuperado |
| L | Data de Início | date | Data de início do contrato original |
| M | Data de Renovação | date | Data de renovação/fim do contrato |
| N | Valor Original | decimal | Valor anual do contrato original |
| O | Valor Ajustado | decimal | Valor proporcional ao período recuperado (fórmula) |
| P | Comissão | decimal | 2% do Valor Ajustado (fórmula) |
| ~~Q~~ | ~~(auxiliar)~~ | — | **Ignorar — lixo de planilha** |
| ~~R~~ | ~~(auxiliar)~~ | — | **Ignorar — lixo de planilha** |

### Fórmulas

**Valor Ajustado (O):**
```
Valor Ajustado = (Data_Renovação − Fechamento) × Valor_Original
                 ─────────────────────────────────────────────
                       (Data_Renovação − Data_Início)
```
Lógica: proporciona o valor original pelo tempo de contrato restante a partir da recuperação.
Se o cliente foi recuperado no meio do ciclo, a consultora é comissionada apenas
sobre a fração que ainda resta até a renovação.

**Exemplo:**
- Contrato: R$ 12.000/ano, Data Início: 01/jan, Renovação: 31/dez
- Recuperado em 01/jul → restam 6 meses de 12
- Valor Ajustado = 6/12 × 12.000 = R$ 6.000
- Comissão = 6.000 × 2% = R$ 120

**Comissão (P):**
```
Comissão = Valor_Ajustado × 0.02
```

**SQL equivalente:**
```sql
SELECT
    YEAR(data_fechamento)                                        AS Ano,
    MONTH(data_fechamento)                                       AS Mes,
    consultora_email                                             AS Consultora,
    link_hubspot                                                 AS Link,
    id_contrato                                                  AS Contrato,
    data_fechamento                                              AS Fechamento,
    data_inicio                                                  AS Data_Inicio,
    data_renovacao                                               AS Data_Renovacao,
    valor_original                                               AS Valor_Original,
    DATEDIFF('day', data_fechamento, data_renovacao)
        * valor_original
        / NULLIF(DATEDIFF('day', data_inicio, data_renovacao), 0) AS Valor_Ajustado,
    DATEDIFF('day', data_fechamento, data_renovacao)
        * valor_original
        / NULLIF(DATEDIFF('day', data_inicio, data_renovacao), 0)
        * 0.02                                                   AS Comissao
FROM <tabela_cancelamentos_recuperados>
WHERE equipe = 'Saving'
```

### Status de Implementação

**Implementado.** O cálculo é feito automaticamente pelo app — não há entrada manual para
recuperação de cancelamentos.

**Fonte:** `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS` (migrado de
`SUPERSET.COMISSOES.CONSULTA_CANCELAMENTOS` em 21/08/2026, ver `docs/00_estado_atual.md`) —
tabela dbt com os negócios do pipeline "CS - Saving | Pedidos de Cancelamento" na etapa "Salvo",
joinando com a tabela `CONTRATOS` pelo número do contrato para obter datas e valor. Quando há
múltiplas versões do contrato, usa a de maior versão. A query filtra por
`EXISTS (... PARAMETROS ... IS_CANC_RECOVERY = TRUE)` para preservar o recorte por consultora que
a view legada fazia por e-mail hardcoded.

O Valor Ajustado é calculado na própria view:
```sql
DATEDIFF('second', DATA_FECHAMENTO_TS, DATA_RENOVACAO::TIMESTAMP) / 86400.0
    * VALOR_ORIGINAL
    / NULLIF(DATEDIFF('day', DATA_INICIO, DATA_RENOVACAO), 0)
```

### Consultoras da Recuperação de Cancelamentos (Saving)

- `barbara.oliveira@altoqi.com.br`

---

## Uso nas Comissões (Saving)

Os valores de Dívidas e Cancelamentos (Barbara) são somados à comissão base da equipe Saving.
O detalhamento de como entram no cálculo final está em `docs/11_aba_comissoes_saving.md`.

---

## Equipe Cancelamento (Raquel e Jessica)

Equipe independente do Saving, criada após a planilha original. Não tem OTE, meta ou acelerador —
a comissão é calculada diretamente sobre os contratos recuperados.

### Consultoras

| E-mail | Flag |
|--------|------|
| `raquel.zanatta@altoqi.com.br` | `IS_CANC_RECOVERY = TRUE` em `PARAMETROS` |
| `jessica.souza@altoqi.com.br` | `IS_CANC_RECOVERY = TRUE` em `PARAMETROS` |

As consultoras **não aparecem** em `METAS_CONSULTORES_CONSOLIDADAS` — são identificadas
exclusivamente pelo flag `IS_CANC_RECOVERY` na tabela `PARAMETROS`.

### Modelo de Cálculo

```
Comissão = SUM(VALOR_AJUSTADO) × PERCENTUAL_CANC_RECOVERY
```

- `VALOR_AJUSTADO` vem de `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS` (mesma fonte que Saving)
- `PERCENTUAL_CANC_RECOVERY` vem de `PARAMETROS` (padrão 2%)
- Não há cliff, OTE, acelerador ou forma de pagamento

### Visualização no App

- **Minha Comissão:** acesso normal — retorna comissão total sem colunas de meta/realizado
- **Minha Equipe (gestor do Saving):** as consultoras aparecem na tabela com `-` nas colunas
  inaplicáveis (Realizado, Meta, % Atingido, OTE Variável, Comissão Extra); Total preenchido
- **Exportar Comissões:** equipe "Cancelamento" disponível como filtro separado; exibe apenas
  Ano, Mês, Nome, Email, Equipe e Total
- **Fechamento:** equipe "Cancelamento" pode ser fechada independentemente do Saving;
  consultores buscados de `PARAMETROS` (não de `METAS`)
