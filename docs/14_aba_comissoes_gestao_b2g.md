# Aba: Comissões Gestão B2G

## Contexto

Aba de cálculo de comissão mensal para **gestores** da equipe **Governo**.
Consultores têm aba separada (`docs/13_aba_comissoes_b2g.md`).

A estrutura é similar à aba de consultores B2G — dois eixos ponderados —
mas o segundo eixo mede o **desempenho da equipe** (proporção de consultores
que atingiram a meta), não apenas um segundo produto.

## Escopo

Filtro via `UNIQUE(FILTER(Metas, Ano > 2025, Equipe = "Governo", Cargo = "Gestor"))`.
Cobre todos os meses a partir de 2026. Atualmente 1 gestor (Marcelo Maestro).

## Estrutura — 3 linhas de cabeçalho + dados (A:AL)

A aba usa 3 linhas de cabeçalho (igual à aba de consultores B2G):
- Linha 1: grupos — Booking, Meta Atingida, Trimestral, Ajuste Trimestral
- Linha 2: sub-grupos de Ajuste Trimestral — Booking, Meta Atingida
- Linha 3: rótulos de coluna
Painel congelado nas 3 primeiras linhas e nas colunas A–F.

---

### Bloco 1 — Identificação (A–F)

Espelhado de Metas via FILTER/UNIQUE: Ano, Mês, Consultor, Email, Equipe, Cargo.
*(Apenas Gestores — sem coluna Gestor, pois o próprio consultor é o gestor)*

---

### Bloco 2 — Eixo Booking (G–J)

| Col | Campo | Fórmula |
|-----|-------|---------|
| G | Realizado Booking | `SUMIFS('Comissões B2G'!L:L, Ano, Mês)` — soma o Booking realizado de todos os consultores da equipe |
| H | Meta Booking | `SUMIFS(Metas!Meta_Proporcional, Ano, Mês, Email, Tipo="Booking")` |
| I | % Atingido Booking | `IFERROR(G / H, 0)` |
| J | Ponderação Booking | `SUMIFS(Metas!Ponderação, Ano, Mês, Email, Tipo="Booking")` — ex: 0,80 |

---

### Bloco 3 — Eixo Meta Atingida (K–N)

Mede a proporção de consultores da equipe que atingiram sua meta de Booking.

| Col | Campo | Fórmula |
|-----|-------|---------|
| K | Realizado Meta Atingida | `COUNTIFS('Comissões B2G'!N, ">=1") / COUNTIFS(...)` — proporção de consultores com % Booking ≥ 100% |
| L | Meta Meta Atingida | `SUMIFS(Metas!Meta_Proporcional, ..., Tipo="Meta Atingida")` — ex: 0,80 (alvo: 80% dos consultores devem bater a meta). Configurável por mês em Metas |
| M | % Atingido Meta Atingida | `IFERROR(K / L, 0)` |
| N | Ponderação Meta Atingida | `SUMIFS(Metas!Ponderação, ..., Tipo="Meta Atingida")` — ex: 0,20 |

---

### Bloco 4 — Atingimento Ponderado e Comissão Mensal (O–S)

| Col | Campo | Fórmula |
|-----|-------|---------|
| O | Atingido Ponderado | `(I × J) + (M × N)` — média ponderada dos dois eixos |
| P | OTE Base | `MAX(OTE tiers baseados em % Booking (I))` — mesmo MAXIFS da aba de consultores |
| Q | Acelerador OTE | `MAX(aceleradores baseados em % Booking (I)) × IF(I ≥ Cliff OTE01, 1, 0)` |
| R | OTE Ajustado | `P × Q` |
| S | OTE Variável | `R × O` — **comissão principal do mês** |

Tanto o OTE Base quanto o Acelerador são determinados pelo **% Booking** (I).
A comissão final multiplica o OTE Ajustado pelo Atingimento Ponderado dos dois eixos.

---

### Bloco 5 — Trimestral Individual (T–W)

