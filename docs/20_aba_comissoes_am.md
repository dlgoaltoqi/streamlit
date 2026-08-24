# Comissões Account Manager (AM) — Medição por NRR da Carteira

> Estado vigente: medição por NRR está no ar desde agosto/2026. Para o resumo
> operacional e pendências atuais, consulte `docs/00_estado_atual.md`.

> **Status: MEDIÇÃO IMPLEMENTADA E NO AR** (06/08/2026). Regra de comissão
> ainda NÃO definida — a página opera em modo medição (MRR Inicial, Evoluído,
> % de crescimento/redução, churn). Decisões do Higor incorporadas abaixo.

> **Equipes (12/08/2026)**: as AMs aparecem como duas equipes conforme o
> pipeline RI, mapeadas na view `METAS_CONSULTORES_CONSOLIDADAS`:
> `B2B GDC - Account Manager` → **AM GDC** (aline.pureza, clidiani) e
> `B2B Escritórios - Account Manager` → **AM Escritório** (debora.vieira,
> mariana, renata.parizotto). O despachante em `utils/commission.py` aceita
> `account manager`, `am gdc` e `am escritório`; o rótulo genérico
> `Account Manager` só aparece para quem tem carteira mas ainda não tem meta RI.

## Contexto levantado (06/08/2026)

- **Equipe nova**: os 5 Farmers viram Account Managers. Gerentes de conta
  mapeados no HubSpot (campo "Gerente de conta"): renata.parizotto (322
  empresas), clidiani (310), aline.pureza (297), debora.vieira (294),
  mariana (281).
- **Pipelines novos** (estreiam em ago/2026 na tabela de vendas):
  `B2B Escritórios - Account Manager` e `B2B GDC - Account Manager`.
  Pipeline `Renovação Automática` (o "raut") existe desde jan/2026.
- Vendas AM de ago/2026 até agora: renata 17 itens (R$ 2.223), mariana 5
  (R$ 1.732), aline 2 (R$ 601).

## Conceito

```
NRR do mês = MRR Evoluído / MRR Inicial da carteira
```

- **MRR Inicial** — foto da carteira no início do mês vigente: contratos dos
  clientes da carteira com `Data de início` < 1º dia do mês vigente E
  (`Data de desativação` nula OU >= 1º dia do mês vigente).
- **MRR Evoluído** — MRR Inicial + vendas que o AM efetuou no mês vigente
  (pipeline AM) + renovações automáticas da carteira no mês.
- Vendas do mês em pipeline diferente de AM/raut **não contam**.

## Fontes de dados (validadas em 06/08/2026)

| Dado | Fonte | Observações |
|---|---|---|
| Carteira (dono do cliente) | `HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES."Gerente de conta"` (PJ) e `HUBSPOT_CONTACTS."Gerente de conta"` (PF) | Guarda o ID do owner → resolver e-mail via `HUBSPOT_OWNERS (ID→EMAIL)`. Existe também o legado "Consultor farmer" — NÃO usar. |
| Contratos (MRR, datas) | `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS` | Colunas com espaço/acento (`"Data de início"`, `"Data de desativação"`, `"MRR"`, `"Status"`). ⚠️ `"Id da empresa"`/`"Id do contato"` vêm como float serializado (`'123.000000'`) — normalizar com `SPLIT_PART(x,'.',1)` para casar com COMPANIES/CONTACTS. |
| Vendas do mês (AM + raut) | `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM` | Filtro por `PIPELINE IN ('B2B Escritórios - Account Manager', 'B2B GDC - Account Manager', 'Renovação Automática')`. |

### Esqueleto SQL da carteira (testado)

```sql
WITH pj AS (
    SELECT o.EMAIL gerente, c."Id do contrato" cid, c."MRR" mrr
    FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS c
    JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_COMPANIES co
      ON co."Id da empresa" = SPLIT_PART(c."Id da empresa", '.', 1)
    JOIN HUBSPOT.HUBSPOT_OURO.HUBSPOT_OWNERS o
      ON TO_VARCHAR(o.ID) = TO_VARCHAR(co."Gerente de conta")
    WHERE c."Tipo de pessoa" = 'Jurídica'
      AND c."Data de início" < :inicio_mes
      AND (c."Data de desativação" IS NULL OR c."Data de desativação" >= :inicio_mes)
), pf AS (
    -- idem via HUBSPOT_CONTACTS."Gerente de conta" p/ Tipo de pessoa <> 'Jurídica'
)
SELECT gerente, SUM(mrr) AS mrr_inicial FROM (pj UNION ALL pf) GROUP BY 1
```

Sanidade (ago/2026): renata 20 contratos / R$ 16.110; aline 9 / R$ 9.070;
mariana 15 / R$ 5.826; clidiani 10 / R$ 5.750; debora 8 / R$ 2.507.

## ⚠️ Achados que precisam de decisão/ação (ver Questões)

1. **Raut não é creditado ao AM na venda**: TODAS as vendas de agosto do
   pipeline Renovação Automática têm `CONSULTOR = thiago.oliveira` (conta
   coletora). Logo a parcela "renovação automática" do MRR Evoluído precisa
   ser atribuída **pela carteira** (gerente de conta do cliente renovado),
   não pelo consultor da venda.
2. **`EQUIPE`/`VERTICAL` = `'??'`** nas vendas dos pipelines AM — o dbt ainda
   não mapeia os pipelines novos. O painel pode operar filtrando por
   `PIPELINE`, mas vale pedir o mapeamento ao time de dados (afeta visões por
   vertical/gestor no resto do painel).
