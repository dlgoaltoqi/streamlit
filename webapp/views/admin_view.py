"""Páginas administrativas em MODO LEITURA (Fase 4 da migração).

Cada página lista o conteúdo da tabela que administra, com filtro de período
quando a tabela é mensal. A EDIÇÃO chega na Fase 5 do plano (repos com binds,
validados em schema CLONE); até lá as alterações continuam sendo feitas no
painel Streamlit, e um aviso fixo deixa isso claro em cada página.
"""
from dataclasses import dataclass

import pandas as pd

from webapp.core.cache import RLS, ttl_cached
from webapp.db.pool import get_pool
from webapp.presentation import (botao_drive, brl, esc_attr, fmt_bool_br,
                                 fmt_cargo, fmt_datetime_br, fmt_int_br,
                                 fmt_num_br, grid_editavel_html, html_table_str,
                                 pct_fmt)


@dataclass(frozen=True)
class Campo:
    nome: str
    label: str
    tipo: str = "texto"  # texto | num | int


@dataclass(frozen=True)
class AdminPage:
    slug: str
    rotulo: str          # como aparece no seletor (mesmo emoji/nome do SiS)
    tabela: str
    mensal: bool = True  # tem colunas ANO/MES filtráveis
    ordem: str = ""      # ORDER BY opcional
    nota: str = ""       # texto de contexto sob o título
    # ── Escrita (Fase 5); vazio = página ainda somente leitura ──
    chaves: tuple = ()         # ((coluna, transform), ...); transform: "", "LOWER", "UPPER"
    chave_remocao: tuple = ()  # chave do DELETE (default = chaves)
    campos: tuple = ()         # campos editáveis (além das chaves)
    campos_chave: tuple = ()   # campos de chave digitáveis (fora ANO/MES)
    modo: str = "merge"        # merge | insert
    copia_mes: bool = False
    audit: str = "updated"     # updated | created | deals

    @property
    def editavel(self):
        return bool(self.chaves)


def _K(col, tr=""):
    return (col, tr)


ADMIN_PAGES = [
    AdminPage("cargos-otes", "🏷️ Cargos e OTEs", "SUPERSET.COMISSOES.CARGOS_OTES",
              chaves=(_K("ANO"), _K("MES"), _K("CARGO", "UPPER")),
              campos_chave=(Campo("CARGO", "Cargo"),),
              campos=(Campo("OTE", "OTE (R$)", "num"),), copia_mes=True),
    AdminPage("parametros", "⚙️ Parâmetros", "SUPERSET.COMISSOES.PARAMETROS"),
    AdminPage("multiplicadores", "✖️ Multiplicadores por Forma de Pag.",
              "SUPERSET.COMISSOES.ACEL_FORMA_PAGAMENTO",
              chaves=(_K("ANO"), _K("MES"), _K("EQUIPE")),
              campos_chave=(Campo("EQUIPE", "Equipe"),),
              campos=(Campo("A_VISTA", "À Vista", "num"),
                      Campo("CC_ATE_3X", "CC até 3x", "num"),
                      Campo("CC_ATE_12X", "CC até 12x", "num"),
                      Campo("RECORRENTE", "Recorrente", "num")), copia_mes=True),
    AdminPage("patamares", "📊 Patamares Saving", "SUPERSET.COMISSOES.PATAMARES_COMISSAO",
              chaves=(_K("ANO"), _K("MES"), _K("EQUIPE"), _K("PATAMAR")),
              campos_chave=(Campo("EQUIPE", "Equipe"),
                            Campo("PATAMAR", "Patamar (fração)", "num")),
              campos=(Campo("PERCENTUAL", "Percentual (fração)", "num"),), copia_mes=True),
    AdminPage("recuperacao-dividas", "🧾 Recuperação de Dívidas",
              "SUPERSET.COMISSOES.RECUPERACAO_DIVIDAS",
              chaves=(_K("ANO"), _K("MES"), _K("EMAIL", "LOWER")),
              campos_chave=(Campo("EMAIL", "E-mail"),),
              campos=(Campo("VALOR", "Valor (R$)", "num"),
                      Campo("PERCENTUAL_COMISSAO", "% Comissão (fração)", "num"))),
    AdminPage("deals-400k", "💎 Deals ≥ 400k", "SUPERSET.COMISSOES.DEALS_PAGOS_400K",
              mensal=False, audit="deals",
              chaves=(_K("ID_NEGOCIO"),),
              campos_chave=(Campo("ID_NEGOCIO", "ID do Negócio"),),
              campos=(Campo("OBSERVACAO", "Observação"),)),
    AdminPage("realizado-gd", "📋 Override de Realizado GD",
              "SUPERSET.COMISSOES.REALIZADO_GD_OVERRIDE",
              chaves=(_K("ANO"), _K("MES"), _K("EMAIL", "LOWER")),
              campos_chave=(Campo("EMAIL", "E-mail"),),
              campos=(Campo("REALIZADO_MANUAL", "Realizado (Opps)", "int"),
                      Campo("MOTIVO", "Motivo"))),
    AdminPage("ponderacoes-meta", "🎯 Ponderações Meta", "SUPERSET.COMISSOES.PONDERACOES_META",
              chaves=(_K("ANO"), _K("MES"), _K("EMAIL", "LOWER"), _K("TIPO_META")),
              campos_chave=(Campo("EMAIL", "E-mail"), Campo("TIPO_META", "Tipo de Meta")),
              campos=(Campo("PONDERACAO", "Ponderação (fração)", "num"),), copia_mes=True),
    AdminPage("acesso-rls", "🔒 Controle de Acesso", "SUPERSET.PARCIAL.PERMISSAO_RLS",
              chaves=(_K("ANO"), _K("MES"), _K("USUARIOEMAIL", "LOWER"),
                      _K("CONSULTOREMAIL", "LOWER")),
              campos_chave=(Campo("USUARIOEMAIL", "Usuário (quem vê)"),
                            Campo("CONSULTOREMAIL", "Consultor (visto)")),
              campos=(Campo("TIPOUSUARIO", "Tipo (Gestor/Consultor)"),), copia_mes=True),
    AdminPage("ajustes-pontuais", "✏️ Ajustes Pontuais", "SUPERSET.COMISSOES.AJUSTES_PONTUAIS",
              modo="insert", audit="created",
              chaves=(_K("ANO"), _K("MES"), _K("EMAIL", "LOWER")),
              chave_remocao=(_K("ID"),),
              campos_chave=(Campo("EMAIL", "E-mail"),),
              campos=(Campo("VALOR", "Valor (R$; negativo debita)", "num"),
                      Campo("DESCRICAO", "Descrição"),
                      Campo("REF_ANO", "Ref. Ano", "int"),
                      Campo("REF_MES", "Ref. Mês", "int"))),
    AdminPage("exportar-comissoes", "📥 Exportar Comissões", "SUPERSET.COMISSOES.FECHAMENTOS",
              mensal=False, ordem="ORDER BY DATA_FECHAMENTO DESC",
              nota="Histórico de fechamentos. Fechar/reabrir período e exportar "
                   "para a folha chegam na Fase 6 da migração; até lá, use o SiS."),
    AdminPage("metas", "🎯 Metas Consultores", "SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS",
              nota="Visão consolidada (precedência override > RI > form)."),
    AdminPage("pvt-overrides", "🔬 Overrides PVT", "SUPERSET.COMISSOES.PVT_OVERRIDES"),
    AdminPage("config", "🔧 Configurações", "SUPERSET.COMISSOES.CONFIG", mensal=False,
              ordem="ORDER BY CHAVE, ANO, MES",
              nota="Regras com vigência: cada linha vale a partir de (ANO, MES)."),
    AdminPage("exclusoes-carteira-am", "📂 Exclusões Carteira AM",
              "SUPERSET.COMISSOES.EXCLUSOES_CARTEIRA_AM", mensal=False,
              modo="insert", audit="created",
              chaves=(_K("ID_CONTRATO"),),
              chave_remocao=(_K("ID_CONTRATO"),),
              campos_chave=(Campo("ID_CONTRATO", "ID do Contrato"),),
              campos=(Campo("SOLICITADO_POR", "Solicitado por"),
                      Campo("MOTIVO", "Motivo"))),
    AdminPage("metas-override", "🎯 Override de Metas", "SUPERSET.COMISSOES.METAS_OVERRIDE"),
]
POR_SLUG = {p.slug: p for p in ADMIN_PAGES}


