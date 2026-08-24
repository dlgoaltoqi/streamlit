# Migração da Fonte de Vendas — HUBSPOT_OURO (03/08/2026)

## O que mudou

A fonte de dados de vendas realizadas do painel migrou de:

- **Antes:** `SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM`
- **Agora:** `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`

Migração puramente mecânica: **mesmo contrato de colunas** (mesmos nomes —
`CONSULTOR`, `EQUIPE`, `VERTICAL`, `MRR`, `NMRR`, `MRR_EXPANSAO`,
`FECHAMENTO_NEGOCIO`, `BOOKING`, `ARR` etc.), então nenhuma lógica de cálculo
mudou — só a `FROM`/`JOIN` das queries.

## Por que migrar

Validação em 30/07–03/08/2026 (ver [[project-migracao-vendas-ouro]]) mostrou
que `SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM` estava **desatualizada e
incompleta**:
- Histórico jan–nov/2025 sistematicamente incompleto (centenas de linhas a
  menos por mês que a `HUBSPOT_OURO`).
- Meses correntes (jul/ago 2026) com dezenas de itens faltando — consequência
  do incidente de 29/07/2026 (a tabela zerou e foi recarregada a partir de um
  snapshot que não capturou o histórico nem as atualizações mais recentes).
- `HUBSPOT_OURO` é a camada "ouro" mantida ativamente pelo pipeline de dados
  (dbt), com colunas de controle (`HASH_PK`, `DT_REGISTER`, `UPDATE_REGISTER`)
  e granularidade idêntica, incluindo a mesma lógica de **consultor
  secundário** (item de linha duplicado, um registro por consultor, cada um
  com o valor cheio — confirmado idêntico nas duas tabelas antes da migração).

## Arquivos alterados

- `utils/commission.py` (14 ocorrências)
- `pages/20_Admin_Exportar_Comissoes.py` (6)
- `pages/22_Comissao_PVT.py` (6)
- `pages/23_Admin_PVT_Overrides.py` (6)

Troca mecânica de `SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM` →
`HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM` em todo `FROM`/`JOIN`.
Nenhuma outra linha de código mudou.

**Não alterados intencionalmente:**
- `validacao/commission_legacy.py` — cópia congelada do código pré-refatoração,
  usada como baseline de comparação; não deve refletir a fonte nova.
- `output/bundle/**` — regenerado pelo `deploy.ps1` a cada deploy.

## Permissões

**Nenhum GRANT foi necessário.** O app Streamlit roda com os privilégios do
seu **dono** (`GENERAL_ANALYST`, confirmado via `SHOW GRANTS ON STREAMLIT`),
não do role de quem abre o app (`ROLE_METAS_EDITORS`, que só tem `USAGE`).
`GENERAL_ANALYST` já tinha `SELECT` em `HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM`
antes da migração (grant concedido em 31/07/2026 pelo `DATA_ENGINEER`, junto com
`DATA_ANALYST`, `HUBSPOT_ANALYST`, `HUBSPOT_BASIC`, `MARKETING_ANALYST`, `SALESOPS`).

## Diferenças estruturais conhecidas (não afetam o painel)

| Coluna | `SUPERSET.PARCIAL` (antiga) | `HUBSPOT_OURO` (nova) |
|---|---|---|
| `BOOKING`/`ARR`/`MRR`/... | `FLOAT` | `NUMBER(18,2)` |
| `PARCELAS` | `VARCHAR` | `NUMBER(38,2)` |
| `DURACAO` | `NUMBER(8,0)` | `NUMBER(38,2)` |
| Colunas extras | — | `MRR_REATIVACAO`, `HASH_PK`, `HASHMAP`, `DT_REGISTER`, `UPDATE_REGISTER` |

`PARCELAS` só é usada em `calc_acel_form_pag()` via `int(parcelas)` — funciona
igual com `VARCHAR` numérico ou `NUMBER`. Nenhum outro ponto do código depende
do tipo exato dessas colunas.

## Validação pós-migração (03/08/2026)

Rodado `validacao/validar_hist.py` (legado vs. novo, mar–jul/2026 + lotes
multi-mês) após a troca de fonte. Dois padrões distintos, nenhum inesperado:

**mar/2026: 36/36 idênticos.** Nenhum negócio de março tocado pelo gap de
dados (fora da janela problemática).

**abr–jun/2026: ruído de arredondamento de 1-2 centavos** em ~20-25 pessoas
por mês (`mrr_avista`/`mrr_cc12x`/`mrr_recorrente` e, por propagação,
`ote_variavel`/`total`/`realizado`). Causa: `SUPERSET.PARCIAL` armazenava
`BOOKING`/`ARR`/`MRR`... como `FLOAT`; `HUBSPOT_OURO` usa `NUMBER(18,2)`
exato. Sem impacto prático — são meses fechados por snapshot (protegidos) e a
diferença é sub-centavo por pessoa.

**jul/2026 (mês corrente, ao vivo): diferenças reais e materiais**, todas
explicadas pelo gap de dados já documentado (SUPERSET.PARCIAL faltava ~24
itens de julho — ver validação de igualdade anterior):
- Maioria das pessoas: `realizado` SOBE (receita que estava faltando entra).
  Ex.: beatriz +7.376, rubia.estipe +1.518, cintia +908, maicon.fentzke +290.
- Duas pessoas cruzam patamar/acelerador por causa disso: **francisco.junior**
  (acelerador 1,2→1,3, "Acelerador 1"→"Acelerador 2") e **jaqueline.correa**
  (patamar 95%→110%, atinge o teto — `proxima_faixa` vira `None`).
- **leandro.fontana: `realizado` CAI** (bk_real 482.823→152.955, acelerador
  1,25→**0,0**, cai abaixo do cliff de Booking). Causa identificada: o negócio
  `57979921926` (SEJUS/MT — LVIT+SSA05) tem booking total de **R$ 679.700**
  (8 itens) na `HUBSPOT_OURO` — acima do corte de R$ 400k
  (`corte_deal_grande`) e **não está** em `SUPERSET.COMISSOES.DEALS_PAGOS_400K`.
  Com os dados incompletos da fonte antiga (faltavam 4 dos 8 itens), o total
  aparente do negócio ficava abaixo de R$ 400k e ele contava normalmente na
  comissão individual — **violação da regra de corte mascarada pelo gap de
  dados**. Com a fonte completa, a regra passa a ser aplicada corretamente.
  ✅ **Confirmado pelo Higor em 03/08/2026: a exclusão está correta.** O
  negócio SEJUS/MT NÃO deve ser adicionado a `DEALS_PAGOS_400K`; a queda de
  realizado/comissão do leandro.fontana em julho é o valor certo.
- Outros movimentos relevantes em B2G (carla.araujo, fernanda.barbosa, soraia,
  tabata.couto): `arr_real`/`bk_real` sobem — mesma causa-raiz (itens que
  faltavam na fonte antiga).

**Lotes multi-mês**: 223/223 e 241/241 idênticos (a consistência do contexto
em lote não foi afetada pela troca de fonte).

**Veredito**: migração correta. Abr–jun sem impacto prático (snapshot +
centavos). Julho reflete dados mais completos — é o comportamento esperado e
desejado, incluindo a correção do caso leandro.fontana/SEJUS-MT, confirmada
pelo Higor como o comportamento correto. Nenhuma pendência de negócio em aberto.

## Rollback

Reverter as 4 edições (`git diff`/backup) ou simplesmente trocar de volta
`HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM` →
`SUPERSET.PARCIAL.VENDAS_REALIZADAS_POR_ITEM` nos mesmos 4 arquivos.
