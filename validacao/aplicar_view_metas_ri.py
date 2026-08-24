"""Aplica a METAS_CONSULTORES_CONSOLIDADAS a partir de docs/18_nova_view_metas_ri.sql
(UTF-8 via connector — nunca snow sql -f) e roda conferências."""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import snowflake.connector

SQL_PATH = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões\docs\18_nova_view_metas_ri.sql"

with open(SQL_PATH, encoding="utf-8") as f:
    ddl = f.read()

conn = snowflake.connector.connect(connection_name="local_cli")
cur = conn.cursor()

# Trevisiol permanece B2B Escritório em julho (RI o coloca em GD por engano;
# a view exclui quem tem form com equipe != 'GD', entao o form prevalece)
cur.execute("""
    MERGE INTO SUPERSET.PARCIAL.META_CONSULTOR AS t
    USING (SELECT 2026 AS ANO, 7 AS MES,
                  'arthur.trevisiol@altoqi.com.br' AS EMAIL) AS s
    ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
    WHEN NOT MATCHED THEN INSERT
        (ANO, MES, EMAIL, EQUIPE, PERCENTUAL_DESCONTO_METAS,
         META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
         META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR)
    VALUES (2026, 7, 'arthur.trevisiol@altoqi.com.br', 'B2B Escritório', 0,
            0, 0, 0, 8,
            0, 0, 0, 8)
""")
print("MERGE Trevisiol (B2B Escritório, jul/26):", cur.fetchone())

# André Cardoso: gestor de GD a partir de julho; META_OTR = soma do time
# (excluindo Trevisiol, que ficou em B2B Escritório)
cur.execute("""
    MERGE INTO SUPERSET.PARCIAL.META_CONSULTOR AS t
    USING (SELECT
        2026 AS ANO, 7 AS MES,
        'andre.cardoso@altoqi.com.br' AS EMAIL,
        'GD' AS EQUIPE
    ) AS s ON t.ANO = s.ANO AND t.MES = s.MES AND LOWER(t.EMAIL) = LOWER(s.EMAIL)
    WHEN NOT MATCHED THEN INSERT
        (ANO, MES, EMAIL, EQUIPE, PERCENTUAL_DESCONTO_METAS,
         META_NMRR_BRUTO, META_EXPANSAO_BRUTO, META_RENOVACAO_BRUTO, META_OTR_BRUTO,
         META_NMRR, META_EXPANSAO, META_RENOVACAO, META_OTR)
    VALUES (2026, 7, 'andre.cardoso@altoqi.com.br', 'GD', 0,
            0, 0, 0, 398,
            0, 0, 0, 398)
    WHEN MATCHED THEN UPDATE SET
        META_OTR_BRUTO = 398, META_OTR = 398
""")
print("MERGE André Cardoso (GD gestor, jul/26):", cur.fetchone())

cur.execute(ddl)
print("\nCREATE OR REPLACE VIEW:", cur.fetchone()[0])

print("\n— Julho pela view (linhas por fonte/equipe):")
cur.execute("""
    SELECT FONTE, EQUIPE, COUNT(*) N,
           ROUND(SUM(META_MRR), 2) SOMA_MRR, ROUND(SUM(META_OTR), 2) SOMA_OTR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
    GROUP BY 1, 2 ORDER BY 1, 2
""")
for r in cur.fetchall():
    print(f"  {r[0]:5s} {r[1]:20s} n={r[2]:3d} mrr={r[3]}  otr={r[4]}")

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

print("\n— Trevisiol e André em julho/26 (deve: Trevisiol=B2B Escritório/Form, André=GD/Form):")
cur.execute("""
    SELECT CONSULTOR, EQUIPE, FONTE, META_OTR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
      AND CONSULTOR IN ('arthur.trevisiol@altoqi.com.br','andre.cardoso@altoqi.com.br')
    ORDER BY CONSULTOR
""")
for r in cur.fetchall():
    print(f"  {r[0]}  equipe={r[1]}  fonte={r[2]}  otr={r[3]}")

print("\n— Grants na view:")
cur.execute("SHOW GRANTS ON VIEW SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS")
for r in cur.fetchall():
    print(f"  {r[1]:10s} -> {r[5]}")

cur.close()
conn.close()
