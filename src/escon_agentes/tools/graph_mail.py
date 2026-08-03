"""Caixa de e-mail Rachel via Microsoft Graph (OAuth device code).

Usa MSAL (login por dispositivo, respeita MFA/Conditional Access) em vez de
IMAP com usuário/senha — necessário porque o tenant escondigital.com.br
exige MFA moderno (Authenticator), que bloqueia autenticação básica.

Somente leitura + rascunho: nunca envia e-mail (nunca chama /sendMail).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import msal

from escon_agentes.config import Settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "Mail.ReadWrite"]


class MailboxUnavailable(RuntimeError):
    """Configuração ausente ou falha ao autenticar/chamar o Graph."""


def _cache_path(settings: Settings) -> Path:
    p = Path(settings.ms_graph_token_cache)
    if not p.is_absolute():
        from escon_agentes.config import PROJECT_ROOT

        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cache(settings: Settings) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    path = _cache_path(settings)
    if path.exists():
        cache.deserialize(path.read_text(encoding="utf-8"))
    return cache


def _save_cache(settings: Settings, cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _cache_path(settings).write_text(cache.serialize(), encoding="utf-8")


def get_access_token(settings: Settings, *, interactive_ok: bool = True) -> str:
    if not settings.ms_graph_client_id or not settings.ms_graph_tenant_id:
        raise MailboxUnavailable(
            "MS_GRAPH_CLIENT_ID / MS_GRAPH_TENANT_ID ausentes no .env "
            "(registre o app no Azure AD e preencha o .env)"
        )
    cache = _load_cache(settings)
    app = msal.PublicClientApplication(
        settings.ms_graph_client_id,
        authority=f"https://login.microsoftonline.com/{settings.ms_graph_tenant_id}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        if not interactive_ok:
            raise MailboxUnavailable(
                "Sem token em cache — rode uma vez de forma interativa para autorizar "
                "(abre um código para inserir em microsoft.com/devicelogin)."
            )
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise MailboxUnavailable(f"Falha ao iniciar device flow: {flow}")
        print(flow["message"])  # instrução com URL + código para o usuário
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(settings, cache)

    if "access_token" not in result:
        raise MailboxUnavailable(
            f"Falha ao obter token: {result.get('error')} — {result.get('error_description')}"
        )
    return result["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _mailbox_base(settings: Settings) -> str:
    # Login por device code é feito diretamente como a própria caixa
    # (contato@escondigital.com.br) — "/me" é o endpoint correto, não
    # "/users/{mailbox}" (que exige permissão de aplicativo/admin distinta).
    return f"{GRAPH_BASE}/me"


def list_recent_messages(
    token: str,
    settings: Settings,
    *,
    since_days: int = 30,
    unread_only: bool = False,
    top: int = 100,
) -> list[dict[str, Any]]:
    since = (datetime.utcnow() - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filt = f"receivedDateTime ge {since}"
    if unread_only:
        filt += " and isRead eq false"
    params = {
        "$filter": filt,
        "$select": "id,subject,from,receivedDateTime,hasAttachments,internetMessageId,conversationId",
        "$orderby": "receivedDateTime desc",
        "$top": str(min(top, 999)),
    }
    url = f"{_mailbox_base(settings)}/mailFolders/Inbox/messages"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=_headers(token), params=params)
    if r.status_code != 200:
        raise MailboxUnavailable(f"Falha ao listar mensagens: {r.status_code} {r.text[:300]}")
    return r.json().get("value", [])


def get_attachments(token: str, settings: Settings, message_id: str) -> list[tuple[str, bytes]]:
    url = f"{_mailbox_base(settings)}/messages/{message_id}/attachments"
    with httpx.Client(timeout=60) as client:
        r = client.get(url, headers=_headers(token))
    if r.status_code != 200:
        raise MailboxUnavailable(f"Falha ao buscar anexos: {r.status_code} {r.text[:300]}")
    out: list[tuple[str, bytes]] = []
    for att in r.json().get("value", []):
        if att.get("@odata.type") == "#microsoft.graph.fileAttachment" and att.get("contentBytes"):
            out.append((att.get("name") or "anexo", base64.b64decode(att["contentBytes"])))
    return out


def get_body_text(token: str, settings: Settings, message_id: str) -> str:
    url = f"{_mailbox_base(settings)}/messages/{message_id}"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=_headers(token), params={"$select": "body"})
    if r.status_code != 200:
        return ""
    body = r.json().get("body", {})
    content = body.get("content", "")
    if body.get("contentType") == "html":
        import re

        content = re.sub(r"<[^>]+>", " ", content)
    return content.strip()


def create_draft_reply(token: str, settings: Settings, message_id: str, body_text: str) -> str:
    """Cria um rascunho de resposta (nunca envia). Retorna o id do rascunho."""
    url = f"{_mailbox_base(settings)}/messages/{message_id}/createReply"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=_headers(token), json={})
    if r.status_code not in (200, 201):
        raise MailboxUnavailable(f"Falha ao criar rascunho: {r.status_code} {r.text[:300]}")
    draft = r.json()
    draft_id = draft["id"]

    patch_url = f"{_mailbox_base(settings)}/messages/{draft_id}"
    with httpx.Client(timeout=30) as client:
        r2 = client.patch(
            patch_url,
            headers=_headers(token),
            json={"body": {"contentType": "Text", "content": body_text}},
        )
    if r2.status_code not in (200, 201):
        raise MailboxUnavailable(f"Rascunho criado mas falhou ao escrever o texto: {r2.status_code}")
    return draft_id


def flag_message(token: str, settings: Settings, message_id: str) -> None:
    _set_flag(token, settings, message_id, "flagged")


def unflag_message(token: str, settings: Settings, message_id: str) -> None:
    """Tira a estrela — usado quando um e-mail marcado como 'não-cliente' passa a
    ser reconhecido como cliente (ex.: depois que o Pedro sincroniza o cadastro)."""
    _set_flag(token, settings, message_id, "notFlagged")


def _set_flag(token: str, settings: Settings, message_id: str, status: str) -> None:
    url = f"{_mailbox_base(settings)}/messages/{message_id}"
    with httpx.Client(timeout=30) as client:
        r = client.patch(url, headers=_headers(token), json={"flag": {"flagStatus": status}})
    if r.status_code not in (200, 201):
        raise MailboxUnavailable(f"Falha ao marcar e-mail ({status}): {r.status_code} {r.text[:300]}")


def mover_para_lixeira(token: str, settings: Settings, message_id: str) -> None:
    """Move para Itens Excluídos — reversível pelo Outlook. Nunca apaga de vez."""
    _mover(token, settings, message_id, "deleteditems")


def mover_para_pasta(token: str, settings: Settings, message_id: str, nome_pasta: str) -> None:
    pasta_id = _achar_pasta_id(token, settings, nome_pasta)
    if not pasta_id:
        raise MailboxUnavailable(f"Pasta não encontrada na caixa: {nome_pasta}")
    _mover(token, settings, message_id, pasta_id)


def _mover(token: str, settings: Settings, message_id: str, destino: str) -> None:
    url = f"{_mailbox_base(settings)}/messages/{message_id}/move"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=_headers(token), json={"destinationId": destino})
    if r.status_code not in (200, 201):
        raise MailboxUnavailable(f"Falha ao mover e-mail: {r.status_code} {r.text[:300]}")


def _achar_pasta_id(token: str, settings: Settings, nome: str) -> str | None:
    alvo = (nome or "").strip().lower()
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{_mailbox_base(settings)}/mailFolders",
            headers=_headers(token),
            params={"$top": "200", "$select": "id,displayName"},
        )
    if r.status_code != 200:
        return None
    for f in r.json().get("value", []):
        if (f.get("displayName") or "").strip().lower() == alvo:
            return f.get("id")
    return None


def find_by_internet_id(token: str, settings: Settings, internet_message_id: str) -> dict | None:
    """Localiza a mensagem pelo Message-ID do cabeçalho (o que guardamos no estado)."""
    safe = internet_message_id.replace("'", "''")
    params = {
        "$filter": f"internetMessageId eq '{safe}'",
        "$select": "id,subject,from,receivedDateTime,hasAttachments,internetMessageId",
    }
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{_mailbox_base(settings)}/messages", headers=_headers(token), params=params)
    if r.status_code != 200:
        return None
    vals = r.json().get("value", [])
    return vals[0] if vals else None
