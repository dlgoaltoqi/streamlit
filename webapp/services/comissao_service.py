"""Porta de utils/connection.py (camada de dados) para o webapp.

Mesmas assinaturas dos wrappers do SiS — utils/fechamento.py e o front
chamam sem session; a session vem do pool aqui dentro. O roteamento
snapshot/ao vivo é uma cópia fiel de utils/connection.py:205-327.

IMPORTANTE: importe webapp.bootstrap (install_connection_shim) antes de
qualquer import de utils.commission/utils.fechamento no processo.
"""
import json as _json

import pandas as pd

from webapp.core.cache import LIVE, SNAP_FID, SNAPSHOT, ttl_cached
from webapp.db.pool import get_pool

_SNAP = "SUPERSET.COMISSOES"


def _is_xp_err(e) -> bool:
    """True se a exceção é terminação de processo XP do Snowflake
    (cópia de utils/connection.py:20; usada por utils/fechamento.py)."""
    s = str(e).lower()
    return "terminated" in s or "xp process" in s or "termination" in s or "child job" in s


# ── Contexto e cálculo (ao vivo) ─────────────────────────────────────────────

# Sentinela para consultar TTLCache.get sem colidir com valores None
# legítimos (mês sem fechamento cacheia None, por exemplo).
_MISS = object()


def get_contexto_cached(ano: int, mes: int) -> dict:
    return _get_contextos_cached(int(ano), (int(mes),))[int(mes)]


def _get_contextos_cached(ano: int, meses_t: tuple) -> dict:
    """{mes: ctx} com cache POR MÊS, não pelo conjunto pedido: cada consultor
    tem um conjunto próprio de meses abertos no histórico, e cachear pelo
    conjunto refazia o lote inteiro de montar_contextos a cada conjunto
    inédito (19/08/2026: trocar de consultor disparava ~25 queries). Os
    meses que faltam são montados num único lote e semeados um a um, então
    o mês calculado para um consultor serve para todos os outros."""
    ano = int(ano)
    meses = sorted({int(m) for m in meses_t})
    out, faltam = {}, []
    for m in meses:
        v = LIVE.get(("ctx_mes", ano, m), _MISS)
        if v is _MISS:
            faltam.append(m)
        else:
            out[m] = v
    if faltam:
        from utils.commission import montar_contextos
        with get_pool().session() as s:
            novos = montar_contextos(s, ano, faltam)
        for m, ctx in novos.items():
            LIVE.set(("ctx_mes", ano, int(m)), ctx)
            out[int(m)] = ctx
    return out


@ttl_cached(LIVE)
def get_comissao_cached(email: str, ano: int, mes: int) -> dict:
    from utils.commission import calcular_comissao
    ctx = get_contexto_cached(int(ano), int(mes))
    with get_pool().session() as s:
        return calcular_comissao(s, email, int(ano), int(mes), ctx)


@ttl_cached(LIVE)
def get_comissao_hist(email: str, pares: tuple) -> dict:
    """{(ano, mes): dados} para o histórico; fechados via snapshot, abertos
    com UM contexto multi-mês por ano (cópia de utils/connection.py:86-111).
    Fids e conteúdos dos snapshots vêm em lote: 1 query cada, não 1 por mês."""
    pares_i = [(int(a), int(m)) for (a, m) in pares]
    fids = _get_snapshot_fids(email, tuple(pares_i))
    fechados = {p: snap["fid"] for p, snap in fids.items() if snap}
    dados_snap = _get_comissoes_snapshot(tuple(sorted(set(fechados.values()))), email)
    out, vivos = {}, {}
    for (a, m) in pares_i:
        if (a, m) in fechados:
            out[(a, m)] = dados_snap[fechados[(a, m)]]
        else:
            vivos.setdefault(a, []).append(m)
    if vivos:
        from utils.commission import calcular_comissao
        with get_pool().session() as s:
            for a, meses in vivos.items():
                ctxs = _get_contextos_cached(a, tuple(sorted(set(meses))))
                for m in meses:
                    out[(a, m)] = calcular_comissao(s, email, a, m, ctxs[m])
    return out


