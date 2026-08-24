# Estado Atual do Projeto

> Atualizado em 17/08/2026. Este é o resumo de fatos vigentes. Para contexto
> histórico e detalhamento, use os documentos numerados e `DECISOES.md`.

## Migração em curso (atualizado 19/08/2026)

- O painel está migrando do SiS para um app web próprio (FastAPI + Jinja2 +
  htmx), em `webapp/`. Fatos, decisões e detalhamento técnico ficam em
  `docs/21_migracao_web.md` (documento vivo, atualizado a cada fase); este
  resumo aqui é só o status. **Fica só SiS e webapp**: o estágio de
  demonstração via Claude Artifact foi cancelado em 19/08/2026 (a pasta
  `artifact/` que existia foi apagada; nunca esteve versionada no git).
- **O SiS continua sendo a produção e intocado**: nada em `webapp/` entra no
  deploy do Streamlit (`snowflake.yml` só lista os arquivos do SiS). Escritas
  de verdade (Parâmetros, Metas, fechamento etc.) continuam sendo feitas no
  painel Streamlit até o cutover formal.
- Estágio **localhost com paridade funcional completa**: dados/cálculo,
  leitura (Minha Comissão, Minha Equipe, PVT, RLS) e escrita (as 16 páginas
  admin do SiS têm equivalente no webapp, hoje desligado por padrão via
  `WRITES_ENABLED`). Falta só o estágio servidor (Docker + OAuth de produção
  + cutover de escritas), com duas pendências externas: rodar
  `webapp/ops/service_account.sql` no Snowflake e criar o OAuth Client no
  Google Cloud Console.
- **Exportação para Google Drive (só no webapp, 21/08/2026)**: todo botão de
  exportação (Minha Comissão, Minha Equipe, admin) sobe a planilha pro Drive
  da própria pessoa via OAuth (escopo `drive.file`), com hyperlinks
  embutidos nas células — substituiu o download `.xlsx`. Detalhe e a
  pendência de persistência do token antes do servidor em
  `docs/21_migracao_web.md`. SiS não foi tocado; segue só com o download de
  sempre.
- O repositório é versionado com git desde 17/08/2026; `output/` está no
  `.gitignore`.

## Produto em produção

- App: `SUPERSET.COMISSOES.PAINEL_COMISSOES`.
- Plataforma: Streamlit in Snowflake.
- Entrada: `Minha_Comissao.py`.
- Deploy: `./deploy.ps1`, pela conexão Snowflake `local_cli`.
- Acesso de usuários: `ROLE_METAS_EDITORS` recebe `USAGE` no Streamlit pelo
  próprio script de deploy.
- Visualizadores globais (20/08/2026): a chave `visualizadores_globais` da
  CONFIG (lista de e-mails separada por vírgula, editável em 🔧 Configurações,
  vigente desde abr/2026) dá ao e-mail listado a visão de TODOS os
  consultores no filtro de Minha Comissão, mas com tipo "Consultor": nenhuma
  outra aba aparece. A checagem fica em
  `utils/connection.py:_consultores_rls_data` (antes do deny-by-default) e no
  espelho `webapp/services/rls_service.py:consultores_rls`. Primeiro usuário:
  paulo.pereira@altoqi.com.br.
- Minha Comissão mostra um chip "Atualizado em" na linha dos filtros
  (19/08/2026, fonte trocada em 20/08/2026), com a hora da última
  sincronização da fonte de dados: para quem não é GD/SDR vem de
  `HUBSPOT_VENDAS_REALIZADAS_POR_ITEM.ATUALIZACAO`; para GD e SDR fora do
  time GD (cujo realizado é Opps, não vendas) vem de
  `MAX(TO_TIMESTAMP(HUBSPOT_OURO.HUBSPOT_REALIZADO_GD.ATUALIZACAO))`.
  Implementado igual no SiS (`utils/connection.py:render_filters`) e no
  webapp (`webapp/services/comissao_service.py`, mesmas duas fontes e o
  mesmo critério de qual usar).

