"""Helpers visuais compartilhados entre as paginas do painel."""
import io as _io
import base64 as _base64

import streamlit as st
import pandas as _pd

from utils.connection import _cache_decorator


def download_link(data: bytes, filename: str, label: str = "Exportar",
                  mime: str = "application/octet-stream") -> str:
    """Markup de <a download> estilizado como botão (o SiS não serve arquivos,
    então o download é um data: URI em base64). Fonte única do visual."""
    b64 = _base64.b64encode(data).decode("ascii")
    return (
        f'<a href="data:{mime};base64,{b64}" download="{filename}"'
        f' style="display:inline-block;padding:0.45rem 1.1rem;'
        f'background:#083b8a;color:#fff;border-radius:6px;'
        f'text-decoration:none;font-weight:600;font-size:0.9rem;">{label}</a>'
    )


def df_download_link(df, fname: str, label: str = "Exportar", sheet_name=None) -> str:
    """DataFrame → .xlsx (openpyxl; fallback .csv utf-8-sig ';') → link de download.
    A extensão de fname é trocada conforme o formato efetivamente gerado.

    A geração é cacheada (14/08/2026): openpyxl + base64 rodavam em TODO rerun
    para cada tabela exportável da página. Se o hash do DataFrame falhar, cai
    na geração direta."""
    try:
        return _df_download_link_cached(df, fname, label, sheet_name)
    except Exception:
        return _df_download_link_raw(df, fname, label, sheet_name)


def _df_download_link_raw(df, fname: str, label: str, sheet_name) -> str:
    try:
        import openpyxl  # noqa: F401
        buf = _io.BytesIO()
        with _pd.ExcelWriter(buf, engine="openpyxl") as w:
            if sheet_name:
                df.to_excel(w, index=False, sheet_name=sheet_name)
            else:
                df.to_excel(w, index=False)
        data = buf.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = fname.rsplit(".", 1)[0] + ".xlsx"
    except Exception:
        data = df.to_csv(index=False, sep=";").encode("utf-8-sig")
        mime = "text/csv"
        filename = fname.rsplit(".", 1)[0] + ".csv"
    return download_link(data, filename, label, mime)


_df_download_link_cached = _cache_decorator(ttl=3000)(_df_download_link_raw)

# ── Logo AltoQi (base64) ───────────────────────────────────────────────────────
_LOGO_B64 = "data:image/png;base64,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zojpeI02uSxJFDMqODhY2PyiPQBzywJL6ihchj4+sbGXhfeciFBSg9OXK1cOY0Y/9dYj25POPyxYJDoDo8fK+vXtDRosCvczJrAZ69FmxcpVa0BXBg03mAhIisTQ6YUOoC+qEok68bz//oCTJ0+LiqNoihTbuHBSisAk09fXB69NnmDSS8mWBKb6CWO6sXUt7jq279iJ2NgrsmAlv/OIiHDh+I3cMa2dFUmtnEhLPtf0lCg5+YhdxjeURf2H/LEL7iXTWjomZovgAiqWl55RpeOpAP//BadnAhdhIVqbUUwlOmwXeyKSpprkkkcbJEomchZ4661/mBRp6CetJIGpUnIcGTVquOhZtq0JXKB0wW4t7S6TzzS9+mfq2IaiatDRUIf27RESUlUIiCDnkoKStqN2Z2c/QXx8PA4e/E24sELTY7FEU2Nan9P+ScH1UboDTDeRxEIS08dp4IB+wnXLAjdTJrAZ6xFxTbm60Re0YGdRyU5Assy9tVN4o+np4+HKvilkaiPLVLuoQ1m7hCgKQ6qXdqkzHmciKysTebl5wgeGzslpravUDEhpO9KMipZeNLrSyxd0tu3q5oZiXp6Cc45hu6mvkS2L6nOFfcQLPnSmPhC2tIlUrBwiJpZUZTgfI6A3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BJjAerM466spBJjAmjInK6M3BP4fCdsjP8Nxmn8AAAAASUVORK5CYII="


