# Validação da refatoração busca/cálculo em lote — 24/07/2026

Refatoração: `calcular_comissao` deixou de fazer queries por pessoa e passou a ler
de um contexto em lote (`montar_contexto`, ~15 queries por mês, cacheado por
(ano, mês) em `connection.get_contexto_cached`).

## Método

- Baseline de junho/2026 capturado ANTES da refatoração (1 consultor + 1 gestor
  por equipe, 15 referências) → `baseline_2026_06.json`.
- Código legado preservado e executado lado a lado com o novo, na mesma conexão,
  para TODAS as pessoas (METAS ∪ PARAMETROS) de mai, jun e jul/2026.
- Comparação campo a campo do dict completo (tolerância: 0,5 centavo).

## Resultado

| Mês     | Pessoas | Idênticos | Queries legado → novo |
|---------|---------|-----------|------------------------|
| 05/2026 | 53      | 53/53     | 361 → 15               |
| 06/2026 | 58      | 57/58     | 583 → 46               |
| 07/2026 | 54      | 54/54     | 205 → 15               |

Baseline: 14/15 idênticos.

## Única divergência (esperada e documentada)

`marcelo.maestro@altoqi.com.br` (gestor Governo), junho/2026, bloco `b2g_ajuste`:

| Campo | Legado | Novo |
|---|---|---|
| ma_q | 0,0 | 0,30 |
| pct_ma_q | 0,0 | 0,375 |
| pct_ponderado_q | 0,6155 | 0,6905 |
| ote_variavel_q | 25.639,08 | 28.763,48 |

Causa: a query legada da "Meta Atingida trimestral" fazia
`SUM(v.BOOKING) / NULLIF(SUM(m.META_OTR), 0)` com JOIN em nível de item —
o `SUM(m.META_OTR)` multiplicava a meta pelo nº de itens vendidos, zerando o
percentual de todos. A versão nova calcula por membro: Σ Booking ÷ Σ META_OTR
dos meses com meta (mesma família do bug corrigido no item 1).

**Impacto financeiro: nenhum.** `b2g_ajuste.ajuste` e `total` não divergiram —
o trimestral recalculado segue abaixo do pago mensal no Q2/2026.

## Rodada 2 — contexto multi-mês (histórico sob demanda), 24/07/2026

Generalização de montar_contexto → montar_contextos (vários meses numa passada,
usado pelo histórico da Minha Comissão). Revalidação completa (validar_hist.py):

- Legado vs novo, mar-jul/2026 (36+52+53+58+54 pessoas): 100% idênticos
  (única exceção: diff documentado do gestor B2G em junho, acima).
- Lote multi-mês vs mês único, janelas [3-6] e [4-7]: 199/199 e 217/217 idênticos.

## Rodada 3 — regras administráveis (SUPERSET.COMISSOES.CONFIG), 27/07/2026

Regras de negócio movidas para a tabela CONFIG (vigência por chave; tela
Administração > Configurações). Validação com a config semeada nos valores atuais:

- 1ª execução REPROVOU: o seed via `snow sql -f` corrompeu acentos
  ('ImplantaÃ§Ã£o...') e zerou o Booking Extra de 8 pessoas em mai/jun.
  Re-semeado via connector Python com binds; NUNCA semear texto acentuado
  com snow sql -f.
- 2ª execução: mar-jul/2026 (36+52+53+58+54) 100% idênticos ao legado
  (exceções documentadas: ma_q do gestor B2G e o campo novo
  rotulo_aproveitamento); lote [3-6] 199/199 e [4-7] 217/217 idênticos.

## Rodada 4 — divisão por modelo (item 18), 27/07/2026

calcular_comissao (~630 linhas, 4 modelos entrelaçados) refatorado em despachante
fino + _base_comissao + _calcular_gd/_calcular_b2g/_calcular_saving/_calcular_mrr
+ _montar_resultado + helpers compartilhados. Validação: mar-jul/2026
(36+52+53+58+54) 100% idênticos ao legado (exceções documentadas); lote [3-6]
199/199 e [4-7] 217/217 idênticos.

## Rodada 5 — rampagem de migração de equipe, 27/07/2026

Novos campos PARAMETROS.PCT_RAMPAGEM (fator meta+OTE do mês) e
PCT_PROTECAO_RAMPAGEM (proteção somada = pct × média do OTE Variável dos
últimos 6 meses; HISTORICO_COMISSOES manual > painel; média dos meses com dado).
Validação com campos nulos: mar-jul (36+60+61+66+54, já incluindo os demos)
100% idênticos ao legado; lotes 223/223 e 241/241. Teste funcional em demo.fsb
jun/2026: meta 50% ✓, OTE 50% ✓, proteção 0,8×média(2 meses) ✓, reversão ✓.
