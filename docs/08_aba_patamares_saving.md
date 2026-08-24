# Aba: Patamares Saving

## Contexto

Define uma estrutura de comissão **escalonada por faixas de atingimento** usada atualmente
pela equipe Saving. Em vez de um cliff simples (abaixo = zero, acima = OTE cheio),
a faixa atingida funciona como um multiplicador sobre o OTE × % Atingido — ou seja,
a comissão cresce linearmente com o desempenho dentro de cada faixa, e salta para um
multiplicador mais alto ao cruzar o limiar do próximo patamar.

Aparece apenas a partir de abril/2026, alinhado com a absorção da equipe Renovação por Saving.

## Estrutura

| Coluna | Nome | Tipo | Descrição |
|--------|------|------|-----------|
| A | Ano | int | Ano de referência |
| B | Mês | int | Mês de referência |
| C | Patamar | decimal | % mínimo de atingimento da meta para entrar nessa faixa |
| D | % | decimal | % do OTE Proporcional pago nessa faixa |

- Sem fórmulas — dados puros
- Chave: `Ano + Mês + Equipe + Patamar` (ver Implementação abaixo)
- Dados apenas de abr e mai/2026, com valores idênticos nos dois meses

## Patamares (abr e mai/2026)

| Atingimento ≥ | % do OTE pago |
|:-------------:|:-------------:|
| 60% | 55% |
| 70% | 70% |
| 80% | 85% |
| 90% | 95% |
| 100% | 105% |
| 110% | 110% (teto) |

## Regras de Aplicação

**Abaixo de 60%:** sem comissão (zero).

**Entre patamares — transição por degrau (stepwise):**
Não há interpolação. O vendedor recebe o % do patamar imediatamente inferior ao seu atingimento.

A fórmula é: `OTE Proporcional × % Atingido × Faixa Atingida`

```
Exemplos (OTE Proporcional = R$ 10.000):
  Atingimento = 75% → patamar 70% → R$ 10.000 × 0,75 × 0,70 = R$ 5.250
  Atingimento = 99% → patamar 90% → R$ 10.000 × 0,99 × 0,95 = R$ 9.405
  Atingimento = 100% → patamar 100% → R$ 10.000 × 1,00 × 1,05 = R$ 10.500
  Atingimento = 150% → patamar 110% → R$ 10.000 × 1,50 × 1,10 = R$ 16.500
```

**Acima de 110%:** a Faixa Atingida trava em 1,10 (teto da tabela), mas a comissão
continua crescendo linearmente com o % Atingido — `OTE × K × 1,10`. Não há cap no
valor final; o que não cresce mais é a Faixa, não a comissão.

**Base de cálculo:** o OTE Proporcional (aba Parâmetros, coluna I) já considera o
desconto de meses parciais. O impacto completo do cálculo está na aba Comissões Saving.

**Lookup Python:**
```python
def calc_comissao_patamar(atingimento: float, patamares: list[tuple], ote_proporcional: float) -> float:
    """
    patamares: lista de (patamar, percentual) ordenada do maior para o menor
    Ex: [(1.10, 1.10), (1.00, 1.05), (0.90, 0.95), ...]
    Fórmula: OTE Proporcional × % Atingido × Faixa Atingida
    """
    for patamar, percentual in sorted(patamares, reverse=True):
        if atingimento >= patamar:
            return ote_proporcional * atingimento * percentual
    return 0.0  # abaixo do cliff mínimo
```

**Lookup SQL (Snowflake):**
```sql
SELECT
    :atingimento * p.percentual * params.ote_proporcional AS comissao
FROM patamares p
WHERE p.equipe = 'Saving'
  AND p.ano    = :ano
  AND p.mes    = :mes
  AND p.patamar = (
      SELECT MAX(patamar)
      FROM patamares
      WHERE equipe  = 'Saving'
        AND ano     = :ano
        AND mes     = :mes
        AND patamar <= :atingimento
  )
```

## Implementação — Estrutura Genérica

A tabela hoje não tem coluna de Equipe (exclusiva de Saving na planilha).
Na implementação, adicionar `Equipe` como chave para que outras equipes possam
adotar esse modelo sem mudança de código.

**Tabela Snowflake sugerida:** `SUPERSET.COMISSOES.PATAMARES_COMISSAO`

```sql
CREATE TABLE SUPERSET.COMISSOES.PATAMARES_COMISSAO (
    ANO       INT            NOT NULL,
    MES       INT            NOT NULL,
    EQUIPE    VARCHAR(100)   NOT NULL,
    PATAMAR   DECIMAL(5, 4)  NOT NULL,  -- ex: 0.6000 = 60%
    PERCENTUAL DECIMAL(5, 4) NOT NULL,  -- ex: 0.5500 = 55%
    PRIMARY KEY (ANO, MES, EQUIPE, PATAMAR)
);
```

**Página de administração:** mesma dinâmica de Cargos e OTEs — cadastro manual
com funcionalidade de **copiar mês anterior** para não redigitar tudo.

## Associação com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Parâmetros | OTE Proporcional (col I) | Fator OTE na fórmula OTE × % Atingido × Faixa |
| Metas | Meta efetiva | Cálculo do % de atingimento para lookup |
| Comissões Saving | — | Uso completo explicado lá |
