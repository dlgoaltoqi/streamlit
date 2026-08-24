"""Tela de Exportar/Fechar Comissões — porta do fluxo de fechamento de
pages/20_Admin_Exportar_Comissoes.py:36-49,1096-1280 (a exportação já está
coberta por /export/drive/admin/exportar-comissoes via admin_view; esta view
cobre só fechar/reabrir, que é o que falta da página 20)."""
from webapp.core.cache import RLS, ttl_cached
from webapp.db.pool import get_pool
from webapp.presentation import brl
from webapp.services import fechamento_service as fs


@ttl_cached(RLS)
def equipes_periodo(ano: int, mes: int) -> tuple:
    """Porta de pages/20:36-59 (inclui Cancelamento e PVT quando aplicável)."""
    with get_pool().session() as s:
        df = s.sql("""
            SELECT DISTINCT EQUIPE FROM SUPERSET.PARCIAL.METAS_CONSULTORES_CONSOLIDADAS
            WHERE ANO = %s AND MES = %s AND EQUIPE IS NOT NULL AND EQUIPE NOT IN ('Sonia')
            ORDER BY EQUIPE
        """, (ano, mes)).to_pandas()
        equipes = [str(e) for e in df["EQUIPE"]]
        cr = s.sql("""
            SELECT COUNT(*) AS N FROM SUPERSET.COMISSOES.PARAMETROS
            WHERE ANO = %s AND MES = %s AND IS_CANC_RECOVERY = TRUE
        """, (ano, mes)).to_pandas()
        if int(cr.iloc[0]["N"]) > 0:
            equipes.append("Cancelamento")
        if mes in (3, 6, 9, 12):
            pvt = s.sql("""
                SELECT COUNT(*) AS N FROM SUPERSET.COMISSOES.PARAMETROS
                WHERE ANO = %s AND MES = %s AND IS_PVT = TRUE
                  AND COALESCE(IS_GESTOR, FALSE) = FALSE
            """, (ano, mes)).to_pandas()
            if int(pvt.iloc[0]["N"]) > 0:
                equipes.append("PVT")
    return tuple(equipes)


def bloco_status(ano, mes, equipe, writes_enabled):
    """Badge de status + botões (some se writes_enabled=False — leitura só)."""
    info = fs.status_periodo(ano, mes, equipe)
    b = []
    if info:
        b.append(
            f"<div class='aviso-azul'>Já existe fechamento ativo desta equipe/período "
            f"(v{info['versao']}). Fechar de novo cria a v{info['versao'] + 1} e "
            f"substitui a anterior.</div>")
    else:
        b.append("<div class='caption'>Período aberto (cálculo ao vivo).</div>")

    if not writes_enabled:
        b.append("<div class='aviso-azul'>🔒 Fechar/reabrir estão desligados durante "
                 "a migração (WRITES_ENABLED). Use o painel Streamlit.</div>")
        return "".join(b)

    if info:
        b.append(
            f"<form method='post' action='/admin/exportar-comissoes/reabrir?ano={ano}&mes={mes}' "
            f"onsubmit=\"return confirm('Abrir a comissão de {equipe} — {mes:02d}/{ano}? "
            f"O período volta a calcular ao vivo; o snapshot v{info['versao']} fica "
            f"preservado mas inativo.')\">"
            f"<input type='hidden' name='equipe' value='{equipe}'>"
            f"<button type='submit' class='btn-secundario'>🔓 Abrir Comissão</button></form>")
    b.append(
        f"<form method='post' action='/admin/exportar-comissoes/fechar?ano={ano}&mes={mes}' "
        f"onsubmit=\"return confirm('Fechar a comissão de {equipe} — {mes:02d}/{ano}? "
        f"Isso congela os números atuais num snapshot imutável.')\" style='margin-top:6px;'>"
        f"<input type='hidden' name='equipe' value='{equipe}'>"
        f"<button type='submit' class='btn-secundario'>🔒 Fechar Comissão</button></form>")
    return "".join(b)


def bloco_job(job):
    """Div com data-status, para o JS de polling (sem htmx — mesmo padrão de
    fetch puro usado no resto do app) decidir se continua consultando."""
    if job is None:
        return ("<div id='job-status' data-status='done'>"
                "<div class='caption'>Job não encontrado (pode ter expirado "
                "com um restart).</div></div>")
    if job.status == "running":
        return (
            f"<div id='job-status' data-status='running'>"
            f"<progress value='{job.concluidos}' max='{max(job.total, 1)}' "
            f"style='width:100%'></progress>"
            f"<div class='caption'>{job.concluidos}/{job.total} — {job.atual}</div></div>")
    if job.status == "error":
        return (f"<div id='job-status' data-status='error'>"
                f"<div class='aviso-ambar'>Falha ao fechar: {job.erro}</div></div>")
    r = job.resultado or {}
    msg = (f"✓ Comissão fechada: {r.get('fechamento_id', '?')} — "
           f"{r.get('n_pessoas', 0)} pessoa(s), {r.get('n_composicao', 0)} linha(s) "
           f"de composição.")
    extra = ""
    if job.erros:
        extra = f"<div class='caption'>Não calculados: {', '.join(job.erros)}</div>"
    return f"<div id='job-status' data-status='done'><div class='aviso-azul'>{msg}</div>{extra}</div>"
