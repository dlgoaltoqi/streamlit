# Lógica de Composição — Minha Comissão (Equipe AM)

> Documento de referência. Para pendências operacionais e decisões vigentes,
> consulte `docs/00_estado_atual.md` e `docs/DECISOES.md`.

## Visão geral

A tela Minha Comissão para as AMs exibe o NRR (Net Revenue Retention) da
carteira do mês corrente. A fórmula central é:

```
NRR = MRR Evoluído / MRR Inicial
```

O cálculo parte de eventos de contrato, não do MRR bruto das vendas. Cada
contrato tem uma classificação de evento e contribui com o delta certo no
Evoluído. A regra de comissão em dinheiro ainda não foi definida; a página
opera em modo medição.

---

## Equipes

As AMs aparecem como duas equipes conforme o pipeline Revenue Intelligence:

| Equipe | Membros |
|---|---|
| AM GDC | aline.pureza, clidiani |
| AM Escritório | debora.vieira, mariana, renata.parizotto |

O despachante aceita os valores `account manager`, `am gdc` e `am escritório`.
O rótulo genérico "Account Manager" aparece apenas para quem tem carteira mas
ainda não tem meta RI cadastrada.

---

## Fontes de dados

| Dado | Tabela/View | Observações |
|---|---|---|
| Carteira (dono do cliente) | `HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER` | `ID_CLIENTE` + `ACCOUNT_MANAGER` (nome); e-mail resolvido via RI owners. Nunca usar o campo "Gerente de conta" de COMPANIES/CONTACTS (incompleto). |
| Contratos (MRR, datas) | `HUBSPOT_OURO.HUBSPOT_CONTRATOS` | Colunas MAIÚSCULAS desde 13/08/2026. `NUMERO_DO_CONTRATO` é `NUMBER(38,6)` — usar `::NUMBER(38,0)`. `ID_DA_EMPRESA`/`ID_DO_CONTATO` são TEXT float serializado — normalizar com `SPLIT_PART(x,'.',1)`. Contratos Ativos têm `DATA_DE_DESATIVACAO = 1900-01-01` (placeholder). |
| Vendas | `HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM` | Filtro por pipeline (ver cada componente). |
| Negócios | `HUBSPOT_OURO.HUBSPOT_DEALS` | Colunas quoted (`"Id do negócio"`, etc.); id é STRING no ouro. |
| Associações contrato-negócio | `HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL` | Pode ficar dias defasada da `DEALS` (ingestão por batch). Nunca depender só dela. |
| Exclusões administrativas | `SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM` | Contratos excluídos por decisão do admin; saem do Inicial e do Evoluído ao vivo. |

---

## Componente 1 — MRR Inicial da Carteira

**O que mede:** MRR recorrente que o AM tinha sob responsabilidade no início
do mês.

**Condições de inclusão** (todas devem ser verdadeiras):

1. Cliente consta em `HUBSPOT_LISTA_POTENCIAL_FARMER` com o ACCOUNT_MANAGER
   da AM.
2. `DATA_DE_INICIO` < 1° dia do mês.
3. `DATA_DE_DESATIVACAO` >= 1° dia do mês (ou seja, `STATUS = 'Ativo'` ou
   inativado dentro do mês — ainda vigente no dia 1°).
4. `DATA_DE_RENOVACAO` >= 1° dia do mês.
5. `TIPO_DE_CONTRATO` IN `('Assinatura', 'plano_business')`.
6. Contrato NÃO está em `EXCLUSOES_CARTEIRA_AM`.

**Semântica da desativação:** a coluna nunca é nula. Ativos têm o placeholder
`1900-01-01`; inativos têm a data real de churn. Logo:

- "vigente no dia 1°" = `DATA_DE_DESATIVACAO >= inicio_mes`
- churn durante o mês = `STATUS = 'Inativo' AND DATA_DE_DESATIVACAO < fim_mes`

O MRR Inicial é calculado ao vivo. Contratos editados retroativamente podem
alterar o número do mês corrente.

---

## Componente 2 — Novos Negócios do Mês

**O que mede:** contratos novos que entraram na carteira sem substituir nenhum
contrato anterior. Adiciona o MRR cheio ao Evoluído.

