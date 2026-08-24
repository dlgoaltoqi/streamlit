"""Export para Google Drive (como Google Sheets), OAuth por usuário, escopo
`drive.file` (só os arquivos que o próprio app cria — por isso não exige
revisão de segurança do Google, mesmo em produção).

POC (21/08/2026): o token fica em memória do processo (`_TOKENS`), chaveado
pelo e-mail REAL da pessoa (não o "visualizar como" — a autorização pertence
a quem está logado de verdade). Reinicia zerado a cada restart do servidor;
antes de ir para produção, decidir onde persistir de verdade (hoje o webapp
não tem tabela de usuário nenhuma, só o cookie assinado do "visualizar
como").
"""
import json
import time

import httpx

from webapp.config import settings

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

_TOKENS = {}  # email -> {"refresh_token", "access_token", "expires_at"}


def salvar_token(email: str, token: dict):
    """Chamado pelo callback OAuth (webapp/auth/drive_oauth.py) com o que o
    Google devolveu na troca do code. O refresh_token só vem na primeira
    autorização (ou quando forçamos prompt=consent); preserva o antigo se
    esta rodada não trouxer um novo."""
    email = email.lower()
    anterior = _TOKENS.get(email, {})
    _TOKENS[email] = {
        "refresh_token": token.get("refresh_token") or anterior.get("refresh_token"),
        "access_token": token.get("access_token"),
        "expires_at": time.time() + token.get("expires_in", 3600) - 60,
    }


def tem_autorizacao(email: str) -> bool:
    return bool(_TOKENS.get(email.lower(), {}).get("refresh_token"))


def _renovar(email: str) -> str:
    tk = _TOKENS.get(email.lower())
    if not tk or not tk.get("refresh_token"):
        return ""
    resp = httpx.post(_TOKEN_URL, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": tk["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    novo = resp.json()
    tk["access_token"] = novo["access_token"]
    tk["expires_at"] = time.time() + novo.get("expires_in", 3600) - 60
    return tk["access_token"]


def _access_token(email: str) -> str:
    tk = _TOKENS.get(email.lower())
    if not tk:
        return ""
    if tk.get("access_token") and time.time() < tk.get("expires_at", 0):
        return tk["access_token"]
    return _renovar(email)


def upload_xlsx_como_sheet(email: str, conteudo_xlsx: bytes, nome: str) -> dict:
    """Sobe os bytes de um .xlsx já gerado (export_view.xlsx_bytes) e devolve
    {"id", "webViewLink"} do Google Sheet criado — o Drive converte na hora
    porque o mimeType pedido no metadata é do Google Sheets, não do xlsx."""
    token = _access_token(email)
    if not token:
        raise RuntimeError("Sem autorização do Drive para este usuário.")
    metadata = {"name": nome, "mimeType": "application/vnd.google-apps.spreadsheet"}
    resp = httpx.post(
        f"{_UPLOAD_URL}?uploadType=multipart&fields=id,webViewLink",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "metadata": (None, json.dumps(metadata), "application/json"),
            "file": (nome, conteudo_xlsx,
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
