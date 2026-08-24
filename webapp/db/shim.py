"""ShimSession: a interface session.sql(q).to_pandas()/.collect() que
utils/commission.py e utils/fechamento.py esperam, sobre snowflake-connector.

Promovida de validacao/harness.py (onde o padrão foi provado), com três
acréscimos: suporte a binds (params), contador de queries para o smoke, e
despacho assíncrono (19/08/2026 — ver _ShimResult/ShimSession abaixo).

Por que assíncrono: utils/commission.py:_lote_pandas dispara ~15 queries de
montar_contexto via session.sql(q).to_pandas(block=False) esperando o modo
assíncrono nativo do Snowpark (paralelo de verdade: tempo do lote = o da
query mais lenta). O ShimSession antigo não aceitava `block`, então TODO
lote caía no fallback sequencial do próprio _lote_pandas — o webapp nunca
tinha o ganho que o SiS tem desde 14/08/2026 (comentário no próprio
commission.py). Testado empiricamente (19/08/2026): 10 queries de 1s cada,
12,4s sequencial vs 8,7s via execute_async — melhora real, não dramática
(overhead de submissão por query ainda existe), mas sem essa mudança o
webapp NUNCA tinha esse ganho, só o fallback lento sempre.
"""
import decimal

import pandas as pd


class _AsyncJob:
    """Superfície mínima do AsyncJob do Snowpark: só .result()."""

    def __init__(self, shim_result):
        self._r = shim_result

    def result(self):
        self._r._aguardar()
        return self._r._to_df()


class _ShimResult:
    def __init__(self, cur):
        self._cur = cur
        self._pronto = False
        self._df = None

    def _aguardar(self):
        """Garante que a query (disparada com execute_async) terminou, antes
        de buscar description/linhas — sem isso fetchall() falha com
        'NoneType is not an iterator' (testado em 19/08/2026)."""
        if not self._pronto:
            self._cur.get_results_from_sfqid(self._cur.sfqid)
            self._pronto = True

    def _to_df(self):
        if self._df is None:
            rows = self._cur.fetchall()
            cols = [d[0] for d in self._cur.description]
            df = pd.DataFrame(rows, columns=cols)
            # Decimal -> float para casar com o to_pandas do Snowpark
            for c in df.columns:
                if df[c].map(lambda v: isinstance(v, decimal.Decimal)).any():
                    df[c] = df[c].map(lambda v: float(v) if isinstance(v, decimal.Decimal) else v)
            self._df = df
        return self._df

    def to_pandas(self, block=True):
        """block=False replica o AsyncJob do Snowpark (usado por
        utils/commission.py:_lote_pandas): devolve um job com .result(),
        sem esperar aqui — quem chama dispara vários e só espera depois,
        deixando as queries correrem em paralelo no warehouse."""
        if not block:
            return _AsyncJob(self)
        self._aguardar()
        return self._to_df()

    def collect(self):
        self._aguardar()
        return self._cur.fetchall()


class ShimSession:
    """Mesma superfície usada pelo código compartilhado: sql().to_pandas()/collect().

    `params` habilita binds (paramstyle pyformat %s) nas queries NOVAS do
    webapp; o código compartilhado continua chamando sql(q) sem params.

    sql() despacha com execute_async (não bloqueia); quem encadeia
    .to_pandas()/.collect() na hora (o padrão em ~99% do código) espera ali
    mesmo, sem diferença de comportamento. Isso deixa uma query "solta" (sem
    ninguém ter chamado .to_pandas()/.collect() nela) tecnicamente pendente
    até alguém confirmar — por isso todo sql() registra o resultado em
    _pendentes, e confirmar_pendentes() (chamado pelo pool ao devolver a
    conexão, webapp/db/pool.py) garante que nenhuma escrita "fire-and-forget"
    (ex.: admin_repo.py, que não encadeia .collect()) fique sem confirmar —
    erro nela precisa continuar estourando, só que na saída do `with
    get_pool().session()`, não mais na linha do sql().
    """

    def __init__(self, conn, on_query=None):
        self._conn = conn
        self.n_queries = 0
        self._on_query = on_query
        self._pendentes = []

    def sql(self, q, params=None):
        cur = self._conn.cursor()
        cur.execute_async(q, params)
        self.n_queries += 1
        if self._on_query is not None:
            self._on_query()
        r = _ShimResult(cur)
        self._pendentes.append(r)
        return r

    def confirmar_pendentes(self):
        pendentes, self._pendentes = self._pendentes, []
        for r in pendentes:
            r._aguardar()

    def descartar_pendentes(self):
        """Abandona pendentes sem esperar por eles nem propagar erro — usado
        quando o corpo do `with get_pool().session()` já lançou uma
        exceção; sem isso, uma escrita fire-and-forget órfã ficaria em
        _pendentes e sua falha estouraria na próxima sessão que reusar esta
        conexão do pool, num request sem relação com a que a causou."""
        self._pendentes.clear()

    def is_alive(self):
        try:
            return not self._conn.is_closed()
        except Exception:
            return False

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