# ── Composições (ao vivo) ────────────────────────────────────────────────────

@ttl_cached(LIVE)
def get_composicao_cached(email, ano, mes, equipe, is_gestor, is_gd, is_b2g):
    from utils.commission import composicao_realizado
    with get_pool().session() as s:
        return composicao_realizado(s, email, ano, mes, equipe, is_gestor, is_gd, is_b2g)


@ttl_cached(LIVE)
def get_composicao_bk_extra_cached(email, ano, mes, equipe, is_gestor):
    from utils.commission import composicao_booking_extra
    with get_pool().session() as s:
        return composicao_booking_extra(s, email, ano, mes, equipe, is_gestor)


@ttl_cached(LIVE)
def get_composicao_canc_recovery_cached(email, ano, mes):
    from utils.commission import composicao_cancelamentos
    with get_pool().session() as s:
        return composicao_cancelamentos(s, email, ano, mes)


@ttl_cached(LIVE)
def get_composicao_renovacoes_canc_cached(email, ano, mes):
    from utils.commission import composicao_renovacoes_canc
    with get_pool().session() as s:
        return composicao_renovacoes_canc(s, email, ano, mes)


@ttl_cached(LIVE)
def get_carteira_am(email, ano, mes):
    from utils.commission import composicao_carteira_am
    with get_pool().session() as s:
        return composicao_carteira_am(s, email, ano, mes)


@ttl_cached(LIVE)
def get_movim_am(email, ano, mes):
    from utils.commission import composicao_movim_am
    with get_pool().session() as s:
        return composicao_movim_am(s, email, ano, mes)


@ttl_cached(LIVE)
def get_churn_am(email, ano, mes):
    from utils.commission import composicao_churn_am
    with get_pool().session() as s:
        return composicao_churn_am(s, email, ano, mes)


@ttl_cached(LIVE)
def get_renovacoes_am(email, ano, mes):
    from utils.commission import composicao_renovacoes_am
    with get_pool().session() as s:
        return composicao_renovacoes_am(s, email, ano, mes)


@ttl_cached(LIVE)
def get_impulsos_am(email, ano, mes):
    from utils.commission import composicao_impulsos_am
    with get_pool().session() as s:
        return composicao_impulsos_am(s, email, ano, mes)


@ttl_cached(LIVE)
def get_exclusoes_carteira_am(email):
    from utils.commission import composicao_exclusoes_carteira_am
    with get_pool().session() as s:
        return composicao_exclusoes_carteira_am(s, email)


@ttl_cached(LIVE)
def get_ajustes_cached(email, ano, mes):
    from utils.commission import composicao_ajustes
    with get_pool().session() as s:
        return composicao_ajustes(s, email, ano, mes)


@ttl_cached(LIVE)
def get_mrr_recuperado_canc(email: str, ano: int, mes: int) -> float:
    with get_pool().session() as s:
        df = s.sql("""
            SELECT COALESCE(SUM(VALOR_ORIGINAL / NULLIF(DATEDIFF('month', DATA_INICIO, DATA_RENOVACAO), 0)), 0) AS TOTAL_MRR
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS cc
            WHERE ANO = %s AND MES = %s AND LOWER(EMAIL) = %s
              -- Recorte da equipe Cancelamento via IS_CANC_RECOVERY: a tabela ouro
              -- cobre todas as consultoras do pipeline (inclui Saving).
              AND EXISTS (
                  SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS p
                  WHERE p.ANO = cc.ANO AND p.MES = cc.MES
                    AND LOWER(p.EMAIL) = LOWER(cc.EMAIL)
                    AND p.IS_CANC_RECOVERY = TRUE
              )
        """, (int(ano), int(mes), str(email).lower())).to_pandas()
    return float(df.iloc[0]["TOTAL_MRR"]) if not df.empty else 0.0


# ── Roteamento snapshot / ao vivo ────────────────────────────────────────────

