"""Gate da Fase 5: ciclo add → verificar (com auditoria) → copiar mês →
remover → verificar, para as 10 páginas admin editáveis, SEMPRE nos clones
MIGTESTE_* (WRITES_TARGET=clone é forçado aqui; nada toca as tabelas reais).

    python validacao/testar_escritas_clone.py
"""
import io
import os
import sys

os.environ["WRITES_TARGET"] = "clone"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, PROJECT)

from webapp.bootstrap import install_connection_shim  # noqa: E402

install_connection_shim()

from webapp.db.pool import get_pool                   # noqa: E402
from webapp.services import admin_repo                # noqa: E402
from webapp.views import admin_view                   # noqa: E402

USUARIO = "teste.migracao@altoqi.com.br"
ANO, MES = 2031, 1          # período que não existe em nenhum clone
ANO2, MES2 = 2031, 2        # destino do copiar-mês

# Valores de teste por página (chaves digitáveis + campos)
VALORES = {
    "cargos-otes": {"CARGO": "Cargo Migteste", "OTE": 1234.56},
    "multiplicadores": {"EQUIPE": "MigTeste", "A_VISTA": 1.1, "CC_ATE_3X": 1.0,
                        "CC_ATE_12X": 0.9, "RECORRENTE": 0.8},
    "patamares": {"EQUIPE": "MigTeste", "PATAMAR": 0.6, "PERCENTUAL": 0.5},
    "recuperacao-dividas": {"EMAIL": "migteste@altoqi.com.br", "VALOR": 1000.0,
                            "PERCENTUAL_COMISSAO": 0.02},
    "deals-400k": {"ID_NEGOCIO": "999999999999", "OBSERVACAO": "teste migração"},
    "realizado-gd": {"EMAIL": "migteste@altoqi.com.br",
                     "REALIZADO_MANUAL": 42, "MOTIVO": "teste migração"},
    "ponderacoes-meta": {"EMAIL": "migteste@altoqi.com.br", "TIPO_META": "BOOKING",
                         "PONDERACAO": 0.35},
    "acesso-rls": {"USUARIOEMAIL": "migteste@altoqi.com.br",
                   "CONSULTOREMAIL": "migteste2@altoqi.com.br",
                   "TIPOUSUARIO": "Gestor"},
    "ajustes-pontuais": {"EMAIL": "migteste@altoqi.com.br", "VALOR": -12.34,
                         "DESCRICAO": "teste migração", "REF_ANO": 2031, "REF_MES": 1},
    "exclusoes-carteira-am": {"ID_CONTRATO": "99999999999",
                              "SOLICITADO_POR": "MigTeste", "MOTIVO": "teste migração"},
}

AUDIT_COL = {"updated": "UPDATED_BY", "created": "CREATED_BY", "deals": "USUARIO"}


def contar(t, conds, params):
    with get_pool().session() as s:
        df = s.sql(f"SELECT COUNT(*) AS N, MAX({audit_col}) AS AUTOR FROM {t} "
                   f"WHERE {conds}", params).to_pandas()
    return int(df.iloc[0]["N"]), df.iloc[0]["AUTOR"]


falhas = 0
for page in admin_view.ADMIN_PAGES:
    if not page.editavel:
        continue
    slug = page.slug
    vals = dict(VALORES[slug])
    if page.mensal:
        vals["ANO"], vals["MES"] = ANO, MES
    t = admin_repo.tabela_escrita(page.tabela)
    assert "MIGTESTE_" in t, f"{slug}: escrita NÃO redirecionada ({t})"
    audit_col = AUDIT_COL[page.audit]

    # condição de verificação pelas chaves
    conds, params = [], []
    for col, tr in page.chaves:
        conds.append(f"{tr}({col}) = {tr}(%s)" if tr else f"{col} = %s")
        params.append(vals[col])
    cond_sql, params = " AND ".join(conds), tuple(params)

    try:
        # 1. upsert (insert)
        admin_repo.upsert(page, vals, USUARIO)
        n, autor = contar(t, cond_sql, params)
        assert n == 1, f"{slug}: esperado 1 registro após insert, achei {n}"
        assert str(autor).lower() == USUARIO, f"{slug}: auditoria {autor!r} != {USUARIO!r}"

        # 2. upsert de novo (update; modo insert duplica de propósito — pula)
        if page.modo == "merge":
            admin_repo.upsert(page, vals, USUARIO)
            n, _ = contar(t, cond_sql, params)
            assert n == 1, f"{slug}: MERGE duplicou ({n} registros)"

        # 3. copiar mês (quando a página tem)
        if page.copia_mes:
            admin_repo.copiar_mes(page, ANO, MES, ANO2, MES2, USUARIO)
            n2, _ = contar(t, cond_sql.replace("MES = %s", "MES = %s"),
                           tuple(v if c != "MES" else MES2
                                 for (c, _t), v in zip(page.chaves, params)))
            assert n2 == 1, f"{slug}: copiar-mês não criou o registro destino"

        # 4. remover (origem e cópia)
        rem = admin_view.chave_remocao(page)
        if rem == ((("ID", ""),) if False else rem) and rem[0][0] == "ID":
            with get_pool().session() as s:
                df = s.sql(f"SELECT MAX(ID) AS ID FROM {t} WHERE {cond_sql}",
                           params).to_pandas()
            admin_repo.excluir(page, {"ID": int(df.iloc[0]["ID"])})
        else:
            admin_repo.excluir(page, vals)
            if page.copia_mes:
                vals2 = dict(vals); vals2["MES"] = MES2
                admin_repo.excluir(page, vals2)
        n, _ = contar(t, cond_sql, params)
        assert n == 0, f"{slug}: registro ainda existe após delete ({n})"

        print(f"  ✓ {slug}")
    except AssertionError as e:
        falhas += 1
        print(f"  ✗ {e}")
    except Exception as e:
        falhas += 1
        print(f"  ✗ {slug}: {type(e).__name__}: {e}")

print("\n" + ("FALHOU" if falhas else "CICLO COMPLETO OK NOS CLONES"))
sys.exit(1 if falhas else 0)
