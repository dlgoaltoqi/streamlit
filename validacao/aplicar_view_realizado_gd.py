"""Corrige SUPERSET.COMISSOES.REALIZADO_GD após a renomeação das tabelas do
schema HUBSPOT.HUBSPOT_PRATA (padrão HUBSPOT_*, 18/08/2026).

A tabela ASSOCIATIONS_LEADS_DEAL foi renomeada para HUBSPOT_ASSOCIATIONS_LEADS_DEAL
e, diferente de LEADS/CONTACTS/DEALS, não ganhou view de compatibilidade. As
colunas do join também mudaram de nomes acentuados para MAIÚSCULAS:

    ALD."Id do lead"    -> ALD.ID_LEAD
    ALD."Id do negócio" -> ALD.ID_DEAL

O DDL é lido de volta com GET_DDL e alterado por substituição de texto, para não
reescrever à mão os identificadores acentuados da view.

UTF-8 via connector — nunca `snow sql -f`, que corrompe os acentos.

Uso:
    python validacao/aplicar_view_realizado_gd.py           # só testa (dry-run)
    python validacao/aplicar_view_realizado_gd.py --apply   # aplica a view
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import snowflake.connector

APLICAR = "--apply" in sys.argv

SUBSTITUICOES = [
    ("HUBSPOT.HUBSPOT_PRATA.ASSOCIATIONS_LEADS_DEAL",
     "HUBSPOT.HUBSPOT_PRATA.HUBSPOT_ASSOCIATIONS_LEADS_DEAL"),
    ('ALD."Id do lead"', "ALD.ID_LEAD"),
    ('ALD."Id do negócio"', "ALD.ID_DEAL"),
]

conn = snowflake.connector.connect(connection_name="local_cli")
cur = conn.cursor()
cur.execute("USE SCHEMA SUPERSET.COMISSOES")

# ── DDL atual ────────────────────────────────────────────────────────────────
cur.execute("SELECT GET_DDL('view', 'SUPERSET.COMISSOES.REALIZADO_GD')")
ddl = cur.fetchone()[0]

novo = ddl
for antigo, atual in SUBSTITUICOES:
    n = novo.count(antigo)
    print(f"  {antigo:52s} -> {atual:<44s} ({n}x)")
    if n == 0:
        sys.exit(f"ABORTADO: trecho não encontrado no DDL: {antigo}")
    novo = novo.replace(antigo, atual)

# COPY GRANTS preserva os SELECT de ACCOUNTADMIN / DATA_ANALYST / GENERAL_ANALYST
marcador = ") COMMENT="
if "COPY GRANTS" not in novo:
    if marcador not in novo:
        sys.exit("ABORTADO: não achei onde inserir COPY GRANTS")
    novo = novo.replace(marcador, ") COPY GRANTS COMMENT=", 1)
    print("  + COPY GRANTS")

# ── Teste do corpo antes de trocar a view ────────────────────────────────────
inicio = novo.index("WITH PROPRIETARIO_PRATA_01")
corpo = novo[inicio:].rstrip().rstrip(";")

print("\n— Teste do corpo novo (sem tocar na view):")
cur.execute(f"SELECT COUNT(*) FROM ({corpo})")
print(f"  linhas = {cur.fetchone()[0]}")

cur.execute(f"""
    SELECT DATE_TRUNC('month', DATA_QUALIFICACAO)::date AS MES,
           COUNT(DISTINCT ID_CONTATO) AS OPPS,
           COUNT(*) AS LINHAS
    FROM ({corpo})
    GROUP BY 1 ORDER BY 1
""")
for r in cur.fetchall():
    print(f"  {r[0]}  opps={r[1]:>5}  linhas={r[2]:>6}")

print("\n— Realizado por equipe (últimos meses):")
cur.execute(f"""
    SELECT DATE_TRUNC('month', DATA_QUALIFICACAO)::date AS MES, EQUIPE,
           COUNT(DISTINCT ID_CONTATO) AS OPPS
    FROM ({corpo})
    WHERE DATA_QUALIFICACAO >= '2026-06-01'
    GROUP BY 1, 2 ORDER BY 1, 2
""")
for r in cur.fetchall():
    print(f"  {r[0]}  {r[1]:24s} opps={r[2]:>5}")

# ── Aplicação ────────────────────────────────────────────────────────────────
if not APLICAR:
    print("\nDRY-RUN: a view NÃO foi alterada. Rode com --apply para aplicar.")
else:
    # A view pertence a DATA_ENGINEER; GENERAL_ANALYST não tem CREATE VIEW aqui.
    cur.execute("USE ROLE DATA_ENGINEER")
    cur.execute("USE SCHEMA SUPERSET.COMISSOES")
    cur.execute(novo)
    print("\nCREATE OR REPLACE VIEW:", cur.fetchone()[0])

    cur.execute("SELECT COUNT(*) FROM SUPERSET.COMISSOES.REALIZADO_GD")
    print(f"  SELECT na view: {cur.fetchone()[0]} linhas")

    print("\n— Grants depois (devem ser os mesmos 3 SELECT + OWNERSHIP):")
    cur.execute("SHOW GRANTS ON VIEW SUPERSET.COMISSOES.REALIZADO_GD")
    for r in cur.fetchall():
        print(f"  {r[1]:10s} -> {r[5]}")

cur.close()
conn.close()
