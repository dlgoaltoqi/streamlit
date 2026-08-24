"""Cria SUPERSET.COMISSOES.METAS_OVERRIDE, grava as metas originais das
consultoras Farmer de jul/2026 e aplica a v4 da METAS_CONSULTORES_CONSOLIDADAS
(override > RI > form) a partir de docs/18_nova_view_metas_ri.sql.

UTF-8 via connector — nunca `snow sql -f`, que corrompe os acentos dos nomes
de pipeline dentro da view.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import snowflake.connector

SQL_PATH = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões\docs\18_nova_view_metas_ri.sql"

MOTIVO = ("Metas originais das consultoras Farmer definidas pelo negócio; "
          "substituem as metas propostas carregadas na RI.")
USUARIO = "higor.nocetti@altoqi.com.br"

# (ano, mes, email, equipe, desconto_pct 0-100, meta_bruta)
OVERRIDES = [
    (2026, 7, "aline.pureza@altoqi.com.br",     "Farmer",  0.0, 11000.0),
    (2026, 7, "clidiani@altoqi.com.br",         "Farmer",  0.0, 11000.0),
    (2026, 7, "debora.vieira@altoqi.com.br",    "Farmer",  0.0,  8600.0),
    (2026, 7, "mariana@altoqi.com.br",          "Farmer",  0.0, 14300.0),
    (2026, 7, "renata.parizotto@altoqi.com.br", "Farmer", 50.0, 14300.0),
]

with open(SQL_PATH, encoding="utf-8") as f:
    ddl = f.read()

conn = snowflake.connector.connect(connection_name="local_cli")
cur = conn.cursor()

# ── Baseline de julho ANTES de trocar a view ─────────────────────────────────
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(META_MRR), 2), ROUND(SUM(META_OTR), 2)
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
""")
antes_jul = cur.fetchone()
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(META_MRR), 2), ROUND(SUM(META_OTR), 2)
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 6
""")
antes_jun = cur.fetchone()
print(f"ANTES  jul/26: n={antes_jul[0]}  mrr={antes_jul[1]}  otr={antes_jul[2]}")
print(f"ANTES  jun/26: n={antes_jun[0]}  mrr={antes_jun[1]}  otr={antes_jun[2]}")

# ── Tabela de override ───────────────────────────────────────────────────────
cur.execute("""
    CREATE TABLE IF NOT EXISTS SUPERSET.COMISSOES.METAS_OVERRIDE (
        ANO                       NUMBER(4,0)   NOT NULL,
        MES                       NUMBER(2,0)   NOT NULL,
        EMAIL                     VARCHAR(255)  NOT NULL,
        EQUIPE                    VARCHAR(100)  NOT NULL,
        PERCENTUAL_DESCONTO_METAS FLOAT         DEFAULT 0,
        META_BRUTA                FLOAT         NOT NULL,
        ATIVO                     BOOLEAN       DEFAULT TRUE,
        MOTIVO                    VARCHAR(1000),
        USUARIO                   VARCHAR(255),
        DATA_REGISTRO             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )
    COMMENT = 'Correcao administrativa de meta para meses cuja origem e a RI (>= jul/2026). Vence RI e form na METAS_CONSULTORES_CONSOLIDADAS.'