**Critérios:**

- Contrato iniciado no mês (`DATA_DE_INICIO` dentro do mês).
- Pipeline da venda: `%Account Manager%`, `%E-commerce%` ou `%Saving%`.
- Nos pipelines AM: a consultora da venda deve ser a própria AM.
- Em e-commerce e saving: atribuído pela carteira (qualquer consultor), pois o
  e-commerce tem `CONSULTOR = 'N/A'` e o saving é conduzido pelo CS.
- Não existe contrato substituído identificado (nenhuma das regras de
  Upsell/Downgrade/Renovação/Impulso se aplica).

**Impacto no Evoluído:** `+ MRR do contrato novo` (valor cheio).

---

## Componente 3 — Upsells do Mês

**O que mede:** substituição de contrato em que o sucessor tem subtipo de
upsell ou downgrade, pelo delta entre o MRR novo e o anterior.

**Identificação de uma substituição:**
- Mesmo número de contrato (`NUMERO_DO_CONTRATO`), versão antiga inativada e
  versão ativa no mês.
- OU contrato novo de outro número ligado ao antigo pelo nome do negócio
  (padrão downgrade, ver abaixo).

**Classificação do subtipo:**

| Subtipo do contrato sucessor | Tipo exibido |
|---|---|
| Contém `upsell` E sem `renov` (ex.: `upsell`, `upsell_cross`) | **Upsell** |
| Contrato novo de outro número vinculado por nome do negócio | **Downgrade** |

A classificação segue o subtipo do contrato sucessor, nunca o pipeline ou o
consultor da venda. A venda do mês (buscada em qualquer pipeline via
`vendas_carteira_mes`) só enriquece a linha com o negócio e a data; sem venda,
exibe o início do contrato sucessor.

**Downgrade por nome do negócio:** ocorre quando o contrato novo tem outro
número e não há venda que ligue os dois. O vínculo é o nome do negócio
gerador que traz o número do contrato substituído após a palavra
"downgrade/downsell". Padrão: `[CS - Cancelamentos] Downgrade 620616 - ...`.
O contrato antigo sai do churn; o delta entra neste grupo com tipo Downgrade.

**Impacto no Evoluído:** `+ (MRR novo - MRR anterior)` (pode ser negativo em
downgrades).

---

## Componente 4 — Renovações de Contrato

**O que mede:** substituição de contrato classificada como renovação, pelo
delta de MRR entre a versão nova e a antiga.

**Critérios:**

- Mesmo `NUMERO_DO_CONTRATO` entre origem (inativada no mês) e sucessor
  (ativo), com mesmo cliente OU mesma gerente (cruzamento de registros de
  cliente permitido desde 17/08/2026).
- Subtipo do sucessor não se enquadra em upsell/cross puro (cai em Upsells).
- O negócio associado ao contrato sucessor (ou o deal da venda do mês, ou o
  deal pelo campo "Número do contrato") não está perdido; se todos os deals
  associados estão perdidos, o contrato vai para o Churn.
- RAUT não soma seu MRR bruto à carteira: a renovação via raut é calculada
  pelo delta do par de contratos, não pelo valor da venda.

**Cruzamento de registros:** o contrato novo pode estar em outro registro de
cliente da mesma carteira (filial, PF/PJ, cadastro duplicado). O match é por
`NUMERO_DO_CONTRATO` + (mesmo `ID_CLIENTE` OU mesma gerente).

**Negócio exibido (3 vias, prioridade decrescente):**
1. Associação contrato-deal do contrato novo, restrita a subtipo de renovação.
2. Deal da venda do mês para o mesmo número de contrato.
3. Deal cujo campo "Número do contrato" aponta o número, com fechamento no mês.

Só deal com `Stage = 'Fechado ganho'` aparece. Perdido e em aberto ficam
vazios até o status mudar.

**Impacto no Evoluído:** `+ (MRR novo - MRR anterior)`.
- renovação igual: impacto zero;
- renovação com upsell embutido: delta positivo;
- renovação com downsell embutido: delta negativo.

---

## Componente 5 — Impulsos de Contrato

**O que mede:** consolidação de contratos menores em um contrato maior
(impulso), calculado pelo delta entre a soma dos MRRs de origem e o MRR do
contrato consolidado.

