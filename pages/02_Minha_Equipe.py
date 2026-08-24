import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")

from utils.ui import render_css
render_css()
import pandas as pd
from utils.connection import (
    get_session, compat_divider, get_comissao,
    is_admin, get_snapshot_info, current_email,
    ano_atual, mes_atual, hide_stale_on_change,
)
from utils.ui import brl, pct_fmt, stat, html_table, render_banner, df_download_link

from utils.connection import MESES_NOME as MESES

render_banner("Minha Equipe")

session    = get_session()
_sfx       = st.session_state.get("_tab_key_", "")
_user      = current_email(session).lower()
_user_safe = _user.replace("'", "''")
_admin_me  = is_admin(session)

# ── Filtros ───────────────────────────────────────────────────────────────────

_anos_me = list(range(ano_atual(), 2024, -1))
_meses_me = list(MESES.keys())

_key_ano = f"_me_ano_{_sfx}"
_key_mes = f"_me_mes_{_sfx}"
if _key_ano not in st.session_state or st.session_state[_key_ano] not in _anos_me:
    st.session_state[_key_ano] = int(st.session_state.get("ano", ano_atual()))
if _key_mes not in st.session_state:
    st.session_state[_key_mes] = int(st.session_state.get("mes", mes_atual()))

col_ano, col_mes, col_filtro = st.columns([1, 1, 3])
col_ano.selectbox("📅 Ano", _anos_me, key=_key_ano)
col_mes.selectbox("🗓️ Mês", _meses_me, key=_key_mes, format_func=lambda x: MESES[x][:3])
ano = st.session_state[_key_ano]
mes = st.session_state[_key_mes]
st.session_state["ano"] = ano
st.session_state["mes"] = mes

consultor        = None
equipe           = ""
eq_map_ne        = {}
todos_membros_ne = []
equipe_ne        = "Todas"

if _admin_me:
    _gest_df = session.sql(f"""
        SELECT DISTINCT LOWER(EMAIL) AS EMAIL
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND IS_GESTOR = TRUE
        ORDER BY EMAIL
    """).to_pandas()
    gestores = _gest_df["EMAIL"].tolist() if not _gest_df.empty else []
    if not gestores:
        col_filtro.selectbox("👤 Líder", ["(nenhum)"], disabled=True)
        st.warning("Nenhum gestor encontrado para este período.")
        st.stop()
    _key_lid = f"_me_lider_{_sfx}"
    if _key_lid not in st.session_state or st.session_state[_key_lid] not in gestores:
        st.session_state[_key_lid] = gestores[0]
    col_filtro.selectbox("👤 Líder", gestores, key=_key_lid)
    consultor = st.session_state[_key_lid]
else:
    rls_df = session.sql(f"""
        SELECT LOWER(CONSULTOREMAIL) AS EMAIL
        FROM SUPERSET.PARCIAL.PERMISSAO_RLS
        WHERE ANO = {ano} AND MES = {mes}
          AND LOWER(USUARIOEMAIL) = '{_user_safe}'
          AND TIPOUSUARIO = 'Gestor'
        ORDER BY CONSULTOREMAIL
    """).to_pandas()
    todos_membros_ne = rls_df["EMAIL"].tolist() if not rls_df.empty else []

    if todos_membros_ne:
        _vals_ne = ",".join("'" + e.replace("'", "''") + "'" for e in todos_membros_ne)
        eq_df_ne = session.sql(f"""
            SELECT EMAIL, EQUIPE FROM (
                SELECT LOWER(CONSULTOR) AS EMAIL, EQUIPE,
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(CONSULTOR)
                           ORDER BY ABS(MES - {mes}) ASC, MES DESC
                       ) AS rn
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = {ano} AND EQUIPE IS NOT NULL
                  AND LOWER(CONSULTOR) IN ({_vals_ne})
            ) WHERE rn = 1
        """).to_pandas()
        eq_map_ne = {str(r["EMAIL"]): str(r["EQUIPE"]) for _, r in eq_df_ne.iterrows()}
        cr_df_ne = session.sql(f"""
            SELECT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
              AND LOWER(EMAIL) IN ({_vals_ne})
        """).to_pandas()
        for _, r in cr_df_ne.iterrows():
            eq_map_ne[str(r["EMAIL"])] = "Cancelamento"
        _equipes_ne_opc = ["Todas"] + sorted({v for v in eq_map_ne.values() if v})
    else:
        _equipes_ne_opc = ["(nenhuma)"]

    _key_eq = f"_me_equipe_{_sfx}"
    if _key_eq not in st.session_state or st.session_state[_key_eq] not in _equipes_ne_opc:
        st.session_state[_key_eq] = "Todas" if "Todas" in _equipes_ne_opc else _equipes_ne_opc[0]
    col_filtro.selectbox("👥 Equipe", _equipes_ne_opc, key=_key_eq,
                         disabled=not todos_membros_ne)

    if not todos_membros_ne:
        st.markdown(
            "<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            "Nenhum consultor encontrado na equipe para este período.</div>",
            unsafe_allow_html=True,
        )
        st.stop()
    equipe_ne = st.session_state[_key_eq]

