"""Caixa de e-mail Rachel — Microsoft 365 via IMAP (contato@escondigital.com.br).

Somente leitura + rascunho: nunca envia e-mail. Usa apenas a biblioteca padrão
(imaplib/email) — sem dependências novas.
"""

from __future__ import annotations

import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr, parsedate_to_datetime

from escon_agentes.config import Settings

DRAFT_FOLDER_CANDIDATES = ("Drafts", "Draft", "Rascunhos")


@dataclass
class EmailSummary:
    uid: str
    message_id: str
    from_addr: str
    from_name: str
    subject: str
    date: datetime
    has_attachments: bool


@dataclass
class EmailFull(EmailSummary):
    body_text: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


class MailboxUnavailable(RuntimeError):
    """Credenciais ausentes ou falha ao conectar/logar no IMAP."""


def connect(settings: Settings) -> imaplib.IMAP4_SSL:
    if not settings.outlook_imap_user or not settings.outlook_imap_password:
        raise MailboxUnavailable(
            "OUTLOOK_IMAP_USER / OUTLOOK_IMAP_PASSWORD ausentes no .env"
        )
    conn = imaplib.IMAP4_SSL(settings.outlook_imap_host, settings.outlook_imap_port)
    try:
        conn.login(settings.outlook_imap_user, settings.outlook_imap_password)
    except imaplib.IMAP4.error as e:
        raise MailboxUnavailable(f"Login IMAP falhou para {settings.outlook_imap_user}: {e}") from e
    return conn


def find_drafts_folder(conn: imaplib.IMAP4_SSL) -> str:
    typ, data = conn.list()
    if typ == "OK":
        for raw in data or []:
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if "\\Drafts" in line:
                # formato: (flags) "delim" "Nome da pasta"
                m = re.search(r'"([^"]*)"$', line)
                if m:
                    return m.group(1)
            for name in DRAFT_FOLDER_CANDIDATES:
                if f'"{name}"' in line:
                    return name
    return "Drafts"


def _decode_header_value(raw: bytes) -> dict[str, str]:
    msg = message_from_bytes(raw)
    return {
        "from": msg.get("From", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
    }


def search_recent(
    conn: imaplib.IMAP4_SSL,
    *,
    folder: str = "INBOX",
    since_days: int = 30,
    unseen_only: bool = False,
) -> list[bytes]:
    typ, _ = conn.select(folder, readonly=False)
    if typ != "OK":
        raise MailboxUnavailable(f"Não foi possível abrir a pasta {folder}")
    since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    criteria = f'(SINCE "{since}")'
    if unseen_only:
        criteria = f'(SINCE "{since}" UNSEEN)'
    typ, data = conn.uid("SEARCH", None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def fetch_summary(conn: imaplib.IMAP4_SSL, uid: bytes) -> EmailSummary | None:
    typ, data = conn.uid(
        "FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
    )
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    headers = _decode_header_value(data[0][1])
    typ2, flags_data = conn.uid("FETCH", uid, "(BODYSTRUCTURE)")
    has_attach = False
    if typ2 == "OK" and flags_data and flags_data[0]:
        raw = flags_data[0]
        blob = raw if isinstance(raw, bytes) else str(raw).encode("utf-8", "ignore")
        has_attach = b"attachment" in blob.lower()
    name, addr = parseaddr(headers["from"])
    try:
        dt = parsedate_to_datetime(headers["date"]) if headers["date"] else datetime.now()
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
    except (TypeError, ValueError):
        dt = datetime.now()
    return EmailSummary(
        uid=uid.decode() if isinstance(uid, bytes) else str(uid),
        message_id=headers["message_id"].strip(),
        from_addr=addr.lower().strip(),
        from_name=name or addr,
        subject=headers["subject"].strip() or "(sem assunto)",
        date=dt,
        has_attachments=has_attach,
    )


def fetch_full(conn: imaplib.IMAP4_SSL, summary: EmailSummary) -> EmailFull:
    typ, data = conn.uid("FETCH", summary.uid.encode(), "(BODY.PEEK[])")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return EmailFull(**summary.__dict__)
    msg = message_from_bytes(data[0][1])

    body_text = ""
    attachments: list[tuple[str, bytes]] = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            filename = part.get_filename()
            if filename:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((filename, payload))
                continue
            if part.get_content_type() == "text/plain" and "attachment" not in disp and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    return EmailFull(
        **summary.__dict__,
        body_text=body_text.strip(),
        attachments=attachments,
    )


def create_draft(
    conn: imaplib.IMAP4_SSL,
    *,
    mailbox_address: str,
    to_addr: str,
    to_name: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
) -> None:
    folder = find_drafts_folder(conn)
    msg = EmailMessage()
    msg["From"] = mailbox_address
    msg["To"] = formataddr((to_name, to_addr)) if to_name else to_addr
    clean_subject = re.sub(r"^(re:\s*)+", "", subject, flags=re.IGNORECASE).strip()
    msg["Subject"] = f"Re: {clean_subject}" if clean_subject else "Re:"
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    typ, _ = conn.append(folder, "(\\Draft)", imaplib.Time2Internaldate(datetime.now().timestamp()), msg.as_bytes())
    if typ != "OK":
        raise MailboxUnavailable(f"Falha ao salvar rascunho na pasta {folder}")


def flag_message(conn: imaplib.IMAP4_SSL, uid: str) -> None:
    conn.uid("STORE", uid.encode(), "+FLAGS", "(\\Flagged)")
