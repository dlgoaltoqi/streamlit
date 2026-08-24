# Aba: Parâmetros

## Contexto

Define, por pessoa e mês, todos os parâmetros necessários para calcular a comissão:
OTE de cada nível, cliffs de desbloqueio, aceleradores e bônus de booking extra.
É aqui que as regras gerais (Cargos e OTEs) se tornam individualizadas por vendedor.

Preenchida manualmente — mesma dinâmica de Metas e Cargos e OTEs.
A partir do mês 5/2026, alguns campos passaram a usar fórmulas (com exceções),
mas para a implementação no Streamlit **todos os valores devem ser consumidos da
tabela de Cargos e OTEs** — nunca hardcodados por pessoa.

## Estrutura — 23 Colunas (A1:W)

| Coluna | Nome | Tipo | Descrição |
|--------|------|------|-----------|
| A | Ano | int | Ano de referência |
| B | Mês | int | Mês de referência |
| C | Consultor | string | Nome do vendedor/gestor |
| D | Email | string | E-mail (chave de identificação) |
| E | Equipe | string | Equipe |
| F | Cargo | string | `Consultor` ou `Gestor` |
| G | Cliff OTE 01 | decimal | % mínimo de atingimento da meta para desbloquear OTE 01 |
| H | OTE 01 Cheio | decimal | Valor cheio do OTE 01 (fonte: Cargos e OTEs) |
| I | OTE 01 Proporcional | decimal | OTE 01 ajustado para meses parciais (fórmula) |
| J | Cliff OTE 02 | decimal | % mínimo para desbloquear OTE 02 (vazio = não se aplica) |
| K | OTE 02 Cheio | decimal | Valor cheio do OTE 02 |
| L | OTE 02 Proporcional | decimal | OTE 02 ajustado para meses parciais (fórmula) |
| M | Cliff OTE 03 | decimal | % mínimo para desbloquear OTE 03 (reservado) |
| N | OTE 03 Cheio | decimal | Valor cheio do OTE 03 (reservado) |
| O | OTE 03 Proporcional | decimal | OTE 03 ajustado para meses parciais (fórmula) |
| P | Cliff Acelerador 01 | decimal | % de atingimento para acionar Acelerador 01 |
| Q | Acelerador OTE 01 | decimal | Multiplicador do Acelerador 01 (ex: 1.15 = 115%) |
| R | Cliff Acelerador 02 | decimal | % de atingimento para acionar Acelerador 02 |
| S | Val Acelerador OTE 02 | decimal | Multiplicador do Acelerador 02 (ex: 1.25 = 125%) |
| T | Cliff Acelerador 03 | decimal | % de atingimento para acionar Acelerador 03 (reservado) |
| U | Acelerador OTE 03 | decimal | Multiplicador do Acelerador 03 (reservado) |
| V | Cliff Booking Extra | decimal | Mesmo valor do Cliff OTE 01 — referenciado via fórmula `=G` |
| W | % Booking Extra | decimal | Percentual de bônus sobre booking (ver aba Comissões) |

## Cliff — Conceito Central

**Cliff** = percentual mínimo de atingimento da meta para desbloquear um benefício.
Abaixo do cliff → valor zerado. Igual ou acima → benefício aplicado integralmente.

Parâmetros observados por equipe (jan/2026):

| Equipe | Cliff OTE 01 | Cliff Acel 01 | Mult Acel 01 | Cliff Acel 02 | Mult Acel 02 |
|--------|:-----------:|:-------------:|:------------:|:-------------:|:------------:|
| Ares / B2B / Farmer | 55% | 95% | 1,15× | 105% | 1,25× |
| FSB | 60% | 95% | 1,15× | 105% | 1,25× |
| GD (maioria) | 70% | 90% | 1,15× | 100% | 1,25× |
| GD (alguns SDRs) | 50% | 75% | 1,15× | 90% | 1,25× |
| Governo | 50% | 75% | 1,15× | 90% | 1,25× |

> Esses valores podem variar mês a mês — sempre ler da tabela, nunca hardcodar.

## OTE Cheio — Fonte e Implementação

O valor de `OTE Cheio` (colunas H, K, N) vem da aba **Cargos e OTEs**, considerando
a Ponderação definida na aba **Metas** (quando há múltiplas métricas para a mesma pessoa).

Na planilha Excel, a partir do mês 5/2026, esse vínculo passou a ser feito via fórmula
em vez de valor manual — com algumas exceções individuais.

**Para a implementação no Streamlit:** sempre consumir da tabela `CARGOS_OTES` pelo
par `Cargo + Mês`, multiplicado pela Ponderação da Metas quando aplicável.
Nunca armazenar o OTE por pessoa diretamente.

## OTE Proporcional — Fórmula (associação com Metas)

As colunas I, L e O são calculadas aplicando o `Desconto` da aba Metas:

```
OTE Proporcional =
    SE(Desconto da Metas = 0,
        OTE Cheio,
        OTE Cheio × (1 − Desconto da Metas)
    )
```

