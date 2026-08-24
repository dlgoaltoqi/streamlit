"""Autorização e RLS de interface — porta de utils/connection.py e _app.py.

Politica deny-by-default (igual ao SiS):
  - admin (ADMIN_EMAILS via config)         -> vê todos os consultores do período
  - CONFIG 'visualizadores_globais'         -> vê todos, mas como Consultor
                                               (nav mostra só Minha Comissão)
  - tem registro em PERMISSAO_RLS           -> vê apenas seus CONSULTOREMAIL
  - nenhum dos anteriores                   -> SemAcesso
"""
from webapp.config import settings
from webapp.core.cache import RLS, ttl_cached
from webapp.db.pool import get_pool


def is_admin(email: str) -> bool:
    return (email or "").strip().lower() in settings.admin_emails


@ttl_cached(RLS)
def _is_restrito(user: str) -> bool:
    """True se o usuário tem QUALQUER registro em PERMISSAO_RLS (qualquer período)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT COUNT(*) AS N FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE LOWER(USUARIOEMAIL) = %s
        """, (user,)).to_pandas()
    return int(df.iloc[0]["N"]) > 0


def _todos_consultores_periodo(ano: int, mes: int) -> tuple:
    """Lista completa de consultores do período (a mesma visão do admin)."""
    am_union = ""
    if (int(ano), int(mes)) >= (2026, 8):
        am_union = """
            UNION
            SELECT DISTINCT LOWER(rio.EMAIL) AS EMAIL
            FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
              ON ric.NAME = l.ACCOUNT_MANAGER
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = ric.HUBSPOT_OWNER_ID
            WHERE l.ACCOUNT_MANAGER IS NOT NULL AND l.ACCOUNT_MANAGER <> 'N/A'
        """
    with get_pool().session() as s:
        df = s.sql(f"""
            SELECT DISTINCT EMAIL FROM (
                SELECT LOWER(CONSULTOR) AS EMAIL
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = %s AND MES = %s AND CONSULTOR IS NOT NULL
                UNION
                SELECT LOWER(EMAIL) AS EMAIL
                FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE ANO = %s AND MES = %s AND EMAIL IS NOT NULL
                {am_union}
            ) ORDER BY EMAIL
        """, (ano, mes, ano, mes)).to_pandas()
    return tuple(str(e) for e in df["EMAIL"])


def _visualizadores_globais(ano: int, mes: int) -> tuple:
    """E-mails da chave CONFIG 'visualizadores_globais' vigente no período
    (vale o valor mais recente com (ANO, MES) <= período)."""
    try:
        with get_pool().session() as s:
            df = s.sql("""
                SELECT VALOR
                FROM SUPERSET.COMISSOES.CONFIG
                WHERE CHAVE = 'visualizadores_globais'
                  AND (ANO * 100 + MES) <= %s
                ORDER BY ANO DESC, MES DESC
                LIMIT 1
            """, (int(ano) * 100 + int(mes),)).to_pandas()
    except Exception:
        return tuple()
    if df.empty or df.iloc[0]["VALOR"] is None:
        return tuple()
    return tuple(e.strip().lower() for e in str(df.iloc[0]["VALOR"]).split(",") if e.strip())


@ttl_cached(RLS)
def consultores_rls(user: str, ano: int, mes: int):
    """(tupla_consultores, tipo_usuario) — porta de _consultores_rls_data."""
    user = (user or "").strip().lower()
    if is_admin(user):
        return _todos_consultores_periodo(ano, mes), "Admin"

    if user in _visualizadores_globais(ano, mes):
        return _todos_consultores_periodo(ano, mes), "Consultor"

    if not _is_restrito(user):
        return tuple(), "SemAcesso"

    with get_pool().session() as s:
        df = s.sql("""
            SELECT CONSULTOREMAIL, TIPOUSUARIO
            FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE ANO = %s AND MES = %s AND LOWER(USUARIOEMAIL) = %s
            ORDER BY CONSULTOREMAIL
        """, (ano, mes, user)).to_pandas()
    consultores = tuple(str(e).lower() for e in df["CONSULTOREMAIL"]) if not df.empty else tuple()
    tipo = str(df.iloc[0]["TIPOUSUARIO"]) if not df.empty else "Restrito"
    return consultores, tipo


@ttl_cached(RLS)
def is_gestor_in_rls(user: str) -> bool:
    """TIPOUSUARIO='Gestor' em qualquer período; admins retornam False (SiS)."""
    user = (user or "").strip().lower()
    if is_admin(user):
        return False
    with get_pool().session() as s:
        df = s.sql("""
            SELECT COUNT(*) AS N FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE LOWER(USUARIOEMAIL) = %s AND UPPER(TIPOUSUARIO) = 'GESTOR'
        """, (user,)).to_pandas()
    return int(df.iloc[0]["N"]) > 0


