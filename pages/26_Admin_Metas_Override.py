import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
st.set_page_config(layout="wide")
import pandas as pd
from snowflake.snowpark.context import get_active_session
from utils.connection import get_session, compat_rerun, compat_divider, render_period_filter, require_admin, audit_user_sql
from utils.ui import render_css, render_banner, html_table, brl, pct_fmt

render_css()
render_banner("Override de Metas")

session = get_session()

require_admin(session)
# Autoria pelo app: CURRENT_USER() volta NULL no SiS (owner's rights).
_usuario_sql = audit_user_sql(session)

from utils.connection import MESES_NOME as MESES

# A view só aplica override a partir de jul/2026 (docs/18_migracao_metas_ri.md).
# Antes disso a meta vem do form e a própria tela Metas Consultores edita.
_OVERRIDE_DESDE = (2026, 7)

# Equipes conhecidas pelo modelo, usadas para barrar erro de digitação: uma
# equipe errada tira a pessoa da varredura do fechamento sem qualquer aviso.
_EQUIPES_FIXAS = [
    "Ares", "B2B Construtora", "B2B Escritório", "Farmer", "FSB", "GD",
    "Governo", "Saving", "Sonia", "AM GDC", "AM Escritório",
]


@st.cache_data(ttl=3000)
def _load_overrides(ano: int, mes: int, ativo: bool) -> pd.DataFrame:
    session = get_active_session()
    return session.sql(f"""
        SELECT EMAIL, EQUIPE, META_BRUTA, PERCENTUAL_DESCONTO_METAS, MOTIVO,
               USUARIO, TO_CHAR(DATA_REGISTRO, 'DD/MM/YYYY HH24:MI') AS REGISTRADO_EM,
               DESATIVADO_POR,
               TO_CHAR(DESATIVADO_EM, 'DD/MM/YYYY HH24:MI') AS DESATIVADO_EM
        FROM SUPERSET.COMISSOES.METAS_OVERRIDE
        WHERE ANO = {ano} AND MES = {mes}
          AND COALESCE(ATIVO, TRUE) = {'TRUE' if ativo else 'FALSE'}
        ORDER BY EQUIPE, EMAIL
    """).to_pandas()


@st.cache_data(ttl=3000)
def _load_equipes(ano: int, mes: int) -> list:
    session = get_active_session()
    df = session.sql(f"""
        SELECT DISTINCT EQUIPE
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
        WHERE ANO = {ano} AND MES = {mes} AND EQUIPE IS NOT NULL
    """).to_pandas()
    achadas = df["EQUIPE"].tolist() if not df.empty else []
    return sorted(set(achadas) | set(_EQUIPES_FIXAS))


