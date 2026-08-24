"""Pool de conexões Snowflake para o servidor multiusuário.

Empréstimo exclusivo via context manager (thread-safe por construção):

    from webapp.db.pool import get_pool
    with get_pool().session() as s:
        df = s.sql("SELECT 1").to_pandas()

Dois modos (webapp/config.py): dev usa connection_name (connections.toml,
igual ao harness); servidor usa service account com key-pair.
"""
import contextvars
import queue
import threading
import time
from contextlib import contextmanager

import snowflake.connector as sc

from webapp.config import settings
from webapp.db.shim import ShimSession

_PING_IDLE_S = 300  # revalida conexão ociosa há mais de 5 min

# Progresso de consultas "de verdade" (19/08/2026, pedido do Higor: trocar o
# spinner indeterminado por uma barra que reflita consultas reais ao
# Snowflake). Quem quiser acompanhar quantas consultas uma operação disparou
# seta um JobState aqui (contextvars.ContextVar isola por thread — cada job
# roda na sua própria thread dedicada, então jobs concorrentes não se
# misturam). Objeto esperado: qualquer coisa com atributo `concluidos: int`.
PROGRESSO_ATUAL = contextvars.ContextVar("progresso_atual", default=None)


def _connect():
    if settings.usa_keypair():
        from cryptography.hazmat.primitives import serialization
        with open(settings.sf_private_key_path, "rb") as fh:
            pk = serialization.load_pem_private_key(fh.read(), password=None)
        key_der = pk.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return sc.connect(
            account=settings.sf_account,
            user=settings.sf_user,
            private_key=key_der,
            role=settings.sf_role,
            warehouse=settings.sf_warehouse,
        )
    return sc.connect(connection_name=settings.sf_connection_name)


class SnowflakePool:
    def __init__(self, size=None):
        self._size = size or settings.pool_size
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._criadas = 0
        self.n_queries = 0

    def _conta_query(self):
        self.n_queries += 1
        job = PROGRESSO_ATUAL.get()
        if job is not None:
            job.concluidos += 1

    def _nova(self):
        sess = ShimSession(_connect(), on_query=self._conta_query)
        return {"sess": sess, "ultimo_uso": time.time()}

    @contextmanager
    def session(self):
        item = None
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._criadas < self._size:
                    self._criadas += 1
                    item = self._nova()
            if item is None:
                item = self._q.get()  # espera devolverem uma
        # Revalida se ficou ociosa
        if time.time() - item["ultimo_uso"] > _PING_IDLE_S:
            try:
                item["sess"].sql("SELECT 1").collect()
            except Exception:
                item["sess"].close()
                item = self._nova()
        try:
            yield item["sess"]
            # Garante que toda query desta sessão terminou antes de devolver
            # a conexão ao pool — sql() dispara com execute_async (ver
            # webapp/db/shim.py), então uma escrita "fire-and-forget" (sem
            # .to_pandas()/.collect() encadeado, ex.: admin_repo.py) ainda
            # não tinha sido confirmada; sem isso o erro dela ficaria mudo e
            # a próxima sessão do pool poderia herdar uma query pendente.
            # Só roda se o `with` body não levantou exceção (nesse caso o
            # `except` abaixo descarta em vez de confirmar, para não
            # mascarar o erro real nem deixar pendente vazando pra próxima
            # sessão do pool).
            item["sess"].confirmar_pendentes()
        except BaseException:
            item["sess"].descartar_pendentes()
            raise
        finally:
            item["ultimo_uso"] = time.time()
            if item["sess"].is_alive():
                self._q.put(item)
            else:
                with self._lock:
                    self._criadas -= 1

    def close(self):
        while True:
            try:
                self._q.get_nowait()["sess"].close()
            except queue.Empty:
                break


_pool = None
_pool_lock = threading.Lock()


def get_pool() -> SnowflakePool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = SnowflakePool()
    return _pool
