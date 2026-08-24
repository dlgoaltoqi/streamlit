# Configurações do cálculo (SUPERSET.COMISSOES.CONFIG)

Regras de negócio administráveis sem deploy, com **vigência**: cada linha é
`(CHAVE, ANO, MES, VALOR)` e vale **a partir** de (ANO, MES). O cálculo do mês M
usa a vigência mais recente ≤ M — alterar uma regra para frente nunca reescreve
meses passados, e meses fechados (snapshot) são imunes a qualquer edição.

- **Tela:** Administração → 🔧 Configurações (somente admin).
- **Leitura no código:** `carregar_config` em `utils/commission.py`; o
  `montar_contextos` injeta `ctx["config"]` (uma leitura da tabela por contexto,
  cacheada). Composições e fechamento usam `_config_mes` sob demanda.
- **Fallback:** chave ausente ou tabela ilegível ⇒ o código usa o valor padrão
  embutido (comportamento idêntico ao anterior à criação da tabela). Exceção:
  chaves por pessoa (`gestor_equipes.*`, rótulos) — com a tabela legível, a
  ausência da chave significa "sem override" (removê-la desliga o override).
- **Auditoria:** UPDATED_BY / UPDATED_AT por linha; histórico completo visível
  na própria tela.

## Chaves

| Chave | Padrão | Controla |
|---|---|---|
| `fator_trim_consultor` | 0.3 | Fator do bônus trimestral individual dos consultores |
| `fator_trim_gestor` | 0.6 | Fator do bônus trimestral dos gestores (exceto B2G) |
| `fator_trim_gestor_b2g` | 0.9 | Fator do bônus trimestral do gestor B2G |
| `fator_trim_equipe` | 0.3 | Fator do bônus trimestral de equipe dos consultores |
| `meta_atingida_gestor_b2g` | 0.8 | Meta de % da equipe B2G atingindo quota |
| `meta_arr_pct_booking` | 0.5 | Meta ARR = percentual × meta Booking (B2G) |
| `corte_deal_grande` | 400000 | Booking a partir do qual o deal é excluído por padrão |
| `pct_canc_recovery_default` | 0.02 | % padrão canc-recovery quando vazio nos Parâmetros |
| `pct_dividas_default` | 0.025 | % padrão sobre dívidas quando vazio no cadastro |
| `categorias_booking_extra` | Implantação,Serviço,Curso | Categorias que contam como Booking Extra |
| `cargo_sdr_contem` | sales development | Trecho de cargo que identifica SDR (modelo GD) |
| `gestor_equipes.<email>` | — | Equipes agregadas por um gestor multi-equipe |
| `gestor_b2g_rotulo_aproveitamento` | — | E-mails de gestores B2G com rótulo "Aproveitamento da Equipe" |
| `equipes_fechamento.<equipe>` | a própria | Equipes do METAS varridas ao fechar/exportar (ex.: Farmer inclui Sonia) |

## O que ficou fora (de propósito)

- `ADMIN_EMAILS` (connection.py) — proteção anti-lockout, muda só por deploy.
- Piso estrutural do painel (abr/2026) e detecção de equipe por nome (gd/governo/saving).
- `REALIZADO_COLUNAS` (Farmer = NMRR+MRR_EXPANSAO) — entranhado nos geradores de
  SQL da composição; mover exigiria refatoração própria.
- Estrutura do modelo PVT (equipes NMRR nas páginas 22/23).
