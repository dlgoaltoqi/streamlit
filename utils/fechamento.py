"""Fechamento (snapshot) de comissões.

Congela, por (ano, mês, equipe), o resultado por pessoa (o dict de calcular_comissao)
e a composição (realizado/deals, GD, cancelamentos, booking extra, ajustes) nas tabelas
SUPERSET.COMISSOES.FECHAMENTOS / COMISSOES_FECHADAS / COMPOSICAO_FECHADA.

Imutável: refechar gera nova VERSAO e marca a anterior como SUBSTITUIDO.
Vale apenas de abril/2026 em diante.
"""

import json
import pandas as pd

from utils.connection import (
    get_comissao_cached, get_composicao_cached, get_composicao_bk_extra_cached,
    get_composicao_canc_recovery_cached, get_ajustes_cached, _is_xp_err,
)
from utils.commission import _config_mes, _cfg_list

_SCHEMA = "SUPERSET.COMISSOES"
_MIN_ANO, _MIN_MES = 2026, 4
_BATCH = 50  # linhas por INSERT


def _jdefault(o):
    """Serializa tipos que o json não conhece (numpy, Decimal, datas)."""
    try:
        import numpy as _np
        if isinstance(o, _np.integer):
            return int(o)
        if isinstance(o, _np.floating):
            return float(o)
        if isinstance(o, _np.bool_):
            return bool(o)
    except Exception:
        pass
    return str(o)


def _row_json(r):
    d = {}
    for k, v in r.items():
        try:
            if pd.isna(v):
                v = None
        except (TypeError, ValueError):
            pass
        d[str(k)] = v
    return json.dumps(d, default=_jdefault, ensure_ascii=False)


def _consultores(session, ano, mes, equipe):
    """Lista os e-mails da equipe/período (inclui Sonia dentro de Farmer).
    Cancelamento usa PARAMETROS pois essas consultoras não têm meta."""
    if equipe == "Cancelamento":
        df = session.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
            ORDER BY EMAIL
        """).to_pandas()
        return df["EMAIL"].tolist() if not df.empty else []
    if equipe == "PVT":
        df = session.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_PVT = TRUE
              AND COALESCE(IS_GESTOR, FALSE) = FALSE
            ORDER BY EMAIL
        """).to_pandas()
        return df["EMAIL"].tolist() if not df.empty else []
    # Equipes do METAS varridas p/ esta equipe (config equipes_fechamento.<equipe>)
    _cfgx = _config_mes(session, ano, mes)
    if _cfgx.get("config_ok"):
        eqs = _cfg_list(_cfgx, f"equipes_fechamento.{equipe}", None) or [equipe]
    else:
        eqs = ["Farmer", "Sonia"] if equipe == "Farmer" else [equipe]
    ein = ", ".join("'" + str(e).replace("'", "''") + "'" for e in eqs)
    filt = f"AND EQUIPE IN ({ein})"
    df = session.sql(f"""
        SELECT DISTINCT LOWER(CONSULTOR) AS EMAIL
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} {filt} AND CONSULTOR IS NOT NULL
        ORDER BY EMAIL
    """).to_pandas()
    return df["EMAIL"].tolist() if not df.empty else []


def periodo_fechado(session, ano, mes, equipe):
    """Retorna o FECHAMENTO_ID ativo para (ano, mês, equipe), ou None."""
    eq = equipe.replace("'", "''")
    df = session.sql(f"""
        SELECT FECHAMENTO_ID, VERSAO, DATA_FECHAMENTO
        FROM {_SCHEMA}.FECHAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{eq}' AND STATUS = 'ATIVO'
        ORDER BY VERSAO DESC LIMIT 1
    """).to_pandas()
    if df.empty:
        return None
    return {
        "fechamento_id": str(df.iloc[0]["FECHAMENTO_ID"]),
        "versao": int(df.iloc[0]["VERSAO"]),
        "data": df.iloc[0]["DATA_FECHAMENTO"],
    }


