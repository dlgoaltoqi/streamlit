"""Blocos da tela Minha Equipe — porta de pages/02_Minha_Equipe.py.

Dois modos, como no SiS: admin escolhe o Líder; gestor vê a própria equipe
(RLS) com seletor de Equipe quando lidera mais de uma. Melhoria sobre o SiS:
o loop get_comissao por membro roda em paralelo.
"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from webapp.core.cache import RLS, ttl_cached
from webapp.db.pool import get_pool
from webapp.presentation import brl, fmt_cargo, html_table_str, pct_fmt, stat
from webapp.services import comissao_service as cs
from webapp.services import rls_service
from webapp.views.comissao_view import (aviso_ambar, aviso_azul, celula,
                                        divisor, expander, linha)


@ttl_cached(RLS)
def gestores_periodo(ano: int, mes: int) -> tuple:
    with get_pool().session() as s:
        df = s.sql("""
            SELECT DISTINCT LOWER(EMAIL) AS EMAIL
            FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = %s AND MES = %s AND IS_GESTOR = TRUE
            ORDER BY EMAIL
        """, (ano, mes)).to_pandas()
    return tuple(str(e) for e in df["EMAIL"])


@ttl_cached(RLS)
def _equipe_do_gestor(ano: int, mes: int, lider: str):
    with get_pool().session() as s:
        df = s.sql("""
            SELECT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND MES = %s AND LOWER(CONSULTOR) = %s
        """, (ano, mes, lider)).to_pandas()
    if df.empty:
        return None
    return str(df.iloc[0]["EQUIPE"] or "")


@ttl_cached(RLS)
def _membros_da_equipe(ano: int, mes: int, equipe: str) -> tuple:
    """Membros não-gestores da equipe; Saving agrega as consultoras de
    Cancelamento (cópia de pages/02:154-173)."""
    canc_union = """
        UNION
        SELECT LOWER(EMAIL) AS EMAIL
        FROM SUPERSET.COMISSOES.PARAMETROS
        WHERE ANO = %s AND MES = %s AND IS_CANC_RECOVERY = TRUE
    """ if equipe == "Saving" else ""
    params = [ano, mes, equipe] + ([ano, mes] if canc_union else [])
    with get_pool().session() as s:
        df = s.sql(f"""
            SELECT EMAIL FROM (
                SELECT LOWER(m.CONSULTOR) AS EMAIL
                FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
                INNER JOIN SUPERSET.COMISSOES.PARAMETROS p
                  ON p.ANO = m.ANO AND p.MES = m.MES AND LOWER(p.EMAIL) = LOWER(m.CONSULTOR)
                WHERE m.ANO = %s AND m.MES = %s
                  AND m.EQUIPE = %s AND p.IS_GESTOR = FALSE
                {canc_union}
            )
            ORDER BY EMAIL
        """, tuple(params)).to_pandas()
    return tuple(str(e) for e in df["EMAIL"])


def _calcular_membros(ano, mes, membros, equipe_rotulo, eq_map=None):
    """(df, errors) com uma linha por membro (paralelo)."""
    def _um(email_m):
        try:
            return email_m, cs.get_comissao(email_m, ano, mes), None
        except Exception as e:
            return email_m, None, str(e)

    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for email_m, dados, err in ex.map(_um, membros):
            if err:
                errors.append(f"{email_m}: {err}")
                continue
            if "erro" in dados:
                errors.append(f"{email_m}: {dados['erro']}")
                continue
            is_gd_m = dados.get("is_gd", False)
            is_b2g_m = dados.get("is_b2g", False)
            rows.append({
                "Equipe": (eq_map or {}).get(email_m, equipe_rotulo),
                "Consultor": email_m,
                "Cargo": fmt_cargo(dados["cargo"]),
                "Realizado": dados["realizado"],
                "Unidade": "Opps" if is_gd_m else ("Booking" if is_b2g_m else "MRR"),
                "Meta": dados["meta_mrr"],
                "% Atingido": dados["pct_atingido"],
                "OTE Variável": dados["ote_variavel"],
                "Comissão Extra": dados.get("comissao_bk_extra", 0) + dados.get("comissao_dividas", 0),
                "Premiação": dados.get("bonificacao_protecao", 0) or 0,
                "Total": dados["total"],
                "Valor Recuperado Total": dados.get("valor_recuperado", 0),
                "Valor Recuperado MRR": dados.get("mrr_recuperado", 0),
                "_is_canc": dados.get("is_canc_recovery", False),
            })
    return (pd.DataFrame(rows) if rows else pd.DataFrame()), errors


def _df_display(df, equipe, show_equipe_col):
    """(df_display, tem_prem, unidade, fmt_val) — porta de pages/02:292-327."""
    tem_prem = (df["Premiação"].fillna(0) > 0).any()
    unidade = df["Unidade"].iloc[0] if not df.empty else "MRR"
    fmt_val = (lambda v: f"{int(v):,}".replace(",", ".")) if unidade == "Opps" else brl
    if equipe == "Cancelamento":
        disp = {
            "Consultor": df["Consultor"],
            "Valor Recuperado Total": df["Valor Recuperado Total"].apply(brl),
            "Valor Recuperado MRR": df["Valor Recuperado MRR"].apply(brl),
            "Comissão": df["Total"].apply(brl),
        }
    else:
        disp = {}
        if show_equipe_col:
            disp["Equipe"] = df["Equipe"]
        disp.update({
            "Consultor": df["Consultor"],
            "Cargo": df["Cargo"],
            f"Realizado ({unidade})": df.apply(
                lambda r: "-" if r["_is_canc"] else fmt_val(r["Realizado"]), axis=1),
            f"Meta ({unidade})": df.apply(
                lambda r: "-" if r["_is_canc"] else fmt_val(r["Meta"]), axis=1),
            "% Atingido": df.apply(
                lambda r: "-" if r["_is_canc"] else pct_fmt(r["% Atingido"]), axis=1),
            "OTE Variável": df.apply(
                lambda r: "-" if r["_is_canc"] else brl(r["OTE Variável"]), axis=1),
            "Comissão Extra": df.apply(
                lambda r: "-" if r["_is_canc"] else brl(r["Comissão Extra"]), axis=1),
        })
        if tem_prem:
            disp["Premiação"] = df.apply(
                lambda r: "-" if r["_is_canc"] else brl(r["Premiação"]), axis=1)
        disp["Total"] = df["Total"].apply(brl)
    return pd.DataFrame(disp), tem_prem, unidade, fmt_val


def _resolver(ano, mes, modo, lider="", user="", equipe_sel="Todas"):
    """(equipe_rotulo, membros, eq_map, show_equipe_col, erro_html)."""
    if modo == "admin":
        equipe = _equipe_do_gestor(ano, mes, lider)
        if equipe is None:
            return None, (), {}, False, aviso_azul(
                "Sem dados de meta para este gestor neste período.")
        membros = _membros_da_equipe(ano, mes, equipe)
        return equipe, membros, {}, False, None
    # gestor (RLS)
    todos = rls_service.membros_rls_gestor(user, ano, mes)
    if not todos:
        return None, (), {}, False, aviso_ambar(
            "Nenhum consultor encontrado na equipe para este período.")
    eq_map = rls_service.equipes_consultores(ano, mes, tuple(todos))
    if equipe_sel != "Todas":
        membros = tuple(sorted(c for c in todos if eq_map.get(c) == equipe_sel))
        return equipe_sel, membros, eq_map, False, None
    membros = tuple(sorted(todos, key=lambda e: (eq_map.get(e, ""), e)))
    return "todas", membros, eq_map, True, None


def equipes_do_gestor(ano, mes, user):
    """Opções do seletor de Equipe no modo gestor (pages/02:105)."""
    todos = rls_service.membros_rls_gestor(user, ano, mes)
    if not todos:
        return ["(nenhuma)"]
    eq_map = rls_service.equipes_consultores(ano, mes, tuple(todos))
    return ["Todas"] + sorted({v for v in eq_map.values() if v})


def tabela_equipe(ano, mes, modo, lider="", user="", equipe_sel="Todas"):
    """(equipe, df_display) para o export xlsx; (None, None) em erro."""
    equipe, membros, eq_map, show_eq, erro = _resolver(
        ano, mes, modo, lider, user, equipe_sel)
    if erro or not membros:
        return None, None
    df, _ = _calcular_membros(ano, mes, membros, equipe, eq_map)
    if df.empty:
        return None, None
    disp, _, _, _ = _df_display(df, equipe, show_eq)
    return equipe, disp


def montar_equipe(ano, mes, modo, lider="", user="", equipe_sel="Todas",
                  dl_url=""):
    """Lista de blocos HTML da tela (título, badge, tabela, totais, export)."""
    equipe, membros, eq_map, show_eq, erro = _resolver(
        ano, mes, modo, lider, user, equipe_sel)
    if erro:
        return [erro]

    b = []
    if equipe != "todas":
        b.append(f"<div style='color:#1a1a1a;font-weight:700;font-size:1.5rem;"
                 f"margin:0.5rem 0 0.25rem;'>{equipe}</div>")
    if not membros:
        return b + [aviso_ambar("Nenhum consultor encontrado na equipe para este período.")]

    snap = cs.get_snapshot_info(ano, mes, lider) if modo == "admin" else None
    if snap:
        try:
            data_txt = " em " + pd.to_datetime(snap["data"]).strftime("%d/%m/%Y")
        except Exception:
            data_txt = ""
        b.append(aviso_ambar(
            f"🔒 <strong>Período fechado{data_txt}.</strong> "
            f"Se houver algum negócio não contabilizado ou com valor desatualizado, "
            f"solicite o recálculo para Higor."))
    else:
        # Aquece o contexto UMA vez antes do paralelo (senão N threads
        # computariam o mesmo contexto simultaneamente no primeiro acesso).
        cs.get_contexto_cached(ano, mes)

    b.append(f"<p style='color:#1a1a1a;font-size:0.875rem;margin:0 0 0.75rem;'>"
             f"{len(membros)} consultores encontrados.</p>")

    df, errors = _calcular_membros(ano, mes, membros, equipe, eq_map)
    if errors:
        b.append(expander(f"{len(errors)} erro(s)",
                          "".join(f"<div style='font-size:0.85rem;'>{e}</div>" for e in errors)))
    if df.empty:
        return b + [aviso_azul("Nenhuma comissão pôde ser calculada.")]

    disp, tem_prem, unidade, fmt_val = _df_display(df, equipe, show_eq)
    b.append(html_table_str(disp, scrollable=True))

    b.append(divisor())
    if equipe == "Cancelamento":
        b.append(linha([
            celula(stat("Total Recuperado", brl(df["Valor Recuperado Total"].sum()))),
            celula(stat("Total Recuperado MRR", brl(df["Valor Recuperado MRR"].sum()))),
            celula(stat("Total Comissões", brl(df["Total"].sum()), highlight=True)),
        ], "cols-3"))
    else:
        df_main = df[~df["_is_canc"]]
        cards = [
            celula(stat(f"Total Realizado ({unidade})", fmt_val(df_main["Realizado"].sum()))),
            celula(stat("% Médio Atingido",
                        pct_fmt(df_main["% Atingido"].mean() if not df_main.empty else 0.0))),
            celula(stat("Total OTE Variável", brl(df["OTE Variável"].sum()))),
            celula(stat("Total Extras", brl(df["Comissão Extra"].sum()))),
        ]
        if tem_prem:
            cards.append(celula(stat("Total Premiações", brl(df["Premiação"].sum()))))
        cards.append(celula(stat("Total Comissões", brl(df["Total"].sum()), highlight=True)))
        b.append(linha(cards, "cols-6" if tem_prem else "cols-5"))
    if dl_url:
        from webapp.presentation import botao_drive
        b.append(f"<div style='margin-top:10px;'>{botao_drive(dl_url)}</div>")
    return b
