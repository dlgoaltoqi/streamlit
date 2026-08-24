# Aba: Comissões Saving

## Contexto

Define as regras de cálculo de comissão para a equipe **Saving a partir de abril/2026**.
Usa patamares escalonados (ver `docs/08_aba_patamares_saving.md`) em vez de aceleradores
lineares, e não aplica Acel Form Pag.

> **No app Streamlit não existe uma página separada para o Saving.** O motor de cálculo
> unificado (ver `docs/01_visao_geral.md`) detecta `Equipe = Saving` e `Mês ≥ 4` e aplica
> automaticamente estas regras em vez do modelo principal.

## Escopo

```
Equipe = "Saving"
  E Ano > 2025
  E Mês ≥ 4  (abril/2026 em diante)
```

Para Saving em Jan–Mar 2026, aplicam-se as regras de `docs/10_aba_comissoes.md`.

## Estrutura — Colunas A:AE

### Bloco 1 — Identificação (A–H)

Espelhado de Metas via FILTER: Ano, Mês, Consultor, Email, Equipe, Cargo, Gestor, Tipo.

---

### Bloco 2 — Realizado vs. Meta (I–K)

| Col | Campo | Fórmula |
|-----|-------|---------|
| I | Realizado | Consultor: `SUMIFS(Negócios!MRR, Ano, Mês, Email)`. Gestor: soma do Realizado da equipe |
| J | Meta | `SUMIFS(Metas!Meta_Proporcional, Ano, Mês, Email, Tipo)` |
| K | % Atingido | `IFERROR(I / J, 0)` |

---

### Bloco 3 — Comissão Principal (L–N)

| Col | Campo | Fórmula |
|-----|-------|---------|
| L | OTE Base | `MAX(OTE03_Prop se Cliff03 ≤ K, OTE02_Prop se Cliff02 ≤ K, OTE01_Prop)` — mesmo tier logic da aba Comissões |
| M | Faixa Atingida | `MAXIFS(Patamares Saving!%, patamar <= K)` — retorna o multiplicador do degrau atingido na tabela de patamares |
| N | OTE Variável | `L × M × K` — **comissão principal do mês** |

**Saving não usa Acel Form Pag** — não há breakdown por forma de pagamento.

Funcionamento de M: varre a tabela Patamares Saving e pega o maior patamar que K atinge.
O multiplicador satura em 1,10 (cap da tabela), mas K continua crescendo acima de 110%.

---

### Bloco 4 — Booking Extra (O–P)

| Col | Campo | Fórmula |
|-----|-------|---------|
| O | Bookings Extras | Individual: `SUMIFS(Negócios!Booking, ..., Categoria IN ["Curso","Serviço","Implementação"])`. Gestor: soma da equipe (via coluna auxiliar AE) |
| P | Comissão Bookings Extras | `2% × O × IF(K ≥ Cliff Booking Extra, 1, 0)` |

> A coluna AE é auxiliar — calcula os bookings individuais antes da agregação do gestor.
> P referencia AE (agregado) em vez de O (individual bruto).

---

### Bloco 5 — Dívidas Pagas (Q–R)

| Col | Campo | Fórmula |
|-----|-------|---------|
| Q | Dívidas Pagas | `SUMIFS('Recuperação de Canc e Divs'!D:D, Ano, Mês, Email)` |
| R | Comissão sobre Dívidas | `IF(K ≥ Cliff OTE01, Q × 2,5%, 0)` — gatilho é o Cliff OTE01 |

---

### Bloco 6 — Trimestral (S–Z)

Calculado apenas nos meses de fechamento de trimestre (3, 6, 9, 12).

**Individual:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| S | Realizado Trimestral Individual | Soma dos 3 meses do trimestre, mesmo e-mail |
| T | Meta Trimestral Individual | Soma das metas dos 3 meses |
| U | % Trimestral Individual | `IFERROR(S / T, 0)` |

**Equipe:**

| Col | Campo | Fórmula |
|-----|-------|---------|
| V | Realizado Trimestral Equipe | Soma do trimestre de todos os consultores (exclui gestores) |
| W | Meta Trimestral Equipe | Soma das metas da equipe |
| X | % Trimestral Equipe | `IFERROR(V / W, 0)` |

**Comissões:**

| Col | Campo | Fórmula | Condição |
|-----|-------|---------|----------|
| Y | Comissão Trimestral Individual | Gestor: `U × 0,6` / Consultor: `U × 0,3` | Individual ≥ 100% no trimestre |
| Z | Comissão Trimestral Equipe | `U × 0,3` | Equipe ≥ 100% **E** individual ≥ Cliff OTE01 |

Os valores de Y e Z são fatores aplicados sobre o **salário base** do colaborador pelo DP.
Fora dos meses de fechamento de trimestre, retornam `""`.

---

## Fluxo de Cálculo

```
Realizado (I) ÷ Meta (J) = % Atingido (K)
    │
    ├── K → lookup Patamares Saving → Faixa Atingida (M)
    ├── K → OTE Base (L) por tiers de Parâmetros
    │
    └── OTE Variável (N) = L × M × K ← comissão principal

Booking Extras (O) × 2% × IF(cliff OK) = Comissão Booking (P)
Dívidas Pagas (Q) × 2,5% × IF(K ≥ Cliff OTE01) = Comissão Dívidas (R)

Trimestral: só em meses 3/6/9/12 → fatores de salário (Y, Z)
```

---

## Diferenças em Relação à Aba Comissões Principal

| Aspecto | Comissões | Comissões Saving |
|---------|-----------|------------------|
| Comissão principal | OTE × Acelerador × K, distribuído por forma de pagamento | OTE × Patamar × K (sem forma de pagamento) |
| Faixa/Patamar | Aceleradores em Parâmetros (lineares) | Tabela Patamares Saving (escalonada) |
| Acel Form Pag | Sim | Não (Saving não usa a partir de abr) |
| Comissão Dívidas | Regra antiga (não implementar) | Cliff OTE01 como gatilho |
| Booking Extra | Saving: Curso+Serviço+Impl / Outros: só Impl | Sempre Curso+Serviço+Impl |

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado |
|-----|---------------|------------|
| Metas | Identificação + Meta Proporcional | FILTER base + col J |
| Negócios | MRR (Realizado) + Booking por categoria | Colunas I, O |
| Parâmetros | OTE tiers, cliffs, % booking extra | Colunas L, P |
| Patamares Saving | Multiplicador por faixa de atingimento | Coluna M |
| Recuperação de Canc e Divs | Valor de dívidas pagas | Coluna Q |
