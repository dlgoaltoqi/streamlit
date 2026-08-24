"""Validação pós multi-mês: (1) legado vs novo mês a mês (mar-jul);
(2) contexto em lote multi-mês vs mês único (janelas do histórico)."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRATCH = os.path.dirname(os.path.abspath(__file__))
PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, SCRATCH)

import harness

session = harness.setup(PROJECT)
import utils.commission as novo
import commission_legacy as legado

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


ANO = 2026
falhas = 0

# ── 1. Legado vs novo, mês a mês ──────────────────────────────────────────────
for mes in [3, 4, 5, 6, 7]:
    emails = universo(ANO, mes)
    harness.reset(); harness.CALC = legado
    res_leg = {}
    for e in emails:
        try:
            res_leg[e] = legado.calcular_comissao(session, e, ANO, mes)
        except Exception as ex:
            res_leg[e] = {"erro_execucao": str(ex)}
    harness.reset(); harness.CALC = novo
    n_diff = 0
    for e in emails:
        try:
            r_n = harness.calc_live(e, ANO, mes)
        except Exception as ex:
            r_n = {"erro_execucao": str(ex)}
        diffs = _diff(res_leg[e], r_n)
        # diffs conhecidos e documentados:
        #  - rotulo_aproveitamento: flag de exibição criada após o legado (None vs bool)
        #  - ma_q do gestor B2G em junho (bug do legado, sem impacto no pago)
        #  - b2g_ajuste.ajuste ~0: ruído de float do legado (ex.: 7e-12) vs None
        def _zero(v):
            n = _num(v)
            return v is None or (n is not None and abs(n) < 1e-6)
        diffs = [d for d in diffs if not (
            d[0] == "rotulo_aproveitamento"
            or (e == "marcelo.maestro@altoqi.com.br" and mes == 6
                and d[0].startswith("b2g_ajuste."))
            or (d[0] == "b2g_ajuste.ajuste" and _zero(d[1]) and _zero(d[2])))]
        if diffs:
            n_diff += 1
            print(f"  ✗ {mes:02d}/{ANO} {e}")
            for p, va, vb in diffs[:8]:
                print(f"      {p}: legado={va!r}  novo={vb!r}")
    print(f"{mes:02d}/{ANO}: {len(emails) - n_diff}/{len(emails)} idênticos (exceto diff documentado)")
    falhas += n_diff

# ── 2. Lote multi-mês vs mês único (janelas do histórico) ────────────────────
harness.reset(); harness.CALC = novo
for janela in ([3, 4, 5, 6], [4, 5, 6, 7]):
    ctxs = novo.montar_contextos(session, ANO, janela)
    n_diff = 0
    n_tot = 0
    for mes in janela:
        for e in universo(ANO, mes):
            n_tot += 1
            r_single = harness.calc_live(e, ANO, mes)          # ctx mês único (memoizado)
            r_multi = novo.calcular_comissao(session, e, ANO, mes, ctxs[mes])
            diffs = _diff(r_single, r_multi)
            if diffs:
                n_diff += 1
                print(f"  ✗ lote {janela} {mes:02d} {e}")
                for p, va, vb in diffs[:8]:
                    print(f"      {p}: unico={va!r}  lote={vb!r}")
    print(f"lote {janela}: {n_tot - n_diff}/{n_tot} idênticos")
    falhas += n_diff

print(f"\nqueries totais: {session.n_queries}")
print("FALHOU" if falhas else "TUDO IGUAL")
