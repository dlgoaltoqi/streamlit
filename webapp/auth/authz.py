"""Gating de abas e páginas — porta de _app.py:98-106 e _GESTOR_PAGES."""
from webapp.services import rls_service


def nav_tabs(ctx, ano: int) -> list:
    """Abas visíveis para o usuário efetivo (mesma regra do _app.py)."""
    admin = ctx.is_admin
    gestor = rls_service.is_gestor_in_rls(ctx.email)
    saving_gestor = (gestor and not admin
                     and rls_service.is_saving_gestor(ctx.email, ano))
    tabs = ["mc"]
    if gestor or admin:
        tabs.append("me")
    if admin or rls_service.is_pvt(ctx.email):
        tabs.append("pvt")
    if admin or saving_gestor:
        tabs.append("rd")
    if admin or saving_gestor:
        tabs.append("adm")
    return tabs


def admin_paginas_permitidas(ctx, admin_pages) -> list:
    """Admin vê todas; gestor Saving só Patamares (_GESTOR_PAGES do SiS)."""
    if ctx.is_admin:
        return [(p.slug, p.rotulo) for p in admin_pages]
    return [(p.slug, p.rotulo) for p in admin_pages if p.slug == "patamares"]
