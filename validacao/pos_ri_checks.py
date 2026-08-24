"""Pós-migração metas RI (fase 5, docs/18): sanidade da view + pendências.
Somente SELECTs."""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import snowflake.connector

conn = snowflake.connector.connect(connection_name="local_cli")
cur = conn.cursor()

print("— Julho pela view (linhas por fonte/equipe):")
cur.execute("""
    SELECT FONTE, EQUIPE, COUNT(*) N,
           ROUND(SUM(META_MRR), 2) SOMA_MRR, ROUND(SUM(META_OTR), 2) SOMA_OTR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
    GROUP BY 1, 2 ORDER BY 1, 2
""")
for r in cur.fetchall():
    print(f"  {r[0]:5s} {r[1]:20s} n={r[2]:3d} mrr={r[3]}  otr={r[4]}")

print("\n— Spot-checks (esperado: fernanda 9500/50/4750; renata 12750/48/6630):")
cur.execute("""
    SELECT CONSULTOR, FONTE, PERCENTUAL_DESCONTO_METAS, META_MRR_BRUTO, META_MRR, META_OTR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
      AND CONSULTOR IN ('fernanda.fertonani@altoqi.com.br',
                        'renata.parizotto@altoqi.com.br',
                        'thales.sa@altoqi.com.br',
                        'luiz.santos@altoqi.com.br',
                        'luciana.vieira@altoqi.com.br',
                        'beatriz@altoqi.com.br',
                        'tabata.couto@altoqi.com.br')
    ORDER BY CONSULTOR
""")
for r in cur.fetchall():
    print(f"  {r[0]:42s} {r[1]:5s} desc={r[2]} bruto={r[3]} liq={r[4]} otr={r[5]}")

print("\n— Junho intacto? (view nova × form direto):")
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(META_MRR), 2), ROUND(SUM(META_OTR), 2),
           MIN(FONTE), MAX(FONTE)
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 6
""")
print("  view :", cur.fetchone())
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(meta_nmrr + meta_expansao + meta_renovacao), 2),
           ROUND(SUM(meta_otr), 2)
    FROM SUPERSET.PARCIAL.META_CONSULTOR
    WHERE ANO = 2026 AND MES = 6
      AND (meta_nmrr > 0 OR meta_expansao > 0 OR meta_renovacao > 0 OR meta_otr > 0)
""")
print("  form :", cur.fetchone())

print("\n— Grants na view:")
cur.execute("SHOW GRANTS ON VIEW SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS")
for r in cur.fetchall():
    print(f"  {r[1]:10s} -> {r[5]}")

print("\n— Pendências (RI jul/2026 sem e-mail, sem Parâmetros ou sem RLS):")
cur.execute("""
    WITH ri AS (
        SELECT ric.name nome, rip.name pipeline, LOWER(rio.email) email
        FROM revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_consultant_goals ricg
        JOIN revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_consultants ric
          ON ric.id = ricg.consultant_id
        LEFT JOIN revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_owners rio
          ON rio.id = ric.hubspot_owner_id
        LEFT JOIN revenue_intelligence.revenue_intelligence_prata.revenue_intelligence_pipelines rip
          ON rip.id = ricg.pipeline_id
        WHERE ricg.year = 2026 AND ricg.month = 7
    ),
    par AS (SELECT DISTINCT LOWER(EMAIL) email FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = 2026 AND MES = 7),
    rls AS (SELECT DISTINCT LOWER(CONSULTOREMAIL) email FROM SUPERSET.PARCIAL.PERMISSAO_RLS)
    SELECT ri.nome, ri.pipeline, COALESCE(ri.email, '(sem e-mail!)') email,
           IFF(ri.email IS NULL, 'SEM E-MAIL', '') f1,
           IFF(p.email IS NULL, 'SEM PARAMETROS', '') f2,
           IFF(r.email IS NULL, 'SEM RLS', '') f3
    FROM ri
    LEFT JOIN par p ON p.email = ri.email
    LEFT JOIN rls r ON r.email = ri.email
    WHERE ri.email IS NULL OR p.email IS NULL OR r.email IS NULL
    ORDER BY ri.pipeline, ri.nome
""")
rows = cur.fetchall()
if not rows:
    print("  (nenhuma pendência)")
for r in rows:
    flags = " | ".join(x for x in (r[3], r[4], r[5]) if x)
    print(f"  {r[0]:42s} {r[1]:30s} {r[2]:40s} {flags}")

cur.close()
conn.close()
