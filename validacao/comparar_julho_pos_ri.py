"""Compara o cálculo de julho/2026 APÓS a migração de metas RI contra o
baseline pré-migração (validacao/baseline_2026_07_pre_ri.json)."""
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
TOL = 0.005

session = harness.setup(PROJECT)
import utils.commission as C

with open(os.path.join(PROJECT, "validacao", "baseline_2026_07_pre_ri.json"),
          encoding="utf-8") as f:
    baseline = json.load(f)

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
        return abs(na - nb) <= max(TOL, 1e-9 * max(abs(na), abs(nb)))
    return a == b


CAMPOS = ["equipe", "meta_mrr", "desconto", "realizado", "pct_atingido",
          "ote_base", "ote_variavel", "comissao_bk_extra", "comissao_dividas",
          "bonificacao_protecao", "ajuste_total", "total"]

ctx = C.montar_contexto(session, ANO, MES)
novos, mudaram, iguais, sumiram = [], [], [], []

for email in emails:
    try:
        d_new = C.calcular_comissao(session, email, ANO, MES, ctx)
    except Exception as e:
        d_new = {"erro_execucao": str(e)}
    b = baseline.get(email)
    if b is None:
        novos.append((email, d_new))
        continue
    d_old = b["dados"]
    difs = [(k, d_old.get(k), d_new.get(k)) for k in CAMPOS
            if not _eq(d_old.get(k), d_new.get(k))]
    (mudaram if difs else iguais).append((email, difs, d_old, d_new))

for email in baseline:
    if email not in emails:
        sumiram.append(email)

print(f"universo julho: {len(emails)} | iguais: {len(iguais)} | "
      f"mudaram: {len(mudaram)} | novos: {len(novos)} | sumiram: {len(sumiram)}\n")

if mudaram:
    print("═══ MUDARAM ═══")
    for email, difs, d_old, d_new in mudaram:
        print(f"\n  {email}  (total {d_old.get('total')!r} → {d_new.get('total')!r})")
        for k, va, vb in difs:
            print(f"      {k}: {va!r} → {vb!r}")

if novos:
    print("\n═══ NOVOS (não existiam no baseline) ═══")
    for email, d in novos:
        if "erro_execucao" in d:
            print(f"  {email}: ERRO {d['erro_execucao'][:120]}")
        else:
            print(f"  {email}: equipe={d.get('equipe')!r} meta={d.get('meta_mrr')!r} "
                  f"total={d.get('total')!r}")

if sumiram:
    print("\n═══ SUMIRAM do universo ═══")
    for email in sumiram:
        print(f"  {email}")

print(f"\nqueries totais: {session.n_queries}")