def chave_remocao(page):
    return page.chave_remocao or page.chaves

AVISO_LEITURA = (
    "<div class='aviso-azul'>🔒 <b>Somente leitura durante a migração.</b> "
    "Edições continuam no painel Streamlit; a edição aqui chega na Fase 5 "
    "(docs/21_migracao_web.md).</div>")
AVISO_ESCRITA_CLONE = (
    "<div class='aviso-ambar'>🧪 <b>Modo de teste (WRITES_TARGET=clone).</b> "
    "As escritas aqui vão para tabelas MIGTESTE_*, não para produção.</div>")


def parse_valor(raw: str, tipo: str):
    """Converte o texto de um <input> para o tipo do campo. Segue a convenção
    do projeto (vírgula decimal — ver memória feedback_decimal_separator):
    "1,25" e "1.25" são aceitos, sempre como vírgula na tela."""
    raw = (raw or "").strip()
    if tipo == "texto":
        return raw or None
    if raw == "":
        return None
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    if tipo == "int":
        return int(float(raw))
    return float(raw)


def fmt_valor(v, tipo: str) -> str:
    """Texto do input ao reabrir um valor existente (vírgula decimal)."""
    if v is None:
        return ""
    if tipo == "int":
        return str(int(v))
    if tipo == "num":
        return f"{float(v):.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(v)


def form_editar(page) -> str:
    """<Adicionar/Atualizar>: preencher a chave de um registro existente
    reaplica os valores (MERGE); uma chave nova cria o registro."""
    campos_html = "".join(
        f"<label>{c.label}<input type='text' name='{c.nome}' required></label>"
        for c in page.campos_chave)
    campos_html += "".join(
        f"<label>{c.label}<input type='text' name='{c.nome}'></label>"
        for c in page.campos)
    return (
        f"<form method='post' action='/admin/{page.slug}/salvar' class='filtros admin-form'>"
        f"{campos_html}"
        f"<button type='submit'>Salvar</button>"
        f"</form>")


def form_copiar(page) -> str:
    return (
        f"<form method='post' action='/admin/{page.slug}/copiar' style='margin:6px 0;'>"
        f"<button type='submit' class='btn-secundario'>📋 Copiar do mês anterior</button>"
        f"</form>")


def _form_remover(page, row) -> str:
    chaves = chave_remocao(page)
    campos = "".join(
        f"<input type='hidden' name='{col}' value='{esc_attr(row.get(col))}'>"
        for col, _ in chaves)
    return (
        f"<form method='post' action='/admin/{page.slug}/excluir' "
        f"onsubmit=\"return confirm('Remover este registro?')\">"
        f"{campos}<button type='submit' class='btn-remover'>🗑️</button></form>")

