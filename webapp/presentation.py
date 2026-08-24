"""Componentes visuais do painel SEM Streamlit.

Porta fiel de utils/ui.py (brl, pct_fmt, stat, stat_pair, formula,
html_table_str) e dos helpers de link HubSpot de _comissao.py: as funções
devolvem strings HTML — no SiS elas eram entregues ao st.markdown, aqui vão
direto ao template. Mesmos estilos inline para paridade visual pixel a pixel.
"""
import re

# ── Paleta AltoQi (cópia de utils/ui.py:480-487) ─────────────────────────────
HIGHLIGHT_BORDER = "#0c5a93"
HIGHLIGHT_VAL = "#1ecb78"
CARD_BORDER = "rgba(128,128,128,0.25)"
CARD_BG = "#ffffff"
CARD_SHADOW = "rgba(15,23,42,0.10)"
TABLE_BORDER_ROW = "#d1d5db"
HEADER_GRADIENT = "linear-gradient(to right,#083b8a,#0c5a93 40%,#129b92 70%,#1ecb78)"


def brl(v):
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct_fmt(v):
    if v is None:
        return "—"
    return f"{v:.2%}".replace(".", ",")


def fmt_num_br(v, casas=2):
    """Número genérico com separador de milhar '.' e decimal ',' (mesma
    convenção do brl(), sem o prefixo R$) — para campos numéricos que não
    são dinheiro nem percentual."""
    try:
        if v is None or v != v:  # None ou NaN
            return "—"
    except TypeError:
        pass
    return f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int_br(v, separador=True):
    """Inteiro com separador de milhar '.' (ou sem, para ano/mês/id/versão,
    onde o separador atrapalha a leitura em vez de ajudar)."""
    try:
        if v is None or v != v:
            return "—"
    except TypeError:
        pass
    n = int(round(float(v)))
    return f"{n:,}".replace(",", ".") if separador else str(n)


def fmt_datetime_br(v):
    """dd/mm/aaaa hh:mm:ss a partir de Timestamp/datetime/string ISO."""
    if v is None:
        return "—"
    import pandas as pd
    try:
        ts = pd.Timestamp(v)
        if pd.isna(ts):
            return "—"
        return ts.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(v)


def fmt_bool_br(v):
    if v is None:
        return "—"
    return "Sim" if bool(v) else "Não"


# Siglas que devem ficar maiúsculas dentro de um cargo (porta de
# _comissao.py:_fmt_cargo — fonte única; comissao_view e equipe_view usam
# esta mesma função para não divergir).
SIGLAS_RE = re.compile(r"\b(II|SDR|JR|PL|SR|FSB)\b", re.IGNORECASE)


def fmt_cargo(s):
    return SIGLAS_RE.sub(lambda m: m.group().upper(), str(s or "").title())


def stat(label, value, highlight=False, min_h=94, val_color=None):
    """Card estatístico (utils/ui.py:502) — retorna o HTML em vez de renderizar."""
    if highlight:
        border = f"2px solid {HIGHLIGHT_BORDER}"
        valcolor = val_color if val_color is not None else HIGHLIGHT_VAL
        valsize = "1.6rem"
    else:
        border = f"1px solid {CARD_BORDER}"
        valcolor = val_color if val_color is not None else "#1a1a1a"
        valsize = "1.35rem"
    return (
        f"<div style='border:{border};border-radius:14px;padding:14px 10px;"
        f"box-shadow:0 3px 10px {CARD_SHADOW};text-align:center;"
        f"background:{CARD_BG};min-height:{min_h}px;"
        "display:flex;flex-direction:column;justify-content:center;'>"
        "<div style='font-size:0.95rem;font-weight:600;color:#555555;margin-bottom:4px;'>"
        f"{label}</div>"
        f"<div style='font-size:{valsize};font-weight:700;line-height:1.15;color:{valcolor};"
        f"word-break:break-word;'>{value}</div>"
        "</div>"
    )


