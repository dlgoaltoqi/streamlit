-- ═══════════════════════════════════════════════════════════════════════════
-- METAS_CONSULTORES_CONSOLIDADAS — v4 (12/08/2026)
-- Metas RI a partir de jul/2026 (consultant_goals + gd_owner_targets) COM
-- fallback do formulário para quem não tem linha RI no mês (decisão do Higor
-- em 30/07: goals de gestores vão demorar na RI; o fallback é temporário e
-- se auto-resolve — a RI vence sempre que tiver a linha).
-- v4 acrescenta o override administrativo do painel, acima do RI.
-- Ver docs/18_migracao_metas_ri.md.
--
-- COMO EXECUTAR:
--   • Dono atual da view: GENERAL_ANALYST. Rodar pelo Snowsight OU via
--     `validacao/aplicar_view_metas_override.py` (connector, UTF-8 seguro).
--   • NÃO usar `snow sql -f` (corrompe acentos de 'Escritórios'/'Deméter').
--   • COPY GRANTS preserva os SELECTs (DATA_ANALYST, DATA_ENGINEER,
--     GENERAL_ANALYST).
--   • Rollback: docs/18_rollback_metas_view.sql (definição pré-migração).
--
-- Regras:
--   ≤ jun/2026: form (META_CONSULTOR), intacto.
--   ≥ jul/2026: override primeiro, depois RI, depois form —
--     (a) override: SUPERSET.COMISSOES.METAS_OVERRIDE (ATIVO = TRUE). Vale só
--         para ≥ jul/2026, onde a tela Admin → Metas é somente leitura porque
--         a origem é a RI. Chave de precedência: (ANO, MES, e-mail) — quem tem
--         override ativo no mês não entra pelo RI nem pelo form.
--     (b) consultores dos 6 pipelines: CONSULTANT_GOALS
--         (TARGET_VALUE = bruta; REDUCTION_PCT 0-100; líquida = bruta×(1−pct/100))
--     (c) GD/SDRs: GD_OWNER_TARGETS (TARGET_QUALIFIED = Opps → META_OTR)
--     (d) fallback: form (META_CONSULTOR) para quem não tem linha RI no mês
--         (hoje: gestores, Sonia, Beatriz e o GD de julho ainda não carregado)
-- ═══════════════════════════════════════════════════════════════════════════

create or replace view SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
copy grants
as
with form as (
    -- Comportamento histórico (≤ jun/2026), inalterado
    select
        ano,
        mes,
        email                as consultor,
        equipe,
        mc.senioridade       as senioridade,
        'Form'               as fonte,
        percentual_desconto_metas,
        meta_nmrr_bruto + meta_expansao_bruto + meta_renovacao_bruto as meta_mrr_bruto,
        meta_nmrr + meta_expansao + meta_renovacao                   as meta_mrr,
        meta_nmrr_bruto,
        meta_nmrr,
        meta_expansao_bruto,
        meta_expansao,
        meta_renovacao_bruto,
        meta_renovacao,
        0 as meta_reativacao,
        0 as meta_devedor,
        meta_otr_bruto,
        meta_otr
    from superset.parcial.meta_consultor mc
    where date_from_parts(ano, mes, 1) >= '2025-10-01'
      and (meta_nmrr > 0 or meta_expansao > 0 or meta_renovacao > 0 or meta_otr > 0)
),

override_raw as (
    -- Correção administrativa do painel: vence RI e form em (ano, mês, e-mail).
    -- Mesma semântica da RI: META_BRUTA + PERCENTUAL_DESCONTO_METAS em 0-100.
    select
        ano,
        mes,
        lower(email)                                 as consultor,
        equipe,
        coalesce(percentual_desconto_metas, 0)       as desconto_pct,
        meta_bruta,
        round(meta_bruta
              * (1 - coalesce(percentual_desconto_metas, 0) / 100), 2) as meta_liquida
    from superset.comissoes.metas_override
    where coalesce(ativo, true)
      and email is not null
      and meta_bruta is not null
      and date_from_parts(ano, mes, 1) >= '2026-07-01'   -- só onde a origem é a RI
),