## ── Formatação genérica das tabelas admin (colunas cruas de 16 tabelas) ──────
#
# Cada página lista uma tabela SQL diferente sem um layout dedicado (esse é o
# ponto: uma tela genérica para 16 tabelas). Sem tratamento, os cabeçalhos
# ficam com o nome cru da coluna (PERCENTUAL_COMISSAO, UPDATED_AT...) e os
# valores saem sem formatação de domínio (fração 0-1 sem "%", timestamp sem
# dd/mm/aaaa). As classificações abaixo foram conferidas contra o schema real
# (INFORMATION_SCHEMA, 18/08/2026) e, para o que já tem precedente na tela
# Minha Comissão (ex.: MULT_ACELERADOR é exibido via pct_fmt em
# comissao_view.py), replicam esse precedente — "como é feito no Streamlit".

# Dinheiro (brl): nome exato OU contém MRR/OTR (cobre META_NMRR, REAL_OTR etc.
# sem listar cada variante _BRUTO).
_COLS_BRL = {
    "VALOR", "OTE", "OTE_VARIAVEL", "META_MRR", "META_MRR_BRUTO", "META_NMRR",
    "META_NMRR_BRUTO", "META_OTR", "META_OTR_BRUTO", "META_BRUTA", "REAL_NMRR",
    "REAL_OTR", "OTE_01_CHEIO", "OTE_02_CHEIO", "MRR", "BOOKING", "TOTAL",
    "VALOR_PAGO",
}
# Percentual (fração 0-1 → pct_fmt, igual à Minha Comissão): checado por nome
# exato OU substring PERCENTUAL/PONDERACAO. CLIFF_*/MULT_ACELERADOR entram
# porque comissao_view.py já os exibe via pct_fmt (ex.: "Acel de 115,00%").
_COLS_PERCENT = {
    "PATAMAR", "PERCENTUAL", "CLIFF_OTE_01", "CLIFF_OTE_02",
    "CLIFF_ACELERADOR_01", "MULT_ACELERADOR_01", "CLIFF_ACELERADOR_02",
    "MULT_ACELERADOR_02",
}
# Ano/mês/versão/id: são identificadores, não quantidades — "2.026" ou "v.1"
# atrapalhariam a leitura em vez de ajudar.
_COLS_SEM_SEPARADOR = {"ANO", "MES", "REF_ANO", "REF_MES", "ID", "VERSAO"}
# Timestamps que às vezes chegam como texto/objeto (nem sempre datetime64).
_COLS_DATA = {"UPDATED_AT", "CREATED_AT", "DATA_FECHAMENTO", "DATA_MARCACAO",
             "DATA_REGISTRO", "DESATIVADO_EM"}
_ENUM_STATUS = {"ATIVO": "Ativo", "SUBSTITUIDO": "Substituído", "REABERTO": "Reaberto"}

# Rótulo amigável para colunas sem Campo (specs cobrem só o que é editável;
# ANO/MES/UPDATED_AT/etc. aparecem em toda tabela e precisam de tradução aqui).
_RENOMEIA_COLUNA = {
    "ANO": "Ano", "MES": "Mês", "EMAIL": "E-mail", "CARGO": "Cargo",
    "EQUIPE": "Equipe", "OTE": "OTE", "VALOR": "Valor", "STATUS": "Status",
    "VERSAO": "Versão", "ID": "ID", "USUARIO": "Usuário",
    "USUARIOEMAIL": "Usuário", "CONSULTOREMAIL": "Consultor",
    "CONSULTOR": "Consultor", "TIPOUSUARIO": "Tipo de Usuário",
    "OBS": "Observação", "OBSERVACAO": "Observação", "MOTIVO": "Motivo",
    "DESCRICAO": "Descrição", "SOLICITADO_POR": "Solicitado Por",
    "UPDATED_BY": "Atualizado Por", "UPDATED_AT": "Atualizado Em",
    "CREATED_BY": "Criado Por", "CREATED_AT": "Criado Em",
    "DATA_MARCACAO": "Data de Marcação", "FECHAMENTO_ID": "ID do Fechamento",
    "DATA_FECHAMENTO": "Data de Fechamento", "N_PESSOAS": "Nº de Pessoas",
    "ID_NEGOCIO": "ID do Negócio", "ID_CONTRATO": "ID do Contrato",
    "REF_ANO": "Ref. Ano", "REF_MES": "Ref. Mês",
    "PERCENTUAL_COMISSAO": "% Comissão", "PATAMAR": "Patamar",
    "PERCENTUAL": "Percentual", "A_VISTA": "À Vista", "CC_ATE_3X": "CC até 3x",
    "CC_ATE_12X": "CC até 12x", "RECORRENTE": "Recorrente",
    "TIPO_META": "Tipo de Meta", "PONDERACAO": "Ponderação",
    "REALIZADO_MANUAL": "Realizado Manual", "SENIORIDADE": "Senioridade",
    "FONTE": "Fonte", "PERCENTUAL_DESCONTO_METAS": "% Desconto Metas",
    "META_MRR_BRUTO": "Meta MRR Bruta", "META_MRR": "Meta MRR",
    "META_NMRR_BRUTO": "Meta NMRR Bruta", "META_NMRR": "Meta NMRR",
    "META_OTR_BRUTO": "Meta OTR Bruta", "META_OTR": "Meta OTR",
    "META_EXPANSAO_BRUTO": "Meta Expansão Bruta", "META_EXPANSAO": "Meta Expansão",
    "META_RENOVACAO_BRUTO": "Meta Renovação Bruta", "META_RENOVACAO": "Meta Renovação",
    "META_REATIVACAO": "Meta Reativação", "META_DEVEDOR": "Meta Devedor",
    "REAL_NMRR": "Real NMRR", "REAL_OTR": "Real OTR",
    "CLIFF_OTE_01": "Cliff OTE 1", "CLIFF_OTE_02": "Cliff OTE 2",
    "CLIFF_ACELERADOR_01": "Cliff Acelerador 1",
    "MULT_ACELERADOR_01": "Multiplicador Acelerador 1",
    "CLIFF_ACELERADOR_02": "Cliff Acelerador 2",
    "MULT_ACELERADOR_02": "Multiplicador Acelerador 2",
    "PERCENTUAL_BOOKING_EXTRA": "% Booking Extra", "OTE_01_CHEIO": "OTE 1 Cheio",
    "OTE_02_CHEIO": "OTE 2 Cheio", "IS_GESTOR": "É Gestor",
    "IS_CANC_RECOVERY": "Recup. Cancelamento",
    "PERCENTUAL_CANC_RECOVERY": "% Recup. Cancelamento",
    "PERCENTUAL_PROTECAO": "% Proteção", "IS_PVT": "É PVT",
    "IS_TRIM_HABILITADO": "Trimestral Habilitado", "CHAVE": "Chave",
    "ATIVO": "Ativo", "META_BRUTA": "Meta Bruta",
    "DATA_REGISTRO": "Data de Registro", "DESATIVADO_POR": "Desativado Por",
    "DESATIVADO_EM": "Desativado Em",
}


