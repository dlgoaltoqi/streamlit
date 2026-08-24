# Aba: Acel Form Pag

## Contexto

Tabela de multiplicadores de comissão por **forma de pagamento**, por equipe e mês.
Para cada venda, o multiplicador é determinado cruzando a equipe do vendedor com o
tipo de pagamento calculado na aba Negócios (campo `Acel Form Pag`).

## Estrutura

| Coluna | Nome | Tipo | Descrição |
|--------|------|------|-----------|
| A | Ano | int | Ano de referência |
| B | Mês | int | Mês de referência |
| C | Pipeline | string | Equipe/pipeline do vendedor |
| D | À Vista | decimal | Multiplicador para pagamento à vista |
| E | CC Até 3x | decimal | Multiplicador para cartão até 3 parcelas |
| F | CC Até 12x | decimal | Multiplicador para cartão até 12 parcelas |
| G | Recorrente | decimal | Multiplicador para pagamento recorrente |

- Sem fórmulas — dados puros
- Chave: `Ano + Mês + Pipeline`
- Preenchida manualmente pelo administrador

## Multiplicadores por Equipe

### Janeiro a Março de 2026

| Equipe | À Vista | CC Até 3x | CC Até 12x | Recorrente |
|--------|:-------:|:---------:|:----------:|:----------:|
| Ares | 1,30 | 1,20 | 1,15 | 1,00 |
| B2B / B2B Construtora / B2B Escritório | 1,30 | 1,20 | 1,15 | 1,00 |
| Farmer | 1,50 | 1,40 | 1,25 | 1,00 |
| FSB | 1,30 | 1,20 | 1,15 | 0,90 |
| Renovação ¹ | 1,30 | 1,20 | 1,15 | 0,90 |
| Saving | 1,20 | 1,15 | 1,10 | 1,00 |
| Sonia | 1,40 | 1,30 | 1,20 | 1,00 |

### A partir de Abril de 2026

| Equipe | À Vista | CC ² | Recorrente |
|--------|:-------:|:----:|:----------:|
| Ares | 1,30 | 1,15 | 1,00 |
| B2B Construtora / B2B Escritório | 1,30 | 1,15 | 1,00 |
| Farmer | 1,50 | 1,25 | 1,00 |
| FSB | 1,30 | 1,15 | 1,00 |
| Saving | — ³ | — ³ | — ³ |
| Sonia | 1,40 | 1,30 | 1,20 |

**¹ Renovação:** era uma equipe separada, absorvida pela equipe Saving. Não aparece mais a partir de abril.

**² CC unificado:** a partir de abril, CC Até 3x e CC Até 12x passaram a ter o mesmo multiplicador.
Na implementação, quando os dois valores forem iguais, exibir apenas **"CC"** (sem distinção de prazo).

**³ Saving:** deixou de usar acelerador de forma de pagamento a partir de abril.
Quando a equipe não tiver multiplicadores cadastrados, o acelerador deve ser tratado como 1,0 (neutro).

## Equipes Ausentes

- **GD e Governo:** não usam acelerador de forma de pagamento — suas comissões são calculadas de forma diferente.

## Associação com Outras Abas

O valor do campo `Acel Form Pag` calculado na aba **Negócios** (ver [docs/02_aba_negocios.md](02_aba_negocios.md))
é a chave de lookup nesta tabela:

| Valor em Negócios.Acel Form Pag | Coluna usada aqui |
|---------------------------------|-------------------|
| "À Vista" | D — À Vista |
| "CC 3x" | E — CC Até 3x |
| "CC 12x" | F — CC Até 12x |
| "Recorrente" | G — Recorrente |

**Lookup completo (SQL):**
```sql
SELECT
    n.ID_NEGOCIO,
    n.CONSULTOR,
    n.EQUIPE,
    n.Acel_Form_Pag,  -- calculado conforme doc 02_aba_negocios
    CASE n.Acel_Form_Pag
        WHEN 'À Vista'    THEN a.A_VISTA
        WHEN 'CC 3x'      THEN a.CC_ATE_3X
        WHEN 'CC 12x'     THEN a.CC_ATE_12X
        WHEN 'Recorrente' THEN a.RECORRENTE
        ELSE 1.0
    END AS MULTIPLICADOR_FORM_PAG
FROM Negócios n
LEFT JOIN Acel_Form_Pag a
    ON  a.ANO      = n.ANO
    AND a.MES      = n.MES
    AND a.PIPELINE = n.EQUIPE
```

## Requisitos de Implementação

- Página de administração para cadastrar/editar os multiplicadores por equipe e mês
- Quando CC Até 3x = CC Até 12x: exibir coluna unificada **"CC"** na interface
- Quando equipe não tiver registro (ex: Saving a partir de abr): usar multiplicador 1,0
- GD e Governo: não exibir esse acelerador na tela de comissões dessas equipes
