"""Cria usuários de DEMONSTRAÇÃO para apresentação (Q2/2026), copiando o
resultado real de consultores-fonte de forma anônima, via snapshot de fechamento.

- 1 demo por equipe (Saving/FSB/GD/Governo): consultor de total mediano em junho.
- Equipe 'Demo Escritório' completa: cópia de todos do B2B Escritório + líder.
- Composições anonimizadas: clientes viram 'Cliente Demo NN', negócios/contatos
  viram IDs fictícios (99…/88…), consultores viram e-mails demo.
- Tudo rastreável (demo.%, equipe 'Demo %', fechamento 2026-MM-Demo-v1) e
  removível com validacao/demo_apagar.py. Idempotente: reexecutar recria.

Rodar com o venv de validação:
  venv\\Scripts\\python.exe validacao\\demo_criar.py
"""
import io
import os
import sys
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AQUI = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)

import pandas as pd
import harness

ANO = 2026
MESES = [4, 5, 6]

session = harness.setup(PROJECT)
import utils.commission as C

conn = session._conn
cur = conn.cursor()

# ── 0. Limpeza prévia (idempotência) ─────────────────────────────────────────
for sql in [
    "DELETE FROM SUPERSET.COMISSOES.COMPOSICAO_FECHADA WHERE LOWER(EMAIL) LIKE 'demo.%'",
    "DELETE FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS WHERE LOWER(EMAIL) LIKE 'demo.%'",
    "DELETE FROM SUPERSET.COMISSOES.FECHAMENTOS WHERE EQUIPE = 'Demo'",
    "DELETE FROM SUPERSET.COMISSOES.PARAMETROS WHERE LOWER(EMAIL) LIKE 'demo.%'",
    "DELETE FROM SUPERSET.PARCIAL.META_CONSULTOR WHERE LOWER(EMAIL) LIKE 'demo.%'",
    "DELETE FROM SUPERSET.PARCIAL.PERMISSAO_RLS WHERE LOWER(USUARIOEMAIL) LIKE 'demo.%' OR LOWER(CONSULTOREMAIL) LIKE 'demo.%'",
]:
    cur.execute(sql)

# ── 1. Fontes ─────────────────────────────────────────────────────────────────
def membros(equipe, gestor):
    cur.execute(f"""
        SELECT LOWER(m.CONSULTOR)
        FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS m
        JOIN SUPERSET.COMISSOES.PARAMETROS p
          ON p.ANO = m.ANO AND p.MES = m.MES AND LOWER(p.EMAIL) = LOWER(m.CONSULTOR)
        WHERE m.ANO = {ANO} AND m.MES = 6 AND m.EQUIPE = '{equipe}'
          AND p.IS_GESTOR = {'TRUE' if gestor else 'FALSE'}
        ORDER BY 1
    """)
    return [r[0] for r in cur.fetchall()]