def _nome_amigavel(page, col: str) -> str:
    """Reaproveita o Campo.label das specs de escrita (Fase 5); para o resto
    (colunas estruturais/auditoria, ou tabelas ainda sem spec) usa o dicionário
    acima e cai num fallback genérico (initcap por palavra) por último."""
    for c in page.campos_chave + page.campos:
        if c.nome == col:
            return c.label
    if col in _RENOMEIA_COLUNA:
        return _RENOMEIA_COLUNA[col]
    return " ".join(w.capitalize() for w in col.split("_") if w)


def _tipo_do_campo(page, col: str):
    for c in page.campos_chave + page.campos:
        if c.nome == col:
            return c.tipo
    return None


def _eh_booleano(serie) -> bool:
    if serie.dtype == bool:
        return True
    vistos = serie.dropna()
    return len(vistos) > 0 and vistos.map(lambda v: isinstance(v, bool)).all()


def _vazio(v) -> bool:
    """None ou NaN — cobre os dois jeitos de 'sem valor' que chegam do
    Snowflake/pandas (texto vem None; numérico vem NaN)."""
    try:
        return v is None or v != v
    except TypeError:
        return v is None


def _fmt_ou_vazio(v, fn):
    return "—" if _vazio(v) else fn(float(v))


def _formatar_coluna(page, col: str, serie) -> list:
    """Lista de células já formatadas para UMA coluna do DataFrame cru.

    Prioridade: booleano > data/hora > [dtype numérico: percentual > dinheiro
    > genérico inteiro/float] > cargo (siglas) > enum conhecido > texto como
    veio. O dtype numérico é checado ANTES de percentual/dinheiro por nome —
    "VALOR" é dinheiro em AJUSTES_PONTUAIS mas é TEXTO livre em CONFIG, e o
    nome sozinho não distingue os dois."""
    nome = col.upper()
    if _eh_booleano(serie):
        return [fmt_bool_br(v) for v in serie]
    if serie.dtype.kind == "M" or nome in _COLS_DATA:
        return [fmt_datetime_br(v) for v in serie]
    if serie.dtype.kind in "fiu":
        if nome in _COLS_PERCENT or "PERCENTUAL" in nome or "PONDERACAO" in nome:
            return [_fmt_ou_vazio(v, pct_fmt) for v in serie]
        if nome in _COLS_BRL or "MRR" in nome or "OTR" in nome:
            return [_fmt_ou_vazio(v, brl) for v in serie]
        sem_sep = nome in _COLS_SEM_SEPARADOR
        tipo_campo = _tipo_do_campo(page, col)
        amostra = [v for v in serie if not _vazio(v)]
        eh_inteiro = tipo_campo == "int" or (
            tipo_campo != "num" and amostra
            and all(float(v).is_integer() for v in amostra))
        if eh_inteiro:
            return [fmt_int_br(v, separador=not sem_sep) if not _vazio(v) else "—"
                    for v in serie]
        return [fmt_num_br(v, 2) for v in serie]
    if nome == "CARGO":
        return [fmt_cargo(v) if not _vazio(v) else "—" for v in serie]
    if nome == "STATUS":
        return [_ENUM_STATUS.get(str(v), str(v)) if not _vazio(v) else "—" for v in serie]
    return [("—" if _vazio(v) else str(v)) for v in serie]


@ttl_cached(RLS)
def _listar(tabela: str, mensal: bool, ordem: str, ano: int, mes: int):
    """Lê da mesma tabela para onde o admin_repo escreve (tabela_escrita):
    em produção é a tabela real (identidade); no gate de teste
    (WRITES_TARGET=clone) lê o clone MIGTESTE_*, senão a tela nunca
    mostraria o que acabou de ser salvo no clone."""
    from webapp.services.admin_repo import tabela_escrita
    t = tabela_escrita(tabela)
    with get_pool().session() as s:
        if mensal:
            df = s.sql(f"SELECT * FROM {t} WHERE ANO = %s AND MES = %s "
                       f"{ordem} LIMIT 1000", (ano, mes)).to_pandas()
        else:
            df = s.sql(f"SELECT * FROM {t} {ordem} LIMIT 1000").to_pandas()
    return df


