from snowflake.snowpark.context import get_active_session
import streamlit as st
import pandas as pd
import json as _json
import datetime as _dt


def get_session():
    return get_active_session()


def compat_rerun():
    """st.rerun() foi adicionado no Streamlit 1.27; SiS usa versão anterior."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _is_xp_err(e) -> bool:
    """True se a exceção é terminação de processo XP do Snowflake."""
    s = str(e).lower()
    return "terminated" in s or "xp process" in s or "termination" in s or "child job" in s


def compat_divider():
    st.markdown(
        "<hr style='margin:12px 0;border:none;border-top:1px solid #9ca3af;'>",
        unsafe_allow_html=True,
    )


def hide_stale_on_change(state_key: str, valor):
    """Ao detectar mudança de `valor` entre reruns (troca de página ou de
    filtro), esconde NA HORA os elementos do rerun anterior (fantasmas), só
    neste rerun. Sem mudança, vale o esmaecimento atrasado do CSS persistente.

    SEMPRE renderiza um bloco <style> (neutro quando não há troca): no
    Streamlit 1.22 a identidade dos elementos é posicional, então um elemento
    condicional no topo deslocaria todos os seguintes; e o bloco neutro
    substitui o de esconder logo no início do rerun seguinte (senão o
    opacity:0 vazaria para interações comuns até ser trocado)."""
    mudou = st.session_state.get(state_key) not in (None, valor)
    st.session_state[state_key] = valor
    if mudou:
        # O banner e imune por construcao: e ::before do block-container.
        _css = ("div[data-stale='true'],.stale-element"
                "{opacity:0 !important;transition:none !important;}")
    else:
        _css = "/* sem troca de pagina/filtro neste rerun */"
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)


def _cache_decorator(ttl=300):
    if hasattr(st, "cache_data"):
        return st.cache_data(ttl=ttl)
    elif hasattr(st, "experimental_memo"):
        return st.experimental_memo(ttl=ttl)
    return lambda f: f


@_cache_decorator(ttl=3000)
def get_contexto_cached(ano: int, mes: int) -> dict:
    """Contexto em lote (montar_contexto) — 1x por (ano, mes), TTL 50 minutos.
    Compartilhado por todas as pessoas do mês: Minha Equipe/Exportar/fechamento
    pagam as queries uma vez por mês em vez de uma vez por pessoa."""
    from utils.commission import montar_contexto
    return montar_contexto(get_active_session(), ano, mes)


@_cache_decorator(ttl=3000)
def get_comissao_cached(email: str, ano: int, mes: int) -> dict:
    """Cached wrapper para calcular_comissao — TTL 50 minutos."""
    from utils.commission import calcular_comissao
    return calcular_comissao(get_active_session(), email, ano, mes,
                             get_contexto_cached(ano, mes))


@_cache_decorator(ttl=3000)
def _get_contextos_cached(ano: int, meses_t: tuple) -> dict:
    """Contextos de vários meses do mesmo ano numa única passada (montar_contextos)."""
    from utils.commission import montar_contextos
    return montar_contextos(get_active_session(), ano, list(meses_t))


@_cache_decorator(ttl=3000)
def get_comissao_hist(email: str, pares) -> dict:
    """{(ano, mes): dados} para meses do histórico. `pares` deve ser tupla.

    Meses fechados vêm do snapshot; os abertos são calculados com UM contexto
    em lote multi-mês por ano (~15 queries no total, não por mês).

    O resultado final é cacheado (14/08/2026): sem isso, o expander de
    histórico refazia a cada rerun a desserialização do contexto multi-mês
    (objeto grande) e o recálculo dos meses abertos, mesmo com o expander
    fechado — era o maior custo Python por interação na Minha Comissão."""
    out, vivos = {}, {}
    for (a, m) in pares:
        snap = _get_snapshot_fid(a, m, email)
        if snap:
            out[(a, m)] = _get_comissao_snapshot(snap["fid"], email)
        else:
            vivos.setdefault(int(a), []).append(int(m))
    if vivos:
        from utils.commission import calcular_comissao
        session = get_active_session()
        for a, meses in vivos.items():
            ctxs = _get_contextos_cached(a, tuple(sorted(set(meses))))
            for m in meses:
                out[(a, m)] = calcular_comissao(session, email, a, m, ctxs[m])
    return out


@_cache_decorator(ttl=3000)
def get_composicao_cached(email, ano, mes, equipe, is_gestor, is_gd, is_b2g):
    """Cached wrapper para composicao_realizado (negocios que compoem o realizado)."""
    from utils.commission import composicao_realizado
    return composicao_realizado(get_active_session(), email, ano, mes, equipe, is_gestor, is_gd, is_b2g)


@_cache_decorator(ttl=3000)
def get_composicao_bk_extra_cached(email, ano, mes, equipe, is_gestor):
    """Cached wrapper para composicao_booking_extra."""
    from utils.commission import composicao_booking_extra
    return composicao_booking_extra(get_active_session(), email, ano, mes, equipe, is_gestor)


@_cache_decorator(ttl=3000)
def get_composicao_canc_recovery_cached(email, ano, mes):
    """Cached wrapper para composicao_cancelamentos."""
    from utils.commission import composicao_cancelamentos
    return composicao_cancelamentos(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_composicao_renovacoes_canc_cached(email, ano, mes):
    """Cached wrapper para composicao_renovacoes_canc."""
    from utils.commission import composicao_renovacoes_canc
    return composicao_renovacoes_canc(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_carteira_am(email, ano, mes):
    """Cached wrapper para composicao_carteira_am (contratos do MRR inicial)."""
    from utils.commission import composicao_carteira_am
    return composicao_carteira_am(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_movim_am(email, ano, mes):
    """Cached wrapper para composicao_movim_am (upsells do mês)."""
    from utils.commission import composicao_movim_am
    return composicao_movim_am(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_churn_am(email, ano, mes):
    """Cached wrapper para composicao_churn_am (clientes vencidos sem renovar)."""
    from utils.commission import composicao_churn_am
    return composicao_churn_am(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_renovacoes_am(email, ano, mes):
    """Cached wrapper para as substituições de contrato das renovações AM."""
    from utils.commission import composicao_renovacoes_am
    return composicao_renovacoes_am(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_impulsos_am(email, ano, mes):
    """Cached wrapper para os impulsos que consolidam contratos da carteira."""
    from utils.commission import composicao_impulsos_am
    return composicao_impulsos_am(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_exclusoes_carteira_am(email):
    """Exclusoes administrativas da carteira atribuida a uma AM."""
    from utils.commission import composicao_exclusoes_carteira_am
    return composicao_exclusoes_carteira_am(get_active_session(), email)


@_cache_decorator(ttl=3000)
def get_ajustes_cached(email, ano, mes):
    """Cached wrapper para composicao_ajustes."""
    from utils.commission import composicao_ajustes
    return composicao_ajustes(get_active_session(), email, ano, mes)


@_cache_decorator(ttl=3000)
def get_mrr_recuperado_canc(email: str, ano: int, mes: int) -> float:
    """MRR recuperado das consultoras de cancelamento (fallback de exibicao
    quando o dict de comissao nao traz mrr_recuperado, ex.: snapshots antigos)."""
    session = get_active_session()
    em = email.lower().replace("'", "''")
    df = session.sql(f"""
        SELECT COALESCE(SUM(VALOR_ORIGINAL / NULLIF(DATEDIFF('month', DATA_INICIO, DATA_RENOVACAO), 0)), 0) AS TOTAL_MRR
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_CONSULTA_CANCELAMENTOS_SALVOS cc
        WHERE ANO = {int(ano)} AND MES = {int(mes)} AND LOWER(EMAIL) = '{em}'
          -- Recorte da equipe Cancelamento via IS_CANC_RECOVERY: a tabela ouro
          -- cobre todas as consultoras do pipeline (inclui Saving).
          AND EXISTS (
              SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS p
              WHERE p.ANO = cc.ANO AND p.MES = cc.MES
                AND LOWER(p.EMAIL) = LOWER(cc.EMAIL)
                AND p.IS_CANC_RECOVERY = TRUE
          )
    """).to_pandas()
    return float(df.iloc[0]["TOTAL_MRR"]) if not df.empty else 0.0


# ── Roteamento snapshot / ao vivo ──────────────────────────────────────────────
# Período fechado → lê das tabelas de snapshot (imutável).
# Período aberto  → calcula ao vivo via as funções _cached acima.
# fechamento.py usa as funções _cached diretamente (precisa do dado vivo para gravar).

_SNAP = "SUPERSET.COMISSOES"


@_cache_decorator(ttl=3000)
def _get_snapshot_fid(ano: int, mes: int, email: str):
    """Dict {fid, data} se período fechado, ou None se aberto.

    TTL longo é seguro: fechar e reabrir período limpam o cache global
    (clear_comissao_cache na página Exportar Comissões). Com TTL curto, a
    Minha Equipe pagava 1 query POR MEMBRO a cada expiração (14/08/2026)."""
    session = get_active_session()
    em = email.lower().replace("'", "''")
    df = session.sql(f"""
        SELECT cf.FECHAMENTO_ID, f.DATA_FECHAMENTO
        FROM {_SNAP}.COMISSOES_FECHADAS cf
        JOIN {_SNAP}.FECHAMENTOS f ON cf.FECHAMENTO_ID = f.FECHAMENTO_ID
        WHERE cf.ANO = {ano} AND cf.MES = {mes}
          AND LOWER(cf.EMAIL) = '{em}'
          AND f.STATUS = 'ATIVO'
        ORDER BY f.DATA_FECHAMENTO DESC
        LIMIT 1
    """).to_pandas()
    if df.empty:
        return None
    return {"fid": str(df.iloc[0]["FECHAMENTO_ID"]), "data": df.iloc[0]["DATA_FECHAMENTO"]}


def get_snapshot_info(ano: int, mes: int, email: str):
    """Expõe _get_snapshot_fid para páginas exibirem badge de período fechado."""
    return _get_snapshot_fid(ano, mes, email)


@_cache_decorator(ttl=86400)
def _get_comissao_snapshot(fid: str, email: str) -> dict:
    """Lê resultado de comissão do snapshot (imutável após fechamento)."""
    session = get_active_session()
    em = email.lower().replace("'", "''")
    fid_esc = fid.replace("'", "''")
    df = session.sql(f"""
        SELECT DADOS
        FROM {_SNAP}.COMISSOES_FECHADAS
        WHERE FECHAMENTO_ID = '{fid_esc}'
          AND LOWER(EMAIL) = '{em}'
        LIMIT 1
    """).to_pandas()
    if df.empty:
        return {"erro": "snapshot não encontrado"}
    v = df.iloc[0]["DADOS"]
    return v if isinstance(v, dict) else _json.loads(str(v))


@_cache_decorator(ttl=86400)
def _get_composicao_snapshot(fid: str, email: str, tipo: str) -> pd.DataFrame:
    """Lê composição do snapshot para o tipo dado (REALIZADO/GD/BOOKING_EXTRA/AJUSTE/CANCELAMENTO)."""
    session = get_active_session()
    em = email.lower().replace("'", "''")
    fid_esc = fid.replace("'", "''")
    tipo_esc = tipo.replace("'", "''")
    df = session.sql(f"""
        SELECT LINHA
        FROM {_SNAP}.COMPOSICAO_FECHADA
        WHERE FECHAMENTO_ID = '{fid_esc}'
          AND LOWER(EMAIL) = '{em}'
          AND TIPO = '{tipo_esc}'
        ORDER BY ORDEM
    """).to_pandas()
    if df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        v = r["LINHA"]
        rows.append(v if isinstance(v, dict) else _json.loads(str(v)))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_comissao(email: str, ano: int, mes: int) -> dict:
    """Retorna snapshot se período fechado, senão calcula ao vivo."""
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_comissao_snapshot(snap["fid"], email)
    return get_comissao_cached(email, ano, mes)


def get_composicao(email, ano, mes, equipe, is_gestor, is_gd, is_b2g):
    """Composição principal: snapshot ou ao vivo."""
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "GD" if is_gd else "REALIZADO")
    return get_composicao_cached(email, ano, mes, equipe, is_gestor, is_gd, is_b2g)


def get_composicao_bk_extra(email, ano, mes, equipe, is_gestor):
    """Booking extra: snapshot ou ao vivo."""
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "BOOKING_EXTRA")
    return get_composicao_bk_extra_cached(email, ano, mes, equipe, is_gestor)


def get_composicao_canc_recovery(email, ano, mes):
    """Cancelamentos/recuperação: snapshot ou ao vivo."""
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "CANCELAMENTO")
    return get_composicao_canc_recovery_cached(email, ano, mes)


def get_composicao_renovacoes_canc(email, ano, mes):
    """Renovações das consultoras de cancelamento: sempre ao vivo (booking integral)."""
    return get_composicao_renovacoes_canc_cached(email, ano, mes)


def get_ajustes(email, ano, mes):
    """Ajustes: snapshot ou ao vivo."""
    snap = _get_snapshot_fid(ano, mes, email)
    if snap:
        return _get_composicao_snapshot(snap["fid"], email, "AJUSTE")
    return get_ajustes_cached(email, ano, mes)


_MESES_ABREV = {
    1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
    7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez",
}

# Dicionarios publicos de meses — fonte unica para todas as paginas
# (antes cada pagina redefinia o seu; 17 copias removidas em 13/08/2026).
MESES_ABREV = _MESES_ABREV
MESES_NOME = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",    6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro",10: "Outubro",  11: "Novembro", 12: "Dezembro",
}

# O painel de comissões vale de abril/2026 em diante — fonte única do período.
_MIN_ANO_PAINEL, _MIN_MES_PAINEL = 2026, 4


def _hoje_brt():
    """Data atual no fuso de Brasília (UTC-3; o SiS roda em UTC)."""
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=3)).date()


def ano_atual():
    return _hoje_brt().year


def mes_atual():
    return _hoje_brt().month


def periodo_anos():
    """Anos selecionáveis nos filtros principais: 2026 até o ano corrente."""
    return list(range(_MIN_ANO_PAINEL, max(ano_atual(), _MIN_ANO_PAINEL) + 1))


def periodo_meses(ano):
    """Meses selecionáveis do ano: Abr-Dez em 2026, Jan-Dez nos seguintes."""
    return [m for m in _MESES_ABREV
            if (int(ano), m) >= (_MIN_ANO_PAINEL, _MIN_MES_PAINEL)]


def _periodo_default():
    """(ano, mes) default dos filtros: período atual, nunca antes de abr/2026."""
    a, m = ano_atual(), mes_atual()
    if (a, m) < (_MIN_ANO_PAINEL, _MIN_MES_PAINEL):
        return _MIN_ANO_PAINEL, _MIN_MES_PAINEL
    return a, m


def _safe_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _qp_get():
    """Le query params da URL como dict simples (compat entre versoes do Streamlit)."""
    try:
        return {k: (v if isinstance(v, str) else (v[0] if v else "")) for k, v in st.query_params.items()}
    except Exception:
        try:
            qp = st.experimental_get_query_params()
            return {k: (v[0] if isinstance(v, list) and v else v) for k, v in qp.items()}
        except Exception:
            return {}


def _qp_set(**kwargs):
    """Grava filtros na URL (persistem apos reset de sessao). So escreve se mudou."""
    cur = _qp_get()
    novo = {k: str(v) for k, v in kwargs.items() if v not in (None, "")}
    if all(cur.get(k) == val for k, val in novo.items()):
        return
    try:
        for k, val in novo.items():
            st.query_params[k] = val
    except Exception:
        try:
            merged = dict(cur)
            merged.update(novo)
            st.experimental_set_query_params(**merged)
        except Exception:
            pass

def render_period_filter():
    """Renderiza seletores de Ano/Mes. Mudancas aplicam imediatamente."""
    qp = _qp_get()
    anos = periodo_anos()
    ano_atu, mes_atu = _periodo_default()
    ano_def = _safe_int(qp.get("ano"), int(st.session_state.get("ano", ano_atu)))
    if ano_def not in anos:
        ano_def = ano_atu
    mes_def = _safe_int(qp.get("mes"), int(st.session_state.get("mes", mes_atu)))
    _sfx = st.session_state.get("_tab_key_", "")
    _key_ano = f"_pf_ano_{_sfx}"
    _key_mes = f"_pf_mes_{_sfx}"

    if _key_ano not in st.session_state or st.session_state[_key_ano] not in anos:
        st.session_state[_key_ano] = ano_def
    meses = periodo_meses(st.session_state[_key_ano])
    if _key_mes not in st.session_state or st.session_state[_key_mes] not in meses:
        _cm = mes_def if mes_def in meses else (mes_atu if mes_atu in meses else meses[-1])
        st.session_state[_key_mes] = _cm

    col1, col2 = st.columns([1, 2])
    col1.selectbox("Ano", anos, key=_key_ano)
    meses2 = periodo_meses(st.session_state[_key_ano])
    if st.session_state[_key_mes] not in meses2:
        st.session_state[_key_mes] = meses2[-1]
    col2.selectbox("Mês", meses2, key=_key_mes, format_func=lambda x: _MESES_ABREV[x])

    ano = st.session_state[_key_ano]
    mes = st.session_state[_key_mes]
    st.session_state["ano"] = ano
    st.session_state["mes"] = mes
    _qp_set(ano=ano, mes=mes)
    hide_stale_on_change(f"_pf_prev_{_sfx}", (ano, mes))
    return ano, mes


# Admins explicitos (acesso total). Garante acesso de partida e evita lockout.
# Para adicionar/remover admins, edite esta lista e faca deploy.
# Inclui tanto o e-mail quanto o login do Snowflake (fallback caso a resolucao
# de e-mail via ACCOUNT_USAGE falhe).
ADMIN_EMAILS = {
    "higor.nocetti@altoqi.com.br",
    "higornocetti",
}


def _is_admin(user):
    return (user or "").strip().lower() in ADMIN_EMAILS


def current_email(session):
    """Resolve o e-mail do usuario logado: CURRENT_USER() (login do Snowflake)
    -> SHOW USERS (real-time) -> ACCOUNT_USAGE.USERS (fallback, ate 2h latencia).
    Cacheia na sessao.

    Necessario porque CURRENT_USER() retorna o login (ex: HIGORNOCETTI), mas
    PERMISSAO_RLS e ADMIN_EMAILS usam e-mail (higor.nocetti@altoqi.com.br).
    """
    view_as = st.session_state.get("_view_as_email_")
    if view_as and _is_admin(st.session_state.get("_real_user_email_", "")):
        return str(view_as).strip().lower()
    cached = st.session_state.get("_user_email_")
    if cached:
        return cached
    # No SiS (owner's rights), CURRENT_USER()/get_current_user() vem NULL.
    # A fonte confiavel do usuario visualizando e st.experimental_user.user_name.
    login = ""
    try:
        eu = getattr(st, "experimental_user", None)
        if eu is not None:
            login = getattr(eu, "user_name", None) or ""
    except Exception:
        pass
    if not login:
        try:
            udf = session.sql("SELECT CURRENT_USER() AS U").to_pandas()
            if not udf.empty and udf.iloc[0]["U"]:
                login = str(udf.iloc[0]["U"])
        except Exception:
            pass
    if not login:
        login = session.get_current_user() or ""
    login = str(login).strip().strip('"')
    email = login.lower()
    # Atalho: se o proprio login ja e reconhecido como admin, nao precisa resolver email.
    if _is_admin(email):
        st.session_state["_user_email_"] = email
        if "_real_user_email_" not in st.session_state:
            st.session_state["_real_user_email_"] = email
        return email
    if login:
        ls = login.replace("'", "''")
        # Tentativa 1: SHOW USERS — real-time, sem latencia de ACCOUNT_USAGE.
        try:
            session.sql(f"SHOW USERS LIKE '{ls}'").collect()
            df_show = session.sql(
                "SELECT \"email\" FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))"
            ).to_pandas()
            if not df_show.empty and df_show.iloc[0]["email"]:
                email = str(df_show.iloc[0]["email"]).strip().lower()
        except Exception:
            pass
        # Tentativa 2: ACCOUNT_USAGE.USERS — fallback com latencia de ate 2h.
        if "@" not in email:
            try:
                df = session.sql(f"""
                    SELECT EMAIL
                    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
                    WHERE DELETED_ON IS NULL
                      AND EMAIL IS NOT NULL
                      AND (UPPER(LOGIN_NAME) = UPPER('{ls}') OR UPPER(NAME) = UPPER('{ls}'))
                    ORDER BY CREATED_ON DESC
                    LIMIT 1
                """).to_pandas()
                if not df.empty and df.iloc[0]["EMAIL"]:
                    email = str(df.iloc[0]["EMAIL"]).strip().lower()
            except Exception:
                pass
        # Tentativa 3: st.experimental_user.email — direto do Snowflake, sem latencia.
        # Usado como ultimo recurso pois pode retornar email diferente do ADMIN_EMAILS.
        if "@" not in email:
            try:
                eu = getattr(st, "experimental_user", None)
                if eu is not None:
                    direct_email = getattr(eu, "email", None) or ""
                    if direct_email and "@" in str(direct_email):
                        email = str(direct_email).strip().lower()
            except Exception:
                pass
    st.session_state["_user_email_"] = email
    if "_real_user_email_" not in st.session_state:
        st.session_state["_real_user_email_"] = email
    return email


def _is_restrito(session, user_safe):
    """True se o usuario tem QUALQUER registro em PERMISSAO_RLS (em qualquer periodo).

    Admin = usuario sem nenhum registro. A checagem e periodo-independente: um
    usuario restrito continua restrito mesmo num mes em que nao tenha registro.
    """
    try:
        df = session.sql(f"""
            SELECT COUNT(*) AS N
            FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE LOWER(USUARIOEMAIL) = '{user_safe}'
        """).to_pandas()
        return int(df.iloc[0]["N"]) > 0
    except Exception as _e:
        if _is_xp_err(_e):
            compat_rerun()
        raise


def _consultores_rls(session, ano, mes):
    """Retorna (lista_consultores, tipo_usuario, user_email).

    A resolucao em si fica em _consultores_rls_data (cacheada 30 min): o
    render_filters roda em TODO rerun, e sem cache cada interacao pagava
    1-2 round-trips so para remontar a mesma lista. Edicoes nas paginas
    admin invalidam via st.cache_data.clear() no salvamento.
    """
    try:
        user = current_email(session)
        consultores, tipo_usuario = _consultores_rls_data(user, int(ano), int(mes))
        return consultores, tipo_usuario, user
    except Exception as _e:
        if _is_xp_err(_e):
            compat_rerun()
        raise


def _todos_consultores_periodo(session, ano: int, mes: int):
    """Lista completa de consultores do periodo (a mesma visao do admin).

    Uniao de METAS + PARAMETROS: inclui quem tem comissao configurada
    mesmo sem META no mes (ex: GD/Governo em meses sem meta carregada).
    A partir de ago/2026, inclui tambem os Account Managers (gerentes
    de conta com carteira — modelo NRR independe de meta/parametros,
    ver docs/20_aba_comissoes_am.md).
    """
    _am_union = ""
    if (int(ano), int(mes)) >= (2026, 8):
        _am_union = """
            UNION
            SELECT DISTINCT LOWER(rio.EMAIL) AS EMAIL
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
              ON ric.NAME = l.ACCOUNT_MANAGER
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = ric.HUBSPOT_OWNER_ID
            WHERE l.ACCOUNT_MANAGER IS NOT NULL AND l.ACCOUNT_MANAGER <> 'N/A'
        """
    consultores_df = session.sql(f"""
        SELECT DISTINCT EMAIL FROM (
            SELECT LOWER(CONSULTOR) AS EMAIL
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = {ano} AND MES = {mes} AND CONSULTOR IS NOT NULL
            UNION
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND EMAIL IS NOT NULL
            {_am_union}
        )
        ORDER BY EMAIL
    """).to_pandas()
    return consultores_df["EMAIL"].tolist() if not consultores_df.empty else []


def _visualizadores_globais(session, ano: int, mes: int):
    """E-mails da chave CONFIG 'visualizadores_globais' vigente no periodo
    (mesma semantica de vigencia do carregar_config: vale o valor mais
    recente com (ANO, MES) <= periodo). Veem todos os consultores no filtro,
    mas so a aba Minha Comissao (nao sao admin nem Gestor)."""
    try:
        df = session.sql(f"""
            SELECT VALOR
            FROM SUPERSET.COMISSOES.CONFIG
            WHERE CHAVE = 'visualizadores_globais'
              AND (ANO * 100 + MES) <= {int(ano) * 100 + int(mes)}
            ORDER BY ANO DESC, MES DESC
            LIMIT 1
        """).to_pandas()
    except Exception:
        return []
    if df.empty or df.iloc[0]["VALOR"] is None:
        return []
    return [e.strip().lower() for e in str(df.iloc[0]["VALOR"]).split(",") if e.strip()]


@_cache_decorator(ttl=1800)
def _consultores_rls_data(user: str, ano: int, mes: int):
    """(lista_consultores, tipo_usuario) para o usuario/periodo.

    Politica deny-by-default:
      - admin (ADMIN_EMAILS)                    -> ve todos os consultores do periodo
      - CONFIG 'visualizadores_globais'         -> ve todos, mas como Consultor
                                                   (nav mostra so Minha Comissao)
      - tem registro em PERMISSAO_RLS           -> ve apenas seus CONSULTOREMAIL do periodo
      - nenhum dos anteriores                   -> SemAcesso (bloqueado)
    """
    session = get_active_session()
    user_safe = user.replace("'", "''")

    if _is_admin(user):
        return _todos_consultores_periodo(session, ano, mes), "Admin"

    if user in _visualizadores_globais(session, ano, mes):
        return _todos_consultores_periodo(session, ano, mes), "Consultor"

    if not _is_restrito(session, user_safe):
        return [], "SemAcesso"

    # Usuario restrito: ve apenas seus CONSULTOREMAIL do periodo selecionado
    rls_df = session.sql(f"""
        SELECT CONSULTOREMAIL, TIPOUSUARIO
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano} AND MES = {mes}
          AND LOWER(USUARIOEMAIL) = '{user_safe}'
        ORDER BY CONSULTOREMAIL
    """).to_pandas()
    consultores  = rls_df["CONSULTOREMAIL"].tolist() if not rls_df.empty else []
    tipo_usuario = str(rls_df.iloc[0]["TIPOUSUARIO"]) if not rls_df.empty else "Restrito"
    return consultores, tipo_usuario


def require_admin(session):
    """Bloqueia a pagina se o usuario nao for admin (ADMIN_EMAILS).
    Chamar no topo de toda pagina admin."""
    user = current_email(session)
    if _is_admin(user):
        st.session_state["tipo_usuario"] = "Admin"
        return user
    st.session_state["tipo_usuario"] = "Restrito"
    st.error("Acesso restrito a administradores.")
    st.stop()


def _equipes_consultores(session, ano, mes, consultores):
    """Mapa {email_lower: equipe} — wrapper com cache (30 min) e retry de XP.
    Sem cache, o render_filters pagava ate 3 round-trips por rerun so aqui."""
    if not consultores:
        return {}
    try:
        return _equipes_consultores_data(int(ano), int(mes), tuple(consultores))
    except Exception as _e:
        if _is_xp_err(_e):
            compat_rerun()
        raise


@_cache_decorator(ttl=1800)
def _equipes_consultores_data(ano: int, mes: int, consultores: tuple) -> dict:
    """Mapa {email_lower: equipe} para os consultores informados.
    Resolve a equipe pelo mes mais proximo do selecionado (no mesmo ano), pois
    nem todo consultor tem META no mes corrente (ex: GD/Governo)."""
    session = get_active_session()
    vals = ",".join("'" + c.replace("'", "''").lower() + "'" for c in consultores)
    df = session.sql(f"""
        SELECT EMAIL, EQUIPE FROM (
            SELECT LOWER(CONSULTOR) AS EMAIL, EQUIPE,
                   ROW_NUMBER() OVER (PARTITION BY LOWER(CONSULTOR)
                                      ORDER BY ABS(MES - {mes}) ASC, MES DESC) AS rn
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = {ano} AND EQUIPE IS NOT NULL AND LOWER(CONSULTOR) IN ({vals})
        ) WHERE rn = 1
    """).to_pandas()
    eq_map = {
        str(r["EMAIL"]): (str(r["EQUIPE"]) if r["EQUIPE"] is not None else "")
        for _, r in df.iterrows()
    }
    # Canc/Recovery não tem meta — sobrescreve com 'Cancelamento'
    cr_df = session.sql(f"""
        SELECT LOWER(EMAIL) AS EMAIL FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
          AND LOWER(EMAIL) IN ({vals})
    """).to_pandas()
    for _, r in cr_df.iterrows():
        eq_map[str(r["EMAIL"])] = "Cancelamento"
    # Account Managers (ago/2026+): a equipe especifica (AM GDC / AM Escritório)
    # vem das METAS via pipeline RI. O rotulo generico 'Account Manager' so
    # preenche quem tem carteira e NENHUMA equipe nas metas — nunca sobrescreve
    # (ex.: consultor FSB com clientes encarteirados continua FSB).
    if (int(ano), int(mes)) >= (2026, 8):
        am_df = session.sql(f"""
            SELECT DISTINCT LOWER(rio.EMAIL) AS EMAIL
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
              ON ric.NAME = l.ACCOUNT_MANAGER
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = ric.HUBSPOT_OWNER_ID
            WHERE l.ACCOUNT_MANAGER IS NOT NULL AND l.ACCOUNT_MANAGER <> 'N/A'
              AND LOWER(rio.EMAIL) IN ({vals})
        """).to_pandas()
        for _, r in am_df.iterrows():
            _em = str(r["EMAIL"])
            if not eq_map.get(_em):
                eq_map[_em] = "Account Manager"
    return eq_map


@st.cache_data(ttl=1800)
def _ultima_atualizacao_vendas():
    """Última sincronização da fonte de vendas (usada por quem não é GD/SDR).

    ATUALIZACAO já vem em texto no horário local (BR); NÃO passar por
    CONVERT_TIMEZONE aqui, porque TO_TIMESTAMP produz um TIMESTAMP_NTZ e o
    CONVERT_TIMEZONE de 2 argumentos assume a origem no fuso da SESSÃO
    (não em UTC), deslocando o horário errado (achado em 19/08/2026: virou
    +4h em vez de continuar igual)."""
    session = get_active_session()
    df = session.sql("""
        SELECT MAX(TO_TIMESTAMP(ATUALIZACAO, 'DD/MM/YYYY HH24:MI:SS')) AS ULT
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_VENDAS_REALIZADAS_POR_ITEM
    """).to_pandas()
    v = df.iloc[0]["ULT"]
    return v if pd.notna(v) else None


@st.cache_data(ttl=1800)
def _ultima_atualizacao_captacao():
    """Última atualização da fonte de Opps (GD e SDRs fora do time GD, que têm
    o realizado em Opps via HUBSPOT_REALIZADO_GD em vez de vendas). ATUALIZACAO
    já vem em BRT, no mesmo padrão da tabela de vendas."""
    session = get_active_session()
    df = session.sql("""
        SELECT MAX(TO_TIMESTAMP(ATUALIZACAO, 'DD/MM/YYYY HH24:MI:SS')) AS ULT
        FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_REALIZADO_GD
    """).to_pandas()
    v = df.iloc[0]["ULT"]
    return v if pd.notna(v) else None


@st.cache_data(ttl=1800)
def _cargo_email(email, ano, mes):
    session = get_active_session()
    email_safe = str(email).strip().lower().replace("'", "''")
    df = session.sql(f"""
        SELECT CARGO FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {int(ano)} AND MES = {int(mes)} AND LOWER(EMAIL) = '{email_safe}'
    """).to_pandas()
    if df.empty or not df.iloc[0]["CARGO"]:
        return ""
    return str(df.iloc[0]["CARGO"])


def _ultima_atualizacao_dados(email, ano, mes, equipe):
    """Escolhe a fonte certa (vendas x captação/Opps) pelo mesmo critério de
    utils/commission.py:2073-2075 (is_gd OR cargo contém "sales development")."""
    cargo = _cargo_email(email, ano, mes)
    is_gd_like = (str(equipe or "").strip().lower() == "gd"
                 or "sales development" in cargo.lower())
    return _ultima_atualizacao_captacao() if is_gd_like else _ultima_atualizacao_vendas()


def _chip_atualizacao_html(dt):
    if dt is None:
        return ""
    txt = dt.strftime("%d/%m/%Y %H:%M:%S")
    return (
        "<div style='text-align:right;padding-top:1.85rem;'>"
        "<span style='background:#f3f4f6;color:#4b5563;border-radius:999px;"
        "padding:5px 12px;font-size:0.78rem;font-weight:600;white-space:nowrap;"
        f"display:inline-block;'>🕒 Atualizado em {txt}</span></div>"
    )


def render_filters(session, with_equipe=False):
    """Renderiza filtros Ano/Mes/Equipe/Consultor. Mudancas aplicam imediatamente."""
    qp = _qp_get()
    anos = periodo_anos()
    ano_atu, mes_atu = _periodo_default()
    ano_def = _safe_int(qp.get("ano"), int(st.session_state.get("ano", ano_atu)))
    if ano_def not in anos:
        ano_def = ano_atu
    mes_def = _safe_int(qp.get("mes"), int(st.session_state.get("mes", mes_atu)))
    eq_def  = qp.get("equipe", "Todas")

    _sfx     = st.session_state.get("_tab_key_", "")
    _key_ano = f"_f_ano_{_sfx}"
    _key_mes = f"_f_mes_{_sfx}"
    _key_eq  = f"_f_eq_{_sfx}"
    _key_con = f"_f_con_{_sfx}"

    if _key_ano not in st.session_state or st.session_state[_key_ano] not in anos:
        st.session_state[_key_ano] = ano_def
    meses = periodo_meses(st.session_state[_key_ano])
    if _key_mes not in st.session_state or st.session_state[_key_mes] not in meses:
        _cm = mes_def if mes_def in meses else (mes_atu if mes_atu in meses else meses[-1])
        st.session_state[_key_mes] = _cm

    ano = st.session_state[_key_ano]
    meses2 = periodo_meses(ano)
    if st.session_state[_key_mes] not in meses2:
        st.session_state[_key_mes] = meses2[-1]
    mes = st.session_state[_key_mes]

    consultores, tipo_usuario, user = _consultores_rls(session, ano, mes)
    st.session_state["tipo_usuario"] = tipo_usuario

    _nc = [1, 1, 1.5, 2.5] if with_equipe else [1, 1, 3]
    if tipo_usuario == "SemAcesso":
        _dc = st.columns(_nc)
        _dc[0].selectbox("📅 Ano", anos, disabled=True)
        _dc[1].selectbox("🗓️ Mês", ["—"], disabled=True)
        if with_equipe:
            _dc[2].selectbox("👥 Equipe", ["Todas"], disabled=True)
            _dc[3].selectbox("👤 Consultor", ["(sem acesso)"], disabled=True)
        else:
            _dc[2].selectbox("👤 Consultor", ["(sem acesso)"], disabled=True)
        st.session_state["consultor"] = ""
        st.error("Você não tem acesso a este painel. Solicite cadastro ao administrador.")
        st.stop()

    if not consultores:
        _dc = st.columns(_nc)
        _dc[0].selectbox("📅 Ano", anos, disabled=True)
        _dc[1].selectbox("🗓️ Mês", ["—"], disabled=True)
        if with_equipe:
            _dc[2].selectbox("👥 Equipe", ["Todas"], disabled=True)
            _dc[3].selectbox("👤 Consultor", ["(nenhum)"], disabled=True)
        else:
            _dc[2].selectbox("👤 Consultor", ["(nenhum)"], disabled=True)
        st.session_state["consultor"] = ""
        st.markdown("<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>Nenhum consultor disponível para este período.</div>", unsafe_allow_html=True)
        st.stop()

    if with_equipe:
        eq_map     = _equipes_consultores(session, ano, mes, consultores)
        equipes_opc = ["Todas"] + sorted({e for e in eq_map.values() if e})
        if _key_eq not in st.session_state or st.session_state[_key_eq] not in equipes_opc:
            st.session_state[_key_eq] = eq_def if eq_def in equipes_opc else "Todas"
        cur_eq = st.session_state[_key_eq]
        cons_display = [c for c in consultores if eq_map.get(c.lower()) == cur_eq] if cur_eq != "Todas" else consultores
        if not cons_display:
            cons_display = consultores
            st.session_state[_key_eq] = "Todas"
    else:
        equipes_opc  = []
        cons_display = consultores

    prev_cons = qp.get("consultor", "") or st.session_state.get("consultor", "")
    if _key_con not in st.session_state or st.session_state[_key_con] not in cons_display:
        if prev_cons in cons_display:
            st.session_state[_key_con] = prev_cons
        elif user in cons_display:
            st.session_state[_key_con] = user
        else:
            st.session_state[_key_con] = cons_display[0]

    if with_equipe:
        col_ano, col_mes, col_eq, col_con, col_upd = st.columns([1, 1, 1.3, 2.2, 1.6])
    else:
        col_ano, col_mes, col_con, col_upd = st.columns([1, 1, 2.5, 1.6])
        col_eq = None

    col_ano.selectbox("📅 Ano", anos, key=_key_ano)
    meses3 = periodo_meses(st.session_state[_key_ano])
    if st.session_state[_key_mes] not in meses3:
        st.session_state[_key_mes] = meses3[-1]
    col_mes.selectbox("🗓️ Mês", meses3, key=_key_mes, format_func=lambda x: _MESES_ABREV[x])
    if col_eq is not None:
        col_eq.selectbox("👥 Equipe", equipes_opc, key=_key_eq)
    col_con.selectbox("👤 Consultor", cons_display, key=_key_con)

    email = st.session_state[_key_con]
    ano   = st.session_state[_key_ano]
    mes   = st.session_state[_key_mes]
    st.session_state["ano"]       = ano
    st.session_state["mes"]       = mes
    st.session_state["consultor"] = email
    _qp_set(ano=ano, mes=mes, consultor=email,
            equipe=st.session_state.get(_key_eq, "Todas"))
    hide_stale_on_change(f"_flt_prev_{_sfx}",
                         (ano, mes, email, st.session_state.get(_key_eq, "")))

    _equipe_email = eq_map.get(email.lower(), "") if with_equipe else ""
    try:
        _dt_atualizacao = _ultima_atualizacao_dados(email, ano, mes, _equipe_email)
    except Exception:
        _dt_atualizacao = None
    col_upd.markdown(_chip_atualizacao_html(_dt_atualizacao), unsafe_allow_html=True)

    return ano, mes, email, tipo_usuario


def clear_comissao_cache():
    """Limpa todo o cache @st.cache_data do app (comissão + páginas admin)."""
    if hasattr(st, "cache_data") and hasattr(st.cache_data, "clear"):
        st.cache_data.clear()
    elif hasattr(st, "experimental_memo") and hasattr(st.experimental_memo, "clear"):
        st.experimental_memo.clear()
    else:
        for fn in [get_comissao_cached, get_composicao_cached,
                   get_composicao_bk_extra_cached, get_composicao_canc_recovery_cached,
                   get_composicao_renovacoes_canc_cached]:
            if hasattr(fn, "clear"):
                fn.clear()


def is_admin(session) -> bool:
    """True se o usuario logado esta em ADMIN_EMAILS."""
    return _is_admin(current_email(session))


def _login_to_email(session, login) -> str:
    """Resolve login do Snowflake -> e-mail. Devolve '' se nao conseguir.

    Mesma cascata do current_email (SHOW USERS -> ACCOUNT_USAGE -> experimental_user),
    isolada aqui para o audit_user. O current_email nao foi refatorado de proposito:
    ele decide RLS e acesso admin, e um erro sutil ali vira problema de permissao.
    """
    if not login:
        return ""
    email = ""
    ls = str(login).replace("'", "''")
    # Tentativa 1: SHOW USERS — real-time, sem latencia de ACCOUNT_USAGE.
    try:
        session.sql(f"SHOW USERS LIKE '{ls}'").collect()
        df_show = session.sql(
            "SELECT \"email\" FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))"
        ).to_pandas()
        if not df_show.empty and df_show.iloc[0]["email"]:
            email = str(df_show.iloc[0]["email"]).strip().lower()
    except Exception:
        pass
    # Tentativa 2: ACCOUNT_USAGE.USERS — fallback com latencia de ate 2h.
    if "@" not in email:
        try:
            df = session.sql(f"""
                SELECT EMAIL
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
                WHERE DELETED_ON IS NULL
                  AND EMAIL IS NOT NULL
                  AND (UPPER(LOGIN_NAME) = UPPER('{ls}') OR UPPER(NAME) = UPPER('{ls}'))
                ORDER BY CREATED_ON DESC
                LIMIT 1
            """).to_pandas()
            if not df.empty and df.iloc[0]["EMAIL"]:
                email = str(df.iloc[0]["EMAIL"]).strip().lower()
        except Exception:
            pass
    # Tentativa 3: st.experimental_user.email — direto do Snowflake, sem latencia.
    if "@" not in email:
        try:
            eu = getattr(st, "experimental_user", None)
            if eu is not None:
                direct_email = getattr(eu, "email", None) or ""
                if direct_email and "@" in str(direct_email):
                    email = str(direct_email).strip().lower()
        except Exception:
            pass
    return email if "@" in email else ""


def audit_user(session) -> str:
    """E-mail de quem esta gravando, para colunas de autoria (UPDATED_BY, USUARIO...).

    Use SEMPRE esta funcao em vez de CURRENT_USER() no SQL: no SiS o app roda com
    owner's rights e CURRENT_USER() volta NULL, o que gravava autoria vazia.

    Devolve sempre e-mail. O current_email pode parar no login quando o proprio
    login esta em ADMIN_EMAILS (atalho de performance), entao aqui a resolucao
    login -> e-mail e forcada. Cai no login e, em ultimo caso, em 'desconhecido',
    para nunca gravar NULL.
    """
    user = (current_email(session) or "").strip().lower()
    if "@" in user:
        return user
    cached = st.session_state.get("_audit_user_")
    if cached:
        return cached
    resolvido = _login_to_email(session, user) or user or "desconhecido"
    st.session_state["_audit_user_"] = resolvido
    return resolvido


def audit_user_sql(session) -> str:
    """audit_user pronto para interpolar em SQL, ja com aspas e escape."""
    return "'" + audit_user(session).replace("'", "''") + "'"


def real_email(session) -> str:
    """Retorna o e-mail real do usuario logado, ignorando impersonacao."""
    cached = st.session_state.get("_real_user_email_")
    if cached:
        return cached
    saved = st.session_state.get("_view_as_email_")
    if "_view_as_email_" in st.session_state:
        del st.session_state["_view_as_email_"]
    try:
        email = current_email(session)
    finally:
        if saved is not None:
            st.session_state["_view_as_email_"] = saved
    return st.session_state.get("_real_user_email_", email)


def is_real_admin(session) -> bool:
    """True se o usuario REAL logado esta em ADMIN_EMAILS (ignora impersonacao)."""
    return _is_admin(real_email(session))


def is_gestor_in_rls(session) -> bool:
    """True se o usuario tem TIPOUSUARIO='Gestor' em qualquer periodo no RLS.
    Admins retornam False (ja tem acesso total por outra via)."""
    cached = st.session_state.get("_is_gestor_rls_")
    if cached is not None:
        return bool(cached)
    user = current_email(session)
    if _is_admin(user):
        st.session_state["_is_gestor_rls_"] = False
        return False
    user_safe = user.replace("'", "''")
    df = session.sql(f"""
        SELECT COUNT(*) AS N
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE LOWER(USUARIOEMAIL) = '{user_safe}'
          AND UPPER(TIPOUSUARIO) = 'GESTOR'
    """).to_pandas()
    result = int(df.iloc[0]["N"]) > 0
    st.session_state["_is_gestor_rls_"] = result
    return result


def require_admin_or_gestor(session):
    """Permite acesso a admins (ADMIN_EMAILS) e gestores (TIPOUSUARIO=Gestor no RLS).
    Para os demais, interrompe silenciosamente — a pagina nao deve aparecer na nav deles."""
    user = current_email(session)
    if _is_admin(user):
        st.session_state["tipo_usuario"] = "Admin"
        return user
    if is_gestor_in_rls(session):
        st.session_state["tipo_usuario"] = "Gestor"
        return user
    st.stop()