## Mapa técnico vigente

| Responsabilidade | Local |
| --- | --- |
| Navegação, RLS de interface e shell | `_app.py` |
| Entrada (só delega ao `_app.py`) | `Minha_Comissao.py` |
| Minha Comissão | `_comissao.py` |
| Minha Equipe e administração | `pages/` |
| Cálculo de todos os modelos | `utils/commission.py` |
| Sessão Snowflake, cache, RLS e leitura de snapshot | `utils/connection.py` |
| Fechamento e persistência de snapshot | `utils/fechamento.py` |
| Estilos e componentes comuns | `utils/ui.py` |

## Fontes e invariantes

- Vendas realizadas: `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`.
  A migração e suas validações estão em `docs/19_migracao_vendas_ouro.md`.
- Contratos e carteira AM: `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONTRATOS` e
  `HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER`.
- Negócios e associações contrato-negócio (19/08/2026): migrados de
  `HUBSPOT_PRATA.DEALS` (view legada de outro projeto dbt, lia o bronze) e
  `HUBSPOT_PRATA.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL` para
  `HUBSPOT.HUBSPOT_OURO.HUBSPOT_DEALS` e
  `HUBSPOT.HUBSPOT_OURO.HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL`. Paridade
  validada em 19/08/2026 (associações idênticas; deals com defasagem só de
  atualização — ouro atualiza via DAG, a view legada era live no bronze).
  Mesmos nomes de coluna quoted ("Id do negócio" etc.); no ouro o id é STRING.
- Realizado GD migrado para o ouro (20/08/2026):
  `SUPERSET.COMISSOES.REALIZADO_GD` → `HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD`
  nas 3 queries de `utils/commission.py` e na página Admin Realizado GD.
  Paridade validada na migração: 152 vs 151 opps de agosto (defasagem do run
  horário), 9 consultores dos dois lados. O bloqueio anterior (prata
  `HUBSPOT_PRATA.HUBSPOT_LEADS` estagnada desde 11/08) foi sanado pela
  engenharia em 19/08. O chip "Atualizado em" de GD/SDR passou do bronze
  (`_AIRBYTE_EXTRACTED_AT`) para
  `MAX(TO_TIMESTAMP(HUBSPOT_REALIZADO_GD.ATUALIZACAO))` — SiS e webapp.
- Cancelamentos migrados para o ouro (21/08/2026):
  `SUPERSET.COMISSOES.CONSULTA_CANCELAMENTOS` →
  `HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS`, nas 2 queries
  de `utils/commission.py` e nos `get_mrr_recuperado_canc` do SiS
  (`utils/connection.py`) e do webapp (`webapp/services/comissao_service.py`).
  A tabela foi corrigida pelo PR AltoQiTec/data-platform#500 (regra: pipeline
  "CS - Saving | Pedidos de Cancelamento" id 140387887 + etapa "Salvo" id
  240497234 + purga de órfãs via post_hook) e validada em 21/08: 192 linhas
  totais, 2026 = 131 / R$ 956.804,46, zero linhas fora da regra. As queries
  do painel ganharam o recorte `EXISTS (... PARAMETROS ...
  IS_CANC_RECOVERY = TRUE)` — a tabela nova cobre todas as consultoras do
  pipeline (inclui Saving), enquanto a view legada hardcodava as duas da
  equipe Cancelamento. Diferença de regra vs a view legada (apurada
  19/08/2026): 13 deals entram (salvos por Saving/outros) e 5 saem (deals
  das consultoras fora do pipeline) — mudança de negócio intencional,
  solicitada pelo P.O. As views legadas do SUPERSET não são mais consumidas
  pelo painel e podem ser descomissionadas após validação com demais
  consumidores.
