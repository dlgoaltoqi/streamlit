"""Validação da refatoração em lote: legado vs novo, pessoa a pessoa.

Para cada mês testado, calcula a comissão de TODAS as pessoas (METAS ∪ PARAMETROS)
pelo código legado (commission_legacy) e pelo novo (utils.commission) e compara
os dicts campo a campo. Tolerância: 0,5 centavo ou 1e-9 relativo.
Também compara o novo resultado com o baseline salvo de junho.
"""
import io
import os
import sys
import json
import math

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRATCH = os.path.dirname(os.path.abspath(__file__))
PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, SCRATCH)

import harness

session = harness.setup(PROJECT)
import utils.commission as novo
import commission_legacy as legado

MESES_TESTE = [(2026, 5), (2026, 6), (2026, 7)]
TOL_ABS = 0.005


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _eq(a, b):
    if a is None and b is None:
        return True
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= max(TOL_ABS, 1e-9 * max(abs(na), abs(nb)))
    return a == b


def _diff(a, b, path=""):
    """Lista de (path, legado, novo) onde os valores divergem."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out.extend(_diff(a.get(k), b.get(k), f"{path}.{k}" if path else str(k)))
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            out.append((path, f"len={len(a)}", f"len={len(b)}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out.extend(_diff(x, y, f"{path}[{i}]"))
    elif not _eq(a, b):
        out.append((path, a, b))
    return out


def universo(ano, mes):
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
    return [str(e) for e in df["EMAIL"].tolist()]


total_diffs = 0
resumo = []
for ano, mes in MESES_TESTE:
    emails = universo(ano, mes)
    print(f"\n══ {mes:02d}/{ano} — {len(emails)} pessoas ══")

    harness.reset()
    harness.CALC = legado
    q0 = session.n_queries
    res_leg = {}
    for e in emails:
        try:
            res_leg[e] = legado.calcular_comissao(session, e, ano, mes)
        except Exception as ex:
            res_leg[e] = {"erro_execucao": str(ex)}
    q_leg = session.n_queries - q0

    harness.reset()
    harness.CALC = novo
    q0 = session.n_queries
    res_novo = {}
    for e in emails:
        try:
            res_novo[e] = harness.calc_live(e, ano, mes)
        except Exception as ex:
            res_novo[e] = {"erro_execucao": str(ex)}
    q_novo = session.n_queries - q0

    n_diff_mes = 0
    for e in emails:
        diffs = _diff(res_leg[e], res_novo[e])
        if diffs:
            n_diff_mes += 1
            print(f"\n  ✗ {e}")
            for p, va, vb in diffs[:12]:
                print(f"      {p}: legado={va!r}  novo={vb!r}")
            if len(diffs) > 12:
                print(f"      ... +{len(diffs) - 12} campos")
    total_diffs += n_diff_mes
    ok = len(emails) - n_diff_mes
    resumo.append((f"{mes:02d}/{ano}", len(emails), ok, n_diff_mes, q_leg, q_novo))
    print(f"  ✓ {ok}/{len(emails)} idênticos | queries: legado={q_leg}, novo={q_novo}")

# ── Baseline de junho ─────────────────────────────────────────────────────────
print("\n══ Baseline junho (código atual em produção no momento da captura) ══")
bl_path = os.path.join(PROJECT, "validacao", "baseline_2026_06.json")
with open(bl_path, encoding="utf-8") as f:
    baseline = json.load(f)
n_bl_diff = 0
for e, item in baseline.items():
    atual = harness.calc_live(e, 2026, 6)
    diffs = _diff(item["dados"], atual)
    if diffs:
        n_bl_diff += 1
        print(f"\n  ✗ {item['equipe_ref']} — {e}")
        for p, va, vb in diffs[:10]:
            print(f"      {p}: baseline={va!r}  novo={vb!r}")
if n_bl_diff == 0:
    print(f"  ✓ {len(baseline)}/{len(baseline)} referências idênticas ao baseline")

print("\n══ RESUMO ══")
for m, n, ok, nd, ql, qn in resumo:
    print(f"  {m}: {ok}/{n} idênticos ({nd} diffs) | queries {ql} → {qn}")
print(f"  Baseline: {len(baseline) - n_bl_diff}/{len(baseline)} idênticos")
print(f"\n{'FALHOU' if (total_diffs or n_bl_diff) else 'TUDO IGUAL'}")