3. **Cadastro da carteira em andamento**: os gerentes têm ~300 empresas
   marcadas cada, mas só 8–20 contratos ativos casam por AM hoje (a maioria
   dos contratos não tem vínculo empresa/contato preenchido, ou o
   contato/empresa ainda não tem "Gerente de conta"). Os MRRs iniciais acima
   ficarão baixos até o cadastro completar.

## Estrutura visual proposta — Minha Comissão (ramo AM)

Segue o padrão dos demais modelos (cards `stat` + `formula`, expanders de
composição, mesmos estilos). Novo ramo `is_am` no despachante.

```
┌─ SEGMENTO 1 — Resumo ────────────────────────────────────────────────────┐
│ [Cargo]  [Variável Total*]  [MRR Inicial]  [MRR Evoluído]  [NRR]  [Meta NRR]│
│                              da Carteira     no Mês        120,4%   ex.:100%│
└──────────────────────────────────────────────────────────────────────────┘
* fórmula do total conforme regra de comissão (Questão 1)

┌─ SEGMENTO 2 — Evolução da Carteira (novo, exclusivo AM) ─────────────────┐
│ [MRR Inicial]  [+ Vendas do AM no mês]  [+ Renovação Automática]  [= MRR │
│  R$ 16.110,27      R$ 2.223,25              R$ 1.480,00          Evoluído]│
│                                                                R$ 19.813  │
│  formula: 16.110,27 + 2.223,25 + 1.480,00 = 19.813,52 → NRR 123,0%       │
│                                                                           │
│ ▸ Composição da Carteira (MRR Inicial)                                    │
│     Cliente | Contrato | Data de Início | Vigência | MRR                  │
│ ▸ Movimentações do Mês                                                    │
│     Tipo (Venda AM / Renov. Automática) | Cliente | Negócio |             │
│     Data de Fechamento | MRR                                              │
└──────────────────────────────────────────────────────────────────────────┘

┌─ SEGMENTO 3 — Cálculo do OTE ────────────────────────────────────────────┐
│ Mesmo padrão das outras equipes: [OTE Base] [Acelerador/Faixa por NRR]    │
│ [OTE Variável] — estrutura final depende da regra de comissão (Questão 1) │
└──────────────────────────────────────────────────────────────────────────┘

SEGMENTO 4 — Histórico dos últimos meses (reusa o existente; colunas:
Período, MRR Inicial, MRR Evoluído, NRR, OTE Variável, Total)
```

Minha Equipe e Exportar Comissões ganham colunas equivalentes (MRR Inicial,
MRR Evoluído, NRR) no lugar de Realizado/Meta/% Atingido quando a equipe for
AM — mesma mecânica do que já fazemos para GD (Opps) e Governo (Booking).

## Encaixe na arquitetura existente

- `montar_contextos()`: +2 consultas por mês (carteira/MRR inicial por
  gerente; movimentações AM+raut por gerente via carteira) — mantém o padrão
  de lote (~15 queries/mês → ~17).
- Despachante: novo `_calcular_am(ctx, b)` ao lado de `_calcular_gd/_b2g/...`;
  flag `is_am` derivada da EQUIPE da pessoa nas metas (equipe "AM"?/
  "Account Manager"?) ou de Parâmetros.
- Composições: novas funções para carteira e movimentações (com snapshot via
  fechamento como os demais TIPOs de composição).
- Metas: meta de NRR por AM — idealmente da RI (novo pipeline nos goals?),
  interim via form (Questão 5).
- Fechamento/snapshot mensal já congela `dados` + composições — protege os
  meses pagos de flutuações retroativas nos contratos. Ainda assim, o MRR
  Inicial do mês VIGENTE flutua se contratos forem editados retroativamente
  (Questão 6).

## Decisões do Higor (06/08/2026)

- **Raut**: negócio/contrato ficam no nome do thiago (coletora); o que vale é
  o ENCARTEIRAMENTO — raut de cliente da carteira conta para o gerente dela.
- **Comissão**: sem regra por ora — só medir NRR (Inicial, Evoluído, %
  Crescimento/Redução).
- **Churn visível**: mostrar com destaque os clientes que churnaram no mês,
  para o AM "correr atrás".
- **Venda AM fora da carteira**: em teoria não acontece; sinalizar casos
  (1º caso já sinalizado: renata × LC ENGENHARIA, cliente sem gerente).
- **Sem snapshot do inicial**: carteira olhada de forma VIVA, com o MRR
  inicial definido por critérios estáticos (datas dos contratos).
- **Farmer deixa de existir** (substituída pela AM).

## Correção da fonte da carteira (06/08/2026, tarde)

O primeiro corte usava o campo "Gerente de conta" de COMPANIES/CONTACTS +
"Data de desativação" dos contratos — subcontava brutalmente (mariana: 8,5k
vs ~500k reais). A fonte correta, alinhada ao painel PBI "Potenciais Clientes
Farmer" (`C:\...\Paineis PBI\Potenciais Clientes Farmer`, regras em
documentação do painel PBI de referência):

- **Carteira** = `HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER`
  (dbt): ID_CLIENTE → ACCOUNT_MANAGER (por NOME → e-mail via
  consultants/owners da RI). É a mesma base do PBI (mariana: 449 clientes).
