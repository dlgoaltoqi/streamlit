"""Compara o cálculo ao vivo de jul/2026 (Farmer, já reaberto) com o snapshot
2026-07-Farmer-v2, para medir o efeito das metas originais das consultoras.
"""
import io
import os
import sys
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "validacao"))

import harness

session = harness.setup(ROOT)

ANO, MES = 2026, 7
EMAILS = [
    "aline.pureza@altoqi.com.br",
    "clidiani@altoqi.com.br",
    "debora.vieira@altoqi.com.br",
    "mariana@altoqi.com.br",
    "renata.parizotto@altoqi.com.br",
    "sonia.zielinski@altoqi.com.br",
]

snap = {}
df = session.sql(f"""
    SELECT LOWER(EMAIL) AS EMAIL, DADOS
    FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS
    WHERE FECHAMENTO_ID = '2026-07-Farmer-v2'
""").to_pandas()
for _, r in df.iterrows():
    v = r["DADOS"]
    snap[r["EMAIL"]] = v if isinstance(v, dict) else json.loads(str(v))


def f(d, k):
    v = d.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def brl(v):
    return f"{v:>12,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


print(f"{'Pessoa':<22} {'Meta antes':>11} {'Meta agora':>11} "
      f"{'% antes':>8} {'% agora':>8} {'Total antes':>13} {'Total agora':>13} {'Delta':>13}")
print("-" * 108)

tot_a = tot_d = 0.0
for em in EMAILS:
    vivo = harness.calc_live(em, ANO, MES)
    if not isinstance(vivo, dict) or "erro" in vivo:
        print(f"{em:<22} ERRO: {vivo}")
        continue
    s = snap.get(em, {})
    nome = em.split("@")[0]
    ma, md = f(s, "meta_mrr"), f(vivo, "meta_mrr")
    pa, pd_ = f(s, "pct_atingido") * 100, f(vivo, "pct_atingido") * 100
    ta, td = f(s, "total"), f(vivo, "total")
    tot_a += ta
    tot_d += td
    print(f"{nome:<22} {ma:>11,.0f} {md:>11,.0f} {pa:>7.2f}% {pd_:>7.2f}% "
          f"{brl(ta)} {brl(td)} {brl(td - ta)}")

print("-" * 108)
print(f"{'TOTAL':<22} {'':>11} {'':>11} {'':>8} {'':>8} "
      f"{brl(tot_a)} {brl(tot_d)} {brl(tot_d - tot_a)}")

print("\nDetalhe do OTE (efeito do desconto):")
for em in EMAILS:
    vivo = harness.calc_live(em, ANO, MES)
    if not isinstance(vivo, dict) or "erro" in vivo:
        continue
    s = snap.get(em, {})
    print(f"  {em.split('@')[0]:<22} desconto {f(s,'desconto'):.2f} -> {f(vivo,'desconto'):.2f}"
          f" | ote_base {f(s,'ote_base'):>9,.2f} -> {f(vivo,'ote_base'):>9,.2f}"
          f" | realizado {f(s,'realizado'):>11,.2f} -> {f(vivo,'realizado'):>11,.2f}")