# Banner desenhado por CSS puro (::before do block-container). NÃO voltar a
# renderizá-lo como elemento Streamlit: no SiS 1.22, transições rápidas de
# página removem elementos do DOM sem recriá-los (nem reenviando delta novo a
# cada rerun) e o banner "se perdia" até o F5 (14/08/2026). O block-container
# nunca é removido e o CSS vive no <head> persistente — indestrutível.
_CSS_BANNER = (
    # Faixa do banner (::before, em fluxo) — gradiente + título.
    "[data-testid='stMain']>.block-container,"
    ".main>.block-container,"
    "section.main>.block-container{position:relative;}"
    "[data-testid='stMain']>.block-container::before,"
    ".main>.block-container::before,"
    "section.main>.block-container::before{"
    "content:'Painel de Comissões';"
    "display:flex;align-items:center;box-sizing:border-box;"
    "height:144px;padding:0 36px 0 154px;margin:0 0 8px;"
    "border-radius:12px;color:#ffffff;"
    "font-size:2.5rem;font-weight:700;line-height:1.2;"
    "font-family:'Segoe UI',Arial,sans-serif;"
    "background:linear-gradient(to right,#083b8a,#0c5a93 40%,#129b92 70%,#1ecb78);"
    "}"
    # Círculo branco com o logo (::after, absoluto sobre a faixa). O
    # border-radius corta as pontas do quadrado do logo, como o
    # overflow:hidden fazia na versão-elemento. Offsets: padding 10px do
    # container + 36px/27px internos da faixa.
    "[data-testid='stMain']>.block-container::after,"
    ".main>.block-container::after,"
    "section.main>.block-container::after{"
    "content:'';position:absolute;top:37px;left:46px;"
    "width:90px;height:90px;border-radius:50%;"
    f"background:#ffffff url('{_LOGO_B64}') center/70px 70px no-repeat;"
    "box-shadow:0 2px 8px rgba(0,0,0,0.2);"
    "}"
)


def render_banner(subtitle=""):
    """O banner é desenhado pelo CSS (_CSS_BANNER, ::before do block-container),
    não por um elemento — ver comentário acima. Aqui só se garante o CSS
    global no corpo o mais cedo possível (o <head> persistente cobre o resto)."""
    st.markdown(_CSS_GLOBAL, unsafe_allow_html=True)