- `HUBSPOT_CONTRATOS` foi recriada pelo dbt em 13/08/2026 com colunas
  MAIÚSCULAS sem espaço/acento (`ID_DO_CONTRATO`, `DATA_DE_INICIO`,
  `NUMERO_DO_CONTRATO` agora `NUMBER(38,6)`, etc.); os nomes antigos entre
  aspas ("Id do contrato") não existem mais. `utils/commission.py` foi
  ajustado no mesmo dia. A data de desativação dos contratos Ativos usa o
  placeholder `1900-01-01`. As demais fontes HUBSPOT não mudaram; a
  `HUBSPOT_LISTA_POTENCIAL_FARMER` ganhou `ACCOUNT_MANAGER_EMAIL` (ainda não
  usada pelo código).
- Metas, parâmetros, ajustes e snapshots: schemas `SUPERSET.COMISSOES`,
  `SUPERSET.PARCIAL` e Revenue Intelligence, conforme o modelo e o período.
- Metas na `SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS` seguem a
  precedência **override > RI > form** de jul/2026 em diante; até jun/2026 é só
  o form. O override fica em `SUPERSET.COMISSOES.METAS_OVERRIDE` e é a única
  forma de corrigir uma meta pelo painel nos meses em que a origem é a RI, já
  que a tela Admin → Metas é somente leitura nesses meses. A manutenção fica em
  Administração → Override de Metas (`pages/26_Admin_Metas_Override.py`). Ver
  `docs/18_migracao_metas_ri.md`.
- Período fechado é lido das tabelas `FECHAMENTOS`, `COMISSOES_FECHADAS` e
  `COMPOSICAO_FECHADA`; ele não é recalculado ao vivo.
- Autoria de escrita (`UPDATED_BY`, `USUARIO`, `CREATED_BY`, `SOLICITADO_POR`)
  usa `audit_user(session)` / `audit_user_sql(session)` de `utils/connection.py`,
  nunca `CURRENT_USER()`: no SiS o app roda com owner's rights e
  `CURRENT_USER()` retorna NULL. O helper devolve sempre e-mail e nunca vazio.
- Valores interpolados em SQL sempre passam por `.replace("'", "''")`
  (sanitização de 13/08/2026: corrigidos os 8 pontos que interpolavam texto de
  input ou do banco sem escape). Não há binds no SiS (`utils/`, `pages/`); ao
  criar query nova nesse lado, escapar todo valor textual. O webapp usa binds
  `%s` (`webapp/db/shim.py`, paramstyle pyformat) nas queries próprias dele
  (`rls_service.py`, `comissao_service.py`, `admin_repo.py`); o código
  compartilhado importado via shim continua chamando `sql(q)` sem params.
- `Minha_Comissao.py` apenas delega ao `_app.py` (13/08/2026): o ramo
  alternativo via `st.navigation` foi removido por estar divergente e depender
  da versão do Streamlit no SiS.
- Dicionários de meses têm fonte única em `utils/connection.py` (`MESES_NOME`
  e `MESES_ABREV`, 13/08/2026); páginas importam com alias em vez de redefinir.

## Estabilidade visual no SiS

Desde 12/08/2026, `render_interaction_guard()` (`utils/ui.py`) injeta o CSS
completo do painel (`_CSS_SHELL_HEAD` + `_CSS_GLOBAL`) no `<head>` do
documento pai. O `<head>` sobrevive aos reruns, então o visual não quebra mais
quando o usuário interage durante o carregamento (os blocos `<style>` do corpo
somem a cada rerun). Fatos apurados por sonda no SiS: JS inline em iframe de
componente funciona, `window.parent.document` é acessível, mas NÃO existe
`[data-testid="stApp"]` nem `data-test-script-state` — código que dependa
desses seletores fica morto. Desde 13/08/2026 o `_app.py` importa
`_CSS_SHELL_HEAD` de `utils/ui.py` em vez de manter cópia própria: o CSS do
shell tem fonte única e não exige mais sincronia manual. A sonda
`render_guard_probe()` em `utils/ui.py` fica disponível para diagnósticos
futuros. Detalhe em `docs/DECISOES.md` e na regra visual fixa do `CLAUDE.md`.