- **Contratos** (regras RN-SQL-01/01b do PBI): `Tipo de contrato =
  'Assinatura'`, `Subtipo da venda <> 'Cancelado'`, `Status = 'Ativo'`,
  **vigência pela "Data de renovação"** (não desativação!), cliente = contato
  p/ PF e empresa p/ PJ (COALESCE invertido por tipo de pessoa).
- Reconciliação contra a LISTA (corte hoje): desvio < 0,3% por AM (produtos
  'Não Contabilizar' do dbt).

Números pós-correção (06/08): renata inicial 586.516 (542 contratos, NRR
100,9%), mariana 494.673 (NRR 100,6%), aline 352.395 (100,2%), debora
244.429 (100,8%), clidiani 207.033 (102,6%).

## Regras FORMAIS (definidas pelo Higor em 06/08/2026 — VIGENTES)

**MRR Inicial da Carteira** — contratos que atendem TODAS as condições:
1. Cliente da carteira do AM (via `HUBSPOT_LISTA_POTENCIAL_FARMER.ACCOUNT_MANAGER`);
2. `Data de início` < 1º dia do mês;
3. `Data de desativação` nula ou no mês em questão;
4. `Data de renovação` >= 1º dia do mês;
5. `Tipo de contrato` ∈ {'Assinatura', 'plano_business'}.

**MRR Evoluído** = Inicial
+ vendas do AM no mês (pipeline AM) **de clientes da própria carteira**
+ vendas de e-commerce e saving do mês para clientes da carteira, atribuídas
  pela carteira (regra de 13/08/2026)
+ renovações automáticas do mês de clientes da carteira (atribuídas pela carteira)
− contratos da carteira que **churnaram** no mês.

**Tradução da condição 3 para os dados** (verificado em 06/08): "Data de
desativação" NUNCA é nula na base — nos contratos `Status='Ativo'` ela carrega
uma data antiga (resíduo), e nos `Status='Inativo'` marca o churn real. Logo:
- "desativação nula" ≡ `Status = 'Ativo'`;
- "desativação no mês" ≡ `Status = 'Inativo' AND desativação >= 1º do mês`
  (estava vigente no dia 1º; churnou durante o mês — entra no Inicial e sai
  no Evoluído);
- **Churn do mês** = contratos do Inicial com `Status='Inativo'` e desativação
  dentro do mês (até hoje, no mês corrente). A álgebra −churn +raut compensa
  renovações automaticamente.
- **Continuidade comercial** = não conta como churn o contrato de origem de
  impulso (`Contrato gerado por impulso` preenchido) nem a troca/upsell em que
  outro contrato do mesmo cliente inicia no mesmo mês da desativação e possui
  MRR maior ou igual. O contrato sucessor preserva a receita da carteira.
- Venda AM para cliente FORA da carteira não conta no Evoluído (aparece nas
  Movimentações com "⚠️ fora da carteira — não contabilizada").

Sanidade (06/08): renata inicial 592.730 / NRR 99,5% (churn 6.213); mariana
499.522 / 100,0%; aline 355.472 / 99,3%; debora 245.710 / 100,4%; clidiani
210.430 / 100,9%. Obs.: a única venda AM da renata (LC ENGENHARIA, 2.223)
zerou o "Vendas do AM" dela por estar fora da carteira — encarteirar o
cliente (id 53077607713) resolve.

## Semântica implementada (descoberta importante de dados)

Os contratos são de **ciclo mensal**: praticamente todos os contratos ativos
têm "Data de desativação" preenchida DENTRO do próprio mês (fim do ciclo) e o
raut renova. Logo, desativação ≠ churn. Definições implementadas:

- **MRR Inicial** = contratos da carteira com início < dia 1º e (desativação
  nula ou ≥ dia 1º) — critério estático, calculado ao vivo.
- **Vendas do AM** = vendas do mês em pipeline `%Account Manager%`, pelo
  CONSULTOR da venda. Desde 13/08/2026 também as vendas em pipeline
  `%E-commerce%` ou `%Saving%` para clientes da carteira, atribuídas pela
  carteira (qualquer consultor).
- **Renov. Automática** = vendas do mês em pipeline raut, atribuídas pelo
  gerente de conta do CLIENTE (nunca pelo consultor da venda).
- **Churn (não renovados)** = contratos do inicial já vencidos no mês (fim ≤
  hoje) de cliente SEM contrato vigente e SEM venda raut/AM no mês. (A venda
  raut é o sinal confiável de renovação — o contrato renovado entra na base
  de contratos com defasagem.)
- **MRR Evoluído = Inicial + Vendas AM + Renov. Automática − Não renovados.**
  O desconto do churn é necessário porque a carteira inteira recicla
  mensalmente — sem ele o NRR somaria o mesmo MRR duas vezes (base + raut) e
  nunca teria "Redução". NRR = Evoluído / Inicial.
- Meio do mês: contratos vencidos há poucos dias cujo raut ainda não rodou
  aparecem temporariamente como "não renovados" — visão viva, autocorrige
  quando a renovação processa.

Sanidade (06/08/2026): renata NRR 48,7% (churn 13.716 de 16.110 inicial),
aline 9,8%, mariana 90,1%, clidiani 123,5%, debora 115,3%.

## Ajuste vigente: continuidade comercial no churn (07/08/2026)

Churn AM passou a medir perda real de receita. Um contrato inativado é excluído
do churn quando o campo `Contrato gerado por impulso` está preenchido ou quando
há contrato sucessor do mesmo cliente iniciado no mesmo mês da desativação com
MRR maior ou igual. A regra é aplicada tanto ao NRR quanto ao detalhamento da
lista de churn.