_CSS_GLOBAL = (
    "<style>"
    "html, body, [class*='css'], .stApp {"
    "font-family: 'Segoe UI', Arial, sans-serif !important;"
    "}"
    ".stApp, [data-testid='stAppViewContainer'], [data-testid='stMain'] {"
    "background-color: #E8E8E8 !important;"
    "}"
    "html body [data-testid='stWidgetLabel'] p,"
    "html body [data-testid='stWidgetLabel'] label,"
    "html body .stSelectbox label, html body .stTextInput label,"
    "html body .stNumberInput label, html body label {"
    "color: #1a1a1a !important; font-weight: 700 !important;"
    "}"
    "[data-testid='stExpander'], details[open], details {"
    "border: 1px solid #1a1a1a !important; border-radius: 8px !important;"
    "}"
    "[data-testid='stExpander'] summary, details summary,"
    "[data-testid='stExpander'] summary p, details summary p,"
    ".streamlit-expanderHeader, .streamlit-expanderHeader p {"
    "color: #1a1a1a !important; font-weight: 700 !important;"
    "}"
    "[data-testid='stSelectbox'] > div > div,"
    "[data-baseweb='select'] > div,"
    ".stSelectbox [data-baseweb='select'] > div {"
    "background-color: #ffffff !important;"
    "border-color: #ffffff !important;"
    "}"
    "[data-baseweb='select']:focus-within > div {"
    "border-color: #0c5a93 !important;"
    "box-shadow: 0 0 0 1px #0c5a93 !important;"
    "}"
    "[data-baseweb='select'] span,"
    "[data-baseweb='select'] div,"
    "[data-baseweb='select'] input,"
    "[data-baseweb='select'] [class*='placeholder'],"
    "[data-baseweb='select'] [class*='singleValue'],"
    "[data-baseweb='select'] [class*='value' i],"
    "[data-testid='stSelectbox'] span,"
    "[data-testid='stSelectbox'] div[class] {"
    "color: #1a1a1a !important;"
    "}"
    "[data-baseweb='popover'],"
    "[data-baseweb='menu'],"
    "[role='listbox'] {"
    "background-color: #ffffff !important;"
    "}"
    "[data-baseweb='menu-item'],"
    "li[role='option'] {"
    "background-color: #ffffff !important;"
    "color: #1a1a1a !important;"
    "}"
    "[data-baseweb='menu-item']:hover,"
    "li[role='option']:hover {"
    "background-color: #e5e7eb !important;"
    "}"
    "div[data-testid='stButton'] > button,"
    "div[data-testid='stButton'] button,"
    "[data-testid='stBaseButton-secondary'],"
    "[data-testid='stBaseButton-primary'],"
    ".stButton > button,"
    ".stButton button {"
    "background: #6b7280 !important;"
    "background-color: #6b7280 !important;"
    "background-image: none !important;"
    "color: #ffffff !important;"
    "font-weight: 600 !important;"
    "border: none !important;"
    "border-radius: 4px !important;"
    "}"
    "div[data-testid='stButton'] > button:hover,"
    "div[data-testid='stButton'] button:hover,"
    "[data-testid='stBaseButton-secondary']:hover,"
    "[data-testid='stBaseButton-primary']:hover,"
    ".stButton > button:hover {"
    "background: #4b5563 !important;"
    "background-color: #4b5563 !important;"
    "background-image: none !important;"
    "border: none !important;"
    "}"
    "[data-baseweb='input'] {"
    "background-color: #ffffff !important;"
    "border: 1px solid #ffffff !important;"
    "}"
    "[data-baseweb='input']:focus-within {"
    "border: 1px solid #0c5a93 !important;"
    "box-shadow: 0 0 0 1px #0c5a93 !important;"
    "}"
    "[data-baseweb='input'] input,"
    "[data-testid='stTextInput'] input,"
    "[data-testid='stNumberInput'] input {"
    "background-color: #ffffff !important;"
    "color: #1a1a1a !important;"
    "}"
    "[data-baseweb='input'] input::placeholder,"
    "[data-testid='stTextInput'] input::placeholder,"
    "[data-testid='stNumberInput'] input::placeholder {"
    "color: #9ca3af !important;"
    "opacity: 1 !important;"
    "}"
    "html body [data-testid='stNumberInputStepUp'],"
    "html body [data-testid='stNumberInputStepDown'],"
    "html body [data-baseweb='number-input'] button,"
    "html body [data-testid='stNumberInput'] button {"
    "background-color: #083b8a !important;"
    "background-image: none !important;"
    "color: #ffffff !important;"
    "border: none !important;"
    "border-radius: 3px !important;"
    "}"
    "input[type='number']::-webkit-inner-spin-button,"
    "input[type='number']::-webkit-outer-spin-button {"
    "-webkit-appearance: none;"
    "margin: 0;"
    "}"
    "html body [data-testid='stCheckbox'] span,"
    "html body [data-testid='stCheckbox'] p,"
    "html body [data-testid='stCheckbox'] label {"
    "color: #1a1a1a !important;"
    "}"
    "::-webkit-scrollbar {"
    "width: 8px;"
    "height: 8px;"
    "}"
    "::-webkit-scrollbar-track {"
    "background: #e8edf5;"
    "border-radius: 4px;"
    "}"
    "::-webkit-scrollbar-thumb {"
    "background: #083b8a;"
    "border-radius: 4px;"
    "}"
    "::-webkit-scrollbar-thumb:hover {"
    "background: #0c5a93;"
    "}"
    "[data-testid='stSpinner'] *,"
    ".stSpinner *,"
    ".stProgress * {"
    "color: #1ecb78 !important;"
    "}"
    "[data-testid='stStatusWidget']{"
    "display:none !important;"
    "}"
    "[data-testid='stProgressBar'] {"
    "color: #1a1a1a !important;"
    "}"
    "[data-testid='stProgressBar'] > div {"
    "background-color: #1a1a1a !important;"
    "border-radius: 4px !important;"
    "}"
    "[data-testid='stProgressBar'] > div > div {"
    "background-color: #1ecb78 !important;"
    "border-radius: 4px !important;"
    "}"
    "[data-testid='stHeaderActionElements'] {"
    "display: none !important;"
    "}"
    "[data-testid='stHeader'] {"
    "display: none !important;"
    "}"
    "[data-testid='stDecoration'] {"
    "display: none !important;"
    "}"
    "[data-testid='stToolbar'] {"
    "display: none !important;"
    "}"
    + _CSS_BANNER +
    "</style>"
)


