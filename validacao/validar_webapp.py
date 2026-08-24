"""Validação de paridade do webapp (Fase 2 do plano de migração).

    python validacao/validar_webapp.py [AAAA-MM ...]

Para cada mês (default: jun/2026 e o mês corrente), gera uma referência pelo
HARNESS em processo separado (o caminho SiS-equivalente, mesmo código de
cálculo) e compara pessoa a pessoa com o caminho do WEBAPP (bootstrap + pool
+ comissao_service, cálculo vivo). Igualdade aqui prova que a troca de
plataforma não muda nenhum número.

O baseline_2026_06.json NÃO é gate: ele foi congelado em julho e as regras
de negócio mudaram desde então (metas RI v4, renovações de cancelamento,
rotulo_aproveitamento, recriação da HUBSPOT_CONTRATOS) — o próprio SiS de
hoje diverge dele. A referência viva do harness é a comparação correta.

Tolerância numérica: 0,5 centavo ou 1e-9 relativo.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, PROJECT)

from webapp.bootstrap import install_connection_shim  # noqa: E402

install_connection_shim()

from webapp.core import periods                        # noqa: E402
from webapp.services import comissao_service as cs     # noqa: E402

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


def _roundtrip(o):
    """Passa pelo JSON para igualar tipos (numpy/Decimal/datas) à referência."""
    import decimal
    def default(x):
        if isinstance(x, decimal.Decimal):
            return float(x)
        try:
            import numpy as np
            if isinstance(x, np.integer):
                return int(x)
            if isinstance(x, np.floating):
                return float(x)
            if isinstance(x, np.bool_):
                return bool(x)
        except Exception:
            pass
        return str(x)
    return json.loads(json.dumps(o, default=default))


def _meses_alvo():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return [(int(a.split("-")[0]), int(a.split("-")[1])) for a in args]
    return [(2026, 6), periods.periodo_default()]


falhas = 0
for ano, mes in _meses_alvo():
    ref_path = os.path.join(tempfile.gettempdir(), f"ref_harness_{ano}_{mes:02d}.json")
    print(f"\n══ Webapp vs harness — {mes:02d}/{ano} (referência em processo separado) ══")
    r = subprocess.run(
        [sys.executable, os.path.join(PROJECT, "validacao", "ref_harness_mes.py"),
         str(ano), str(mes), ref_path],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit(1)
    with open(ref_path, encoding="utf-8") as f:
        ref = json.load(f)

    n_diff_mes = 0
    for e, dados_ref in ref.items():
        try:
            atual = _roundtrip(cs.get_comissao_cached(e, ano, mes))
        except Exception as ex:
            atual = {"erro_execucao": str(ex)}
        diffs = _diff(dados_ref, atual)
        if diffs:
            n_diff_mes += 1
            print(f"\n  ✗ {e}")
            for p, va, vb in diffs[:10]:
                print(f"      {p}: harness={va!r}  webapp={vb!r}")
    if n_diff_mes == 0:
        print(f"  ✓ {len(ref)}/{len(ref)} pessoas idênticas à referência")
    falhas += n_diff_mes

print(f"\n{'FALHOU' if falhas else 'TUDO IGUAL'}")
sys.exit(1 if falhas else 0)
