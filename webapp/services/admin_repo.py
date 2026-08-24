"""Motor genérico de ESCRITA das páginas admin (Fase 5 da migração).

Reproduz os 3 gestos do SiS — upsert (MERGE), remover (DELETE por chave) e
copiar do mês anterior — com binds (%s) e auditoria (UPDATED_BY/UPDATED_AT ou
CREATED_BY/CREATED_AT), terminando SEMPRE em invalidate_after_write().

Segurança da migração:
- settings.writes_enabled (env WRITES_ENABLED=1) liga a edição na UI; o
  default é DESLIGADO — produção continua editando no SiS até o cutover.
- settings.writes_target (env WRITES_TARGET=clone) aponta as escritas para
  os clones MIGTESTE_* — é assim que o gate da Fase 5 valida o ciclo
  add/edit/copiar/delete sem tocar nas tabelas reais.

As specs (chaves com transform, campos, estilo de auditoria) vivem em
webapp/views/admin_view.py junto do registro das páginas.
"""
from webapp.config import settings
from webapp.core.cache import invalidate_after_write
from webapp.db.pool import get_pool

# Redirecionamento de escrita para os clones de teste (WRITES_TARGET=clone).
_CLONES = {
    "SUPERSET.COMISSOES.CARGOS_OTES": "SUPERSET.COMISSOES.MIGTESTE_CARGOS_OTES",
    "SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO": "SUPERSET.COMISSOES.MIGTESTE_ACEL_FORMA_PAGAMENTO",
    "SUPERSET.COMISSOES.PATAMARES_COMISSAO": "SUPERSET.COMISSOES.MIGTESTE_PATAMARES_COMISSAO",
    "SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS": "SUPERSET.COMISSOES.MIGTESTE_RECUPERACAO_DIVIDAS",
    "SUPERSET.COMISSOES.DEALS_PAGOS_400K": "SUPERSET.COMISSOES.MIGTESTE_DEALS_PAGOS_400K",
    "SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE": "SUPERSET.COMISSOES.MIGTESTE_REALIZADO_GD_OVERRIDE",
    "SUPERSET.COMISSOES.PONDERACOES_META": "SUPERSET.COMISSOES.MIGTESTE_PONDERACOES_META",
    "SUPERSET.COMISSOES.AJUSTES_PONTUAIS": "SUPERSET.COMISSOES.MIGTESTE_AJUSTES_PONTUAIS",
    "SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM": "SUPERSET.COMISSOES.MIGTESTE_EXCLUSOES_CARTEIRA_AM",
    "SUPERSET.PARCIAL.PERMISSAO_RLS": "SUPERSET.COMISSOES.MIGTESTE_PERMISSAO_RLS",
    "SUPERSET.COMISSOES.PARAMETROS": "SUPERSET.COMISSOES.MIGTESTE_PARAMETROS",
    "SUPERSET.PARCIAL.META_CONSULTOR": "SUPERSET.COMISSOES.MIGTESTE_META_CONSULTOR",
    "SUPERSET.COMISSOES.CONFIG": "SUPERSET.COMISSOES.MIGTESTE_CONFIG",
}


def tabela_escrita(fq: str) -> str:
    if settings.writes_target == "clone":
        return _CLONES.get(fq, fq)
    return fq


def _cmp(alias_t, alias_s, chave):
    """Comparação de chave com o transform do SiS (UPPER/LOWER quando havia)."""
    col, tr = chave
    if tr:
        return f"{tr}({alias_t}.{col}) = {tr}({alias_s}.{col})"
    return f"{alias_t}.{col} = {alias_s}.{col}"


