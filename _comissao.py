import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import streamlit as st
import pandas as pd
from utils.connection import (
    get_session, compat_rerun, compat_divider, _is_xp_err,
    get_comissao, get_comissao_hist, get_composicao, get_composicao_bk_extra,
    get_composicao_canc_recovery, get_composicao_renovacoes_canc, get_ajustes,
    get_carteira_am, get_movim_am, get_churn_am, get_renovacoes_am, get_impulsos_am,
    get_exclusoes_carteira_am, get_mrr_recuperado_canc,
    render_filters, get_snapshot_info,
)
from utils.ui import (brl, pct_fmt, stat, stat_pair, formula, html_table,
                      render_banner, render_css, df_download_link)

_SIGLAS_RE = re.compile(r'\b(II|SDR|JR|PL|SR|FSB)\b', re.IGNORECASE)

def _fmt_cargo(s):
    return _SIGLAS_RE.sub(lambda m: m.group().upper(), str(s).title())

from utils.connection import MESES_NOME as MESES

# ── CSS: global via fonte única ───────────────────────────────────────────────
render_css()


def _hist_pares(ano, mes, n=6):
    """[(ano, mes)] dos n meses anteriores ao selecionado."""
    pares = []
    for delta in range(1, n + 1):
        m_h, a_h = mes - delta, ano
        while m_h < 1:
            m_h += 12
            a_h -= 1
        pares.append((a_h, m_h))
    return pares

# ── Cabecalho e Filtros (3 na mesma linha) ────────────────────────────────────

render_banner("Minha Comissão")

session = get_session()

ano, mes, email, tipo_usuario = render_filters(session, with_equipe=True)

# Separacao discreta entre filtros e o primeiro segmento
st.markdown(
    "<hr style='margin:8px 0 16px;border:none;"
    "border-top:1px solid #9ca3af;'>",
    unsafe_allow_html=True,
)

# ── Badge de período fechado ──────────────────────────────────────────────────
_snap_info = get_snapshot_info(ano, mes, email.lower())
if _snap_info:
    try:
        _data_fech = pd.to_datetime(_snap_info["data"]).strftime("%d/%m/%Y")
        _data_txt = f" em {_data_fech}"
    except Exception:
        _data_txt = ""
    st.markdown(
        f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
        f"padding:0.4rem 0.9rem;border-left:4px solid #d97706;"
        f"font-size:0.9rem;margin:0.3rem 0 0.6rem;'>"
        f"🔒 <strong>Período fechado{_data_txt}.</strong> "
        f"Se houver algum negócio não contabilizado ou com valor desatualizado, "
        f"solicite o recálculo para Higor.</div>",
        unsafe_allow_html=True,
    )

# ── Calculo ───────────────────────────────────────────────────────────────────

with st.spinner("Calculando..."):
    try:
        dados = get_comissao(email.lower(), ano, mes)
    except Exception as _e:
        if _is_xp_err(_e):
            compat_rerun()
        st.error(f"Erro ao calcular comissão: {_e}")
        st.stop()

