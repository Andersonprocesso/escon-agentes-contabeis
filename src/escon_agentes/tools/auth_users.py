"""Usuários e convites do painel (login próprio, sem Traefik basic auth).

Arquivo: data/users.json (volume Docker — sobrevive a deploy).
Senhas: PBKDF2-SHA256 (stdlib, sem dependência nova).
Sessão: cookie assinado HMAC, 14 dias.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USERS_FILE = "users.json"
SESSION_DAYS = 14
PBKDF2_ROUNDS = 200_000
COOKIE_NAME = "escon_session"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def users_path(data_dir: Path) -> Path:
    return Path(data_dir) / USERS_FILE


def load_store(data_dir: Path) -> dict[str, Any]:
    p = users_path(data_dir)
    if not p.exists():
        return {"users": [], "invites": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"users": [], "invites": []}
    if not isinstance(data, dict):
        return {"users": [], "invites": []}
    data.setdefault("users", [])
    data.setdefault("invites", [])
    return data


def save_store(data_dir: Path, store: dict[str, Any]) -> None:
    p = users_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ROUNDS,
    )
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, rounds_s, salt, hex_dk = stored.split("$", 3)
        if kind != "pbkdf2":
            return False
        rounds = int(rounds_s)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            rounds,
        )
        return hmac.compare_digest(dk.hex(), hex_dk)
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user(store: dict[str, Any], email: str) -> dict[str, Any] | None:
    e = normalize_email(email)
    for u in store.get("users") or []:
        if normalize_email(u.get("email") or "") == e:
            return u
    return None


def public_user(u: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": u.get("email"),
        "name": u.get("name") or u.get("email"),
        "role": u.get("role") or "colaboradora",
        "created_at": u.get("created_at"),
    }


def ensure_admin(
    data_dir: Path,
    *,
    email: str,
    password: str,
    name: str = "Anderson",
) -> dict[str, Any]:
    """Garante um admin no primeiro boot (ou se a lista estiver vazia)."""
    store = load_store(data_dir)
    email_n = normalize_email(email)
    if not email_n or not password:
        return store
    existing = find_user(store, email_n)
    if existing:
        # se já existe, só eleva a admin se for o bootstrap e ainda não for
        if existing.get("role") != "admin" and not any(
            (u.get("role") == "admin") for u in store["users"]
        ):
            existing["role"] = "admin"
            save_store(data_dir, store)
        return store
    if store["users"]:
        # já há usuários — não cria admin silencioso de novo
        return store
    store["users"].append(
        {
            "email": email_n,
            "name": name or "Admin",
            "password_hash": hash_password(password),
            "role": "admin",
            "created_at": _now_iso(),
        }
    )
    save_store(data_dir, store)
    return store


def register_user(
    data_dir: Path,
    *,
    email: str,
    password: str,
    name: str,
    invite_code: str,
) -> dict[str, Any]:
    email_n = normalize_email(email)
    if not _EMAIL_RE.match(email_n):
        raise ValueError("E-mail inválido.")
    if len(password or "") < 8:
        raise ValueError("Senha deve ter pelo menos 8 caracteres.")
    name = (name or "").strip() or email_n.split("@")[0]
    code = (invite_code or "").strip().upper()
    if not code:
        raise ValueError("Informe o código de convite (peça ao Anderson).")

    store = load_store(data_dir)
    if find_user(store, email_n):
        raise ValueError("Já existe conta com este e-mail.")

    invite = None
    for inv in store.get("invites") or []:
        if (inv.get("code") or "").upper() == code:
            invite = inv
            break
    if not invite:
        raise ValueError("Código de convite inválido.")
    if invite.get("used_by"):
        raise ValueError("Este convite já foi usado.")

    user = {
        "email": email_n,
        "name": name,
        "password_hash": hash_password(password),
        "role": "colaboradora",
        "created_at": _now_iso(),
        "invite_code": code,
    }
    store["users"].append(user)
    invite["used_by"] = email_n
    invite["used_at"] = _now_iso()
    save_store(data_dir, store)
    return public_user(user)


def create_user_by_admin(
    data_dir: Path,
    *,
    email: str,
    password: str,
    name: str,
    role: str = "colaboradora",
) -> dict[str, Any]:
    email_n = normalize_email(email)
    if not _EMAIL_RE.match(email_n):
        raise ValueError("E-mail inválido.")
    if len(password or "") < 8:
        raise ValueError("Senha deve ter pelo menos 8 caracteres.")
    store = load_store(data_dir)
    if find_user(store, email_n):
        raise ValueError("Já existe conta com este e-mail.")
    role = role if role in ("admin", "colaboradora") else "colaboradora"
    user = {
        "email": email_n,
        "name": (name or "").strip() or email_n.split("@")[0],
        "password_hash": hash_password(password),
        "role": role,
        "created_at": _now_iso(),
    }
    store["users"].append(user)
    save_store(data_dir, store)
    return public_user(user)


def authenticate(data_dir: Path, email: str, password: str) -> dict[str, Any] | None:
    store = load_store(data_dir)
    user = find_user(store, email)
    if not user:
        return None
    if not verify_password(password, user.get("password_hash") or ""):
        return None
    return public_user(user)


def create_invite(
    data_dir: Path,
    *,
    created_by: str,
    label: str = "",
) -> dict[str, Any]:
    store = load_store(data_dir)
    code = "ESCON-" + secrets.token_hex(3).upper()
    inv = {
        "code": code,
        "label": (label or "").strip() or "Colaboradora",
        "created_by": normalize_email(created_by),
        "created_at": _now_iso(),
        "used_by": None,
        "used_at": None,
    }
    store.setdefault("invites", []).append(inv)
    save_store(data_dir, store)
    return inv


def list_users_public(data_dir: Path) -> list[dict[str, Any]]:
    store = load_store(data_dir)
    return [public_user(u) for u in store.get("users") or []]


def list_invites(data_dir: Path) -> list[dict[str, Any]]:
    store = load_store(data_dir)
    return list(store.get("invites") or [])


# --- sessão assinada ---


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    import base64

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def make_session_token(secret: str, user: dict[str, Any]) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = json.dumps(
        {
            "email": user["email"],
            "name": user.get("name"),
            "role": user.get("role"),
            "exp": exp,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    body = _b64(payload.encode("utf-8"))
    sig = hmac.new(
        secret.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{body}.{sig}"


def read_session_token(secret: str, token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(
            secret.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        data = json.loads(_b64d(body).decode("utf-8"))
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        return {
            "email": data.get("email"),
            "name": data.get("name"),
            "role": data.get("role") or "colaboradora",
        }
    except (ValueError, json.JSONDecodeError, TypeError):
        return None