def upsert(spec, valores: dict, usuario: str):
    """MERGE por chave (ou INSERT puro no modo 'insert'), com auditoria.

    `valores` inclui chaves e campos; ANO/MES entram como chaves nas specs
    mensais. Tudo via binds.
    """
    t = tabela_escrita(spec.tabela)
    chaves = [c for c, _ in spec.chaves]
    campos = [c.nome for c in spec.campos]
    cols = chaves + campos

    if spec.modo == "insert":
        col_sql = ", ".join(cols) + ", CREATED_BY, CREATED_AT"
        ph = ", ".join(["%s"] * len(cols)) + ", %s, CURRENT_TIMESTAMP()"
        params = [valores[c] for c in cols] + [usuario]
        with get_pool().session() as s:
            s.sql(f"INSERT INTO {t} ({col_sql}) VALUES ({ph})", tuple(params))
        invalidate_after_write()
        return

    src = ", ".join(f"%s AS {c}" for c in cols)
    on = " AND ".join(_cmp("t", "s", ch) for ch in spec.chaves)
    if spec.audit == "deals":
        set_upd = (", ".join(f"{c} = s.{c}" for c in campos)
                   + ", DATA_MARCACAO = CURRENT_DATE, USUARIO = %s")
        ins_cols = ", ".join(cols) + ", DATA_MARCACAO, USUARIO"
        ins_vals = ", ".join(f"s.{c}" for c in cols) + ", CURRENT_DATE, %s"
    else:
        set_upd = (", ".join(f"{c} = s.{c}" for c in campos)
                   + ", UPDATED_BY = %s, UPDATED_AT = CURRENT_TIMESTAMP()")
        ins_cols = ", ".join(cols) + ", UPDATED_BY, UPDATED_AT"
        ins_vals = ", ".join(f"s.{c}" for c in cols) + ", %s, CURRENT_TIMESTAMP()"
    q = (f"MERGE INTO {t} AS t USING (SELECT {src}) AS s ON {on} "
         f"WHEN MATCHED THEN UPDATE SET {set_upd} "
         f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})")
    params = [valores[c] for c in cols] + [usuario, usuario]
    with get_pool().session() as s:
        s.sql(q, tuple(params))
    invalidate_after_write()


def excluir(spec, chaves_valores: dict):
    """DELETE pela chave de remoção da spec (com transform onde o SiS tinha).
    Sem chave_remocao própria (a maioria), cai na chave normal."""
    t = tabela_escrita(spec.tabela)
    conds, params = [], []
    for col, tr in (spec.chave_remocao or spec.chaves):
        if tr:
            conds.append(f"{tr}({col}) = {tr}(%s)")
        else:
            conds.append(f"{col} = %s")
        params.append(chaves_valores[col])
    with get_pool().session() as s:
        s.sql(f"DELETE FROM {t} WHERE " + " AND ".join(conds), tuple(params))
    invalidate_after_write()


def copiar_mes(spec, ano_orig: int, mes_orig: int, ano: int, mes: int, usuario: str):
    """Copia o conteúdo do período origem para o destino via MERGE (como o SiS)."""
    t = tabela_escrita(spec.tabela)
    chaves_nao_periodo = [c for c, _ in spec.chaves if c not in ("ANO", "MES")]
    campos = [c.nome for c in spec.campos]
    cols = chaves_nao_periodo + campos
    col_sql = ", ".join(cols)
    on = " AND ".join(_cmp("t", "s", ch) for ch in spec.chaves)
    set_upd = (", ".join(f"{c} = s.{c}" for c in campos)
               + ", UPDATED_BY = %s, UPDATED_AT = CURRENT_TIMESTAMP()")
    ins_cols = "ANO, MES, " + col_sql + ", UPDATED_BY, UPDATED_AT"
    ins_vals = ("s.ANO, s.MES, " + ", ".join(f"s.{c}" for c in cols)
                + ", %s, CURRENT_TIMESTAMP()")
    q = (f"MERGE INTO {t} AS t USING ("
         f"  SELECT %s AS ANO, %s AS MES, {col_sql} FROM {t}"
         f"  WHERE ANO = %s AND MES = %s"
         f") AS s ON {on} "
         f"WHEN MATCHED THEN UPDATE SET {set_upd} "
         f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})")
    with get_pool().session() as s:
        s.sql(q, (ano, mes, ano_orig, mes_orig, usuario, usuario))
    invalidate_after_write()


# ── Grades editáveis (Parâmetros, Metas) e Config com vigência ───────────────
#
# Parâmetros e Metas usam uma grade de linhas dinâmicas (equivalente do
# st.data_editor), fora do modelo AdminPage/Campo de cima porque têm conversão
# percentual (×100 na tela) e semânticas de salvar/copiar próprias — replicam
# pages/11_Admin_Parametros.py e pages/21_Admin_Metas.py linha a linha.