Validação de referência: para Aline, os contratos de origem `633499` (impulso
para `639268`) e `634540` (upsell) deixaram de compor o churn. Esses números são
evidência de regressão, não exceções codificadas.

## Ajuste vigente: renovação substitui o MRR inicial (07/08/2026)

Renovação não é receita adicional à carteira inicial. Quando as versões antiga
e nova têm o mesmo número de contrato, o Evoluído substitui o MRR anterior pelo
novo e contabiliza apenas o delta:

`MRR Evoluído = MRR Inicial - MRR anterior + MRR novo`

- renovação igual: impacto zero;
- upsell na renovação: delta positivo;
- downsell na renovação: delta negativo;
- ausência de sucessor: perda integral classificada como churn.

Se a mesma renovação também estiver em `HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`
com pipeline `r.aut`, ela é retirada desse somatório para não duplicar o MRR.
O contrato antigo deixa de aparecer na lista de churn e a tabela de renovações
mostra os dois MRRs e o impacto líquido no NRR.

Validação de referência: contrato `631939`, de R$ 1.796,40 para R$ 699,50,
gera downsell de R$ 1.096,90 em vez de churn integral.

## Ajuste vigente: eventos de contrato para todo o NRR (07/08/2026)

O cálculo passou a usar a mesma álgebra para toda movimentação da carteira:

`impacto = MRR dos contratos novos - MRR dos contratos iniciais substituídos`

- **Novo negócio:** contrato novo dos pipelines AM/e-commerce/saving sem
  contrato substituído; adiciona seu MRR cheio ao Evoluído (até 13/08/2026
  este caso era exibido dentro do grupo Upsells).
- **Upsell:** substituição de contrato classificada pelo subtipo do sucessor;
  entra pelo delta, com MRR anterior e novo expostos no painel.
- **Renovação:** troca a versão antiga pela nova, inclusive quando a venda é
  RAUT. A RAUT não soma seu MRR bruto à carteira.
- **Impulso:** as associações do negócio de impulso determinam todas as
  origens inativadas e o contrato consolidado. O anterior é a soma de todas
  essas origens; o novo é o MRR do consolidado.
- **Churn:** é o caso complementar, com MRR novo igual a zero e sem vínculo de
  substituição.

O painel apresenta Novos Negócios, Upsells, Renovações de Contrato, Impulsos e
Churn em cards separados, com tabelas de detalhe para cada grupo. Referências de
regressão: `631939` gera delta de -R$ 1.096,90; `633499` é origem do impulso
`639268` e não compõe churn.

## Ajuste vigente: substituição classificada pelo subtipo do contrato (13/08/2026)

A distinção entre Renovação e Upsell numa substituição de contrato (mesmo
número, linha antiga inativada e sucessora ativa) passou a depender apenas do
`Subtipo da venda` do contrato sucessor:

- subtipo contendo `upsell` e sem `renov` (ex.: `upsell`, `upsell_cross`):
  grupo **Upsells**, com o delta de MRR;
- qualquer outro subtipo (incl. `renovacao_upsell_cross`): grupo **Renovações
  de Contrato**, também pelo delta.

Antes, a classificação como upsell exigia uma venda no mês em pipeline
`%Account Manager%` feita pelo próprio gerente. Upsells vendidos no pipeline
legado `Farmer - Deméter` (transição Farmer para AM) ou sem linha de venda no
mês caíam indevidamente no grupo de renovação. Caso motivador: contrato
`59734732177` (nº `516295`, Clidiani, ago/2026), upsell de R$ 377,55 para
R$ 487,63 vendido via pipeline Farmer.

A venda do mês (agora buscada em qualquer pipeline, CTE `vendas_carteira_mes`)
só enriquece a linha com o negócio e a data de fechamento; sem venda, a data
exibida é o início do contrato sucessor. Uma RAUT do mesmo contrato não gera
linha de renovação quando a substituição já foi classificada como upsell.

O MRR Evoluído não muda com esse ajuste: o delta é contabilizado igual nos
dois grupos. Validação de 13/08/2026 (as 4 substituições reclassificadas em
ago/2026, Evoluído idêntico antes e depois para as 5 AMs):

| AM | Contrato | Delta movido p/ Upsells |
| --- | --- | --- |
| Clidiani | `516295` | R$ 110,08 |
| Débora | `626547` | R$ 209,75 |
| Mariana | `632662` | R$ 330,75 |
| Renata | `626939` | R$ 646,65 |

## Ajuste vigente: downgrade identificado pelo nome do negócio (13/08/2026)

Existem downgrades em que o contrato novo tem OUTRO número e não há venda do
mês ligando os dois contratos. O único vínculo é o nome do negócio que gerou o
contrato novo (via `ASSOCIATIONS_CONTRATO_DEAL`), que carrega o número do
contrato substituído logo após a palavra downgrade/downsell. Padrão típico do
pipeline `CS - Saving | Pedidos de Cancelamento`:

`[CS - Cancelamentos] Downgrade 620616 - Gabriel Macêdo`

