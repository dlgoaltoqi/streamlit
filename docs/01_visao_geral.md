# Visão Geral — Painel de Comissões

> Para o estado vigente do app, comece em `docs/00_estado_atual.md`. Este
> documento mantém a arquitetura detalhada e o histórico de decisões técnicas.

## Objetivo

Substituir a planilha Excel "Calculadora de Comissões 2026.xlsx" por um app Streamlit rodando no Snowflake.
Vendedores poderão consultar seus resultados de comissão diretamente pelo painel, sem depender do Excel Online.

## Arquitetura

```
Snowflake (dados)
    └── HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
            ↓
        Streamlit in Snowflake (app)
            ├── Leitura dos dados via Snowpark/SQL
            ├── Aplicação das regras de cálculo (Python)
            └── Exibição do painel para os vendedores
```

## Plataforma

- **Streamlit in Snowflake:** o app roda dentro do ambiente Snowflake, sem infraestrutura externa.
- **Linguagem:** Python (Streamlit + Snowpark).
- **Autenticação:** gerenciada pelo Snowflake (vendedor acessa com seu login Snowflake).

## Fluxo de Dados

1. Os dados de venda ficam na tabela `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM` no Snowflake
   (migrado de `SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM` em 03/08/2026 — ver `docs/19_migracao_vendas_ouro.md`).
2. O app lê esses dados via SQL/Snowpark.
3. Aplica as regras de cálculo das comissões (definidas nas abas da planilha).
4. Exibe o resultado filtrado pelo vendedor logado.

## Modelo de Cálculo Unificado

A estrutura de abas do Excel **não é espelhada** no app. Em vez de páginas separadas por equipe,
há uma única tela de comissões que determina automaticamente qual conjunto de regras aplicar
com base no usuário logado, na equipe e no mês selecionado.

### Mapeamento de Regras por Equipe e Período

| Equipe | Período | Modelo | Acel Form Pag |
|--------|---------|--------|:---:|
| Ares, B2B Construtora, B2B Escritório, Farmer, FSB, Sonia | Todo o período | OTE tiers + aceleradores | Sim |
| Saving | Jan–Mar 2026 | OTE tiers + aceleradores | Sim |
| Saving | Abr 2026+ | Patamares escalonados | Não |
| GD (SDRs/BDRs) | Todo o período | OTE tiers + aceleradores, realizado em Opps | Não |
| Governo — Consultores | Todo o período | Dois eixos ARR + Booking ponderados | Não |
| Governo — Gestores | Todo o período | Dois eixos Booking equipe + Meta Atingida | Não |
| Cancelamento | Abr 2026+ | Comissão direta sobre valor ajustado recuperado (sem OTE, sem meta) | Não |

> Este mapeamento é o ponto de entrada do motor de cálculo. Para cada linha de comissão,
> o app resolve `(equipe, mês)` → modelo → aplica as fórmulas correspondentes.

## Perfis de Acesso

O app tem três perfis. A autenticação é gerenciada pelo Snowflake — o e-mail do usuário
logado é a chave de identificação em todas as queries.

| Perfil | O que vê | Acesso admin |
|--------|----------|:---:|
| **Consultor** | Apenas a própria comissão | Não |
| **Gestor** | Própria comissão + toda a sua hierarquia de equipe | Não |
| **Admin** | Tudo | Sim |

### Visibilidade do Gestor — PERMISSAO_RLS

A visibilidade é determinada pela tabela `SUPERSET.PARCIAL.PERMISSAO_RLS`, que já existe
e é mantida pelo time de dados. Ela registra, por ANO/MES, quais consultores cada usuário
pode visualizar — cobrindo hierarquias simples, múltiplas equipes e gestores que gerenciam
outros gestores.

| Coluna | Descrição |
|--------|-----------|
| `ANO`, `MES` | Período |
| `USUARIOEMAIL` | E-mail do usuário logado |
| `CONSULTOREMAIL` | E-mail do consultor que ele pode ver |
| `TIPOUSUARIO` | `"Consultor"` ou `"Gestor"` |