### Anti-fantasma nas transições (13/08/2026)

Durante um rerun o Streamlit mantém o DOM da execução anterior na tela,
marcado com `data-stale="true"`, e só o esmaece após ~1s; na troca de aba a
página anterior inteira ficava visível ("fantasmas") até a nova terminar de
renderizar. O `_CSS_SHELL_HEAD` esmaece esses elementos com atraso de 0,6s
(`opacity .15`, `transition .3s ease .6s`): rerun rápido não esmaece nada
(sem o atraso, todo clique escurecia a tela e o app parecia mais lento, o
que foi corrigido no mesmo dia), e a volta é instantânea porque o estado
base não define transition. Não usar `display:none` nem `pointer-events`
nessa regra: apagaria ou travaria a página a cada interação pequena. Na TROCA
de página/aba (inclusive o selectbox de administração) e na TROCA de FILTRO
(ano/mês/equipe/consultor), `hide_stale_on_change` (`utils/connection.py`)
injeta um estilo de um rerun só que zera a opacidade dos elementos antigos na
hora; chamado no `_app.py`, no `render_filters`/`render_period_filter` e na
Minha Equipe. Interações que não mudam página nem filtro não são afetadas.

O banner NÃO é mais um elemento Streamlit (arquitetura final de 14/08/2026):
é CSS puro, `::before` do block-container (`_CSS_BANNER` em `utils/ui.py`,
incluído no `_CSS_GLOBAL` e no `<head>` persistente). Motivo: no SiS 1.22,
transições rápidas de página removem elementos do DOM e nada os recria (nem
reenvio com delta novo a cada rerun; só F5 trazia o banner de volta). O
block-container nunca é removido, então o banner é imune por construção.
`render_banner()` hoje só injeta o CSS global. Não voltar a renderizar o
banner como elemento. O `hide_stale_on_change` SEMPRE renderiza um `<style>`
(neutro quando não há troca): no Streamlit 1.22 a identidade dos elementos é
posicional, então um elemento condicional no topo deslocaria os seguintes, e
o bloco neutro substitui o de esconder logo no início do rerun seguinte.

### Custo por rerun (13/08/2026)

Cada interação reexecuta o script inteiro, então as queries "fixas" do topo
definiam a latência de qualquer clique. Ficaram cacheadas:

- `_consultores_rls_data` e `_equipes_consultores_data`
  (`utils/connection.py`, `st.cache_data` ttl=1800): o `render_filters` não
  paga mais até 5 round-trips por rerun. Edições nas telas admin invalidam
  pelo `st.cache_data.clear()` que elas já fazem ao salvar. O TTL subiu de
  300 para 1800 em 14/08/2026 (o recarregamento custava ~3s a cada 5 min).
- Gating das abas Saving/PVT no `_app.py`: resultado em `session_state`,
  chaveado por e-mail (e ano, no caso Saving), então "Visualizar como"
  invalida sozinho. Conceder IS_PVT a alguém no meio de uma sessão aberta
  passa a exigir refresh da página dessa pessoa.
- `get_mrr_recuperado_canc` (`utils/connection.py`): a query inline que a
  `_comissao.py` fazia a cada rerun no layout de Cancelamento.
- `get_comissao_hist` (14/08/2026): o resultado final é cacheado. Sem isso, o
  expander de histórico refazia a cada rerun a desserialização do contexto
  multi-mês e o recálculo dos meses abertos, mesmo fechado.
- `_get_snapshot_fid` passou de ttl=300 para 3000 (14/08/2026): com TTL curto
  a Minha Equipe pagava 1 query por membro a cada expiração. Ficou seguro
  porque tanto FECHAR quanto REABRIR período limpam o cache global (o clear
  ao final do fechamento foi adicionado na mesma data na página Exportar).
