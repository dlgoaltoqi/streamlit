"""Gera referência de comissões de um mês via harness (caminho SiS-equivalente).

    python validacao/ref_harness_mes.py <ano> <mes> <saida.json>

Usada por validar_webapp.py para comparar o webapp com o cálculo de referência
em processo separado (harness e webapp registram stubs diferentes de
utils.connection e não podem coexistir no mesmo processo).
"""
import json
import sys

PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, PROJECT + r"\validacao")

import harness  # noqa: E402

ano, mes, saida = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
session = harness.setup(PROJECT)

df = session.sql(f"""
    SELECT DISTINCT EMAIL FROM (
        SELECT LOWER(CONSULTOR) AS EMAIL
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND CONSULTOR IS NOT NULL
        UNION
        SELECT LOWER(EMAIL) FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND EMAIL IS NOT NULL
    ) ORDER BY EMAIL
""").to_pandas()

out = {}
for e in [str(x) for x in df["EMAIL"]]:
    try:
        out[e] = harness.calc_live(e, ano, mes)
    except Exception as ex:
        out[e] = {"erro_execucao": str(ex)}

with open(saida, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, default=harness.jdefault)
print(f"referencia {mes:02d}/{ano}: {len(out)} pessoas -> {saida}")