A CTE `downgrades_contrato` casa esse número com um contrato do Inicial do
mesmo cliente (inativado dentro do mês) e trata o par como substituição.
O negócio liga-se ao contrato novo pelo campo "Número do contrato" do próprio
negócio OU pela associação em `HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL` (tabela dbt
da prata; a view `ASSOCIATIONS_CONTRATO_DEAL` é um rename sobre o bronze com o
mesmo conteúdo, verificado linha a linha em 13/08/2026). A associação sozinha
não basta porque a ingestão de associações é uma foto que pode ficar dias
defasada da `DEALS` (constatado em 13/08/2026: carga de 11/08 06:11, ~200
negócios mais novos ausentes, entre eles o deal de impulso `63716240479`).

- o contrato antigo entra em `contratos_substituidos` e sai do churn;
- o delta de MRR (novo menos antigo) entra no grupo Upsells com tipo
  `Downgrade`, visível no expander "Upsells do Mês" com link para o negócio;
- guardas de precedência: impulso, substituição por subtipo e renovação por
  mesmo número vêm antes; RAUT não duplica um contrato já coberto.

Atenção: negócios "Pedido de Downgrade" (o pedido em si, associado ao contrato
antigo) trazem o número ANTES da palavra, então não casam com o padrão; apenas
o negócio que gera o contrato novo casa.

Caso motivador e validação (13/08/2026): cliente `22812263068` (Débora),
contrato `620616` (R$ 612,08, desativado 10/08) substituído pelo `639307`
(R$ 311,67, iniciado 07/08). Depois do ajuste o churn da Débora caiu de
R$ 980,18 para R$ 368,10, o grupo Upsells recebeu o delta de −R$ 300,41 e o
Evoluído subiu R$ 311,67 (o MRR do contrato novo, antes ignorado). As outras
4 AMs não mudaram; era o único caso de agosto.

## Ajuste vigente: impulso pelo campo do contrato e origens só do Inicial (13/08/2026)

Dois problemas corrigidos na detecção de impulsos:

**1. Impulso sem negócio associado.** Há impulsos em que o contrato novo não
tem nenhum negócio em `ASSOCIATIONS_CONTRATO_DEAL` (caso motivador: `638194`
consolidado no `639342`, Mariana, ago/2026; o `638194` caía no churn e o
`639342` não aparecia). O campo `Contrato gerado por impulso` da origem
carrega o NÚMERO do contrato consolidado (sempre numérico quando preenchido;
716 de 766 origens de 2026 apontam contrato existente). A CTE `impulsos_pares`
une as duas vias, associações do negócio de impulso e o campo, e deduplica
antes de agregar por sucessor.

**2. Origens que nunca compuseram o Inicial.** O processo de impulso carimba a
"Data de desativação" também nas linhas HISTÓRICAS do contrato (ciclos já
vencidos, ex.: `602012` com 2 ciclos de 2024/2025 carimbados em 03/08/2026) e
em linhas criadas e desativadas no próprio mês (ex.: renovação do `631608`
criada e consolidada no mesmo dia 05/08/2026). Essas linhas entravam na soma
de origens (na via por negócio isso já acontecia antes) e subtraíam MRR que
nunca esteve no Inicial nem em nenhum outro grupo, distorcendo o Evoluído. A
origem de impulso agora vem de `carteira_inicial`, nunca de `cc`. Linhas fora
do Inicial não são contadas em nenhum lugar do mês (upsell, renovação e
substituição exigem sucessor Ativo), então excluí-las é neutro por construção.

Validação (13/08/2026, ago/2026): Mariana churn 627,20 para 407,70 e impulso
`639342` com delta +240,00 (Evoluído +459,50); Renata com 3 impulsos
(+33,30, +93,42, +1.973,19; Evoluído +2.697,00); Aline impulso `639268` de
+5,79 para +2.795,81 (origem `631522` venceu em 31/07 e não compunha o Inicial
de agosto; Evoluído +2.790,02). Clidiani e Débora inalteradas. O saldo por
cliente confere em todos os casos (ex.: COOXUPE `634813` para `639347` valia
churn −309,00 + upsell +402,42 = +93,42 e virou impulso +93,42).

**3. Origens em outro registro de cliente (13/08/2026, à noite).** O impulso
pode consolidar contratos de OUTRO registro: caso motivador foi o deal
`63465435532` (Renata, ago/2026), "Novo negócio - Impulso de Contrato" que
consolidou 3 contratos PF do contato `2119728` (`622256` + `636933` + `537971`
= 2.173,23, todos com o campo preenchido) no contrato PJ `639252` (3.066,50)
da empresa LC ENGENHARIA, essa sim na carteira. Como as duas vias exigiam o
mesmo ID de cliente e a mesma gerente, o par não casava e o `639252` caía em
Novos Negócios com MRR cheio. A CTE `origens_impulso` passou a buscar origens
em TODOS os contratos (tipos e exclusões do `_AM_CONTRATOS_SQL`), mantendo as
guardas temporais de vigência no dia 1º que preservam a regra "origens só do
Inicial"; o par credita a GERENTE do contrato consolidado e origem de OUTRA
carteira não cruza (só entra origem sem carteira ou da mesma gerente).
Validação: `639252` virou impulso com delta +893,27 (Evoluído da Renata
−2.173,23); a ampliação também revelou o impulso do OKTAGON da Clidiani
(`322728` → `639387`, delta +154,35, antes Novo negócio de 1.019,57) e um
terceiro da Mariana (`321551`+`619562` → `639255`, delta +127,59, antes
invisível). Checagem de dupla contagem entre grupos veio vazia.

## Ajuste vigente: e-commerce e saving entram no net da carteira (13/08/2026)

