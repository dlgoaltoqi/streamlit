# Aba: Metas

## Contexto

Define a meta mensal de cada vendedor/gestor. É a base para calcular o percentual de atingimento
e, consequentemente, a comissão. Preenchida manualmente.

## Fonte de Dados

View Snowflake: `SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS`

> A tabela-base `superset.parcial.meta_consultor` é atualmente populada via um form Streamlit.
> Isso está previsto para mudar — provavelmente será alimentada por uma plataforma externa.
> Quando isso acontecer, a view pode precisar de ajuste na cláusula `FONTE = 'Form'`.

## Estrutura da Planilha (aba Metas)

| Coluna | Nome | Tipo | Descrição |
|--------|------|------|-----------|
| A | Ano | int | Ano de referência |
| B | Mês | int | Mês de referência |
| C | Consultor | string | Nome do vendedor/gestor |
| D | Email | string | E-mail (chave de identificação) |
| E | Equipe | string | Equipe |
| F | Cargo | string | `Consultor` ou `Gestor` |
| G | Gestor | string | E-mail do gestor responsável (vazio para gestores) |
| H | Tipo | string | Tipo de métrica da meta (ver abaixo) |
| I | Meta Cheia | decimal | Meta bruta do mês (sem ajustes) |
| J | Desconto na Meta | decimal | Fator de desconto para meses parciais (0–1). Normalmente incide sobre OTE Base e Meta. Em casos pontuais pode incidir apenas sobre um dos dois |
| K | Meta Proporcional | decimal | Meta efetiva após desconto. Vazia quando não há desconto |
| L | Ponderação | decimal | Peso da linha quando há múltiplas métricas para a mesma pessoa/mês |
| M | % Proteção | decimal | Proteção de OTE em meses de transição (ver abaixo) |
| N | Adicional na Meta | decimal | Ajuste pontual adicional à meta |

**Meta efetiva usada no cálculo:**
- Se `Meta Proporcional` preenchida → usa `Meta Proporcional`
- Se `Meta Proporcional` vazia → usa `Meta Cheia`

## Tipos de Meta por Equipe

| Equipe | Tipo(s) | Métrica |
|--------|---------|---------|
| Ares | MRR | MRR mensal |
| B2B Construtora | MRR | MRR mensal |
| B2B Escritório | MRR | MRR mensal |
| Farmer | MRR | MRR mensal |
| FSB | MRR | MRR mensal |
| Saving | MRR | MRR mensal |
| Sonia | MRR | MRR mensal |
| GD | Opps | Oportunidades qualificadas (COUNT DISTINCT ID_CONTATO) |
| Governo | ARR + Booking | 2 linhas por pessoa (ver Ponderação abaixo) |
| Gestores Governo | Booking + Meta Atingida | 2 linhas: resultado da equipe + % atingimento da equipe |

## Ponderação — Pessoas com Múltiplas Métricas

Quando uma pessoa tem mais de uma linha no mesmo mês, a `Ponderação` define o peso de cada uma:

**Consultores Governo (B2G):**
- ARR → Ponderação = 0.4
- Booking → Ponderação = 0.6

**Gestor Governo (ex: Marcelo Maestro):**
- Booking → Ponderação = 0.8 (resultado absoluto da equipe)
- Meta Atingida → Ponderação = 0.2 (% de atingimento médio da equipe)

## Desconto e Proporcionalização

Usado quando o vendedor não trabalhou o mês cheio (férias, admissão, desligamento, transição).
O Desconto incide normalmente sobre **OTE Base e Meta**. Em casos pontuais pode incidir
apenas sobre um dos dois — isso é definido caso a caso pelo administrador.

**Quando `Desconto` é uma fração (0 < Desconto < 1):**
```
Meta Proporcional  = Meta Cheia  × (1 − Desconto)
OTE Proporcional   = OTE Cheio   × (1 − Desconto)
```
Exemplo: Desconto = 0,5 → vendedor trabalhou 50% do mês → meta e OTE reduzidos à metade.

**Quando `Desconto = Meta Cheia`:**
Indica que não há desconto aplicado — pessoa trabalhou o mês inteiro.
`Meta Proporcional` fica vazia e o cálculo usa `Meta Cheia` diretamente.

**Caso especial — Transição de equipe:**
Quando o vendedor muda de equipe no meio do mês, aparece **duas vezes**: uma linha por equipe,
cada uma com seu próprio Desconto representando a fração do mês naquele time.

Exemplo: Renata Scheffer (jan/2026) — aparece em FSB e GD no mesmo mês com frações complementares do mês.

## % Proteção

Percentual aplicado diretamente sobre o **OTE Base** do consultor como bonificação bruta, sem
dependência de atingimento de meta. Usado em meses de transição para garantir renda mínima.

**Fórmula:**
```
Premiação = % Proteção × OTE Base
```

**Onde fica configurado:** `SUPERSET.COMISSOES.PARAMETROS` (coluna `PERCENTUAL_PROTECAO`),
gerenciado pela página Admin → Parâmetros de Comissão.

**Impacto no total:** a Premiação soma no total de comissão do mês normalmente
(`total = OTE Variável + Booking Extra + Dívidas + Premiação + Ajustes`).

