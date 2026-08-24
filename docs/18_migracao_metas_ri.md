# Migração da Fonte de Metas — Revenue Intelligence (jul/2026+)

> **Status: DESBLOQUEADO em 29/07/2026** — a prata ganhou `REDUCTION_PCT` e
> `TARGET_VALUE` passou a ser a meta BRUTA (jul/2026+). Nova definição da view pronta para revisão em `docs/18_nova_view_metas_ri.sql`.
> Baseline de julho pré-migração capturado (fase 3). Restam as ressalvas abaixo.

## Objetivo

A partir de **julho/2026**, as metas dos **consultores** passam a vir do Revenue
Intelligence (RI). Abril, maio e junho/2026 permanecem exatamente como estão
(fonte atual + snapshots fechados). SDRs/GD ficam **fora** desta migração (fonte
já migrada antes — inclusive a prata tem `REVENUE_INTELLIGENCE_GD_OWNER_TARGETS`
separada, coerente com isso).

## Calibração da nova semântica (29/07/2026)

- `REDUCTION_PCT` em **escala 0–100** (NULL = sem redução): fernanda.fertonani
  jul = 50.0; renata.parizotto jul = 48.0. Líquida = bruta × (1 − pct/100).
- Derivação bate com o form ao centavo: fernanda 9.500×0,50 = 4.750 ✓;
  renata 12.750×0,52 = 6.630 ✓ — as duas "divergências de julho" do plano
  original estavam certas no form e agora a RI as representa corretamente.
- **Junho na RI continua com a semântica antiga** (target = líquida, pct NULL).
  Irrelevante: o corte é jul/2026 e o modelo não lê RI antes disso.

### ⚠️ Ressalva de qualidade de dados (verificar com o time da RI)

Três metas de julho parecem já REDUZIDAS no `TARGET_VALUE`, com `REDUCTION_PCT`
vazio/zero — nesses casos o painel veria a meta certa, mas **não reduziria o
OTE Base** (o % é o que reduz o OTE):

| Pessoa | TARGET jul | pct | Suspeita |
|---|---:|---|---|
| Thales Mariante de Sá | 5.214 | NULL | colegas Construtoras têm 9.480 (rampagem?) |
| Luiz Guilherme Groff Dos Santos | 2.340 | NULL | novo, ~25% do padrão da equipe |
| Luciana Vieira | 14.029,78 | 0 | colegas B2G têm 140k–524k |

Se a intenção é reduzir OTE junto, a carga correta é bruta cheia + pct
preenchido. Se a intenção é meta menor SEM redução de OTE, está certo como está.

## ⛔ Impeditivo (decisão do Higor, 28/07/2026) — RESOLVIDO em 29/07/2026

A `REVENUE_INTELLIGENCE_CONSULTANT_GOALS` da prata tem **apenas `TARGET_VALUE`**.
Era esperado que a prata já tivesse **MRR bruto, MRR líquido e percentual de
redução**. Verificado em 28/07: nenhuma das 6 tabelas do schema
(`CONSULTANTS`, `CONSULTANT_GOALS`, `CONSULTANT_PIPELINE_ASSIGNMENTS`,
`GD_OWNER_TARGETS`, `OWNERS`, `PIPELINES`) tem esses campos.

**A migração só continua depois que a prata expuser os três campos.** Quando
existirem, o mapeamento fica direto e o painel não precisa de premissas:

| Campo prata (a criar) | Coluna no contrato do painel |
|---|---|
| meta bruta | `META_MRR_BRUTO` |
| meta líquida | `META_MRR` (equipes MRR) / `META_OTR` (Governo = Booking) |
| % redução | `PERCENTUAL_DESCONTO_METAS` (reduz OTE Base) |

Com isso a RI vira dona também do desconto — elimina o risco de divergência de
desconto entre sistemas (caso thales: form 67% × RI ~50%).

## Decisões já tomadas (28/07/2026)

| # | Tema | Decisão |
|---|---|---|
| 2 | Divergências form × RI em julho (fernanda.fertonani, renata.parizotto, thales) | **Vale a RI** para jul/2026+ |
| 3 | Bruto/líquido/% redução | Devem vir da prata — **impeditivo** até existirem |
| 4 | Gestores | **Entrarão na RI.** O desenho já absorve: linha RI quando existir, fallback form enquanto não existir — sem retrabalho |
| 5 | Pessoas novas na RI (ex.: Luiz Guilherme→luiz.santos@, Luciana Vieira→luciana.vieira@) | Entram. Criar **alerta admin**: pessoas com meta na fonte mas sem registro em RLS e/ou Parâmetros |
| 6 | Admin → Metas (página 21) | Por mês filtrado: **≤ jun/2026 = edição como hoje; ≥ jul/2026 = somente visualização** da tabela que compõe as metas |

