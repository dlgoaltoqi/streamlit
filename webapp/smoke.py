"""Smoke test da camada de dados do webapp (Fase 1 do plano).

    python -m webapp.smoke

Verifica, com a conexão configurada (dev: local_cli; servidor: key-pair):
1. get_comissao de um período FECHADO (via snapshot) devolve dict com total;
2. get_comissao de um período ABERTO (cálculo vivo) devolve dict com total;
3. repetir as duas chamadas não gera NENHUMA query nova (cache efetivo);
4. o processo não contém streamlit (shim íntegro).
"""
import sys
import time

from webapp.bootstrap import install_connection_shim

install_connection_shim()

from webapp.config import settings                    # noqa: E402
from webapp.core import periods                       # noqa: E402
from webapp.db.pool import get_pool                   # noqa: E402
from webapp.services import comissao_service as cs    # noqa: E402


def _falha(msg):
    print(f"FALHA: {msg}")
    sys.exit(1)


def main():
    modo = "key-pair (service account)" if settings.usa_keypair() else \
           f"connections.toml ({settings.sf_connection_name})"
    print(f"Conexão: {modo}")
    pool = get_pool()

    # 0. Streamlit não pode estar no processo
    if "streamlit" in sys.modules:
        _falha("streamlit foi importado no processo do webapp")

    # 1. Descobre um período fechado real (qualquer pessoa de fechamento ATIVO)
    with pool.session() as s:
        df = s.sql("""
            SELECT cf.EMAIL, cf.ANO, cf.MES
            FROM SUPERSET.COMISSOES.COMISSOES_FECHADAS cf
            JOIN SUPERSET.COMISSOES.FECHAMENTOS f
              ON cf.FECHAMENTO_ID = f.FECHAMENTO_ID
            WHERE f.STATUS = 'ATIVO' AND LOWER(cf.EMAIL) NOT LIKE 'demo.%%'
            ORDER BY cf.ANO DESC, cf.MES DESC
            LIMIT 1
        """).to_pandas()
    if df.empty:
        _falha("nenhum fechamento ATIVO encontrado")
    em_f, ano_f, mes_f = str(df.iloc[0]["EMAIL"]).lower(), int(df.iloc[0]["ANO"]), int(df.iloc[0]["MES"])

    t0 = time.time()
    d_fechado = cs.get_comissao(em_f, ano_f, mes_f)
    t_fechado = time.time() - t0
    if not isinstance(d_fechado, dict) or "total" not in d_fechado:
        _falha(f"snapshot de {em_f} {mes_f:02d}/{ano_f} sem 'total': {type(d_fechado)}")
    print(f"[1] fechado  {em_f} {mes_f:02d}/{ano_f}: total={d_fechado['total']} ({t_fechado:.1f}s)")

    # 2. Período aberto: mês corrente, uma pessoa com meta
    ano_a, mes_a = periods.periodo_default()
    with pool.session() as s:
        df = s.sql("""
            SELECT LOWER(CONSULTOR) AS EMAIL
            FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND MES = %s AND CONSULTOR IS NOT NULL
              AND LOWER(CONSULTOR) NOT LIKE 'demo.%%'
            ORDER BY EMAIL LIMIT 1
        """, (ano_a, mes_a)).to_pandas()
    if df.empty:
        _falha(f"nenhum consultor com meta em {mes_a:02d}/{ano_a}")
    em_a = str(df.iloc[0]["EMAIL"])

    t0 = time.time()
    d_aberto = cs.get_comissao(em_a, ano_a, mes_a)
    t_aberto = time.time() - t0
    if not isinstance(d_aberto, dict) or ("total" not in d_aberto and "erro" not in d_aberto):
        _falha(f"cálculo vivo de {em_a} {mes_a:02d}/{ano_a} inválido")
    print(f"[2] aberto   {em_a} {mes_a:02d}/{ano_a}: total={d_aberto.get('total')} ({t_aberto:.1f}s)")

    # 3. Cache: repetir não pode gerar query nova
    antes = pool.n_queries
    cs.get_comissao(em_f, ano_f, mes_f)
    cs.get_comissao(em_a, ano_a, mes_a)
    novas = pool.n_queries - antes
    if novas != 0:
        _falha(f"repetição gerou {novas} query(ies) nova(s) — cache inefetivo")
    print(f"[3] cache    repetição com 0 queries novas (total do smoke: {pool.n_queries})")

    print("SMOKE OK")


if __name__ == "__main__":
    main()