**Implementação:**
```sql
-- Perfil do usuário logado no mês selecionado
SELECT DISTINCT TIPOUSUARIO
FROM SUPERSET.PARCIAL.PERMISSAO_RLS
WHERE USUARIOEMAIL = :usuario_logado AND ANO = :ano AND MES = :mes;

-- Lista de consultores que o usuário pode ver
SELECT CONSULTOREMAIL
FROM SUPERSET.PARCIAL.PERMISSAO_RLS
WHERE USUARIOEMAIL = :usuario_logado AND ANO = :ano AND MES = :mes;
```

Para o perfil **Admin**, o filtro por `USUARIOEMAIL` é ignorado — todas as queries retornam
sem restrição de e-mail.

### Páginas do App

| Página | Perfil | Descrição |
|--------|--------|-----------|
| **Minha Comissão** | Todos | Comissão do usuário logado, com filtro de mês |
| **Minha Equipe** | Gestor, Admin | Comissões de toda a equipe visível do gestor; inclui consultoras de Cancelamento para o gestor do Saving |
| **Administração** | Admin | Acesso às tabelas de configuração e fechamento |

### Páginas de Administração

Acessíveis apenas ao perfil **Admin**:

| Página | Função |
|--------|--------|
| Cargos e OTEs | Edita `CARGOS_OTES` |
| Parâmetros | Edita `PARAMETROS` |
| Acel Form Pag | Edita `ACEL_FORMA_PAGAMENTO` |
| Ponderações de Meta | Edita `PONDERACOES_META` |
| Patamares Saving | Edita `PATAMARES_COMISSAO` |
| Realizado GD (override) | Edita `REALIZADO_GD_OVERRIDE` |
| Recuperação de Dívidas | Edita `RECUPERACAO_DIVIDAS` |
| Deals Pago >400k | Edita `DEALS_PAGOS_400K` |
| Ajustes Pontuais | Edita `AJUSTES_PONTUAIS` — ajustes manuais pontuais por pessoa/mês |
| Acesso RLS | Edita `SUPERSET.PARCIAL.PERMISSAO_RLS` |
| Exportar Comissões | Gera relatório por equipe/mês e executa o fechamento (snapshot) |

## Tabelas em SUPERSET.COMISSOES

Todas criadas. Schema `SUPERSET.COMISSOES`.

### PONDERACOES_META

Armazena o peso de cada tipo de métrica por pessoa/mês. Usado pelo motor de cálculo para
determinar se a comissão é calculada com métrica única (sem registro) ou multi-métrica ponderada.

```sql
CREATE TABLE SUPERSET.COMISSOES.PONDERACOES_META (
    ANO        INT            NOT NULL,
    MES        INT            NOT NULL,
    EMAIL      VARCHAR(200)   NOT NULL,
    TIPO_META  VARCHAR(50)    NOT NULL,  -- 'ARR', 'Booking', 'MRR', 'Opps'
    PONDERACAO DECIMAL(5,4)   NOT NULL,  -- ex: 0.4000, 0.6000
    PRIMARY KEY (ANO, MES, EMAIL, TIPO_META)
);
```

**Regra do motor:** se existem entradas para (ANO, MES, EMAIL) → usa atingimento ponderado
(`SUM(% atingido por tipo × ponderação)`). Se não há entradas → usa a métrica principal do grupo
(MRR para a maioria; Opps para GD).

**Exemplo — B2G jan/2026:**

| ANO | MES | EMAIL | TIPO_META | PONDERACAO |
|-----|-----|-------|-----------|-----------|
| 2026 | 1 | fulano@altoqi.com.br | ARR | 0.4 |
| 2026 | 1 | fulano@altoqi.com.br | Booking | 0.6 |

Outras equipes que adotarem modelo bi-métrico no futuro apenas recebem entradas nessa tabela —
sem mudança de código.

### PARAMETROS

Parâmetros de comissão por pessoa/mês: CARGO, cliffs, OTE tiers, aceleradores e booking extra.
Ver detalhes em `docs/06_aba_parametros.md`.