# Regras do shell no <head> persistente do documento pai. O Streamlit nunca
# toca o <head> durante reruns; os blocos <style> do corpo somem/voltam a cada
# rerun, e é isso que "quebra" o visual quando uma interação interrompe o
# carregamento. O _app.py importa esta constante para o CSS do corpo — fonte
# única, sem cópia manual.
_CSS_SHELL_HEAD = (
    "[data-testid='stSidebar']{display:none !important;}"
    "[data-testid='collapsedControl']{display:none !important;}"
    "[data-testid='stMain']>.block-container,.main>.block-container,"
    "section.main>.block-container{padding-top:10px !important;"
    "padding-left:10px !important;padding-right:10px !important;}"
    "div[data-testid='stElementContainer']:has(>div[data-testid='stMarkdown']>div[data-testid='stMarkdownContainer']>style:only-child),"
    "div[data-testid='element-container']:has(>div[data-testid='stMarkdown']>div[data-testid='stMarkdownContainer']>style:only-child),"
    "div.element-container:has(>div.stMarkdown>div[data-testid='stMarkdownContainer']>style:only-child)"
    "{display:none !important;}"
    "div[data-testid='stElementContainer']:has(iframe[height='0']),"
    "div[data-testid='element-container']:has(iframe[height='0']),"
    "div.element-container:has(iframe[height='0'])"
    "{display:none !important;}"
    # Anti-fantasma: durante o rerun o Streamlit mantem o DOM antigo marcado
    # como data-stale (versoes antigas: .stale-element). O delay de .6s e
    # essencial: rerun rapido (<0,6s) nao esmaece NADA (senao todo clique
    # escurece a tela e o app parece lento); transicao demorada esmaece os
    # fantasmas. A volta e instantanea porque o estado base nao define
    # transition. Nunca usar display:none (apagaria a pagina inteira).
    # O banner e imune por construcao: e ::before do block-container
    # (_CSS_BANNER), nao um elemento sujeito a stale/remocao.
    "div[data-stale='true'],.stale-element{"
    "opacity:.15 !important;transition:opacity .3s ease .6s !important;}"
    "div:has(#_nav_marker_)+div button{"
    "background:#083b8a !important;background-color:#083b8a !important;"
    "background-image:none !important;color:#ffffff !important;"
    "font-weight:700 !important;border:none !important;border-radius:6px 6px 0 0 !important;}"
    "div:has(#_nav_marker_)+div button:hover{"
    "background:#0c5a93 !important;background-color:#0c5a93 !important;}"
    "div:has(#_nav_marker_)+div button *{color:#ffffff !important;}"
)