PARAMETROS_TABELA = "SUPERSET.COMISSOES.PARAMETROS"
_PARAMETROS_COLS = [
    "CARGO", "IS_GESTOR", "IS_PVT", "IS_TRIM_HABILITADO",
    "CLIFF_OTE_01", "CLIFF_OTE_02",
    "CLIFF_ACELERADOR_01", "MULT_ACELERADOR_01",
    "CLIFF_ACELERADOR_02", "MULT_ACELERADOR_02",
    "PERCENTUAL_BOOKING_EXTRA", "OTE_01_CHEIO", "OTE_02_CHEIO",
    "PERCENTUAL_PROTECAO", "IS_CANC_RECOVERY", "PERCENTUAL_CANC_RECOVERY",
]
_PARAMETROS_BOOL = {"IS_GESTOR", "IS_PVT", "IS_TRIM_HABILITADO", "IS_CANC_RECOVERY"}
_PARAMETROS_PCT = {
    "CLIFF_OTE_01", "CLIFF_OTE_02", "CLIFF_ACELERADOR_01", "CLIFF_ACELERADOR_02",
    "PERCENTUAL_BOOKING_EXTRA", "PERCENTUAL_PROTECAO", "PERCENTUAL_CANC_RECOVERY",
}


def _norm_cmp(v):
    """Normaliza um valor para comparação de diff (mesmo espaço de unidades
    dos dois lados: ambos em unidade de EXIBIÇÃO, percentual já ×100)."""
    try:
        if v is None or v != v:
            return None
    except TypeError:
        pass
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        v = v.strip()
        return v or None
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return v


def parametros_salvar_grid(ano: int, mes: int, linhas: list, usuario: str):
    """Salva só quem mudou (diff contra o banco, em unidade de exibição) e
    remove quem tinha e-mail antes e não veio mais na lista enviada — mesma
    lógica de pages/11_Admin_Parametros.py."""
    t = tabela_escrita(PARAMETROS_TABELA)
    with get_pool().session() as s:
        antes = s.sql(
            f"SELECT EMAIL, {', '.join(_PARAMETROS_COLS)} FROM {t} "
            "WHERE ANO = %s AND MES = %s", (ano, mes)).to_pandas()

    orig_por_email = {}
    for _, r in antes.iterrows():
        vals = []
        for c in _PARAMETROS_COLS:
            v = r[c]
            if c in _PARAMETROS_PCT and v is not None and v == v:
                v = round(float(v) * 100, 4)
            vals.append(_norm_cmp(v))
        orig_por_email[str(r["EMAIL"]).strip().lower()] = tuple(vals)

    novos_emails, salvos, erros = set(), 0, []
    for linha in linhas:
        em = str(linha.get("EMAIL") or "").strip().lower()
        if not em:
            continue
        novos_emails.add(em)
        cargo = str(linha.get("CARGO") or "").strip()
        if not cargo:
            erros.append(f"Cargo não informado para {em}.")
            continue
        valores = {"CARGO": cargo}
        for c in _PARAMETROS_COLS:
            if c == "CARGO":
                continue
            v = linha.get(c)
            if c in _PARAMETROS_BOOL:
                valores[c] = bool(v) if v is not None else (c == "IS_TRIM_HABILITADO")
            else:
                valores[c] = None if v in (None, "") else float(v)

        atual = tuple(_norm_cmp(valores[c]) for c in _PARAMETROS_COLS)
        if orig_por_email.get(em) == atual:
            continue  # sem alteração, preserva UPDATED_AT/UPDATED_BY

        armazenar = dict(valores)
        for c in _PARAMETROS_PCT:
            if armazenar[c] is not None:
                armazenar[c] = round(armazenar[c] / 100, 6)

        cols_src = ["EMAIL"] + _PARAMETROS_COLS
        src = ", ".join(f"%s AS {c}" for c in cols_src)
        set_upd = (", ".join(f"{c} = s.{c}" for c in _PARAMETROS_COLS)
                   + ", UPDATED_BY = %s, UPDATED_AT = CURRENT_TIMESTAMP()")
        ins_cols = "ANO, MES, " + ", ".join(cols_src) + ", UPDATED_BY, UPDATED_AT"
        ins_vals = ("%s, %s, " + ", ".join(f"s.{c}" for c in cols_src)
                    + ", %s, CURRENT_TIMESTAMP()")
        q = (f"MERGE INTO {t} AS t USING (SELECT {src}) AS s "
             "ON t.ANO = %s AND t.MES = %s AND LOWER(t.EMAIL) = LOWER(s.EMAIL) "
             f"WHEN MATCHED THEN UPDATE SET {set_upd} "
             f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})")
        params = ([em] + [armazenar[c] for c in _PARAMETROS_COLS]
                  + [ano, mes] + [usuario] + [ano, mes] + [usuario])
        try:
            with get_pool().session() as s:
                s.sql(q, tuple(params))
            salvos += 1
        except Exception as e:
            erros.append(f"Erro ao salvar {em}: {e}")

    removidos = orig_por_email.keys() - novos_emails
    for em in removidos:
        try:
            with get_pool().session() as s:
                s.sql(f"DELETE FROM {t} WHERE ANO = %s AND MES = %s AND LOWER(EMAIL) = %s",
                      (ano, mes, em))
        except Exception as e:
            erros.append(f"Erro ao remover {em}: {e}")

    invalidate_after_write()
    return salvos, len(removidos), erros