def _get_snapshot_fid(ano: int, mes: int, email: str):
    return _get_snapshot_fids(email, ((int(ano), int(mes)),))[(int(ano), int(mes))]


def _get_snapshot_fids(email: str, pares: tuple) -> dict:
    """{(ano, mes): {fid, data} | None} com cache POR PAR em SNAP_FID e uma
    única query para os pares que faltam (o histórico consultava os 6 fids
    um a um, 19/08/2026)."""
    email = str(email).lower()
    out, faltam = {}, []
    for (a, m) in pares:
        a, m = int(a), int(m)
        v = SNAP_FID.get(("snap_fid", a, m, email), _MISS)
        if v is _MISS:
            faltam.append((a, m))
        else:
            out[(a, m)] = v
    if faltam:
        pares_sql = ",".join(f"({a},{m})" for a, m in faltam)
        with get_pool().session() as s:
            df = s.sql(f"""
                SELECT cf.ANO, cf.MES, cf.FECHAMENTO_ID, f.DATA_FECHAMENTO
                FROM {_SNAP}.COMISSOES_FECHADAS cf
                JOIN {_SNAP}.FECHAMENTOS f ON cf.FECHAMENTO_ID = f.FECHAMENTO_ID
                WHERE LOWER(cf.EMAIL) = %s AND f.STATUS = 'ATIVO'
                  AND (cf.ANO, cf.MES) IN ({pares_sql})
                QUALIFY ROW_NUMBER() OVER (PARTITION BY cf.ANO, cf.MES
                                           ORDER BY f.DATA_FECHAMENTO DESC) = 1
            """, (email,)).to_pandas()
        achados = {}
        for _, r in df.iterrows():
            achados[(int(r["ANO"]), int(r["MES"]))] = {
                "fid": str(r["FECHAMENTO_ID"]), "data": r["DATA_FECHAMENTO"]}
        for (a, m) in faltam:
            v = achados.get((a, m))
            SNAP_FID.set(("snap_fid", a, m, email), v)
            out[(a, m)] = v
    return out


def get_snapshot_info(ano: int, mes: int, email: str):
    return _get_snapshot_fid(ano, mes, email)


def _get_comissao_snapshot(fid: str, email: str) -> dict:
    return _get_comissoes_snapshot((str(fid),), email)[str(fid)]


def _get_comissoes_snapshot(fids: tuple, email: str) -> dict:
    """{fid: dados} com cache POR FID em SNAPSHOT e uma única query para os
    que faltam (o histórico lia um snapshot por mês fechado, 19/08/2026)."""
    email = str(email).lower()
    out, faltam = {}, []
    for fid in fids:
        fid = str(fid)
        v = SNAPSHOT.get(("snap_dados", fid, email), _MISS)
        if v is _MISS:
            faltam.append(fid)
        else:
            out[fid] = v
    if faltam:
        marks = ",".join(["%s"] * len(faltam))
        with get_pool().session() as s:
            df = s.sql(f"""
                SELECT FECHAMENTO_ID, DADOS
                FROM {_SNAP}.COMISSOES_FECHADAS
                WHERE FECHAMENTO_ID IN ({marks}) AND LOWER(EMAIL) = %s
            """, (*faltam, email)).to_pandas()
        achados = {}
        for _, r in df.iterrows():
            k = str(r["FECHAMENTO_ID"])
            if k not in achados:
                v = r["DADOS"]
                achados[k] = v if isinstance(v, dict) else _json.loads(str(v))
        for fid in faltam:
            v = achados.get(fid, {"erro": "snapshot não encontrado"})
            SNAPSHOT.set(("snap_dados", fid, email), v)
            out[fid] = v
    return out