# ── Grade editável de Parâmetros (porta de pages/11_Admin_Parametros.py) ─────

_PARAMETROS_GRID_COLS = [
    ("EMAIL", "E-mail", "texto"),
    ("CARGO", "Cargo", "texto"),
    ("IS_GESTOR", "Gestor", "bool"),
    ("IS_PVT", "PVT", "bool"),
    ("IS_TRIM_HABILITADO", "Trim. Habilitado", "bool"),
    ("CLIFF_OTE_01", "Cliff OTE 1 (%)", "num"),
    ("CLIFF_OTE_02", "Cliff OTE 2 (%)", "num"),
    ("CLIFF_ACELERADOR_01", "Cliff Acel. 1 (%)", "num"),
    ("MULT_ACELERADOR_01", "Mult. Acel. 1", "num"),
    ("CLIFF_ACELERADOR_02", "Cliff Acel. 2 (%)", "num"),
    ("MULT_ACELERADOR_02", "Mult. Acel. 2", "num"),
    ("PERCENTUAL_BOOKING_EXTRA", "% Booking Extra", "num"),
    ("OTE_01_CHEIO", "OTE 1 Cheio", "num"),
    ("OTE_02_CHEIO", "OTE 2 Cheio", "num"),
    ("PERCENTUAL_PROTECAO", "% Proteção", "num"),
    ("IS_CANC_RECOVERY", "Recup. Cancel.", "bool"),
    ("PERCENTUAL_CANC_RECOVERY", "% Recup. Cancel.", "num"),
]


@ttl_cached(RLS)
def _parametros_listar(ano: int, mes: int) -> pd.DataFrame:
    from webapp.services import admin_repo
    t = admin_repo.tabela_escrita(admin_repo.PARAMETROS_TABELA)
    cols = ", ".join(admin_repo._PARAMETROS_COLS)
    with get_pool().session() as s:
        return s.sql(
            f"SELECT EMAIL, {cols} FROM {t} WHERE ANO = %s AND MES = %s ORDER BY EMAIL",
            (ano, mes)).to_pandas()


def _parametros_grid_html(ano: int, mes: int, pode_editar: bool) -> list:
    from webapp.config import settings
    from webapp.services import admin_repo
    page = POR_SLUG["parametros"]
    editar_ativo = pode_editar and settings.writes_enabled
    b = [AVISO_ESCRITA_CLONE if editar_ativo and settings.writes_target == "clone"
         else AVISO_LEITURA]
    try:
        df = _parametros_listar(ano, mes)
    except Exception as e:
        return b + [f"<div class='aviso-ambar'>Erro ao listar: {e}</div>"]

    if not editar_ativo:
        if df.empty:
            return b + [f"<div class='caption'>Sem registros em {mes:02d}/{ano}.</div>"]
        d = pd.DataFrame({col: _formatar_coluna(page, col, df[col]) for col in df.columns},
                         index=df.index)
        d = d.rename(columns={c: _nome_amigavel(page, c) for c in df.columns})
        _dl = f"/export/drive/admin/parametros?ano={ano}&mes={mes}"
        b.append(f"<div style='display:flex;justify-content:space-between;"
                 f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                 f"{len(df)} registro(s)</span>{botao_drive(_dl)}</div>")
        b.append(html_table_str(d, scrollable=True, compact_headers=True))
        return b

    linhas = []
    for _, r in df.iterrows():
        linha = {"EMAIL": r["EMAIL"], "CARGO": r["CARGO"]}
        for c in admin_repo._PARAMETROS_COLS:
            if c == "CARGO":
                continue
            v = r[c]
            if c == "IS_TRIM_HABILITADO" and _vazio(v):
                v = True
            if c in admin_repo._PARAMETROS_PCT and not _vazio(v):
                v = round(float(v) * 100, 4)
            linha[c] = None if _vazio(v) else v
        linhas.append(linha)

    b.append(grid_editavel_html(
        "grid_parametros", _PARAMETROS_GRID_COLS, linhas,
        salvar_url=f"/admin/parametros/salvar-grade?ano={ano}&mes={mes}",
        voltar_url=f"/admin/parametros?ano={ano}&mes={mes}"))
    b.append(form_copiar(page))
    return b


# ── Metas: grade editável (pré-RI) ou composição somente-leitura (pós-RI) ────
# (porta de pages/21_Admin_Metas.py)

_METAS_GRID_COLS = [
    ("EMAIL", "E-mail", "texto"),
    ("EQUIPE", "Equipe", "texto"),
    ("SENIORIDADE", "Senioridade", "texto"),
    ("PERCENTUAL_DESCONTO_METAS", "% Desconto Metas", "num"),
    ("META_NMRR_BRUTO", "Meta NMRR Bruta", "num"),
    ("META_EXPANSAO_BRUTO", "Meta Expansão Bruta", "num"),
    ("META_RENOVACAO_BRUTO", "Meta Renovação Bruta", "num"),
    ("META_OTR_BRUTO", "Meta OTR Bruta", "num"),
    ("META_NMRR", "Meta NMRR", "num"),
    ("META_EXPANSAO", "Meta Expansão", "num"),
    ("META_RENOVACAO", "Meta Renovação", "num"),
    ("META_OTR", "Meta OTR", "num"),
]