> O Desconto normalmente incide sobre OTE e Meta simultaneamente. Em casos pontuais
> pode incidir apenas sobre a Meta (OTE permanece cheio) ou apenas sobre o OTE
> (Meta permanece cheia). Quando isso ocorre, o administrador garante a consistência
> dos valores — o app sempre aplica o Desconto ao OTE conforme cadastrado.

**Lookup usado (MAXIFS):** busca na aba Metas filtrando por `Ano + Mês + Email`.
Para pessoas em transição de equipe (duas linhas no mesmo mês), o lookup
adiciona **Equipe** como filtro extra, garantindo que cada linha de Parâmetros
use o desconto correto da respectiva equipe.

**Implementação Python/SQL:**
```python
ote_proporcional = ote_cheio if desconto == 0 else ote_cheio * (1 - desconto)
```

## OTE em Múltiplos Níveis (Tiers)

Cada pessoa pode ter até 3 níveis de OTE, cada um com seu próprio cliff:

| Nível | Quando se aplica |
|-------|-----------------|
| OTE 01 | Atingiu o Cliff OTE 01 (ex: 55%) |
| OTE 02 | Atingiu o Cliff OTE 02 — regra configurável por pessoa/mês |
| OTE 03 | Reservado — estrutura criada preventivamente, não está em uso |

O Cliff OTE 02 é configurável: em maio/2026, Mariana e Clidiani (Farmer) têm
Cliff OTE 02 = 100%, com OTE 02 superior ao OTE 01. Em meses anteriores,
os percentuais variaram. **A regra não é fixa — deve ser parametrizável por pessoa e mês.**

## Aceleradores

Aceleradores são multiplicadores aplicados sobre o OTE quando o vendedor supera
determinados percentuais de atingimento:

- **Acelerador 01:** atingiu `Cliff Acelerador 01` → comissão × `Multiplicador 01`
- **Acelerador 02:** atingiu `Cliff Acelerador 02` → comissão × `Multiplicador 02`
- **Acelerador 03:** reservado — estrutura preventiva, sem uso atual

**Requisito de implementação:** iniciar com 2 aceleradores, mas o sistema deve
permitir adicionar mais sem mudança de código (estrutura extensível por configuração).

## Booking Extra

- `Cliff Booking Extra` = mesmo valor do Cliff OTE 01 (fórmula `=G` na planilha)
- `% Booking Extra` = 2% (para todos os casos visíveis)
- A base de cálculo e onde é aplicado serão detalhados na aba **Comissões**.

## Página de Administração

Tabela única com todas as colunas, filtrada por mês/ano.

**Colunas de identificação** — preenchidas automaticamente a partir de Metas, não editáveis:

| Campo | Fonte |
|-------|-------|
| Consultor (email), Equipe | `METAS_CONSULTORES_CONSOLIDADAS` do mês selecionado |

**CARGO** — editável pelo admin; determina qual modelo de comissão se aplica:

| Valor | Modelo aplicado |
|-------|----------------|
| `Consultor` | Comissões padrão (OTE tiers) ou Comissões B2G consultores |
| `Gestor` | Comissões Gestão (ex: Comissões Gestão B2G) |

**Colunas derivadas** — calculadas automaticamente, exibidas como leitura:

| Campo | Cálculo |
|-------|---------|
| OTE 01 Cheio | `Cargos e OTEs (cargo, mês)` × `Ponderação (Metas)` |
| OTE 01 Proporcional | `OTE 01 Cheio × (1 − Desconto)` |
| OTE 02 Cheio | Idem, para o segundo tier |
| OTE 02 Proporcional | Idem |
| Cliff Booking Extra | Espelha o Cliff OTE 01 |

**Colunas editáveis pelo admin:**

| Campo | Observação |
|-------|-----------|
| Cliff OTE 01 | % mínimo para desbloquear comissão |
| Cliff OTE 02 | Opcional — vazio se não se aplica |
| Cliff Acelerador 01 | |
| Multiplicador Acelerador 01 | ex: 1,15 |
| Cliff Acelerador 02 | |
| Multiplicador Acelerador 02 | ex: 1,25 |
| % Booking Extra | ex: 2% |

**Ações:**
- Filtro de mês/ano
- Copiar mês anterior — replica todos os valores editáveis do mês anterior para o mês selecionado
- Edição inline por linha
- Salvar

> OTE 03 e Acelerador 03 estão em backlog — não aparecem na interface por ora.

## Associações com Outras Abas

| Aba | Dado consumido | Onde usado em Parâmetros |
|-----|---------------|--------------------------|
| Cargos e OTEs | OTE do cargo no mês | OTE Cheio (H, K, N) |
| Metas | Desconto na Meta (col J) | OTE Proporcional (I, L, O) |
| Metas | Ponderação (col L) | OTE Cheio quando há múltiplas métricas |
| Comissões | — | Booking Extra (W) — uso detalhado lá |