@st.cache_data(ttl=3000)
def _load_comparacao(ano: int, mes: int) -> pd.DataFrame:
    """Override ativo do mês x meta que a origem (RI ou form) traria sem ele."""
    session = get_active_session()
    return session.sql(f"""
        WITH ov AS (
            SELECT LOWER(EMAIL) AS EMAIL, EQUIPE, META_BRUTA,
                   COALESCE(PERCENTUAL_DESCONTO_METAS, 0) AS PCT,
                   MOTIVO, USUARIO,
                   TO_CHAR(DATA_REGISTRO, 'DD/MM/YYYY HH24:MI') AS REGISTRADO_EM
            FROM SUPERSET.COMISSOES.METAS_OVERRIDE
            WHERE ANO = {ano} AND MES = {mes} AND COALESCE(ATIVO, TRUE)
        ),
        ri AS (
            -- QUALIFY porque a pessoa pode ter mais de um pipeline no mês; sem
            -- isso o LEFT JOIN duplicaria a linha do override na comparação.
            SELECT LOWER(rio.EMAIL) AS EMAIL,
                   ricg.TARGET_VALUE AS BRUTA,
                   COALESCE(ricg.REDUCTION_PCT, 0) AS PCT
            FROM REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANT_GOALS ricg
            JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_CONSULTANTS ric
              ON ric.ID = ricg.CONSULTANT_ID
            LEFT JOIN REVENUE_INTELLIGENCE.REVENUE_INTELLIGENCE_PRATA.REVENUE_INTELLIGENCE_OWNERS rio
              ON rio.ID = ric.HUBSPOT_OWNER_ID
            WHERE ricg.YEAR = {ano} AND ricg.MONTH = {mes}
              AND ricg.TARGET_VALUE IS NOT NULL
              AND rio.EMAIL IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY LOWER(rio.EMAIL) ORDER BY ricg.TARGET_VALUE DESC) = 1
        ),
        fm AS (
            SELECT LOWER(EMAIL) AS EMAIL,
                   META_NMRR_BRUTO + META_EXPANSAO_BRUTO + META_RENOVACAO_BRUTO AS BRUTA,
                   COALESCE(PERCENTUAL_DESCONTO_METAS, 0) AS PCT
            FROM SUPERSET.PARCIAL.META_CONSULTOR
            WHERE ANO = {ano} AND MES = {mes}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY LOWER(EMAIL)
                ORDER BY META_NMRR_BRUTO + META_EXPANSAO_BRUTO + META_RENOVACAO_BRUTO DESC) = 1
        )
        SELECT ov.EMAIL, ov.EQUIPE,
               ov.META_BRUTA AS OV_BRUTA, ov.PCT AS OV_PCT,
               ROUND(ov.META_BRUTA * (1 - ov.PCT / 100), 2) AS OV_LIQUIDA,
               IFF(ri.EMAIL IS NOT NULL, 'RI',
                   IFF(fm.EMAIL IS NOT NULL, 'Form', 'sem origem')) AS ORIGEM,
               COALESCE(ri.BRUTA, fm.BRUTA) AS OR_BRUTA,
               ROUND(COALESCE(ri.BRUTA, fm.BRUTA)
                     * (1 - IFF(COALESCE(ri.PCT, fm.PCT) > 1,
                                COALESCE(ri.PCT, fm.PCT) / 100,
                                COALESCE(ri.PCT, fm.PCT))), 2) AS OR_LIQUIDA,
               ov.MOTIVO, ov.USUARIO, ov.REGISTRADO_EM
        FROM ov
        LEFT JOIN ri ON ri.EMAIL = ov.EMAIL
        LEFT JOIN fm ON fm.EMAIL = ov.EMAIL
        ORDER BY ov.EQUIPE, ov.EMAIL
    """).to_pandas()


ano, mes = render_period_filter()

st.markdown(
    "<div style='color:#1a1a1a;background:#dbeafe;border-radius:6px;"
    "padding:0.75rem 1rem;border-left:4px solid #0c5a93;margin:0.5rem 0;'>"
    "Correção administrativa de meta para os meses em que a origem é o "
    "<b>Revenue Intelligence</b> e a tela Metas Consultores é somente leitura. "
    "O override <b>vence o RI e o formulário</b> e aparece lá com a fonte "
    "<b>Override</b>.<br>"
    "A meta líquida é derivada: <b>bruta × (1 − desconto/100)</b>. O desconto "
    "também reduz o OTE Base da pessoa, como no RI.</div>",
    unsafe_allow_html=True,
)

if (ano, mes) < _OVERRIDE_DESDE:
    st.markdown(
        "<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
        "padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
        "⚠️ Override vale apenas de <b>julho/2026</b> em diante. Até junho/2026 a "
        "meta vem do formulário e pode ser editada direto em "
        "<b>Metas Consultores</b>.</div>",
        unsafe_allow_html=True,
    )
    st.stop()

try:
    df       = _load_overrides(ano, mes, ativo=True)
    inativos = _load_overrides(ano, mes, ativo=False)
    equipes  = _load_equipes(ano, mes)
except Exception as _qe:
    if "terminated" in str(_qe).lower() or "xp process" in str(_qe).lower():
        compat_rerun()
    st.error(f"Erro ao carregar dados: {_qe}")
    st.stop()

# ── Aviso de período fechado ──────────────────────────────────────────────────

try:
    _fech = session.sql(f"""
        SELECT EQUIPE FROM SUPERSET.COMISSOES.FECHAMENTOS
        WHERE ANO = {ano} AND MES = {mes} AND STATUS = 'ATIVO'
        ORDER BY EQUIPE
    """).to_pandas()
    _eqs_fechadas = _fech["EQUIPE"].tolist() if not _fech.empty else []