@ttl_cached(SNAPSHOT)
def _get_composicao_snapshot(fid: str, email: str, tipo: str) -> pd.DataFrame:
    with get_pool().session() as s:
        df = s.sql(f"""
            SELECT LINHA
            FROM {_SNAP}.COMPOSICAO_FECHADA
            WHERE FECHAMENTO_ID = %s AND LOWER(EMAIL) = %s AND TIPO = %s
            ORDER BY ORDEM
        """, (fid, str(email).lower(), tipo)).to_pandas()
    if df.empty:
        return pd.DataFrame()
    rows = [v if isinstance(v, dict) else _json.loads(str(v)) for v in df["LINHA"]]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_comissao(email: str, ano: int, mes: int) -> dict:
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_comissao_snapshot(snap["fid"], email)
    return get_comissao_cached(email, ano, mes)


def get_composicao(email, ano, mes, equipe, is_gestor, is_gd, is_b2g):
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "GD" if is_gd else "REALIZADO")
    return get_composicao_cached(email, ano, mes, equipe, is_gestor, is_gd, is_b2g)


def get_composicao_bk_extra(email, ano, mes, equipe, is_gestor):
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "BOOKING_EXTRA")
    return get_composicao_bk_extra_cached(email, ano, mes, equipe, is_gestor)


def get_composicao_canc_recovery(email, ano, mes):
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "CANCELAMENTO")
    return get_composicao_canc_recovery_cached(email, ano, mes)


def get_composicao_renovacoes_canc(email, ano, mes):
    """Sempre ao vivo (booking integral), como no SiS."""
    return get_composicao_renovacoes_canc_cached(email, ano, mes)


def get_ajustes(email, ano, mes):
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "AJUSTE")
    return get_ajustes_cached(email, ano, mes)


# ── Chip "Atualizado em" da tela Minha Comissão (porta de
# utils/connection.py:_ultima_atualizacao_*) ─────────────────────────────────

@ttl_cached(LIVE)
def ultima_atualizacao_vendas():
    """Última sincronização da fonte de vendas (usada por quem não é GD/SDR).

    ATUALIZACAO já vem em texto no horário local (BR); NÃO passar por
    CONVERT_TIMEZONE aqui, porque TO_TIMESTAMP produz um TIMESTAMP_NTZ e o
    CONVERT_TIMEZONE de 2 argumentos assume a origem no fuso da SESSÃO
    (não em UTC), deslocando o horário errado (achado em 19/08/2026: virou
    +4h em vez de continuar igual)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT MAX(TO_TIMESTAMP(ATUALIZACAO, 'DD/MM/YYYY HH24:MI:SS')) AS ULT
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
        """).to_pandas()
    v = df.iloc[0]["ULT"]
    return v if pd.notna(v) else None


@ttl_cached(LIVE)
def ultima_atualizacao_captacao():
    """Última atualização da fonte de Opps (GD e SDRs fora do time GD, que têm
    o realizado em Opps via HUBSPOT_REALIZADO_GD em vez de vendas). ATUALIZACAO
    já vem em BRT, no mesmo padrão da tabela de vendas."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT MAX(TO_TIMESTAMP(ATUALIZACAO, 'DD/MM/YYYY HH24:MI:SS')) AS ULT
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD
        """).to_pandas()
    v = df.iloc[0]["ULT"]
    return v if pd.notna(v) else None


@ttl_cached(LIVE)
def _cargo_email(email, ano, mes):
    with get_pool().session() as s:
        df = s.sql("""
            SELECT CARGO FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = %s AND MES = %s AND LOWER(EMAIL) = %s
        """, (ano, mes, str(email).strip().lower())).to_pandas()
    if df.empty or not df.iloc[0]["CARGO"]:
        return ""
    return str(df.iloc[0]["CARGO"])


def ultima_atualizacao_dados(email, ano, mes, equipe):
    """Escolhe a fonte certa (vendas x captação/Opps) pelo mesmo critério de
    utils/commission.py:2073-2075 (is_gd OR cargo contém "sales development")."""
    cargo = _cargo_email(email, ano, mes)
    is_gd_like = (str(equipe or "").strip().lower() == "gd"
                 or "sales development" in cargo.lower())
    return ultima_atualizacao_captacao() if is_gd_like else ultima_atualizacao_vendas()