def stat_pair(top_label, top_value, bot_label, bot_value,
              top_highlight=False, bot_highlight=False, h_outer=228, gap=12):
    """Dois cards empilhados de altura igual (utils/ui.py:528)."""
    def _cs(hl):
        if hl:
            return f"2px solid {HIGHLIGHT_BORDER}", HIGHLIGHT_VAL, "1.6rem"
        return f"1px solid {CARD_BORDER}", "#1a1a1a", "1.35rem"

    def _card(b, vc, vs, label, value):
        return (
            f"<div style='flex:1;box-sizing:border-box;border:{b};border-radius:14px;"
            f"padding:14px 10px;box-shadow:0 3px 10px {CARD_SHADOW};text-align:center;"
            f"background:{CARD_BG};"
            "display:flex;flex-direction:column;justify-content:center;'>"
            "<div style='font-size:0.95rem;font-weight:600;color:#555555;margin-bottom:4px;'>"
            f"{label}</div>"
            f"<div style='font-size:{vs};font-weight:700;line-height:1.15;color:{vc};"
            f"word-break:break-word;'>{value}</div>"
            "</div>"
        )

    tb, tvc, tvs = _cs(top_highlight)
    bb, bvc, bvs = _cs(bot_highlight)
    return (
        f"<div style='display:flex;flex-direction:column;gap:{gap}px;height:{h_outer}px;'>"
        + _card(tb, tvc, tvs, top_label, top_value)
        + _card(bb, bvc, bvs, bot_label, bot_value)
        + "</div>"
    )


def formula(text):
    return (f"<div style='font-size:0.72rem;font-weight:600;color:#374151;"
            f"text-align:center;margin-top:6px;'>{text}</div>")