## Questão 1 — DECIDIDA: Opção B (28/07/2026)

A regra "form até junho, RI de julho em diante" entra na própria
`METAS_CONSULTORES_CONSOLIDADAS`. O painel não muda nenhuma referência de
código (continua lendo o mesmo nome), e todos os consumidores da view passam a
ver as metas da RI a partir de jul/2026 automaticamente.

**Esclarecido em 29/07/2026: a view NÃO é dbt** — é uma view direta no
Snowflake, dona = role `DATA_ENGINEER` (GENERAL_ANALYST, usado pelo painel/CLI,
só tem SELECT). Consequências práticas:
- Aplicação = `CREATE OR REPLACE VIEW ... COPY GRANTS` executado por alguém com
  o role **DATA_ENGINEER**, pelo **Snowsight** (nunca `snow sql -f`, que
  corrompe os acentos dos nomes de pipeline). SQL pronto em
  `docs/18_nova_view_metas_ri.sql`.
- `COPY GRANTS` é obrigatório: preserva os SELECTs de DATA_ANALYST,
  DATA_ENGINEER e GENERAL_ANALYST (sem este último o painel cai).
- O de-para pipeline→equipe e o corte de vigência ficam no SQL da view.
- O dono (DATA_ENGINEER) precisa de SELECT em
  `revenue_intelligence.revenue_intelligence_prata.*`.
- Rollback = `docs/18_rollback_metas_view.sql` (definição original + COPY GRANTS).

## De-para (RESOLVIDO — não precisa de tabela manual)

`CONSULTANTS.HUBSPOT_OWNER_ID → OWNERS.EMAIL` entrega o e-mail de todos os
consultores ativos, validado em 28/07 inclusive para os casos onde nome≠e-mail
(Aline Castilho→aline.pureza@; Jordayn Wall→jordayn.almeida@; Thales Mariante de
Sá→thales.sa@). O de-para vira um JOIN na view. Consultor com meta e sem e-mail
(owner faltando) entra no alerta admin da decisão 5 — nunca some em silêncio.

Pipeline→equipe e o corte de vigência (jul/2026) ficam no SQL da view
(decisão da questão 1 — opção B):

| Pipeline RI | Equipe no painel |
|---|---|
| CS - Saving | Saving |
| Comercial B2B - Construtoras | B2B Construtora |
| Comercial B2B - Escritórios | B2B Escritório |
| Comercial B2G | Governo (meta = Booking → `META_OTR`) |
| Comercial FSB | FSB |
| Farmer - Deméter | Farmer |

## Desenho da view (quando o impeditivo cair)

```
≤ 2026-06  → passthrough da fonte atual (nada muda; meses fechados ainda
             protegidos pelo roteamento snapshot-first)
≥ 2026-07  → UNION de:
   (a) RI: consultant_goals × consultants × owners (e-mail) × pipelines
       (equipe via CONFIG), com bruto/líquido/% redução da prata
   (b) fallback form: quem NÃO tem linha RI no mês (hoje gestores, Ares,
       Sonia; GD/SDR sempre) — desaparece naturalmente conforme a RI cobrir
```

## Fatos de referência do levantamento (28/07/2026)

- RI `target_value` atual = meta LÍQUIDA (calibrado com jun/2026: bate ao
  centavo com o form para Saving, FSB, Farmer, Escritórios).
- Julho no form está incompleto (só Escritório/Farmer/Saving, 16 linhas); RI
  tem as 35 completas incluindo Governo — a migração conserta o mês corrente.
- Governo na RI só existe a partir de julho (ok, corte é julho).
- Ares não tem pipeline na RI (sem metas em jun/jul no form também).

## Fases de execução (após o impeditivo cair)

1. ✅ Confirmar os campos novos na prata e recalibrar (feito 29/07 — ver
   Calibração; resta a ressalva thales/luiz/luciana com o time da RI).
2. ✅ Redigir a nova definição da view (`docs/18_nova_view_metas_ri.sql`) e o
   rollback (`docs/18_rollback_metas_view.sql`).
3. ✅ Baseline de julho pré-migração: `validacao/baseline_2026_07_pre_ri.json`
   (54 pessoas, script `validacao/baseline_julho_pre_ri.py`).