def mediano(equipe):
    """Consultor (não-gestor) com total mediano em junho."""
    totais = []
    for e in membros(equipe, gestor=False):
        d = harness.calc_live(e, ANO, 6)
        if isinstance(d, dict) and "erro" not in d and (d.get("total") or 0) > 0:
            totais.append((float(d["total"]), e))
    totais.sort()
    return totais[len(totais) // 2][1]


mapa = {}  # fonte -> (demo_email, equipe_demo)
for equipe, demo in [("Saving", "demo.saving@altoqi.com.br"),
                     ("FSB", "demo.fsb@altoqi.com.br"),
                     ("GD", "demo.gd@altoqi.com.br"),
                     ("Governo", "demo.governo@altoqi.com.br")]:
    fonte = mediano(equipe)
    mapa[fonte] = (demo, f"Demo {equipe}")
    print(f"{equipe:10s}: {fonte}  ->  {demo}")

# Equipe demo completa (fonte: B2B Escritório) — nome neutro, sem citar a fonte
esc_membros = membros("B2B Escritório", gestor=False)
esc_gestor = membros("B2B Escritório", gestor=True)[0]
email_map = {esc_gestor: "demo.gestor.captacao@altoqi.com.br"}
for i, e in enumerate(esc_membros, start=1):
    email_map[e] = f"demo.captacao{i:02d}@altoqi.com.br"
for fonte, demo in email_map.items():
    mapa[fonte] = (demo, "Demo Captação")
    print(f"{'Captação':10s}: {fonte}  ->  {demo}")

# ── 2. Helpers ────────────────────────────────────────────────────────────────
_neg_map, _cli_map, _ct_map = {}, {}, {}


def _anon_neg(v):
    if v is None or str(v).strip() in ("", "None"):
        return v
    k = str(v)
    if k not in _neg_map:
        _neg_map[k] = str(99000000 + len(_neg_map) + 1)
    return _neg_map[k]


def _anon_cli(v):
    k = "" if v is None else str(v)
    if k not in _cli_map:
        _cli_map[k] = f"Cliente Demo {len(_cli_map) + 1:02d}"
    return _cli_map[k]


def _anon_ct(v):
    if v is None or str(v).strip() in ("", "None"):
        return v
    k = str(v)
    if k not in _ct_map:
        _ct_map[k] = str(88000000 + len(_ct_map) + 1)
    return _ct_map[k]


def _anon_comp(df, demo_email):
    if df is None or df.empty:
        return df
    d = df.copy()
    if "NEGOCIO" in d.columns:
        d["NEGOCIO"] = d["NEGOCIO"].map(_anon_neg)
    if "CLIENTE" in d.columns:
        d["CLIENTE"] = d["CLIENTE"].map(_anon_cli)
    if "CONTATO" in d.columns:
        d["CONTATO"] = d["CONTATO"].map(_anon_ct)
    if "CONSULTOR" in d.columns:
        d["CONSULTOR"] = d["CONSULTOR"].map(
            lambda e: email_map.get(str(e), demo_email))
    return d


def _row_json(r):
    d = {}
    for k, v in r.items():
        try:
            if pd.isna(v):
                v = None
        except (TypeError, ValueError):
            pass
        d[str(k)] = v
    return json.dumps(d, default=str, ensure_ascii=False)


def _copiar_linha(tabela, where_sql, overrides):
    """SELECT * da linha-fonte e INSERT com colunas sobrescritas (binds)."""
    cur.execute(f"SELECT * FROM {tabela} WHERE {where_sql}")
    row = cur.fetchone()
    if row is None:
        return False
    cols = [d[0] for d in cur.description]
    vals = list(row)
    for c, v in overrides.items():
        if c in cols:
            vals[cols.index(c)] = v
    cur.execute(
        f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        vals,
    )
    return True


# ── 3. Criação por mês ────────────────────────────────────────────────────────
for mes in MESES:
    fid = f"{ANO}-{mes:02d}-Demo-v1"
    n_pessoas = 0

    for fonte, (demo, eq_demo) in mapa.items():
        f_sql = fonte.replace("'", "''")

        # Metas e parâmetros (para o demo aparecer nos filtros e listagens).
        # METAS_CONSULTORES_CONSOLIDADAS é view — a base editável é META_CONSULTOR.
        tem_meta = _copiar_linha(
            "SUPERSET.PARCIAL.META_CONSULTOR",
            f"ANO = {ANO} AND MES = {mes} AND LOWER(EMAIL) = '{f_sql}'",
            {"EMAIL": demo, "EQUIPE": eq_demo},
        )
        tem_param = _copiar_linha(
            "SUPERSET.COMISSOES.PARAMETROS",
            f"ANO = {ANO} AND MES = {mes} AND LOWER(EMAIL) = '{f_sql}'",
            {"EMAIL": demo, "UPDATED_BY": "demo_criar.py"},
        )
        if not (tem_meta and tem_param):
            print(f"  ! {mes:02d} {fonte}: sem meta/parâmetro — pulado")
            continue

        # Resultado (dict completo) calculado ao vivo do consultor-fonte
        dados = harness.calc_live(fonte, ANO, mes)
        if not isinstance(dados, dict) or "erro" in dados:
            print(f"  ! {mes:02d} {fonte}: cálculo com erro — pulado")
            continue
        equipe_real = dados.get("equipe", "")
        dados = dict(dados)
        dados["equipe"] = eq_demo

        cur.execute(
            """INSERT INTO SUPERSET.COMISSOES.COMISSOES_FECHADAS
               (FECHAMENTO_ID, ANO, MES, EQUIPE, EMAIL, CARGO, TOTAL, DADOS, DATA_FECHAMENTO)
               SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), CURRENT_TIMESTAMP()""",
            (fid, ANO, mes, eq_demo, demo, dados.get("cargo"),
             float(dados.get("total") or 0),
             json.dumps(dados, default=str, ensure_ascii=False)),
        )
        n_pessoas += 1

        # Composições anonimizadas
        comps = []
        comp = C.composicao_realizado(session, fonte, ANO, mes, equipe_real,
                                      bool(dados.get("is_gestor")),
                                      bool(dados.get("is_gd")),
                                      bool(dados.get("is_b2g")))
        comps.append(("GD" if dados.get("is_gd") else "REALIZADO",
                      _anon_comp(comp, demo)))
        bk = C.composicao_booking_extra(session, fonte, ANO, mes, equipe_real,
                                        bool(dados.get("is_gestor")))
        comps.append(("BOOKING_EXTRA", _anon_comp(bk, demo)))
        if int(dados.get("ajuste_n") or 0) > 0:
            comps.append(("AJUSTE", pd.DataFrame([{
                "Valor": float(dados.get("ajuste_total") or 0),
                "Descrição": "Ajuste (demonstração)",
                "Ref. Mês": "—",
            }])))

        linhas = []
        for tipo, dfc in comps:
            if dfc is None or dfc.empty:
                continue
            for i, (_, r) in enumerate(dfc.iterrows()):
                linhas.append((fid, ANO, mes, eq_demo, demo, tipo, i,
                               _row_json(r.to_dict())))
        for lin in linhas:
            cur.execute(
                """INSERT INTO SUPERSET.COMISSOES.COMPOSICAO_FECHADA
                   (FECHAMENTO_ID, ANO, MES, EQUIPE, EMAIL, TIPO, ORDEM, LINHA)
                   SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s)""",
                lin,
            )

    # Cabeçalho do fechamento demo do mês
    cur.execute(
        """INSERT INTO SUPERSET.COMISSOES.FECHAMENTOS
           (FECHAMENTO_ID, ANO, MES, EQUIPE, VERSAO, STATUS, DATA_FECHAMENTO,
            USUARIO, N_PESSOAS, OBS)
           VALUES (%s, %s, %s, 'Demo', 1, 'ATIVO', CURRENT_TIMESTAMP(),
                   'demo_criar.py', %s,
                   'DADOS DE DEMONSTRACAO - apagar com validacao/demo_apagar.py')""",
        (fid, ANO, mes, n_pessoas),
    )

    # RLS do gestor demo (aba Minha Equipe via "Visualizar como")
    g_sql = esc_gestor.replace("'", "''")
    demo_gestor = email_map[esc_gestor]
    for alvo in [demo_gestor] + [email_map[e] for e in esc_membros]:
        _copiar_linha(
            "SUPERSET.PARCIAL.PERMISSAO_RLS",
            f"ANO = {ANO} AND MES = {mes} AND LOWER(USUARIOEMAIL) = '{g_sql}' "
            f"AND CONSULTOREMAIL IS NOT NULL LIMIT 1",
            {"USUARIOEMAIL": demo_gestor, "CONSULTOREMAIL": alvo,
             "TIPOUSUARIO": "Gestor"},
        )

    print(f"{mes:02d}/{ANO}: fechamento {fid} com {n_pessoas} pessoas")

# ── 4. Verificação ────────────────────────────────────────────────────────────
print("\nVerificação (snapshot lido como o painel lê):")
harness.reset()
for fonte, (demo, eq_demo) in mapa.items():
    d = harness._stub_get_comissao(demo, ANO, 6)
    ok = isinstance(d, dict) and "erro" not in d
    print(f"  {'✓' if ok else '✗'} {demo:44s} total jun = "
          f"{d.get('total') if ok else d}")
conn.commit()
cn_total = cur.execute(
    "SELECT COUNT(*) FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS WHERE LOWER(EMAIL) LIKE 'demo.%'"
).fetchone()[0]
print(f"\n{cn_total} snapshots demo criados. Para remover: validacao/demo_apagar.py")
