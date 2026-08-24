"""App web do Painel de Comissões (migração do SiS — docs/21_migracao_web.md).

    python -m uvicorn webapp.main:app --reload
    → http://localhost:8000

Fases 3-4: identidade (dev/OAuth Google), RLS deny-by-default, gating de abas,
"Visualizar como" (admin real), telas mc/me/pvt/rd/admin e downloads xlsx.
Edições admin chegam na Fase 5; fechamento na Fase 6.
"""
from webapp.bootstrap import install_connection_shim

install_connection_shim()

import re                                              # noqa: E402
import threading                                       # noqa: E402
from pathlib import Path                               # noqa: E402
from urllib.parse import quote                         # noqa: E402

import pandas as pd                                    # noqa: E402
from fastapi import Depends, FastAPI, Form, Request    # noqa: E402
from fastapi.responses import (HTMLResponse, JSONResponse,      # noqa: E402
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles            # noqa: E402
from fastapi.templating import Jinja2Templates         # noqa: E402

from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from webapp.auth import authz                          # noqa: E402
from webapp.auth.drive_oauth import register_drive_oauth  # noqa: E402
from webapp.auth.identity import (UserCtx, VIEW_AS_COOKIE,  # noqa: E402
                                  cookie_view_as, get_user_ctx)
from webapp.auth.oauth import register_oauth           # noqa: E402
from webapp.config import settings                     # noqa: E402
from webapp.core import periods                        # noqa: E402
from webapp.services import admin_repo                 # noqa: E402
from webapp.services import drive_service               # noqa: E402
from webapp.services import fechamento_service as fs   # noqa: E402
from webapp.services import comissao_service as cs     # noqa: E402
from webapp.services import rls_service                # noqa: E402
from webapp.views import (admin_view, equipe_view, export_view,  # noqa: E402
                          fechamento_view, pvt_view)
from webapp.views.comissao_view import montar_blocos   # noqa: E402
from webapp.jobs import JobState, get_job, novo_job, set_job  # noqa: E402
from webapp.db import pool as pool_module              # noqa: E402

_AQUI = Path(__file__).resolve().parent

app = FastAPI(title="Painel de Comissões")
# Sessão (Starlette) única para o processo — usada pelo Authlib no login
# (AUTH_MODE=google) E no consentimento avulso do Drive (drive_oauth.py),
# que precisa funcionar mesmo com AUTH_MODE=dev.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory=_AQUI / "static"), name="static")
templates = Jinja2Templates(directory=_AQUI / "templates")
# Cache-busting: a URL do CSS muda quando o arquivo muda (evita CSS velho
# preso no cache do navegador durante a migração).
templates.env.globals["CSS_V"] = int((_AQUI / "static" / "css" / "painel.css").stat().st_mtime)
register_oauth(app)
register_drive_oauth(app)

_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def _base_ctx(ctx: UserCtx, aba: str, ano_nav: int, **extras):
    """Contexto comum dos templates: abas visíveis, páginas admin e view-as."""
    tabs = authz.nav_tabs(ctx, ano_nav)
    d = {
        "aba": aba, "tabs": tabs,
        "admin_paginas": authz.admin_paginas_permitidas(ctx, admin_view.ADMIN_PAGES),
        "is_real_admin": ctx.is_real_admin,
        "view_as": ctx.view_as,
        "user_email": ctx.email,
    }
    d.update(extras)
    return d


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def raiz():
    return RedirectResponse("/comissao")


# ── Visualizar como (só admin real; porta de _app.py:115-170) ────────────────

@app.post("/view-as")
def view_as(request: Request, email: str = Form(""),
            ctx: UserCtx = Depends(get_user_ctx)):
    destino = request.headers.get("referer") or "/comissao"
    if not ctx.is_real_admin:
        return RedirectResponse("/comissao", status_code=303)
    alvo = (email or "").strip().lower()
    if not _EMAIL_RE.match(alvo):
        return RedirectResponse(f"/comissao?va_erro={quote('E-mail inválido.')}",
                                status_code=303)
    if not rls_service.email_existe_nas_bases(alvo):
        return RedirectResponse(
            f"/comissao?va_erro={quote('E-mail não encontrado nas bases do painel (metas, parâmetros ou RLS).')}",
            status_code=303)
    resp = RedirectResponse(destino, status_code=303)
    resp.set_cookie(VIEW_AS_COOKIE, cookie_view_as(alvo), httponly=True,
                    samesite="lax", secure=settings.env == "prod")
    return resp


@app.post("/view-as/clear")
def view_as_clear(request: Request):
    resp = RedirectResponse(request.headers.get("referer") or "/comissao",
                            status_code=303)
    resp.delete_cookie(VIEW_AS_COOKIE)
    return resp


# ── Minha Comissão ────────────────────────────────────────────────────────────

def _resolve_filtros(ctx: UserCtx, ano, mes, consultor, equipe="Todas"):
    """render_filters(with_equipe=True) com RLS real: a lista de consultores é
    a do usuário efetivo (admin vê todos; restrito vê os seus; SemAcesso vazio)."""
    ano_d, mes_d = periods.periodo_default()
    ano = periods.safe_int(ano, ano_d)
    mes = periods.safe_int(mes, mes_d)
    if ano not in periods.periodo_anos():
        ano = ano_d
    if mes not in periods.periodo_meses(ano):
        mes = periods.periodo_meses(ano)[0] if ano != ano_d else mes_d

    consultores_t, tipo = rls_service.consultores_rls(ctx.email, ano, mes)
    consultores = list(consultores_t)
    if tipo == "SemAcesso":
        return ano, mes, "", [], "Todas", ["Todas"], tipo, {}

    eq_map = rls_service.equipes_consultores(ano, mes, tuple(consultores))
    equipes = ["Todas"] + sorted({e for e in eq_map.values() if e})
    equipe = (equipe or "Todas").strip()
    if equipe not in equipes:
        equipe = "Todas"
    cons_display = ([c for c in consultores if eq_map.get(c) == equipe]
                    if equipe != "Todas" else consultores)
    if not cons_display:
        cons_display, equipe = consultores, "Todas"

    consultor = (consultor or "").strip().lower()
    if consultor not in cons_display:
        # preferência do SiS: consultor anterior → o próprio usuário → primeiro
        consultor = ctx.email if ctx.email in cons_display else (
            cons_display[0] if cons_display else "")
    return ano, mes, consultor, cons_display, equipe, equipes, tipo, eq_map


@app.get("/comissao")
def comissao(request: Request, ano: int = None, mes: int = None,
             consultor: str = "", equipe: str = "Todas", va_erro: str = "",
             ctx: UserCtx = Depends(get_user_ctx)):
    ano, mes, consultor, consultores, equipe, equipes, tipo, eq_map = _resolve_filtros(
        ctx, ano, mes, consultor, equipe)
    atualizado_em = ""
    if consultor:
        try:
            _dt = cs.ultima_atualizacao_dados(consultor, ano, mes, eq_map.get(consultor, ""))
            if _dt is not None:
                atualizado_em = pd.Timestamp(_dt).strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            atualizado_em = ""
    return templates.TemplateResponse(request, "comissao.html", _base_ctx(
        ctx, "mc", ano,
        titulo="Minha Comissão", subtitulo="Minha Comissão",
        anos=periods.periodo_anos(),
        meses=[(m, periods.MESES_NOME[m]) for m in periods.periodo_meses(ano)],
        ano=ano, mes=mes,
        consultores=consultores, consultor=consultor,
        equipes=equipes, equipe=equipe,
        atualizado_em=atualizado_em,
        sem_acesso=(tipo == "SemAcesso"), va_erro=va_erro))


# Heurística: ~15 queries do lote de montar_contexto + algumas de
# composição/render. Não é exato (varia por layout AM/GD/B2G/padrão); o
# front nunca deixa a barra passar de 90% por causa disso, só fecha em
# 100% quando o job realmente termina (19/08/2026).
_TOTAL_ESTIMADO_COMISSAO = 20


def _montar_html_comissao(ano, mes, consultor):
    """Corpo de /comissao/blocos sem nada de HTTP — compartilhado pelo
    fallback síncrono e pelo job com progresso (comissao_iniciar)."""
    partes = []
    snap = cs.get_snapshot_info(ano, mes, consultor)
    if snap:
        try:
            data_txt = " em " + pd.to_datetime(snap["data"]).strftime("%d/%m/%Y")
        except Exception:
            data_txt = ""
        partes.append(
            f"<div class='aviso-ambar'>🔒 <strong>Período fechado{data_txt}.</strong> "
            f"Se houver algum negócio não contabilizado ou com valor desatualizado, "
            f"solicite o recálculo para Higor.</div>")

    dados = cs.get_comissao(consultor, ano, mes)
    if "erro" in dados:
        return "".join(partes) + f"<div class='aviso-azul'>{dados['erro']}</div>"
    if dados.get("ote_indisponivel"):
        return "".join(partes) + (
            f"<div class='aviso-ambar'>OTE para o cargo {dados.get('cargo', '')} "
            f"não encontrado em Cargos e OTEs ({periods.MESES_NOME.get(mes, mes)}/{ano}). "
            f"Comissão não pode ser calculada.</div>")

    partes.extend(montar_blocos(dados, consultor, ano, mes))
    return "".join(partes)


@app.get("/comissao/blocos")
def comissao_blocos(ano: int = None, mes: int = None, consultor: str = "",
                    equipe: str = "Todas", ctx: UserCtx = Depends(get_user_ctx)):
    """Fragmento com badge + blocos (a parte que calcula). RLS reaplicado.
    Fallback síncrono; a tela usa /comissao/iniciar + polling (progresso)."""
    ano, mes, consultor, _, _, _, tipo, _ = _resolve_filtros(ctx, ano, mes, consultor, equipe)
    if tipo == "SemAcesso":
        return HTMLResponse("<div class='aviso-ambar'>Você não tem acesso a este "
                            "painel. Solicite cadastro ao administrador.</div>")
    if not consultor:
        return HTMLResponse("<div class='aviso-azul'>Nenhum consultor encontrado para o período.</div>")
    try:
        return HTMLResponse(_montar_html_comissao(ano, mes, consultor))
    except Exception as e:
        return HTMLResponse(f"<div class='aviso-ambar'>Erro ao calcular comissão: {e}</div>")


@app.get("/comissao/iniciar")
def comissao_iniciar(ano: int = None, mes: int = None, consultor: str = "",
                     equipe: str = "Todas", ctx: UserCtx = Depends(get_user_ctx)):
    """Dispara o cálculo numa thread e devolve o job_id: a tela faz polling
    em /comissao/progresso/{job_id} pra desenhar uma barra de progresso com
    consultas de verdade, em vez do spinner indeterminado de antes."""
    ano, mes, consultor, _, _, _, tipo, _ = _resolve_filtros(ctx, ano, mes, consultor, equipe)

    if tipo == "SemAcesso" or not consultor:
        html_pronto = ("<div class='aviso-ambar'>Você não tem acesso a este painel. "
                       "Solicite cadastro ao administrador.</div>" if tipo == "SemAcesso" else
                       "<div class='aviso-azul'>Nenhum consultor encontrado para o período.</div>")
        job_id = novo_job()
        set_job(job_id, JobState(status="done", total=1, concluidos=1,
                                 resultado={"html": html_pronto}))
        return JSONResponse({"job_id": job_id})

    job_id = novo_job()
    job = JobState(status="running", total=_TOTAL_ESTIMADO_COMISSAO, concluidos=0)
    set_job(job_id, job)

    def _worker():
        token = pool_module.PROGRESSO_ATUAL.set(job)
        try:
            html = _montar_html_comissao(ano, mes, consultor)
            job.resultado = {"html": html}
            job.status = "done"
        except Exception as e:
            job.status = "error"
            job.erro = str(e)
        finally:
            pool_module.PROGRESSO_ATUAL.reset(token)

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/comissao/progresso/{job_id}")
def comissao_progresso(job_id: str):
    job = get_job(job_id)
    if job is None:
        return JSONResponse({"status": "error", "erro": "job não encontrado"}, status_code=404)
    out = {"status": job.status, "concluidos": job.concluidos, "total": job.total}
    if job.status == "done":
        out["html"] = (job.resultado or {}).get("html", "")
    elif job.status == "error":
        out["erro"] = job.erro
    return JSONResponse(out)


# ── Minha Equipe (admin: escolhe líder; gestor: a própria equipe) ─────────────

def _resolve_equipe_filtros(ctx: UserCtx, ano, mes, lider, equipe):
    ano_d, mes_d = periods.periodo_default()
    anos = list(range(periods.ano_atual(), 2024, -1))
    ano = periods.safe_int(ano, ano_d)
    mes = periods.safe_int(mes, mes_d)
    if ano not in anos:
        ano = ano_d
    if mes not in periods.MESES_NOME:
        mes = mes_d
    if ctx.is_admin:
        gestores = list(equipe_view.gestores_periodo(ano, mes))
        lider = (lider or "").strip().lower()
        if lider not in gestores:
            lider = gestores[0] if gestores else ""
        return ano, mes, anos, "admin", lider, gestores, "Todas", []
    equipes = equipe_view.equipes_do_gestor(ano, mes, ctx.email)
    equipe = equipe if equipe in equipes else ("Todas" if "Todas" in equipes else equipes[0])
    return ano, mes, anos, "gestor", "", [], equipe, equipes


@app.get("/equipe")
def equipe_page(request: Request, ano: int = None, mes: int = None,
                lider: str = "", equipe: str = "Todas",
                ctx: UserCtx = Depends(get_user_ctx)):
    ano_chk = periods.safe_int(ano, periods.periodo_default()[0])
    if "me" not in authz.nav_tabs(ctx, ano_chk):
        return RedirectResponse("/comissao")
    ano, mes, anos, modo, lider, gestores, equipe, equipes = _resolve_equipe_filtros(
        ctx, ano, mes, lider, equipe)
    frag = (f"/equipe/blocos?ano={ano}&mes={mes}&lider={lider}"
            if modo == "admin" else
            f"/equipe/blocos?ano={ano}&mes={mes}&equipe={quote(equipe)}")
    return templates.TemplateResponse(request, "equipe.html", _base_ctx(
        ctx, "me", ano,
        titulo="Minha Equipe", subtitulo="Minha Equipe",
        anos=anos,
        meses=[(m, periods.MESES_NOME[m][:3]) for m in periods.MESES_NOME],
        ano=ano, mes=mes, modo=modo,
        gestores=gestores, lider=lider, equipes=equipes, equipe=equipe,
        erro=(None if (gestores or modo == "gestor")
              else "Nenhum gestor encontrado para este período."),
        frag_url=frag,
        msg_carregando="Calculando a equipe… (uma comissão por membro; "
                       "a primeira carga de um mês aberto é a mais lenta)"))


@app.get("/equipe/blocos")
def equipe_blocos(ano: int = None, mes: int = None, lider: str = "",
                  equipe: str = "Todas", ctx: UserCtx = Depends(get_user_ctx)):
    ano_chk = periods.safe_int(ano, periods.periodo_default()[0])
    if "me" not in authz.nav_tabs(ctx, ano_chk):
        return HTMLResponse("")
    ano, mes, _, modo, lider, gestores, equipe, _ = _resolve_equipe_filtros(
        ctx, ano, mes, lider, equipe)
    if modo == "admin" and not lider:
        return HTMLResponse("<div class='aviso-ambar'>Nenhum gestor encontrado.</div>")
    dl = (f"/export/drive/equipe?ano={ano}&mes={mes}&lider={lider}"
          if modo == "admin" else
          f"/export/drive/equipe?ano={ano}&mes={mes}&equipe={quote(equipe)}")
    return HTMLResponse("".join(equipe_view.montar_equipe(
        ano, mes, modo, lider=lider, user=ctx.email, equipe_sel=equipe, dl_url=dl)))


# ── Comissão PVT ─────────────────────────────────────────────────────────────

@app.get("/pvt")
def pvt_page(request: Request, ano: int = None, trim: str = "",
             ctx: UserCtx = Depends(get_user_ctx)):
    anos = list(range(periods.ano_atual(), 2024, -1))
    ano = periods.safe_int(ano, periods.ano_atual())
    if ano not in anos:
        ano = anos[0]
    if "pvt" not in authz.nav_tabs(ctx, ano):
        return RedirectResponse("/comissao")
    q_default = f"Q{min((periods.mes_atual() - 1) // 3, 3) + 1}"
    trim = trim if trim in pvt_view.TRIMESTRES else q_default
    return templates.TemplateResponse(request, "pvt.html", _base_ctx(
        ctx, "pvt", ano,
        titulo="Comissão PVT", subtitulo="Comissão PVT",
        anos=anos, ano=ano, trim=trim,
        frag_url=f"/pvt/blocos?ano={ano}&trim={trim}",
        msg_carregando="Carregando o trimestre…"))


@app.get("/pvt/blocos")
def pvt_blocos(ano: int = None, trim: str = "",
               ctx: UserCtx = Depends(get_user_ctx)):
    ano = periods.safe_int(ano, periods.ano_atual())
    if "pvt" not in authz.nav_tabs(ctx, ano):
        return HTMLResponse("")
    trim = trim if trim in pvt_view.TRIMESTRES else "Q1"
    try:
        return HTMLResponse("".join(pvt_view.montar_pvt(ano, trim)))
    except Exception as e:
        return HTMLResponse(f"<div class='aviso-ambar'>Erro ao carregar dados: {e}</div>")


# ── Administração (modo leitura na Fase 4) ───────────────────────────────────

def _pode_admin_page(ctx: UserCtx, slug: str, ano: int) -> bool:
    tabs = authz.nav_tabs(ctx, ano)
    if slug == "recuperacao-dividas":
        return "rd" in tabs
    if "adm" not in tabs:
        return False
    return ctx.is_admin or slug == "patamares"


@app.get("/admin")
def admin_raiz(ctx: UserCtx = Depends(get_user_ctx)):
    destino = admin_view.ADMIN_PAGES[0].slug if ctx.is_admin else "patamares"
    return RedirectResponse(f"/admin/{destino}")


@app.get("/admin/{slug}")
def admin_page(request: Request, slug: str, ano: int = None, mes: int = None,
               equipe: str = "", job: str = "",
               ctx: UserCtx = Depends(get_user_ctx)):
    page = admin_view.POR_SLUG.get(slug)
    ano_d, mes_d = periods.periodo_default()
    ano = periods.safe_int(ano, ano_d)
    mes = periods.safe_int(mes, mes_d)
    if page is None or not _pode_admin_page(ctx, slug, ano):
        return RedirectResponse("/comissao")
    if mes not in periods.MESES_NOME:
        mes = mes_d

    extra = {}
    if slug == "exportar-comissoes" and ctx.is_admin:
        equipes = list(fechamento_view.equipes_periodo(ano, mes))
        equipe_sel = equipe if equipe in equipes else (equipes[0] if equipes else "")
        extra["fechamento_equipes"] = equipes
        extra["fechamento_equipe"] = equipe_sel
        if equipe_sel:
            extra["fechamento_status"] = fechamento_view.bloco_status(
                ano, mes, equipe_sel, settings.writes_enabled)
        extra["job_id"] = job
        if job:
            extra["job_html"] = fechamento_view.bloco_job(get_job(job))

    return templates.TemplateResponse(request, "admin.html", _base_ctx(
        ctx, "rd" if slug == "recuperacao-dividas" else "adm", ano,
        titulo=page.rotulo, subtitulo="Administração",
        admin_slug=slug, rotulo=page.rotulo, mensal=page.mensal,
        anos=list(range(periods.ano_atual(), 2024, -1)),
        meses=[(m, periods.MESES_NOME[m][:3]) for m in periods.MESES_NOME],
        ano=ano, mes=mes,
        frag_url=f"/admin/{slug}/dados?ano={ano}&mes={mes}",
        msg_carregando="Carregando…",
        msg=request.query_params.get("msg", ""),
        erro_admin=request.query_params.get("erro", ""),
        **extra))


@app.get("/admin/{slug}/dados")
def admin_dados(slug: str, ano: int = None, mes: int = None,
                ctx: UserCtx = Depends(get_user_ctx)):
    page = admin_view.POR_SLUG.get(slug)
    ano_d, mes_d = periods.periodo_default()
    ano = periods.safe_int(ano, ano_d)
    mes = periods.safe_int(mes, mes_d)
    if page is None or not _pode_admin_page(ctx, slug, ano):
        return HTMLResponse("")
    return HTMLResponse("".join(admin_view.montar_admin(slug, ano, mes, ctx.is_admin)))


# ── Escrita admin (Fase 5) — desligada por padrão (settings.writes_enabled) ──

def _writes_guard(ctx: UserCtx, slug: str, ano: int):
    page = admin_view.POR_SLUG.get(slug)
    if (page is None or not page.editavel or not settings.writes_enabled
            or not ctx.is_admin or not _pode_admin_page(ctx, slug, ano)):
        return None
    return page


@app.post("/admin/{slug}/salvar")
async def admin_salvar(slug: str, request: Request, ano: int = None, mes: int = None,
                       ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    page = _writes_guard(ctx, slug, ano)
    dest = f"/admin/{slug}?ano={ano}&mes={mes}"
    if page is None:
        return RedirectResponse(dest, status_code=303)
    form = await request.form()
    try:
        valores = {}
        if page.mensal:
            valores["ANO"], valores["MES"] = ano, mes
        for c in page.campos_chave:
            valores[c.nome] = admin_view.parse_valor(form.get(c.nome, ""), "texto")
        for c in page.campos:
            valores[c.nome] = admin_view.parse_valor(form.get(c.nome, ""), c.tipo)
        admin_repo.upsert(page, valores, ctx.real_email)
        return RedirectResponse(f"{dest}&msg={quote('Registro salvo.')}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


@app.post("/admin/{slug}/excluir")
async def admin_excluir(slug: str, request: Request, ano: int = None, mes: int = None,
                        ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    page = _writes_guard(ctx, slug, ano)
    dest = f"/admin/{slug}?ano={ano}&mes={mes}"
    if page is None:
        return RedirectResponse(dest, status_code=303)
    form = await request.form()
    try:
        chaves = dict(form)
        for col, _tr in (page.chave_remocao or page.chaves):
            if col in ("ID",) and chaves.get(col) is not None:
                chaves[col] = int(chaves[col])
        admin_repo.excluir(page, chaves)
        return RedirectResponse(f"{dest}&msg={quote('Registro removido.')}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


@app.post("/admin/{slug}/copiar")
def admin_copiar(slug: str, ano: int = None, mes: int = None,
                 ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    dest = f"/admin/{slug}?ano={ano}&mes={mes}"
    if slug in ("parametros", "metas") and _grade_pode_editar(ctx, slug, ano):
        ano_o, mes_o = (ano, mes - 1) if mes > 1 else (ano - 1, 12)
        try:
            if slug == "parametros":
                admin_repo.parametros_copiar_mes(ano, mes, ano_o, mes_o, ctx.real_email)
            else:
                admin_repo.metas_copiar_mes(ano, mes, ano_o, mes_o)
            return RedirectResponse(
                f"{dest}&msg={quote(f'Copiado de {mes_o:02d}/{ano_o}.')}", status_code=303)
        except Exception as e:
            return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)
    page = _writes_guard(ctx, slug, ano)
    if page is None or not page.copia_mes:
        return RedirectResponse(dest, status_code=303)
    ano_o, mes_o = (ano, mes - 1) if mes > 1 else (ano - 1, 12)
    try:
        admin_repo.copiar_mes(page, ano_o, mes_o, ano, mes, ctx.real_email)
        return RedirectResponse(
            f"{dest}&msg={quote(f'Copiado de {mes_o:02d}/{ano_o}.')}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


# ── Grades editáveis (Parâmetros, Metas) e Config com vigência ───────────────
# Fora do modelo AdminPage.chaves genérico (grade dinâmica com diff no
# servidor, ou form de vigência com dois modos de salvar) — guard próprio.

def _grade_pode_editar(ctx: UserCtx, slug: str, ano: int) -> bool:
    return (ctx.is_admin and settings.writes_enabled
            and _pode_admin_page(ctx, slug, ano))


@app.post("/admin/parametros/salvar-grade")
async def admin_parametros_salvar_grade(request: Request, ano: int = None, mes: int = None,
                                        ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    if not _grade_pode_editar(ctx, "parametros", ano):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)
    body = await request.json()
    try:
        salvos, removidos, erros = admin_repo.parametros_salvar_grid(
            ano, mes, body.get("linhas", []), ctx.real_email)
        if erros:
            return JSONResponse({"ok": False, "erro": "; ".join(erros)})
        return JSONResponse({"ok": True,
                             "msg": f"{salvos} registro(s) salvos. {removidos} removido(s)."})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


@app.post("/admin/metas/salvar-grade")
async def admin_metas_salvar_grade(request: Request, ano: int = None, mes: int = None,
                                   ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    if not _grade_pode_editar(ctx, "metas", ano) or (ano, mes) >= admin_view._RI_DESDE:
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)
    body = await request.json()
    try:
        salvos, erros = admin_repo.metas_salvar_grid(ano, mes, body.get("linhas", []))
        if erros:
            return JSONResponse({"ok": False, "erro": "; ".join(erros)})
        return JSONResponse({"ok": True, "msg": f"{salvos} registro(s) salvos."})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


@app.post("/admin/config/salvar-atual")
async def admin_config_salvar_atual(request: Request, ano: int = None, mes: int = None,
                                    ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    if not _grade_pode_editar(ctx, "config", ano):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)
    alterados = (await request.json()).get("alterados") or {}
    if not alterados:
        return JSONResponse({"ok": True, "msg": "Nenhum valor alterado."})
    try:
        dados = {chave: (v["valor"], int(v["ano"]), int(v["mes"]))
                 for chave, v in alterados.items()}
        admin_repo.config_salvar_atual(dados, ctx.real_email)
        return JSONResponse({"ok": True,
                             "msg": f"{len(dados)} valor(es) atualizados na vigência atual."})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


@app.post("/admin/config/nova-vigencia")
async def admin_config_nova_vigencia(request: Request, ano: int = None, mes: int = None,
                                     ctx: UserCtx = Depends(get_user_ctx)):
    ano_d, mes_d = periods.periodo_default()
    ano, mes = periods.safe_int(ano, ano_d), periods.safe_int(mes, mes_d)
    if not _grade_pode_editar(ctx, "config", ano):
        return JSONResponse({"ok": False, "erro": "Sem permissão."}, status_code=403)
    alterados = (await request.json()).get("alterados") or {}
    if not alterados:
        return JSONResponse({"ok": True, "msg": "Nenhum valor alterado."})
    try:
        dados = {chave: v["valor"] for chave, v in alterados.items()}
        admin_repo.config_nova_vigencia(dados, ano, mes, ctx.real_email)
        return JSONResponse({"ok": True,
                             "msg": f"Nova vigência {mes:02d}/{ano} criada para {len(dados)} chave(s)."})
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)})


@app.post("/admin/config/criar-chave")
async def admin_config_criar_chave(request: Request, ctx: UserCtx = Depends(get_user_ctx)):
    form = await request.form()
    ano_d, mes_d = periods.periodo_default()
    ano = periods.safe_int(form.get("ano"), ano_d)
    mes = periods.safe_int(form.get("mes"), mes_d)
    dest = f"/admin/config?ano={ano}&mes={mes}"
    if not _grade_pode_editar(ctx, "config", ano):
        return RedirectResponse(dest, status_code=303)
    chave = (form.get("chave") or "").strip()
    valor = (form.get("valor") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    if not chave or not valor:
        return RedirectResponse(f"{dest}&erro={quote('Informe chave e valor.')}", status_code=303)
    try:
        admin_repo.config_criar_chave(chave, valor, descricao, ano, mes, ctx.real_email)
        return RedirectResponse(f"{dest}&msg={quote('Chave criada.')}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


# ── Exportação para o Google Drive (RLS reaplicado em cada endpoint) ────────
# Troca o antigo download .xlsx (só no local, ver docs/21_migracao_web.md):
# sobe a planilha pro Drive da própria pessoa via OAuth incremental (escopo
# drive.file), com os mesmos hyperlinks embutidos que a tela mostra, em vez
# de uma coluna separada com a URL crua — ver webapp/services/drive_service.py
# e webapp/views/export_view.py.

def _consultor_permitido(ctx: UserCtx, consultor: str, ano: int, mes: int) -> bool:
    consultores, tipo = rls_service.consultores_rls(ctx.email, int(ano), int(mes))
    return tipo != "SemAcesso" and (consultor or "").lower() in consultores


def _drive_upload_response(ctx: UserCtx, df, nome, links, next_url: str):
    if df is None:
        return HTMLResponse("Sem dados para exportar.", status_code=404)
    if not drive_service.tem_autorizacao(ctx.real_email):
        return RedirectResponse(f"/auth/drive/autorizar?next={quote(next_url)}")
    try:
        arquivo = drive_service.upload_xlsx_como_sheet(
            ctx.real_email, export_view.xlsx_bytes(df, links=links),
            nome.rsplit(".", 1)[0])
    except Exception:
        return HTMLResponse("Falha ao exportar para o Drive.", status_code=502)
    return RedirectResponse(arquivo["webViewLink"])


@app.get("/export/drive/composicao")
def export_drive_composicao(consultor: str, ano: int, mes: int,
                            ctx: UserCtx = Depends(get_user_ctx)):
    if not _consultor_permitido(ctx, consultor, ano, mes):
        return HTMLResponse("Sem acesso.", status_code=403)
    df, nome, links = export_view.composicao(consultor.lower(), ano, mes)
    url = f"/export/drive/composicao?consultor={consultor}&ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, links, url)


@app.get("/export/drive/bk-extra")
def export_drive_bk_extra(consultor: str, ano: int, mes: int,
                          ctx: UserCtx = Depends(get_user_ctx)):
    if not _consultor_permitido(ctx, consultor, ano, mes):
        return HTMLResponse("Sem acesso.", status_code=403)
    df, nome, links = export_view.bk_extra(consultor.lower(), ano, mes)
    url = f"/export/drive/bk-extra?consultor={consultor}&ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, links, url)


@app.get("/export/drive/carteira-am")
def export_drive_carteira(consultor: str, ano: int, mes: int,
                          ctx: UserCtx = Depends(get_user_ctx)):
    if not _consultor_permitido(ctx, consultor, ano, mes):
        return HTMLResponse("Sem acesso.", status_code=403)
    df, nome, links = export_view.carteira_am(consultor.lower(), ano, mes)
    url = f"/export/drive/carteira-am?consultor={consultor}&ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, links, url)


@app.get("/export/drive/canc")
def export_drive_canc(consultor: str, ano: int, mes: int,
                      ctx: UserCtx = Depends(get_user_ctx)):
    if not _consultor_permitido(ctx, consultor, ano, mes):
        return HTMLResponse("Sem acesso.", status_code=403)
    df, nome, links = export_view.canc(consultor.lower(), ano, mes)
    url = f"/export/drive/canc?consultor={consultor}&ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, links, url)


@app.get("/export/drive/renovacoes-canc")
def export_drive_renov_canc(consultor: str, ano: int, mes: int,
                            ctx: UserCtx = Depends(get_user_ctx)):
    if not _consultor_permitido(ctx, consultor, ano, mes):
        return HTMLResponse("Sem acesso.", status_code=403)
    df, nome, links = export_view.renovacoes_canc(consultor.lower(), ano, mes)
    url = f"/export/drive/renovacoes-canc?consultor={consultor}&ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, links, url)


@app.get("/export/drive/equipe")
def export_drive_equipe(ano: int, mes: int, lider: str = "", equipe: str = "Todas",
                        ctx: UserCtx = Depends(get_user_ctx)):
    if "me" not in authz.nav_tabs(ctx, ano):
        return HTMLResponse("Sem acesso.", status_code=403)
    if ctx.is_admin:
        eq, df = equipe_view.tabela_equipe(ano, mes, "admin", lider=lider.lower())
        url = f"/export/drive/equipe?ano={ano}&mes={mes}&lider={quote(lider)}"
    else:
        eq, df = equipe_view.tabela_equipe(ano, mes, "gestor", user=ctx.email,
                                           equipe_sel=equipe)
        url = f"/export/drive/equipe?ano={ano}&mes={mes}&equipe={quote(equipe)}"
    nome = f"equipe_{eq}_{mes:02d}_{ano}.xlsx"
    return _drive_upload_response(ctx, df, nome, None, url)


@app.get("/export/drive/admin/{slug}")
def export_drive_admin(slug: str, ano: int = None, mes: int = None,
                       ctx: UserCtx = Depends(get_user_ctx)):
    page = admin_view.POR_SLUG.get(slug)
    ano_d, mes_d = periods.periodo_default()
    ano = periods.safe_int(ano, ano_d)
    mes = periods.safe_int(mes, mes_d)
    if page is None or not _pode_admin_page(ctx, slug, ano):
        return HTMLResponse("Sem acesso.", status_code=403)
    try:
        df = admin_view._listar(page.tabela, page.mensal, page.ordem, ano, mes)
    except Exception:
        return HTMLResponse("Erro ao exportar.", status_code=500)
    suf = f"_{mes:02d}_{ano}" if page.mensal else ""
    nome = f"{slug}{suf}.xlsx"
    url = f"/export/drive/admin/{slug}?ano={ano}&mes={mes}"
    return _drive_upload_response(ctx, df, nome, None, url)



# ── Fechamento (Fase 6) — desligado por padrão (settings.writes_enabled) ─────

@app.post("/admin/exportar-comissoes/fechar")
def fechar_comissao_route(ano: int, mes: int, equipe: str = Form(...),
                          ctx: UserCtx = Depends(get_user_ctx)):
    dest = f"/admin/exportar-comissoes?ano={ano}&mes={mes}&equipe={quote(equipe)}"
    if not ctx.is_admin or not settings.writes_enabled:
        return RedirectResponse(dest, status_code=303)
    try:
        job_id = fs.iniciar_fechamento(ano, mes, equipe, ctx.real_email)
        return RedirectResponse(f"{dest}&job={job_id}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


@app.post("/admin/exportar-comissoes/reabrir")
def reabrir_comissao_route(ano: int, mes: int, equipe: str = Form(...),
                           ctx: UserCtx = Depends(get_user_ctx)):
    dest = f"/admin/exportar-comissoes?ano={ano}&mes={mes}&equipe={quote(equipe)}"
    if not ctx.is_admin or not settings.writes_enabled:
        return RedirectResponse(dest, status_code=303)
    try:
        fs.reabrir(ano, mes, equipe)
        return RedirectResponse(f"{dest}&msg={quote('Comissão reaberta.')}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{dest}&erro={quote(str(e))}", status_code=303)


@app.get("/admin/exportar-comissoes/job/{job_id}")
def job_status_route(job_id: str, ctx: UserCtx = Depends(get_user_ctx)):
    if not ctx.is_admin:
        return HTMLResponse("")
    return HTMLResponse(fechamento_view.bloco_job(get_job(job_id)))