def render_css():
    """Injeta o CSS global do painel (_CSS_GLOBAL) — fonte única de estilos.
    Paginas chamam render_css() em vez de colar o bloco: dentro do _app.py a
    chamada vira no-op (o _app ja injetou via render_banner); standalone,
    injeta de verdade. Apenas CSS — nada que ocupe slot no layout (um iframe
    aqui empurraria o banner para baixo)."""
    st.markdown(_CSS_GLOBAL, unsafe_allow_html=True)


def render_interaction_guard(height: int = 0):
    """Injeta o CSS do painel no <head> do documento pai via iframe.
    O Streamlit nunca mexe no <head> durante reruns, então o visual
    sobrevive a qualquer número de interações (os blocos <style> do
    corpo somem no rerun; o do <head> não).
    height=0 fica oculto pelo CSS (regra iframe height=0); height=1
    escapa dessa regra (fallback no fim da página)."""
    try:
        import json as _json
        import streamlit.components.v1 as components
        _head_css = _CSS_SHELL_HEAD + _CSS_GLOBAL.replace(
            "<style>", "").replace("</style>", "")
        components.html(
            """
            <script>
            (function() {
                var P;
                try { P = window.parent.document; } catch (e) { return; }
                function injectHeadStyle() {
                    var s = P.getElementById('_sis_persistent_css_');
                    if (!s) {
                        s = P.createElement('style');
                        s.id = '_sis_persistent_css_';
                        P.head.appendChild(s);
                    }
                    var css = __HEAD_CSS__;
                    if (s.textContent !== css) s.textContent = css;
                }
                if (P.readyState === 'loading') {
                    P.addEventListener('DOMContentLoaded', injectHeadStyle);
                } else {
                    injectHeadStyle();
                }
            })();
            </script>
            """.replace("__HEAD_CSS__", _json.dumps(_head_css)),
            height=height,
            scrolling=False,
        )
    except Exception:
        pass


def render_guard_probe():
    """TEMP (12/08/2026): sonda de diagnóstico do canal JS de iframe no SiS.
    Renderiza um iframe VISÍVEL que reporta, linha a linha, o que funciona:
    JS inline em srcdoc, acesso ao documento pai, testids disponíveis, estado
    dos iframes height=0 e se o CSS persistente foi injetado no <head>.
    Remover esta função e sua chamada no _app.py após o diagnóstico."""
    try:
        import streamlit.components.v1 as components
        components.html(
            """
            <div style="font-family:monospace;font-size:12px;color:#111;
                        background:#fffbe6;border:1px solid #d97706;
                        border-radius:6px;padding:6px 10px;line-height:1.5;">
              <b>[sonda TEMP]</b> linha estática — se nada aparecer abaixo,
              o JS inline do iframe está bloqueado (CSP).
              <div id="r"></div>
            </div>
            <script>
            (function(){
              var out = document.getElementById('r');
              function add(t){
                var d = document.createElement('div');
                d.textContent = t;
                out.appendChild(d);
              }
              add('1. JS do iframe executou');
              var P = null;
              try {
                P = window.parent.document;
                add('2. parent.document acessível');
              } catch (e) {
                add('2. parent.document BLOQUEADO: ' + e.name);
                return;
              }
              var app = P.querySelector('[data-testid="stApp"]');
              add('3. stApp por testid: ' + (app
                  ? 'ok, state=' + (app.getAttribute('data-test-script-state') || '(sem atributo)')
                  : 'NAO ENCONTRADO'));
              var appc = P.querySelector('.stApp');
              add('3b. .stApp por classe: ' + (appc ? 'ok' : 'NAO ENCONTRADO'));
              if (appc) {
                var at = [];
                for (var j = 0; j < appc.attributes.length; j++)
                  at.push(appc.attributes[j].name + '=' +
                          String(appc.attributes[j].value).substring(0, 60));
                add('3c. atributos do .stApp: ' + at.join('  |  '));
              }
              add('4. stStatusWidget: ' +
                  (P.querySelector('[data-testid="stStatusWidget"]') ? 'presente' : 'ausente'));
              add('5. CSS persistente no head: ' +
                  (P.getElementById('_sis_persistent_css_') ? 'INJETADO' : 'AUSENTE'));
              var ifr = P.querySelectorAll('iframe[height="0"]');
              add('6. iframes height=0 no parent: ' + ifr.length);
              for (var i = 0; i < ifr.length; i++) {
                var s = '?';
                try {
                  s = ifr[i].contentDocument
                      ? ifr[i].contentDocument.readyState
                      : 'sem contentDocument (nao carregou)';
                } catch (e) { s = 'acesso bloqueado (' + e.name + ')'; }
                add('   6.' + i + ' iframe: ' + s);
              }
              try {
                var st_ = P.createElement('style');
                st_.id = '_probe_sty_';
                P.head.appendChild(st_);
                add('7. head do parent gravavel');
              } catch (e) {
                add('7. head do parent BLOQUEADO: ' + e.name);
              }
            })();
            </script>
            """,
            height=280,
            scrolling=True,
        )
    except Exception:
        pass


