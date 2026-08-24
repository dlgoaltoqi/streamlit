"""Exports xlsx — os mesmos DataFrames que o SiS gerava no df_download_link
(renomeados e formatados), servidos por endpoint real.
"""
import io

import pandas as pd
from openpyxl.styles import Font

from webapp.presentation import BASE_CONTRATO, BASE_NEG, brl, nome_negocio_limpo
from webapp.services import comissao_service as cs
from webapp.views.comissao_view import _REN, _REN_CANC

_FONTE_LINK = Font(color="0563C1", underline="single")


def xlsx_bytes(df: pd.DataFrame, sheet_name="Dados", links: dict = None) -> bytes:
    """`links`: {nome_da_coluna_final: [urls]} alinhado linha a linha com
    `df` (mesma ordem) — embute hyperlink de verdade na célula, igual ao
    painel (nome do negócio/cliente/contrato já É o link, sem uma coluna
    separada só com a URL crua)."""
    nome_aba = sheet_name[:31] or "Dados"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=nome_aba)
        if links:
            ws = xw.sheets[nome_aba]
            colunas = list(df.columns)
            for col_nome, urls in links.items():
                if col_nome not in colunas:
                    continue
                col_idx = colunas.index(col_nome) + 1  # openpyxl é 1-indexado
                for i, url in enumerate(urls):
                    if not url:
                        continue
                    cel = ws.cell(row=i + 2, column=col_idx)  # +2: cabeçalho + 1-index
                    cel.hyperlink = url
                    cel.font = _FONTE_LINK
    return buf.getvalue()


def _url_negocio(row, id_col="NEGOCIO"):
    x = row.get(id_col)
    if x is None or str(x).strip() in ("", "None"):
        return ""
    return f"{BASE_NEG}{str(x).split('.')[0]}"


def _label_negocio(row, id_col="NEGOCIO", nome_col="NOME_NEGOCIO"):
    x = row.get(id_col)
    if x is None or str(x).strip() in ("", "None"):
        return ""
    nid = str(x).split(".")[0]
    if nome_col in row.index:
        return nome_negocio_limpo(row.get(nome_col)) or nid
    return nid


def _url_contrato(row, id_col="ID_CONTRATO"):
    cid = row.get(id_col)
    if cid is None or str(cid).strip() in ("", "None"):
        return ""
    return f"{BASE_CONTRATO}{str(cid).split('.')[0]}"


def _label_contrato(row, num_col="NUM_CONTRATO", id_col="ID_CONTRATO"):
    num = row.get(num_col)
    num_s = "" if num is None or str(num) in ("None", "nan") else str(num)
    if num_s:
        return num_s
    cid = row.get(id_col)
    return "" if cid is None else str(cid).split(".")[0]


_BASE_CONTATO = "https://app.hubspot.com/contacts/44552714/record/0-1/"


def composicao(consultor, ano, mes):
    dados = cs.get_comissao(consultor, ano, mes)
    if "erro" in dados:
        return None, None, None
    comp = cs.get_composicao(consultor, ano, mes, dados.get("equipe", ""),
                             dados.get("is_gestor", False), dados.get("is_gd", False),
                             dados.get("is_b2g", False))
    if comp is None or comp.empty:
        return None, None, None
    d = comp.copy()
    if "VALOR" in d.columns:
        d["VALOR"] = d["VALOR"].apply(brl)
    elif "BOOKING" in d.columns:
        d["BOOKING"] = d["BOOKING"].apply(brl)
        if "ARR" in d.columns:
            d["ARR"] = d["ARR"].apply(brl)

    links = {}
    if "NEGOCIO" in d.columns:
        links["Negócio"] = d.apply(_url_negocio, axis=1).tolist()
        d["NEGOCIO"] = d.apply(_label_negocio, axis=1)
    if "NUM_CONTRATO" in d.columns:
        links["Número do Contrato"] = d.apply(_url_contrato, axis=1).tolist()
        d["NUM_CONTRATO"] = d.apply(_label_contrato, axis=1)
    if "LINK_CLIENTE" in d.columns:
        links["Cliente"] = d["LINK_CLIENTE"].fillna("").tolist()
    if "CONTATO" in d.columns:
        links["Contato"] = d["CONTATO"].apply(
            lambda x: (f"{_BASE_CONTATO}{str(x).split('.')[0]}"
                       if x is not None and str(x).strip() not in ("", "None") else "")
        ).tolist()
        d["CONTATO"] = d["CONTATO"].apply(
            lambda x: "" if x is None or str(x).strip() in ("", "None") else str(x).split(".")[0])

    d = d.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO")
                        if c in d.columns])
    return d.rename(columns=_REN), f"realizado_{mes:02d}_{ano}.xlsx", links