# A partir de jul/2026 as metas vêm do Revenue Intelligence; ver
# docs/18_migracao_metas_ri.md (mesma regra de pages/21_Admin_Metas.py).
_RI_DESDE = (2026, 7)


@ttl_cached(RLS)
def _metas_listar(ano: int, mes: int) -> pd.DataFrame:
    from webapp.services import admin_repo
    t = admin_repo.tabela_escrita(admin_repo.META_CONSULTOR_TABELA)
    cols = ", ".join(admin_repo._METAS_COLS)
    with get_pool().session() as s:
        return s.sql(
            f"SELECT EMAIL, {cols} FROM {t} WHERE ANO = %s AND MES = %s ORDER BY EQUIPE, EMAIL",
            (ano, mes)).to_pandas()


@ttl_cached(RLS)
def _metas_composicao(ano: int, mes: int) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql("""
            SELECT CONSULTOR, EQUIPE, FONTE,
                   PERCENTUAL_DESCONTO_METAS,
                   META_MRR_BRUTO, META_MRR, META_OTR_BRUTO, META_OTR
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND MES = %s ORDER BY EQUIPE, CONSULTOR
        """, (ano, mes)).to_pandas()


@ttl_cached(RLS)
def _metas_pendencias(ano: int, mes: int) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql("""
            WITH metas AS (
                SELECT DISTINCT LOWER(CONSULTOR) AS EMAIL, EQUIPE
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = %s AND MES = %s AND CONSULTOR IS NOT NULL
            ),
            par AS (
                SELECT DISTINCT LOWER(EMAIL) AS EMAIL FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE ANO = %s AND MES = %s
            ),
            rls AS (
                SELECT DISTINCT LOWER(CONSULTOREMAIL) AS EMAIL
                FROM SUPERSET.PARCIAL.PERMISSAO_RLS
            )
            SELECT m.EMAIL, m.EQUIPE,
                   IFF(p.EMAIL IS NULL, '✗', '') AS SEM_PARAMETROS,
                   IFF(r.EMAIL IS NULL, '✗', '') AS SEM_RLS
            FROM metas m
            LEFT JOIN par p ON p.EMAIL = m.EMAIL
            LEFT JOIN rls r ON r.EMAIL = m.EMAIL
            WHERE p.EMAIL IS NULL OR r.EMAIL IS NULL
            ORDER BY m.EQUIPE, m.EMAIL
        """, (ano, mes, ano, mes)).to_pandas()


def _metas_grid_html(ano: int, mes: int, pode_editar: bool) -> list:
    from webapp.config import settings
    from webapp.services import admin_repo

    if (ano, mes) >= _RI_DESDE:
        b = [
            "<div class='aviso-azul'>A partir de <b>julho/2026</b> as metas dos "
            "consultores vêm de <b>Revenue Intelligence</b>, com complemento do "
            "formulário para quem não está lá (ver coluna <b>Fonte</b>).<br>"
            "Esta tela é somente visualização; edições devem ser feitas na origem "
            "(RI). Correções administrativas ficam em "
            "<b>SUPERSET.COMISSOES.METAS_OVERRIDE</b> e aparecem aqui com a fonte "
            "<b>Override</b>, vencendo o RI e o formulário.</div>"
        ]
        try:
            comp = _metas_composicao(ano, mes)
            pend = _metas_pendencias(ano, mes)
        except Exception as e:
            return b + [f"<div class='aviso-ambar'>Erro ao carregar dados: {e}</div>"]

        if not pend.empty:
            b.append(
                f"<div class='aviso-ambar'>⚠️ <b>{len(pend)} pessoa(s) com meta "
                "cadastrada mas com cadastro incompleto.</b><br>Sem Parâmetros a "
                "comissão não calcula; sem RLS a pessoa não acessa o painel.</div>")
            dpend = pd.DataFrame({
                "Consultor": pend["EMAIL"], "Equipe": pend["EQUIPE"],
                "Sem Parâmetros": pend["SEM_PARAMETROS"], "Sem RLS": pend["SEM_RLS"],
            })
            b.append(html_table_str(dpend, scrollable=True))

        if comp.empty:
            b.append("<div class='caption'>Nenhuma meta encontrada para este período.</div>")
            return b

        def _fmt_otr(row):
            v = row["META_OTR"]
            if _vazio(v) or not v:
                return "—"
            if str(row["EQUIPE"]).strip().upper() == "GD":
                return fmt_int_br(v)
            return brl(v)

        d = pd.DataFrame({
            "Consultor": comp["CONSULTOR"], "Equipe": comp["EQUIPE"], "Fonte": comp["FONTE"],
            "% Desconto": comp["PERCENTUAL_DESCONTO_METAS"].apply(
                lambda v: pct_fmt(float(v) / 100) if not _vazio(v) and float(v) > 0 else "—"),
            "Meta Bruta (MRR)": comp["META_MRR_BRUTO"].apply(
                lambda v: brl(v) if not _vazio(v) and v else "—"),
            "Meta Líquida (MRR)": comp["META_MRR"].apply(
                lambda v: brl(v) if not _vazio(v) and v else "—"),
            "Meta (OTR/Booking)": comp.apply(_fmt_otr, axis=1),
        })
        b.append(f"<div class='caption' style='margin-bottom:4px;'>"
                 f"{len(comp)} registro(s) em {mes:02d}/{ano}.</div>")
        b.append(html_table_str(d, scrollable=True))
        return b

    # Pré-RI: grade editável direta em META_CONSULTOR.
    page = POR_SLUG["metas"]
    editar_ativo = pode_editar and settings.writes_enabled
    b = [AVISO_ESCRITA_CLONE if editar_ativo and settings.writes_target == "clone"
         else AVISO_LEITURA]
    try:
        df = _metas_listar(ano, mes)
    except Exception as e:
        return b + [f"<div class='aviso-ambar'>Erro ao listar: {e}</div>"]

    if not editar_ativo:
        if df.empty:
            return b + [f"<div class='caption'>Sem registros em {mes:02d}/{ano}.</div>"]
        d = pd.DataFrame({col: _formatar_coluna(page, col, df[col]) for col in df.columns},
                         index=df.index)
        d = d.rename(columns={c: _nome_amigavel(page, c) for c in df.columns})
        _dl = f"/export/drive/admin/metas?ano={ano}&mes={mes}"
        b.append(f"<div style='display:flex;justify-content:space-between;"
                 f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                 f"{len(df)} registro(s)</span>{botao_drive(_dl)}</div>")
        b.append(html_table_str(d, scrollable=True, compact_headers=True))
        return b

    linhas = []
    for _, r in df.iterrows():
        linha = {"EMAIL": r["EMAIL"]}
        for c in admin_repo._METAS_COLS:
            v = r[c]
            if c == "PERCENTUAL_DESCONTO_METAS" and not _vazio(v):
                v = round(float(v) * 100, 4)
            linha[c] = None if _vazio(v) else v
        linhas.append(linha)

    b.append(grid_editavel_html(
        "grid_metas", _METAS_GRID_COLS, linhas,
        salvar_url=f"/admin/metas/salvar-grade?ano={ano}&mes={mes}",
        voltar_url=f"/admin/metas?ano={ano}&mes={mes}"))
    b.append(form_copiar(page))
    return b


