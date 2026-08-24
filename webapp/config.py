"""Configuração do webapp — tudo por variável de ambiente (12-factor).

O mesmo módulo serve o smoke local (connection_name) e o servidor (service
account com key-pair). Em dev, um `.env` na raiz do repo (fora do git) supre
essas variáveis sem precisar exportar no shell; no servidor real, quem injeta
as env vars é a plataforma, e o arquivo simplesmente não existe.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _csv(nome: str, default: str = "") -> tuple:
    return tuple(e.strip().lower() for e in os.getenv(nome, default).split(",") if e.strip())


@dataclass(frozen=True)
class Settings:
    # ── Ambiente ─────────────────────────────────────────────────────────────
    env: str = os.getenv("ENV", "dev")                     # dev | prod
    auth_mode: str = os.getenv("AUTH_MODE", "dev")         # dev | google
    dev_user_email: str = os.getenv("DEV_USER_EMAIL", "")  # identidade fake no modo dev
    secret_key: str = os.getenv("SECRET_KEY", "dev-nao-usar-em-prod")

    # ── Snowflake ────────────────────────────────────────────────────────────
    # Modo 1 (dev): perfil do connections.toml (igual ao harness de validação).
    sf_connection_name: str = os.getenv("SNOWFLAKE_CONNECTION_NAME", "local_cli")
    # Escritas admin (Fase 5): desligadas por default até o cutover; "clone"
    # aponta os writes para as tabelas MIGTESTE_* (gate de validação).
    writes_enabled: bool = os.getenv("WRITES_ENABLED", "") == "1"
    writes_target: str = os.getenv("WRITES_TARGET", "prod")
    # Modo 2 (servidor): service account com key-pair; ativa quando ACCOUNT definido.
    sf_account: str = os.getenv("SNOWFLAKE_ACCOUNT", "")
    sf_user: str = os.getenv("SNOWFLAKE_USER", "SVC_PAINEL_COMISSOES")
    sf_private_key_path: str = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")
    sf_role: str = os.getenv("SNOWFLAKE_ROLE", "ROLE_PAINEL_COMISSOES_APP")
    sf_warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE", "DATAANALYST_WH")
    pool_size: int = int(os.getenv("SNOWFLAKE_POOL_SIZE", "4"))

    # ── Autorização ──────────────────────────────────────────────────────────
    # Mesma semântica do ADMIN_EMAILS hardcoded do SiS (lockout-proof: mudar
    # exige redeploy/restart). Default espelha utils/connection.py.
    admin_emails: tuple = field(
        default_factory=lambda: _csv("ADMIN_EMAILS", "higor.nocetti@altoqi.com.br"))
    google_workspace_domain: str = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "altoqi.com.br")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    def usa_keypair(self) -> bool:
        return bool(self.sf_account)


settings = Settings()
