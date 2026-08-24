"""Identidade do usuário no webapp.

- AUTH_MODE=dev: identidade fixa por env (DEV_USER_EMAIL; default = primeiro
  ADMIN_EMAILS) — substitui o st.experimental_user do SiS no desenvolvimento.
- AUTH_MODE=google: sessão criada pelo OAuth (webapp/auth/oauth.py).

Impersonação ("Visualizar como", só admin real): e-mail num cookie ASSINADO
(HMAC com SECRET_KEY) — no SiS ficava em st.session_state; aqui o servidor
valida a assinatura e reconfere que o usuário real é admin a cada request.
"""
import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request

from webapp.config import settings
from webapp.services import rls_service

VIEW_AS_COOKIE = "pc_view_as"
SESSION_COOKIE = "pc_sid"

# Sessões do modo google (sid -> email). In-process, como o cache (1 worker).
_SESSOES = {}


def _assinar(valor: str) -> str:
    sig = hmac.new(settings.secret_key.encode(), valor.encode(),
                   hashlib.sha256).hexdigest()[:32]
    return f"{valor}|{sig}"


def _validar(token: str) -> str:
    if not token or "|" not in token:
        return ""
    valor, _, sig = token.rpartition("|")
    esperado = hmac.new(settings.secret_key.encode(), valor.encode(),
                        hashlib.sha256).hexdigest()[:32]
    return valor if hmac.compare_digest(sig, esperado) else ""


def cookie_view_as(email: str) -> str:
    return _assinar(email)


def criar_sessao(email: str) -> str:
    import secrets
    sid = secrets.token_urlsafe(24)
    _SESSOES[sid] = email
    return _assinar(sid)


def encerrar_sessao(token: str):
    _SESSOES.pop(_validar(token or ""), None)


@dataclass(frozen=True)
class UserCtx:
    email: str        # identidade EFETIVA (já resolve o "visualizar como")
    real_email: str   # quem está logado de verdade
    is_admin: bool    # da identidade efetiva
    is_real_admin: bool
    view_as: str      # e-mail impersonado ("" quando não há)


def get_user_ctx(request: Request) -> UserCtx:
    if settings.auth_mode == "google":
        real = _SESSOES.get(_validar(request.cookies.get(SESSION_COOKIE, "")))
        if not real:
            raise HTTPException(status_code=307, headers={"Location": "/login"})
    else:
        real = (settings.dev_user_email or
                (settings.admin_emails[0] if settings.admin_emails else "")).lower()
    real_admin = rls_service.is_admin(real)
    view_as = _validar(request.cookies.get(VIEW_AS_COOKIE, "")) if real_admin else ""
    email = view_as or real
    return UserCtx(email=email, real_email=real,
                   is_admin=rls_service.is_admin(email),
                   is_real_admin=real_admin, view_as=view_as)