except Exception:
    _eqs_fechadas = []

if _eqs_fechadas:
    st.markdown(
        f"<div style='color:#1a1a1a;background:#fef3c7;border-radius:6px;"
        f"padding:0.75rem 1rem;border-left:4px solid #d97706;margin:0.5rem 0;'>"
        f"⚠️ Equipes com fechamento ativo em {MESES.get(mes, mes)}/{ano}: "
        f"<b>{', '.join(_eqs_fechadas)}</b>. Para essas equipes a comissão vem do "
        f"snapshot, então o override só muda o resultado depois de reabrir e "
        f"refazer o fechamento em <b>Exportar Comissões</b>.</div>",
        unsafe_allow_html=True,
    )

# ── Tabela editável ───────────────────────────────────────────────────────────

_COLS_EDIT = ["EMAIL", "EQUIPE", "META_BRUTA", "PERCENTUAL_DESCONTO_METAS", "MOTIVO"]
df_edit = df[_COLS_EDIT].copy() if not df.empty else pd.DataFrame(columns=_COLS_EDIT)

_orig_chaves = {
    (str(r["EMAIL"]).strip().lower(), str(r["EQUIPE"]).strip())
    for _, r in df_edit.iterrows() if str(r.get("EMAIL") or "").strip()
}

_data_editor = getattr(st, "data_editor", None) or getattr(st, "experimental_data_editor", None)
if _data_editor is None:
    st.error("Esta versão do Streamlit não suporta edição inline de tabelas.")
    st.stop()

st.markdown(
    f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>"
    f"<b>META_BRUTA</b> em reais (Opps para GD). "
    f"<b>PERCENTUAL_DESCONTO_METAS</b> em pontos percentuais, ou seja 50 = 50%. "
    f"Tirar a linha da tabela desativa o override e preserva o histórico.</p>",
    unsafe_allow_html=True,
)

edited = _data_editor(
    df_edit,
    num_rows="dynamic",
    use_container_width=True,
    key=f"metas_override_editor_{ano}_{mes}",
)

