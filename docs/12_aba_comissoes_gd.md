# Aba: Comissões GD

## Contexto

Aba de cálculo de comissão mensal para a equipe **GD** (SDRs e BDRs).
A métrica de realizado é em **Opps** (leads qualificados), não em MRR —
os dados vêm da aba Realizado GD, não de Negócios.

Não usa Acel Form Pag nem Booking Extra — GD não vende diretamente.

## Escopo

Filtro via FILTER de Metas: `Ano > 2025`, `Equipe = "GD"`.
Sem filtro de mês — cobre todos os meses a partir de 2026.
O FILTER inclui também linhas com `Equipe = "Equipe"` para suportar os cálculos trimestrais de equipe.

## Estrutura — Colunas A:W

### Bloco 1 — Identificação (A–H)

Espelhado de Metas via FILTER: Ano, Mês, Consultor, Email, Equipe, Cargo, Gestor, Tipo.

---

### Bloco 2 — Realizado vs. Meta (I–K)

| Col | Campo | Fórmula |
|-----|-------|---------|
| I | Realizado | Consultor: `SUMIFS('Realizado GD'!D:D, Ano, Mês, Email)` — quantidade de Opps qualificados. Gestor: soma do Realizado da equipe |
| J | Meta | `SUMIFS(Metas!Meta_Proporcional, Ano, Mês, Email, Tipo)` — meta em Opps |
| K | % Atingido | `IFERROR(I / J, 0)` |

---

### Bloco 3 — Comissão Principal (L–O)

| Col | Campo | Fórmula |
|-----|-------|---------|
| L | OTE Base | `MAX(OTE03_Prop se Cliff03 ≤ K, OTE02_Prop se Cliff02 ≤ K, OTE01_Prop)` — maior tier qualificado |
| M | Acelerador OTE | `MAX(Acel01 se CliffAcel01 ≤ K, Acel02 se CliffAcel02 ≤ K, ..., 1) × IF(K ≥ Cliff OTE01, 1, 0)` |
| N | OTE Ajustado | `L × M` |
| O | OTE Variável | `N × K` — **comissão principal do mês** |

**GD não usa Acel Form Pag** — não há breakdown por forma de pagamento.
A fórmula difere sutilmente da aba principal: N = L×M (sem K) e O = N×K,
em vez de AA = Y×Z×K direto. O resultado é equivalente, mas a separação
entre "OTE Ajustado" e "OTE Variável" é mais explícita aqui.

---

### Bloco 4 — Trimestral (P–W)

Calculado apenas nos meses de fechamento de trimestre (3, 6, 9, 12).

**Individual:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| P | Realizado Trimestral Individual | Soma dos 3 meses do trimestre, mesmo e-mail |
| Q | Meta Trimestral Individual | Soma das metas dos 3 meses |
| R | % Trimestral Individual | `IFERROR(P / Q, 0)` |

**Equipe:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| S | Realizado Trimestral Equipe | Soma do trimestre de todos os consultores (exclui gestores) |
| T | Meta Trimestral Equipe | Soma das metas da equipe |
| U | % Trimestral Equipe | `IFERROR(S / T, 0)` |

**Comissões:**

| Col | Campo | Fórmula | Condição |
|-----|-------|---------|----------|
| V | Comissão Trimestral Individual | Gestor: `R × 0,6` / Consultor: `R × 0,3` | Individual ≥ 100% no trimestre |
| W | Comissão Trimestral Equipe | `R × 0,3` | Equipe ≥ 100% **E** individual ≥ Cliff OTE01 |

Os valores de V e W são fatores aplicados sobre o **salário base** do colaborador pelo DP.
Fora dos meses de fechamento de trimestre, retornam `""`.

---

## Fluxo de Cálculo

```
Realizado GD (Opps) (I) ÷ Meta (J) = % Atingido (K)
    │
    ├── K → OTE Base (L) por tiers de Parâmetros
    ├── K → Acelerador (M) de Parâmetros
    │
    └── OTE Variável (O) = L × M × K ← comissão principal

Trimestral: só em meses 3/6/9/12 → fatores de salário (V, W)
```

---

## Diferenças em Relação à Aba Comissões Principal

| Aspecto | Comissões | Comissões GD |
|---------|-----------|--------------|
| Realizado | MRR de Negócios | Opps de Realizado GD |
| Acel Form Pag | Sim | Não |
| Booking Extra | Sim | Não |
| Comissão principal | OTE×Acel×K distribuído por forma de pagamento | OTE×Acel×K direto |

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Metas | Identificação + Meta Proporcional (Opps) | FILTER base + col J |
| Realizado GD | Quantidade de Opps qualificados | Coluna I |
| Parâmetros | OTE tiers, cliffs, aceleradores | Colunas L, M |