hide_stale_on_change("_me_flt_prev_", (ano, mes, consultor, equipe_ne))

# ── Montar lista de membros ───────────────────────────────────────────────────

_show_equipe_col = False

if _admin_me:
    _cons_safe = consultor.lower().replace("'", "''")
    meta_gest_df = session.sql(f"""
        SELECT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND LOWER(CONSULTOR) = '{_cons_safe}'
    """).to_pandas()

    if meta_gest_df.empty:
        st.markdown(
            "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>"
            "Sem dados de meta para este gestor neste período.</div>",
            unsafe_allow_html=True,
        )
        st.stop()

    equipe = str(meta_gest_df.iloc[0]["EQUIPE"] or "")
    st.markdown(
        f"<div style='color:#1a1a1a;font-weight:700;font-size:1.5rem;"
        f"margin:0.5rem 0 0.25rem;'>{equipe}</div>",
        unsafe_allow_html=True,
    )

    _canc_union = f"""
        UNION
        SELECT LOWER(EMAIL) AS EMAIL
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = {ano} AND MES = {mes} AND IS_CANC_RECOVERY = TRUE
    """ if equipe == "Saving" else ""

    _eq_safe = equipe.replace("'", "''")
    membros_df = session.sql(f"""
        SELECT EMAIL FROM (
            SELECT LOWER(m.CONSULTOR) AS EMAIL
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
            INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
              ON p.ANO = m.ANO AND p.MES = m.MES AND LOWER(p.EMAIL) = LOWER(m.CONSULTOR)
            WHERE m.ANO = {ano} AND m.MES = {mes}
              AND m.EQUIPE = '{_eq_safe}' AND p.IS_GESTOR = FALSE
            {_canc_union}
        )
        ORDER BY EMAIL
    """).to_pandas()

    if membros_df.empty:
        st.markdown(
            "<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            "Nenhum consultor encontrado na equipe para este período.</div>",
            unsafe_allow_html=True,
        )
        st.stop()

    _snap_me = get_snapshot_info(ano, mes, consultor.lower())
    if _snap_me:
        try:
            _data_me = pd.to_datetime(_snap_me["data"]).strftime("%d/%m/%Y")
            _data_txt_me = f" em {_data_me}"
        except Exception:
            _data_txt_me = ""
        st.markdown(
            f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            f"padding:0.4rem 0.9rem;border-left:4px solid #d97706;"
            f"font-size:0.9rem;margin:0.3rem 0 0.6rem;'>"
            f"🔒 <strong>Período fechado{_data_txt_me}.</strong> "
            f"Se houver algum negócio não contabilizado ou com valor desatualizado, "
            f"solicite o recálculo para Higor.</div>",
            unsafe_allow_html=True,
        )

else:
    # Não-admin: filtra pelo equipe selecionada (ou usa todos)
    if equipe_ne != "Todas":
        membros_lista = sorted(
            [c for c in todos_membros_ne if eq_map_ne.get(c) == equipe_ne]
        )
        equipe = equipe_ne
        st.markdown(
            f"<div style='color:#1a1a1a;font-weight:700;font-size:1.5rem;"
            f"margin:0.5rem 0 0.25rem;'>{equipe_ne}</div>",
            unsafe_allow_html=True,
        )
    else:
        membros_lista = sorted(todos_membros_ne, key=lambda e: (eq_map_ne.get(e, ""), e))
        equipe = "todas"
        _show_equipe_col = True

    membros_df = pd.DataFrame({"EMAIL": membros_lista})

    if membros_df.empty:
        st.markdown(
            "<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
            "padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
            "Nenhum consultor encontrado na equipe para este período.</div>",
            unsafe_allow_html=True,
        )
        st.stop()

# ── Calcular comissões ────────────────────────────────────────────────────────

st.markdown(
    f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0 0 0.75rem;'>"
    f"{len(membros_df)} consultores encontrados.</p>",
    unsafe_allow_html=True,
)

rows    = []
errors  = []
progress = st.progress(0)
total_m  = len(membros_df)

for idx, (_, row) in enumerate(membros_df.iterrows()):
    email_m = str(row["EMAIL"]).lower()
    try:
        dados = get_comissao(email_m, ano, mes)
        if "erro" in dados:
            errors.append(f"{email_m}: {dados['erro']}")
        else:
            is_gd_m  = dados.get("is_gd", False)
            is_b2g_m = dados.get("is_b2g", False)
            unidade_m = "Opps" if is_gd_m else ("Booking" if is_b2g_m else "MRR")
            _eq_m = eq_map_ne.get(email_m, equipe) if not _admin_me else equipe
            rows.append({
                "Equipe":        _eq_m,
                "Consultor":     email_m,
                "Cargo":         dados["cargo"],
                "Realizado":     dados["realizado"],
                "Unidade":       unidade_m,
                "Meta":          dados["meta_mrr"],
                "% Atingido":    dados["pct_atingido"],
                "OTE Variável":  dados["ote_variavel"],
                "Comissão Extra": dados.get("comissao_bk_extra", 0) + dados.get("comissao_dividas", 0),
                "Premiação":     dados.get("bonificacao_protecao", 0) or 0,
                "Total":                  dados["total"],
                "Valor Recuperado Total": dados.get("valor_recuperado", 0),
                "Valor Recuperado MRR":   dados.get("mrr_recuperado", 0),
                "_is_canc":      dados.get("is_canc_recovery", False),
            })
    except Exception as e:
        errors.append(f"{email_m}: {e}")
    progress.progress((idx + 1) / total_m)

