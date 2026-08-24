"""Gate das 3 grades editáveis (Parâmetros, Metas, Config) somadas depois da
Fase 5 — mesmo espírito de testar_escritas_clone.py: ciclo completo SEMPRE
nos clones MIGTESTE_* (WRITES_TARGET=clone forçado aqui), num período que
não existe em nenhuma tabela real ou clone (ANO=2031) para não colidir com
nada.

    python validacao/testar_grades_clone.py
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

from webapp.db.pool import get_pool     # noqa: E402
from webapp.services import admin_repo  # noqa: E402

USUARIO = "teste.migracao@altoqi.com.br"
EMAIL = "migteste@altoqi.com.br"
ANO, MES = 2031, 1
ANO2, MES2 = 2031, 2

falhas = []


def checar(nome, cond, detalhe=""):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {nome}" + (f" — {detalhe}" if detalhe and not cond else ""))
    if not cond:
        falhas.append(nome)


def _linha(tabela, conds, params):
    with get_pool().session() as s:
        df = s.sql(f"SELECT * FROM {tabela} WHERE {conds}", params).to_pandas()
    return df


print("== Parâmetros (grade) ==")
t_param = admin_repo.tabela_escrita(admin_repo.PARAMETROS_TABELA)
linha_param = {
    "EMAIL": EMAIL, "CARGO": "Cargo Teste", "IS_GESTOR": False, "IS_PVT": False,
    "IS_TRIM_HABILITADO": True, "CLIFF_OTE_01": 80, "CLIFF_OTE_02": 90,
    "CLIFF_ACELERADOR_01": 115, "MULT_ACELERADOR_01": 0.9,
    "CLIFF_ACELERADOR_02": 125, "MULT_ACELERADOR_02": 1.0,
    "PERCENTUAL_BOOKING_EXTRA": 5, "OTE_01_CHEIO": 1000, "OTE_02_CHEIO": 1200,
    "PERCENTUAL_PROTECAO": 10, "IS_CANC_RECOVERY": False,
    "PERCENTUAL_CANC_RECOVERY": None,
}
salvos, removidos, erros = admin_repo.parametros_salvar_grid(ANO, MES, [linha_param], USUARIO)
checar("salvar 1a vez: 1 salvo, 0 erros", salvos == 1 and not erros, str(erros))
df = _linha(t_param, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (ANO, MES, EMAIL))
checar("linha existe no clone", len(df) == 1)
if len(df):
    r = df.iloc[0]
    checar("CLIFF_OTE_01 armazenado como fração (0.80)", abs(float(r["CLIFF_OTE_01"]) - 0.80) < 1e-6,
          str(r["CLIFF_OTE_01"]))
    checar("UPDATED_BY = usuário de teste", r["UPDATED_BY"] == USUARIO, str(r["UPDATED_BY"]))
    _updated_at_1 = r["UPDATED_AT"]

salvos2, removidos2, erros2 = admin_repo.parametros_salvar_grid(ANO, MES, [linha_param], USUARIO)
checar("salvar sem mudança: 0 salvos (diff-skip preserva UPDATED_AT)", salvos2 == 0, str(salvos2))

salvos3, removidos3, erros3 = admin_repo.parametros_salvar_grid(ANO, MES, [], USUARIO)
checar("salvar lista vazia remove a linha", removidos3 == 1, str(removidos3))
df = _linha(t_param, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (ANO, MES, EMAIL))
checar("linha removida do clone", len(df) == 0)

admin_repo.parametros_salvar_grid(ANO, MES, [linha_param], USUARIO)
admin_repo.parametros_copiar_mes(ANO2, MES2, ANO, MES, USUARIO)
df2 = _linha(t_param, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (ANO2, MES2, EMAIL))
checar("copiar do mês anterior cria linha no destino", len(df2) == 1)
admin_repo.parametros_salvar_grid(ANO, MES, [], USUARIO)
admin_repo.parametros_salvar_grid(ANO2, MES2, [], USUARIO)
df, df2 = (_linha(t_param, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (a, m, EMAIL))
          for a, m in [(ANO, MES), (ANO2, MES2)])
checar("limpeza: nada sobrou nos dois períodos", len(df) == 0 and len(df2) == 0)


print("\n== Metas Consultores (grade, pré-RI) ==")
t_meta = admin_repo.tabela_escrita(admin_repo.META_CONSULTOR_TABELA)
linha_meta = {
    "EMAIL": EMAIL, "EQUIPE": "MigTeste", "SENIORIDADE": "JR",
    "PERCENTUAL_DESCONTO_METAS": 10, "META_NMRR_BRUTO": 1000, "META_EXPANSAO_BRUTO": 500,
    "META_RENOVACAO_BRUTO": 300, "META_OTR_BRUTO": 200, "META_NMRR": 900,
    "META_EXPANSAO": 450, "META_RENOVACAO": 270, "META_OTR": 180,
}
salvos, erros = admin_repo.metas_salvar_grid(ANO, MES, [linha_meta])
checar("salvar: 1 salvo, 0 erros", salvos == 1 and not erros, str(erros))
df = _linha(t_meta, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (ANO, MES, EMAIL))
checar("linha existe no clone", len(df) == 1)
if len(df):
    r = df.iloc[0]
    checar("PERCENTUAL_DESCONTO_METAS armazenado como fração (0.10)",
          abs(float(r["PERCENTUAL_DESCONTO_METAS"]) - 0.10) < 1e-6, str(r["PERCENTUAL_DESCONTO_METAS"]))

admin_repo.metas_copiar_mes(ANO2, MES2, ANO, MES)
df2 = _linha(t_meta, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (ANO2, MES2, EMAIL))
checar("copiar do mês anterior cria linha no destino", len(df2) == 1)

with get_pool().session() as s:
    s.sql(f"DELETE FROM {t_meta} WHERE ANO IN (%s,%s) AND MES IN (%s,%s) AND LOWER(EMAIL)=%s",
         (ANO, ANO2, MES, MES2, EMAIL))
df, df2 = (_linha(t_meta, "ANO=%s AND MES=%s AND LOWER(EMAIL)=%s", (a, m, EMAIL))
          for a, m in [(ANO, MES), (ANO2, MES2)])
checar("limpeza: nada sobrou nos dois períodos", len(df) == 0 and len(df2) == 0)


print("\n== Config (vigências) ==")
t_cfg = admin_repo.tabela_escrita(admin_repo.CONFIG_TABELA)
CHAVE = "migteste_chave_grade"
admin_repo.config_criar_chave(CHAVE, "10", "teste migração", ANO, MES, USUARIO)
df = _linha(t_cfg, "CHAVE=%s AND ANO=%s AND MES=%s", (CHAVE, ANO, MES))
checar("criar chave: linha existe com valor 10", len(df) == 1 and df.iloc[0]["VALOR"] == "10")

admin_repo.config_nova_vigencia({CHAVE: "20"}, ANO2, MES2, USUARIO)
df1 = _linha(t_cfg, "CHAVE=%s AND ANO=%s AND MES=%s", (CHAVE, ANO, MES))
df2 = _linha(t_cfg, "CHAVE=%s AND ANO=%s AND MES=%s", (CHAVE, ANO2, MES2))
checar("nova vigência: período antigo intocado (ainda 10)",
      len(df1) == 1 and df1.iloc[0]["VALOR"] == "10", str(df1.iloc[0]["VALOR"]) if len(df1) else "sumiu")
checar("nova vigência: novo período criado com 20",
      len(df2) == 1 and df2.iloc[0]["VALOR"] == "20", str(df2.iloc[0]["VALOR"]) if len(df2) else "não criado")

admin_repo.config_salvar_atual({CHAVE: ("30", ANO2, MES2)}, USUARIO)
df1 = _linha(t_cfg, "CHAVE=%s AND ANO=%s AND MES=%s", (CHAVE, ANO, MES))
df2 = _linha(t_cfg, "CHAVE=%s AND ANO=%s AND MES=%s", (CHAVE, ANO2, MES2))
checar("salvar na vigência atual: só o período apontado muda (30)",
      len(df2) == 1 and df2.iloc[0]["VALOR"] == "30", str(df2.iloc[0]["VALOR"]) if len(df2) else "sumiu")
checar("salvar na vigência atual: período mais antigo intocado (ainda 10)",
      len(df1) == 1 and df1.iloc[0]["VALOR"] == "10")

with get_pool().session() as s:
    s.sql(f"DELETE FROM {t_cfg} WHERE CHAVE=%s AND ANO IN (%s,%s) AND MES IN (%s,%s)",
         (CHAVE, ANO, ANO2, MES, MES2))
df = _linha(t_cfg, "CHAVE=%s", (CHAVE,))
checar("limpeza: chave de teste removida por completo", len(df) == 0)


print(f"\n{'TUDO OK' if not falhas else f'{len(falhas)} FALHA(S): ' + ', '.join(falhas)}")
sys.exit(1 if falhas else 0)