**Identificação de pares (duas vias unidas por UNION, deduplica por sucessor):**

1. Negócio de impulso associado ao contrato novo via
   `HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL`.
2. Campo `Contrato gerado por impulso` da origem, que carrega o número do
   contrato consolidado (716 de 766 origens de 2026 preenchidas).

A segunda via cobre impulsos sem negócio associado (ex.: `638194` → `639342`,
Mariana, ago/2026).

**Regras de origens:**

- A origem deve estar vigente no dia 1° do mês (mesmas condições do Inicial):
  `DATA_DE_INICIO < inicio_mes AND DATA_DE_DESATIVACAO >= inicio_mes`.
- Linhas históricas (ciclos vencidos carimbados pelo impulso) e linhas criadas
  e desativadas no próprio mês (fantasmas) são excluídas — nunca compuseram o
  Inicial e não devem ser subtraídas.
- Origens de outro registro de cliente (ex.: contratos PF de um contato
  consolidados no PJ da empresa encarteirada) são válidas desde que sem
  gerente ou com a mesma gerente do contrato consolidado.

**Impacto no Evoluído:** `+ (MRR do consolidado - soma dos MRRs de origem)`.

---

## Componente 6 — Churn

**O que mede:** perda real de receita recorrente no mês.

**Critérios:**

- Contrato estava no Inicial (início < dia 1°, vigente no dia 1°).
- `STATUS = 'Inativo'` com `DATA_DE_DESATIVACAO` dentro do mês (até hoje,
  no mês corrente).
- Não foi identificada continuidade comercial:
  - Campo `Contrato gerado por impulso` não preenchido, E
  - Nenhum contrato sucessor do mesmo cliente com MRR >= ao anterior,
    iniciado no mesmo mês da desativação.
- O contrato não é origem de uma Renovação, Upsell ou Impulso identificado.
- Nenhum negócio associado ao contrato sucessor está perdido com todos os
  deals perdidos (nesse caso, o próprio sucessor é marcado como não-renovação
  e a origem vai para churn).

**Visibilidade:** o painel exibe lista de clientes em churn com alerta,
para que o AM "corra atrás".

**Impacto no Evoluído:** `- MRR do contrato`.

---

## Fórmula consolidada do MRR Evoluído

```
MRR Evoluído = MRR Inicial
             + Novos Negócios        (MRR cheio de contratos sem substituição)
             + Upsells               (delta: MRR novo - MRR anterior)
             + Renovações            (delta: MRR novo - MRR anterior)
             + Impulsos              (delta: MRR consolidado - soma origens)
             - Churn                 (MRR de contratos inativados sem continuidade)
```

```
NRR = MRR Evoluído / MRR Inicial
```

---

## Cadeia de cards "Evolução da Carteira" (7 cards)

```
[MRR Inicial]  [+ Novos Negócios]  [+ Upsells]  [+ Renovações]
[+ Impulsos]  [- Churn]  [= MRR Evoluído]
```

Cada card abre um expander com a tabela de detalhe do grupo.

---

## Precedência entre grupos (anti dupla contagem)

Cada contrato pertence a no máximo um grupo de movimentação. Ordem de
prioridade aplicada na query:

1. Impulso (campo `Contrato gerado por impulso` ou associação ao negócio de
   impulso).
2. Substituição por subtipo do sucessor (upsell/downgrade).
3. Renovação por mesmo número de contrato.
4. Downgrade por nome do negócio.
5. Novo Negócio (contrato novo sem substituição).
6. Churn (complemento: tudo que não foi identificado nas regras acima).

RAUT não duplica um contrato já coberto por substituição ou renovação.

---

## Pipelines considerados por componente

| Componente | Pipelines |
|---|---|
| Vendas AM (própria consultora) | `B2B Escritórios - Account Manager`, `B2B GDC - Account Manager` |
| E-commerce e Saving (pela carteira) | `Comercial - E-commerce`, `CS - Saving` |
| Renovação Automática (pela carteira) | `Renovação Automática` |

Vendas fora desses pipelines não entram no Evoluído. Venda AM para cliente
fora da carteira aparece nas Movimentações com aviso "fora da carteira —
não contabilizada".