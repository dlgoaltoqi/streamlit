"""Fechamento/reabertura de período — porta de pages/20_Admin_Exportar_Comissoes.py.

utils/fechamento.py NÃO é editado: fechar_consultores/fechar_um/fechar_inserir/
periodo_fechado/reabrir_fechamento vêm de lá sem alteração, satisfeitas pelo
shim do bootstrap (get_comissao_cached etc.). fechar_um só LÊ (cache), então
paralelizamos aqui (melhoria sobre o loop sequencial de reruns do SiS); só
fechar_inserir grava, uma vez, no fim — igual ao SiS.

Duas trancas: settings.writes_enabled (front nem mostra os botões sem ela) e
o lock em jobs.py contra fechar a mesma equipe/período duas vezes ao mesmo
tempo. WRITES_TARGET=clone NÃO se aplica aqui (o gate de escrita da Fase 5
cobriu as tabelas administrativas; fechamento continua sendo testado com
refechamento + diff, não em clone, porque a leitura ao vivo já depende de
dezenas de tabelas reais via montar_contexto).
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from utils.fechamento import (fechar_consultores, fechar_inserir, fechar_um,
                              periodo_fechado, reabrir_fechamento)
from webapp.core.cache import clear_all
from webapp.db.pool import get_pool
from webapp.jobs import JobState, equipe_ocupada, get_job, marcar_equipe, novo_job, set_job
from webapp.views import pvt_view

_MAX_WORKERS = 6


def chave_equipe(ano, mes, equipe):
    return (int(ano), int(mes), equipe)


def status_periodo(ano, mes, equipe):
    """None se aberto, ou {fechamento_id, versao, data} se há snapshot ATIVO."""
    with get_pool().session() as s:
        return periodo_fechado(s, ano, mes, equipe)


def _fechar_pvt(ano, mes, usuario):
    """PVT é comissão de EQUIPE (não por pessoa), só paga no fim do
    trimestre — porta de pages/20:128-260, reaproveitando os loaders já
    cacheados e testados de webapp/views/pvt_view.py."""
    q = (mes - 1) // 3 + 1
    trim = f"Q{q}"
    mi = pvt_view._meses_in(trim)
    df_nr = pvt_view._load_nmrr_real(ano, mi).copy()
    df_or = pvt_view._load_otr_real(ano, mi).copy()
    df_nm = pvt_view._load_nmrr_meta(ano, mi).copy()
    df_om = pvt_view._load_otr_meta(ano, mi).copy()
    df_ov = pvt_view._load_overrides(ano, mi)
    df_nr, df_nm, df_or, df_om = pvt_view._aplicar_overrides(df_nr, df_nm, df_or, df_om, df_ov)

    meta_nmrr = float(df_nm["VALOR"].sum()) if not df_nm.empty else 0.0
    real_nmrr = float(df_nr["VALOR"].sum()) if not df_nr.empty else 0.0
    meta_otr = float(df_om["VALOR"].sum()) if not df_om.empty else 0.0
    real_otr = float(df_or["VALOR"].sum()) if not df_or.empty else 0.0
    pct_nmrr = real_nmrr / meta_nmrr if meta_nmrr > 0 else 0.0
    pct_otr = real_otr / meta_otr if meta_otr > 0 else 0.0
    pct_pond = pct_nmrr * pvt_view.POND_NMRR + pct_otr * pvt_view.POND_OTR

    if pct_pond < pvt_view.CLIFF_GERAL:
        acel = 0.0
    elif pct_pond < pvt_view.MULT_115_CLIFF:
        acel = 1.00
    elif pct_pond < pvt_view.MULT_125_CLIFF:
        acel = 1.15
    else:
        acel = 1.25
    ote_aj = pvt_view.OTE_BASE * acel
    # Regra de negócio: PVT só é pago no fechamento do último mês do trimestre.
    total = ote_aj * pct_pond if mes in (3, 6, 9, 12) else 0.0

    with get_pool().session() as s:
        emails = fechar_consultores(s, ano, mes, "PVT")
    if not emails:
        raise ValueError(f"Nenhum consultor em 'PVT' para {mes:02d}/{ano}.")

    res_rows = []
    for email in emails:
        linha = {
            "Ano": ano, "Mês": mes, "Email": email, "Equipe": "PVT", "Cargo": "PVT",
            "Total": total, "OTE Base": pvt_view.OTE_BASE, "Acelerador OTE": acel,
            "OTE Ajustado": ote_aj, "% NMRR": pct_nmrr, "Meta NMRR": meta_nmrr,
            "Real NMRR": real_nmrr, "% Booking": pct_otr, "Meta Booking": meta_otr,
            "Real Booking": real_otr, "% Atingimento Pond.": pct_pond,
        }
        res_rows.append([email, "PVT", total, json.dumps(linha, default=str)])

    with get_pool().session() as s:
        return fechar_inserir(s, ano, mes, "PVT", usuario, res_rows, [])


def iniciar_fechamento(ano: int, mes: int, equipe: str, usuario: str) -> str:
    """Dispara o fechamento em thread e devolve o job_id para polling."""
    chave = chave_equipe(ano, mes, equipe)
    if equipe_ocupada(chave):
        raise RuntimeError("Já existe um fechamento em andamento para esta equipe/período.")

    job_id = novo_job()
    set_job(job_id, JobState(status="running", atual="Iniciando…"))
    marcar_equipe(chave, True)

    def _run():
        try:
            # Mesmo gesto do SiS: limpar tudo ANTES de calcular, para não
            # fechar com valores possivelmente defasados do cache.
            clear_all()
            if equipe == "PVT":
                set_job(job_id, JobState(status="running", total=1, atual="Calculando PVT…"))
                r = _fechar_pvt(ano, mes, usuario)
            else:
                with get_pool().session() as s:
                    emails = fechar_consultores(s, ano, mes, equipe)
                if not emails:
                    raise ValueError(f"Nenhum consultor em '{equipe}' para {mes:02d}/{ano}.")
                total = len(emails)
                set_job(job_id, JobState(status="running", total=total, atual="Calculando…"))

                lock = threading.Lock()
                res_rows, comp_rows, erros = [], [], []
                concluidos = 0

                def _um(email):
                    nonlocal concluidos
                    try:
                        rr, cr, err = fechar_um(email, ano, mes, equipe)
                    except Exception:
                        rr, cr, err = None, [], True
                    with lock:
                        if err:
                            erros.append(email)
                        else:
                            res_rows.append(rr)
                            comp_rows.extend(cr)
                        concluidos += 1
                        set_job(job_id, JobState(status="running", total=total,
                                                 concluidos=concluidos, atual=email))

                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
                    list(ex.map(_um, emails))

                set_job(job_id, JobState(status="running", total=total,
                                         concluidos=total, atual="Gravando snapshot…"))
                with get_pool().session() as s:
                    r = fechar_inserir(s, ano, mes, equipe, usuario, res_rows, comp_rows)
                r["erros"] = erros

            clear_all()
            set_job(job_id, JobState(status="done", total=r.get("n_pessoas", 1),
                                     concluidos=r.get("n_pessoas", 1), resultado=r,
                                     erros=r.get("erros", [])))
        except Exception as e:
            set_job(job_id, JobState(status="error", erro=str(e)))
        finally:
            marcar_equipe(chave, False)

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def reabrir(ano: int, mes: int, equipe: str):
    with get_pool().session() as s:
        reabrir_fechamento(s, equipe, ano, mes)
    clear_all()