if "erro" in dados:
    st.markdown(
        f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
        f"padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>"
        f"{dados['erro']}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.stop()

dados["cargo"] = _fmt_cargo(dados.get("cargo", ""))

if dados["ote_indisponivel"]:
    st.warning(
        f"OTE para o cargo **{dados['cargo']}** não encontrado em Cargos e OTEs "
        f"({MESES.get(mes, mes)}/{ano}). Comissão não pode ser calculada."
    )
    st.stop()

is_canc_recovery = dados.get("is_canc_recovery", False)
is_gestor = dados.get("is_gestor", False)
is_gd     = dados.get("is_gd", False)
is_b2g    = dados.get("is_b2g", False)
is_saving = dados.get("is_saving", False)
unidade   = "Opps" if is_gd else ("Booking" if is_b2g else "MRR")
fmt_val   = (lambda v: f"{int(v):,}".replace(",", ".")) if is_gd else brl
ote_ajustado = dados["ote_ajustado"]

_H1 = 124  # altura maior p/ comportar cargo em duas linhas
_base_neg = "https://app.hubspot.com/contacts/44552714/record/0-3/"
def _link_neg(x):
    if x is None or str(x).strip() in ("", "None"):
        return ""
    nid = str(x).split(".")[0]
    return f"<a href='{_base_neg}{nid}' target='_blank'>{nid}</a>"

_base_contrato = "https://app.hubspot.com/contacts/44552714/record/2-25175098/"
def _link_contrato(cid, numero):
    """Âncora p/ o contrato no HubSpot com o Número do contrato como texto."""
    num = "" if numero is None or str(numero) in ("None", "nan") else str(numero)
    if cid is None or str(cid).strip() in ("", "None"):
        return num
    cid_s = str(cid).split(".")[0]
    return f"<a href='{_base_contrato}{cid_s}' target='_blank'>{num or cid_s}</a>"

# Limite do nome do negócio nas tabelas largas de AM: o nome completo fica no
# title do link, então truncar aqui evita a coluna esticar a tabela.
_NEG_MAX_LEN = 30

def _nome_negocio_limpo(s):
    """Nome do negócio sem as partes de ruído separadas por '||'.

    O HubSpot embute ids e datas no nome com '||' em posições variadas
    ('123 || nome', 'R.aut || 123 || nome', 'nome ||', 'nome || 04/12/2025'),
    então pegar só a última parte devolvia id ou data. Aqui descartam-se as
    partes vazias, só-número e só-data e fica a mais longa (a descritiva)."""
    import re as _re
    s = str(s or "").strip()
    if "||" not in s:
        return _re.sub(r"\s+", " ", s)
    partes = [p.strip() for p in s.split("||")]
    validas = [p for p in partes
               if p and not _re.fullmatch(r"\d+", p)
               and not _re.fullmatch(r"\d{2}/\d{2}/\d{4}", p)]
    escolhido = max(validas, key=len) if validas else s
    return _re.sub(r"\s+", " ", escolhido)

def _esc_attr(s):
    """Escapa o texto do negócio para caber em atributo/HTML sem quebrar a tag."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))

def _link_neg_nome(nid, nome, max_len=45):
    """Link HubSpot para negócio com o nome limpo truncado como texto
    (nome completo no title)."""
    nid_s = str(nid or "").split(".")[0].strip()
    if not nid_s or nid_s in ("", "None"):
        return ""
    nome_limpo = _nome_negocio_limpo(nome) or nid_s
    label = (nome_limpo[:max_len] + "…") if len(nome_limpo) > max_len else nome_limpo
    return (f"<a href='{_base_neg}{nid_s}' target='_blank' "
            f"title='{_esc_attr(nome_limpo)}'>{_esc_attr(label)}</a>")


_CLIENTE_MAX_LEN = 35

def _link_cliente(link, nome, max_len=_CLIENTE_MAX_LEN):
    """Nome do cliente com link HubSpot; 'N/A'/vazio vira travessao.

    Razão social truncada com '…' e nome completo no title — sem isso um
    cliente com nome muito longo estoura a coluna (mesmo cuidado que
    _link_neg_nome já tinha para nome de negócio)."""
    nome_s = str(nome or "").strip()
    if nome_s.upper() in ("", "N/A", "NA", "NAN", "NONE"):
        return "—"
    label = (nome_s[:max_len] + "…") if len(nome_s) > max_len else nome_s
    if link is None or str(link).strip() in ("", "None", "nan"):
        return f"<span title='{_esc_attr(nome_s)}'>{_esc_attr(label)}</span>"
    return (f"<a href='{link}' target='_blank' title='{_esc_attr(nome_s)}'>"
            f"{_esc_attr(label)}</a>")

def _cap(col, text):
    col.markdown(
        f"<span style='color:#6b7280;font-size:0.88rem;'>{text.replace('$', '&#36;')}</span>",
        unsafe_allow_html=True,
    )

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

# ══ LAYOUT ALTERNATIVO — Account Manager (medição NRR da carteira) ═════════════
if dados.get("is_am"):
    _inicial  = dados.get("am_mrr_inicial") or 0.0
    _novos    = dados.get("am_novos_negocios") or 0.0
    _upsells  = dados.get("am_upsells") or 0.0
    _renov_delta = dados.get("am_renovacoes_delta") or 0.0
    _impulso_delta = dados.get("am_impulsos_delta") or 0.0
    _churn    = dados.get("am_churn_mrr") or 0.0
    _evoluido = dados.get("am_mrr_evoluido") or 0.0
    _nrr      = dados.get("am_nrr")
    _cresc    = (_nrr - 1) if _nrr is not None else None

    # ── Resumo ────────────────────────────────────────────────────────────────
    _am_meta_nrr = dados.get("am_meta_nrr")

    c = st.columns(6)
    stat(c[0], "Cargo", dados["cargo"], min_h=_H1)
    stat(c[1], "MRR Inicial da Carteira", brl(_inicial), min_h=_H1)
    formula(c[1], f"{dados.get('am_n_inicial', 0)} contratos vigentes no dia 1º")
    stat(c[2], "MRR Evoluído", brl(_evoluido), min_h=_H1)

    # NRR como card principal; Crescimento como observação abaixo
    if _nrr is None:
        stat(c[3], "NRR", "—", min_h=_H1)
    else:
        _seta = ""
        if _am_meta_nrr is not None:
            if _nrr > _am_meta_nrr:
                _seta = " <span style='color:#1ecb78;font-size:0.9em;'>↑</span>"
            elif _nrr < _am_meta_nrr:
                _seta = " <span style='color:#dc2626;font-size:0.9em;'>↓</span>"
        stat(c[3], "NRR", f"{pct_fmt(_nrr)}{_seta}", min_h=_H1)
        if _cresc is not None:
            _sinal = "+" if _cresc >= 0 else ""
            formula(c[3], f"Crescimento: {_sinal}{pct_fmt(_cresc)}")

    # Meta NRR
    if _am_meta_nrr is None:
        stat(c[4], "Meta NRR", "—", min_h=_H1)
    else:
        stat(c[4], "Meta NRR", pct_fmt(_am_meta_nrr), min_h=_H1)

    # % Atingido
    if _nrr is None or _am_meta_nrr is None:
        stat(c[5], "% Atingido", "—", min_h=_H1)
    else:
        _pct_at = _nrr / _am_meta_nrr
        _cor_at = "#1ecb78" if _pct_at >= 1 else "#dc2626"
        stat(c[5], "% Atingido",
             f"<span style='color:{_cor_at};'>{pct_fmt(_pct_at)}</span>",
             min_h=_H1)

    # ── Evolução da Carteira ──────────────────────────────────────────────────
    compat_divider()
    st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Evolução da Carteira</div>", unsafe_allow_html=True)
    # Sem textos explicativos sob os cards: as tabelas dos expanders abaixo
    # já detalham cada grupo (pedido de 14/08/2026).
    c = st.columns(7)
    stat(c[0], "MRR Inicial", brl(_inicial))
    stat(c[1], "+ Novos Negócios", brl(_novos))
    stat(c[2], "+ Upsells", brl(_upsells))
    stat(c[3], "Renovações de Contrato", brl(_renov_delta))
    stat(c[4], "Impulsos", brl(_impulso_delta))
    stat(c[5], "− Churn no Mês", brl(_churn))
    stat(c[6], "= MRR Evoluído", brl(_evoluido))

    compat_divider()

    # ── Renovações que substituíram o contrato inicial ────────────────────────
    if (dados.get("am_renovacoes_contratos") or 0) > 0:
        with st.expander("Renovações de Contrato", expanded=True):
            renov_df = get_renovacoes_am(email.lower(), ano, mes)
            if renov_df is not None and not renov_df.empty:
                d = renov_df.copy()
                for _col in ("MRR_ANTERIOR", "MRR_NOVO", "DELTA_MRR"):
                    d[_col] = d[_col].apply(lambda v: brl(v) if pd.notna(v) else "")
                d["CLIENTE"] = d.apply(
                    lambda r: (f"<a href='{r['LINK_CLIENTE']}' target='_blank'>"
                               f"{r['CLIENTE']}</a>")
                    if pd.notna(r.get("LINK_CLIENTE")) and str(r.get("LINK_CLIENTE")).strip()
                    else ("" if r.get("CLIENTE") is None else str(r["CLIENTE"])), axis=1)
                d["NEGOCIO"] = d.apply(
                    lambda r: _link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                             max_len=_NEG_MAX_LEN), axis=1)
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("CONTRATO_NOVO"), r.get("NUM_CONTRATO")),
                    axis=1)
                d = d.drop(columns=[col for col in (
                    "ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO",
                    "CONTRATO_ANTERIOR", "CONTRATO_NOVO"
                ) if col in d.columns])
                html_table(d.rename(columns={
                    "TIPO": "Tipo", "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                    "NUM_CONTRATO": "Número do Contrato",
                    "DATA_INICIO_NOVO": "Início do Novo Contrato",
                    "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
                    "DELTA_MRR": "Impacto no NRR",
                }), scrollable=True, compact_headers=True)
            else:
                st.caption("Sem dados.")

    if (dados.get("am_impulsos_contratos") or 0) > 0:
        with st.expander("Impulsos de Contrato", expanded=True):
            impulso_df = get_impulsos_am(email.lower(), ano, mes)
            if impulso_df is not None and not impulso_df.empty:
                d = impulso_df.copy()
                for _col in ("MRR_ANTERIOR", "MRR_NOVO", "DELTA_MRR"):
                    d[_col] = d[_col].apply(lambda v: brl(v) if pd.notna(v) else "")
                d["CLIENTE"] = d.apply(
                    lambda r: (f"<a href='{r['LINK_CLIENTE']}' target='_blank'>"
                               f"{r['CLIENTE']}</a>")
                    if pd.notna(r.get("LINK_CLIENTE")) and str(r.get("LINK_CLIENTE")).strip()
                    else ("" if r.get("CLIENTE") is None else str(r["CLIENTE"])), axis=1)
                d["NEGOCIO"] = d.apply(
                    lambda r: _link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                             max_len=_NEG_MAX_LEN), axis=1)
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("CONTRATO_NOVO"), r.get("NUM_CONTRATO")),
                    axis=1)
                d = d.drop(columns=[col for col in (
                    "ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO", "CONTRATO_NOVO"
                ) if col in d.columns])
                html_table(d.rename(columns={
                    "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                    "NUM_CONTRATO": "Novo Contrato",
                    "CONTRATOS_ANTERIORES": "Contratos Anteriores",
                    "N_CONTRATOS_ANTERIORES": "Qtd. Contratos Anteriores",
                    "DATA_INICIO_NOVO": "Início do Novo Contrato",
                    "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
                    "DELTA_MRR": "Impacto no NRR",
                }), scrollable=True, compact_headers=True)
            else:
                st.caption("Sem dados.")

    # ── Clientes churnados (correr atrás) ────────────────────────────────────
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    if (dados.get("am_churn_clientes") or 0) > 0:
        st.markdown(
            f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            f"padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            f"⚠️ <b>{dados['am_churn_clientes']} contrato(s) da carteira churnaram "
            f"no mês.</b><br>"
            f"{brl(_churn)} de MRR para recuperar.</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Churn de Contratos", expanded=True):
            churn_df = get_churn_am(email.lower(), ano, mes)
            if churn_df is not None and not churn_df.empty:
                d = churn_df.copy()
                d["MRR_PERDIDO"] = d["MRR_PERDIDO"].apply(
                    lambda v: brl(v) if pd.notna(v) else "")
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")),
                    axis=1)
                d["CLIENTE"] = d.apply(
                    lambda r: (f"<a href='{r['LINK_CLIENTE']}' target='_blank'>"
                               f"{r['CLIENTE']}</a>")
                    if pd.notna(r.get("LINK_CLIENTE")) and str(r.get("LINK_CLIENTE")).strip()
                    else ("" if r.get("CLIENTE") is None else str(r["CLIENTE"])), axis=1)
                d = d.drop(columns=[col for col in ("ID_CLIENTE", "CONTRATO", "LINK_CLIENTE")
                                    if col in d.columns])
                html_table(d.rename(columns={
                    "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                    "DATA_DESATIVACAO": "Data de Desativação",
                    "DATA_RENOVACAO": "Data de Renovação",
                    "MRR_PERDIDO": "MRR Perdido",
                }))
            else:
                st.caption("Sem dados.")

    # ── Composições ───────────────────────────────────────────────────────────
    mov_df = get_movim_am(email.lower(), ano, mes)
    if mov_df is not None and not mov_df.empty:
        _mov = mov_df.copy()
        _mov["NEGOCIO"] = _mov.apply(
            lambda r: (f"<a href='{_base_neg}{str(r['NEGOCIO']).split('.')[0]}' "
                       f"target='_blank'>{_nome_negocio_limpo(r.get('NOME_NEGOCIO'))}</a>")
            if pd.notna(r.get("NEGOCIO")) else "", axis=1)
        _mov["CLIENTE"] = _mov.apply(
            lambda r: (f"<a href='{r['LINK_CLIENTE']}' target='_blank'>"
                       f"{r['CLIENTE']}</a>")
            if pd.notna(r.get("LINK_CLIENTE")) and str(r.get("LINK_CLIENTE")).strip()
            else ("" if r.get("CLIENTE") is None else str(r["CLIENTE"])), axis=1)
        _mov["NUM_CONTRATO"] = _mov.apply(
            lambda r: _link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")),
            axis=1)
        _mov = _mov.drop(columns=[col for col in (
            "ID_CLIENTE", "LINK_CLIENTE", "NOME_NEGOCIO", "CONTRATO"
        ) if col in _mov.columns])
    else:
        _mov = None

    with st.expander("Novos Negócios do Mês"):
        if _mov is not None and (_mov["TIPO"] == "Novo negócio").any():
            d = _mov[_mov["TIPO"] == "Novo negócio"].copy()
            d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
            d = d.drop(columns=[col for col in ("TIPO", "MRR_ANTERIOR", "MRR_NOVO")
                                if col in d.columns])
            html_table(d.rename(columns={
                "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                "NUM_CONTRATO": "Número do Contrato",
                "DATA_FECH": "Data de Fechamento", "MRR": "MRR",
            }))
        else:
            st.markdown("<span style='color:#1a1a1a;'>Sem novos negócios no mês.</span>",
                        unsafe_allow_html=True)

    with st.expander("Upsells do Mês"):
        if _mov is not None and (_mov["TIPO"] != "Novo negócio").any():
            d = _mov[_mov["TIPO"] != "Novo negócio"].copy()
            for _col in ("MRR_ANTERIOR", "MRR_NOVO", "MRR"):
                d[_col] = d[_col].apply(lambda v: brl(v) if pd.notna(v) else "")
            html_table(d.rename(columns={
                "TIPO": "Tipo", "CLIENTE": "Cliente", "NEGOCIO": "Negócio",
                "NUM_CONTRATO": "Número do Contrato",
                "DATA_FECH": "Data de Fechamento",
                "MRR_ANTERIOR": "MRR Anterior", "MRR_NOVO": "MRR Novo",
                "MRR": "Impacto no NRR",
            }))
        else:
            st.markdown("<span style='color:#1a1a1a;'>Sem upsells de substituição no mês.</span>",
                        unsafe_allow_html=True)

    with st.expander("Composição da Carteira (MRR Inicial)"):
        cart_df = get_carteira_am(email.lower(), ano, mes)
        if cart_df is not None and not cart_df.empty:
            _busca_cart = st.text_input(
                "Pesquisar carteira",
                placeholder="Nome do cliente ou número do contrato…",
                key="busca_carteira_am",
                label_visibility="collapsed",
            )
            _total_cart = len(cart_df)
            d = cart_df.copy()
            if _busca_cart.strip():
                _term = _busca_cart.strip().lower()
                _mask = (
                    d["CLIENTE"].astype(str).str.lower().str.contains(_term, na=False)
                    | d["NUM_CONTRATO"].astype(str).str.lower().str.contains(_term, na=False)
                )
                d = d[_mask].copy()

            d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
            _d_export = d.drop(columns=[c_ for c_ in ("ID_CLIENTE", "LINK_CLIENTE",
                                                      "CONTRATO") if c_ in d.columns])
            d["CLIENTE"] = d.apply(
                lambda r: _link_cliente(r.get("LINK_CLIENTE"), r.get("CLIENTE")), axis=1)
            d["NUM_CONTRATO"] = d.apply(
                lambda r: _link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")),
                axis=1)
            d = d.drop(columns=[c_ for c_ in ("ID_CLIENTE", "LINK_CLIENTE", "CONTRATO")
                                if c_ in d.columns])
            _REN_CART = {
                "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                "DATA_INICIO": "Data de Início",
                "PROX_RENOVACAO": "Próxima Renovação", "MRR": "MRR",
            }
            _cap_c, _dl_c = st.columns([6, 1])
            _txt_cart = f"{len(d)} contratos | {brl(_inicial)} MRR Inicial"
            if len(d) < _total_cart:
                _txt_cart = f"{len(d)} de {_total_cart} contratos (filtrados)"
            _cap(_cap_c, _txt_cart)
            _dl_c.markdown(df_download_link(_d_export.rename(columns=_REN_CART),
                                            f"carteira_am_{mes:02d}_{ano}.xls"),
                           unsafe_allow_html=True)
            html_table(d.rename(columns=_REN_CART))
        else:
            st.caption("Nenhum contrato vigente no início do mês.")

    # ── Exclusões administrativas da carteira ─────────────────────────────────
    excl_df = get_exclusoes_carteira_am(email.lower())
    if excl_df is not None and not excl_df.empty:
        with st.expander("Contratos Excluídos da Carteira", expanded=True):
            st.markdown(
                f"<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
                f"padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0 0 12px;'>"
                f"<b>{len(excl_df)} contrato(s) excluído(s) da carteira.</b><br>"
                f"Esses contratos não compõem o MRR Inicial nem o MRR Evoluído.</div>",
                unsafe_allow_html=True,
            )
            d = excl_df.copy()
            d["MRR"] = d["MRR"].apply(lambda v: brl(v) if pd.notna(v) else "")
            d["NUM_CONTRATO"] = d.apply(
                lambda r: _link_contrato(r.get("CONTRATO"), r.get("NUM_CONTRATO")),
                axis=1)
            d = d.drop(columns=["CONTRATO"])
            html_table(d.rename(columns={
                "CLIENTE": "Cliente", "NUM_CONTRATO": "Número do Contrato",
                "MRR": "MRR", "SOLICITADO_POR": "Solicitado por",
                "MOTIVO": "Motivo", "CADASTRADO_EM": "Cadastrado em",
            }))

    st.stop()

# ══ LAYOUT ALTERNATIVO — Recuperação de Cancelamentos ══════════════════════════
if is_canc_recovery:
    _has_renov = (dados.get("comissao_renovacoes_canc") or 0) > 0

    c = st.columns(4)
    stat(c[0], "Cargo", dados["cargo"], min_h=_H1)
    _mrr_rec = dados.get("mrr_recuperado") or 0
    if not _mrr_rec:
        try:
            _mrr_rec = get_mrr_recuperado_canc(email.lower(), ano, mes)
        except Exception:
            _mrr_rec = 0.0  # exibicao opcional: sem MRR na linha, valor principal segue correto
    _bk_ren = dados.get("booking_renovacoes_canc") or 0
    _total_rec = dados["valor_recuperado"] + _bk_ren
    _val_rec = brl(_total_rec)
    if _mrr_rec:
        _val_rec += (
            f"<div style='font-size:0.75rem;font-weight:500;color:#6b7280;margin-top:6px;'>"
            f"MRR: {brl(_mrr_rec)}</div>"
        )
    stat(c[1], "Valor Recuperado", _val_rec, min_h=_H1)
    stat(c[2], "% de Comissão Aplicado", pct_fmt(dados["pct_canc_recovery"]), min_h=_H1)
    stat(c[3], "Comissão", brl(dados["total"]), highlight=True, min_h=_H1, val_color="#1a1a1a")

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    with st.expander("Composição da Recuperação de Cancelamentos"):
        canc_comp = get_composicao_canc_recovery(email.lower(), ano, mes)
        if canc_comp is not None and not canc_comp.empty:
            _busca_canc = st.text_input(
                "Pesquisar cancelamentos",
                placeholder="Negócio ou número do contrato…",
                key="busca_canc",
                label_visibility="collapsed",
            )
            _total_canc = len(canc_comp)
            if _busca_canc.strip():
                _term_c = _busca_canc.strip().lower()
                _mask_c = pd.Series(False, index=canc_comp.index)
                if "NEGOCIO" in canc_comp.columns:
                    _mask_c |= canc_comp["NEGOCIO"].astype(str).str.lower().str.contains(_term_c, na=False)
                if "CONTRATO" in canc_comp.columns:
                    _mask_c |= canc_comp["CONTRATO"].astype(str).str.lower().str.contains(_term_c, na=False)
                canc_comp = canc_comp[_mask_c].copy()
            _filtrado_canc = len(canc_comp) < _total_canc

            pct_cr = dados["pct_canc_recovery"]
            d = canc_comp.copy()
            d["COMISSAO"] = d["VALOR_AJUSTADO"].apply(
                lambda v: brl(round(float(v or 0) * pct_cr, 2))
            )
            for col in ("VALOR_ORIGINAL", "VALOR_AJUSTADO"):
                if col in d.columns:
                    d[col] = d[col].apply(lambda v: brl(float(v or 0)))
            _aux_canc = [c for c in ("NOME_NEGOCIO", "ID_CONTRATO") if c in d.columns]
            d_export = d.drop(columns=_aux_canc).rename(columns=_REN_CANC)
            if "NEGOCIO" in d.columns:
                d["NEGOCIO"] = d.apply(
                    lambda r: _link_neg_nome(r["NEGOCIO"], r.get("NOME_NEGOCIO")), axis=1)
            if "CONTRATO" in d.columns:
                d["CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("ID_CONTRATO"), r["CONTRATO"]), axis=1)
            d = d.drop(columns=_aux_canc)
            _cap_c, _dl_c = st.columns([6, 1])
            _cnt_canc = f"{len(canc_comp)} de {_total_canc}" if _filtrado_canc else str(len(canc_comp))
            _cap(_cap_c, f"{_cnt_canc} negócios | {brl(float(canc_comp['VALOR_AJUSTADO'].apply(lambda v: float(v or 0)).sum()))} Total Recuperado")
            _dl_c.markdown(df_download_link(d_export, f"cancelamentos_{mes:02d}_{ano}.xls"), unsafe_allow_html=True)
            html_table(d.rename(columns=_REN_CANC))
        else:
            st.caption("Sem recuperações de cancelamento neste período.")

    if _has_renov:
        with st.expander("Renovações"):
            _renov_comp = get_composicao_renovacoes_canc(email.lower(), ano, mes)
            if _renov_comp is not None and not _renov_comp.empty:
                pct_cr = dados["pct_canc_recovery"]
                dr = _renov_comp.copy()
                dr["COMISSAO"] = dr["BOOKING"].apply(
                    lambda v: brl(round(float(v or 0) * pct_cr, 2))
                )
                for col in ("MRR", "BOOKING"):
                    if col in dr.columns:
                        dr[col] = dr[col].apply(lambda v: brl(float(v or 0)))
                if "NEGOCIO" in dr.columns:
                    dr["NEGOCIO"] = dr.apply(
                        lambda r: _link_neg_nome(r["NEGOCIO"], r.get("NOME_NEGOCIO")), axis=1)
                if "CLIENTE" in dr.columns:
                    dr["CLIENTE"] = dr.apply(
                        lambda r: (
                            f"<a href='{r['LINK_CLIENTE']}' target='_blank'>{r['CLIENTE']}</a>"
                            if r.get("LINK_CLIENTE") and str(r.get("LINK_CLIENTE", "")).strip()
                               not in ("", "None")
                            else str(r.get("CLIENTE", "") or "")
                        ), axis=1)
                _ren_renov = {"NEGOCIO": "Negócio", "CLIENTE": "Cliente",
                              "CONTRATO": "Contrato", "PIPELINE": "Pipeline",
                              "FORMA_PAG": "Forma de Pagamento",
                              "DATA_FECH": "Data de Fechamento",
                              "MRR": "MRR", "BOOKING": "Booking",
                              "COMISSAO": "Comissão"}
                if "CONTRATO" in dr.columns:
                    dr["CONTRATO"] = dr.apply(
                        lambda r: _link_contrato(r.get("ID_CONTRATO"), r["CONTRATO"]), axis=1)
                _aux_cols = [c for c in ("NOME_NEGOCIO", "LINK_CLIENTE", "ID_CONTRATO") if c in dr.columns]
                _dr_export = dr.drop(columns=_aux_cols).rename(columns=_ren_renov)
                dr = dr.drop(columns=_aux_cols)
                _total_bk = float(_renov_comp["BOOKING"].apply(lambda v: float(v or 0)).sum())
                _cap_r, _dl_r = st.columns([6, 1])
                _cap(_cap_r, f"{len(_renov_comp)} negócios | {brl(_total_bk)} Total Booking")
                _dl_r.markdown(
                    df_download_link(_dr_export, f"renovacoes_canc_{mes:02d}_{ano}.xls"),
                    unsafe_allow_html=True,
                )
                html_table(dr.rename(columns=_ren_renov))
            else:
                st.caption("Sem renovações neste período.")

    compat_divider()
    with st.expander("Histórico dos últimos meses"):
        _pares = _hist_pares(ano, mes)
        try:
            _hist = get_comissao_hist(email.lower(), tuple(_pares))
        except Exception as _e:
            if _is_xp_err(_e):
                compat_rerun()
            raise
        hist_rows = []
        for a_h, m_h in _pares:
            d_h = _hist.get((a_h, m_h)) or {}
            if d_h and "erro" not in d_h and d_h.get("is_canc_recovery"):
                hist_rows.append({
                    "Periodo":             f"{MESES.get(m_h, m_h)}/{a_h}",
                    "Valor Recuperado":    brl(d_h["valor_recuperado"]),
                    "Comissão Recuperação": brl(d_h.get("comissao_canc_recovery", 0)),
                    "Comissão Renovações": brl(d_h.get("comissao_renovacoes_canc", 0)),
                    "Total":               brl(d_h.get("total", d_h.get("comissao_canc_recovery", 0))),
                })
        if hist_rows:
            html_table(pd.DataFrame(hist_rows))
        else:
            st.caption("Sem dados históricos disponíveis.")

    st.stop()

# ══ SEGMENTO 1 — Resumo ════════════════════════════════════════════════════════

# Inconsistência (metas RI, jul/2026+): proteção ativa deveria vir acompanhada
# de redução equivalente na meta/OTE (reduction_pct na RI). Proteção > 0 com
# desconto = 0 indica meta carregada já reduzida sem o percentual — o OTE
# Base fica cheio indevidamente. O aviso some quando a RI corrigir.
if ((ano, mes) >= (2026, 7) and dados.get("pct_protecao", 0) > 0
        and (dados.get("desconto") or 0) == 0):
    st.markdown(
        f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
        f"padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0 0.75rem;'>"
        f"⚠️ <b>Possível inconsistência no cadastro da meta</b><br>"
        f"Há proteção de {pct_fmt(dados['pct_protecao'])} cadastrada, mas a meta "
        f"deste mês veio sem percentual de redução.<br>"
        f"O OTE Base está sem a redução correspondente.<br>"
        f"É necessário informar o percentual de redução no cadastro de Meta no RI."
        f"</div>",
        unsafe_allow_html=True,
    )

_partes_total = ["OTE Variável"]
if dados.get("comissao_bk_extra", 0) > 0:
    _partes_total.append("Comissão Extra")
if dados.get("comissao_dividas", 0) > 0:
    _partes_total.append("Comissão sobre Dívidas")
if dados.get("bonificacao_protecao", 0) > 0:
    _partes_total.append("Premiação")
if dados.get("ajuste_total", 0) != 0:
    _partes_total.append("Ajustes de Comissão")
if is_b2g and ((dados.get("b2g_ajuste") or {}).get("ajuste") or 0) > 0:
    _partes_total.append("Ajuste Trimestral")
_formula_total = " + ".join(_partes_total)

_trim_sub = ""
if dados.get("trim"):
    _trim = dados["trim"]
    _fator_trim_total = _trim["fator_ind"] + _trim.get("fator_eq", 0)
    if _fator_trim_total > 0:
        _trim_sub = (
            f"<div style='font-size:0.85rem;font-weight:600;color:#1ecb78;margin-top:6px;'>"
            f"+&nbsp;{pct_fmt(_fator_trim_total)} de um Salário</div>"
        )
_val_total = brl(dados["total"]) + _trim_sub

if is_b2g:
    _H_BIG = 200  # altura p/ cards que span as duas linhas
    _H_SM  = 80

    c = st.columns([1, 1.4, 1, 1, 1, 1])
    stat(c[0], "Cargo", dados["cargo"], min_h=_H_BIG)
    stat(c[1], "Variável Total", _val_total, highlight=True, min_h=_H_BIG)
    formula(c[1], _formula_total)

    _H_PAIR = _H_BIG  # border-box: big card total height = min_h (padding included)

    if not is_gestor:
        stat_pair(c[2], "Realizado (Booking)", brl(dados["bk_real"]),
                        "Realizado (ARR)",     brl(dados["arr_real"]),
                        h_outer=_H_PAIR)
        stat_pair(c[3], "Meta (Booking)",      brl(dados["meta_mrr"]),
                        "Meta (ARR)",          brl(dados["meta_arr"]),
                        h_outer=_H_PAIR)
        stat_pair(c[4], "% Atingido (Booking)", pct_fmt(dados["pct_bk_b2g"]),
                        "% Atingido (ARR)",     pct_fmt(dados["pct_arr_b2g"]),
                        h_outer=_H_PAIR)
        stat(c[5], "% Atingido Pond.", pct_fmt(dados["pct_ponderado"]), min_h=_H_BIG)
    else:
        _rot_ma = dados.get("rotulo_aproveitamento", "marcelo.maestro" in email.lower())
        _lbl_eq      = "Aproveit. Equipe"      if _rot_ma else "% Equipe c/ Meta"
        _lbl_meta_eq = "Meta Aproveit. Equipe" if _rot_ma else "Meta Equipe c/ Meta"
        stat_pair(c[2], "Realizado (Booking)", brl(dados["bk_real"]),
                        _lbl_eq,               pct_fmt(dados["meta_atingida_real"]),
                        h_outer=_H_PAIR)
        stat_pair(c[3], "Meta (Booking)",      brl(dados["meta_mrr"]),
                        _lbl_meta_eq,          pct_fmt(dados["meta_atingida_meta"]),
                        h_outer=_H_PAIR)
        stat_pair(c[4], "% Atingido (Booking)", pct_fmt(dados["pct_bk_b2g"]),
                        "% Meta Atingida",      pct_fmt(dados["pct_meta_atingida"]),
                        h_outer=_H_PAIR)
        stat(c[5], "% Atingido Pond.", pct_fmt(dados["pct_ponderado"]), min_h=_H_BIG)

else:
    label_realizado = f"Realizado ({unidade})"

    c = st.columns([1, 1.4, 1, 1, 1])
    stat(c[0], "Cargo", dados["cargo"], min_h=_H1)
    stat(c[1], "Variável Total", _val_total, highlight=True, min_h=_H1)
    formula(c[1], _formula_total)
    stat(c[2], label_realizado, fmt_val(dados["realizado"]), min_h=_H1)
    _opps_ov = dados.get("opps_override")
    if _opps_ov is not None and is_gd and not is_gestor:
        _sign = "+" if _opps_ov > 0 else ""
        c[2].markdown(
            f"<div style='font-size:0.75rem;color:#6b7280;text-align:center;margin-top:4px;'>"
            f"{_sign}{int(_opps_ov)} Opps por override</div>",
            unsafe_allow_html=True,
        )
    stat(c[3], f"Meta ({unidade})", fmt_val(dados["meta_mrr"]), min_h=_H1)
    stat(c[4], "% Atingido", pct_fmt(dados["pct_atingido"]), min_h=_H1)

# Composição do Realizado (negocios que somam o realizado) — para conferencia
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
_REN = {
    "CONSULTOR": "Consultor", "NEGOCIO": "Negócio", "CLIENTE": "Cliente",
    "NUM_CONTRATO": "Número do Contrato",
    "PRODUTO": "Produto", "PIPELINE": "Pipeline", "FORMA_PAG": "Forma de Pagamento",
    "VALOR": "MRR", "BOOKING": "Booking", "CONTATO": "Contato",
    "DATA_FMT": "Data da Qualificação",
    "DATA_FECH": "Data de Fechamento",
}

with st.expander("Composição do Realizado"):
    comp = get_composicao(email.lower(), ano, mes, dados.get("equipe", ""), is_gestor, is_gd, is_b2g)
    if comp is not None and not comp.empty:
        _busca = st.text_input(
            "Pesquisar",
            placeholder="Cliente, negócio, contrato…",
            key="busca_composicao",
            label_visibility="collapsed",
        )
        _total_comp = len(comp)
        if _busca.strip():
            _term = _busca.strip().lower()
            _mask = pd.Series(False, index=comp.index)
            for _sc in ("CLIENTE", "NOME_NEGOCIO", "NEGOCIO", "NUM_CONTRATO", "CONTATO"):
                if _sc in comp.columns:
                    _mask |= comp[_sc].astype(str).str.lower().str.contains(_term, na=False)
            comp = comp[_mask].copy()
        _filtrado = len(comp) < _total_comp

        if "VALOR" in comp.columns:
            d = comp.copy()
            d["VALOR"] = d["VALOR"].apply(brl)
            d_export = d.drop(columns=[c_ for c_ in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c_ in d.columns]).rename(columns=_REN)
            if "LINK_CLIENTE" in d.columns:
                d["CLIENTE"] = d.apply(
                    lambda r: _link_cliente(r.get("LINK_CLIENTE"), r.get("CLIENTE")), axis=1)
            if "NOME_NEGOCIO" in d.columns:
                d["NEGOCIO"] = d.apply(
                    lambda r: _link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                             max_len=_NEG_MAX_LEN), axis=1)
            elif "NEGOCIO" in d.columns:
                d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
            if "ID_CONTRATO" in d.columns and "NUM_CONTRATO" in d.columns:
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("ID_CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
            d = d.drop(columns=[c_ for c_ in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c_ in d.columns])
            _lnk = df_download_link(d_export, f"realizado_{mes:02d}_{ano}.xls")
            _cnt = f"{len(comp)} de {_total_comp}" if _filtrado else str(len(comp))
            _txt = f"{_cnt} Deals | {brl(float(comp['VALOR'].sum()))} Total de MRR"
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'<span style="color:#6b7280;font-size:0.88rem;">{_txt}</span>'
                f'{_lnk}</div>',
                unsafe_allow_html=True,
            )
            html_table(d.rename(columns=_REN))
        elif "BOOKING" in comp.columns:
            d = comp.copy()
            d["BOOKING"] = d["BOOKING"].apply(brl)
            if "ARR" in d.columns:
                d["ARR"] = d["ARR"].apply(brl)
            d_export = d.drop(columns=[c_ for c_ in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c_ in d.columns]).rename(columns=_REN)
            if "LINK_CLIENTE" in d.columns:
                d["CLIENTE"] = d.apply(
                    lambda r: _link_cliente(r.get("LINK_CLIENTE"), r.get("CLIENTE")), axis=1)
            if "NOME_NEGOCIO" in d.columns:
                d["NEGOCIO"] = d.apply(
                    lambda r: _link_neg_nome(r.get("NEGOCIO"), r.get("NOME_NEGOCIO"),
                                             max_len=_NEG_MAX_LEN), axis=1)
            elif "NEGOCIO" in d.columns:
                d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
            if "ID_CONTRATO" in d.columns and "NUM_CONTRATO" in d.columns:
                d["NUM_CONTRATO"] = d.apply(
                    lambda r: _link_contrato(r.get("ID_CONTRATO"), r.get("NUM_CONTRATO")), axis=1)
            d = d.drop(columns=[c_ for c_ in ("LINK_CLIENTE", "NOME_NEGOCIO", "ID_CONTRATO") if c_ in d.columns])
            _arr_part = f" | {brl(float(comp['ARR'].sum()))} Total de ARR" if "ARR" in comp.columns else ""
            _cnt = f"{len(comp)} de {_total_comp}" if _filtrado else str(len(comp))
            _txt = f"{_cnt} Deals | {brl(float(comp['BOOKING'].sum()))} Total de Booking{_arr_part}"
            _lnk = df_download_link(d_export, f"realizado_{mes:02d}_{ano}.xls")
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'<span style="color:#6b7280;font-size:0.88rem;">{_txt}</span>'
                f'{_lnk}</div>',
                unsafe_allow_html=True,
            )
            html_table(d.rename(columns=_REN))
        else:  # GD — contagem de Opps (Contato vira hyperlink p/ HubSpot)
            d = comp.copy()
            d_export = d.rename(columns=_REN)
            if "CONTATO" in d.columns:
                _base_ct = "https://app.hubspot.com/contacts/44552714/record/0-1/"
                def _link_ct(x):
                    if x is None or str(x).strip() in ("", "None"):
                        return ""
                    cid = str(x).split(".")[0]
                    return f"<a href='{_base_ct}{cid}' target='_blank'>{cid}</a>"
                d["CONTATO"] = d["CONTATO"].apply(_link_ct)
            _lnk = df_download_link(d_export, f"realizado_{mes:02d}_{ano}.xls")
            _cnt = f"{len(comp)} de {_total_comp}" if _filtrado else str(len(comp))
            _txt = f"{_cnt} Opps"
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'<span style="color:#6b7280;font-size:0.88rem;">{_txt}</span>'
                f'{_lnk}</div>',
                unsafe_allow_html=True,
            )
            html_table(d.rename(columns=_REN))
    else:
        st.caption("Sem itens para compor o realizado neste período.")

# ══ SEGMENTO 2 — Comissoes Extras (condicional) ════════════════════════════════

tem_bk_extra  = dados["comissao_bk_extra"] > 0 or dados["booking_extras"] > 0
tem_dividas   = dados["dividas_pagas"] > 0 or dados["comissao_dividas"] > 0
tem_protecao  = dados.get("pct_protecao", 0) > 0
tem_ajuste    = dados.get("ajuste_total", 0) != 0

if tem_bk_extra or tem_dividas or tem_ajuste:
    compat_divider()
    st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Comissões Extras</div>", unsafe_allow_html=True)

    if tem_bk_extra:
        c = st.columns([1, 1, 1.4])
        stat(c[0], "Booking Extra", brl(dados["booking_extras"]))
        stat(c[1], "% de Comissão Aplicado", pct_fmt(dados["pct_bk_extra"]))
        stat(c[2], "Comissão Extra no Mês", brl(dados["comissao_bk_extra"]), highlight=True)
        if dados["comissao_bk_extra"] == 0 and dados["booking_extras"] > 0:
            st.caption(f"Cliff mínimo não atingido ({pct_fmt(dados['cliff_ote_01'])}) — sem comissão sobre booking extra.")
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        with st.expander("Composição do Booking Extra"):
            bk_comp = get_composicao_bk_extra(
                email.lower(), ano, mes, dados.get("equipe", ""), is_gestor
            )
            if bk_comp is not None and not bk_comp.empty:
                d = bk_comp.copy()
                d["BOOKING"] = d["BOOKING"].apply(brl)
                d_export = d.rename(columns=_REN)
                if "NEGOCIO" in d.columns:
                    d["NEGOCIO"] = d["NEGOCIO"].apply(_link_neg)
                _cap_c, _dl_c = st.columns([6, 1])
                _cap(_cap_c, f"{len(bk_comp)} itens | {brl(float(bk_comp['BOOKING'].sum()))} Total de Booking")
                _dl_c.markdown(df_download_link(d_export, f"booking_extra_{mes:02d}_{ano}.xls"), unsafe_allow_html=True)
                html_table(d.rename(columns=_REN))
            else:
                st.caption("Sem itens de booking extra neste período.")

    if tem_dividas:
        if tem_bk_extra:
            st.markdown("")
        pct_div = (dados["comissao_dividas"] / dados["dividas_pagas"]) if dados["dividas_pagas"] > 0 else 0.0
        c = st.columns([1, 1, 1.4])
        stat(c[0], "Dívidas Recuperadas", brl(dados["dividas_pagas"]))
        stat(c[1], "% de Comissão Aplicado", pct_fmt(pct_div))
        stat(c[2], "Comissão sobre Dívidas", brl(dados["comissao_dividas"]), highlight=True)
        if dados["comissao_dividas"] == 0 and dados["dividas_pagas"] > 0:
            st.caption(f"Cliff mínimo não atingido ({pct_fmt(dados['cliff_ote_01'])}) — sem comissão sobre dívidas.")

    if tem_ajuste:
        if tem_bk_extra or tem_dividas:
            st.markdown("")
        with st.expander("Ajustes de Comissão", expanded=True):
            aj_comp = get_ajustes(email.lower(), ano, mes)
            if aj_comp is not None and not aj_comp.empty:
                d = aj_comp.copy()
                d["Valor"] = d["Valor"].apply(brl)
                html_table(d)
            else:
                st.caption("Sem dados.")

# ══ SEGMENTO 2b — Premiação (condicional) ══════════════════════════════════════

if tem_protecao:
    compat_divider()
    st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Premiação</div>", unsafe_allow_html=True)
    c = st.columns(4)
    stat(c[0], "% de Proteção", pct_fmt(dados["pct_protecao"]))
    stat(c[1], "OTE Base", brl(dados["ote_cheio"]))
    stat(c[2], "OTE Base com Desconto", brl(dados["ote_prop"]))
    formula(c[2], f"{brl(dados['ote_cheio'])} × (1 − {pct_fmt(dados['pct_protecao'])})")
    stat(c[3], "Premiação", brl(dados["bonificacao_protecao"]), highlight=True)
    formula(c[3], f"{pct_fmt(dados['pct_protecao'])} × {brl(dados['ote_cheio'])}")

# ══ SEGMENTO 3 — Calculo do OTE ════════════════════════════════════════════════

compat_divider()
st.markdown("<div style='font-size:1.3rem;font-weight:700;color:#1a1a1a;margin-bottom:8px;'>Cálculo do OTE</div>", unsafe_allow_html=True)

# No Saving o OTE Ajustado nao se aplica -> 3 cards (OTE Base, Faixa, OTE Variavel)
if is_saving:
    c = st.columns(3)
    i_base, i_acel, i_var = 0, 1, 2
else:
    c = st.columns(4)
    i_base, i_acel, i_var = 0, 1, 3

# OTE Base — com redução (desconto), mostra o cálculo X × Y = Z
stat(c[i_base], "OTE Base", brl(dados["ote_base"]))
_ote_cheio_ref = dados.get("ote_02_cheio") if dados.get("ote_tier") == 2 else dados.get("ote_cheio")
if (dados.get("desconto") or 0) > 0 and _ote_cheio_ref:
    formula(c[i_base], f"{brl(_ote_cheio_ref)} × {pct_fmt(1 - dados['desconto'])} = {brl(dados['ote_base'])}")
if dados.get("cliff_ote_02") is not None and dados.get("ote_02_prop") is not None:
    if dados["ote_tier"] == 2:
        formula(c[i_base], "OTE máximo já atingido.")
    else:
        formula(c[i_base], f"Próximo: %Atingido de {pct_fmt(dados['cliff_ote_02'])} → OTE de {brl(dados['ote_02_prop'])}")

# Acelerador (ou Faixa, no Saving) — mostra o proximo patamar
if is_saving:
    faixa = dados["faixa_atingida"]
    stat(c[i_acel], "Faixa Atingida", pct_fmt(faixa) if faixa is not None else "—")
    prox = dados.get("proxima_faixa")
    if prox is not None:
        formula(c[i_acel], f"Próxima faixa: %Atingido de {pct_fmt(prox[0])} → Faixa de {pct_fmt(prox[1])}")
    elif faixa is not None:
        formula(c[i_acel], "Faixa máxima já atingida.")
    else:
        formula(c[i_acel], "Abaixo do patamar mínimo (60,00%)")
else:
    stat(c[i_acel], "Acelerador Atingido", pct_fmt(dados['acelerador']))
    if dados["acelerador"] == 0:
        formula(c[i_acel], dados["acel_desc"])
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
            formula(c[i_acel], f"Próximo: %Atingido de {pct_fmt(t)} → Acel de {pct_fmt(m)}")
        elif tiers:
            formula(c[i_acel], "Acelerador máximo já atingido.")
        else:
            formula(c[i_acel], dados["acel_desc"])

# OTE Ajustado (oculto no Saving)
if not is_saving:
    stat(c[2], "OTE Ajustado", brl(ote_ajustado))
    if is_b2g:
        formula(c[2], f"{brl(dados['ote_base'])} × {dados['acelerador']:.2f}")
    elif ote_ajustado is not None:
        formula(c[2], f"{brl(dados['ote_base'])} × {dados['acelerador']:.2f} × {pct_fmt(dados['pct_atingido'])}")

# OTE Variavel
stat(c[i_var], "OTE Variável", brl(dados["ote_variavel"]), highlight=True)
if is_saving:
    faixa = dados["faixa_atingida"]
    if faixa is not None:
        formula(c[i_var], f"{brl(dados['ote_prop'])} × {pct_fmt(dados['pct_atingido'])} × {pct_fmt(faixa)}")
    else:
        formula(c[i_var], "Abaixo do patamar mínimo (60,00%)")
elif is_b2g:
    formula(c[i_var], f"{brl(ote_ajustado)} × {pct_fmt(dados['pct_ponderado'])} (ponderado)")
elif is_gd:
    formula(c[i_var], "= OTE Ajustado (sem forma de pagamento)")
else:
    formula(c[i_var], "Soma por forma de pagamento (tabela abaixo)")

# Tabela de formas de pagamento (somente modelo MRR)
if not is_saving and not is_b2g and not is_gd:
    realizado = dados["realizado"]
    payment_rows = []
    for tipo, mrr_v, mult_v in [
        ("A Vista",    dados["mrr_avista"],     dados["mult_avista"]),
        ("CC 3x",      dados["mrr_cc3x"],       dados["mult_cc3x"]),
        ("CC 12x",     dados["mrr_cc12x"],      dados["mult_cc12x"]),
        ("Recorrente", dados["mrr_recorrente"], dados["mult_recorrente"]),
    ]:
        if mrr_v > 0:
            pct_tipo = mrr_v / realizado if realizado > 0 else 0.0
            contrib  = (ote_ajustado or 0) * pct_tipo * mult_v
            _calc = (
                f"<span style='font-size:0.72rem;opacity:0.65;'>"
                f"{brl(ote_ajustado or 0)} × {pct_fmt(pct_tipo)} × {mult_v:.2f}"
                f"</span>"
            )
            payment_rows.append({
                "Forma de Pagamento": tipo,
                "MRR": brl(mrr_v),
                "% do Total": pct_fmt(pct_tipo),
                "Multiplicador": f"{mult_v:.2f}x",
                "Contribuição para a Comissão": brl(contrib),
                "Cálculo": _calc,
            })
    if payment_rows:
        st.markdown("")
        html_table(pd.DataFrame(payment_rows))
    elif realizado == 0:
        st.caption("Nenhuma venda registrada para este período.")

# ══ SEGMENTO 4 — Historico ════════════════════════════════════════════════════

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
with st.expander("Histórico dos últimos meses"):
    _pares = _hist_pares(ano, mes)
    try:
        _hist = get_comissao_hist(email.lower(), tuple(_pares))
    except Exception as _e:
        if _is_xp_err(_e):
            compat_rerun()
        raise
    hist_rows = []
    for a_h, m_h in _pares:
        d_h = _hist.get((a_h, m_h)) or {}
        if d_h and "erro" not in d_h:
            def _bv(v): return brl(v) if v else "—"
            hist_rows.append({
                "Periodo":          f"{MESES.get(m_h, m_h)}/{a_h}",
                "Realizado":        brl(d_h["realizado"]) if not d_h.get("is_gd") else f"{int(d_h['realizado']):,}".replace(",", "."),
                "Meta":             brl(d_h["meta_mrr"]) if not d_h.get("is_gd") else f"{int(d_h['meta_mrr']):,}".replace(",", "."),
                "% Atingido":       pct_fmt(d_h["pct_atingido"]),
                "OTE Variável":     brl(d_h["ote_variavel"]),
                "Comissão Extra":   _bv(d_h.get("comissao_bk_extra")),
                "Dívidas":          _bv(d_h.get("comissao_dividas")),
                "Premiação":        _bv(d_h.get("bonificacao_protecao")),
                "Ajustes":          _bv(d_h.get("ajuste_total")),
                "Total":            brl(d_h["total"]),
            })
    if hist_rows:
        df_hist = pd.DataFrame(hist_rows)
        cols_show = [c for c in df_hist.columns if not (df_hist[c] == "—").all()]
        html_table(df_hist[cols_show])
    else:
        st.caption("Sem dados históricos disponíveis.")

# ══ SEGMENTO 5 — Comissao Trimestral ══════════════════════════════════════════

if dados.get("trim_bloqueado"):
    compat_divider()
    st.markdown(
        "<div style='background:#fef3c7;border-left:4px solid #d97706;border-radius:6px;"
        "padding:10px 16px;color:#1a1a1a;font-size:0.9rem;'>"
        "⚠️ <b>Comissão trimestral não aplicável</b> a este período para este consultor.</div>",
        unsafe_allow_html=True,
    )
elif dados["trim"]:
    trim = dados["trim"]
    compat_divider()
    st.markdown("<div style='color:#1a1a1a;font-weight:700;font-size:1.25rem;margin:0.5rem 0 0.25rem;'>Comissão Trimestral</div>", unsafe_allow_html=True)

    if trim["is_gestor"] and trim.get("is_b2g"):
        mult_ind = 0.9
    elif trim["is_gestor"]:
        mult_ind = 0.6
    else:
        mult_ind = 0.3

    # Individual
    st.markdown("<span style='color:#1a1a1a;font-weight:700;'>Individual</span>", unsafe_allow_html=True)
    c = st.columns(4)
    stat(c[0], "Realizado", fmt_val(trim["real_ind"]))
    stat(c[1], "Meta", fmt_val(trim["meta_ind"]))
    stat(c[2], "% Atingido", pct_fmt(trim["pct_ind"]))
    if trim["fator_ind"] > 0:
        stat(c[3], "Comissão", f"{pct_fmt(trim['fator_ind'])} de um Salário", highlight=True)
        formula(c[3], f"{pct_fmt(trim['pct_ind'])} × {pct_fmt(mult_ind)} = {pct_fmt(trim['fator_ind'])}")
    else:
        stat(c[3], "Comissão", "—", highlight=True)
        formula(c[3], f"Não atingido: {pct_fmt(trim['pct_ind'])} do trimestre (mínimo 100%).")

    # Equipe (apenas consultores — gestor nao acumula bonus de equipe)
    if not trim["is_gestor"]:
        st.markdown("<span style='color:#1a1a1a;font-weight:700;'>Equipe</span>", unsafe_allow_html=True)
        c = st.columns(4)
        stat(c[0], "Realizado", fmt_val(trim["real_eq"]))
        stat(c[1], "Meta", fmt_val(trim["meta_eq"]))
        stat(c[2], "% Atingido", pct_fmt(trim["pct_eq"]))
        if trim["fator_eq"] > 0:
            stat(c[3], "Comissão", f"{pct_fmt(trim['fator_eq'])} de um Salário", highlight=True)
            formula(c[3], f"{pct_fmt(trim['pct_ind'])} × 30% = {pct_fmt(trim['fator_eq'])}")
        else:
            stat(c[3], "Comissão", "—", highlight=True)
            if trim["pct_eq"] < 1.0:
                formula(c[3], f"Não atingido: {pct_fmt(trim['pct_eq'])} do trimestre (mínimo 100%).")
            else:
                formula(c[3], f"Não atingido: atingimento individual de {pct_fmt(trim['pct_ind'])} abaixo do cliff mínimo.")

    # Ajuste Trimestral (B2G — recalculo acumulado vs. mensais)
    if is_b2g and dados.get("b2g_ajuste"):
        aj = dados["b2g_ajuste"]
        _is_gest = aj.get("is_gestor", False)
        st.markdown("<span style='color:#1a1a1a;font-weight:700;'>Ajuste Trimestral</span>", unsafe_allow_html=True)

        # Pago/ajuste vêm do próprio cálculo (aj) — mesma fonte do Variável
        # Total. Os dicts mensais alimentam apenas a tabela de desenvolvimento.
        _mcache = {}
        for _dm in [mes - 2, mes - 1, mes]:
            _m_h, _a_h = _dm, ano
            while _m_h < 1:
                _m_h += 12
                _a_h -= 1
            try:
                _d_h = get_comissao(email.lower(), _a_h, _m_h)
                if "erro" not in _d_h:
                    _mcache[_m_h] = _d_h
            except Exception as _e:
                if _is_xp_err(_e):
                    compat_rerun()

        pago_3m = float(aj.get("pago_mensal", 0) or 0)
        ajuste_real = float(aj.get("ajuste") or 0)
        if not _is_gest:
            c = st.columns(7)
            stat_pair(c[0], "Realizado (Booking)", brl(aj.get("bk_q", 0)),
                            "Realizado (ARR)",      brl(aj.get("arr_q", 0)),
                            h_outer=_H_BIG)
            stat_pair(c[1], "Meta (Booking)",       brl(aj.get("meta_bk_q", 0)),
                            "Meta (ARR)",           brl(aj.get("meta_arr_q", 0)),
                            h_outer=_H_BIG)
            stat_pair(c[2], "% Atingido (Booking)", pct_fmt(aj.get("pct_bk_q", 0)),
                            "% Atingido (ARR)",     pct_fmt(aj.get("pct_arr_q", 0)),
                            h_outer=_H_BIG)
        else:
            _rot_ma_q = dados.get("rotulo_aproveitamento", "marcelo.maestro" in email.lower())
            _lbl_eq_q      = "Aproveit. Equipe"      if _rot_ma_q else "% Equipe c/ Meta"
            _lbl_meta_eq_q = "Meta Aproveit. Equipe" if _rot_ma_q else "Meta Equipe c/ Meta"
            c = st.columns(7)
            stat_pair(c[0], "Realizado (Booking)", brl(aj.get("bk_q", 0)),
                            _lbl_eq_q,             pct_fmt(aj.get("ma_q", 0)),
                            h_outer=_H_BIG)
            stat_pair(c[1], "Meta (Booking)",      brl(aj.get("meta_bk_q", 0)),
                            _lbl_meta_eq_q,        pct_fmt(dados.get("meta_atingida_meta", 0.8)),
                            h_outer=_H_BIG)
            stat_pair(c[2], "% Atingido (Booking)", pct_fmt(aj.get("pct_bk_q", 0)),
                            "% Meta Atingida",      pct_fmt(aj.get("pct_ma_q", 0)),
                            h_outer=_H_BIG)
        stat(c[3], "% Atingido Pond.",    pct_fmt(aj.get("pct_ponderado_q", 0)), min_h=_H_BIG)
        stat(c[4], "OTE Variável (trim)", brl(aj["ote_variavel_q"]),              min_h=_H_BIG)
        stat(c[5], "Pago nos 3 Meses",    brl(pago_3m),                          min_h=_H_BIG)
        if ajuste_real > 0:
            stat(c[6], "Ajuste Trimestral", brl(ajuste_real), highlight=True,    min_h=_H_BIG)
        else:
            stat(c[6], "Ajuste Trimestral", brl(0), highlight=True,              min_h=_H_BIG)
            formula(c[6], "Acumulado não supera a soma dos mensais.")

        # Tabela de desenvolvimento do cálculo
        _trows = []
        for _dm in [mes - 2, mes - 1, mes]:
            _m_h, _a_h = _dm, ano
            while _m_h < 1:
                _m_h += 12
                _a_h -= 1
            _d = _mcache.get(_m_h, {})
            _row = {"Mês": MESES.get(_m_h, _m_h), "OTE Base": brl(_d.get("ote_base", 0))}
            if _is_gest:
                _row["Book Equipe"]   = brl(_d.get("bk_real", 0))
                _row["Meta Book"]     = brl(_d.get("meta_mrr", 0))
                _row["% Book"]        = pct_fmt(_d.get("pct_bk_b2g", 0))
                _row["Aprov. Eq."]  = pct_fmt(_d.get("meta_atingida_real", 0))
                _row["Meta Aprov."] = pct_fmt(_d.get("meta_atingida_meta", 0))
                _row["% Aprov."]    = pct_fmt(_d.get("pct_meta_atingida", 0))
            else:
                _row["Booking"]     = brl(_d.get("bk_real", 0))
                _row["Meta Book"]     = brl(_d.get("meta_mrr", 0))
                _row["% Book"]        = pct_fmt(_d.get("pct_bk_b2g", 0))
                _row["ARR"]         = brl(_d.get("arr_real", 0))
                _row["Meta ARR"]    = brl(_d.get("meta_arr", 0))
                _row["% ARR"]       = pct_fmt(_d.get("pct_arr_b2g", 0))
            _row["% Pond."]      = pct_fmt(_d.get("pct_ponderado", 0))
            _row["Acelerador"]   = pct_fmt(_d.get("acelerador", 0))
            _row["OTE Variável"] = brl(_d.get("ote_variavel", 0))
            _trows.append(_row)

        # Linha trimestre (acumulado)
        _tr = {"Mês": "Trimestre", "OTE Base": brl(aj.get("ote_base_q", 0))}
        if _is_gest:
            _tr["Book Equipe"]   = brl(aj.get("bk_q", 0))
            _tr["Meta Book"]     = brl(aj.get("meta_bk_q", 0))
            _tr["% Book"]        = pct_fmt(aj.get("pct_bk_q", 0))
            _tr["Aprov. Eq."]  = pct_fmt(aj.get("ma_q", 0))
            _tr["Meta Aprov."] = pct_fmt(dados.get("meta_atingida_meta", 0.8))
            _tr["% Aprov."]    = pct_fmt(aj.get("pct_ma_q", 0))
        else:
            _tr["Booking"]     = brl(aj.get("bk_q", 0))
            _tr["Meta Book"]     = brl(aj.get("meta_bk_q", 0))
            _tr["% Book"]        = pct_fmt(aj.get("pct_bk_q", 0))
            _tr["ARR"]         = brl(aj.get("arr_q", 0))
            _tr["Meta ARR"]    = brl(aj.get("meta_arr_q", 0))
            _tr["% ARR"]       = pct_fmt(aj.get("pct_arr_q", 0))
        _tr["% Pond."]      = pct_fmt(aj.get("pct_ponderado_q", 0))
        _tr["Acelerador"]   = pct_fmt(aj.get("acel_q", 0))
        _tr["OTE Variável"] = brl(aj.get("ote_variavel_q", 0))
        _trows.append(_tr)

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        html_table(pd.DataFrame(_trows))