4. ✅ **View aplicada em 29/07/2026** (ownership transferido DATA_ENGINEER →
   GENERAL_ANALYST com COPY CURRENT GRANTS + CREATE VIEW no schema; Higor
   executou o replace).
5. ✅ Pós-aplicação (29/07): julho pela view OK (35 RI + fallback form: sonia,
   beatriz, GD); junho idêntico ao form (56 linhas, somas iguais); grants
   preservados; comparação contra baseline: 32 iguais, 20 ganharam meta (buraco
   de julho do form), fernanda.fertonani/renata.parizotto agora com desconto
   aplicado no OTE (comportamento correto), thales calculado com a ressalva do
   pct vazio, luiz.santos sem Parâmetros não calcula. Pendências: luiz.santos
   (sem Parâmetros+RLS), luciana.vieira (sem RLS). Vendas de julho sem meta
   (thiago.oliveira, anand.figueiredo, raquel.zanatta, jessica.souza):
   confirmado pelo Higor que NÃO devem ter meta por ora.
6. ✅ **Painel** (29/07): página 21 em modo visualização para ≥ jul/2026 (tabela
   da composição com coluna Fonte; edição mantida ≤ jun) + alerta de meta com
   cadastro incompleto (sem Parâmetros/RLS). Deploy + GRANT feitos.
7. ✅ `validar_hist.py` pós-migração (29/07): mar 36/36, abr 60/60, mai 61/61,
   jun 66/66 idênticos; lotes 223/223 e 242/242. Único diff: ana.camargo em jul
   (realizado GD 47→48 Opps) — corrida de dado vivo entre as duas passadas do
   próprio validador, não relacionado a metas. RLS de luiz.santos (gestor
   rafael.acencio) e luciana.vieira (gestor marcelo.maestro) inseridos em jul.

## v2 — 100% RI, sem fallback (29/07/2026, aplicada)

Por decisão do Higor: "de julho em diante, TODA meta deve vir do RI".
- Fallback do form REMOVIDO ≥ jul/2026: Sonia, Beatriz e demais gestores ficam
  SEM meta até serem cadastrados na RI (gestores preencherão aos poucos).
- GD passou a vir de `REVENUE_INTELLIGENCE_GD_OWNER_TARGETS`
  (OWNER_ID→owners.email; TARGET_QUALIFIED = Opps → META_OTR; filtro >0;
  TEAM='GD'). Calibração jun: idêntico ao form (72/22/22/75/72/72/72).
- ⚠️ GD_OWNER_TARGETS tem série jan/2025–jun/2026; **julho/2026 NÃO carregado**
  — Higor decidiu aplicar mesmo assim ("Aplicar agora"): GD de julho fica sem
  meta até a carga na RI. Cobrar carga com o time da RI.
- Conferido pós-aplicação: julho = 35 linhas, todas RI (4 Construtora, 2
  Escritório, 6 FSB, 5 Farmer, 11 Governo, 7 Saving); junho intacto (56 linhas,
  somas idênticas ao form); grants preservados.

Pendências externas: Parâmetros do luiz.santos; carga GD julho na RI; goals de
gestores/Sonia/Beatriz na RI; reduction_pct de thales/luiz/luciana (gestores vão
preencher aos poucos, decisão do Higor).

## v3 — fallback do form reativado (30/07/2026, VIGENTE)

Como os goals dos gestores vão demorar na RI, o Higor decidiu reativar o
fallback: **form (META_CONSULTOR) para quem não tem linha RI no mês** (≥ jul).
A RI vence sempre que tiver a linha — quando os goals de gestores e a carga GD
de julho chegarem, o fallback esvazia sozinho, sem novo deploy.

- Fallback hoje cobre: 4 gestores (metas de jul gravadas em 29/07: anderson
  61.340, motta 17.467, acencio 48.622, sonia 110.753 c/ espelho OTR),
  beatriz (Saving 124.243) e os 7 do GD (form de jul).
- Corrigido em 30/07 o e-mail truncado do form de jul:
  `lherme.marcolino@` → `guilherme.marcolino@`.
- Conferência pós-aplicação: jul = 35 linhas RI + 12 Form; junho intacto
  (view = form, 56 linhas, somas idênticas); grants preservados.
- SQL vigente: `docs/18_nova_view_metas_ri.sql` (v3).

Rollback: revert do modelo no dbt (o painel não precisa de mudança para voltar).

