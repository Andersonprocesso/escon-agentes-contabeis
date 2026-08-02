"""Raquel/Rachel — triagem da caixa contato@escondigital.com.br (Microsoft Graph).

Para cada e-mail recente:
  - cliente conhecido (e-mail cadastrado bate exato) → anexos ficam prontos para
    ir ao Drive em Radar Escon/{Empresa}/{Ano}/{Mês} + rascunho de resposta
    salvo na própria caixa (Outlook Drafts, via createReply), nunca enviado;
  - não-cliente → some no relatório de pendências + fica marcado (estrela) na caixa.

Idempotente: guarda os internetMessageId já processados em
data/outbox/email_triage_state.json para não duplicar rascunho/relatório.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from escon_agentes.agents.rachel import classify_category, classify_priority, default_draft_body
from escon_agentes.config import Settings
from escon_agentes.tools import graph_mail as mail
from escon_agentes.tools.clients import list_clients


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ._-]", "", t).strip()
    return re.sub(r"\s+", " ", t) or "sem-nome"


def _safe_filename(name: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "_", name or "arquivo")[:180]


def pasta_mes(d: datetime) -> str:
    """'07-2026' — mesma convenção que o Radar já usa no Drive
    (`{Empresa}/{Departamento}/{Ano}/{MM-AAAA}/`). Inventar outro formato
    deixaria as pastas do mesmo cliente inconsistentes entre si.
    """
    return f"{d.month:02d}-{d.year}"


# Imagens embutidas na assinatura do e-mail (image001.png, logos) não são
# documento do cliente e não devem ir para o Drive.
RE_IMAGEM_INLINE = re.compile(r"^image\d{3,}\.(png|jpg|jpeg|gif)$", re.IGNORECASE)
TAMANHO_MINIMO_ANEXO = 20 * 1024  # 20 KB


def anexo_relevante(nome: str, conteudo: bytes) -> bool:
    if RE_IMAGEM_INLINE.match(Path(nome).name):
        return False
    ext = Path(nome).suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp"} and len(conteudo) < TAMANHO_MINIMO_ANEXO:
        return False
    return True


def _load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_received(iso: str) -> datetime:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            return parsedate_to_datetime(iso).replace(tzinfo=None)
        except Exception:
            return datetime.now()


def run_email_triage(
    settings: Settings,
    *,
    since_days: int | None = None,
    unseen_only: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    clients = list_clients(settings.clients_dir)
    clients_with_email = [c for c in clients if c.email]
    by_email = {c.email.strip().lower(): c for c in clients_with_email}

    state_path = settings.outbox / "email_triage_state.json"
    state = _load_state(state_path)

    staging_root = settings.outbox / "email_attachments"
    non_client_report = settings.outbox / "emails_nao_clientes.jsonl"
    processed_report = settings.outbox / "emails_processados.jsonl"

    token = mail.get_access_token(settings)
    messages = mail.list_recent_messages(
        token,
        settings,
        since_days=since_days or settings.outlook_lookback_days,
        unread_only=unseen_only,
        top=limit,
    )

    clients_touched: dict[str, dict[str, Any]] = {}
    non_clients: list[dict[str, Any]] = []
    drafts_created = 0
    attachments_staged = 0
    flagged = 0
    skipped_already_processed = 0

    for msg in messages:
        internet_id = msg.get("internetMessageId") or msg["id"]
        if internet_id in state:
            skipped_already_processed += 1
            continue

        from_info = (msg.get("from") or {}).get("emailAddress") or {}
        from_addr = (from_info.get("address") or "").strip().lower()
        from_name = from_info.get("name") or from_addr
        subject = msg.get("subject") or "(sem assunto)"
        received = _parse_received(msg.get("receivedDateTime") or "")
        has_attachments = bool(msg.get("hasAttachments"))
        graph_id = msg["id"]

        client = by_email.get(from_addr)

        if client:
            saved_files: list[str] = []
            if has_attachments:
                ano = received.strftime("%Y")
                mes = pasta_mes(received)
                dest_dir = staging_root / client.id / ano / mes
                attachments = [
                    (n, c)
                    for n, c in mail.get_attachments(token, settings, graph_id)
                    if anexo_relevante(n, c)
                ]
                if attachments:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    for filename, content in attachments:
                        target = dest_dir / _safe_filename(Path(filename).name)
                        target.write_bytes(content)
                        saved_files.append(str(target))
                        attachments_staged += 1
            else:
                ano = received.strftime("%Y")
                mes = pasta_mes(received)

            body_text = mail.get_body_text(token, settings, graph_id)
            text_blob = f"{subject}\n{body_text}"
            priority = classify_priority(text_blob)
            category = classify_category(text_blob)
            draft_body = default_draft_body(subject, settings.escon_office_name)
            mail.create_draft_reply(token, settings, graph_id, draft_body)
            drafts_created += 1

            entry = clients_touched.setdefault(
                client.id,
                {
                    "client_id": client.id,
                    "name": client.name,
                    "emails": 0,
                    "attachments": 0,
                    "drive_dest": f"Radar Escon/{client.drive_folder_hint or _slug(client.name)}",
                },
            )
            entry["emails"] += 1
            entry["attachments"] += len(saved_files)

            with processed_report.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "message_id": internet_id,
                            "from": from_addr,
                            "subject": subject,
                            "date": received.isoformat(),
                            "client_id": client.id,
                            "priority": priority,
                            "category": category,
                            "attachments": saved_files,
                            "staged_for_drive": f"Radar Escon/{client.drive_folder_hint or _slug(client.name)}/{ano}/{mes}",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        else:
            mail.flag_message(token, settings, graph_id)
            flagged += 1
            record = {
                "message_id": internet_id,
                "from": from_addr,
                "from_name": from_name,
                "subject": subject,
                "date": received.isoformat(),
                "has_attachments": has_attachments,
                "nota": "Remetente não é cliente cadastrado — possui documento(s) que precisam de análise humana."
                if has_attachments
                else "Remetente não é cliente cadastrado.",
            }
            non_clients.append(record)
            with non_client_report.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        state[internet_id] = datetime.now().isoformat(timespec="seconds")

    _save_state(state_path, state)

    summary_txt = (
        f"{len(messages)} e-mail(s) analisado(s) ({skipped_already_processed} já processados antes). "
        f"{drafts_created} rascunho(s) criado(s) na caixa, {attachments_staged} anexo(s) prontos "
        f"para o Drive, {len(non_clients)} e-mail(s) de não-clientes marcado(s)/reportado(s)."
    )
    if len(clients_with_email) <= 5:
        summary_txt += (
            f" Atenção: só {len(clients_with_email)} de {len(clients)} clientes têm e-mail "
            f"cadastrado — cadastre mais para a triagem reconhecer mais remetentes."
        )

    return {
        "success": True,
        "summary": summary_txt,
        "since_days": since_days or settings.outlook_lookback_days,
        "emails_seen": len(messages),
        "skipped_already_processed": skipped_already_processed,
        "drafts_created": drafts_created,
        "attachments_staged": attachments_staged,
        "attachments_staging_root": str(staging_root),
        "clients_touched": list(clients_touched.values()),
        "non_clients": non_clients,
        "clients_with_email_registered": len(clients_with_email),
        "clients_total": len(clients),
        "non_client_report_file": str(non_client_report),
        "processed_report_file": str(processed_report),
    }