def _sql_val(v, is_json=False):
    """Formata um valor Python como literal SQL Snowflake."""
    if v is None:
        return "NULL"
    if is_json:
        return "PARSE_JSON('" + str(v).replace("'", "''") + "')"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _insert_batch(session, tabela, col_names, rows, json_cols=()):
    """INSERT puro em lotes — não usa save_as_table (evita CREATE TABLE no schema)."""
    if not rows:
        return
    json_set = set(json_cols)
    cols_sql = ", ".join(col_names)
    for start in range(0, len(rows), _BATCH):
        batch = rows[start:start + _BATCH]
        selects = [
            "SELECT " + ", ".join(
                _sql_val(v, is_json=(col_names[i] in json_set))
                for i, v in enumerate(row)
            )
            for row in batch
        ]
        session.sql(
            f"INSERT INTO {_SCHEMA}.{tabela} ({cols_sql})\n"
            + "\nUNION ALL\n".join(selects)
        ).collect()


def fechar_consultores(session, ano, mes, equipe):
    """Lista os e-mails a fechar — wrapper público de _consultores."""
    return _consultores(session, ano, mes, equipe)


def reabrir_fechamento(session, equipe, ano, mes):
    """Reverte o snapshot ativo para REABERTO, liberando cálculo ao vivo.
    Retorna True se havia snapshot ativo e foi reaberto."""
    eq = equipe.replace("'", "''")
    session.sql(
        f"UPDATE {_SCHEMA}.FECHAMENTOS SET STATUS = 'REABERTO' "
        f"WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{eq}' AND STATUS = 'ATIVO'"
    ).collect()


def fechar_um(email, ano, mes, equipe):
    """Calcula a comissão de uma pessoa.
    Retorna (res_row, comp_rows, erro_bool).
    Re-levanta erros de XP para permitir retry pelo chamador."""
    try:
        dados = get_comissao_cached(email, ano, mes)
    except Exception as e:
        if _is_xp_err(e):
            raise
        return None, [], True
    if not isinstance(dados, dict) or "erro" in dados:
        return None, [], True

    is_gestor = bool(dados.get("is_gestor"))
    is_gd     = bool(dados.get("is_gd"))
    is_b2g    = bool(dados.get("is_b2g"))
    is_canc   = bool(dados.get("is_canc_recovery"))
    eq_pessoa = dados.get("equipe", "") or equipe

    res_row = [
        email, dados.get("cargo"), float(dados.get("total") or 0),
        json.dumps(dados, default=_jdefault, ensure_ascii=False),
    ]
    comp_rows_pessoa = []

    def _add(dfc, tipo):
        if dfc is not None and not getattr(dfc, "empty", True):
            for i, (_, r) in enumerate(dfc.iterrows()):
                comp_rows_pessoa.append([email, tipo, i, _row_json(r.to_dict())])

    try:
        if is_canc:
            _add(get_composicao_canc_recovery_cached(email, ano, mes), "CANCELAMENTO")
        else:
            _add(get_composicao_cached(email, ano, mes, eq_pessoa, is_gestor, is_gd, is_b2g),
                 "GD" if is_gd else "REALIZADO")
            _add(get_composicao_bk_extra_cached(email, ano, mes, eq_pessoa, is_gestor),
                 "BOOKING_EXTRA")
        _add(get_ajustes_cached(email, ano, mes), "AJUSTE")
    except Exception as e:
        if _is_xp_err(e):
            raise
        # composição é opcional; não derruba o resultado

    return res_row, comp_rows_pessoa, False