override_contrato as (
    select
        ano,
        mes,
        consultor,
        equipe,
        cast(null as varchar)  as senioridade,
        'Override'             as fonte,
        desconto_pct           as percentual_desconto_metas,
        -- Governo e GD medem em OTR (Booking / Opps); demais equipes em MRR
        iff(equipe in ('Governo', 'GD'), 0, meta_bruta)    as meta_mrr_bruto,
        iff(equipe in ('Governo', 'GD'), 0, meta_liquida)  as meta_mrr,
        -- NMRR espelha o MRR nas equipes de venda nova (padrão do form)
        iff(equipe in ('Saving', 'Governo', 'GD', 'AM GDC', 'AM Escritório'), 0, meta_bruta)   as meta_nmrr_bruto,
        iff(equipe in ('Saving', 'Governo', 'GD', 'AM GDC', 'AM Escritório'), 0, meta_liquida) as meta_nmrr,
        0 as meta_expansao_bruto,
        0 as meta_expansao,
        0 as meta_renovacao_bruto,
        0 as meta_renovacao,
        0 as meta_reativacao,
        0 as meta_devedor,
        iff(equipe in ('Governo', 'GD'), meta_bruta, 0)    as meta_otr_bruto,
        iff(equipe in ('Governo', 'GD'), meta_liquida, 0)  as meta_otr
    from override_raw
),

override_chave as (
    select distinct ano, mes, consultor from override_contrato
),

ri as (
    select
        ricg.year                                   as ano,
        ricg.month                                  as mes,
        lower(rio.email)                            as consultor,
        case rip.name
            when 'CS - Saving'                   then 'Saving'
            when 'Comercial B2B - Construtoras'  then 'B2B Construtora'
            when 'Comercial B2B - Escritórios'   then 'B2B Escritório'
            when 'Comercial B2G'                 then 'Governo'
            when 'Comercial FSB'                 then 'FSB'
            when 'Farmer - Deméter'              then 'Farmer'
            when 'B2B GDC - Account Manager'       then 'AM GDC'
            when 'B2B Escritórios - Account Manager' then 'AM Escritório'
        end                                         as equipe,
        coalesce(ricg.reduction_pct, 0)             as desconto_pct,   -- escala 0-100
        ricg.target_value                           as meta_bruta,
        round(ricg.target_value
              * (1 - coalesce(ricg.reduction_pct, 0) / 100), 2)        as meta_liquida
    from revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_consultant_goals ricg
    join revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_consultants ric
      on ric.id = ricg.consultant_id
    left join revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_owners rio
      on rio.id = ric.hubspot_owner_id
    left join revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_pipelines rip
      on rip.id = ricg.pipeline_id
    where date_from_parts(ricg.year, ricg.month, 1) >= '2026-07-01'     -- corte da migração
      and ricg.target_value is not null
),

ri_contrato as (
    select
        ano,
        mes,
        consultor,
        equipe,
        cast(null as varchar)  as senioridade,   -- só exibição (pág. Admin Metas)
        'RI'                   as fonte,
        desconto_pct           as percentual_desconto_metas,
        -- Governo: meta é Booking → META_OTR; demais equipes → META_MRR
        iff(equipe = 'Governo', 0, meta_bruta)    as meta_mrr_bruto,
        iff(equipe = 'Governo', 0, meta_liquida)  as meta_mrr,
        -- NMRR espelha o MRR nas equipes de venda nova (padrão do form);
        -- Saving, Governo e Account Managers (AM GDC / AM Escritório) = 0
        iff(equipe in ('Saving', 'Governo', 'AM GDC', 'AM Escritório'), 0, meta_bruta)   as meta_nmrr_bruto,
        iff(equipe in ('Saving', 'Governo', 'AM GDC', 'AM Escritório'), 0, meta_liquida) as meta_nmrr,
        0 as meta_expansao_bruto,
        0 as meta_expansao,
        0 as meta_renovacao_bruto,
        0 as meta_renovacao,
        0 as meta_reativacao,
        0 as meta_devedor,
        iff(equipe = 'Governo', meta_bruta, 0)    as meta_otr_bruto,
        iff(equipe = 'Governo', meta_liquida, 0)  as meta_otr
    from ri
    where equipe is not null      -- pipeline sem de-para não entra
      and consultor is not null   -- consultor sem e-mail (owner ausente) não entra
),

