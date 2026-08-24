# Aba: Comissões

## Contexto

Define as regras de cálculo de comissão mensal para **consultores e gestores** das equipes
que usam o modelo de OTE tiers + aceleradores + Acel Form Pag.

> **No app Streamlit não existe uma página separada por equipe.** O motor de cálculo unificado
> (ver `docs/01_visao_geral.md`) determina automaticamente quais regras aplicar com base em
> `equipe + mês`. As equipes e períodos abaixo definem o escopo de aplicação destas regras.

**Equipes e períodos cobertos por este modelo:**
- Ares, B2B Construtora, B2B Escritório, Farmer, FSB, Sonia — todo o período
- Saving — Jan a Mar 2026 (a partir de Abr/2026 usa o modelo de Patamares, ver `docs/11_aba_comissoes_saving.md`)

**Equipes com modelo próprio (não usam estas regras):**
- Governo → ver `docs/13_aba_comissoes_b2g.md` e `docs/14_aba_comissoes_gestao_b2g.md`
- GD → ver `docs/12_aba_comissoes_gd.md`
- Saving Abr/2026+ → ver `docs/11_aba_comissoes_saving.md`

## Escopo — Equivalente ao FILTER do Excel

Na planilha, a aba é populada via FILTER de Metas. No app, o mesmo critério define
quais linhas de Metas recebem este conjunto de regras:

```
Ano > 2025
  E Equipe ∉ {Governo, GD}
  E NÃO (Equipe = Saving E Mês ≥ 4)
```

## Estrutura — 40 Colunas (A:AN)

### Bloco 1 — Identificação (A–H)

Espelhado de Metas via FILTER. Campos: Ano, Mês, Consultor, Email, Equipe, Cargo, Gestor, Tipo.

---

### Bloco 2 — Realizado vs. Meta (I–K)

| Col | Campo | Fórmula |
|-----|-------|---------|
| I | Realizado | Consultor MRR → `SUMIFS(Negócios!MRR, Ano, Mês, Email)`. Gestor → soma do Realizado dos consultores da equipe |
| J | Meta | `SUMIFS(Metas!Meta_Proporcional, Ano, Mês, Email, Tipo)` |
| K | % Atingido | `IFERROR(I / J, 0)` |

---

### Bloco 3 — Cliffs e Breakdown por Forma de Pagamento (L–X)

| Col | Campo | Fórmula / Fonte |
|-----|-------|-----------------|
| L | Cliff (display) | Exibe os cliffs do Parâmetros (G, J, M) formatados como texto — apenas informativo |
| M | Parte da Venda — À Vista | `SUMIFS(Negócios!MRR, Ano, Mês, Email, Acel_Form_Pag="À Vista", Equipe)`. Gestor → soma da equipe |
| N | % À Vista | `IFERROR(M / I, 0)` |
| O | Mult À Vista | Lookup em Acel Form Pag — coluna D |
| P | Parte da Venda — CC 3x | `SUMIFS(Negócios!MRR, ..., Acel_Form_Pag="CC 3x")` |
| Q | % CC 3x | `IFERROR(P / I, 0)` |
| R | Mult CC 3x | Lookup em Acel Form Pag — coluna E |
| S | Parte da Venda — CC 12x | `SUMIFS(Negócios!MRR, ..., Acel_Form_Pag="CC 12x")` |
| T | % CC 12x | `IFERROR(S / I, 0)` |
| U | Mult CC 12x | Lookup em Acel Form Pag — coluna F |
| V | Parte da Venda — Recorrente | `SUMIFS(Negócios!MRR, ..., Acel_Form_Pag="Recorrente")` |
| W | % Recorrente | `IFERROR(V / I, 0)` |
| X | Mult Recorrente | Lookup em Acel Form Pag — coluna G |

---

### Bloco 4 — OTE e Comissão Principal (Y–AB)

| Col | Campo | Fórmula |
|-----|-------|---------|
| Y | OTE Base | `MAX(OTE03_Prop se Cliff03 ≤ K, OTE02_Prop se Cliff02 ≤ K, OTE01_Prop)` — pega o tier mais alto para o qual o % atingido se qualifica |
| Z | Acelerador OTE | `MAX(Acel01 se CliffAcel01 ≤ K, Acel02 se CliffAcel02 ≤ K, ..., 1) × IF(K ≥ Cliff_OTE01, 1, 0)` — zero se abaixo do cliff mínimo |
| AA | OTE Ajustado | `Y × Z × K` |
| AB | OTE Variável | `(AA×N×O) + (AA×Q×R) + (AA×T×U) + (AA×W×X)` — OTE ajustado distribuído pelas formas de pagamento com seus multiplicadores |

**AB é a comissão principal do mês.**

