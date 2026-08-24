# Aba: Comissões PVT (Pré Vendas Técnicas)

## Contexto

Comissão **trimestral coletiva** da equipe de Pré Vendas Técnicas.
Não há cálculo por consultor — toda a equipe vê e recebe o mesmo resultado, calculado
sobre o desempenho agregado das equipes comerciais que a PVT apoia.

Acesso restrito: apenas membros da equipe PVT e admins.

## Fonte: `bases de referência/Calculadora PVT.xlsx` — aba `Calculadora 2026`

---

## Estrutura do Cálculo (C2:G20)

Dois eixos de meta por trimestre (Q1–Q4):

| Linha | Campo | Descrição |
|-------|-------|-----------|
| C3 | Meta NMRR | Soma trimestral das metas NMRR das equipes Escritórios + Construtoras + Farmer (FSB excluído) |
| C4 | Realizado NMRR | Soma trimestral do realizado NMRR dessas equipes |
| C5 | % Atingido NMRR | `Realizado / Meta` |
| C6 | Ponderação Meta 1 | **0,60** (fixo) |
| C8 | Meta OTR | Soma trimestral da meta de Booking da equipe B2G |
| C9 | Realizado OTR | Soma trimestral do realizado de Booking B2G |
| C10 | % Atingido OTR | `Realizado / Meta` |
| C11 | Ponderação Meta 2 | **0,40** (fixo) |
| C13 | OTE Variável Base | R$ 3.600 por trimestre (parameterizável por Q) |
| C14 | Acelerador (Múltiplo OTE) | Baseado no % NMRR atingido — ver tabela abaixo |
| C15 | OTE Variável Ajustado | `OTE Base × Acelerador` |
| C17 | Total Atingimento | `(% NMRR × 0,60) + (% OTR × 0,40)` |
| C18 | OTE Variável Real | `OTE Ajustado × Total Atingimento` |
| C20 | Comissão Total | `= OTE Variável Real` |

> **C21:G27 ignorado** (prêmio campanha empresa — fora do escopo deste painel).

---

## Parâmetros (C30:H36)

| Parâmetro | Q1 | Q2 | Q3 | Q4 | Descrição |
|-----------|----|----|----|----|-----------|
| Cliff Geral | 0,80 | 0,80 | 0,80 | 0,80 | % mínimo de NMRR para receber qualquer comissão |
| Múltiplo 1,15 (acima de) | 0,90 | 0,90 | 0,90 | 0,90 | NMRR ≥ 90% → acelerador 1,15× |
| Múltiplo 1,25 (acima de) | 1,00 | 1,00 | 1,00 | 1,00 | NMRR ≥ 100% → acelerador 1,25× |
| Prêmio Campanha Empresa | 1× | 1× | 1× | 1× | *ignorado neste painel* |
| Cliff Trimestral | 1,07 | 1,07 | 1,00 | 1,00 | *ignorado neste painel* |

### Lógica do Acelerador (baseado em % NMRR)

| % NMRR Atingido | Acelerador |
|-----------------|------------|
| < 80% (cliff) | **0** — nenhuma comissão |
| ≥ 80% e < 90% | **1,00** |
| ≥ 90% e < 100% | **1,15** |
| ≥ 100% | **1,25** |

---

## Fontes de Dados

### NMRR — Realizado

Fonte: `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`
Filtro deals: respeita a lógica `deals_ok` (< R$ 400k ou em `DEALS_PAGOS_400K`)

| Equipe | VERTICAL no Snowflake | Coluna usada |
|--------|----------------------|--------------|
| B2B Escritório | `B2B Escritório` | `NMRR` |
| B2B Construtora | `B2B Construtora` | `NMRR` |
| Farmer | `Farmer` | `MRR_EXPANSAO` (Farmer não tem NMRR próprio) |

> **FSB**: excluído do cálculo PVT.  
> **Ares**: não existe mais — excluída.  
> **Sonia**: consultores Sonia têm VERTICAL = `Farmer` em VENDAS → incluídos automaticamente.

### NMRR — Meta

Fonte: `SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS`
Coluna: `META_NMRR`
Equipes: `B2B Escritório`, `B2B Construtora`, `Farmer`, `Sonia` (FSB excluído)
Agregação: soma mensal dos 3 meses do trimestre, para todos os consultores dessas equipes.

### OTR (Booking) — Realizado

Fonte: `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`
Coluna: `BOOKING`
VERTICAL: `Governo`
Filtro deals: mesma lógica `deals_ok`

### OTR (Booking) — Meta

Fonte: `SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS`
Coluna: `META_OTR`
Equipe: `Governo`
Agregação: soma mensal dos 3 meses do trimestre, para todos os consultores de Governo.

---

## Tabelamento de Metas e Realizado (I2:V10 e I13:V21)

Planilha exibe desdobramento mensal por equipe, com totais trimestrais calculados.
No painel, replicar essa visão: **uma tabela de metas e uma de realizado**, por equipe e mês,
com total do trimestre selecionado.

Meses por trimestre:

| Trimestre | Meses |
|-----------|-------|
| Q1 | Jan, Fev, Mar |
| Q2 | Abr, Mai, Jun |
| Q3 | Jul, Ago, Set |
| Q4 | Out, Nov, Dez |

---

## Fluxo de Cálculo

```
NMRR Realizado (Esc+Const+Farmer Expansão, 3 meses) ÷ NMRR Meta → % NMRR
OTR Realizado (B2G Booking, 3 meses) ÷ OTR Meta              → % OTR

% NMRR → Acelerador (cliff 80%, 1,15× acima 90%, 1,25× acima 100%)
OTE Ajustado = OTE Base (3600) × Acelerador

Total Atingimento = (% NMRR × 0,60) + (% OTR × 0,40)

Comissão = OTE Ajustado × Total Atingimento
```

---

## Acesso

- **Admins**: acesso irrestrito
- **Equipe PVT**: acesso permitido; todos veem o mesmo resultado coletivo
- **Demais equipes**: sem acesso

Mecanismo sugerido: verificar se o email do usuário tem linha em
`SUPERSET.COMISSOES.PARAMETROS` com `EQUIPE = 'PVT'` (ou similar) para o período vigente,
ou manter whitelist em tabela dedicada.

---

## Notas de Implementação

- Não há snapshot/fechamento por consultor — a lógica de fechamento da PVT (se necessária) é separada.
- Os parâmetros (OTE Base, cliff, aceleradores) devem ser configuráveis por trimestre via painel admin.
- O filtro de período na UI deve ser por **trimestre + ano** (não mês isolado).
- Exibir na UI:
  1. Bloco de cálculo (Meta NMRR, Realizado NMRR, % atingido, Ponderação, idem OTR, Acelerador, OTE, Comissão).
  2. Tabela de metas mensais por equipe (com total trimestral).
  3. Tabela de realizado mensais por equipe (com total trimestral).