gd_contrato as (
    -- GD/SDRs: metas em Opps qualificadas, por owner
    select
        gdt.year                as ano,
        gdt.month               as mes,
        lower(rio.email)        as consultor,
        gdt.team                as equipe,          -- hoje sempre 'GD'
        cast(null as varchar)   as senioridade,
        'RI'                    as fonte,
        0                       as percentual_desconto_metas,
        0 as meta_mrr_bruto, 0 as meta_mrr,
        0 as meta_nmrr_bruto, 0 as meta_nmrr,
        0 as meta_expansao_bruto, 0 as meta_expansao,
        0 as meta_renovacao_bruto, 0 as meta_renovacao,
        0 as meta_reativacao, 0 as meta_devedor,
        gdt.target_qualified    as meta_otr_bruto,
        gdt.target_qualified    as meta_otr
    from revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_gd_owner_targets gdt
    left join revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_owners rio
      on rio.id = gdt.owner_id
    where date_from_parts(gdt.year, gdt.month, 1) >= '2026-07-01'       -- corte da migração
      and gdt.target_qualified > 0                                      -- espelha o filtro do form
      and rio.email is not null
      -- form prevalece: se a pessoa tem entrada no form com equipe != 'GD'
      -- (ex.: foi movida para B2B Escritório), o form substitui o target de GD
      and not exists (
          select 1 from superset.parcial.meta_consultor mc2
          where mc2.ano = gdt.year and mc2.mes = gdt.month
            and lower(mc2.equipe) != 'gd'
            and lower(mc2.email) = lower(rio.email)
            and (mc2.meta_nmrr > 0 or mc2.meta_expansao > 0
                 or mc2.meta_renovacao > 0 or mc2.meta_otr > 0)
      )
)

-- ── Até jun/2026: form, exatamente como hoje ────────────────────────────────
select * from form
where date_from_parts(ano, mes, 1) < '2026-07-01'

union all

-- ── Jul/2026+: override administrativo (vence RI e form) ────────────────────
select * from override_contrato

union all

-- ── Jul/2026+: RI consultores (6 pipelines) ─────────────────────────────────
select * from ri_contrato r
where not exists (
    select 1 from override_chave o
    where o.ano = r.ano and o.mes = r.mes and o.consultor = r.consultor
)

union all

-- ── Jul/2026+: RI GD/SDRs ───────────────────────────────────────────────────
select * from gd_contrato g
where not exists (
    select 1 from override_chave o
    where o.ano = g.ano and o.mes = g.mes and o.consultor = g.consultor
)

union all

-- ── Jul/2026+: fallback form p/ quem não tem linha RI no mês ────────────────
-- (temporário: gestores/Sonia/Beatriz até os goals chegarem na RI, e GD
--  enquanto a carga do mês não existir; a RI vence sempre que tiver a linha)
select f.*
from form f
left join ri_contrato r
  on r.ano = f.ano and r.mes = f.mes and r.consultor = f.consultor
left join gd_contrato g
  on g.ano = f.ano and g.mes = f.mes and g.consultor = f.consultor
where date_from_parts(f.ano, f.mes, 1) >= '2026-07-01'
  and r.consultor is null
  and g.consultor is null
  and not exists (
      select 1 from override_chave o
      where o.ano = f.ano and o.mes = f.mes and o.consultor = lower(f.consultor)
  )