if st.button("💾 Salvar alterações", type="primary"):

    def _norm_cell(v):
        try:
            if v is None or pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(v, str):
            return v.strip()
        try:
            return round(float(v), 6)
        except (TypeError, ValueError):
            return str(v).strip()

    _orig_rows = {
        (str(r["EMAIL"]).strip().lower(), str(r["EQUIPE"]).strip()):
            tuple(_norm_cell(r[c]) for c in _COLS_EDIT)
        for _, r in df_edit.iterrows() if str(r.get("EMAIL") or "").strip()
    }

    errors, linhas = [], []
    chaves_editadas = set()

    for _, row in edited.iterrows():
        em = str(row.get("EMAIL") or "").strip().lower()
        if not em:
            continue
        eq = str(row.get("EQUIPE") or "").strip()
        if not eq:
            errors.append(f"Equipe não informada para {em}.")
            continue
        if eq not in equipes:
            errors.append(
                f"Equipe '{eq}' desconhecida para {em}. Use uma destas: {', '.join(equipes)}.")
            continue
        try:
            bruta = float(row.get("META_BRUTA"))
        except (TypeError, ValueError):
            errors.append(f"Meta bruta inválida para {em}.")
            continue
        if bruta <= 0:
            errors.append(f"Meta bruta de {em} precisa ser maior que zero.")
            continue
        try:
            pct = float(row.get("PERCENTUAL_DESCONTO_METAS") or 0)
        except (TypeError, ValueError):
            errors.append(f"Desconto inválido para {em}.")
            continue
        if pct < 0 or pct >= 100:
            errors.append(f"Desconto de {em} precisa ficar entre 0 e 99,99.")
            continue
        motivo = str(row.get("MOTIVO") or "").strip()
        if not motivo:
            errors.append(f"Motivo é obrigatório para {em}.")
            continue

        chave = (em, eq)
        if chave in chaves_editadas:
            errors.append(f"{em} aparece duas vezes na equipe {eq}.")
            continue
        chaves_editadas.add(chave)

        mudou = _orig_rows.get(chave) != tuple(
            _norm_cell(row[c]) for c in _COLS_EDIT)
        if mudou:
            linhas.append((em, eq, bruta, pct, motivo))

    # Uma pessoa não pode ter override em duas equipes: a precedência na view é
    # por (ano, mês, e-mail), então as duas linhas apareceriam juntas.
    _por_email = {}
    for em, eq in chaves_editadas:
        _por_email.setdefault(em, []).append(eq)
    for em, eqs in _por_email.items():
        if len(eqs) > 1:
            errors.append(
                f"{em} tem override em mais de uma equipe ({', '.join(sorted(eqs))}). "
                f"A precedência é por pessoa e mês, então mantenha apenas uma.")

    removidas = _orig_chaves - chaves_editadas

    if errors:
        for err in errors:
            st.error(err)
        st.stop()

    _tot = len(linhas) + len(removidas)
    if _tot == 0:
        st.session_state["_ovr_save_ok_"] = "Nenhuma alteração para salvar."
        compat_rerun()

    _done = 0
    _pb = st.progress(0, text=f"Salvando alterações… 0/{_tot}")
    salvos = 0

    for em, eq in removidas:
        _done += 1
        _pb.progress(_done / _tot, text=f"Salvando alterações… {_done}/{_tot}")
        try:
            # Preserva USUARIO/DATA_REGISTRO: eles guardam quem definiu os
            # valores, não quem desativou.
            session.sql(f"""
                UPDATE SUPERSET.COMISSOES.METAS_OVERRIDE
                SET ATIVO = FALSE, DESATIVADO_POR = {_usuario_sql},
                    DESATIVADO_EM = CURRENT_TIMESTAMP()
                WHERE ANO = {ano} AND MES = {mes}
                  AND LOWER(EMAIL) = '{em.replace("'", "''")}'
                  AND EQUIPE = '{eq.replace("'", "''")}'
            """).collect()
        except Exception as e:
            errors.append(f"Erro ao desativar {em}: {e}")

    for em, eq, bruta, pct, motivo in linhas:
        _done += 1
        _pb.progress(_done / _tot, text=f"Salvando alterações… {_done}/{_tot}")
        try:
            session.sql(f"""
                MERGE INTO SUPERSET.COMISSOES.METAS_OVERRIDE AS t
                USING (SELECT
                    {ano} AS ANO, {mes} AS MES,
                    '{em.replace("'", "''")}' AS EMAIL,
                    '{eq.replace("'", "''")}' AS EQUIPE,
                    {pct} AS PCT, {bruta} AS BRUTA,
                    '{motivo.replace("'", "''")}' AS MOTIVO
                ) AS s
                ON t.ANO = s.ANO AND t.MES = s.MES
                   AND LOWER(t.EMAIL) = LOWER(s.EMAIL) AND t.EQUIPE = s.EQUIPE
                WHEN MATCHED THEN UPDATE SET
                    PERCENTUAL_DESCONTO_METAS = s.PCT,
                    META_BRUTA    = s.BRUTA,
                    ATIVO          = TRUE,
                    MOTIVO         = s.MOTIVO,
                    USUARIO        = {_usuario_sql},
                    DATA_REGISTRO  = CURRENT_TIMESTAMP(),
                    DESATIVADO_POR = NULL,
                    DESATIVADO_EM  = NULL
                WHEN NOT MATCHED THEN INSERT
                    (ANO, MES, EMAIL, EQUIPE, PERCENTUAL_DESCONTO_METAS,
                     META_BRUTA, ATIVO, MOTIVO, USUARIO, DATA_REGISTRO)
                VALUES
                    (s.ANO, s.MES, s.EMAIL, s.EQUIPE, s.PCT,
                     s.BRUTA, TRUE, s.MOTIVO, {_usuario_sql}, CURRENT_TIMESTAMP())
            """).collect()
            salvos += 1
        except Exception as e:
            errors.append(f"Erro ao salvar {em}: {e}")

    _pb.empty()
    if errors:
        for err in errors:
            st.error(err)
    else:
        st.session_state["_ovr_save_ok_"] = (
            f"{salvos} override(s) salvos. {len(removidas)} desativado(s).")
        st.cache_data.clear()
        compat_rerun()