# ── Config: regras com vigência (porta de pages/24_Admin_Config.py) ─────────

_MESES_ABREV_CFG = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
                    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"}


@ttl_cached(RLS)
def _config_vigentes(ano: int, mes: int) -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql("""
            SELECT CHAVE, VALOR, DESCRICAO, ANO, MES FROM (
                SELECT c.*, ROW_NUMBER() OVER (PARTITION BY CHAVE ORDER BY ANO DESC, MES DESC) AS rn
                FROM SUPERSET.COMISSOES.CONFIG c
                WHERE ANO * 100 + MES <= %s
            ) WHERE rn = 1 ORDER BY CHAVE
        """, (ano * 100 + mes,)).to_pandas()


@ttl_cached(RLS)
def _config_historico() -> pd.DataFrame:
    with get_pool().session() as s:
        return s.sql("""
            SELECT CHAVE, ANO, MES, VALOR, DESCRICAO, UPDATED_BY,
                   TO_VARCHAR(UPDATED_AT, 'DD/MM/YYYY HH24:MI') AS ATUALIZADO_EM
            FROM SUPERSET.COMISSOES.CONFIG ORDER BY CHAVE, ANO, MES
        """).to_pandas()


def _config_vigencias_html(ano: int, mes: int, pode_editar: bool) -> list:
    from webapp.config import settings
    editar_ativo = pode_editar and settings.writes_enabled
    b = [AVISO_ESCRITA_CLONE if editar_ativo and settings.writes_target == "clone"
         else AVISO_LEITURA]
    b.append(
        "<div class='caption' style='margin-bottom:8px;'>Cada valor vale "
        "<b>a partir</b> de um mês (vigência). O cálculo de um mês usa a "
        "vigência mais recente até ele: alterar uma regra daqui para frente "
        "não reescreve meses passados, e meses fechados (snapshot) são "
        "imunes. Chave ausente usa o padrão do código. <b>Atenção:</b> "
        "vários valores alteram comissão do mês aberto.</div>")

    try:
        vig = _config_vigentes(ano, mes)
    except Exception as e:
        return b + [f"<div class='aviso-ambar'>Erro ao listar: {e}</div>"]

    if vig.empty:
        return b + ["<div class='caption'>Nenhuma configuração vigente para este período.</div>"]

    if not editar_ativo:
        d = pd.DataFrame({
            "Chave": vig["CHAVE"], "Valor": vig["VALOR"],
            "Descrição": vig["DESCRICAO"].fillna(""),
            "Vigente desde": vig.apply(
                lambda r: f"{_MESES_ABREV_CFG.get(int(r['MES']), r['MES'])}/{int(r['ANO'])}", axis=1),
        })
        _dl = f"/export/drive/admin/config?ano={ano}&mes={mes}"
        b.append(f"<div style='display:flex;justify-content:space-between;"
                 f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                 f"{len(vig)} chave(s) vigente(s)</span>{botao_drive(_dl)}</div>")
        b.append(html_table_str(d, scrollable=True))
        return b

    linhas_html = "".join(
        "<div style='display:flex;gap:12px;align-items:flex-start;padding:6px 0;"
        "border-bottom:1px solid #e5e7eb;'>"
        f"<div style='flex:0 0 260px;'><span style='font-weight:700;color:#1a1a1a;'>"
        f"{esc_attr(r['CHAVE'])}</span><br>"
        f"<span class='caption'>{esc_attr(r['DESCRICAO'] or '')} — vigente desde "
        f"{_MESES_ABREV_CFG.get(int(r['MES']), r['MES'])}/{int(r['ANO'])}</span></div>"
        f"<input type='text' data-chave='{esc_attr(r['CHAVE'])}' "
        f"data-ano='{int(r['ANO'])}' data-mes='{int(r['MES'])}' "
        f"data-original='{esc_attr(r['VALOR'] or '')}' value='{esc_attr(r['VALOR'] or '')}' "
        "style='flex:1;border:1px solid #9ca3af;border-radius:6px;padding:7px 10px;'>"
        "</div>"
        for _, r in vig.iterrows())

    # cfgSalvar é global, definida em webapp/static/js/admin_grade.js (um
    # <script> embutido aqui não executaria: este HTML chega via innerHTML).
    mes_label = f"{_MESES_ABREV_CFG.get(mes, mes)}/{ano}"
    b.append(
        f"<div id='config_linhas'>{linhas_html}</div>"
        "<div style='margin:12px 0;display:flex;gap:10px;flex-wrap:wrap;align-items:center;'>"
        f"<button type='button' onclick=\"cfgSalvar('atual', {ano}, {mes})\" "
        "class='btn-secundario' title='Corrige o valor da vigência já existente; "
        "afeta todos os meses cobertos por ela.'>💾 Salvar na vigência atual</button>"
        f"<button type='button' onclick=\"cfgSalvar('nova', {ano}, {mes})\" "
        "style='background:#083b8a;color:#ffffff;border:none;border-radius:6px;"
        "padding:8px 16px;font:inherit;font-weight:600;cursor:pointer;' "
        "title='Cria novas linhas valendo do mês selecionado em diante; os meses "
        f"anteriores continuam com a vigência antiga.'>📅 Nova vigência a partir de "
        f"{mes_label}</button>"
        "<span id='config_status' class='caption'></span></div>")

    b.append(
        "<hr><div style='font-weight:700;margin-bottom:6px;'>Adicionar nova chave</div>"
        "<form method='post' action='/admin/config/criar-chave' class='filtros admin-form'>"
        f"<input type='hidden' name='ano' value='{ano}'>"
        f"<input type='hidden' name='mes' value='{mes}'>"
        "<label>Chave<input type='text' name='chave' "
        "placeholder='ex.: gestor_equipes.fulano@altoqi.com.br' required></label>"
        "<label>Valor<input type='text' name='valor' placeholder='ex.: FSB,Farmer' required></label>"
        "<label>Descrição<input type='text' name='descricao' "
        "placeholder='O que esta chave controla'></label>"
        f"<button type='submit'>Criar com vigência {mes_label}</button>"
        "</form>")

    try:
        hist = _config_historico()
        dh = pd.DataFrame({
            "Chave": hist["CHAVE"],
            "Vigência": hist.apply(
                lambda r: f"{_MESES_ABREV_CFG.get(int(r['MES']), r['MES'])}/{int(r['ANO'])}", axis=1),
            "Valor": hist["VALOR"], "Alterado por": hist["UPDATED_BY"].fillna(""),
            "Em": hist["ATUALIZADO_EM"].fillna(""),
        })
        b.append(
            "<details class='exp' style='margin-top:14px;'>"
            "<summary>Histórico de vigências (todas as linhas)</summary>"
            f"<div class='exp-body'>{html_table_str(dh, scrollable=True)}</div></details>")
    except Exception as e:
        b.append(f"<div class='aviso-ambar'>Erro ao carregar histórico: {e}</div>")

    return b


