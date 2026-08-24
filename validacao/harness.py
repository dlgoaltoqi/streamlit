"""Harness para rodar utils.commission localmente (fora do SiS).

- ShimSession: implementa session.sql(q).to_pandas() sobre snowflake-connector.
- Stub de utils.connection: fornece get_comissao snapshot-aware (mesma rotina
  do connection.get_comissao de producao, sem streamlit).
Uso: import harness; harness.setup(project_root) -> session
"""
import sys
import json
import types
import decimal

import pandas as pd
import snowflake.connector as sc


class _ShimResult:
    def __init__(self, cur):
        self._cur = cur

    def to_pandas(self):
        rows = self._cur.fetchall()
        cols = [d[0] for d in self._cur.description]
        df = pd.DataFrame(rows, columns=cols)
        # Decimal -> float para casar com o to_pandas do Snowpark
        for c in df.columns:
            if df[c].map(lambda v: isinstance(v, decimal.Decimal)).any():
                df[c] = df[c].map(lambda v: float(v) if isinstance(v, decimal.Decimal) else v)
        return df

    def collect(self):
        return self._cur.fetchall()


class ShimSession:
    def __init__(self, conn):
        self._conn = conn
        self.n_queries = 0

    def sql(self, q):
        cur = self._conn.cursor()
        cur.execute(q)
        self.n_queries += 1
        return _ShimResult(cur)


_SESSION = None
_MEMO = {}
_CTX = {}
CALC = None  # módulo com calcular_comissao a usar no cálculo ao vivo


def reset():
    """Limpa memo/contexto (chame ao trocar de módulo de cálculo)."""
    _MEMO.clear()
    _CTX.clear()


def calc_live(email, ano, mes):
    """calcular_comissao do módulo CALC, com contexto memoizado quando houver."""
    mod = CALC
    if mod is None:
        import utils.commission as mod
    if hasattr(mod, "montar_contexto"):
        key = (int(ano), int(mes), mod.__name__)
        if key not in _CTX:
            _CTX[key] = mod.montar_contexto(_SESSION, ano, mes)
        return mod.calcular_comissao(_SESSION, email, ano, mes, _CTX[key])
    return mod.calcular_comissao(_SESSION, email, ano, mes)


def _stub_get_comissao(email, ano, mes):
    """Espelho local do connection.get_comissao: snapshot se fechado, senao live."""
    em = str(email).strip().lower().replace("'", "''")
    key = (em, int(ano), int(mes), getattr(CALC, "__name__", "default"))
    if key in _MEMO:
        return _MEMO[key]
    df = _SESSION.sql(f"""
        SELECT cf.DADOS
        FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS cf
        JOIN SUPERSET.COMISSOES.FECHAMENTOS f ON cf.FECHAMENTO_ID = f.FECHAMENTO_ID
        WHERE cf.ANO = {int(ano)} AND cf.MES = {int(mes)}
          AND LOWER(cf.EMAIL) = '{em}' AND f.STATUS = 'ATIVO'
        ORDER BY f.DATA_FECHAMENTO DESC
        LIMIT 1
    """).to_pandas()
    if not df.empty:
        v = df.iloc[0]["DADOS"]
        res = v if isinstance(v, dict) else json.loads(str(v))
    else:
        res = calc_live(email, ano, mes)
    _MEMO[key] = res
    return res


def setup(project_root):
    """Conecta, registra o stub utils.connection e retorna a ShimSession."""
    global _SESSION
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    stub = types.ModuleType("utils.connection")
    stub.get_comissao = _stub_get_comissao
    sys.modules["utils.connection"] = stub
    conn = sc.connect(connection_name="local_cli")
    _SESSION = ShimSession(conn)
    return _SESSION


def jdefault(o):
    """Serializa Decimal/numpy/datas para JSON."""
    if isinstance(o, decimal.Decimal):
        return float(o)
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
    except Exception:
        pass
    return str(o)
