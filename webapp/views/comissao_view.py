"""Blocos HTML da tela Minha Comissão — porta 1:1 de _comissao.py.

Cada função devolve strings HTML montadas com webapp/presentation.py (os
mesmos componentes do SiS). A rota junta os blocos e o template só imprime.
Fatia da Fase 4: downloads xlsx e buscas nas tabelas chegam com o htmx.
"""
import pandas as pd

from webapp.core.periods import MESES_NOME as MESES, hist_pares
from webapp.presentation import (botao_drive, brl, fmt_cargo,
                                 formula, html_table_str, link_cliente,
                                 link_contrato, link_neg_nome, pct_fmt, stat,
                                 stat_pair, NEG_MAX_LEN, BASE_NEG)
from webapp.services import comissao_service as cs

_H1 = 124
_H_BIG = 200

_REN = {
    "CONSULTOR": "Consultor", "NEGOCIO": "Negócio", "CLIENTE": "Cliente",
    "NUM_CONTRATO": "Número do Contrato",
    "PRODUTO": "Produto", "PIPELINE": "Pipeline", "FORMA_PAG": "Forma de Pagamento",
    "VALOR": "MRR", "BOOKING": "Booking", "CONTATO": "Contato",
    "DATA_FMT": "Data da Qualificação",
    "DATA_FECH": "Data de Fechamento",
}
_REN_CANC = {
    "ANO": "Ano", "MES": "Mês", "CONSULTORA": "Consultora",
    "NEGOCIO": "Negócio", "CONTRATO": "Contrato",
    "DATA_FECHAMENTO": "Data de Fechamento",
    "DATA_INICIO": "Data de Início",
    "DATA_RENOVACAO": "Data de Renovação",
    "VALOR_ORIGINAL": "Valor Original",
    "VALOR_AJUSTADO": "Valor Ajustado",
    "COMISSAO": "Comissão",
}


def _link_neg(x):
    if x is None or str(x).strip() in ("", "None"):
        return ""
    nid = str(x).split(".")[0]
    return f"<a href='{BASE_NEG}{nid}' target='_blank'>{nid}</a>"


def _busca_input(table_id):
    return (
        f"<input type='text' data-busca-target='{table_id}' placeholder='Cliente, negócio, contrato…' "
        "style='width:100%;box-sizing:border-box;padding:6px 10px;border:1px solid #d1d5db;"
        "border-radius:6px;font-size:0.88rem;margin-bottom:6px;' />"
    )


# ── Primitivos de layout (equivalentes de st.columns/expander/divider) ───────

def linha(cards, cls):
    return f"<div class='row {cls}'>{''.join(cards)}</div>"


def celula(*parts):
    return f"<div>{''.join(parts)}</div>"


def expander(titulo, corpo, aberto=False):
    return (f"<details class='exp'{' open' if aberto else ''}><summary>{titulo}</summary>"
            f"<div class='exp-body'>{corpo}</div></details>")


def divisor():
    return "<hr>"


def secao(titulo):
    return f"<div class='titulo-secao'>{titulo}</div>"


def caption(texto):
    return f"<div class='caption'>{texto}</div>"


def aviso_ambar(html):
    return f"<div class='aviso-ambar'>{html}</div>"


def aviso_azul(html):
    return f"<div class='aviso-azul'>{html}</div>"


def _tabela_ou_caption(df, vazio="Sem dados."):
    return html_table_str(df) if df is not None and not df.empty else caption(vazio)


def _cliente_link_col(d):
    d["CLIENTE"] = d.apply(
        lambda r: link_cliente(r.get("LINK_CLIENTE"), r.get("CLIENTE")), axis=1)
    return d


# ── Layout A: Account Manager (porta de _comissao.py:162-466) ────────────────