### Demais tabelas

Estruturas detalhadas nos docs de cada aba:
- `CARGOS_OTES` → `docs/04_aba_cargos_otes.md`
- `ACEL_FORMA_PAGAMENTO` → `docs/07_aba_acel_form_pag.md`
- `PATAMARES_COMISSAO` → `docs/08_aba_patamares_saving.md`
- `REALIZADO_GD_OVERRIDE` → `docs/03_aba_realizado_gd.md`
- `RECUPERACAO_DIVIDAS` → `docs/09_aba_recuperacao_canc_divs.md`
- `DEALS_PAGOS_400K` → `docs/02_aba_negocios.md`

## Decisões Técnicas

- Todo cálculo que hoje está em fórmulas Excel deve ser reimplementado em Python no Streamlit.
- A estrutura de abas da planilha serve como referência de regras de negócio, não como modelo de navegação do app.
- Parâmetros configuráveis (metas, patamares, OTEs) serão lidos de tabelas Snowflake gerenciadas pelo administrador.
- A planilha `Calculadora de Comissões 2026.xlsx` serve apenas como referência de regras — não é fonte de dados do app.

### Bônus Trimestral

O app exibe o bônus trimestral como fator sobre o salário, no formato **"X% de um Salário"**.
Exemplos: consultor com 110% de atingimento trimestral → `"33% de um Salário"` (110% × 0,3);
gestor B2G com 110% → `"99% de um Salário"` (110% × 0,9). O salário base não é necessário.

### Estratégia de Performance

Abordagem inicial: dados buscados do Snowflake via SQL e cálculos aplicados em Python/Pandas.
Cache (`@st.cache_data`) nas queries mais pesadas para evitar re-consultas a cada interação.
Migração para Snowpark apenas se houver lentidão comprovada após o primeiro deploy — não otimizar antes de ter o problema.

## Sistema de Fechamento (Snapshot)

Disponível a partir de abril/2026. Congela, por (equipe, mês), o resultado calculado de cada
pessoa em tabelas imutáveis. Após o fechamento, qualquer consulta àquele período retorna os
valores congelados — nunca recalcula ao vivo.

### Tabelas

| Tabela | Função |
|--------|--------|
| `FECHAMENTOS` | Cabeçalho por (equipe, mês, versão). Status: `ATIVO` ou `SUBSTITUIDO`. |
| `COMISSOES_FECHADAS` | Resultado por pessoa como VARIANT (dict completo de `calcular_comissao()`). |
| `COMPOSICAO_FECHADA` | Deals/linhas que compõem o realizado. Tipos: `REALIZADO`, `GD`, `BOOKING_EXTRA`, `CANCELAMENTO`, `AJUSTE`. |

### Fluxo

1. Admin acessa **Exportar Comissões**, seleciona equipe/mês e clica **Fechar comissão**.
2. O sistema calcula ao vivo todos os consultores da equipe e grava nas três tabelas.
3. Refechar incrementa a versão (`v2`, `v3`...) e marca a anterior como `SUBSTITUIDO`.
4. A partir daí, `get_comissao(email, ano, mes)` em `utils/connection.py` detecta o snapshot
   e retorna os dados congelados em vez de recalcular.

### Equipes e fonte dos consultores

| Equipe | Fonte da lista de consultores |
|--------|-------------------------------|
| Todas (exceto abaixo) | `METAS_CONSULTORES_CONSOLIDADAS` |
| Farmer | `METAS_CONSULTORES_CONSOLIDADAS` com `EQUIPE IN ('Farmer', 'Sonia')` |
| Cancelamento | `PARAMETROS` com `IS_CANC_RECOVERY = TRUE` |

### Badge de período fechado

Quando um período está fechado, as páginas **Minha Comissão** e **Minha Equipe** exibem
um banner âmbar: _"🔒 Período fechado em DD/MM/AAAA. Se houver algum negócio não contabilizado
ou com valor desatualizado, solicite o recálculo para Higor."_