_msg_ok = st.session_state.pop("_ovr_save_ok_", None)
if _msg_ok:
    st.markdown(
        f"<div style='color:#1a1a1a;background:#dcfce7;border-radius:6px;"
        f"padding:0.6rem 0.9rem;border-left:4px solid #16a34a;margin:0.4rem 0;'>"
        f"✓ {_msg_ok}</div>",
        unsafe_allow_html=True,
    )

# ── Efeito no mês ─────────────────────────────────────────────────────────────

compat_divider()
st.markdown(
    "<p style='color:#1a1a1a;font-size:0.95rem;font-weight:600;margin:0.5rem 0 0.25rem;'>"
    "Efeito no mês</p>", unsafe_allow_html=True)

try:
    comp = _load_comparacao(ano, mes)
except Exception as _qe:
    comp = pd.DataFrame()
    st.error(f"Erro ao comparar com a origem: {_qe}")

if comp.empty:
    st.markdown(
        f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>"
        f"Nenhum override ativo em {MESES.get(mes, mes)}/{ano}.</p>",
        unsafe_allow_html=True,
    )
else:
    def _delta(r):
        if pd.isna(r["OR_LIQUIDA"]):
            return "—"
        d = float(r["OV_LIQUIDA"]) - float(r["OR_LIQUIDA"])
        return ("+" if d > 0 else "") + brl(d)

    html_table(pd.DataFrame({
        "Consultor":       comp["EMAIL"],
        "Equipe":          comp["EQUIPE"],
        "Origem":          comp["ORIGEM"],
        "Meta da origem":  comp["OR_LIQUIDA"].apply(
            lambda v: brl(v) if pd.notna(v) else "—"),
        "Meta do override": comp["OV_LIQUIDA"].apply(brl),
        "% Desconto":      comp["OV_PCT"].apply(
            lambda v: pct_fmt(float(v) / 100) if pd.notna(v) and float(v) > 0 else "—"),
        "Diferença":       comp.apply(_delta, axis=1),
        "Motivo":          comp["MOTIVO"],
        "Por":             comp["USUARIO"],
        "Em":              comp["REGISTRADO_EM"],
    }))

# ── Desativados ───────────────────────────────────────────────────────────────

compat_divider()
with st.expander(f"Overrides desativados ({len(inativos)})", expanded=False):
    if inativos.empty:
        st.markdown(
            "<p style='color:#1a1a1a;font-size:0.875rem;margin:0.25rem 0;'>"
            "Nenhum override desativado neste mês.</p>",
            unsafe_allow_html=True,
        )
    else:
        html_table(pd.DataFrame({
            "Consultor":  inativos["EMAIL"],
            "Equipe":     inativos["EQUIPE"],
            "Meta bruta": inativos["META_BRUTA"].apply(brl),
            "% Desconto": inativos["PERCENTUAL_DESCONTO_METAS"].apply(
                lambda v: pct_fmt(float(v) / 100) if pd.notna(v) and float(v) > 0 else "—"),
            "Motivo":       inativos["MOTIVO"],
            "Criado por":   inativos["USUARIO"].fillna("—"),
            "Criado em":    inativos["REGISTRADO_EM"].fillna("—"),
            "Desativado por": inativos["DESATIVADO_POR"].fillna("—"),
            "Desativado em":  inativos["DESATIVADO_EM"].fillna("—"),
        }))
        _opts = [f"{r['EMAIL']} | {r['EQUIPE']}" for _, r in inativos.iterrows()]
        _sel = st.selectbox("Reativar", _opts, key=f"ovr_react_{ano}_{mes}")
        if st.button("Reativar override", type="secondary"):
            _em, _eq = [p.strip() for p in _sel.split("|", 1)]
            # Reativar não mexe nos valores, então a autoria de criação fica.
            session.sql(f"""
                UPDATE SUPERSET.COMISSOES.METAS_OVERRIDE
                SET ATIVO = TRUE, DESATIVADO_POR = NULL, DESATIVADO_EM = NULL
                WHERE ANO = {ano} AND MES = {mes}
                  AND LOWER(EMAIL) = '{_em.lower().replace("'", "''")}'
                  AND EQUIPE = '{_eq.replace("'", "''")}'
            """).collect()
            st.session_state["_ovr_save_ok_"] = f"Override de {_em} reativado."
            st.cache_data.clear()
            compat_rerun()