Vendas dos pipelines `Comercial - E-commerce` e `CS - Saving` para clientes da
carteira passaram a compor o Evoluído. A atribuição é pela carteira (dona do
cliente), como no raut: no e-commerce o CONSULTOR da venda vem `N/A`
(autosserviço) e no saving quem conduz é o time de CS. Nos pipelines AM nada
muda: continuam exigindo que a própria AM seja a consultora da venda.

Implementação: constante `_AM_PIPE_CARTEIRA` e condição composta na CTE
`vendas_am_mes` (`utils/commission.py`). O restante do motor não muda. A
classificação continua pelos eventos de contrato, com as guardas de
precedência existentes (renovação por mesmo número, substituição por subtipo,
impulso e downgrade), então não há dupla contagem quando a venda de
e-commerce/saving corresponder a uma renovação ou substituição.

Caso motivador e validação (13/08/2026): BAMBOO ARQUITETURA (cliente
`21383380562`, carteira da Renata) deixou o contrato `631693` (R$ 328,95)
desativar em 09/08 e recomprou pelo e-commerce em 11/08 (contrato
`60051897643`, nº `639337`, Plano Builder Premium, R$ 419,50). Antes o painel
via só o churn; agora a recompra entra no grupo Upsells (+419,50) e o churn
antigo permanece (números de contrato diferentes, sem vínculo estrutural), net
de +90,55 no Evoluído. Era a única venda de agosto afetada nas 5 carteiras;
não havia venda de saving para clientes de carteira no mês.

## Ajuste vigente: Novos Negócios separados dos Upsells no painel (13/08/2026)

O grupo Upsells misturava contratos novos sem substituição (MRR cheio) e
substituições/downgrades (delta). O painel passou a separar:

- card e expander **"Novos Negócios do Mês"**: contratos novos dos pipelines
  AM/e-commerce/saving sem contrato substituído, com o MRR cheio;
- card e expander **"Upsells do Mês"**: substituições (tipos `Upsell` e
  `Downgrade`), agora com colunas de MRR Anterior, MRR Novo e Impacto no NRR,
  no mesmo padrão das tabelas de Renovações e Impulsos.

A cadeia "Evolução da Carteira" ficou com 7 cards (Inicial, Novos Negócios,
Upsells, Renovações, Impulsos, Churn, Evoluído), sem textos explicativos sob
os cards desde 14/08/2026 (as tabelas dos expanders já detalham cada grupo). O MRR Evoluído não muda:
novos negócios + upsells somam exatamente o antigo grupo Upsells. Validação de
13/08/2026 (ago/2026): renata 3.486,00 (2 novos) + 1.772,39 (2 upsells) =
5.258,39; clidiani 1.359,07 + 110,08 = 1.469,15; mariana 723,87 + 1.871,40 =
2.595,27; aline 0 + 839,31; débora 0 + (−90,66). Implementação: TIPO
`Novo negócio` na CTE `upsells_contrato` (com MRR anterior/novo nas
substituições), métricas `am_novos_negocios` e agregados anterior/novo em
`_am_sql`/`_am_processar`/`_calcular_am`, e os dois expanders em `_comissao.py`.

## Ajuste vigente: coluna Negócio em Renovações e Impulsos (17/08/2026)

As tabelas "Renovações de Contrato" e "Impulsos de Contrato" ganharam a coluna
**Negócio**, logo após Cliente, com o nome do deal ligado ao registro dele no
HubSpot (mesmo padrão das tabelas de Novos Negócios e Upsells). O nome é
truncado em 30 caracteres, com o nome completo no `title` do link, e as duas
tabelas passaram a usar cabeçalho compacto e rolagem horizontal para não
esticar a largura da tela.

O negócio é só exibição: nenhum cálculo depende dele. `_am_negocio_ctes` em
`utils/commission.py` monta duas CTEs de apoio usadas por
`composicao_renovacoes_am` e `composicao_impulsos_am`:

- `negocio_contrato` (fonte primária): associação contrato-deal do contrato
  novo, restrita ao tipo da movimentação (`ILIKE '%renova%'` nas renovações,
  `Novo negócio - Impulso de Contrato` nos impulsos). É o vínculo estrutural
  entre o contrato gerado e o deal que o gerou.
- `negocio_venda` (complemento): negócio da venda do mês para o mesmo número de
  contrato, a mesma `vendas_carteira_mes` que alimenta o Evoluído. Cobre o que
  a associação não alcança: renovação sem sucessor (RAUT que chegou antes da
  linha nova, com `CONTRATO_NOVO` nulo) e associação ainda defasada. A chave é
  gerente + número do contrato, sem o id do cliente, porque a venda que renova
  pode estar em outro registro de cliente da mesma carteira.
- `negocio_numero` (último recurso, 17/08/2026): negócio cujo campo "Número do
  contrato" aponta o número da movimentação, com fechamento a partir do 1º do
  mês. Cobre o negócio ganho que ainda não tem venda no mês nem associação (as
  associações atrasam dias). Caso motivador: contrato `631937` (LTRINDADE,
  ago/2026), renovação com sucessor Ativo cujo deal `62829127210` era
  invisível às duas outras vias. O corte pelo início do mês evita casar
  renovação de ciclos anteriores do mesmo número; empate prefere o fechamento
  mais recente.

