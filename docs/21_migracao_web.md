# Migração para app web (fora do Streamlit)

> Iniciada em 17/08/2026. Plano aprovado pelo G0 no mesmo dia.
> Regra número um: **o app SiS continua no ar e intocado até o cutover.**

## Decisões (17/08/2026, escopo revisado em 19/08/2026)

- Sair do Streamlit: front server-rendered **FastAPI + Jinja2 + htmx** (tudo
  Python; sem toolchain JS além do htmx vendorizado).
- Escopo: **paridade completa** (Minha Comissão, Minha Equipe, PVT,
  Recuperação de Dívidas, 15 páginas admin, fechamento/reabertura).
- Estágios: (1) localhost → (2) servidor. Ficam só SiS e webapp.
- Hospedagem: provedor indefinido de propósito → container Docker portátil +
  **login Google OAuth (Authlib)** restrito ao domínio altoqi.com.br (a
  empresa é Google Workspace). Cloud Run + IAP fica como opção natural.
- Plano completo com fases e critérios: aprovado em 17/08/2026 (cópia em
  `.claude/plans/hidden-zooming-meadow.md` na máquina do Higor; o estágio de
  artifact do plano original foi cancelado, ver nota de 19/08 abaixo).

⚠️ **19/08/2026: estágio de artifact CANCELADO.** A ideia original tinha um
estágio intermediário de demonstração (`artifact/build_artifact.py` gerava
uma página HTML autocontida, publicada como Claude Artifact) entre o
localhost e o servidor. O Higor decidiu não seguir com essa estratégia; a
pasta `artifact/` foi apagada (nunca esteve versionada no git, então não
sobra nada em histórico de commit). Fica só localhost → servidor. O artifact
que já tinha sido publicado no claude.ai não foi apagado (a ferramenta não
oferece exclusão remota), mas segue privado e sem manutenção; ele continha 2
perfis reais (debora.vieira, aline.pureza, dados de agosto/2026 para testar o
layout AM) misturados aos 8 perfis de demonstração fictícios. As seções
abaixo sobre a Fase 7 e o `--extra` ficam só como registro histórico de
decisão, não descrevem nada que ainda exista no repositório.

## Como o SiS fica protegido

- Tudo novo vive em `webapp/`; o deploy SiS é allowlist (`snowflake.yml`) e
  nunca o enxerga.
- Nenhum arquivo deployado é editado: `webapp/bootstrap.py` registra um módulo
  sintético em `sys.modules["utils.connection"]` (padrão provado pelo
  `validacao/harness.py`) com exatamente o que `utils/commission.py:1615` e
  `utils/fechamento.py:14-17` importam.
- Streamlit não entra no processo do webapp (o smoke aborta se entrar).
- O webapp fica **read-only até a Fase 5**; edições admin continuam no SiS.
  Cutover de escritas será um evento único.
- Helpers de período foram COPIADOS para `webapp/core/periods.py`; mudanças de
  regra de período precisam ser feitas nos dois lugares enquanto o SiS viver.

## O que já existe (Fases 0-2, concluídas em 17/08/2026)

| Peça | Arquivo | Papel |
| --- | --- | --- |
| Versionamento | `.git` + `.gitignore` | repo era sem git; commit inicial `cf2763a` |
| Pedido do service account | `webapp/ops/service_account.sql` | enviar ao admin Snowflake (usuário SVC + role + grants) |
| Config | `webapp/config.py` | tudo por env var; dev usa `local_cli`, servidor usa key-pair |
| Sessão | `webapp/db/shim.py` | ShimSession (sql/to_pandas/collect) com binds `%s` |
| Pool | `webapp/db/pool.py` | pool thread-safe de conexões snowflake-connector |
| Cache | `webapp/core/cache.py` | TTLCache LIVE/RLS/SNAP_FID/SNAPSHOT + `invalidate_after_write()`/`clear_all()` |
| Períodos | `webapp/core/periods.py` | cópia dos helpers de `utils/connection.py:330-384` |
| Shim | `webapp/bootstrap.py` | `install_connection_shim()` — chamar antes de importar `utils.*` |
| Dados | `webapp/services/comissao_service.py` | os 17 wrappers + roteamento snapshot/vivo + histórico |
| Smoke | `webapp/smoke.py` | `python -m webapp.smoke` |
| Paridade | `validacao/validar_webapp.py` + `validacao/ref_harness_mes.py` | webapp vs harness por mês |

### Validações que passaram (17/08/2026)

- Smoke: snapshot de período fechado em 0,7s; cálculo vivo do mês aberto;
  repetição com **0 queries novas** (cache efetivo); sem streamlit no processo.
- Paridade: `python validacao/validar_webapp.py 2026-06 2026-07 2026-08` →
  **jun 66/66, jul 54/54, ago 54/54 pessoas idênticas** (tolerância 0,5
  centavo) entre o webapp e a referência harness (caminho SiS-equivalente).

### Nota sobre o baseline_2026_06.json

