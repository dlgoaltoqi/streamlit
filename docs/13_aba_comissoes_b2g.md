# Aba: Comissões B2G

## Contexto

Aba de cálculo de comissão mensal para **consultores** da equipe **Governo**.
Gestores têm aba separada (Comissões Gestão B2G).

A particularidade desta equipe é ter **dois eixos de meta e realizado** — ARR e Booking —
cada um com seu próprio peso (ponderação). A comissão final é calculada sobre o
**atingimento ponderado** dos dois eixos.

Há também um bloco de **Ajuste Trimestral**: ao fechar o trimestre, a comissão é
recalculada sobre o acumulado do período; se o resultado for maior que a soma dos
mensais pagos, a diferença é paga como ajuste.

## Escopo

Filtro via `UNIQUE(FILTER(Metas, Ano > 2025, Equipe = "Governo", Cargo = "Consultor"))`.
`UNIQUE` evita duplicatas quando a pessoa aparece em mais de uma linha de Metas.
Cobre todos os meses a partir de 2026.

## Estrutura — 2 linhas de cabeçalho + dados (A:AQ)

A aba tem dois níveis de cabeçalho: linha 1 agrupa colunas em blocos (ARR, Booking,
Trimestral, Ajuste Trimestral); linha 3 traz os rótulos individuais.
O painel é congelado nas 3 primeiras linhas.

---

### Bloco 1 — Identificação (A–G)

Espelhado de Metas via FILTER/UNIQUE: Ano, Mês, Consultor, Email, Equipe, Cargo, Gestor.
*(Apenas Consultores — gestores excluídos nesta aba)*

---

### Bloco 2 — ARR (H–K)

| Col | Campo | Fórmula |
|-----|-------|---------|
| H | Realizado ARR | `SUMIFS(Negócios!ARR, Ano, Mês, Email, Pago>400k <> "n")` — ARR excluindo deals já marcados como acima de 400k |
| I | Meta ARR | `Meta Booking × 0,5` — derivada no app; a view de Metas não armazena META_ARR separadamente |
| J | % Atingido ARR | `IFERROR(H / I, 0)` |
| K | Ponderação ARR | `SUMIFS(Metas!Ponderação, Ano, Mês, Email, Tipo="ARR")` — ex: 0,40 |

---

### Bloco 3 — Booking (L–O)

| Col | Campo | Fórmula |
|-----|-------|---------|
| L | Realizado Booking | `SUMIFS(Negócios!Booking, Ano, Mês, Email, Pago>400k <> "n")` — Booking excluindo deals acima de 400k |
| M | Meta Booking | `SUMIFS(Metas!Meta_Proporcional, Ano, Mês, Email, Tipo="Booking")` |
| N | % Atingido Booking | `IFERROR(L / M, 0)` |
| O | Ponderação Booking | `SUMIFS(Metas!Ponderação, Ano, Mês, Email, Tipo="Booking")` — ex: 0,60 |

---

### Bloco 4 — Atingimento Ponderado e Comissão Mensal (P–T)

| Col | Campo | Fórmula |
|-----|-------|---------|
| P | Atingido Ponderado | `(J × K) + (N × O)` — média ponderada dos dois eixos |
| Q | OTE Base | `MAX(OTE03_Prop se Cliff03 ≤ J, OTE02_Prop se Cliff02 ≤ J, OTE01_Prop)` — tier baseado em **% ARR** |
| R | Acelerador OTE | `MAX(Acels baseados em % Booking (N)) × IF(N ≥ Cliff OTE01, 1, 0)` — acelerador disparado pelo **% Booking** |
| S | OTE Ajustado | `Q × R` |
| T | OTE Variável | `S × P` — **comissão principal do mês** (OTE Ajustado × atingimento ponderado) |

**Lógica de eixos:** o tier de OTE é desbloqueado pelo desempenho em ARR; o acelerador
é disparado pelo desempenho em Booking. A comissão final usa o atingimento ponderado dos dois.

---

### Bloco 5 — Trimestral (U–AB)

Calculado apenas nos meses de fechamento de trimestre (3, 6, 9, 12).
As métricas trimestrais usam o eixo **Booking** (L/M).

**Individual:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| U | Realizado Trimestral Individual | Soma dos Bookings dos 3 meses, mesmo e-mail |
| V | Meta Trimestral Individual | Soma das metas Booking dos 3 meses |
| W | % Trimestral Individual | `IFERROR(U / V, 0)` |