**Só negócio fechado ganho aparece** (regra de 17/08/2026): as três CTEs
exigem `Fechado ganho`. Perdido nunca aparece: um RAUT perdido e substituído
por um negócio ganho em outro pipeline não pode ser exibido como a origem da
movimentação (caso `631731`, ROHR, Clidiani, ago/2026: o RAUT `61694979964`
perdido dava lugar ao ganho `63788756251`, que está no registro de cliente
`57413557115` e não no `37095448225` da carteira, daí a chave sem id do
cliente). Negócio ABERTO também não aparece (mesma lógica, pedido do G0 em
17/08/2026): o deal `62829127210` da renovação da LTRINDADE (`631937`) estava
em Negociação e não podia ser exibido; a célula fica vazia e preenche quando o
negócio ganhar (esse fechou ganho no mesmo dia às 15:56 UTC). A renovação em
si continua contando: o que decide o cálculo é o contrato sucessor, e negócio
perdido derruba a movimentação pela regra própria abaixo.

## Ajuste vigente: renovação/substituição cruza registros de cliente (17/08/2026)

`renovacoes_diretas` e `substituicoes_am` deixaram de exigir o mesmo
`ID_CLIENTE` entre origem e sucessor: o sucessor casa pelo `NUM_CONTRATO` com
o mesmo cliente OU a mesma gerente, o critério que `impulsos_pares` já usava
desde 13/08/2026. A renovação pode criar o contrato novo em outro registro de
cliente da mesma carteira (PF/PJ, filial, cadastro duplicado no HubSpot).

Caso motivador: a renovação da ROHR (`631731`, Clidiani, ago/2026) desativou o
contrato `57832273667` na empresa `37095448225` e criou o `60150311429`
(R$ 1.553,54, `renovacao_upsell_cross`) na empresa `57413557115`, ambas da
carteira. Sem o cruzamento, o painel duplicava o contrato: a renovação entrava
pela via RAUT (delta +276,68 sobre o MRR do deal, sem link do contrato novo) e
o sucessor entrava inteiro como Novo Negócio (+1.553,54). Depois, quando o RAUT
perdido saísse da base, a origem viraria churn falso de 1.202,32. Com o
cruzamento, fica só a renovação com o sucessor real: delta +351,22, link do
contrato novo e nada em Novos Negócios. NRR da Clidiani em ago/2026 corrigido
de 1,0166 para 1,0095 (Evoluído −1.479,00).

Validação de 17/08/2026: diff completo antes/depois das 5 carteiras em
ago/2026 e jul/2026 (12 medidas + 4 composições por AM/mês); a única diferença
foi a correção da ROHR descrita acima.

## Ajuste vigente: sucessor de negócio perdido não é renovação (17/08/2026)

A linha do contrato de renovação é criada antecipadamente no HubSpot e pode
seguir `Ativo` mesmo depois de o negócio ser fechado como perdido. A CTE
`sucessores_negocio_perdido` marca o contrato cujos negócios associados estão
TODOS perdidos e que não tem venda ganha no mês para o mesmo número (via
`vendas_carteira_mes` + `DEALS`): esse sucessor não vira renovação nem
substituição, e a origem segue o caminho natural do churn (correr atrás). Se o
cliente renovar de fato depois (negócio ganho), a renovação reaparece sozinha.
Pelo mesmo princípio, `raut_mes` passou a descartar venda de RAUT cujo negócio
já está perdido: a tabela de vendas retém negócio perdido por um tempo (o RAUT
da ROHR ainda estava lá dias depois de perder), e ele não pode alimentar o MRR
novo de uma renovação sem sucessor.

Caso motivador: contrato nº `321378` (DE MELO MARQUES, Renata, ago/2026). O
RAUT `62688936511` e o negócio AM `62674799972` (o único associado ao sucessor
`60165725596`) foram perdidos, não há venda em 2026 para o número, e mesmo
assim o sucessor seguia Ativo na carga de 17/08 08:15. Antes o painel mostrava
renovação de delta +177,55 sem negócio; agora o cliente aparece no churn com
R$ 407,00 a recuperar. NRR da Renata em ago/2026: 1,0071 → 1,0061 (Evoluído
−584,55).

Validação de 17/08/2026: diff antes/depois das 5 carteiras em ago/2026 e
jul/2026. Além do 321378, o diff só acusou a renovação nova da DAZO
(`544075`, Mariana), dado legítimo que chegou na carga das 08:15 entre as duas
fotos (origem desativada e sucessor `60367943268` criados em 17/08, negócio
ganho `63221681738`).

Validação de 17/08/2026 (ago/2026 e jul/2026, as 5 carteiras AM): 90 renovações
e 16 impulsos, todos com negócio preenchido menos o `321378` acima. Casos que
exigem as duas fontes: `631731` só tem venda, pois a renovação veio por RAUT
sem contrato sucessor; `632581` e `632675` (início em mês futuro) só têm
associação. Quando as duas fontes divergem, vale a associação: o contrato
`60173636144` (VIVACOM, nº `631608`, Renata) tem dois deals de renovação no mês
e só o `63497824541` está associado ao contrato novo.

## Colunas novas da HUBSPOT_CONTRATOS (13/08/2026)

O dbt recriou `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS` em 13/08/2026 (por
volta de 14h BRT) com colunas MAIÚSCULAS sem espaço/acento ("Id do contrato"
virou `ID_DO_CONTRATO`, "Data de início" virou `DATA_DE_INICIO`, e assim por
diante); `NUMERO_DO_CONTRATO` virou `NUMBER(38,6)` e a data de desativação dos
contratos Ativos usa o placeholder `1900-01-01` (a semântica "nunca nula" se
mantém). As consultas AM e o mapeamento número/id de contrato da Recuperação
de Cancelamentos foram ajustados no mesmo dia em `utils/commission.py`, sem
mudança de semântica. As demais fontes (VENDAS_REALIZADAS_POR_ITEM,
LISTA_POTENCIAL_FARMER, DEALS, associações) não foram renomeadas. A
LISTA_POTENCIAL_FARMER ganhou a coluna `ACCOUNT_MANAGER_EMAIL`, ainda não
utilizada pelo código.