Ele NÃO serve mais de gate: foi congelado em julho, antes de mudanças de
negócio (metas RI v4 de 12/08, renovações de cancelamento,
`rotulo_aproveitamento`, recriação da HUBSPOT_CONTRATOS em 13/08). O próprio
SiS de hoje diverge dele. A comparação correta é webapp vs harness com o
mesmo código e os mesmos dados — é o que o `validar_webapp.py` faz.

## Como rodar localmente

```
cd "Painel de Comissões"
pip install -r webapp/requirements.txt                   # uma vez
python -m uvicorn webapp.main:app --reload               # http://localhost:8000
python -m webapp.smoke                                   # sanidade da camada de dados
python validacao/validar_webapp.py 2026-06 2026-08       # paridade por mês
```

Sem `.env`, o modo é dev: conexão `local_cli` e identidade fake
(`AUTH_MODE=dev`). Variáveis em `webapp/config.py`.

### Telas entregues em 17/08/2026 (Fase 4, modo dev)

Navegação por abas como no SiS (`base.html`), casca instantânea com spinner
e conteúdo por fragmento (`_loader.html`). No modo dev tudo opera como
admin (RLS por usuário chega na Fase 3).

- `/comissao`: os TRÊS layouts (AM, canc-recovery, padrão com variantes
  B2G/gestor/GD/Saving + trimestral), 4 filtros (ano/mês/equipe/consultor)
  na URL, badge de período fechado. Primeira carga de mês aberto paga o
  contexto (~1-2 min, como no SiS); repetições <0,5s pelo cache.
- `/equipe`: visão admin (líder → equipe), loop por membro em PARALELO
  (ThreadPool, melhoria sobre o SiS), tabela + totais + variante
  Cancelamento (`views/equipe_view.py`).
- `/pvt`: porta completa da página 22 (cards comissão/NMRR/Booking, pivots
  de metas/realizado com overrides, status de fechamento por equipe/mês).
- `/admin/{slug}`: as 16 páginas administrativas em MODO LEITURA
  (`views/admin_view.py`, registro `ADMIN_PAGES`), com filtro de período
  nas tabelas mensais e aviso fixo de que a edição continua no SiS até a
  Fase 5. A aba Recuperação de Dívidas aponta para a página homônima.

### Fase 3 + downloads entregues em 18/08/2026

- **Identidade** (`webapp/auth/identity.py`): AUTH_MODE=dev usa DEV_USER_EMAIL
  (default: primeiro ADMIN_EMAILS); AUTH_MODE=google ativa o OAuth
  (`webapp/auth/oauth.py`, Authlib) — valida email_verified + domínio
  Workspace de verdade. Pendências externas para ativar: OAuth Client no
  Google Cloud Console + GOOGLE_CLIENT_ID/SECRET + SECRET_KEY forte.
- **RLS deny-by-default** (`webapp/services/rls_service.py`): porta fiel de
  _consultores_rls_data (admin vê tudo incl. AMs; restrito vê seus
  CONSULTOREMAIL; SemAcesso bloqueado), is_gestor_in_rls, is_pvt,
  is_saving_gestor — tudo com binds.
- **Gating de abas** (`webapp/auth/authz.py` = _app.py:98-106): me para
  gestor/admin; pvt para IS_PVT/admin; rd+adm para admin/gestor Saving, que
  no admin só enxerga Patamares. Guards nas rotas E na navegação.
- **Visualizar como** (admin real): barra sob a navegação; e-mail validado
  (regex + existência nas bases) e guardado em cookie ASSINADO; o servidor
  reconfere que o usuário real é admin a cada request.
- **Minha Equipe modo gestor**: seletor de Equipe via RLS (o modo admin
  continua com o seletor de Líder).
- **Downloads xlsx** por endpoint real com RLS reaplicado:
  /download/{composicao,bk-extra,carteira-am,canc,renovacoes-canc,equipe}.xlsx
  e /download/admin/{slug}.xlsx (403 fora do perfil).

Matriz validada em 18/08/2026: admin (4 abas, view-as), gestora Saving via
view-as (me/rd/adm sem pvt; 10 consultores do RLS; admin só patamares;
/admin/parametros e /pvt redirecionam), consultora restrita (vê só ela),
downloads com xlsx válido e 403 cross-perfil.

### Fase 5 entregue em 18/08/2026 (edição admin — DESLIGADA por padrão)

- **Motor de escrita** (`webapp/services/admin_repo.py`): upsert (MERGE ou
  INSERT puro), excluir (DELETE por chave, com o mesmo transform LOWER/UPPER
  que o SiS usava na comparação) e copiar-mês, todos com binds e auditoria
  (UPDATED_BY/UPDATED_AT, CREATED_BY/CREATED_AT ou USUARIO/DATA_MARCACAO para
  Deals 400k). Termina sempre em `invalidate_after_write()`.
- **Specs de escrita** em `webapp/views/admin_view.py` (`AdminPage.chaves`,
  `.campos`, `.modo`, `.audit`, `.copia_mes`): as 10 páginas de padrão
  simples (Cargos e OTEs, Multiplicadores, Patamares, Recuperação de
  Dívidas, Deals ≥ 400k, Realizado GD, Ponderações, Controle de Acesso,
  Ajustes Pontuais, Exclusões Carteira AM) ganharam a spec completa.
  Parâmetros, Metas, Metas Override e Config (grades editáveis / vigência)
  ficam para uma iteração futura — continuam leitura por enquanto.