def montar_admin(slug: str, ano: int, mes: int, pode_editar: bool = False):
    if slug == "parametros":
        return _parametros_grid_html(ano, mes, pode_editar)
    if slug == "metas":
        return _metas_grid_html(ano, mes, pode_editar)
    if slug == "config":
        return _config_vigencias_html(ano, mes, pode_editar)
    from webapp.config import settings
    page = POR_SLUG[slug]
    editar_ativo = pode_editar and page.editavel and settings.writes_enabled
    b = [AVISO_ESCRITA_CLONE if editar_ativo and settings.writes_target == "clone"
         else AVISO_LEITURA]
    if page.nota:
        b.append(f"<div class='caption' style='margin-bottom:8px;'>{page.nota}</div>")
    if editar_ativo:
        b.append(form_editar(page))
        if page.copia_mes:
            b.append(form_copiar(page))
    try:
        df = _listar(page.tabela, page.mensal, page.ordem, ano, mes)
    except Exception as e:
        return b + [f"<div class='aviso-ambar'>Erro ao listar {page.tabela}: {e}</div>"]
    if df is None or df.empty:
        periodo = f" em {mes:02d}/{ano}" if page.mensal else ""
        return b + [f"<div class='caption'>Sem registros{periodo}.</div>"]
    if editar_ativo:
        raw_rows = df.to_dict("records")
    d = pd.DataFrame({col: _formatar_coluna(page, col, df[col]) for col in df.columns},
                     index=df.index)
    if editar_ativo:
        d[""] = [_form_remover(page, r) for r in raw_rows]
    d = d.rename(columns={c: _nome_amigavel(page, c) for c in df.columns})
    _dl = f"/export/drive/admin/{slug}?ano={ano}&mes={mes}"
    b.append(f"<div style='display:flex;justify-content:space-between;"
             f"align-items:center;margin-bottom:4px;'><span class='caption'>"
             f"{len(df)} registro(s)"
             f"{' (limitado a 1000)' if len(df) == 1000 else ''}</span>"
             f"{botao_drive(_dl)}</div>")
    b.append(html_table_str(d, scrollable=True, compact_headers=len(d.columns) > 6))
    return b