def parametros_copiar_mes(ano: int, mes: int, ano_orig: int, mes_orig: int, usuario: str):
    """Copia só registros que NÃO existem no mês atual (MERGE sem
    sobrescrever) — igual ao botão do SiS."""
    t = tabela_escrita(PARAMETROS_TABELA)
    cols = ["EMAIL"] + _PARAMETROS_COLS
    col_sql = ", ".join(cols)
    q = (f"MERGE INTO {t} AS t USING ("
         f"  SELECT %s AS ANO, %s AS MES, {col_sql} FROM {t} WHERE ANO = %s AND MES = %s"
         ") AS s ON LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.ANO = s.ANO AND t.MES = s.MES "
         f"WHEN NOT MATCHED THEN INSERT (ANO, MES, {col_sql}, UPDATED_BY, UPDATED_AT) "
         f"VALUES (s.ANO, s.MES, {', '.join('s.' + c for c in cols)}, %s, CURRENT_TIMESTAMP())")
    with get_pool().session() as s:
        s.sql(q, (ano, mes, ano_orig, mes_orig, usuario))
    invalidate_after_write()


META_CONSULTOR_TABELA = "SUPERSET.PARCIAL.META_CONSULTOR"
_METAS_COLS = [
    "EQUIPE", "SENIORIDADE", "PERCENTUAL_DESCONTO_METAS",
    "META_NMRR_BRUTO", "META_EXPANSAO_BRUTO", "META_RENOVACAO_BRUTO", "META_OTR_BRUTO",
    "META_NMRR", "META_EXPANSAO", "META_RENOVACAO", "META_OTR",
]


def metas_salvar_grid(ano: int, mes: int, linhas: list):
    """MERGE de toda linha enviada (sem diff-skip nem remoção de linha
    apagada na grade) — mesmo comportamento de pages/21_Admin_Metas.py, só
    válido para meses < RI_DESDE (a tela bloqueia o resto)."""
    t = tabela_escrita(META_CONSULTOR_TABELA)
    cols_src = ["EMAIL"] + _METAS_COLS
    src = ", ".join(f"%s AS {c}" for c in cols_src)
    set_upd = ", ".join(f"{c} = s.{c}" for c in _METAS_COLS)
    ins_cols = "ANO, MES, " + ", ".join(cols_src)
    ins_vals = "%s, %s, " + ", ".join(f"s.{c}" for c in cols_src)
    q = (f"MERGE INTO {t} AS t USING (SELECT {src}) AS s "
         "ON t.ANO = %s AND t.MES = %s AND LOWER(t.EMAIL) = LOWER(s.EMAIL) "
         f"WHEN MATCHED THEN UPDATE SET {set_upd} "
         f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})")
    salvos, erros = 0, []
    for linha in linhas:
        em = str(linha.get("EMAIL") or "").strip()
        if not em:
            continue
        valores = {c: (None if linha.get(c) in (None, "") else linha.get(c))
                   for c in _METAS_COLS}
        for c in ("META_NMRR_BRUTO", "META_EXPANSAO_BRUTO", "META_RENOVACAO_BRUTO",
                  "META_OTR_BRUTO", "META_NMRR", "META_EXPANSAO", "META_RENOVACAO",
                  "META_OTR", "PERCENTUAL_DESCONTO_METAS"):
            if valores[c] is not None:
                v = float(valores[c])
                valores[c] = round(v / 100, 6) if c == "PERCENTUAL_DESCONTO_METAS" else v
        params = [em] + [valores[c] for c in _METAS_COLS] + [ano, mes, ano, mes]
        try:
            with get_pool().session() as s:
                s.sql(q, tuple(params))
            salvos += 1
        except Exception as e:
            erros.append(f"Erro ao salvar {em}: {e}")
    invalidate_after_write()
    return salvos, erros