""")
print("\nCREATE TABLE METAS_OVERRIDE:", cur.fetchone()[0])

for ano, mes, email, equipe, pct, bruta in OVERRIDES:
    cur.execute("""
        MERGE INTO SUPERSET.COMISSOES.METAS_OVERRIDE AS t
        USING (SELECT %s AS ANO, %s AS MES, %s AS EMAIL, %s AS EQUIPE,
                      %s AS PCT, %s AS BRUTA, %s AS MOTIVO, %s AS USUARIO) AS s
        ON t.ANO = s.ANO AND t.MES = s.MES
           AND LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.EQUIPE = s.EQUIPE
        WHEN MATCHED THEN UPDATE SET
            PERCENTUAL_DESCONTO_METAS = s.PCT,
            META_BRUTA     = s.BRUTA,
            ATIVO          = TRUE,
            MOTIVO         = s.MOTIVO,
            USUARIO        = s.USUARIO,
            DATA_REGISTRO  = CURRENT_TIMESTAMP(),
            DESATIVADO_POR = NULL,
            DESATIVADO_EM  = NULL
        WHEN NOT MATCHED THEN INSERT
            (ANO, MES, EMAIL, EQUIPE, PERCENTUAL_DESCONTO_METAS, META_BRUTA,
             ATIVO, MOTIVO, USUARIO, DATA_REGISTRO)
        VALUES
            (s.ANO, s.MES, s.EMAIL, s.EQUIPE, s.PCT, s.BRUTA,
             TRUE, s.MOTIVO, s.USUARIO, CURRENT_TIMESTAMP())
    """, (ano, mes, email, equipe, pct, bruta, MOTIVO, USUARIO))
    print(f"  MERGE {email:34s} bruta={bruta:>9.2f}  desc={pct:>5.1f}%  ->", cur.fetchone())

# ── View v4 ──────────────────────────────────────────────────────────────────
cur.execute(ddl)
print("\nCREATE OR REPLACE VIEW:", cur.fetchone()[0])

# ── Conferências ─────────────────────────────────────────────────────────────
print("\n— Julho por fonte/equipe:")
cur.execute("""
    SELECT FONTE, EQUIPE, COUNT(*) N,
           ROUND(SUM(META_MRR), 2) SOMA_MRR, ROUND(SUM(META_OTR), 2) SOMA_OTR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
    GROUP BY 1, 2 ORDER BY 1, 2
""")
for r in cur.fetchall():
    print(f"  {r[0]:9s} {r[1]:16s} n={r[2]:3d} mrr={r[3]}  otr={r[4]}")

print("\n— As cinco consultoras em jul/26 (deve: Override, sem duplicata):")
cur.execute("""
    SELECT CONSULTOR, EQUIPE, FONTE, PERCENTUAL_DESCONTO_METAS,
           META_MRR_BRUTO, META_MRR
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
      AND LOWER(CONSULTOR) IN ('aline.pureza@altoqi.com.br','clidiani@altoqi.com.br',
                               'debora.vieira@altoqi.com.br','mariana@altoqi.com.br',
                               'renata.parizotto@altoqi.com.br')
    ORDER BY CONSULTOR
""")
for r in cur.fetchall():
    print(f"  {r[0]:34s} {r[1]:8s} {r[2]:9s} desc={r[3]:>5}  bruta={r[4]:>10}  liquida={r[5]}")

print("\n— Julho: alguém duplicado?")
cur.execute("""
    SELECT CONSULTOR, COUNT(*) N
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
    GROUP BY 1 HAVING COUNT(*) > 1 ORDER BY 1
""")
dup = cur.fetchall()
print("  nenhum" if not dup else f"  {dup}")

print("\n— Depois (jul deve mudar só nas cinco; jun idêntico ao ANTES):")
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(META_MRR), 2), ROUND(SUM(META_OTR), 2)
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 7
""")
dep_jul = cur.fetchone()
cur.execute("""
    SELECT COUNT(*), ROUND(SUM(META_MRR), 2), ROUND(SUM(META_OTR), 2)
    FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
    WHERE ANO = 2026 AND MES = 6
""")
dep_jun = cur.fetchone()
print(f"  jul/26: n={dep_jul[0]}  mrr={dep_jul[1]}  otr={dep_jul[2]}"
      f"   (delta mrr = {round(float(dep_jul[1]) - float(antes_jul[1]), 2)})")
print(f"  jun/26: n={dep_jun[0]}  mrr={dep_jun[1]}  otr={dep_jun[2]}"
      f"   {'OK idêntico' if dep_jun == antes_jun else '*** MUDOU ***'}")

print("\n— Junho: view × form direto:")
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

cur.close()
conn.close()
