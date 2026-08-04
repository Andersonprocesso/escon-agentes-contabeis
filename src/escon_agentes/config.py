"""Configuração do sistema — OpenRouter multi-modelo + pastas Escon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_DATA = PROJECT_ROOT / "data"

# fallback se models.yaml ausente
DEFAULT_ALIASES: dict[str, str] = {
    "kimi": "moonshotai/kimi-k2",
    "k2": "moonshotai/kimi-k2",
    "gpt": "openai/gpt-4o-mini",
    "gps": "openai/gpt-4o-mini",
    "gpt4": "openai/gpt-4o",
    "grok": "x-ai/grok-4",
    "deepseek": "deepseek/deepseek-chat",
    "gemini": "google/gemini-2.5-flash",
    "claude": "anthropic/claude-sonnet-4",
    "cheap": "deepseek/deepseek-chat",
    "smart": "anthropic/claude-sonnet-4",
}


def load_models_config() -> dict[str, Any]:
    path = CONFIG_DIR / "models.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data
    return {
        "default_alias": "deepseek",
        "aliases": DEFAULT_ALIASES,
        "openrouter_base_url": "https://openrouter.ai/api/v1",
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter (preferido)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""  # id completo ou alias
    llm_model: str = ""  # alias ou id; sobrescreve openrouter_model

    # xAI direto (opcional)
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.5"

    # Provider forçado: openrouter | xai | auto
    llm_provider: str = "auto"

    escon_office_name: str = "Escon Soluções Contábeis"
    escon_data_dir: str = str(DEFAULT_DATA)
    escon_offline: bool = False
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787

    # Pasta local do Google Drive for Desktop (raiz "Radar Escon")
    google_drive_radar_root: str = ""

    # Rachel — caixa de e-mail (Microsoft 365 via IMAP) — mantido como fallback
    outlook_imap_host: str = "outlook.office365.com"
    outlook_imap_port: int = 993
    outlook_imap_user: str = ""
    outlook_imap_password: str = ""
    outlook_lookback_days: int = 30

    # Rachel — caixa de e-mail via Microsoft Graph (OAuth device code, respeita MFA)
    ms_graph_client_id: str = ""
    ms_graph_tenant_id: str = ""
    ms_graph_mailbox: str = ""  # contato@escondigital.com.br
    ms_graph_token_cache: str = ".msal_cache/rachel_token_cache.json"
    # Documentos (OneDrive) costumam estar em outra conta que não a da caixa de
    # e-mail. Dois logins separados: um token só para mail, outro só para arquivos.
    ms_graph_files_user: str = ""
    ms_graph_files_cache: str = ".msal_cache/arquivos_token_cache.json"

    # Pedro Henrique — cadastro (Sistema Acessórias)
    acessorias_token: str = ""

    @property
    def data_dir(self) -> Path:
        p = Path(self.escon_data_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def inbox(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def outbox(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def clients_dir(self) -> Path:
        return self.data_dir / "clients"

    @property
    def tasks_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_dir / "knowledge"

    @property
    def requests_dir(self) -> Path:
        return self.data_dir / "requests"

    def models_meta(self) -> dict[str, Any]:
        return load_models_config()

    def aliases(self) -> dict[str, str]:
        meta = self.models_meta()
        aliases = dict(DEFAULT_ALIASES)
        aliases.update(meta.get("aliases") or {})
        return aliases

    def resolve_model(self, model: str | None = None) -> str:
        """Aceita alias (kimi, gpt, gps, grok...) ou id completo openrouter."""
        raw = (model or self.llm_model or self.openrouter_model or "").strip()
        aliases = self.aliases()
        if not raw:
            default_alias = self.models_meta().get("default_alias") or "deepseek"
            return aliases.get(default_alias, DEFAULT_ALIASES["deepseek"])
        key = raw.lower()
        if key in aliases:
            return aliases[key]
        return raw

    def active_provider(self) -> str:
        """Retorna openrouter | xai | none."""
        if self.escon_offline:
            return "none"
        pref = (self.llm_provider or "auto").lower()
        if pref == "openrouter" and self.openrouter_api_key:
            return "openrouter"
        if pref == "xai" and self.xai_api_key:
            return "xai"
        # auto
        if self.openrouter_api_key:
            return "openrouter"
        if self.xai_api_key:
            return "xai"
        return "none"

    @property
    def llm_available(self) -> bool:
        return self.active_provider() != "none"

    def ensure_dirs(self) -> None:
        for d in (
            self.inbox,
            self.outbox,
            self.clients_dir,
            self.tasks_dir,
            self.knowledge_dir,
            self.requests_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
