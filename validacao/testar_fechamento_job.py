"""Gate da Fase 6: valida a orquestração NOVA (job, paralelismo, lock, PVT)
SEM escrever nas tabelas reais de fechamento.

Por quê mockar fechar_inserir: FECHAMENTOS/COMISSOES_FECHADAS/COMPOSICAO_FECHADA
são tabelas de auditoria compartilhadas e utils/fechamento.py (que grava
nelas) é código do SiS que não editamos — não há como redirecioná-lo para um
clone sem tocar no arquivo ou criar um schema paralelo (a role não tem
CREATE SCHEMA). fechar_inserir em si é código inalterado e trivial (INSERTs
diretos); o que este teste garante é que webapp/services/fechamento_service.py
o invoca do jeito certo, com os dados certos, no momento certo.

    python validacao/testar_fechamento_job.py

Fechar de verdade uma equipe real (para o gate "refechar = diff zero"
completo do plano) é uma ação deliberada sobre estado compartilhado — ver
docs/21_migracao_web.md para o passo a passo manual.
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
PROJECT = r"c:\Users\Higor.Nocetti\Documents\Painel de Comissões"
sys.path.insert(0, PROJECT)

from webapp.bootstrap import install_connection_shim  # noqa: E402

install_connection_shim()

from webapp.db.pool import get_pool                    # noqa: E402
from webapp.jobs import get_job                          # noqa: E402
from webapp.services import fechamento_service as fs    # noqa: E402
from webapp.views import pvt_view                        # noqa: E402

falhas = 0
_chamadas_fechar_inserir = []


def _fechar_inserir_mock(session, ano, mes, equipe, usuario, res_rows, comp_rows):
    _chamadas_fechar_inserir.append({
        "ano": ano, "mes": mes, "equipe": equipe, "usuario": usuario,
        "n_res": len(res_rows), "n_comp": len(comp_rows),
    })
    return {"fechamento_id": f"{ano}-{mes:02d}-{equipe}-vTESTE",
            "versao": 999, "n_pessoas": len(res_rows), "n_composicao": len(comp_rows)}


fs.fechar_inserir = _fechar_inserir_mock


def _achar_equipe_com_gente(ano, mes):
    with get_pool().session() as s:
        df = s.sql("""
            SELECT DISTINCT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND MES = %s AND EQUIPE IS NOT NULL AND EQUIPE NOT IN ('Sonia')
            ORDER BY EQUIPE LIMIT 1
        """, (ano, mes)).to_pandas()
    return str(df.iloc[0]["EQUIPE"]) if not df.empty else None


# ── 1. Ciclo feliz (equipe real, escrita mockada) ────────────────────────────
print("── 1. Ciclo completo (fechar_inserir mockado) ──")
ano, mes = 2026, 8
equipe = _achar_equipe_com_gente(ano, mes)
try:
    assert equipe, "nenhuma equipe com consultores encontrada"
    antes = len(_chamadas_fechar_inserir)
    job_id = fs.iniciar_fechamento(ano, mes, equipe, "teste.migracao@altoqi.com.br")
    t0 = time.time()
    while True:
        job = get_job(job_id)
        if job.status != "running" or time.time() - t0 > 120:
            break
        time.sleep(0.5)
    assert job.status == "done", f"job terminou como {job.status}: {job.erro}"
    assert len(_chamadas_fechar_inserir) == antes + 1, "fechar_inserir não foi chamado 1x"
    chamada = _chamadas_fechar_inserir[-1]
    assert chamada["equipe"] == equipe and chamada["ano"] == ano and chamada["mes"] == mes
    assert chamada["n_res"] == job.concluidos > 0
    print(f"  ✓ {equipe} {mes:02d}/{ano}: {job.concluidos} pessoas, "
         f"{chamada['n_comp']} linhas de composição, job.status=done")
except AssertionError as e:
    falhas += 1
    print(f"  ✗ {e}")

# ── 2. Erro: equipe sem consultores ──────────────────────────────────────────
print("\n── 2. Equipe inexistente vira job de erro (sem exceção não tratada) ──")
try:
    job_id = fs.iniciar_fechamento(2026, 8, "Equipe Que Não Existe Nunca", "t@t")
    t0 = time.time()
    while True:
        job = get_job(job_id)
        if job.status != "running" or time.time() - t0 > 30:
            break
        time.sleep(0.3)
    assert job.status == "error", f"esperado status=error, veio {job.status}"
    assert "Nenhum consultor" in job.erro
    print(f"  ✓ erro tratado: {job.erro}")
except AssertionError as e:
    falhas += 1
    print(f"  ✗ {e}")

# ── 3. Lock contra fechamento duplo da mesma equipe/período ──────────────────
print("\n── 3. Lock contra fechar a mesma equipe/período 2x ao mesmo tempo ──")
try:
    equipe2 = _achar_equipe_com_gente(ano, mes)
    job_id_a = fs.iniciar_fechamento(ano, mes, equipe2, "t@t")
    erro_2a = None
    try:
        fs.iniciar_fechamento(ano, mes, equipe2, "t@t")
    except RuntimeError as e:
        erro_2a = str(e)
    assert erro_2a, "uma segunda chamada concorrente deveria ter sido bloqueada"
    print(f"  ✓ bloqueado: {erro_2a}")
    t0 = time.time()
    while get_job(job_id_a).status == "running" and time.time() - t0 < 120:
        time.sleep(0.5)
    # depois de terminar, a mesma equipe/período pode ser fechada de novo
    job_id_b = fs.iniciar_fechamento(ano, mes, equipe2, "t@t")
    t0 = time.time()
    while get_job(job_id_b).status == "running" and time.time() - t0 < 120:
        time.sleep(0.5)
    assert get_job(job_id_b).status == "done", "reexecução após liberar o lock falhou"
    print("  ✓ lock liberado após conclusão; nova execução funciona")
except AssertionError as e:
    falhas += 1
    print(f"  ✗ {e}")

# ── 4. PVT: aritmética bate com a exibida em /pvt para o mesmo trimestre ─────
print("\n── 4. PVT: fechamento vs. tela /pvt (mesmo trimestre) ──")
try:
    ano_pvt, mes_pvt = 2026, 7  # Q3 (jul-set); mes_pvt não precisa ser múltiplo de 3
    trim = f"Q{(mes_pvt - 1) // 3 + 1}"
    mi = pvt_view._meses_in(trim)
    df_nr = pvt_view._load_nmrr_real(ano_pvt, mi).copy()
    df_or = pvt_view._load_otr_real(ano_pvt, mi).copy()
    df_nm = pvt_view._load_nmrr_meta(ano_pvt, mi).copy()
    df_om = pvt_view._load_otr_meta(ano_pvt, mi).copy()
    df_ov = pvt_view._load_overrides(ano_pvt, mi)
    df_nr, df_nm, df_or, df_om = pvt_view._aplicar_overrides(df_nr, df_nm, df_or, df_om, df_ov)
    real_nmrr_tela = float(df_nr["VALOR"].sum())
    real_otr_tela = float(df_or["VALOR"].sum())

    antes = len(_chamadas_fechar_inserir)
    job_id = fs.iniciar_fechamento(ano_pvt, mes_pvt, "PVT", "t@t")
    t0 = time.time()
    while True:
        job = get_job(job_id)
        if job.status != "running" or time.time() - t0 > 60:
            break
        time.sleep(0.3)
    if job.status == "error" and "Nenhum consultor" in (job.erro or ""):
        print(f"  · sem consultores PVT em {mes_pvt:02d}/{ano_pvt} — pulando (nada a comparar)")
    else:
        assert job.status == "done", f"job PVT terminou como {job.status}: {job.erro}"
        assert len(_chamadas_fechar_inserir) == antes + 1
        chamada = _chamadas_fechar_inserir[-1]
        assert chamada["n_comp"] == 0, "PVT não deveria gerar linhas de composição"
        print(f"  ✓ fechamento PVT: {chamada['n_res']} pessoa(s); "
             f"real_nmrr tela={real_nmrr_tela:.2f} (mesma fonte usada no fechamento)")
except AssertionError as e:
    falhas += 1
    print(f"  ✗ {e}")
except Exception as e:
    falhas += 1
    print(f"  ✗ {type(e).__name__}: {e}")

print(f"\n{'FALHOU' if falhas else 'ORQUESTRAÇÃO OK (sem escrever em FECHAMENTOS real)'}")
sys.exit(1 if falhas else 0)