Interpretação de Y: o vendedor sobe automaticamente para o tier de OTE mais alto que sua performance justifica. O Acelerador (Z) amplifica a comissão quando o vendedor supera os cliffs de aceleração; é zero se nem o cliff mínimo for atingido.

---

### Bloco 5 — Booking Extra (AC–AD)

| Col | Campo | Fórmula |
|-----|-------|---------|
| AC | Bookings Extras | Soma de BOOKING das linhas com CATEGORIA_DO_ITEM ∈ {Implantação, Serviço, Curso} **e MRR = 0** (itens que geraram booking mas não MRR recorrente). Aplica-se a todas as equipes. Gestor: soma da equipe |
| AD | Comissão Bookings Extras | `Parâmetros!W × AC × IF(K ≥ Cliff_Booking_Extra, 1, 0)` → na prática: `2% × AC` se cliff mínimo atingido |

---

### Bloco 6 — Trimestral (AE–AN)

Calculado apenas nos meses de fechamento de trimestre (3, 6, 9, 12).
Fora desses meses, todas as colunas retornam `""`.

**Individual:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AE* | Realizado Trimestral Individual | Soma dos 3 meses do trimestre para o mesmo e-mail |
| AF* | Meta Trimestral Individual | Soma das metas dos 3 meses do trimestre |
| AG* | % Trimestral Individual | `IFERROR(AE / AF, 0)` |

**Equipe:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AH* | Realizado Trimestral Equipe | Soma do trimestre de todos os consultores da equipe (exclui gestores) |
| AI* | Meta Trimestral Equipe | Soma das metas da equipe no trimestre |
| AJ* | % Trimestral Equipe | `IFERROR(AH / AI, 0)` |

**Comissões trimestrais:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AK* | Comissão Trimestral Individual | `IF(% trim ≥ 100%): Gestor → AG × 0,6 / Consultor → AG × 0,3` |
| AL* | Comissão Trimestral Equipe | `IF(equipe ≥ 100% E individual ≥ Cliff_OTE01): AG × 0,3` |

> *Mapeamento de colunas: as letras exatas podem variar — o relevante é a sequência lógica acima.

**Interpretação — como o bônus trimestral é pago:**
Os valores de AK e AL são fatores (ex: `1,05 × 0,3 = 0,315`) aplicados sobre o **salário base** do colaborador pelo Departamento Pessoal. Não são valores em R$ calculados diretamente nesta aba.

Exemplo: consultor com 110% de atingimento trimestral → fator = `1,10 × 0,3 = 0,33` → DP paga 33% de um salário.

---

## Fluxo Completo de Cálculo

```
Realizado (I) ÷ Meta (J) = % Atingido (K)
    │
    ├── K qualifica qual tier de OTE? → OTE Base (Y)
    ├── K qualifica qual acelerador? → Acelerador (Z)
    │
    └── OTE Ajustado (AA) = Y × Z × K
            │
            └── Distribuído por forma de pagamento com multiplicadores
                = OTE Variável (AB) ← comissão principal do mês

Booking Extras (AC) × 2% × IF(cliff OK) = Comissão Booking Extra (AD)

Trimestral: só em meses 3/6/9/12 → fatores de salário (AK, AL)
```

---

## Saídas da Aba

Esta aba **não tem coluna total**. Os componentes de comissão calculados aqui (AB, AD, AK, AL)
alimentam outras planilhas usadas por líderes e pelo Departamento Pessoal, que aplicam a
formatação e consolidação final.

---

## Notas de Implementação

- **Dívidas (AE/AF na planilha original):** colunas de comissão sobre dívidas eram regra antiga; não implementar nesta aba. Comissão sobre dívidas hoje é exclusiva do Saving e está documentada em `docs/11_aba_comissoes_saving.md`.
- **Saving até abril:** o FILTER inclui Saving para meses < 5 de 2026. A partir de maio, Saving usa aba própria.
- **Gestor vs. Consultor:** gestores não têm Realizado próprio — agregam a equipe. Verificar campo `Cargo` (col F) = `"Gestor"` para alternar a lógica.
- **OTE tiers:** usar a mesma lógica MAXIFS da planilha — pegar o maior OTE cujo cliff foi atingido.
- **Booking Extra — categorias:** todas as equipes usam Implantação + Serviço + Curso, **apenas itens com MRR = 0**. Filtrar `CATEGORIA_DO_ITEM IN ('Implantação','Serviço','Curso') AND MRR = 0`.

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Metas | Identificação + Meta Proporcional | Filtro base + coluna J |
| Negócios | MRR por forma de pagamento + Booking por categoria | Colunas I, M, P, S, V, AC |
| Parâmetros | OTE tiers, cliffs, aceleradores, % booking extra | Colunas Y, Z, AD |
| Acel Form Pag | Multiplicadores por equipe/forma de pagamento | Colunas O, R, U, X |
