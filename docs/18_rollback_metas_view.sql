-- ═══════════════════════════════════════════════════════════════════════════
-- ROLLBACK — METAS_CONSULTORES_CONSOLIDADAS
-- Definição ORIGINAL da view (capturada via GET_DDL em 28/07/2026), acrescida
-- de COPY GRANTS para preservar os SELECTs.
-- Executar com role DATA_ENGINEER, pelo Snowsight (não usar `snow sql -f`).
-- ═══════════════════════════════════════════════════════════════════════════

create or replace view SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS(
    ANO,
    MES,
    CONSULTOR,
    EQUIPE,
    SENIORIDADE,
    FONTE,
    PERCENTUAL_DESCONTO_METAS,
    META_MRR_BRUTO,
    META_MRR,
    META_NMRR_BRUTO,
    META_NMRR,
    META_EXPANSAO_BRUTO,
    META_EXPANSAO,
    META_RENOVACAO_BRUTO,
    META_RENOVACAO,
    META_REATIVACAO,
    META_DEVEDOR,
    META_OTR_BRUTO,
    META_OTR
)
copy grants
as
select
    ANO,
    MES,
    EMAIL CONSULTOR,
    EQUIPE,
    mc.senioridade SENIORIDADE,
    'Form' FONTE,
    percentual_desconto_metas,
    meta_nmrr_bruto + meta_expansao_bruto + meta_renovacao_bruto META_MRR_BRUTO,
    meta_nmrr + meta_expansao + meta_renovacao META_MRR,
    meta_nmrr_bruto,
    meta_nmrr,
    meta_expansao_bruto,
    meta_expansao,
    meta_renovacao_bruto,
    meta_renovacao,
    0 meta_reativacao,
    0 meta_devedor,
    meta_otr_bruto,
    meta_otr
from
    superset.parcial.meta_consultor mc
where
    date_from_parts(ANO, MES, 1) >= '2025-10-01' and
    (meta_nmrr > 0 or meta_expansao > 0 or meta_renovacao > 0 or meta_otr > 0);
