"""Login Google OAuth (Authlib) — ativa com AUTH_MODE=google.

Pendências externas antes de ativar: OAuth Client no Google Cloud Console
(redirect http://localhost:8000/auth/callback e o domínio futuro) e as env
vars GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SECRET_KEY. Valida
email_verified e o domínio do Workspace (claims hd) de verdade — o hint de
login não é garantia.
"""
from fastapi.responses import RedirectResponse

from webapp.auth import identity
from webapp.config import settings


def register_oauth(app):
    if settings.auth_mode != "google":
        return

    from authlib.integrations.starlette_client import OAuth

    # SessionMiddleware é registrado uma única vez em webapp/main.py (o
    # Drive OAuth também precisa dela, mesmo com AUTH_MODE != google).
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile",
                       "hd": settings.google_workspace_domain},
    )

    @app.get("/login")
    async def login(request):
        return await oauth.google.authorize_redirect(
            request, str(request.url_for("auth_callback")))

    @app.get("/auth/callback")
    async def auth_callback(request):
        token = await oauth.google.authorize_access_token(request)
        claims = token.get("userinfo") or {}
        email = (claims.get("email") or "").lower()
        if (not email or not claims.get("email_verified")
                or claims.get("hd") != settings.google_workspace_domain):
            return RedirectResponse("/login")
        resp = RedirectResponse("/comissao")
        resp.set_cookie(identity.SESSION_COOKIE, identity.criar_sessao(email),
                        httponly=True, samesite="lax",
                        secure=settings.env == "prod", max_age=8 * 3600)
        return resp

    @app.get("/logout")
    def logout(request):
        identity.encerrar_sessao(request.cookies.get(identity.SESSION_COOKIE, ""))
        resp = RedirectResponse("/login")
        resp.delete_cookie(identity.SESSION_COOKIE)
        return resp