def bk_extra(consultor, ano, mes):
    dados = cs.get_comissao(consultor, ano, mes)
    if "erro" in dados:
        return None, None, None
    comp = cs.get_composicao_bk_extra(consultor, ano, mes, dados.get("equipe", ""),
                                      dados.get("is_gestor", False))
    if comp is None or comp.empty:
        return None, None, None
    d = comp.copy()
    d["BOOKING"] = d["BOOKING"].apply(brl)
    links = {}
    if "NEGOCIO" in d.columns:
        links["Negócio"] = d.apply(_url_negocio, axis=1).tolist()
        d["NEGOCIO"] = d.apply(_label_negocio, axis=1)
    return d.rename(columns=_REN), f"booking_extra_{mes:02d}_{ano}.xlsx", links


def carteira_am(consultor, ano, mes):
    df = cs.get_carteira_am(consultor, ano, mes)
    if df is None or df.empty:
        return None, None, None
    d = df.copy()
    d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
    links = {}
    if "LINK_CLIENTE" in d.columns:
        links["Cliente"] = d["LINK_CLIENTE"].fillna("").tolist()
    if "NUM_CONTRATO" in d.columns:
        # Nesta tabela o id do contrato vem na coluna "CONTRATO", não "ID_CONTRATO".
        links["Número do Contrato"] = d.apply(lambda r: _url_contrato(r, "CONTRATO"), axis=1).tolist()
        d["NUM_CONTRATO"] = d.apply(lambda r: _label_contrato(r, "NUM_CONTRATO", "CONTRATO"), axis=1)
    d = d.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "CONTRATO")
                        if c in d.columns])
    return d.rename(columns={
        "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
        "DATA_INICIO": "Início", "DATA_RENOVACAO": "Renovação", "MRR": "MRR",
    }), f"carteira_{mes:02d}_{ano}.xlsx", links


def canc(consultor, ano, mes):
    dados = cs.get_comissao(consultor, ano, mes)
    comp = cs.get_composicao_canc_recovery(consultor, ano, mes)
    if comp is None or comp.empty:
        return None, None, None
    pct_cr = dados.get("pct_canc_recovery") or 0
    d = comp.copy()
    d["COMISSAO"] = d["VALOR_AJUSTADO"].apply(lambda v: brl(round(float(v or 0) * pct_cr, 2)))
    for col in ("VALOR_ORIGINAL", "VALOR_AJUSTADO"):
        if col in d.columns:
            d[col] = d[col].apply(lambda v: brl(float(v or 0)))
    links = {}
    if "NEGOCIO" in d.columns:
        links["Negócio"] = d.apply(_url_negocio, axis=1).tolist()
        d["NEGOCIO"] = d.apply(_label_negocio, axis=1)
    if "CONTRATO" in d.columns:
        # CONTRATO já vem como o número puro (composicao_cancelamentos faz o
        # SPLIT_PART na origem); só falta o link, o label não muda.
        links["Contrato"] = d.apply(lambda r: _url_contrato(r, "ID_CONTRATO"), axis=1).tolist()
    d = d.drop(columns=[c for c in ("NOME_NEGOCIO", "ID_CONTRATO") if c in d.columns])
    return d.rename(columns=_REN_CANC), f"cancelamentos_{mes:02d}_{ano}.xlsx", links


def renovacoes_canc(consultor, ano, mes):
    dados = cs.get_comissao(consultor, ano, mes)
    comp = cs.get_composicao_renovacoes_canc(consultor, ano, mes)
    if comp is None or comp.empty:
        return None, None, None
    pct_cr = dados.get("pct_canc_recovery") or 0
    d = comp.copy()
    d["COMISSAO"] = d["BOOKING"].apply(lambda v: brl(round(float(v or 0) * pct_cr, 2)))
    for col in ("MRR", "BOOKING"):
        if col in d.columns:
            d[col] = d[col].apply(lambda v: brl(float(v or 0)))
    links = {}
    if "NEGOCIO" in d.columns:
        links["Negócio"] = d.apply(_url_negocio, axis=1).tolist()
        d["NEGOCIO"] = d.apply(_label_negocio, axis=1)
    if "LINK_CLIENTE" in d.columns:
        links["Cliente"] = d["LINK_CLIENTE"].fillna("").tolist()
    if "CONTRATO" in d.columns:
        links["Contrato"] = d.apply(lambda r: _url_contrato(r, "ID_CONTRATO"), axis=1).tolist()
    d = d.drop(columns=[c for c in ("NOME_NEGOCIO", "LINK_CLIENTE", "ID_CONTRATO")
                        if c in d.columns])
    return d.rename(columns={
        "NEGOCIO": "Negócio", "CLIENTE": "Cliente", "CONTRATO": "Contrato",
        "PIPELINE": "Pipeline", "FORMA_PAG": "Forma de Pagamento",
        "DATA_FECH": "Data de Fechamento", "MRR": "MRR", "BOOKING": "Booking",
        "COMISSAO": "Comissão",
    }), f"renovacoes_canc_{mes:02d}_{ano}.xlsx", links