progress.empty()

if errors:
    with st.expander(f"{len(errors)} erro(s)"):
        for err in errors:
            st.markdown(
                f"<div style='color:#1a1a1a;font-size:0.85rem;'>{err}</div>",
                unsafe_allow_html=True,
            )

if not rows:
    st.info("Nenhuma comissão pôde ser calculada.")
    st.stop()

df_result = pd.DataFrame(rows)

# Premiação (proteção) é paga à parte do total — colunas só quando houver valor
_tem_premiacao = (df_result["Premiação"].fillna(0) > 0).any() if "Premiação" in df_result.columns else False

# ── Tabela resumo ─────────────────────────────────────────────────────────────

unidade_equipe = df_result["Unidade"].iloc[0] if not df_result.empty else "MRR"
is_gd_equipe   = unidade_equipe == "Opps"
fmt_val = (lambda v: f"{int(v):,}".replace(",", ".")) if is_gd_equipe else brl

if equipe == "Cancelamento":
    _disp = {
        "Consultor":              df_result["Consultor"],
        "Valor Recuperado Total": df_result["Valor Recuperado Total"].apply(brl),
        "Valor Recuperado MRR":   df_result["Valor Recuperado MRR"].apply(brl),
        "Comissão":               df_result["Total"].apply(brl),
    }
else:
    _disp = {}
    if _show_equipe_col:
        _disp["Equipe"] = df_result["Equipe"]
    _disp.update({
        "Consultor":                    df_result["Consultor"],
        "Cargo":                        df_result["Cargo"],
        f"Realizado ({unidade_equipe})": df_result.apply(
            lambda r: "-" if r["_is_canc"] else fmt_val(r["Realizado"]), axis=1),
        f"Meta ({unidade_equipe})":     df_result.apply(
            lambda r: "-" if r["_is_canc"] else fmt_val(r["Meta"]), axis=1),
        "% Atingido":                   df_result.apply(
            lambda r: "-" if r["_is_canc"] else pct_fmt(r["% Atingido"]), axis=1),
        "OTE Variável":                 df_result.apply(
            lambda r: "-" if r["_is_canc"] else brl(r["OTE Variável"]), axis=1),
        "Comissão Extra":               df_result.apply(
            lambda r: "-" if r["_is_canc"] else brl(r["Comissão Extra"]), axis=1),
    })
    if _tem_premiacao:
        _disp["Premiação"] = df_result.apply(
            lambda r: "-" if r["_is_canc"] else brl(r["Premiação"]), axis=1)
    _disp["Total"] = df_result["Total"].apply(brl)
df_display = pd.DataFrame(_disp)

html_table(df_display)

# ── Totais ────────────────────────────────────────────────────────────────────

compat_divider()
if equipe == "Cancelamento":
    c = st.columns(3)
    stat(c[0], "Total Recuperado", brl(df_result["Valor Recuperado Total"].sum()))
    stat(c[1], "Total Recuperado MRR", brl(df_result["Valor Recuperado MRR"].sum()))
    stat(c[2], "Total Comissões", brl(df_result["Total"].sum()), highlight=True)
else:
    _df_main = df_result[~df_result["_is_canc"]]
    c = st.columns(6 if _tem_premiacao else 5)
    stat(c[0], f"Total Realizado ({unidade_equipe})", fmt_val(_df_main["Realizado"].sum()))
    stat(c[1], "% Médio Atingido", pct_fmt(_df_main["% Atingido"].mean() if not _df_main.empty else 0.0))
    stat(c[2], "Total OTE Variável", brl(df_result["OTE Variável"].sum()))
    stat(c[3], "Total Extras", brl(df_result["Comissão Extra"].sum()))
    if _tem_premiacao:
        stat(c[4], "Total Premiações", brl(df_result["Premiação"].sum()))
    stat(c[-1], "Total Comissões", brl(df_result["Total"].sum()), highlight=True)
st.markdown("")

# ── Exportar ──────────────────────────────────────────────────────────────────

st.markdown(
    df_download_link(df_display, f"equipe_{equipe}_{mes:02d}_{ano}.xlsx",
                     sheet_name=f"{MESES.get(mes, mes)[:3]}{ano}"),
    unsafe_allow_html=True,
)