- `df_download_link` (14/08/2026): a geração do .xlsx (openpyxl + base64) é
  cacheada; rodava em todo rerun para cada tabela exportável.

Diagnóstico de 13/08/2026 via QUERY_HISTORY: com os caches acima, as
interações rodam praticamente sem queries; o tempo restante é o piso do SiS
(rerun completo do script no warehouse) e trabalho Python por rerun. O
`DATAANALYST_WH` é X-Small, compartilhado com cargas dbt, `auto_suspend=60s`
(cold start ao abrir após ociosidade; decisão de custo pendente). Medições
da instrumentação (14/08/2026, Streamlit 1.22.0 no SiS): interações quentes
custam 0,3 a 1,8s; o custo frio é a montagem do contexto.

### Contexto em lote assíncrono (14/08/2026)

`_lote_pandas` em `utils/commission.py` dispara as queries do
`montar_contextos` (15 do bloco principal, 9 do trimestral) de uma
vez via `to_pandas(block=False)` do Snowpark e coleta depois. As medidas AM
viraram UMA query por mês (`_am_sql`, UNION ALL das 5 medidas sobre as mesmas
CTEs, 14/08/2026: antes eram 4-5 queries recomputando as CTEs de movimentação
a cada uma), com os meses AM batelados juntos no mesmo lote assíncrono. Se o runtime
não suportar async ou qualquer erro ocorrer, o lote inteiro cai no caminho
sequencial (comportamento antigo). Validação: antigo vs novo idênticos em
120/120 pessoas (06 e 08/2026, cobrindo os três blocos); ganho medido sem
result cache ~25-30% no X-Small (o warehouse pequeno é o teto — as queries
paralelas disputam a mesma máquina; warehouse maior ampliaria o ganho).
O baseline `validacao/baseline_2026_06.json` está DEFASADO (campos novos,
metas de junho alteradas na base, arredondamentos do rebuild dbt de 13/08):
falhas dele contra o código atual não indicam erro; recapturar quando útil.

A instrumentação temporária de desempenho (perf_reset/perf_mark/perf_report)
foi removida em 14/08/2026 após o diagnóstico. Decisão registrada: o
warehouse `DATAANALYST_WH` NÃO será trocado nem redimensionado para o painel
(orientação do Higor, 14/08/2026); otimizações devem ser feitas no código.

## Modelos de cálculo ativos

- Modelo principal: Ares, B2B, Farmer, FSB e Sonia.
- Saving: patamares a partir de abril/2026.
- GD: realizado em Opps.
- B2G: eixos de ARR e Booking; gestores têm regra própria.
- Cancelamento: recuperação de cancelamentos e dívidas.
- PVT: cálculo coletivo trimestral.
- Account Manager: medição por NRR da carteira a partir de agosto/2026. A regra
  de comissão sobre NRR ainda depende de definição de negócio. Desde 12/08/2026
  as AMs aparecem como duas equipes conforme o pipeline RI: `AM GDC`
  (aline.pureza, clidiani) e `AM Escritório` (debora.vieira, mariana,
  renata.parizotto).

## AM - regra vigente de churn

Churn AM representa perda real de receita, não apenas um contrato inativado.
Contratos de origem não entram no churn quando houver continuidade comercial:

- `Contrato gerado por impulso` preenchido; ou
- contrato sucessor do mesmo cliente iniciado no mesmo mês da desativação, com
  MRR igual ou maior.

A regra está em `utils/commission.py` e vale tanto para o NRR quanto para a
lista detalhada de churn. Ver `docs/20_aba_comissoes_am.md`.

## AM - modelo vigente de movimentações de contrato

O NRR é calculado por eventos de contrato, e não pelo MRR bruto de pipelines:

`MRR Evoluído = MRR Inicial + Upsells + Deltas de Renovação + Deltas de Impulso - Churn`

