"""Consentimento Google Drive (escopo drive.file) — independente do
AUTH_MODE de login: funciona mesmo com identidade fake (AUTH_MODE=dev),
porque é uma concessão à parte, não uma troca de identidade.

Pendência igual à do login (docs/21_migracao_web.md): OAuth Client no Google
Cloud Console + GOOGLE_CLIENT_ID/SECRET no .env local. Sem essas env vars,
register_drive_oauth() não registra as rotas (evita erro do Authlib com
client_id vazio).
"""
from fastapi import Depends
from fastapi.responses import RedirectResponse
from starlette.requests import Request

from webapp.auth.identity import UserCtx, get_user_ctx
from webapp.config import settings
from webapp.services import drive_service


def register_drive_oauth(app):
    if not settings.google_client_id or not settings.google_client_secret:
        return

    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        "google_drive",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        access_token_url="https://oauth2.googleapis.com/token",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        client_kwargs={"scope": "https://www.googleapis.com/auth/drive.file"},
    )

    @app.get("/auth/drive/autorizar")
    async def drive_autorizar(request: Request, next: str = "/comissao",
                              ctx: UserCtx = Depends(get_user_ctx)):
        request.session["drive_next"] = next
        # access_type/prompt só têm efeito passados aqui, não em client_kwargs
        # do register() — Authlib só puxa de lá as chaves em
        # OAuth2Client.EXTRA_AUTHORIZE_PARAMS ("response_mode", "nonce",
        # "prompt", "login_hint"), e access_type não está nessa lista: ele
        # ficava fora da URL, o Google nunca devolvia refresh_token e o app
        # entrava em loop pedindo consentimento de novo a cada exportação
        # (achado testando com o Higor, 21/08/2026). prompt=consent garante
        # o refresh_token mesmo numa segunda autorização da mesma pessoa.
        return await oauth.google_drive.authorize_redirect(
            request, str(request.url_for("drive_callback")),
            access_type="offline", prompt="consent")

    @app.get("/auth/drive/callback")
    async def drive_callback(request: Request, ctx: UserCtx = Depends(get_user_ctx)):
        token = await oauth.google_drive.authorize_access_token(request)
        drive_service.salvar_token(ctx.real_email, token)
        destino = request.session.pop("drive_next", "/comissao")
        return RedirectResponse(destino)
