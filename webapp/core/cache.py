"""Cache TTL in-process, substituto do st.cache_data do SiS.

Quatro caches nomeados espelham os TTLs do utils/connection.py:
- LIVE (3000s): wrappers de cálculo/composição e contexto por (ano, mes)
- RLS (1800s): consultores/gating por usuário
- SNAP_FID (3000s): roteador período fechado/aberto
- SNAPSHOT (86400s): conteúdo de snapshot (imutável após fechamento)

Invalidação (a convenção substitui os 33 st.cache_data.clear() do SiS por
um ponto único): todo repo de escrita termina em invalidate_after_write();
fechar/reabrir período chama clear_all().

Limitação aceita no plano: cache in-process => uvicorn com 1 worker.
"""
import threading
import time
from functools import wraps

import pandas as pd


class TTLCache:
    def __init__(self, ttl_s: float):
        self.ttl = ttl_s
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key, sentinel=None):
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return sentinel
            expira, valor = item
            if time.time() > expira:
                del self._d[key]
                return sentinel
            return valor

    def set(self, key, valor):
        with self._lock:
            self._d[key] = (time.time() + self.ttl, valor)

    def clear(self):
        with self._lock:
            self._d.clear()


LIVE = TTLCache(3000)
RLS = TTLCache(1800)
SNAP_FID = TTLCache(3000)
SNAPSHOT = TTLCache(86400)

_SENT = object()


def ttl_cached(cache: TTLCache):
    """Decorator com a mesma semântica do _cache_decorator do SiS.

    A chave é (qualname, args); como no st.cache_data, os argumentos devem
    ser hashable (tuplas, não listas). DataFrames voltam como cópia para
    preservar o isolamento que o pickle do st.cache_data dava de graça
    (o código de tela faz d = df.copy() e muta; sem cópia, mutaria o cache).
    """
    def deco(f):
        @wraps(f)
        def wrapper(*args):
            key = (f.__qualname__, args)
            v = cache.get(key, _SENT)
            if v is _SENT:
                v = f(*args)
                cache.set(key, v)
            return v.copy() if isinstance(v, pd.DataFrame) else v
        wrapper.__wrapped__ = f
        return wrapper
    return deco


def invalidate_after_write():
    """Após qualquer escrita administrativa (equivalente aos clear() do SiS)."""
    LIVE.clear()
    RLS.clear()
    SNAP_FID.clear()


def clear_all():
    """Fechar/reabrir período (equivalente ao clear_comissao_cache do SiS)."""
    invalidate_after_write()
    SNAPSHOT.clear()
