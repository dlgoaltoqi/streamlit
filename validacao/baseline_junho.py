"""Captura o baseline de junho/2026 com o codigo ATUAL de utils/commission.py.

Seleciona 1 consultor + 1 gestor por equipe (com parametros no mes) e a
consultora de canc-recovery, roda calcular_comissao e salva o dict completo em
validacao/baseline_2026_06.json.
"""
import io
import os
import sys
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRATCH = os.path.dirname(os.path.abspath(__file__))
PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, SCRATCH)

import harness

ANO, MES = 2026, 6

session = harness.setup(PROJECT)
import utils.commission as C

refs_df = session.sql(f"""
    WITH cons AS (
        SELECT m.EQUIPE, LOWER(m.CONSULTOR) AS EMAIL, p.IS_GESTOR,
               ROW_NUMBER() OVER (PARTITION BY m.EQUIPE, p.IS_GESTOR
                                  ORDER BY m.CONSULTOR) AS rn
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON p.ANO = m.ANO AND p.MES = m.MES AND LOWER(p.EMAIL) = LOWER(m.CONSULTOR)
        WHERE m.ANO = {ANO} AND m.MES = {MES}
    )
    SELECT EQUIPE, EMAIL, IS_GESTOR FROM cons WHERE rn = 1
    UNION ALL
    SELECT 'Cancelamento' AS EQUIPE, LOWER(EMAIL) AS EMAIL, FALSE AS IS_GESTOR
    FROM SUPERSET.COMISSOES.PARAMETROS
    WHERE ANO = {ANO} AND MES = {MES} AND IS_CANC_RECOVERY = TRUE
    QUALIFY ROW_NUMBER() OVER (ORDER BY EMAIL) = 1
    ORDER BY EQUIPE, IS_GESTOR
""").to_pandas()

print(f"{len(refs_df)} referencias selecionadas:")
baseline = {}
for _, r in refs_df.iterrows():
    email = str(r["EMAIL"])
    rotulo = f"{r['EQUIPE']}{' (gestor)' if r['IS_GESTOR'] else ''}"
    try:
        dados = C.calcular_comissao(session, email, ANO, MES)
    except Exception as e:
        dados = {"erro_execucao": str(e)}
    total = dados.get("total") if isinstance(dados, dict) else None
    print(f"  {rotulo:28s} {email:42s} total={total}")
    baseline[email] = {"equipe_ref": rotulo, "ano": ANO, "mes": MES, "dados": dados}

out_dir = os.path.join(PROJECT, "validacao")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, f"baseline_{ANO}_{MES:02d}.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(baseline, f, default=harness.jdefault, ensure_ascii=False, indent=2)
print(f"\nBaseline salvo em {out_path}")
print(f"Total de queries executadas: {session.n_queries}")