**Equipe:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| X | Realizado Trimestral Equipe | Soma dos Bookings da equipe nos 3 meses (exclui gestores) |
| Y | Meta Trimestral Equipe | Soma das metas da equipe |
| Z | % Trimestral Equipe | `IFERROR(X / Y, 0)` |

**Comissões:**

| Col | Campo | Fórmula | Condição |
|-----|-------|---------|----------|
| AA | Comissão Trimestral Individual | `W × 0,3` | Individual ≥ 100% no trimestre |
| AB | Comissão Trimestral Equipe | `W × 0,3` | Equipe ≥ 100% **E** individual ≥ Cliff OTE01 |

*(Sem gestores nesta aba — não há lógica ×0,6)*

Os valores de AA e AB são fatores aplicados sobre o **salário base** do colaborador pelo DP.

---

### Bloco 6 — Ajuste Trimestral (AC–AQ)

Recalcula a comissão considerando o trimestre completo e paga a diferença se o
resultado trimestral for superior à soma dos mensais já pagos.

**Acumulados trimestrais:**

| Col | Campo | Descrição |
|-----|-------|-----------|
| AC | Realizado Booking (trim) | Soma dos L dos 3 meses |
| AD | Meta Booking (trim) | Soma dos M dos 3 meses |
| AE | % Atingido Booking (trim) | AC ÷ AD |
| AF | Ponderação Booking | Mesmo peso do mês atual |
| AG | Realizado ARR (trim) | Soma dos H dos 3 meses |
| AH | Meta ARR (trim) | Soma dos I dos 3 meses |
| AI | % Atingido ARR (trim) | AG ÷ AH |
| AJ | Ponderação ARR | Mesmo peso do mês atual |
| AK | Atingido Ponderado (trim) | `(AE × AF) + (AI × AJ)` |

**Recálculo da comissão trimestral:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AL | OTE Base (trim) | Soma dos Q dos 3 meses (OTE Base acumulado) |
| AM | Acelerador (trim) | LET: acelerador recalculado sobre % Booking trimestral (AE), com mesmo cliff |
| AN | OTE Ajustado (trim) | `AL × AM` |
| AO | OTE Variável (trim) | `AN × AK` |

**Comparação e ajuste:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| AP | Pago no Mensal | Soma dos T (OTE Variável mensal) dos 3 meses |
| AQ | Ajuste | `IF(AO > AP, AO − AP, "")` — diferença a pagar no fechamento |

**Lógica do ajuste:** se o cálculo trimestral (usando atingimento acumulado, que pode
ser mais favorável que a média dos mensais) resultar em comissão maior, o consultor
recebe a diferença no mês de fechamento. Se for menor ou igual, não há ajuste (sem estorno).

---

## Fluxo de Cálculo

```
ARR (H) ÷ Meta ARR (I) = % ARR (J) × Ponderação ARR (K)
Booking (L) ÷ Meta Booking (M) = % Booking (N) × Ponderação Booking (O)
    │
    ├── % ARR (J) → OTE Base (Q) por tiers de Parâmetros
    ├── % Booking (N) → Acelerador (R) de Parâmetros
    │
    └── OTE Variável (T) = Q × R × [(J×K)+(N×O)] ← comissão principal

Trimestral (meses 3/6/9/12):
    → fatores de salário (AA, AB) baseados em Booking trimestral
    → Ajuste (AQ): diferença entre cálculo trimestral e soma dos mensais
```

---

## Notas de Implementação

- **Pago >400k:** deals com booking total ≥ R$ 400k ficam com flag `"n"` e são excluídos do Realizado regular. O gestor pode marcar um deal como pago na página de administração (`DEALS_PAGOS_400K`) — a flag é removida e o deal volta ao cálculo. Ver lógica completa em `docs/02_aba_negocios.md`.
- **UNIQUE no FILTER:** necessário para evitar duplicatas quando a pessoa aparece em múltiplas linhas de Metas (ex: múltiplos tipos de meta no mesmo mês).
- **Ajuste Trimestral:** calcular e armazenar somente nos meses 3/6/9/12. Não há estorno — se o trimestral for menor que o mensal acumulado, AQ fica vazio.
- **Gestores:** ausentes nesta aba — calcular separadamente em Comissões Gestão B2G.

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Metas | Identificação, Metas ARR e Booking, Ponderações | FILTER base + cols I, K, M, O |
| Negócios | ARR e Booking excluindo Pago>400k | Colunas H, L |
| Parâmetros | OTE tiers, cliffs, aceleradores | Colunas Q, R |