def blocos_am(dados, email, ano, mes):
    b = []
    _inicial = dados.get("am_mrr_inicial") or 0.0
    _novos = dados.get("am_novos_negocios") or 0.0
    _upsells = dados.get("am_upsells") or 0.0
    _renov_delta = dados.get("am_renovacoes_delta") or 0.0
    _impulso_delta = dados.get("am_impulsos_delta") or 0.0
    _churn = dados.get("am_churn_mrr") or 0.0
    _evoluido = dados.get("am_mrr_evoluido") or 0.0
    _nrr = dados.get("am_nrr")
    _cresc = (_nrr - 1) if _nrr is not None else None
    _meta = dados.get("am_meta_nrr")

    # Resumo (6 cards)
    cards = [
        celula(stat("Cargo", dados["cargo"], min_h=_H1)),
        celula(stat("MRR Inicial da Carteira", brl(_inicial), min_h=_H1),
               formula(f"{dados.get('am_n_inicial', 0)} contratos vigentes no dia 1º")),
        celula(stat("MRR Evoluído", brl(_evoluido), min_h=_H1)),
    ]
    if _nrr is None:
        cards.append(celula(stat("NRR", "—", min_h=_H1)))
    else:
        seta = ""
        if _meta is not None:
            if _nrr > _meta:
                seta = " <span style='color:#1ecb78;font-size:0.9em;'>↑</span>"
            elif _nrr < _meta:
                seta = " <span style='color:#dc2626;font-size:0.9em;'>↓</span>"
        extra = ""
        if _cresc is not None:
            sinal = "+" if _cresc >= 0 else ""
            extra = formula(f"Crescimento: {sinal}{pct_fmt(_cresc)}")
        cards.append(celula(stat("NRR", f"{pct_fmt(_nrr)}{seta}", min_h=_H1), extra))
    cards.append(celula(stat("Meta NRR", pct_fmt(_meta) if _meta is not None else "—", min_h=_H1)))
    if _nrr is None or _meta is None:
        cards.append(celula(stat("% Atingido", "—", min_h=_H1)))
    else:
        pct_at = _nrr / _meta
        cor = "#1ecb78" if pct_at >= 1 else "#dc2626"
        cards.append(celula(stat(
            "% Atingido", f"<span style='color:{cor};'>{pct_fmt(pct_at)}</span>", min_h=_H1)))
    b.append(linha(cards, "cols-6"))

    # Evolução da Carteira
    b.append(divisor())
    b.append(secao("Evolução da Carteira"))
    b.append(linha([
        celula(stat("MRR Inicial", brl(_inicial))),
        celula(stat("+ Novos Negócios", brl(_novos))),
        celula(stat("+ Upsells", brl(_upsells))),
        celula(stat("Renovações de Contrato", brl(_renov_delta))),
        celula(stat("Impulsos", brl(_impulso_delta))),
        celula(stat("− Churn no Mês", brl(_churn))),
        celula(stat("= MRR Evoluído", brl(_evoluido))),
    ], "cols-7"))
    b.append(divisor())

    em = email.lower()

    # Renovações de Contrato
    if (dados.get("am_renovacoes_contratos") or 0) > 0:
        renov_df = cs.get_renovacoes_am(em, ano, mes)
        if renov_df is not None and not renov_df.empty:
            d = renov_df.copy()
            for col in ("MRR_ANTERIOR", "MRR_NOVO", "DELTA_MRR"):
                d[col] = d[col].apply(lambda v: brl(v) if pd.notna(v) else "")
            d = _cliente_link_col(d)
            d["NEGOCIO"] = d.apply(
                lambda r: link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                        max_len=NEG_MAX_LEN), axis=1)
            d["NUM_CONTRATO"] = d.apply(
                lambda r: link_contrato(r.get("CONTRATO_NOVO"), r.get("NUM_CONTRATO")), axis=1)
            d = d.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO",
                                            "CONTRATO_ANTERIOR", "CONTRATO_NOVO") if c in d.columns])
            corpo = html_table_str(d.rename(columns={
                "TIPO": "Tipo", "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                "NUM_CONTRATO": "Número do Contrato",
                "DATA_INICIO_NOVO": "Início do Novo Contrato",
                "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
                "DELTA_MRR": "Impacto no NRR",
            }), scrollable=True, compact_headers=True)
        else:
            corpo = caption("Sem dados.")
        b.append(expander("Renovações de Contrato", corpo, aberto=True))

    # Impulsos de Contrato
    if (dados.get("am_impulsos_contratos") or 0) > 0:
        imp_df = cs.get_impulsos_am(em, ano, mes)
        if imp_df is not None and not imp_df.empty:
            d = imp_df.copy()
            for col in ("MRR_ANTERIOR", "MRR_NOVO", "DELTA_MRR"):
                d[col] = d[col].apply(lambda v: brl(v) if pd.notna(v) else "")
            d = _cliente_link_col(d)
            d["NEGOCIO"] = d.apply(
                lambda r: link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                        max_len=NEG_MAX_LEN), axis=1)
            d["NUM_CONTRATO"] = d.apply(
                lambda r: link_contrato(r.get("CONTRATO_NOVO"), r.get("NUM_CONTRATO")), axis=1)
            d = d.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO",
                                            "CONTRATO_NOVO") if c in d.columns])
            corpo = html_table_str(d.rename(columns={
                "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                "NUM_CONTRATO": "Novo Contrato",
                "CONTRATOS_ANTERIORES": "Contratos Anteriores",
                "N_CONTRATOS_ANTERIORES": "Qtd. Contratos Anteriores",
                "DATA_INICIO_NOVO": "Início do Novo Contrato",
                "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
                "DELTA_MRR": "Impacto no NRR",
            }), scrollable=True, compact_headers=True)
        else:
            corpo = caption("Sem dados.")
        b.append(expander("Impulsos de Contrato", corpo, aberto=True))

    # Churn
    if (dados.get("am_churn_clientes") or 0) > 0:
        b.append(aviso_ambar(
            f"⚠️ <b>{dados['am_churn_clientes']} contrato(s) da carteira churnaram no mês.</b><br>"
            f"{brl(_churn)} de MRR para recuperar."))
        churn_df = cs.get_churn_am(em, ano, mes)
        if churn_df is not None and not churn_df.empty:
            d = churn_df.copy()
            d["MRR_PERDIDO"] = d["MRR_PERDIDO"].apply(lambda v: brl(v) if pd.notna(v) else "")
            d["NUM_CONTRATO"] = d.apply(
                lambda r: link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
            d = _cliente_link_col(d)
            d = d.drop(columns=[c for c in ("ID_CLIENTE", "CONTRATO", "LINK_CLIENTE") if c in d.columns])
            corpo = html_table_str(d.rename(columns={
                "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                "DATA_DESATIVACAO": "Data de Desativação",
                "DATA_RENOVACAO": "Data de Renovação",
                "MRR_PERDIDO": "MRR Perdido",
            }))
        else:
            corpo = caption("Sem dados.")
        b.append(expander("Churn de Contratos", corpo, aberto=True))

    # Novos negócios / upsells do mês
    mov_df = cs.get_movim_am(em, ano, mes)
    mov = None
    if mov_df is not None and not mov_df.empty:
        mov = mov_df.copy()
        mov["NEGOCIO"] = mov.apply(
            lambda r: link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO")), axis=1)
        mov = _cliente_link_col(mov)
        mov["NUM_CONTRATO"] = mov.apply(
            lambda r: link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
        mov = mov.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO",
                                            "CONTRATO") if c in mov.columns])

    if mov is not None and (mov["TIPO"] == "Novo negócio").any():
        d = mov[mov["TIPO"] == "Novo negócio"].copy()
        d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
        d = d.drop(columns=[c for c in ("TIPO", "MRR_ANTERIOR", "MRR_NOVO") if c in d.columns])
        corpo = html_table_str(d.rename(columns={
            "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
            "NUM_CONTRATO": "Número do Contrato",
            "DATA_FECH": "Data de Fechamento", "MRR": "MRR"}))
    else:
        corpo = caption("Sem novos negócios no mês.")
    b.append(expander("Novos Negócios do Mês", corpo))

    if mov is not None and (mov["TIPO"] != "Novo negócio").any():
        d = mov[mov["TIPO"] != "Novo negócio"].copy()
        for col in ("MRR_ANTERIOR", "MRR_NOVO", "MRR"):
            d[col] = d[col].apply(lambda v: brl(v) if pd.notna(v) else "")
        corpo = html_table_str(d.rename(columns={
            "TIPO": "Tipo", "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
            "NUM_CONTRATO": "Número do Contrato", "DATA_FECH": "Data de Fechamento",
            "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
            "MRR": "Impacto no NRR"}))
    else:
        corpo = caption("Sem upsells de substituição no mês.")
    b.append(expander("Upsells do Mês", corpo))

    # Composição da carteira
    cart_df = cs.get_carteira_am(em, ano, mes)
    if cart_df is not None and not cart_df.empty:
        d = cart_df.copy()
        d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
        d = _cliente_link_col(d)
        d["NUM_CONTRATO"] = d.apply(
            lambda r: link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
        d = d.drop(columns=[c for c in ("ID_CLIENTE", "LINK_CLIENTE", "CONTRATO") if c in d.columns])
        _dlc = f"/export/drive/carteira-am?consultor={em}&ano={ano}&mes={mes}"
        corpo = (f"<div style='display:flex;justify-content:space-between;"
                 f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                 f"{len(cart_df)} contratos no MRR Inicial</span>"
                 f"{botao_drive(_dlc)}</div>" +
                 html_table_str(d.rename(columns={
                     "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                     "DATA_INICIO": "Início", "DATA_RENOVACAO": "Renovação",
                     "MRR": "MRR"})))
    else:
        corpo = caption("Sem dados.")
    b.append(expander("Composição da Carteira (MRR Inicial)", corpo))

    # Exclusões administrativas
    excl_df = cs.get_exclusoes_carteira_am(em)
    if excl_df is not None and not excl_df.empty:
        d = excl_df.copy()
        d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
        d["NUM_CONTRATO"] = d.apply(
            lambda r: link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
        d = d.drop(columns=[c for c in ("CONTRATO",) if c in d.columns])
        corpo = (aviso_azul(
            f"<b>{len(excl_df)} contrato(s) excluído(s) da carteira.</b><br>"
            f"Esses contratos não compõem o MRR Inicial nem o MRR Evoluído.") +
            html_table_str(d.rename(columns={
                "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                "MRR": "MRR", "SOLICITADO_POR": "Solicitado por",
                "MOTIVO": "Motivo", "CADASTRADO_EM": "Cadastrado em"})))
        b.append(expander("Contratos Excluídos da Carteira", corpo, aberto=True))

    return b


# ── Layout B: Recuperação de Cancelamentos (porta de _comissao.py:469-609) ───

def blocos_canc(dados, email, ano, mes):
    b = []
    em = email.lower()
    has_renov = (dados.get("comissao_renovacoes_canc") or 0) > 0

    mrr_rec = dados.get("mrr_recuperado") or 0
    if not mrr_rec:
        try:
            mrr_rec = cs.get_mrr_recuperado_canc(em, ano, mes)
        except Exception:
            mrr_rec = 0.0
    bk_ren = dados.get("booking_renovacoes_canc") or 0
    val_rec = brl(dados["valor_recuperado"] + bk_ren)
    if mrr_rec:
        val_rec += (f"<div style='font-size:0.75rem;font-weight:500;color:#6b7280;"
                    f"margin-top:6px;'>MRR: {brl(mrr_rec)}</div>")
    b.append(linha([
        celula(stat("Cargo", dados["cargo"], min_h=_H1)),
        celula(stat("Valor Recuperado", val_rec, min_h=_H1)),
        celula(stat("% de Comissão Aplicado", pct_fmt(dados["pct_canc_recovery"]), min_h=_H1)),
        celula(stat("Comissão", brl(dados["total"]), highlight=True, min_h=_H1,
                    val_color="#1a1a1a")),
    ], "cols-4"))

    canc_comp = cs.get_composicao_canc_recovery(em, ano, mes)
    if canc_comp is not None and not canc_comp.empty:
        pct_cr = dados["pct_canc_recovery"]
        d = canc_comp.copy()
        d["COMISSAO"] = d["VALOR_AJUSTADO"].apply(lambda v: brl(round(float(v or 0) * pct_cr, 2)))
        for col in ("VALOR_ORIGINAL", "VALOR_AJUSTADO"):
            if col in d.columns:
                d[col] = d[col].apply(lambda v: brl(float(v or 0)))
        if "NEGOCIO" in d.columns:
            d["NEGOCIO"] = d.apply(lambda r: link_neg_nome(r["NEGOCIO"], r.get("NOME_NEGOCIO")), axis=1)
        if "CONTRATO" in d.columns:
            d["CONTRATO"] = d.apply(lambda r: link_contrato(r.get("ID_CONTRATO"), r["CONTRATO"]), axis=1)
        d = d.drop(columns=[c for c in ("NOME_NEGOCIO", "ID_CONTRATO") if c in d.columns])
        total_rec = float(canc_comp["VALOR_AJUSTADO"].apply(lambda v: float(v or 0)).sum())
        _dlk = f"/export/drive/canc?consultor={em}&ano={ano}&mes={mes}"
        corpo = (f"<div style='display:flex;justify-content:space-between;"
                 f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                 f"{len(canc_comp)} negócios | {brl(total_rec)} Total Recuperado"
                 f"</span>{botao_drive(_dlk)}</div>"
                 + html_table_str(d.rename(columns=_REN_CANC)))
    else:
        corpo = caption("Sem recuperações de cancelamento neste período.")
    b.append(expander("Composição da Recuperação de Cancelamentos", corpo))

    if has_renov:
        renov = cs.get_composicao_renovacoes_canc(em, ano, mes)
        if renov is not None and not renov.empty:
            pct_cr = dados["pct_canc_recovery"]
            dr = renov.copy()
            dr["COMISSAO"] = dr["BOOKING"].apply(lambda v: brl(round(float(v or 0) * pct_cr, 2)))
            for col in ("MRR", "BOOKING"):
                if col in dr.columns:
                    dr[col] = dr[col].apply(lambda v: brl(float(v or 0)))
            if "NEGOCIO" in dr.columns:
                dr["NEGOCIO"] = dr.apply(lambda r: link_neg_nome(r["NEGOCIO"], r.get("NOME_NEGOCIO")), axis=1)
            if "CLIENTE" in dr.columns:
                dr = _cliente_link_col(dr)
            if "CONTRATO" in dr.columns:
                dr["CONTRATO"] = dr.apply(lambda r: link_contrato(r.get("ID_CONTRATO"), r["CONTRATO"]), axis=1)
            dr = dr.drop(columns=[c for c in ("NOME_NEGOCIO", "LINK_CLIENTE", "ID_CONTRATO") if c in dr.columns])
            total_bk = float(renov["BOOKING"].apply(lambda v: float(v or 0)).sum())
            _dlr = f"/export/drive/renovacoes-canc?consultor={em}&ano={ano}&mes={mes}"
            corpo = (f"<div style='display:flex;justify-content:space-between;"
                     f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                     f"{len(renov)} negócios | {brl(total_bk)} Total Booking"
                     f"</span>{botao_drive(_dlr)}</div>"
                     + html_table_str(dr.rename(columns={
                         "NEGOCIO": "Negócio", "CLIENTE": "Cliente", "CONTRATO": "Contrato",
                         "PIPELINE": "Pipeline", "FORMA_PAG": "Forma de Pagamento",
                         "DATA_FECH": "Data de Fechamento", "MRR": "MRR",
                         "BOOKING": "Booking", "COMISSAO": "Comissão"})))
        else:
            corpo = caption("Sem renovações neste período.")
        b.append(expander("Renovações", corpo))

    b.append(divisor())
    hist = cs.get_comissao_hist(em, tuple(hist_pares(ano, mes)))
    rows = []
    for a_h, m_h in hist_pares(ano, mes):
        d_h = hist.get((a_h, m_h)) or {}
        if d_h and "erro" not in d_h and d_h.get("is_canc_recovery"):
            rows.append({
                "Periodo": f"{MESES.get(m_h, m_h)}/{a_h}",
                "Valor Recuperado": brl(d_h["valor_recuperado"]),
                "Comissão Recuperação": brl(d_h.get("comissao_canc_recovery", 0)),
                "Comissão Renovações": brl(d_h.get("comissao_renovacoes_canc", 0)),
                "Total": brl(d_h.get("total", d_h.get("comissao_canc_recovery", 0))),
            })
    b.append(expander("Histórico dos últimos meses",
                      _tabela_ou_caption(pd.DataFrame(rows), "Sem dados históricos disponíveis.")))
    return b


# ── Layout C: padrão MRR/Saving/GD/B2G (porta de _comissao.py:611-1180) ──────

def blocos_padrao(dados, email, ano, mes):
    b = []
    em = email.lower()
    is_gestor = dados.get("is_gestor", False)
    is_gd = dados.get("is_gd", False)
    is_b2g = dados.get("is_b2g", False)
    is_saving = dados.get("is_saving", False)
    unidade = "Opps" if is_gd else ("Booking" if is_b2g else "MRR")
    fmt_val = (lambda v: f"{int(v):,}".replace(",", ".")) if is_gd else brl
    ote_ajustado = dados["ote_ajustado"]

    # C0 — aviso de inconsistência de meta
    if ((ano, mes) >= (2026, 7) and dados.get("pct_protecao", 0) > 0
            and (dados.get("desconto") or 0) == 0):
        b.append(aviso_ambar(
            f"⚠️ <b>Possível inconsistência no cadastro da meta</b><br>"
            f"Há proteção de {pct_fmt(dados['pct_protecao'])} cadastrada, mas a meta "
            f"deste mês veio sem percentual de redução.<br>"
            f"O OTE Base está sem a redução correspondente.<br>"
            f"É necessário informar o percentual de redução no cadastro de Meta no RI."))

    # C1 — Resumo
    partes = ["OTE Variável"]
    if dados.get("comissao_bk_extra", 0) > 0:
        partes.append("Comissão Extra")
    if dados.get("comissao_dividas", 0) > 0:
        partes.append("Comissão sobre Dívidas")
    if dados.get("bonificacao_protecao", 0) > 0:
        partes.append("Premiação")
    if dados.get("ajuste_total", 0) != 0:
        partes.append("Ajustes de Comissão")
    if is_b2g and ((dados.get("b2g_ajuste") or {}).get("ajuste") or 0) > 0:
        partes.append("Ajuste Trimestral")
    formula_total = " + ".join(partes)

    trim_sub = ""
    if dados.get("trim"):
        fator = dados["trim"]["fator_ind"] + dados["trim"].get("fator_eq", 0)
        if fator > 0:
            trim_sub = (f"<div style='font-size:0.85rem;font-weight:600;color:#1ecb78;"
                        f"margin-top:6px;'>+&nbsp;{pct_fmt(fator)} de um Salário</div>")
    val_total = brl(dados["total"]) + trim_sub

    if is_b2g:
        cards = [
            celula(stat("Cargo", dados["cargo"], min_h=_H_BIG)),
            celula(stat("Variável Total", val_total, highlight=True, min_h=_H_BIG),
                   formula(formula_total)),
        ]
        if not is_gestor:
            cards += [
                celula(stat_pair("Realizado (Booking)", brl(dados["bk_real"]),
                                 "Realizado (ARR)", brl(dados["arr_real"]), h_outer=_H_BIG)),
                celula(stat_pair("Meta (Booking)", brl(dados["meta_mrr"]),
                                 "Meta (ARR)", brl(dados["meta_arr"]), h_outer=_H_BIG)),
                celula(stat_pair("% Atingido (Booking)", pct_fmt(dados["pct_bk_b2g"]),
                                 "% Atingido (ARR)", pct_fmt(dados["pct_arr_b2g"]), h_outer=_H_BIG)),
            ]
        else:
            rot = dados.get("rotulo_aproveitamento", "marcelo.maestro" in em)
            lbl_eq = "Aproveit. Equipe" if rot else "% Equipe c/ Meta"
            lbl_meta = "Meta Aproveit. Equipe" if rot else "Meta Equipe c/ Meta"
            cards += [
                celula(stat_pair("Realizado (Booking)", brl(dados["bk_real"]),
                                 lbl_eq, pct_fmt(dados["meta_atingida_real"]), h_outer=_H_BIG)),
                celula(stat_pair("Meta (Booking)", brl(dados["meta_mrr"]),
                                 lbl_meta, pct_fmt(dados["meta_atingida_meta"]), h_outer=_H_BIG)),
                celula(stat_pair("% Atingido (Booking)", pct_fmt(dados["pct_bk_b2g"]),
                                 "% Meta Atingida", pct_fmt(dados["pct_meta_atingida"]), h_outer=_H_BIG)),
            ]
        cards.append(celula(stat("% Atingido Pond.", pct_fmt(dados["pct_ponderado"]), min_h=_H_BIG)))
        b.append(linha(cards, "resumo-b2g"))
    else:
        opps_nota = ""
        opps_ov = dados.get("opps_override")
        if opps_ov is not None and is_gd and not is_gestor:
            sinal = "+" if opps_ov > 0 else ""
            opps_nota = (f"<div style='font-size:0.75rem;color:#6b7280;text-align:center;"
                         f"margin-top:4px;'>{sinal}{int(opps_ov)} Opps por override</div>")
        b.append(linha([
            celula(stat("Cargo", dados["cargo"], min_h=_H1)),
            celula(stat("Variável Total", val_total, highlight=True, min_h=_H1),
                   formula(formula_total)),
            celula(stat(f"Realizado ({unidade})", fmt_val(dados["realizado"]), min_h=_H1), opps_nota),
            celula(stat(f"Meta ({unidade})", fmt_val(dados["meta_mrr"]), min_h=_H1)),
            celula(stat("% Atingido", pct_fmt(dados["pct_atingido"]), min_h=_H1)),
        ], "resumo-padrao"))

    # C2 — Composição do Realizado
    comp = cs.get_composicao(em, ano, mes, dados.get("equipe", ""), is_gestor, is_gd, is_b2g)
    if comp is not None and not comp.empty:
        d = comp.copy()
        if "VALOR" in d.columns:
            d["VALOR"] = d["VALOR"].apply(brl)
            txt = f"{len(comp)} Deals | {brl(float(comp['VALOR'].sum()))} Total de MRR"
            d = _cliente_link_col(d)
            if "NOME_NEGOCIO" in d.columns:
                d["NEGOCIO"] = d.apply(
                    lambda r: link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                            max_len=NEG_MAX_LEN), axis=1)
            else:
                d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
            if "ID_CONTRATO" in d.columns:
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: link_contrato(r.get("ID_CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
            search_data = [
                " ".join(filter(None, [
                    str(comp.at[idx, "CLIENTE"] or ""),
                    str(comp.at[idx, "NOME_NEGOCIO"] if "NOME_NEGOCIO" in comp.columns else ""),
                    str(comp.at[idx, "NEGOCIO"] or ""),
                    str(comp.at[idx, "NUM_CONTRATO"] if "NUM_CONTRATO" in comp.columns else ""),
                    str(comp.at[idx, "ID_CONTRATO"] if "ID_CONTRATO" in comp.columns else ""),
                ]))
                for idx in comp.index
            ]
            d = d.drop(columns=[c for c in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c in d.columns])
            _dl_drive = f"/export/drive/composicao?consultor={em}&ano={ano}&mes={mes}"
            corpo = (_busca_input("tabela-composicao") +
                     f"<div style='display:flex;justify-content:space-between;"
                     f"align-items:center;margin-bottom:4px;'>"
                     f"<span class='caption'>{txt}</span>{botao_drive(_dl_drive)}</div>"
                     + html_table_str(d.rename(columns=_REN), scrollable=True,
                                      row_search_data=search_data, table_id="tabela-composicao"))
        elif "BOOKING" in d.columns:
            d["BOOKING"] = d["BOOKING"].apply(brl)
            if "ARR" in d.columns:
                d["ARR"] = d["ARR"].apply(brl)
            arr_part = f" | {brl(float(comp['ARR'].sum()))} Total de ARR" if "ARR" in comp.columns else ""
            txt = f"{len(comp)} Deals | {brl(float(comp['BOOKING'].sum()))} Total de Booking{arr_part}"
            d = _cliente_link_col(d)
            if "NOME_NEGOCIO" in d.columns:
                d["NEGOCIO"] = d.apply(
                    lambda r: link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                            max_len=NEG_MAX_LEN), axis=1)
            else:
                d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
            if "ID_CONTRATO" in d.columns:
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: link_contrato(r.get("ID_CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
            search_data = [
                " ".join(filter(None, [
                    str(comp.at[idx, "CLIENTE"] or ""),
                    str(comp.at[idx, "NOME_NEGOCIO"] if "NOME_NEGOCIO" in comp.columns else ""),
                    str(comp.at[idx, "NEGOCIO"] or ""),
                    str(comp.at[idx, "NUM_CONTRATO"] if "NUM_CONTRATO" in comp.columns else ""),
                    str(comp.at[idx, "ID_CONTRATO"] if "ID_CONTRATO" in comp.columns else ""),
                ]))
                for idx in comp.index
            ]
            d = d.drop(columns=[c for c in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c in d.columns])
            _dl_drive = f"/export/drive/composicao?consultor={em}&ano={ano}&mes={mes}"
            corpo = (_busca_input("tabela-composicao") +
                     f"<div style='display:flex;justify-content:space-between;"
                     f"align-items:center;margin-bottom:4px;'>"
                     f"<span class='caption'>{txt}</span>{botao_drive(_dl_drive)}</div>"
                     + html_table_str(d.rename(columns=_REN), scrollable=True,
                                      row_search_data=search_data, table_id="tabela-composicao"))
        else:
            txt = f"{len(comp)} Opps"
            if "CONTATO" in d.columns:
                base_ct = "https://app.hubspot.com/contacts/44552714/record/0-1/"
                d["CONTATO"] = d["CONTATO"].apply(
                    lambda x: "" if x is None or str(x).strip() in ("", "None")
                    else f"<a href='{base_ct}{str(x).split('.')[0]}' target='_blank'>{str(x).split('.')[0]}</a>")
            _dl_drive = f"/export/drive/composicao?consultor={em}&ano={ano}&mes={mes}"
            corpo = (f"<div style='display:flex;justify-content:space-between;"
                     f"align-items:center;margin-bottom:4px;'>"
                     f"<span class='caption'>{txt}</span>{botao_drive(_dl_drive)}</div>"
                     + html_table_str(d.rename(columns=_REN), scrollable=True))
    else:
        corpo = caption("Sem itens para compor o realizado neste período.")
    b.append(expander("Composição do Realizado", corpo))

    # C3 — Comissões Extras
    tem_bk_extra = dados["comissao_bk_extra"] > 0 or dados["booking_extras"] > 0
    tem_dividas = dados["dividas_pagas"] > 0 or dados["comissao_dividas"] > 0
    tem_protecao = dados.get("pct_protecao", 0) > 0
    tem_ajuste = dados.get("ajuste_total", 0) != 0

    if tem_bk_extra or tem_dividas or tem_ajuste:
        b.append(divisor())
        b.append(secao("Comissões Extras"))
        if tem_bk_extra:
            b.append(linha([
                celula(stat("Booking Extra", brl(dados["booking_extras"]))),
                celula(stat("% de Comissão Aplicado", pct_fmt(dados["pct_bk_extra"]))),
                celula(stat("Comissão Extra no Mês", brl(dados["comissao_bk_extra"]), highlight=True)),
            ], "cols-3"))
            if dados["comissao_bk_extra"] == 0 and dados["booking_extras"] > 0:
                b.append(caption(f"Cliff mínimo não atingido ({pct_fmt(dados['cliff_ote_01'])}) — sem comissão sobre booking extra."))
            bk_comp = cs.get_composicao_bk_extra(em, ano, mes, dados.get("equipe", ""), is_gestor)
            if bk_comp is not None and not bk_comp.empty:
                d = bk_comp.copy()
                d["BOOKING"] = d["BOOKING"].apply(brl)
                if "NEGOCIO" in d.columns:
                    d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
                _dlb = f"/export/drive/bk-extra?consultor={em}&ano={ano}&mes={mes}"
                corpo = (f"<div style='display:flex;justify-content:space-between;"
                         f"align-items:center;margin-bottom:4px;'><span class='caption'>"
                         f"{len(bk_comp)} itens | {brl(float(bk_comp['BOOKING'].sum()))} Total de Booking"
                         f"</span>{botao_drive(_dlb)}</div>"
                         + html_table_str(d.rename(columns=_REN)))
            else:
                corpo = caption("Sem itens de booking extra neste período.")
            b.append(expander("Composição do Booking Extra", corpo))

        if tem_dividas:
            pct_div = (dados["comissao_dividas"] / dados["dividas_pagas"]) if dados["dividas_pagas"] > 0 else 0.0
            b.append(linha([
                celula(stat("Dívidas Recuperadas", brl(dados["dividas_pagas"]))),
                celula(stat("% de Comissão Aplicado", pct_fmt(pct_div))),
                celula(stat("Comissão sobre Dívidas", brl(dados["comissao_dividas"]), highlight=True)),
            ], "cols-3"))
            if dados["comissao_dividas"] == 0 and dados["dividas_pagas"] > 0:
                b.append(caption(f"Cliff mínimo não atingido ({pct_fmt(dados['cliff_ote_01'])}) — sem comissão sobre dívidas."))

        if tem_ajuste:
            aj_comp = cs.get_ajustes(em, ano, mes)
            if aj_comp is not None and not aj_comp.empty:
                d = aj_comp.copy()
                d["Valor"] = d["Valor"].apply(brl)
                corpo = html_table_str(d)
            else:
                corpo = caption("Sem dados.")
            b.append(expander("Ajustes de Comissão", corpo, aberto=True))

    # C4 — Premiação
    if tem_protecao:
        b.append(divisor())
        b.append(secao("Premiação"))
        b.append(linha([
            celula(stat("% de Proteção", pct_fmt(dados["pct_protecao"]))),
            celula(stat("OTE Base", brl(dados["ote_cheio"]))),
            celula(stat("OTE Base com Desconto", brl(dados["ote_prop"])),
                   formula(f"{brl(dados['ote_cheio'])} × (1 − {pct_fmt(dados['pct_protecao'])})")),
            celula(stat("Premiação", brl(dados["bonificacao_protecao"]), highlight=True),
                   formula(f"{pct_fmt(dados['pct_protecao'])} × {brl(dados['ote_cheio'])}")),
        ], "cols-4"))

    # C5 — Cálculo do OTE
    b.append(divisor())
    b.append(secao("Cálculo do OTE"))

    # OTE Base
    fx = []
    ote_cheio_ref = dados.get("ote_02_cheio") if dados.get("ote_tier") == 2 else dados.get("ote_cheio")
    if (dados.get("desconto") or 0) > 0 and ote_cheio_ref:
        fx.append(formula(f"{brl(ote_cheio_ref)} × {pct_fmt(1 - dados['desconto'])} = {brl(dados['ote_base'])}"))
    if dados.get("cliff_ote_02") is not None and dados.get("ote_02_prop") is not None:
        if dados["ote_tier"] == 2:
            fx.append(formula("OTE máximo já atingido."))
        else:
            fx.append(formula(f"Próximo: %Atingido de {pct_fmt(dados['cliff_ote_02'])} → OTE de {brl(dados['ote_02_prop'])}"))
    card_base = celula(stat("OTE Base", brl(dados["ote_base"])), *fx)

    # Acelerador / Faixa
    if is_saving:
        faixa = dados["faixa_atingida"]
        fa = []
        prox = dados.get("proxima_faixa")
        if prox is not None:
            fa.append(formula(f"Próxima faixa: %Atingido de {pct_fmt(prox[0])} → Faixa de {pct_fmt(prox[1])}"))
        elif faixa is not None:
            fa.append(formula("Faixa máxima já atingida."))
        else:
            fa.append(formula("Abaixo do patamar mínimo (60,00%)"))
        card_acel = celula(stat("Faixa Atingida", pct_fmt(faixa) if faixa is not None else "—"), *fa)
    else:
        fa = []
        if dados["acelerador"] == 0:
            fa.append(formula(dados["acel_desc"]))
        else:
            acel_ref = dados["pct_bk_b2g"] if is_b2g else dados["pct_atingido"]
            tiers = []
            if dados.get("cliff_acel_01") and dados["cliff_acel_01"] > 0:
                tiers.append((dados["cliff_acel_01"], dados["mult_acel_01"]))
            if dados.get("cliff_acel_02") is not None and dados.get("mult_acel_02") is not None:
                tiers.append((dados["cliff_acel_02"], dados["mult_acel_02"]))
            proximos = [(t, m) for t, m in tiers if acel_ref < t]
            if proximos:
                t, m = proximos[0]
                fa.append(formula(f"Próximo: %Atingido de {pct_fmt(t)} → Acel de {pct_fmt(m)}"))
            elif tiers:
                fa.append(formula("Acelerador máximo já atingido."))
            else:
                fa.append(formula(dados["acel_desc"]))
        card_acel = celula(stat("Acelerador Atingido", pct_fmt(dados["acelerador"])), *fa)

    # OTE Variável
    fv = []
    if is_saving:
        faixa = dados["faixa_atingida"]
        if faixa is not None:
            fv.append(formula(f"{brl(dados['ote_prop'])} × {pct_fmt(dados['pct_atingido'])} × {pct_fmt(faixa)}"))
        else:
            fv.append(formula("Abaixo do patamar mínimo (60,00%)"))
    elif is_b2g:
        fv.append(formula(f"{brl(ote_ajustado)} × {pct_fmt(dados['pct_ponderado'])} (ponderado)"))
    elif is_gd:
        fv.append(formula("= OTE Ajustado (sem forma de pagamento)"))
    else:
        fv.append(formula("Soma por forma de pagamento (tabela abaixo)"))
    card_var = celula(stat("OTE Variável", brl(dados["ote_variavel"]), highlight=True), *fv)

    if is_saving:
        b.append(linha([card_base, card_acel, card_var], "cols-3"))
    else:
        faj = []
        if is_b2g:
            faj.append(formula(f"{brl(dados['ote_base'])} × {dados['acelerador']:.2f}"))
        elif ote_ajustado is not None:
            faj.append(formula(f"{brl(dados['ote_base'])} × {dados['acelerador']:.2f} × {pct_fmt(dados['pct_atingido'])}"))
        card_aj = celula(stat("OTE Ajustado", brl(ote_ajustado)), *faj)
        b.append(linha([card_base, card_acel, card_aj, card_var], "cols-4"))

    # C6 — Formas de pagamento (só MRR)
    if not is_saving and not is_b2g and not is_gd:
        realizado = dados["realizado"]
        rows = []
        for tipo, mrr_v, mult_v in [
            ("A Vista", dados["mrr_avista"], dados["mult_avista"]),
            ("CC 3x", dados["mrr_cc3x"], dados["mult_cc3x"]),
            ("CC 12x", dados["mrr_cc12x"], dados["mult_cc12x"]),
            ("Recorrente", dados["mrr_recorrente"], dados["mult_recorrente"]),
        ]:
            if mrr_v > 0:
                pct_tipo = mrr_v / realizado if realizado > 0 else 0.0
                contrib = (ote_ajustado or 0) * pct_tipo * mult_v
                rows.append({
                    "Forma de Pagamento": tipo,
                    "MRR": brl(mrr_v),
                    "% do Total": pct_fmt(pct_tipo),
                    "Multiplicador": f"{mult_v:.2f}x",
                    "Contribuição para a Comissão": brl(contrib),
                    "Cálculo": (f"<span style='font-size:0.72rem;opacity:0.65;'>"
                                f"{brl(ote_ajustado or 0)} × {pct_fmt(pct_tipo)} × {mult_v:.2f}</span>"),
                })
        if rows:
            b.append(html_table_str(pd.DataFrame(rows)))
        elif realizado == 0:
            b.append(caption("Nenhuma venda registrada para este período."))

    # C7 — Histórico
    hist = cs.get_comissao_hist(em, tuple(hist_pares(ano, mes)))
    rows = []
    for a_h, m_h in hist_pares(ano, mes):
        d_h = hist.get((a_h, m_h)) or {}
        if d_h and "erro" not in d_h:
            def _bv(v):
                return brl(v) if v else "—"
            rows.append({
                "Periodo": f"{MESES.get(m_h, m_h)}/{a_h}",
                "Realizado": brl(d_h["realizado"]) if not d_h.get("is_gd") else f"{int(d_h['realizado']):,}".replace(",", "."),
                "Meta": brl(d_h["meta_mrr"]) if not d_h.get("is_gd") else f"{int(d_h['meta_mrr']):,}".replace(",", "."),
                "% Atingido": pct_fmt(d_h["pct_atingido"]),
                "OTE Variável": brl(d_h["ote_variavel"]),
                "Comissão Extra": _bv(d_h.get("comissao_bk_extra")),
                "Dívidas": _bv(d_h.get("comissao_dividas")),
                "Premiação": _bv(d_h.get("bonificacao_protecao")),
                "Ajustes": _bv(d_h.get("ajuste_total")),
                "Total": brl(d_h["total"]),
            })
    if rows:
        df_hist = pd.DataFrame(rows)
        cols_show = [c for c in df_hist.columns if not (df_hist[c] == "—").all()]
        corpo = html_table_str(df_hist[cols_show])
    else:
        corpo = caption("Sem dados históricos disponíveis.")
    b.append(expander("Histórico dos últimos meses", corpo))

    # C8 — Comissão Trimestral
    b.extend(_blocos_trimestral(dados, em, ano, mes, is_b2g, fmt_val))
    return b


def _blocos_trimestral(dados, em, ano, mes, is_b2g, fmt_val):
    b = []
    if dados.get("trim_bloqueado"):
        b.append(divisor())
        b.append(aviso_ambar("⚠️ <b>Comissão trimestral não aplicável</b> a este período para este consultor."))
        return b
    if not dados.get("trim"):
        return b
    trim = dados["trim"]
    b.append(divisor())
    b.append(secao("Comissão Trimestral"))

    if trim["is_gestor"] and trim.get("is_b2g"):
        mult_ind = 0.9
    elif trim["is_gestor"]:
        mult_ind = 0.6
    else:
        mult_ind = 0.3

    b.append("<b>Individual</b>")
    if trim["fator_ind"] > 0:
        card_com = celula(stat("Comissão", f"{pct_fmt(trim['fator_ind'])} de um Salário", highlight=True),
                          formula(f"{pct_fmt(trim['pct_ind'])} × {pct_fmt(mult_ind)} = {pct_fmt(trim['fator_ind'])}"))
    else:
        card_com = celula(stat("Comissão", "—", highlight=True),
                          formula(f"Não atingido: {pct_fmt(trim['pct_ind'])} do trimestre (mínimo 100%)."))
    b.append(linha([
        celula(stat("Realizado", fmt_val(trim["real_ind"]))),
        celula(stat("Meta", fmt_val(trim["meta_ind"]))),
        celula(stat("% Atingido", pct_fmt(trim["pct_ind"]))),
        card_com,
    ], "cols-4"))

    if not trim["is_gestor"]:
        b.append("<b>Equipe</b>")
        if trim["fator_eq"] > 0:
            card_eq = celula(stat("Comissão", f"{pct_fmt(trim['fator_eq'])} de um Salário", highlight=True),
                             formula(f"{pct_fmt(trim['pct_ind'])} × 30% = {pct_fmt(trim['fator_eq'])}"))
        else:
            if trim["pct_eq"] < 1.0:
                nota = f"Não atingido: {pct_fmt(trim['pct_eq'])} do trimestre (mínimo 100%)."
            else:
                nota = f"Não atingido: atingimento individual de {pct_fmt(trim['pct_ind'])} abaixo do cliff mínimo."
            card_eq = celula(stat("Comissão", "—", highlight=True), formula(nota))
        b.append(linha([
            celula(stat("Realizado", fmt_val(trim["real_eq"]))),
            celula(stat("Meta", fmt_val(trim["meta_eq"]))),
            celula(stat("% Atingido", pct_fmt(trim["pct_eq"]))),
            card_eq,
        ], "cols-4"))

    if is_b2g and dados.get("b2g_ajuste"):
        aj = dados["b2g_ajuste"]
        is_gest = aj.get("is_gestor", False)
        b.append("<b>Ajuste Trimestral</b>")

        mcache = {}
        for dm in [mes - 2, mes - 1, mes]:
            m_h, a_h = dm, ano
            while m_h < 1:
                m_h += 12
                a_h -= 1
            try:
                d_h = cs.get_comissao(em, a_h, m_h)
                if "erro" not in d_h:
                    mcache[m_h] = d_h
            except Exception:
                pass

        pago_3m = float(aj.get("pago_mensal", 0) or 0)
        ajuste_real = float(aj.get("ajuste") or 0)
        if not is_gest:
            pares = [
                celula(stat_pair("Realizado (Booking)", brl(aj.get("bk_q", 0)),
                                 "Realizado (ARR)", brl(aj.get("arr_q", 0)), h_outer=_H_BIG)),
                celula(stat_pair("Meta (Booking)", brl(aj.get("meta_bk_q", 0)),
                                 "Meta (ARR)", brl(aj.get("meta_arr_q", 0)), h_outer=_H_BIG)),
                celula(stat_pair("% Atingido (Booking)", pct_fmt(aj.get("pct_bk_q", 0)),
                                 "% Atingido (ARR)", pct_fmt(aj.get("pct_arr_q", 0)), h_outer=_H_BIG)),
            ]
        else:
            rot = dados.get("rotulo_aproveitamento", "marcelo.maestro" in em)
            lbl_eq = "Aproveit. Equipe" if rot else "% Equipe c/ Meta"
            lbl_meta = "Meta Aproveit. Equipe" if rot else "Meta Equipe c/ Meta"
            pares = [
                celula(stat_pair("Realizado (Booking)", brl(aj.get("bk_q", 0)),
                                 lbl_eq, pct_fmt(aj.get("ma_q", 0)), h_outer=_H_BIG)),
                celula(stat_pair("Meta (Booking)", brl(aj.get("meta_bk_q", 0)),
                                 lbl_meta, pct_fmt(dados.get("meta_atingida_meta", 0.8)), h_outer=_H_BIG)),
                celula(stat_pair("% Atingido (Booking)", pct_fmt(aj.get("pct_bk_q", 0)),
                                 "% Meta Atingida", pct_fmt(aj.get("pct_ma_q", 0)), h_outer=_H_BIG)),
            ]
        if ajuste_real > 0:
            card_aj = celula(stat("Ajuste Trimestral", brl(ajuste_real), highlight=True, min_h=_H_BIG))
        else:
            card_aj = celula(stat("Ajuste Trimestral", brl(0), highlight=True, min_h=_H_BIG),
                             formula("Acumulado não supera a soma dos mensais."))
        b.append(linha(pares + [
            celula(stat("% Atingido Pond.", pct_fmt(aj.get("pct_ponderado_q", 0)), min_h=_H_BIG)),
            celula(stat("OTE Variável (trim)", brl(aj["ote_variavel_q"]), min_h=_H_BIG)),
            celula(stat("Pago nos 3 Meses", brl(pago_3m), min_h=_H_BIG)),
            card_aj,
        ], "cols-7"))

        trows = []
        for dm in [mes - 2, mes - 1, mes]:
            m_h, a_h = dm, ano
            while m_h < 1:
                m_h += 12
                a_h -= 1
            d = mcache.get(m_h, {})
            row = {"Mês": MESES.get(m_h, m_h), "OTE Base": brl(d.get("ote_base", 0))}
            if is_gest:
                row["Book Equipe"] = brl(d.get("bk_real", 0))
                row["Meta Book"] = brl(d.get("meta_mrr", 0))
                row["% Book"] = pct_fmt(d.get("pct_bk_b2g", 0))
                row["Aprov. Eq."] = pct_fmt(d.get("meta_atingida_real", 0))
                row["Meta Aprov."] = pct_fmt(d.get("meta_atingida_meta", 0))
                row["% Aprov."] = pct_fmt(d.get("pct_meta_atingida", 0))
            else:
                row["Booking"] = brl(d.get("bk_real", 0))
                row["Meta Book"] = brl(d.get("meta_mrr", 0))
                row["% Book"] = pct_fmt(d.get("pct_bk_b2g", 0))
                row["ARR"] = brl(d.get("arr_real", 0))
                row["Meta ARR"] = brl(d.get("meta_arr", 0))
                row["% ARR"] = pct_fmt(d.get("pct_arr_b2g", 0))
            row["% Pond."] = pct_fmt(d.get("pct_ponderado", 0))
            row["Acelerador"] = pct_fmt(d.get("acelerador", 0))
            row["OTE Variável"] = brl(d.get("ote_variavel", 0))
            trows.append(row)

        tr = {"Mês": "Trimestre", "OTE Base": brl(aj.get("ote_base_q", 0))}
        if is_gest:
            tr["Book Equipe"] = brl(aj.get("bk_q", 0))
            tr["Meta Book"] = brl(aj.get("meta_bk_q", 0))
            tr["% Book"] = pct_fmt(aj.get("pct_bk_q", 0))
            tr["Aprov. Eq."] = pct_fmt(aj.get("ma_q", 0))
            tr["Meta Aprov."] = pct_fmt(dados.get("meta_atingida_meta", 0.8))
            tr["% Aprov."] = pct_fmt(aj.get("pct_ma_q", 0))
        else:
            tr["Booking"] = brl(aj.get("bk_q", 0))
            tr["Meta Book"] = brl(aj.get("meta_bk_q", 0))
            tr["% Book"] = pct_fmt(aj.get("pct_bk_q", 0))
            tr["ARR"] = brl(aj.get("arr_q", 0))
            tr["Meta ARR"] = brl(aj.get("meta_arr_q", 0))
            tr["% ARR"] = pct_fmt(aj.get("pct_arr_q", 0))
        tr["% Pond."] = pct_fmt(aj.get("pct_ponderado_q", 0))
        tr["Acelerador"] = pct_fmt(aj.get("acel_q", 0))
        tr["OTE Variável"] = brl(aj.get("ote_variavel_q", 0))
        trows.append(tr)
        b.append(html_table_str(pd.DataFrame(trows), scrollable=True))
    return b


def montar_blocos(dados, email, ano, mes):
    """Escolhe o layout como em _comissao.py (AM → canc-recovery → padrão)."""
    dados = dict(dados)
    dados["cargo"] = fmt_cargo(dados.get("cargo", ""))
    if dados.get("is_am"):
        return blocos_am(dados, email, ano, mes)
    if dados.get("is_canc_recovery"):
        return blocos_canc(dados, email, ano, mes)
    return blocos_padrao(dados, email, ano, mes)