Calculado apenas nos meses de fechamento de trimestre (3, 6, 9, 12).
Baseado **apenas no Booking** — sem componente Meta Atingida aqui.

| Col | Campo | Fórmula | Condição |
|-----|-------|---------|----------|
| T | Realizado Trimestral Booking | Soma de G dos 3 meses do trimestre | — |
| U | Meta Trimestral Booking | Soma de H dos 3 meses | — |
| V | % Trimestral | `IFERROR(T / U, 0)` | — |
| W | Comissão Trimestral Individual | `V × 0,9` | V ≥ 100% no trimestre |

O fator **0,9** (90% de um salário) é aplicado sobre o salário base pelo DP.
Não há trimestral por equipe nesta aba — o gestor é avaliado individualmente.

---

### Bloco 6 — Ajuste Trimestral (X–AL)

Recalcula a comissão usando os acumulados do trimestre e paga a diferença
se o resultado for superior à soma dos mensais pagos.

**Acumulados Booking:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| X | Realizado Booking (trim) | Soma de G dos 3 meses (= T) |
| Y | Meta Booking (trim) | Soma de H dos 3 meses (= U) |
| Z | % Atingido Booking (trim) | X ÷ Y (= V) |
| AA | Ponderação Booking | Ponderação do mês atual |

**Acumulados Meta Atingida:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AB | Realizado Meta Atingida (trim) | Baseado na coluna N desta aba — os % mensais de Meta Atingida acumulados no trimestre |
| AC | Meta Meta Atingida (trim) | Meta do período (= L, ex: 0,80) |
| AD | % Atingido Meta Atingida (trim) | AB ÷ AC |
| AE | Ponderação Meta Atingida | Ponderação do mês atual |

**Recálculo da comissão:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AF | Atingido Ponderado (trim) | `(Z × AA) + (AD × AE)` |
| AG | OTE Base (trim) | Soma de P dos 3 meses |
| AH | Acelerador (trim) | LET: acelerador recalculado sobre % Booking trimestral (Z) com mesmo cliff |
| AI | OTE Ajustado (trim) | `AG × AH` |
| AJ | OTE Variável (trim) | `AI × AF` |

**Comparação e ajuste:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AK | Pago no Mensal | Soma de S dos 3 meses |
| AL | Ajuste | `IF(AJ > AK, AJ − AK, "")` — sem estorno se trimestral for menor |

---

## Fluxo de Cálculo

```
Booking equipe (G) ÷ Meta Booking (H) = % Booking (I) × Peso 80% (J)
Prop. consultores com meta (K) ÷ Meta Meta Atingida (L) = % Atingida (M) × Peso 20% (N)
    │
    └── Atingido Ponderado (O) = (I×J) + (M×N)

% Booking (I) → OTE Base (P) e Acelerador (Q)
    │
    └── OTE Variável (S) = P × Q × O ← comissão principal

Trimestral (3/6/9/12):
    → Booking trimestral → fator × 0,9 (W) — apenas se V ≥ 100%
    → Ajuste trimestral (AL) = OTE trim recalculado − soma mensais pagos
```

---

## Diferenças em Relação à Aba Comissões B2G (Consultores)

| Aspecto | Consultores B2G | Gestão B2G |
|---------|----------------|------------|
| Cargo | Consultor | Gestor |
| Eixo 1 | Booking próprio | Booking da equipe (soma de consultores) |
| Eixo 2 | ARR próprio | Meta Atingida (proporção de consultores que bateram booking) |
| Fator trimestral | 0,30 | 0,90 |
| Trimestral equipe | Sim | Não |
| FILTER | `Cargo = "Consultor"` | `Cargo = "Gestor"` |

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Metas | Identificação, metas e ponderações por tipo | FILTER base + cols H, J, L, N |
| Comissões B2G | Booking realizado dos consultores (col L) + % atingido (col N) | G, AB |
| Parâmetros | OTE tiers, cliffs, aceleradores | Colunas P, Q |