def metas_copiar_mes(ano: int, mes: int, ano_orig: int, mes_orig: int):
    t = tabela_escrita(META_CONSULTOR_TABELA)
    cols = ["EMAIL"] + _METAS_COLS
    col_sql = ", ".join(cols)
    q = (f"MERGE INTO {t} AS t USING ("
         f"  SELECT %s AS ANO, %s AS MES, {col_sql} FROM {t} WHERE ANO = %s AND MES = %s"
         ") AS s ON LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.ANO = s.ANO AND t.MES = s.MES "
         f"WHEN NOT MATCHED THEN INSERT (ANO, MES, {col_sql}) "
         f"VALUES (s.ANO, s.MES, {', '.join('s.' + c for c in cols)})")
    with get_pool().session() as s:
        s.sql(q, (ano, mes, ano_orig, mes_orig))
    invalidate_after_write()


CONFIG_TABELA = "SUPERSET.COMISSOES.CONFIG"


def config_salvar_atual(alterados: dict, usuario: str):
    """UPDATE do valor na vigência já existente (corrige erro de digitação;
    afeta todos os meses cobertos por ela). `alterados`: {chave: (valor, ano,
    mes)} da vigência atual de cada chave."""
    t = tabela_escrita(CONFIG_TABELA)
    with get_pool().session() as s:
        for chave, (valor, a_v, m_v) in alterados.items():
            s.sql(f"UPDATE {t} SET VALOR = %s, UPDATED_BY = %s, "
                  "UPDATED_AT = CURRENT_TIMESTAMP() "
                  "WHERE CHAVE = %s AND ANO = %s AND MES = %s",
                  (valor.strip(), usuario, chave, a_v, m_v))
    invalidate_after_write()


def config_nova_vigencia(alterados: dict, ano: int, mes: int, usuario: str):
    """Cria uma nova linha valendo a partir de (ano, mes); vigências
    anteriores continuam intocadas. `alterados`: {chave: valor}."""
    t = tabela_escrita(CONFIG_TABELA)
    with get_pool().session() as s:
        for chave, valor in alterados.items():
            s.sql(
                f"MERGE INTO {t} AS t USING (SELECT %s AS CHAVE, %s AS ANO, %s AS MES) AS s "
                "ON t.CHAVE = s.CHAVE AND t.ANO = s.ANO AND t.MES = s.MES "
                "WHEN MATCHED THEN UPDATE SET VALOR = %s, UPDATED_BY = %s, "
                "UPDATED_AT = CURRENT_TIMESTAMP() "
                f"WHEN NOT MATCHED THEN INSERT (CHAVE, ANO, MES, VALOR, DESCRICAO, "
                "UPDATED_BY, UPDATED_AT) VALUES (%s, %s, %s, %s, "
                f"(SELECT MAX(DESCRICAO) FROM {t} WHERE CHAVE = %s), %s, CURRENT_TIMESTAMP())",
                (chave, ano, mes, valor.strip(), usuario,
                 chave, ano, mes, valor.strip(), chave, usuario))
    invalidate_after_write()


def config_criar_chave(chave: str, valor: str, descricao: str, ano: int, mes: int, usuario: str):
    t = tabela_escrita(CONFIG_TABELA)
    with get_pool().session() as s:
        s.sql(
            f"MERGE INTO {t} AS t USING (SELECT %s AS CHAVE, %s AS ANO, %s AS MES) AS s "
            "ON t.CHAVE = s.CHAVE AND t.ANO = s.ANO AND t.MES = s.MES "
            "WHEN MATCHED THEN UPDATE SET VALOR = %s, DESCRICAO = %s, UPDATED_BY = %s, "
            "UPDATED_AT = CURRENT_TIMESTAMP() "
            "WHEN NOT MATCHED THEN INSERT (CHAVE, ANO, MES, VALOR, DESCRICAO, UPDATED_BY, UPDATED_AT) "
            "VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP())",
            (chave, ano, mes, valor.strip(), descricao.strip(), usuario,
             chave, ano, mes, valor.strip(), descricao.strip(), usuario))
    invalidate_after_write()