def html_table_str(df, scrollable=False, subheader=None, compact_headers=False,
                   row_search_data=None, table_id=None):
    """Cópia fiel de utils/ui.py:574 (células aceitam HTML — links HubSpot).

    Cabeçalho SEMPRE quebra em até 2 linhas (nunca 1 palavra cortada, nunca
    mais que 2 linhas — line-clamp garante o teto); compact_headers só
    aperta o padding/min-width para tabelas com muitas colunas."""
    # -webkit-line-clamp exige display:-webkit-box no elemento clampado, o
    # que sobrescreve o display:table-cell do <th> e quebra a tabela (linha
    # do cabeçalho vira uma coluna empilhada). Por isso o clamp vai num
    # <div> interno, nunca no <th> em si.
    _th_clamp = ("white-space:normal;word-break:break-word;line-height:1.25;"
                 "display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;"
                 "overflow:hidden;")
    if compact_headers:
        _th_style = (
            "padding:8px 6px;text-align:center;"
            "min-width:64px;background:transparent;color:#ffffff;"
            "font-weight:700;border:none;"
        )
        _td_pad = "6px 6px"
    else:
        _th_style = (
            "padding:8px 12px;text-align:center;"
            "min-width:84px;background:transparent;color:#ffffff;"
            "font-weight:700;border:none;"
        )
        _td_pad = "6px 12px"
    th = "".join(
        f"<th style='{_th_style}'><div style='{_th_clamp}'>{h}</div></th>"
        for h in df.columns
    )
    rows = ""
    if subheader is not None:
        cat_tds = "".join(
            f"<td style='padding:3px 12px;text-align:center;white-space:nowrap;"
            f"background:#eef2f7;font-weight:600;font-size:0.75rem;color:#555;font-style:italic;"
            f"border-bottom:2px solid #c7d4e8;'>{subheader.get(h, '')}</td>"
            for h in df.columns
        )
        rows += f"<tr>{cat_tds}</tr>"
    for i, (_, r) in enumerate(df.iterrows()):
        tds = "".join(
            f"<td style='padding:{_td_pad};text-align:center;white-space:nowrap;"
            f"border-top:none;border-left:none;border-right:none;"
            f"border-bottom:1px solid {TABLE_BORDER_ROW};'>{v}</td>"
            for v in r
        )
        search_attr = ""
        if row_search_data and i < len(row_search_data):
            search_attr = f" data-search='{esc_attr(str(row_search_data[i]))}'"
        rows += f"<tr{search_attr}>{tds}</tr>"
    id_attr = f" id='{esc_attr(table_id)}'" if table_id else ""
    table = (
        f"<table{id_attr} style='width:100%;border-collapse:collapse;font-size:0.9rem;color:#1a1a1a;'>"
        f"<thead><tr style='background:{HEADER_GRADIENT};'>{th}</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    if scrollable:
        table = f"<div style='overflow-x:auto;'>{table}</div>"
    return table


def grid_editavel_html(grid_id, colunas, linhas, salvar_url, voltar_url):
    """Equivalente sem Streamlit do st.data_editor(num_rows="dynamic"):
    tabela com um <input>/<checkbox> por célula, adicionar/remover linha no
    cliente e um único POST em JSON com tudo ao salvar — o servidor decide o
    que mudou e o que precisa ser removido.

    O motor JS (gridAdd/gridSalvar) mora em webapp/static/js/admin_grade.js,
    carregado normalmente pela página (admin.html): um <script> embutido
    aqui nunca executaria, porque este HTML é injetado via innerHTML pelo
    fetch de _loader.html, e navegadores ignoram <script> inserido assim.
    A tabela carrega as colunas via data-cols; os botões só chamam as
    funções globais.

    colunas: lista de (nome, label, tipo), tipo em {"texto","num","bool"}.
    linhas: lista de dicts já em unidade de EXIBIÇÃO (percentual já ×100,
    como o SiS mostra no editor)."""
    import json

    def _input_html(nome, tipo, valor):
        if tipo == "bool":
            checked = "checked" if valor else ""
            return (f"<input type='checkbox' data-col='{nome}' {checked}>")
        tipo_html = "number" if tipo == "num" else "text"
        step = " step='any'" if tipo == "num" else ""
        v = "" if valor is None else esc_attr(valor)
        return (f"<input type='{tipo_html}' data-col='{nome}' value='{v}'{step} "
                "style='width:100%;min-width:80px;border:1px solid #d1d5db;"
                "border-radius:4px;padding:4px 6px;font:inherit;'>")

    ths = "".join(
        f"<th style='padding:6px 8px;text-align:center;color:#ffffff;"
        f"font-weight:700;font-size:0.82rem;'>{label}</th>"
        for _, label, _ in colunas) + "<th style='background:transparent;'></th>"

    def _linha_html(linha):
        tds = "".join(
            f"<td style='padding:2px;text-align:{'center' if tipo == 'bool' else 'left'};'>"
            f"{_input_html(nome, tipo, linha.get(nome))}</td>"
            for nome, _, tipo in colunas)
        return (f"<tr>{tds}<td style='text-align:center;padding:2px;'>"
                "<button type='button' onclick=\"this.closest('tr').remove()\" "
                "class='btn-remover'>🗑️</button></td></tr>")

    linhas_html = "".join(_linha_html(l) for l in linhas)
    cols_json = json.dumps([{"nome": n, "tipo": t} for n, _, t in colunas])

    return (
        "<div style='overflow-x:auto;'>"
        f"<table id='{grid_id}' data-cols='{esc_attr(cols_json)}' "
        "style='width:100%;border-collapse:collapse;font-size:0.85rem;'>"
        f"<thead><tr style='background:{HEADER_GRADIENT};'>{ths}</tr></thead>"
        f"<tbody>{linhas_html}</tbody></table></div>"
        "<div style='margin:10px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;'>"
        f"<button type='button' class='btn-secundario' onclick=\"gridAdd('{grid_id}')\">"
        "+ Adicionar linha</button>"
        f"<button type='button' onclick=\"gridSalvar('{grid_id}', '{esc_attr(salvar_url)}', "
        f"'{esc_attr(voltar_url)}')\" "
        "style='background:#083b8a;color:#ffffff;border:none;border-radius:6px;"
        "padding:8px 16px;font:inherit;font-weight:600;cursor:pointer;'>"
        "💾 Salvar alterações</button>"
        f"<span id='{grid_id}_status' class='caption'></span></div>"
    )


# ── Links HubSpot (porta de _comissao.py:114-150) ────────────────────────────
BASE_NEG = "https://app.hubspot.com/contacts/44552714/record/0-3/"
BASE_CONTRATO = "https://app.hubspot.com/contacts/44552714/record/2-25175098/"

# Limite do nome do negócio nas tabelas largas (nome completo fica no title)
NEG_MAX_LEN = 30


def esc_attr(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def link_contrato(cid, numero):
    num = "" if numero is None or str(numero) in ("None", "nan") else str(numero)
    if cid is None or str(cid).strip() in ("", "None"):
        return num
    cid_s = str(cid).split(".")[0]
    return f"<a href='{BASE_CONTRATO}{cid_s}' target='_blank'>{num or cid_s}</a>"


def nome_negocio_limpo(s):
    """Nome do negócio sem as partes de ruído separadas por '||'.

    O HubSpot embute ids e datas no nome com '||' em posições variadas
    ('123 || nome', 'R.aut || 123 || nome', 'nome ||', 'nome || 04/12/2025'),
    então filtrar só a última parte devolvia id ou data. Aqui descartam-se as
    partes vazias, só-número e só-data e fica a mais longa (a descritiva)."""
    s = str(s or "").strip()
    if "||" not in s:
        return re.sub(r"\s+", " ", s)
    partes = [p.strip() for p in s.split("||")]
    validas = [p for p in partes
               if p and not re.fullmatch(r"\d+", p)
               and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", p)]
    escolhido = max(validas, key=len) if validas else s
    return re.sub(r"\s+", " ", escolhido)


def link_neg_nome(nid, nome, max_len=45):
    """Link HubSpot para negócio com o nome limpo truncado como texto
    (nome completo no title)."""
    nid_s = str(nid or "").split(".")[0].strip()
    if not nid_s or nid_s in ("", "None"):
        return ""
    nome_limpo = nome_negocio_limpo(nome) or nid_s
    label = (nome_limpo[:max_len] + "…") if len(nome_limpo) > max_len else nome_limpo
    return (f"<a href='{BASE_NEG}{nid_s}' target='_blank' "
            f"title='{esc_attr(nome_limpo)}'>{esc_attr(label)}</a>")


CLIENTE_MAX_LEN = 35


def link_cliente(link, nome, max_len=CLIENTE_MAX_LEN):
    """Nome do cliente com link HubSpot; 'N/A'/vazio vira travessao.

    Razão social truncada com '…' e nome completo no title — sem isso um
    cliente com nome muito longo estoura a coluna (mesmo cuidado que
    link_neg_nome já tinha para nome de negócio)."""
    nome_s = str(nome or "").strip()
    if nome_s.upper() in ("", "N/A", "NA", "NAN", "NONE"):
        return "—"
    label = (nome_s[:max_len] + "…") if len(nome_s) > max_len else nome_s
    if link is None or str(link).strip() in ("", "None", "nan"):
        return f"<span title='{esc_attr(nome_s)}'>{esc_attr(label)}</span>"
    return (f"<a href='{link}' target='_blank' title='{esc_attr(nome_s)}'>"
            f"{esc_attr(label)}</a>")


def botao_drive(url, label="Exportar p/ Drive"):
    """Variante do botão de exportação que sobe o arquivo como Google Sheets
    no Drive do próprio usuário (OAuth por usuário, escopo drive.file — POC,
    ver webapp/services/drive_service.py). target='_blank' porque, ao
    contrário do download .xlsx, o clique navega de verdade (consentimento
    do Google + a planilha aberta no final) — sem isso o painel sai da tela."""
    return (f"<a href='{url}' target='_blank' style=\"display:inline-block;"
            f"background:#0f9d58;"
            f"color:#ffffff;padding:6px 14px;border-radius:6px;font-size:0.85rem;"
            f"font-weight:600;text-decoration:none;margin-left:8px;\">{label}</a>")