- **Duas trancas independentes** (`webapp/config.py`):
  `WRITES_ENABLED=1` liga a UI de edição (formulário some da tela sem isso —
  testado); `WRITES_TARGET=clone` redireciona TODA leitura e escrita das
  páginas admin para tabelas `MIGTESTE_*` (clones zero-copy criados no
  schema COMISSOES, já que a role não tem CREATE SCHEMA). Produção só edita
  de verdade com as duas flags explicitamente viradas.
- **Gate de teste**: `validacao/testar_escritas_clone.py` roda o ciclo
  add→verificar→copiar mês→remover→verificar nas 10 páginas contra os
  clones — **CICLO COMPLETO OK**. Repeti o mesmo ciclo por HTTP de verdade
  (POST /admin/{slug}/salvar,copiar,excluir) com WRITES_ENABLED=1 e
  WRITES_TARGET=clone: salvar → aparece na tabela → copiar mês → aparece no
  destino → excluir → some. Confirmado também que, com as flags no default
  (desligadas), a tela não mostra formulário e um POST direto na rota é
  redirecionado sem gravar nada — testado contra a tabela real
  (CARGOS_OTES), zero linhas escritas.
- Achado corrigido no caminho: `_listar` (leitura da tela) não seguia o
  mesmo roteamento de tabela que as escritas — em modo `clone` a tela
  continuava lendo a tabela real e nunca mostrava o que acabara de ser
  salvo no clone. Unificado via `admin_repo.tabela_escrita()` nos dois
  lados (em produção é identidade, não muda nada da Fase 4).

### Fase 6 entregue em 18/08/2026 (fechamento — DESLIGADO por padrão)

- **`webapp/jobs.py`**: registro em memória dos jobs (`JobState`) + lock por
  (ano, mes, equipe) contra fechar a mesma equipe/período duas vezes ao
  mesmo tempo.
- **`webapp/services/fechamento_service.py`**: `iniciar_fechamento` dispara
  uma thread que chama `utils.fechamento.fechar_consultores` +
  `fechar_um` (em PARALELO — melhoria sobre o loop sequencial de reruns do
  SiS; `fechar_um` só lê, então é seguro) + `fechar_inserir` uma vez no
  fim, exatamente como pages/20. `reabrir` chama `reabrir_fechamento`.
  **`utils/fechamento.py` não foi alterado.** Fechamento de PVT (comissão
  de equipe, só paga no fim do trimestre) replicado à parte, reaproveitando
  os loaders já testados de `pvt_view.py`.
- **`webapp/views/fechamento_view.py`**: lista de equipes do período, badge
  de status (aberto/fechado + versão) e os formulários de fechar/reabrir
  com confirmação via `confirm()` do navegador (o SiS usava um segundo
  clique; aqui é um diálogo nativo, mesma barreira contra clique acidental).
- Tela em `/admin/exportar-comissoes`: filtro Ano/Mês/Equipe, painel
  Fechar/Reabrir e, abaixo, o histórico de fechamentos (já existia da
  Fase 4). Progresso do fechamento via polling simples (fetch a cada 2s
  até `status != running`, mesmo padrão do resto do app — sem htmx).
- **Mesma tranca da Fase 5**: `WRITES_ENABLED` esconde os botões e os
  guards das rotas `/admin/exportar-comissoes/{fechar,reabrir}` recusam
  sem ela. Fechamento **não** usa `WRITES_TARGET=clone` (as tabelas
  FECHAMENTOS/COMISSOES_FECHADAS/COMPOSICAO_FECHADA são gravadas por
  `utils/fechamento.py`, que não redireciona tabela — é código do SiS
  intocado).

**Validação sem tocar a auditoria real de produção**
(`validacao/testar_fechamento_job.py`, com `fechar_inserir` mockado para
só capturar a chamada em vez de gravar): ciclo completo (fecha uma equipe
real, 3 pessoas, 33 linhas de composição, `job.status=done`), equipe
inexistente vira `job.status=error` tratado, lock bloqueia fechamento
concorrente da mesma equipe/período e libera depois, PVT roda a mesma
aritmética da tela `/pvt`. Por HTTP real: confirmado que com
`WRITES_ENABLED` no padrão (desligado) a tela não mostra os botões e um
POST direto na rota não grava nada em `FECHAMENTOS` (checado antes/depois
no Snowflake).

⚠️ **Pendência deliberada**: o critério do plano "refechar = diff zero
contra o snapshot do SiS" exige fechar uma equipe REAL de verdade (não
mockado) — isso grava uma linha permanente em `FECHAMENTOS` (histórico de
auditoria compartilhado com outros admins). Não fiz isso sozinho por ser
uma ação sobre estado compartilhado difícil de reverter de forma invisível
(dá para reabrir, mas o registro da versão de teste fica no histórico).
Passo a passo para quando quiser rodar: `WRITES_ENABLED=1 WRITES_TARGET=prod
python -m uvicorn webapp.main:app`, fechar uma equipe/período à escolha
pela UI, comparar o `DADOS`/`LINHA` do novo `FECHAMENTO_ID` contra o
snapshot ativo anterior (deve baterem se nada mudou nos dados-fonte desde
o último fechamento do SiS) e reabrir/deixar como preferir.

