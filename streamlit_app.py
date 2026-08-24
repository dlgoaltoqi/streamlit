import re
import sys
import os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

import streamlit as st
import utils.ui as _ui_mod
from utils.connection import get_session, is_admin, is_gestor_in_rls, compat_rerun, current_email, is_real_admin, ano_atual, hide_stale_on_change
from utils.ui import render_banner, _CSS_SHELL_HEAD

_TAB_LABELS = {
    "mc":  "💰 Minha Comissão",
    "me":  "👥 Minha Equipe",
    "pvt": "🔬 Comissão PVT",
    "rd":  "🧾 Recuperação de Dívidas",
    "adm": "⚙️ Administração",
}

# CSS do shell: fonte única em utils.ui._CSS_SHELL_HEAD (esconde sidebar,
# padding 10px, blocos só-CSS, iframes height=0, nav e anti-fantasma).
# Aqui somam-se apenas os elementos do chrome do Streamlit.
st.markdown(
    "<style>"
    + _CSS_SHELL_HEAD +
    "[data-testid='stHeader']{display:none !important;}"
    "[data-testid='stDecoration']{display:none !important;}"
    "[data-testid='stToolbar']{display:none !important;}"
    "[data-testid='stHeaderActionElements']{display:none !important;}"
    "</style>",
    unsafe_allow_html=True,
)

# CSS global e banner ANTES de qualquer query: evita a página "pelada"
# (tema padrão, fundo escuro, sem banner) enquanto o gating consulta o banco.
_ui_mod.render_css()
render_banner()
_ui_mod.render_interaction_guard()

# Troca de página/aba: esconde NA HORA o conteúdo antigo (fantasma), só neste
# rerun. No rerun do clique o _nav_sfx_ ainda é o antigo (muda no handler do
# botão), então o estilo só entra no rerun que desenha a página nova. As
# trocas de FILTRO fazem o mesmo dentro de render_filters/render_period_filter.
hide_stale_on_change("_nav_render_prev_",
                     (st.session_state.get("_nav_sfx_", "mc"),
                      st.session_state.get("_adm_page_sel_", "")))

# Sessão e perfil do usuário
session = get_session()
_real_admin = is_real_admin(session)
_admin  = is_admin(session)
_gestor = is_gestor_in_rls(session)

# Gating das abas Saving/PVT: cache em session_state (chaveado por e-mail/ano,
# entao "Visualizar como" invalida sozinho). Sem isso eram 1-2 queries por
# rerun para nao-admins — o maior custo fixo de cada interacao.
_is_saving_gestor = False
if _gestor and not _admin:
    _sg_email = current_email(session).lower()
    _sg_ano   = int(st.session_state.get("ano", ano_atual()))
    _sg_cache = st.session_state.get("_is_saving_gestor_")
    if isinstance(_sg_cache, tuple) and _sg_cache[0] == (_sg_email, _sg_ano):
        _is_saving_gestor = _sg_cache[1]
    else:
        try:
            _sg_safe = _sg_email.replace("'", "''")
            _sg_df = session.sql(f"""
                SELECT 1 FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
                WHERE ANO = {_sg_ano}
                  AND LOWER(CONSULTOR) = '{_sg_safe}'
                  AND LOWER(EQUIPE) = 'saving'
                LIMIT 1
            """).to_pandas()
            _is_saving_gestor = not _sg_df.empty
            st.session_state["_is_saving_gestor_"] = ((_sg_email, _sg_ano), _is_saving_gestor)
        except Exception:
            pass  # sem cache: o proximo rerun tenta de novo

_is_pvt = False
if not _admin:
    _pvt_email = current_email(session).lower()
    _pvt_cache = st.session_state.get("_is_pvt_")
    if isinstance(_pvt_cache, tuple) and _pvt_cache[0] == _pvt_email:
        _is_pvt = _pvt_cache[1]
    else:
        try:
            _pvt_safe = _pvt_email.replace("'", "''")
            _pvt_df = session.sql(f"""
                SELECT 1 FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE LOWER(EMAIL) = '{_pvt_safe}' AND IS_PVT = TRUE LIMIT 1
            """).to_pandas()
            _is_pvt = not _pvt_df.empty
            st.session_state["_is_pvt_"] = (_pvt_email, _is_pvt)
        except Exception:
            pass  # sem cache: o proximo rerun tenta de novo

# Abas disponíveis para este usuário
_nav_sfxs = ["mc"]
if _gestor or _admin:
    _nav_sfxs.append("me")