def render_reload_watchdog():
    """Watchdog do SiS: recarrega a pagina se ficar presa em 'Starting...'.
    Cria um iframe (components.html) que OCUPA um slot vertical no layout —
    nunca chamar antes do banner/topo da pagina."""
    try:
        import streamlit.components.v1 as components
        components.html(
            """
            <script>
            (function() {
                // Aguarda 6s para não interferir no carregamento inicial normal
                setTimeout(function() {
                    setInterval(function() {
                        try {
                            var txt = window.parent.document.body.innerText || '';
                            if (txt.indexOf('Starting...') !== -1) {
                                setTimeout(function() {
                                    window.parent.location.reload();
                                }, 1500);
                            }
                        } catch(e) {}
                    }, 2500);
                }, 6000);
            })();
            </script>
            """,
            height=0,
            scrolling=False,
        )
    except Exception:
        pass


# ── Paleta AltoQi ─────────────────────────────────────────────────────────────
_HIGHLIGHT_BORDER = "#0c5a93"          # azul principal AltoQi
_HIGHLIGHT_VAL    = "#1ecb78"          # verde destaque AltoQi
_CARD_BORDER      = "rgba(128,128,128,0.25)"
_CARD_BG          = "#ffffff"
_CARD_SHADOW      = "rgba(15,23,42,0.10)"
_TABLE_BORDER_HD  = "#6b7280"
_TABLE_BORDER_ROW = "#d1d5db"


def brl(v):
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct_fmt(v):
    if v is None:
        return "—"
    return f"{v:.2%}".replace(".", ",")