### Formatação das tabelas (18/08/2026)

Passada em todas as telas com tabela, focada nas 16 páginas admin (o maior
gap: mostravam nome cru de coluna e valor sem formatação de domínio).

- **Cabeçalho sempre em 1-2 linhas**: `html_table_str` agora quebra o texto
  do `<th>` normalmente (era `white-space:nowrap` fora do modo compacto,
  podendo estourar a largura) e trava em 2 linhas com `-webkit-line-clamp`
  — vale para toda tabela do app, não só admin.
- **Classificação por coluna** (`webapp/views/admin_view.py`, conferida
  contra o schema real via `INFORMATION_SCHEMA` em 18/08): booleano → "Sim"
  /"Não"; timestamp → `dd/mm/aaaa hh:mm:ss`; percentual (fração 0-1) →
  `pct_fmt`, igual ao que `comissao_view.py` já fazia — inclui
  `CLIFF_*`/`MULT_ACELERADOR_*`, que a Minha Comissão já exibe como % (ex.:
  "Acel de 115,00%"); dinheiro → `brl()`; numérico genérico → inteiro (sem
  casas) quando TODA a amostragem da coluna é inteira, senão float 2 casas;
  tudo com "." de milhar e "," decimal. A checagem do tipo numérico vem
  ANTES do nome (ex.: `VALOR` é dinheiro em `AJUSTES_PONTUAIS` mas é texto
  livre em `CONFIG` — o nome sozinho não distingue os dois; achado e
  corrigido durante a validação).
- **Cabeçalhos amigáveis**: reaproveita `Campo.label` das specs de escrita
  (Fase 5) e, para colunas estruturais sem spec (`UPDATED_AT`, `ANO`,
  `STATUS`...), um dicionário de tradução com fallback genérico (initcap por
  palavra) para o que sobrar.
- **Siglas de cargo**: `fmt_cargo`/`SIGLAS_RE` (regra de `_comissao.py`)
  virou fonte única em `webapp/presentation.py`. Achado e corrigido: a
  Minha Equipe montava a coluna "Cargo" direto do dict de `calcular_comissao`
  sem aplicar essa regra — agora aplica, igual à Minha Comissão.
- Validado com dados reais das 16 páginas (script ad-hoc, sem servidor) e
  depois ao vivo via HTTP: percentuais, dinheiro, datas, booleanos, cargo
  com sigla e o caso `CONFIG.VALOR` (texto) todos corretos.

Ainda fora (próximas fases): Parâmetros/Metas/Config com grade editável,
buscas nas tabelas e expanders lazy via htmx.

⚠️ **Bug encontrado e corrigido em 18/08/2026 (`webapp/presentation.py:
html_table_str`)**: o `-webkit-line-clamp:2` do cabeçalho tinha sido posto
direto no `<th>`, mas esse recurso exige `display:-webkit-box` no elemento
clampado, e isso sobrescreve o `display:table-cell` do `<th>`, quebrando a
tabela inteira (a linha de cabeçalho vira uma coluna empilhada). Como
`html_table_str` é a função compartilhada por toda tabela do app, o bug
valia para qualquer tela, não só o artifact. Ficou sem detecção até agora
porque a validação da "Formatação das tabelas" checou o HTML por texto
(regex nos `<th>`/`<td>`), nunca abriu um navegador de verdade; o Higor só
viu o problema ao olhar visualmente a tabela "Renovações de Contrato" no
artifact, primeira vez com o layout AM renderizado desde aquela mudança.
Corrigido movendo o clamp para um `<div>` interno ao `<th>` (o `<th>`
mantém o display nativo). Lição: revisão de tabela daqui pra frente
precisa incluir uma olhada visual real, não só checagem de texto.

### Fase 7, Artifact v1 (entregue 18/08/2026, CANCELADA em 19/08/2026)

Registro histórico, resumido: existiu um `artifact/build_artifact.py` que
gerava uma página HTML autocontida (reaproveitando
`webapp/views/comissao_view.py:montar_blocos()` sobre dados de snapshot
fechado) e a publicava como Claude Artifact para demonstração. Rodado com 8
perfis de demonstração fictícios e, depois, somando 2 Account Managers reais
via um parâmetro `--extra` pra testar o layout AM. O Higor decidiu não
seguir com essa estratégia (ver decisão no topo do documento); a pasta
inteira foi apagada em 19/08/2026. Detalhe técnico de como funcionava não
importa mais; o que sobrevive é o achado de bug abaixo, porque ele é sobre
código que ainda existe.