if _is_pvt or _admin:
    _nav_sfxs.append("pvt")
if _admin or _is_saving_gestor:
    _nav_sfxs.append("rd")
if _admin or _is_saving_gestor:
    _nav_sfxs.append("adm")

# Inicializa e valida página ativa
if "_nav_sfx_" not in st.session_state:
    st.session_state["_nav_sfx_"] = "mc"
if st.session_state["_nav_sfx_"] not in _nav_sfxs:
    st.session_state["_nav_sfx_"] = "mc"

# ── Modo "Visualizar como" (apenas admin real) ────────────────────────────────
if _real_admin:
    _view_as = st.session_state.get("_view_as_email_", "")
    if _view_as:
        _ic1, _ic2 = st.columns([5, 1])
        _ic1.markdown(
            f"<div style='background:#fef3c7;border-left:4px solid #d97706;"
            f"border-radius:6px;padding:6px 12px;font-size:0.85rem;color:#92400e;'>"
            f"⚠️ Visualizando como: <b>{_view_as}</b></div>",
            unsafe_allow_html=True,
        )
        if _ic2.button("✖ Sair", key="_imp_deact_", use_container_width=True):
            del st.session_state["_view_as_email_"]
            st.session_state.pop("_is_gestor_rls_", None)
            st.session_state.pop("_imp_email_inp_", None)
            compat_rerun()
    else:
        _ic1, _ic2 = st.columns([4, 1])
        _ic1.text_input(
            "Visualizar como",
            placeholder="email@altoqi.com.br",
            key="_imp_email_inp_",
            label_visibility="collapsed",
        )
        if _ic2.button("Visualizar como →", key="_imp_act_", use_container_width=True):
            _inp = (st.session_state.get("_imp_email_inp_", "") or "").strip().lower()
            _imp_err = None
            # Formato estrito: rejeita aspas/espacos/etc. (nenhum vetor de SQL)
            if not re.match(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$", _inp):
                _imp_err = "E-mail inválido."
            else:
                _chk = session.sql(f"""
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
                    ) WHERE E = '{_inp}' LIMIT 1
                """).to_pandas()
                if _chk.empty:
                    _imp_err = "E-mail não encontrado nas bases do painel (metas, parâmetros ou RLS)."
            if _imp_err:
                st.markdown(
                    f"<div style='background:#fee2e2;border-left:4px solid #dc2626;"
                    f"border-radius:6px;padding:6px 12px;font-size:0.85rem;"
                    f"color:#991b1b;'>⚠️ {_imp_err}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.session_state["_view_as_email_"] = _inp
                st.session_state.pop("_is_gestor_rls_", None)
                compat_rerun()

st.markdown('<div id="_nav_marker_"></div>', unsafe_allow_html=True)

_active = st.session_state["_nav_sfx_"]
_nav_cols = st.columns(len(_nav_sfxs))
for _i, _sfx in enumerate(_nav_sfxs):
    with _nav_cols[_i]:
        if _sfx == _active:
            st.markdown(
                f"<div style='"
                f"background:#E8E8E8;"
                f"border-bottom:4px solid #0c5a93;"
                f"border-radius:6px 6px 0 0;"
                f"padding:8px 12px;"
                f"text-align:center;"
                f"font-weight:700;"
                f"font-size:0.95rem;"
                f"color:#1a1a1a;"
                f"cursor:default;"
                f"line-height:1.5;"
                f"margin:0;"
                f"'>{_TAB_LABELS[_sfx]}</div>",
                unsafe_allow_html=True,
            )
        else:
            if st.button(_TAB_LABELS[_sfx], key=f"_navbtn_{_sfx}", use_container_width=True):
                st.session_state["_nav_sfx_"] = _sfx
                compat_rerun()

st.markdown(
    "<hr style='margin:4px 0 8px;border:none;border-top:2px solid #b0b0b0;'>",
    unsafe_allow_html=True,
)


def _exec_page(path, tab_key=""):
    """Executa uma página dentro do contexto da navegação.

    - Define _tab_key_ para render_filters / render_period_filter usarem chaves únicas.
    - Patcha st.button para gerar key única por página, evitando DuplicateWidgetID.
    - Suprime set_page_config, render_banner e render_css das páginas internas.
    """
    st.session_state["_tab_key_"] = tab_key

    _orig_spc    = st.set_page_config
    _orig_banner = _ui_mod.render_banner
    _orig_css    = getattr(_ui_mod, "render_css", None)
    st.set_page_config    = lambda *a, **k: None
    _ui_mod.render_banner = lambda *a, **k: None
    if _orig_css is not None:
        _ui_mod.render_css = lambda *a, **k: None

    _orig_btn = st.button
    def _patched_btn(label="", *args, key=None, **kwargs):
        if key is None:
            key = f"_abtn_{tab_key}_{label}"
        return _orig_btn(label, *args, key=key, **kwargs)
    st.button = _patched_btn

    try:
        exec(
            open(path, encoding="utf-8-sig").read(),
            {"__file__": os.path.abspath(path)},
        )
    finally:
        st.set_page_config    = _orig_spc
        _ui_mod.render_banner = _orig_banner
        if _orig_css is not None:
            _ui_mod.render_css = _orig_css
        st.button = _orig_btn


# ── Conteúdo da página ativa ──────────────────────────────────────────────────
if _active == "mc":
    _exec_page(os.path.join(_dir, "_comissao.py"), tab_key="mc")

elif _active == "me" and (_gestor or _admin):
    _exec_page(os.path.join(_dir, "pages", "02_Minha_Equipe.py"), tab_key="me")

elif _active == "pvt" and (_is_pvt or _admin):
    _exec_page(os.path.join(_dir, "pages", "22_Comissao_PVT.py"), tab_key="pvt")

elif _active == "rd" and (_admin or _is_saving_gestor):
    _exec_page(os.path.join(_dir, "pages", "14_Recuperacao_Dividas.py"), tab_key="rd")

elif _active == "adm" and (_admin or _is_saving_gestor):
    _ADMIN_PAGES_ALL = {
        "🏷️ Cargos e OTEs":                      os.path.join(_dir, "pages", "10_Admin_Cargos_OTEs.py"),
        "⚙️ Parâmetros":                         os.path.join(_dir, "pages", "11_Admin_Parametros.py"),
        "✖️ Multiplicadores por Forma de Pag.":  os.path.join(_dir, "pages", "12_Multiplicadores_por_Forma_de_Pag.py"),
        "📊 Patamares Saving":                   os.path.join(_dir, "pages", "13_Admin_Patamares.py"),
        "💎 Deals ≥ 400k":                       os.path.join(_dir, "pages", "15_Admin_Deals_400k.py"),
        "📋 Override de Realizado GD":           os.path.join(_dir, "pages", "16_Admin_Realizado_GD.py"),
        "🎯 Ponderações Meta":                   os.path.join(_dir, "pages", "17_Admin_Ponderacoes_Meta.py"),
        "🔒 Controle de Acesso":                 os.path.join(_dir, "pages", "18_Admin_Acesso_RLS.py"),
        "✏️ Ajustes Pontuais":                  os.path.join(_dir, "pages", "19_Admin_Ajustes_Pontuais.py"),
        "📂 Exclusões Carteira AM":             os.path.join(_dir, "pages", "25_Admin_Exclusoes_Carteira_AM.py"),
        "📥 Exportar Comissões":                 os.path.join(_dir, "pages", "20_Admin_Exportar_Comissoes.py"),
        "🎯 Metas Consultores":                  os.path.join(_dir, "pages", "21_Admin_Metas.py"),
        "🎯 Override de Metas":                  os.path.join(_dir, "pages", "26_Admin_Metas_Override.py"),
        "🔬 Overrides PVT":                      os.path.join(_dir, "pages", "23_Admin_PVT_Overrides.py"),
        "🔧 Configurações":                      os.path.join(_dir, "pages", "24_Admin_Config.py"),
    }
    _GESTOR_PAGES = {"📊 Patamares Saving"}
    _ADMIN_PAGES = _ADMIN_PAGES_ALL if _admin else {k: v for k, v in _ADMIN_PAGES_ALL.items() if k in _GESTOR_PAGES}
    _ap_sel = st.selectbox(
        "Página de administração",
        list(_ADMIN_PAGES.keys()),
        label_visibility="collapsed",
        key="_adm_page_sel_",
    )
    st.markdown(
        "<hr style='margin:4px 0 8px;border:none;border-top:1px solid #b0b0b0;'>",
        unsafe_allow_html=True,
    )
    _exec_page(_ADMIN_PAGES[_ap_sel], tab_key="adm")

else:
    st.session_state["_nav_sfx_"] = "mc"
    _exec_page(os.path.join(_dir, "_comissao.py"), tab_key="mc")

_ui_mod.render_interaction_guard(height=1)
