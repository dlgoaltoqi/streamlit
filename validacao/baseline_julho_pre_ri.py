"""Baseline de julho/2026 ANTES da migração de metas para o RI (fase 3 do
docs/18_migracao_metas_ri.md).

Roda calcular_comissao para TODAS as pessoas de julho (METAS ∪ PARAMETROS) com
a fonte atual e salva em validacao/baseline_2026_07_pre_ri.json. Após o deploy
do modelo dbt, comparar o cálculo novo contra este arquivo — diffs esperados
apenas onde a meta muda de fato.
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

ANO, MES = 2026, 7

session = harness.setup(PROJECT)
import utils.commission as C

df = session.sql(f"""
    SELECT DISTINCT EMAIL FROM (
        SELECT LOWER(CONSULTOR) AS EMAIL
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ANO} AND MES = {MES} AND CONSULTOR IS NOT NULL
        UNION
        SELECT LOWER(EMAIL) FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ANO} AND MES = {MES} AND EMAIL IS NOT NULL
    ) ORDER BY EMAIL
""").to_pandas()
emails = [str(e) for e in df["EMAIL"].tolist()]
print(f"{len(emails)} pessoas no universo de {MES:02d}/{ANO}")

ctx = C.montar_contexto(session, ANO, MES)
baseline = {}
for email in emails:
    try:
        dados = C.calcular_comissao(session, email, ANO, MES, ctx)
    except Exception as e:
        dados = {"erro_execucao": str(e)}
    total = dados.get("total") if isinstance(dados, dict) else None
    print(f"  {email:45s} total={total}")
    baseline[email] = {"ano": ANO, "mes": MES, "dados": dados}

out_path = os.path.join(PROJECT, "validacao", f"baseline_{ANO}_{MES:02d}_pre_ri.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(baseline, f, default=harness.jdefault, ensure_ascii=False, indent=2)
print(f"\nBaseline salvo em {out_path}")
print(f"Total de queries executadas: {session.n_queries}")