⚠️ **Bug achado testando o artifact (18/08), ainda relevante porque o
código corrigido está em `webapp/`, não no que foi apagado**:
`webapp/presentation.py:html_table_str` aplicava `-webkit-line-clamp:2`
direto no `<th>`; esse recurso exige `display:-webkit-box`, que sobrescreve
`display:table-cell` e quebra a tabela inteira (cabeçalho vira uma coluna
empilhada). Valia para qualquer tabela do app, não só o que foi apagado;
passou despercebido porque a validação anterior da formatação checou o
HTML por texto, nunca abriu navegador de verdade. Corrigido movendo o
clamp para um `<div>` interno ao `<th>`.

### Grades editáveis: Parâmetros, Metas e Config (18/08/2026)

Fechado o único gap de funcionalidade que restava no estágio localhost:
Parâmetros, Metas e Config eram somente leitura na tela genérica de admin
porque não se encaixam no modelo `AdminPage.chaves` (grade de linhas
dinâmicas com conversão percentual, ou vigência com dois modos de salvar).
Cada uma ganhou um renderizador próprio, chamado direto por
`montar_admin()` antes do caminho genérico.

- **`webapp/presentation.py:grid_editavel_html`**: equivalente sem
  Streamlit do `st.data_editor(num_rows="dynamic")` usado por Parâmetros e
  Metas: tabela com `<input>`/checkbox por célula, adicionar/remover linha
  no cliente e um único POST em JSON com tudo ao salvar (o servidor decide
  o que mudou e o que precisa ser removido).
- **`webapp/views/admin_view.py`**: `_parametros_grid_html` (porta de
  `pages/11_Admin_Parametros.py`, com diff contra o banco pra só salvar
  quem mudou e DELETE de quem saiu da grade); `_metas_grid_html` (porta de
  `pages/21_Admin_Metas.py`, dois modos: grade editável direto em
  `META_CONSULTOR` antes de `RI_DESDE=(2026,7)`, e composição somente
  leitura com aviso de pendência de cadastro depois); `_config_vigencias_html`
  (porta de `pages/24_Admin_Config.py`: valor vigente por chave via window
  function, "salvar na vigência atual" vs "nova vigência a partir de",
  criar chave nova, histórico completo).
- **`webapp/services/admin_repo.py`**: `parametros_salvar_grid`/
  `parametros_copiar_mes`, `metas_salvar_grid`/`metas_copiar_mes`,
  `config_salvar_atual`/`config_nova_vigencia`/`config_criar_chave`, todas
  com binds e terminando em `invalidate_after_write()`, mesmo padrão da
  Fase 5.
- Rotas novas em `webapp/main.py`: `POST /admin/parametros/salvar-grade`,
  `POST /admin/metas/salvar-grade` (bloqueada em período RI, defesa em
  profundidade além da UI já esconder a grade), `POST
  /admin/config/{salvar-atual,nova-vigencia,criar-chave}`; `/admin/{slug}/copiar`
  ganhou um branch pras 3 páginas antes de cair no `admin_repo.copiar_mes`
  genérico (que não serve pra elas, não usam `AdminPage.campos`).
- **Clones de teste que faltavam**: `WRITES_TARGET=clone` não cobria
  PARAMETROS/META_CONSULTOR/CONFIG (não estavam no dict `_CLONES`): se
  alguém tivesse testado escrita nessas 3 telas achando que ia pro clone,
  teria gravado direto em produção. Criados `MIGTESTE_PARAMETROS`,
  `MIGTESTE_META_CONSULTOR`, `MIGTESTE_CONFIG` (`webapp/ops/clones_teste.sql`)
  e mapeados no `_CLONES` antes de rodar qualquer teste de escrita real.
- **Bug achado e corrigido antes de ir pro ar**: as 3 telas tinham um
  `<script>` embutido no HTML devolvido por `/admin/{slug}/dados`, mas esse
  HTML é injetado via `element.innerHTML = ...` em `_loader.html`, e
  navegador NUNCA executa `<script>` inserido assim. Os botões "Adicionar
  linha"/"Salvar" ficariam mortos. Corrigido: o motor JS virou
  `webapp/static/js/admin_grade.js` (carregado normalmente por
  `admin.html`, um `<script src>` de verdade), com funções globais
  (`gridAdd`, `gridSalvar`, `cfgSalvar`) que leem os dados da grade via
  atributo `data-cols`/`data-chave` em vez de código gerado por linha.
- Validado por `validacao/testar_grades_clone.py` (novo gate, mesmo
  espírito de `testar_escritas_clone.py`): ciclo completo das 3 telas
  contra os clones num período fictício (ANO=2031): salvar, diff-skip
  (salvar sem mudança não regrava), remover linha da grade apaga no banco,
  copiar do mês anterior, e os dois modos de vigência do Config (corrigir
  vigência existente vs criar nova). 20/20 checagens OK. Também testado o
  ciclo real por HTTP (POST no endpoint de verdade com payload no formato
  que o JS do navegador manda).