def stat(col, label, value, highlight=False, min_h=94, val_color=None):
    """Card arredondado com profundidade, cabecalho e conteudo centralizados.
    min_h: altura minima do card (px) — aumente para comportar rotulos de 2 linhas.
    val_color: sobrescreve a cor do valor (ex: 'inherit' para manter cor do tema)."""
    if highlight:
        border   = f"2px solid {_HIGHLIGHT_BORDER}"
        valcolor = val_color if val_color is not None else _HIGHLIGHT_VAL
        valsize  = "1.6rem"
    else:
        border   = f"1px solid {_CARD_BORDER}"
        valcolor = val_color if val_color is not None else "#1a1a1a"
        valsize  = "1.35rem"
    col.markdown(
        f"<div style='border:{border};border-radius:14px;padding:14px 10px;"
        f"box-shadow:0 3px 10px {_CARD_SHADOW};text-align:center;"
        f"background:{_CARD_BG};min-height:{min_h}px;"
        "display:flex;flex-direction:column;justify-content:center;'>"
        "<div style='font-size:0.95rem;font-weight:600;color:#555555;margin-bottom:4px;'>"
        f"{label}</div>"
        f"<div style='font-size:{valsize};font-weight:700;line-height:1.15;color:{valcolor};"
        f"word-break:break-word;'>{value}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def stat_pair(col, top_label, top_value, bot_label, bot_value,
              top_highlight=False, bot_highlight=False, h_outer=228, gap=12):
    """Two cards filling a fixed-height column: booking at top, ARR at bottom, equal heights."""
    def _cs(hl):
        if hl:
            return f"2px solid {_HIGHLIGHT_BORDER}", _HIGHLIGHT_VAL, "1.6rem"
        return f"1px solid {_CARD_BORDER}", "#1a1a1a", "1.35rem"
    tb, tvc, tvs = _cs(top_highlight)
    bb, bvc, bvs = _cs(bot_highlight)

    def _card(b, vc, vs, label, value):
        return (
            f"<div style='flex:1;box-sizing:border-box;border:{b};border-radius:14px;"
            f"padding:14px 10px;box-shadow:0 3px 10px {_CARD_SHADOW};text-align:center;"
            f"background:{_CARD_BG};"
            "display:flex;flex-direction:column;justify-content:center;'>"
            "<div style='font-size:0.95rem;font-weight:600;color:#555555;margin-bottom:4px;'>"
            f"{label}</div>"
            f"<div style='font-size:{vs};font-weight:700;line-height:1.15;color:{vc};"
            f"word-break:break-word;'>{value}</div>"
            "</div>"
        )

    col.markdown(
        f"<div style='display:flex;flex-direction:column;gap:{gap}px;height:{h_outer}px;'>"
        + _card(tb, tvc, tvs, top_label, top_value)
        + _card(bb, bvc, bvs, bot_label, bot_value)
        + "</div>",
        unsafe_allow_html=True,
    )


def formula(col, text):
    col.markdown(
        f"<div style='font-size:0.72rem;font-weight:600;color:#374151;text-align:center;"
        f"margin-top:6px;'>{text}</div>",
        unsafe_allow_html=True,
    )


def html_table(df, scrollable=False, subheader: dict | None = None, compact_headers=False):
    """Renderiza um DataFrame como tabela HTML (ver html_table_str)."""
    st.markdown(html_table_str(df, scrollable, subheader, compact_headers),
                unsafe_allow_html=True)


def html_table_str(df, scrollable=False, subheader: dict | None = None, compact_headers=False):
    """Markup de um DataFrame como tabela HTML sem indice, com cabecalho e conteudo centralizados.
    scrollable=True envolve em overflow-x:auto para tabelas largas.
    subheader: dict col→categoria — renderiza uma linha de referência logo abaixo do cabeçalho.
    compact_headers=True permite quebra de linha no cabeçalho e reduz padding para tabelas largas."""
    _HEADER_GRADIENT = "linear-gradient(to right,#083b8a,#0c5a93 40%,#129b92 70%,#1ecb78)"
    if compact_headers:
        _th_style = (
            "padding:8px 6px;text-align:center;white-space:normal;word-break:break-word;"
            "min-width:60px;line-height:1.2;background:transparent;color:#ffffff;"
            "font-weight:700;border:none;"
        )
        _td_pad = "6px 6px"
    else:
        _th_style = (
            "padding:6px 12px;text-align:center;white-space:nowrap;"
            "background:transparent;color:#ffffff;font-weight:700;border:none;"
        )
        _td_pad = "6px 12px"
    th = "".join(
        f"<th style='{_th_style}'>{h}</th>"
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
    for _, r in df.iterrows():
        tds = "".join(
            f"<td style='padding:{_td_pad};text-align:center;white-space:nowrap;"
            f"border-top:none;border-left:none;border-right:none;"
            f"border-bottom:1px solid {_TABLE_BORDER_ROW};'>{v}</td>"
            for v in r
        )
        rows += f"<tr>{tds}</tr>"
    table = (
        f"<table style='width:100%;border-collapse:collapse;font-size:0.9rem;color:#1a1a1a;'>"
        f"<thead><tr style='background:{_HEADER_GRADIENT};'>{th}</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    if scrollable:
        table = f"<div style='overflow-x:auto;'>{table}</div>"
    return table
