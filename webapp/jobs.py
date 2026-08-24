"""Registro em memória dos jobs de fechamento (Fase 6).

Um job roda em thread daemon; o front consulta o estado por polling (htmx
every 2s). `marcar_equipe`/`equipe_ocupada` impedem fechar a mesma
equipe/período duas vezes ao mesmo tempo (o SiS evitava isso só por ser
single-user/single-rerun; aqui precisa de lock explícito).
"""
import threading
import uuid
from dataclasses import dataclass, field


@dataclass
class JobState:
    status: str = "running"  # running | done | error
    total: int = 0
    concluidos: int = 0
    atual: str = ""
    resultado: dict = None
    erro: str = ""
    erros: list = field(default_factory=list)


_lock = threading.Lock()
_jobs = {}
_equipes_ocupadas = set()


def novo_job() -> str:
    return uuid.uuid4().hex[:12]


def get_job(job_id):
    with _lock:
        return _jobs.get(job_id)


def set_job(job_id, state: JobState):
    with _lock:
        _jobs[job_id] = state


def equipe_ocupada(chave) -> bool:
    with _lock:
        return chave in _equipes_ocupadas


def marcar_equipe(chave, ocupada: bool):
    with _lock:
        if ocupada:
            _equipes_ocupadas.add(chave)
        else:
            _equipes_ocupadas.discard(chave)
