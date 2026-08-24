"""Re-semeia a CONFIG com binds (corrige mojibake do snow sql -f)."""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import snowflake.connector as sc

SEEDS = [
    ("fator_trim_consultor", "0.3",
     "Fator do bônus trimestral individual dos consultores (× % atingido, se ≥ 100%)"),
    ("fator_trim_gestor", "0.6",
     "Fator do bônus trimestral individual dos gestores (exceto B2G)"),
    ("fator_trim_gestor_b2g", "0.9",
     "Fator do bônus trimestral do gestor B2G/Governo"),
    ("fator_trim_equipe", "0.3",
     "Fator do bônus trimestral de equipe dos consultores (equipe ≥ 100% e individual ≥ cliff)"),
    ("meta_atingida_gestor_b2g", "0.8",
     "Meta de % da equipe B2G atingindo a quota (eixo Meta Atingida do gestor)"),
    ("meta_arr_pct_booking", "0.5",
     "Meta ARR do B2G = este percentual × meta Booking"),
    ("corte_deal_grande", "400000",
     "Booking a partir do qual o negócio é excluído por padrão (tela Deals ≥ 400k decide os pagos)"),
    ("pct_canc_recovery_default", "0.02",
     "% padrão da comissão de recuperação de cancelamentos (quando vazio nos Parâmetros)"),
    ("pct_dividas_default", "0.025",
     "% padrão da comissão sobre dívidas recuperadas (quando vazio no cadastro)"),
    ("categorias_booking_extra", "Implantação,Serviço,Curso",
     "Categorias de item que contam como Booking Extra (itens com MRR = 0)"),
    ("cargo_sdr_contem", "sales development",
     "Trecho do cargo que identifica SDR (segue o modelo GD/Opps)"),
    ("gestor_equipes.sonia.zielinski@altoqi.com.br", "FSB,Farmer,Ares",
     "Equipes agregadas por esta gestora (gestor multi-equipe)"),
    ("gestor_b2g_rotulo_aproveitamento", "marcelo.maestro@altoqi.com.br",
     "E-mails (separados por vírgula) de gestores B2G cujo eixo Meta Atingida aparece como Aproveitamento da Equipe"),
    ("equipes_fechamento.Farmer", "Farmer,Sonia",
     "Equipes do METAS varridas ao fechar/exportar a equipe Farmer"),
]

cn = sc.connect(connection_name="local_cli")
cur = cn.cursor()
cur.execute(
    "DELETE FROM SUPERSET.COMISSOES.CONFIG WHERE ANO = 2026 AND MES = 4 AND CHAVE IN (%s)"
    % ",".join("'" + c.replace("'", "''") + "'" for c, _, _ in SEEDS)
)
print("removidas:", cur.rowcount)
cur.executemany(
    """INSERT INTO SUPERSET.COMISSOES.CONFIG
       (CHAVE, ANO, MES, VALOR, DESCRICAO, UPDATED_BY, UPDATED_AT)
       VALUES (%s, 2026, 4, %s, %s, CURRENT_USER(), CURRENT_TIMESTAMP())""",
    [(c, v, d) for c, v, d in SEEDS],
)
print("inseridas:", len(SEEDS))
cur.execute("SELECT VALOR FROM SUPERSET.COMISSOES.CONFIG WHERE CHAVE = 'categorias_booking_extra'")
print("conferindo:", repr(cur.fetchone()[0]))
cn.close()