@ttl_cached(RLS)
def is_pvt(user: str) -> bool:
    """IS_PVT=TRUE em qualquer período (gating da aba PVT no _app.py)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE LOWER(EMAIL) = %s AND IS_PVT = TRUE LIMIT 1
        """, ((user or "").lower(),)).to_pandas()
    return not df.empty


@ttl_cached(RLS)
def is_saving_gestor(user: str, ano: int) -> bool:
    """Gestor com EQUIPE='saving' nas metas do ano (gating rd/adm no _app.py)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT 1 FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND LOWER(CONSULTOR) = %s AND LOWER(EQUIPE) = 'saving'
            LIMIT 1
        """, (int(ano), (user or "").lower())).to_pandas()
    return not df.empty


@ttl_cached(RLS)
def email_existe_nas_bases(email: str) -> bool:
    """Validação do 'Visualizar como' (porta de _app.py:142-158)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT 1 FROM (
                SELECT LOWER(CONSULTOR) AS E
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE CONSULTOR IS NOT NULL
                UNION
                SELECT LOWER(EMAIL) FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE EMAIL IS NOT NULL
                UNION
                SELECT LOWER(USUARIOEMAIL) FROM SUPERSET.PARCIAL.PERMISSAO_RLS
                WHERE USUARIOEMAIL IS NOT NULL
            ) WHERE E = %s LIMIT 1
        """, ((email or "").lower(),)).to_pandas()
    return not df.empty


@ttl_cached(RLS)
def membros_rls_gestor(user: str, ano: int, mes: int) -> tuple:
    """Membros do gestor no período (porta de pages/02:72-79)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT LOWER(CONSULTOREMAIL) AS EMAIL
            FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            WHERE ANO = %s AND MES = %s
              AND LOWER(USUARIOEMAIL) = %s AND TIPOUSUARIO = 'Gestor'
            ORDER BY CONSULTOREMAIL
        """, (int(ano), int(mes), (user or "").lower())).to_pandas()
    return tuple(str(e) for e in df["EMAIL"])


@ttl_cached(RLS)
def equipes_consultores(ano: int, mes: int, consultores: tuple) -> dict:
    """Mapa {email: equipe} — porta de utils/connection.py:676-722.
    Equipe pelo mês mais próximo no ano (nem todo consultor tem meta no mês);
    Cancelamento sobrescreve; 'Account Manager' genérico só preenche quem tem
    carteira e nenhuma equipe nas metas (ago/2026+)."""
    if not consultores:
        return {}
    ph = ",".join(["%s"] * len(consultores))
    with get_pool().session() as s:
        df = s.sql(f"""
            SELECT EMAIL, EQUIPE FROM (
                SELECT LOWER(CONSULTOR) AS EMAIL, EQUIPE,
                       ROW_NUMBER() OVER (PARTITION BY LOWER(CONSULTOR)
                                          ORDER BY ABS(MES - %s) ASC, MES DESC) AS rn
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = %s AND EQUIPE IS NOT NULL AND LOWER(CONSULTOR) IN ({ph})
            ) WHERE rn = 1
        """, (mes, ano, *consultores)).to_pandas()
        eq_map = {str(r["EMAIL"]): (str(r["EQUIPE"]) if r["EQUIPE"] is not None else "")
                  for _, r in df.iterrows()}
        cr_df = s.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = %s AND MES = %s AND IS_CANC_RECOVERY = TRUE
              AND LOWER(EMAIL) IN ({ph})
        """, (ano, mes, *consultores)).to_pandas()
        for _, r in cr_df.iterrows():
            eq_map[str(r["EMAIL"])] = "Cancelamento"
        if (int(ano), int(mes)) >= (2026, 8):
            am_df = s.sql(f"""
                SELECT DISTINCT LOWER(rio.EMAIL) AS EMAIL
                FROM HUBSPOT.HUBSPOT_OURO.HUBSPOT_LISTA_POTENCIAL_FARMER l
                JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
                  ON ric.NAME = l.ACCOUNT_MANAGER
                JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
                  ON rio.ID = ric.HUBSPOT_OWNER_ID
                WHERE l.ACCOUNT_MANAGER IS NOT NULL AND l.ACCOUNT_MANAGER <> 'N/A'
                  AND LOWER(rio.EMAIL) IN ({ph})
            """, tuple(consultores)).to_pandas()
            for _, r in am_df.iterrows():
                em = str(r["EMAIL"])
                if not eq_map.get(em):
                    eq_map[em] = "Account Manager"
    return eq_map