- ⚠️ **Achado à parte, sem relação com o código**: o `uvicorn --reload`
  neste ambiente ficou preso depois do primeiro reload (arquivo mudou de
  novo, log disse "Reloading…" mas o processo antigo continuou no ar
  servindo código velho, confirmado comparando PID do processo com o
  `Started server process` do log). Não investigado a fundo; enquanto isso
  não for resolvido, depois de editar código do webapp reinicie o processo
  manualmente em vez de confiar no watcher.

Com isso as 16 páginas admin do SiS têm equivalente funcional no
localhost (13 somente leitura ou CRUD genérico da Fase 5, 3 com grade/
vigência própria). Escrita continua OFF por padrão (`WRITES_ENABLED`) e
sem cutover: o SiS segue sendo onde a edição de verdade acontece até a
Fase 8.

### Chip "Atualizado em" em Minha Comissão (19/08/2026)

Pedido do Higor, implementado nos dois lados (SiS e webapp), não é parte
de nenhuma fase do plano de migração, mas mora aqui porque toca a mesma
tela e teve que ser portado duas vezes como tudo mais neste documento.

- Fonte para quem não é GD/SDR: `MAX(ATUALIZACAO)` de
  `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`. `ATUALIZACAO`
  é TEXT em `DD/MM/YYYY HH24:MI:SS`, já em horário local (BR).
- Fonte para GD e SDR fora do time GD (realizado é Opps via
  `REALIZADO_GD`, não vendas): `MAX(_AIRBYTE_EXTRACTED_AT)` de
  `HUBSPOT.HUBSPOT_BRONZE.HUBSPOT_LEADS`, convertido para
  `America/Sao_Paulo` (esse aqui É TIMESTAMP_TZ de verdade, em UTC).
- Critério de qual fonte usar: replica `utils/commission.py:2073-2075`
  (equipe da pessoa é "GD" OU o cargo contém "sales development").
  Implementado via lookup direto de CARGO em `PARAMETROS`, sem depender do
  cálculo completo de comissão (que pode levar 1-2 minutos no primeiro
  acesso a um mês aberto); o chip aparece imediato, na mesma requisição
  que desenha os filtros.
- ⚠️ **Bug corrigido antes de publicar**: a primeira versão passava o
  horário de `ATUALIZACAO` por `CONVERT_TIMEZONE('America/Sao_Paulo', ...)`
  também, mas esse texto já vem em horário local; `CONVERT_TIMEZONE` de 2
  argumentos sobre um `TIMESTAMP_NTZ` assume que a origem está no fuso da
  SESSÃO (não em UTC), então deslocou o horário em +4h. Corrigido
  removendo a conversão dessa fonte (só a de `_AIRBYTE_EXTRACTED_AT`
  precisa dela, por ser genuinamente UTC).
- SiS: `utils/connection.py` (`_ultima_atualizacao_vendas`,
  `_ultima_atualizacao_captacao`, `_cargo_email`,
  `_ultima_atualizacao_dados`, `_chip_atualizacao_html`), chamado de dentro
  de `render_filters()`; um 5º `st.columns` alinhado à direita, larguras
  dos outros 4 reduzidas um pouco para caber. Webapp: mesmas 4 funções em
  `webapp/services/comissao_service.py`, chip renderizado em
  `comissao.html` via `margin-left:auto` no `<form class="filtros">`.
  Ambos com `try/except` silencioso: se a consulta falhar, o chip
  simplesmente não aparece, sem derrubar a tela.

### Desempenho: webapp nunca tinha o paralelismo do lote de contexto (19/08/2026)

Investigando a demora na primeira carga (pedido do Higor), achado real: o
`webapp/db/shim.py` antigo não suportava o modo assíncrono do Snowpark, e
`utils/commission.py:_lote_pandas` (as ~15 queries de `montar_contexto`,
disparadas com `session.sql(q).to_pandas(block=False)`) SEMPRE caía no
fallback sequencial dele por causa disso: o webapp nunca teve o ganho de
paralelismo que o SiS tem desde 14/08/2026 (comentário no próprio
`commission.py`), rodava sequencial 100% do tempo sem avisar nada.

- **Não dava pra corrigir em `commission.py`** (compartilhado, intocado por
  regra do projeto). Corrigido em `webapp/db/shim.py`: `sql()` agora
  dispara com `execute_async` (snowflake-connector) em vez de `execute`
  bloqueante; `to_pandas(block=False)` devolve um job com `.result()`,
  replicando a superfície do `AsyncJob` do Snowpark que `_lote_pandas`
  espera. `to_pandas()`/`collect()` sem `block=False` continuam
  bloqueantes na hora, idêntico a antes, para os outros ~50 lugares que
  encadeiam sem esperar nada.
- **Risco tratado**: com `sql()` sempre assíncrono, uma escrita
  "fire-and-forget" (padrão comum em `admin_repo.py`: `s.sql(query,
  params)` sem `.collect()` encadeado) ficaria pendente sem ninguém nunca
  confirmar se deu certo: erro silencioso, possível corrida. Corrigido com
  uma rede de segurança: toda `_ShimResult` fica registrada em
  `ShimSession._pendentes`; `webapp/db/pool.py` chama
  `confirmar_pendentes()` ao devolver a conexão ao pool (só quando o
  `with get_pool().session()` termina sem exceção), garantindo que toda
  query da sessão terminou (e qualquer erro estourou) antes da conexão
  voltar a ser usada.