## v4 — override administrativo do painel (12/08/2026, VIGENTE)

Como a tela Admin → Metas é somente leitura de jul/2026 em diante e a RI é de
outro time, não havia caminho para corrigir uma meta de julho pelo painel. A v4
cria essa via:

- Tabela `SUPERSET.COMISSOES.METAS_OVERRIDE`: `ANO`, `MES`, `EMAIL`, `EQUIPE`,
  `PERCENTUAL_DESCONTO_METAS` (escala 0-100, igual à RI), `META_BRUTA`,
  `ATIVO`, `MOTIVO`, `USUARIO`, `DATA_REGISTRO`, `DESATIVADO_POR` e
  `DESATIVADO_EM`. A líquida é derivada como `bruta × (1 − pct/100)`, mesma
  conta do ramo RI.
- Auditoria: `USUARIO`/`DATA_REGISTRO` guardam quem definiu os valores;
  `DESATIVADO_POR`/`DESATIVADO_EM` guardam quem desativou. Desativar não toca
  nos dois primeiros e reativar limpa os dois últimos.
- A autoria vem de `require_admin(session)`, nunca de `CURRENT_USER()`: no SiS
  o app roda com owner's rights e `CURRENT_USER()` retorna NULL (ver
  `utils/connection.py`, `current_email`). A primeira versão da tela usava
  `CURRENT_USER()` e a desativação apagou a autoria das cinco linhas de julho,
  recuperada depois por Time Travel.
- Precedência na view: **override > RI > form**. A chave é
  `(ANO, MES, e-mail)`: quem tem override ativo no mês não entra nem pela RI
  nem pelo fallback do form. A coluna `FONTE` mostra `Override`.
- Vale só para `>= 2026-07`. Até jun/2026 a edição continua sendo direta no
  form pela própria tela, então o ramo antigo segue intacto por construção.
- Roteamento por equipe: Governo e GD vão para `META_OTR`; as demais para
  `META_MRR`, com `META_NMRR` espelhando o MRR fora de Saving, Governo, GD e
  os dois times de AM.
- Aplicação: `validacao/aplicar_view_metas_override.py` (connector, UTF-8).
  SQL vigente continua em `docs/18_nova_view_metas_ri.sql`.
- Tela: Administração → **🎯 Override de Metas**
  (`pages/26_Admin_Metas_Override.py`), tabela editável no mesmo padrão de
  Parâmetros. Valida equipe contra as equipes conhecidas do mês (equipe errada
  tiraria a pessoa da varredura do fechamento sem aviso), exige motivo, barra a
  mesma pessoa em duas equipes e avisa quando o mês tem fechamento ativo. Tirar
  a linha da tabela marca `ATIVO = FALSE` em vez de apagar; há expander para
  reativar. Abaixo do editor, uma tabela mostra a meta que a origem traria sem
  o override e a diferença.

### Primeiro uso: metas originais das consultoras Farmer em jul/2026

Decisão de negócio de 12/08/2026: valem as metas originais, não as propostas
que a RI carregou. Registros gravados:

| Pessoa | Bruta | % desc | Líquida | Meta anterior |
|---|---:|---:|---:|---:|
| aline.pureza | 11.000 | 0 | 11.000 | 6.600 |
| clidiani | 11.000 | 0 | 11.000 | 6.600 |
| debora.vieira | 8.600 | 0 | 8.600 | 6.000 |
| mariana | 14.300 | 0 | 14.300 | 12.750 |
| renata.parizotto | 14.300 | 50 | 7.150 | 6.630 (bruta 12.750, 48%) |

Conferência da aplicação: julho manteve 52 linhas (sem duplicata nem perda),
soma de `META_MRR` subiu 13.470 (exatamente a soma das cinco diferenças), junho
ficou idêntico ao form (56 linhas, mesmas somas) e os grants foram preservados
pelo `COPY GRANTS`.

> Observação sobre grants: o `SHOW GRANTS` hoje retorna apenas `OWNERSHIP` e
> `SELECT` para `GENERAL_ANALYST`. A menção a três roles nas seções anteriores é
> de 29/07, antes da transferência de ownership. `ACCOUNT_USAGE` não é visível
> para a role do painel, então não dá para reconstruir o histórico; o
> `COPY GRANTS` não remove concessões, então esse é o estado que já existia.

Pendência: pedir ao time da RI que alinhe os goals de julho dessas cinco. Com a
origem corrigida, os registros de override podem ser marcados `ATIVO = FALSE`
sem mudar nada no painel.
