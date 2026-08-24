"""Remove TODOS os dados de demonstração criados por demo_criar.py.

Rastreabilidade: e-mails demo.%@altoqi.com.br, equipes 'Demo %',
fechamentos '2026-MM-Demo-v1'. Rodar com o venv de validação:
  venv\\Scripts\\python.exe validacao\\demo_apagar.py
"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import snowflake.connector as sc

DELETES = [
    ("COMPOSICAO_FECHADA",
     "DELETE FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA WHERE LOWER(EMAIL) LIKE 'demo.%'"),
    ("COMISSOES_FECHADAS",
     "DELETE FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS WHERE LOWER(EMAIL) LIKE 'demo.%'"),
    ("FECHAMENTOS",
     "DELETE FROM SUPERSET.COMISSOES.FECHAMENTOS WHERE EQUIPE = 'Demo'"),
    ("PARAMETROS",
     "DELETE FROM SUPERSET.COMISSOES.PARAMETROS WHERE LOWER(EMAIL) LIKE 'demo.%'"),
    ("META_CONSULTOR",
     "DELETE FROM SUPERSET.PARCIAL.META_CONSULTOR WHERE LOWER(EMAIL) LIKE 'demo.%'"),
    ("PERMISSAO_RLS",
     "DELETE FROM SUPERSET.PARCIAL.PERMISSAO_RLS WHERE LOWER(USUARIOEMAIL) LIKE 'demo.%' OR LOWER(CONSULTOREMAIL) LIKE 'demo.%'"),
]

cn = sc.connect(connection_name="local_cli")
cur = cn.cursor()
for nome, sql in DELETES:
    cur.execute(sql)
    print(f"{nome}: {cur.rowcount} linha(s) removida(s)")
cn.close()
print("\nDados de demonstração removidos.")