def fechar_inserir(session, ano, mes, equipe, usuario, res_rows, comp_rows):
    """Grava o snapshot no Snowflake. Retorna resumo (sem campo 'erros')."""
    if not res_rows:
        raise ValueError(f"Nenhuma comissão calculada para '{equipe}' em {mes:02d}/{ano}.")

    # ── Versão + travar a anterior ────────────────────────────────────────────
    eq_esc = equipe.replace("'", "''")
    mx = session.sql(
        f"SELECT COALESCE(MAX(VERSAO), 0) AS V FROM {_SCHEMA}.FECHAMENTOS "
        f"WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{eq_esc}'"
    ).collect()
    versao = int(mx[0]["V"]) + 1
    fid = f"{ano}-{mes:02d}-{equipe}-v{versao}"
    if versao > 1:
        session.sql(
            f"UPDATE {_SCHEMA}.FECHAMENTOS SET STATUS = 'SUBSTITUIDO' "
            f"WHERE ANO = {ano} AND MES = {mes} AND EQUIPE = '{eq_esc}' "
            f"AND STATUS IN ('ATIVO', 'REABERTO')"
        ).collect()

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    user_esc = (usuario or "").replace("'", "''")
    fid_esc  = fid.replace("'", "''")
    session.sql(f"""
        INSERT INTO {_SCHEMA}.FECHAMENTOS
            (FECHAMENTO_ID, ANO, MES, EQUIPE, VERSAO, STATUS, DATA_FECHAMENTO, USUARIO, N_PESSOAS, OBS)
        SELECT '{fid_esc}', {ano}, {mes}, '{eq_esc}', {versao}, 'ATIVO',
               CURRENT_TIMESTAMP(), '{user_esc}', {len(res_rows)}, NULL
    """).collect()

    # ── Resultado por pessoa ──────────────────────────────────────────────────
    cols_res = ["FECHAMENTO_ID", "ANO", "MES", "EQUIPE", "EMAIL", "CARGO", "TOTAL", "DADOS", "DATA_FECHAMENTO"]
    json_res = {"DADOS"}
    selects_res = []
    for r in res_rows:
        row = [fid, int(ano), int(mes), equipe, r[0], r[1], r[2], r[3]]
        parts = [_sql_val(v, is_json=(cols_res[i] in json_res)) for i, v in enumerate(row)]
        parts.append("CURRENT_TIMESTAMP()")
        selects_res.append("SELECT " + ", ".join(parts))
    cols_sql = ", ".join(cols_res)
    for start in range(0, len(selects_res), _BATCH):
        batch = selects_res[start:start + _BATCH]
        session.sql(
            f"INSERT INTO {_SCHEMA}.COMISSOES_FECHADAS ({cols_sql})\n"
            + "\nUNION ALL\n".join(batch)
        ).collect()

    # ── Composição ────────────────────────────────────────────────────────────
    if comp_rows:
        cols_comp = ["FECHAMENTO_ID", "ANO", "MES", "EQUIPE", "EMAIL", "TIPO", "ORDEM", "LINHA"]
        comp_full = [
            [fid, int(ano), int(mes), equipe, c[0], c[1], int(c[2]), c[3]]
            for c in comp_rows
        ]
        _insert_batch(session, "COMPOSICAO_FECHADA", cols_comp, comp_full, json_cols=("LINHA",))

    return {
        "fechamento_id": fid,
        "versao": versao,
        "n_pessoas": len(res_rows),
        "n_composicao": len(comp_rows),
    }


def fechar_comissao(session, ano, mes, equipe, usuario):
    """Calcula e grava o snapshot de (ano, mês, equipe). Retorna resumo."""
    if (int(ano), int(mes)) < (_MIN_ANO, _MIN_MES):
        raise ValueError("Fechamento disponível apenas a partir de abril/2026.")

    emails = fechar_consultores(session, ano, mes, equipe)
    if not emails:
        raise ValueError(f"Nenhum consultor em '{equipe}' para {mes:02d}/{ano}.")

    res_rows, comp_rows, erros = [], [], []
    for email in emails:
        res_row, comp_r, erro = fechar_um(email, ano, mes, equipe)
        if erro:
            erros.append(email)
        else:
            res_rows.append(res_row)
            comp_rows.extend(comp_r)

    result = fechar_inserir(session, ano, mes, equipe, usuario, res_rows, comp_rows)
    result["erros"] = erros
    return result