- **Novo negócio:** contrato novo originado nos pipelines AM, e-commerce ou
  saving que não substitui outro contrato; adiciona o MRR cheio. Nos
  pipelines AM a própria AM precisa ser a consultora da venda; e-commerce e
  saving creditam pela carteira, qualquer consultor (decisão de 13/08/2026).
  O painel exibe o grupo em card e expander próprios desde 13/08/2026.
- **Upsell:** substituição cujo contrato sucessor tem subtipo upsell/cross
  sem `renov`; adiciona só o delta, com MRR anterior e novo exibidos no
  painel. A classificação segue o subtipo do contrato sucessor, nunca o
  pipeline ou o consultor da venda (decisão de 13/08/2026).
- **Renovação:** substitui o contrato inicial pelo novo, inclusive para RAUT;
  impacto = `MRR novo - MRR anterior`. Quando a nova linha de contrato ainda
  não chegou à base, a RAUT faz a comparação provisória com seu MRR vendido.
- **Impulso:** localiza os pares origem/consolidado por duas vias, as
  associações do negócio de impulso e o campo `Contrato gerado por impulso`
  da origem (que carrega o número do contrato novo; há impulso sem negócio
  associado). Compara a soma das origens com o MRR do contrato novo. Origens
  vêm de TODOS os contratos, inclusive de outro registro de cliente (ex.:
  contratos PF do contato consolidados no contrato PJ da empresa
  encarteirada); o delta credita a gerente do contrato consolidado e origem
  de outra carteira não cruza (13/08/2026). Só contam como origem linhas
  vigentes no dia 1º do mês; linhas históricas ou criadas e desativadas
  dentro do mês recebem a data de desativação carimbada pelo impulso e não
  devem ser subtraídas (13/08/2026).
- **Downgrade:** quando o contrato novo tem outro número e sem venda no mês,
  o vínculo vem do nome do negócio que gerou o contrato novo (número do
  contrato substituído após a palavra downgrade/downsell). O antigo sai do
  churn e o delta entra no grupo Upsells com tipo `Downgrade` (13/08/2026).
- **Churn:** contrato do Inicial inativado sem substituição identificada.

Assim, renovação igual gera zero, upsell/downsell em uma renovação gera delta
positivo/negativo e contratos substituídos não aparecem como churn.

## AM - exclusões administrativas da carteira

Contratos cadastrados em `SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM` não entram
no MRR Inicial nem no MRR Evoluído ao vivo. A tela de Administração registra o
ID do contrato, solicitante e motivo; a AM visualiza as exclusões da própria
carteira na página Minha Comissão. Para períodos fechados, é necessário
reabrir e refazer o fechamento para atualizar o snapshot.

## Pendências reais

0. As associações contrato-negócio ficam dias defasadas da `DEALS` (13/08/2026:
   carga parada desde 11/08 de manhã). Vale para as duas fontes, que são
   idênticas: a view `ASSOCIATIONS_CONTRATO_DEAL` (rename sobre o bronze) e a
   tabela dbt `HUBSPOT_ASSOCIATIONS_CONTRATO_DEAL`, usada pelo cálculo desde
   13/08. O cálculo AM já não depende só delas (impulso usa o campo do
   contrato; downgrade usa o "Número do contrato" do negócio), mas vale pedir
   ao time de dados um refresh mais frequente da ingestão de associações.
1. Definir como o NRR AM se converte em comissão, meta e possíveis cliffs.
2. Decidir se o MRR inicial AM deve continuar ao vivo ou ser fotografado no
   primeiro dia de cada mês.
3. Manter a carteira AM completa e correta para que a medição de NRR reflita a
   responsabilidade comercial.

## Após uma mudança

1. Atualize este arquivo se um fato vigente mudou.
2. Registre decisão de negócio em `docs/DECISOES.md`.
3. Atualize a documentação de domínio.
4. Valide sintaxe e a regra no Snowflake antes de publicar.