- **Validado com dado real, não só sintético**: `_lote_pandas` com 8
  `SYSTEM$WAIT(1)` foi de ~10s (sequencial estimado) para 6,47s.
  `montar_contexto(2026, 8)` frio: 45,2s. `get_comissao` completo de uma AM
  em mês aberto (contexto + query própria de AM): 60,2s frio, 0,82s pra
  segunda pessoa (cache já quente). `python -m webapp.smoke` continua OK
  (0 queries novas na repetição, sem regressão de cache/paridade).
- **Isso melhora, mas não resolve tudo**: a primeira carga de um mês aberto
  continua na casa de dezenas de segundos, porque ainda são ~15-20
  consultas reais rodando contra o Snowflake, e paralelismo dentro de UMA
  conexão tem limite (overhead de submissão por query não desaparece,
  só o tempo de warehouse ocioso entre elas). Alavancas que ficam em
  aberto, cada uma com trade-off pra decidir com o Higor antes de mexer:
  - **Warehouse maior** (`DATAANALYST_WH`): mais slots de execução
    concorrente no Snowflake, ajudaria o lote a paralelizar de verdade em
    vez de só parte; custo de crédito maior.
  - **Manter o warehouse aquecido**: se ele suspende por ociosidade, a
    PRIMEIRA query do dia paga o resume (pode ser boa parte dos "quase 1
    minuto"); um ping periódico evitaria isso, mas mantém o warehouse
    rodando (custo) fora do horário de uso. Não implementado (decisão de
    custo, não técnica).
  - **Warehouse maior**: não implementado, mesma razão.

### Barra de progresso real em Minha Comissão (19/08/2026, escolhida pelo Higor)

Trocado o spinner indeterminado (que não dizia nada sobre quanto faltava)
por uma barra que reflete consultas de verdade ao Snowflake, sem inventar
número.

- **Contador real, não simulado**: `webapp/db/pool.py` ganhou
  `PROGRESSO_ATUAL` (`contextvars.ContextVar`, isolado por thread, então
  jobs concorrentes de usuários diferentes não se misturam);
  `SnowflakePool._conta_query` incrementa o job ativo (se houver) a cada
  consulta de verdade que roda, além do contador global que já existia.
- **`/comissao/iniciar`** dispara o cálculo numa thread (`JobState` de
  `webapp/jobs.py`, mesma estrutura da Fase 6) e devolve `job_id` na hora;
  **`/comissao/progresso/{job_id}`** é consultado pelo front a cada 400ms
  e devolve `{status, concluidos, total}` e, quando pronto, o HTML final
  (`/comissao/blocos` continua existindo como fallback síncrono, sem uso
  pela tela).
- **`total` é uma estimativa (20), não um número exato**: varia por layout
  (AM tem mais consultas de composição que o padrão). O front nunca deixa
  a barra passar de 90% enquanto `status != done`, e só fecha em 100%
  quando o job termina de verdade — testado com uma AM em mês aberto
  (23 consultas reais contra a estimativa de 20, a barra ficou em 90% até
  o fim, sem travar nem mentir 100% antes da hora).
- Validado ao vivo: job de uma AM em ago/2026 foi de `concluidos=17` (17s
  de espera) até `concluidos=23, status=done` (~85s depois, dentro do que
  já era esperado pra essa combinação); segunda pessoa com contexto já em
  cache: `status=done, concluidos=0` quase instantâneo, sem regressão no
  caminho rápido.

### Troca de consultor não paga mais o lote de contexto (19/08/2026)

Reclamação real do Higor: mesmo com um consultor já carregado no mês,
trocar de consultor reexecutava "tudo". Medido antes de mexer (harness com
contador de queries, mês 08/2026): troca com contexto quente disparava
**38 queries (~39s)**, mais que a primeira carga (23 queries). Voltar ao
mesmo consultor custava 0 (o cache em si sempre funcionou).

Causa: em `webapp/services/comissao_service.py`, dois desperdícios por
consultor novo:

1. **Contexto do histórico cacheado pelo CONJUNTO de meses**:
   `get_comissao_hist` separa os 6 meses do histórico em fechados (snapshot)
   e abertos (cálculo vivo), e o conjunto de meses abertos é próprio de cada
   consultor (depende de quais fechamentos ele entrou). `_get_contextos_cached`
   era chaveado por esse conjunto, então todo conjunto inédito refazia o
   lote INTEIRO do `montar_contextos` (~17-25 queries pesadas que cobrem
   TODOS os consultores). Corrigido: cache POR MÊS (chave `("ctx_mes", ano,
   mes)` no `LIVE`); os meses que faltam continuam vindo num único lote
   multi-mês e são semeados um a um, então o mês calculado para um
   consultor serve para todos os outros, e `get_contexto_cached` (usado
   pela tela e pela Minha Equipe) compartilha as mesmas entradas.
2. **Roteamento de snapshot um a um**: 7 consultas de `FECHAMENTO_ID`
   (mês atual + 6 do histórico) e 1 leitura de `DADOS` por mês fechado,
   todas pontuais e sequenciais. Corrigido: `_get_snapshot_fids` busca os
   fids dos pares que faltam numa única query (`(ANO, MES) IN (...)` +
   `QUALIFY ROW_NUMBER()`) e `_get_comissoes_snapshot` lê os `DADOS` de
   vários fids numa só (`FECHAMENTO_ID IN (...)`), ambos semeando os caches
   por item (`SNAP_FID`/`SNAPSHOT`), então as funções por item continuam
   existindo como fachada com o mesmo contrato.

Validação (19/08/2026, mesmo harness): troca de consultor caiu de 38
queries/~39s para **30 queries/~30s** quando o consultor novo ainda exige
meses de contexto inéditos (o lote roda uma vez por mês inédito, para
sempre dali em diante fica de graça); HTML gerado byte a byte IDÊNTICO ao
anterior nos três cenários (primeira carga, troca, repetição); repetição
segue com 0 queries; reuso por mês provado (subset do conjunto já montado
= 0 queries); `python -m webapp.smoke` OK. O que resta na troca é o custo
por e-mail de verdade (composições da tela + 2-3 lookups em lote), mais o
lote de contexto SÓ quando o consultor abre meses que ninguém tinha aberto.

## Próximas fases (do plano aprovado)

8. Docker + servidor + OAuth prod + cutover de escritas.

Pendências externas: admin Snowflake rodar `webapp/ops/service_account.sql`
(com a chave pública gerada pelo time) e criar o OAuth Client (Google Cloud
Console, redirect de localhost e do domínio futuro).

### Exportação para Google Drive/Sheets (implementada no webapp, 21/08/2026)

Avaliado substituir os botões de exportação (antes `.xlsx` via download
direto) por criação direta de planilha no Google Drive/Sheets do usuário.
Decisão original do Higor foi deixar só para a Fase 8 (servidor); revista no
mesmo dia ao perceber que, pelo caminho de OAuth por usuário, **nada disso
depende do servidor estar pronto** — só do SiS, que continua de fora (ver
racional abaixo). Implementado e testado no webapp local no mesmo dia.

- **Por que não no SiS**: Streamlit in Snowflake exigiria External Access
  Integration + Network Rule liberando saída para `googleapis.com` (aprovação
  de ACCOUNTADMIN) e a credencial num Snowflake SECRET; OAuth por usuário é
  inviável no modelo de rerun do Streamlit. Segue de fora, decisão mantida.
- **OAuth**: escopo `drive.file` (só os arquivos que o próprio app cria — não
  exige revisão de segurança do Google), Client criado no Google Cloud
  Console (projeto `painel-comissoes`, app "Interno" no Workspace, sem
  limite de usuários nem expiração de refresh_token de app em teste).
  `webapp/auth/drive_oauth.py`: rotas `/auth/drive/autorizar` e
  `/auth/drive/callback`, independentes do `AUTH_MODE` de login.
  `access_type=offline` só funciona passado direto pro `authorize_redirect()`
  — Authlib ignora silenciosamente esse parâmetro se vier via `client_kwargs`
  do `register()` (só aceita `response_mode`/`nonce`/`prompt`/`login_hint`
  dali); sem isso o Google nunca manda `refresh_token` e o app entra em loop
  pedindo consentimento de novo a cada exportação (achado testando com o
  Higor, 21/08/2026).
- **Fidelidade ao painel**: `webapp/views/export_view.py` embute hyperlink de
  verdade na célula (nome do negócio/cliente/contrato já É o link, via
  `openpyxl` `cell.hyperlink` + `xlsx_bytes(df, links=...)`), em vez de uma
  coluna separada com a URL crua — cobre as 5 tabelas de Minha Comissão que
  tinham negócio/cliente/contrato (Composição do Realizado, Booking Extra,
  Carteira AM, Cancelamentos, Renovações).
  Testado que o Drive preserva o hyperlink na conversão automática xlsx →
  Sheets.
- **Botão `.xlsx` removido, só no webapp**: `botao_download`/rotas
  `/download/*.xlsx` foram excluídos; todo exportação (Minha Comissão, Minha
  Equipe, as 16 páginas admin) agora sobe pro Drive via
  `/export/drive/...`, com `target='_blank'` (a navegação de verdade — OAuth
  + upload — precisa abrir numa aba separada, senão o painel sai da tela).
  SiS não foi tocado; continua só com o download `.xlsx` de sempre.

⚠️ **Pendência antes do servidor**: o token (`webapp/services/drive_service.py`)
fica em memória do processo (`_TOKENS`, dict por e-mail) — zera a cada
restart e não funciona com mais de um worker/réplica. Decisão para a Fase 8:
persistir numa tabela nova do Snowflake, com o `refresh_token` **criptografado**
(a lib `cryptography` já é dependência do webapp, sem novo custo) e grants
restritos só ao service account — mesmo cuidado que outras credenciais do
projeto já recebem, não fica exposto a leitura geral de admin.