## Exclusões administrativas da carteira (07/08/2026)

Quando um contrato não deve compor a carteira de uma AM, o administrador o
registra em `SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM` com solicitante e motivo.
O contrato fica fora do MRR Inicial e, por consequência, do MRR Evoluído ao
vivo. A AM vê a relação de exclusões atribuídas à própria carteira em Minha
Comissão. Snapshots já fechados preservam o resultado até serem refeitos.

## Implementação (06/08/2026)

- `utils/commission.py`: constantes AM (`AM_DESDE=(2026,8)`, carteira SQL,
  pipes por ILIKE), `_am_sql` + `_am_processar` no `montar_contextos` (desde
  14/08/2026, UMA query por mês AM com as 5 medidas via UNION ALL sobre as
  mesmas CTEs, meses em lote assíncrono; antes eram 4-5 queries por mês
  recomputando as CTEs), hook no despachante (antes de `_base_comissao` — AM
  independe de meta/
  parâmetros), `_calcular_am` (medidas + contrato padrão do painel:
  realizado=Evoluído, meta=Inicial, %atingido=NRR), 3 composições
  (`composicao_carteira_am`, `composicao_movim_am` com flag "fora da
  carteira", `composicao_churn_am`).
- `utils/connection.py`: wrappers cacheados `get_carteira_am`, `get_movim_am`,
  `get_churn_am`.
- `_comissao.py`: layout alternativo AM (resumo com Crescimento colorido,
  segmento Evolução da Carteira com a cadeia de cards, alerta+lista de
  clientes para recuperar, expanders de carteira e movimentações).
- Meses < ago/2026 não executam nada de AM; validação legado×novo inalterada.

## Pendências de negócio

> Esta lista nasceu no levantamento inicial de 06/08/2026. Considere como
> vigente apenas o que também aparecer em `docs/00_estado_atual.md`; os demais
> itens preservam o contexto da investigação.

1. **Regra de comissão sobre o NRR**: como o NRR vira dinheiro? Faixas/
   patamares (estilo Saving), aceleradores por cliff (estilo OTE MRR), ou
   linear? Qual o NRR-meta (100%?) e existe cliff mínimo?
2. **Churn no MRR Evoluído**: pela regra literal (Inicial + vendas AM +
   raut), o evoluído nunca cai — contratos desativados DURANTE o mês não
   subtraem. É isso mesmo (churn só aparece no Inicial do mês seguinte), ou
   o evoluído deve ser a foto de fim de mês (desativações do mês subtraem,
   NRR pode ficar < 100%)? NRR clássico desconta churn.
3. **Atribuição do raut**: confirmar que é pela carteira (gerente de conta
   do cliente renovado), já que o consultor da venda raut é a conta coletora
   (thiago.oliveira). E raut de cliente SEM gerente de conta: fica de fora?
4. **Vendas AM para cliente fora da carteira**: a venda em pipeline AM conta
   pelo CONSULTOR da venda (mesmo se o cliente não estiver marcado com o
   gerente) ou só se o cliente for da carteira dela?
5. **Meta de NRR**: virá da RI (goals com pipeline novo) ou cadastro manual
   (form) por ora? Em que unidade (% ou R$ de MRR evoluído)?
6. **Congelamento do MRR Inicial**: calcular sempre ao vivo (flutua se
   contratos forem corrigidos retroativamente) ou fotografar no dia 1º de
   cada mês numa tabela própria (ex.: `SUPERSET.COMISSOES.CARTEIRA_AM_MENSAL`)?
   Recomendo a foto mensal — é o que garante o "inicial" imutável dentro do mês.
7. **Transição Farmer→AM**: a equipe Farmer deixa de existir a partir de
   ago/2026 (os 5 saem do modelo Farmer e entram no AM), ou convivem os dois
   modelos por um período? Afeta metas RI (pipeline Farmer - Deméter segue
   com goals), PVT (usa expansão de Sonia/Farmer) e o histórico deles.
8. **Cadastro incompleto da carteira** (achado 3): tem dono/prazo? O painel
   pode nascer com os números baixos e crescer conforme o cadastro, mas o
   NRR fica distorcido se o inicial estiver subestimado e as vendas contarem
   cheias.

## Fases do plano original (histórico)

> A medição AM descrita abaixo já foi implementada. Esta seção registra a
> sequência planejada no levantamento inicial e não representa uma fila atual.

1. Doc de regras fechado (este arquivo atualizado com as decisões).
2. Contexto em lote: consultas de carteira + movimentações (com validação de
   sanidade contra os números deste levantamento).
3. `_calcular_am` no despachante + campos novos no dict (`mrr_inicial`,
   `mrr_evoluido`, `nrr`, componentes) + `_montar_resultado`.
4. UI Minha Comissão (segmentos 1–2–3 acima) + Minha Equipe + Exportar.
5. Metas/Parâmetros dos 5 AMs (cargo/OTE/cliffs conforme regra).
6. Validação local (harness) + deploy + GRANT.