**Classificação (28/07/2026):** o valor deixou de ser tratado como "comissão extra"
e passou a se chamar **Premiação**, com exibição própria — mas continua dentro do total.

**Exibição:** grupo próprio "Premiação" no Minha Comissão (separado de Comissões
Extras); coluna "Premiação" no Minha Equipe (exibida só quando houver valor, somada
no Total); colunas "% Proteção" / "Premiação" (antiga "Bonificação") com categoria
"Premiação" no Exportar Comissões. Só é exibido quando `% Proteção > 0`.

## Adicional na Meta

> **Backlog** — pode não ser usado na implementação inicial.

Modificador pontual da meta, positivo ou negativo. Aplicado **após** o Desconto:

```
Meta Efetiva = Meta Proporcional (ou Meta Cheia se sem desconto) + Adicional na Meta
```

Permite correções que não se encaixam no fluxo normal de proporcionalização.

## Definição da View

```sql
CREATE OR REPLACE VIEW SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS AS
SELECT
    ANO,
    MES,
    EMAIL                                                       AS CONSULTOR,
    EQUIPE,
    mc.SENIORIDADE,
    'Form'                                                      AS FONTE,
    PERCENTUAL_DESCONTO_METAS,
    meta_nmrr_bruto + meta_expansao_bruto + meta_renovacao_bruto AS META_MRR_BRUTO,
    meta_nmrr + meta_expansao + meta_renovacao                  AS META_MRR,
    META_NMRR_BRUTO,
    META_NMRR,
    META_EXPANSAO_BRUTO,
    META_EXPANSAO,
    META_RENOVACAO_BRUTO,
    META_RENOVACAO,
    0                                                           AS META_REATIVACAO,
    0                                                           AS META_DEVEDOR,
    META_OTR_BRUTO,   -- exibido como "Meta Booking Bruto" no app
    META_OTR          -- exibido como "Meta Booking" no app
FROM
    SUPERSET.PARCIAL.META_CONSULTOR mc
WHERE
    DATE_FROM_PARTS(ANO, MES, 1) >= '2025-10-01'
    AND (meta_nmrr > 0 OR meta_expansao > 0 OR meta_renovacao > 0 OR meta_otr > 0);
```

## Campos da View

| Campo | Descrição |
|-------|-----------|
| ANO, MES | Período |
| CONSULTOR | **E-mail** do consultor (chave) — a coluna chama-se CONSULTOR mas contém o e-mail; herança de nomenclatura antiga |
| EQUIPE | Equipe |
| SENIORIDADE | Senioridade do cargo |
| FONTE | Origem do registro (`'Form'` hardcoded — campo previsto para ser removido) |
| PERCENTUAL_DESCONTO_METAS | Equivalente ao "Desconto na Meta" da planilha |
| META_MRR_BRUTO | MRR total bruto (NMRR + Expansão + Renovação, sem desconto) |
| META_MRR | MRR total líquido (após desconto) |
| META_NMRR_BRUTO / META_NMRR | Componente New MRR (bruto/líquido) |
| META_EXPANSAO_BRUTO / META_EXPANSAO | Componente Expansão (bruto/líquido) |
| META_RENOVACAO_BRUTO / META_RENOVACAO | Componente Renovação (bruto/líquido) |
| META_REATIVACAO | Reativação — fixo em 0 (não implementado) |
| META_DEVEDOR | Devedor — fixo em 0 (não implementado) |
| META_OTR_BRUTO / META_OTR | Meta Booking bruta/líquida — coluna real na view é `META_OTR`/`META_OTR_BRUTO`; o app exibe como "Booking" sem renomear no Snowflake |

> **Campos ausentes na view:** CARGO, GESTOR, TIPO (tipo de métrica), PONDERAÇÃO não existem
> na view nem na tabela-base `META_CONSULTOR`. CARGO vem de `SUPERSET.COMISSOES.PARAMETROS`
> (form admin). TIPO e PONDERAÇÃO vêm de `SUPERSET.COMISSOES.PONDERACOES_META`.

## Relação com Outras Abas

- **Cargos e OTEs** → fornece o OTE base do cargo; junto com a Ponderação e % Proteção, determina a comissão máxima possível
- **Negócios** → fornece o realizado de MRR/ARR/Booking para comparar com a meta
- **Realizado GD** → fornece o realizado de Opps para comparar com a meta dos SDRs/BDRs
- **Comissões** → usa a meta efetiva desta aba para calcular % atingimento e valor da comissão

## Notas de Implementação

- A view filtra `>= 2025-10-01` e apenas quem tem ao menos uma meta > 0 (MRR ou Booking — este último cobre GD/Opps e B2G).
- Consultores de Governo usam `META_BOOKING` como meta principal. `META_ARR` não existe na view — é sempre derivada no app como `META_BOOKING × 0,5` (regra fixa).
- `META_REATIVACAO` e `META_DEVEDOR` são fixos em 0 — campos reservados para expansão futura.
- O campo `FONTE` (`'Form'` hardcoded) está previsto para ser removido da view — hoje há apenas uma fonte de dados e isso continuará assim.
