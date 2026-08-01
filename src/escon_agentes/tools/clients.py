"""Cadastro de clientes do escritório (CRUD + contatos para cobrança)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from escon_agentes.schema import ClientProfile


def list_clients(clients_dir: Path) -> list[ClientProfile]:
    clients_dir.mkdir(parents=True, exist_ok=True)
    result: list[ClientProfile] = []
    for path in sorted(clients_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append(_normalize(ClientProfile.model_validate(data)))
        except Exception:
            continue
    return result


def get_client(clients_dir: Path, client_id: str) -> ClientProfile | None:
    path = clients_dir / f"{client_id}.json"
    if not path.exists():
        return None
    return _normalize(
        ClientProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    )


def save_client(clients_dir: Path, client: ClientProfile) -> Path:
    clients_dir.mkdir(parents=True, exist_ok=True)
    client = _normalize(client)
    path = clients_dir / f"{client.id}.json"
    path.write_text(client.model_dump_json(indent=2), encoding="utf-8")
    return path


def delete_client(
    clients_dir: Path,
    client_id: str,
    *,
    inbox_root: Path | None = None,
    remove_inbox: bool = False,
) -> bool:
    path = clients_dir / f"{client_id}.json"
    if not path.exists():
        return False
    path.unlink()
    if remove_inbox and inbox_root:
        inbox = inbox_root / client_id
        if inbox.exists() and inbox.is_dir():
            shutil.rmtree(inbox, ignore_errors=True)
    return True


def update_client(
    clients_dir: Path,
    client_id: str,
    patch: dict[str, Any],
) -> ClientProfile | None:
    existing = get_client(clients_dir, client_id)
    if not existing:
        return None
    data = existing.model_dump()
    # contatos merge
    contatos = dict(data.get("contatos") or {})
    if "contatos" in patch and isinstance(patch["contatos"], dict):
        contatos.update({k: v for k, v in patch["contatos"].items() if v is not None})
        patch = {**patch, "contatos": contatos}
    if "telefone" in patch or "phone" in patch or "whatsapp" in patch:
        tel = patch.get("telefone") or patch.get("phone") or patch.get("whatsapp")
        if tel is not None:
            contatos["telefone"] = str(tel).strip()
            contatos["whatsapp"] = str(tel).strip()
            data["telefone"] = str(tel).strip() or None
    if "email" in patch and patch["email"] is not None:
        contatos["email"] = str(patch["email"]).strip()
        data["email"] = str(patch["email"]).strip() or None
    data["contatos"] = contatos

    for key in (
        "name",
        "cnpj",
        "regime",
        "banco_principal",
        "uf",
        "tipo_pessoa",
        "tags",
        "drive_folder_hint",
        "source",
        "radar_id",
        "procuracao_ok",
        "monitoramento_ativo",
    ):
        if key in patch and patch[key] is not None:
            data[key] = patch[key]
    # nome aceita alias
    if "nome" in patch and patch["nome"]:
        data["name"] = patch["nome"]
    if "banco" in patch and patch["banco"]:
        data["banco_principal"] = patch["banco"]

    # id imutável (arquivo)
    data["id"] = client_id
    client = _normalize(ClientProfile.model_validate(data))
    save_client(clients_dir, client)
    return client


def create_client(clients_dir: Path, payload: dict[str, Any], inbox_root: Path | None = None) -> ClientProfile:
    cid = str(payload.get("id") or "").strip()
    if not cid:
        cnpj = re.sub(r"\D", "", str(payload.get("cnpj") or ""))
        if len(cnpj) >= 11:
            cid = cnpj
        else:
            raise ValueError("Informe id (CNPJ sem máscara) ou cnpj válido")
    if get_client(clients_dir, cid):
        raise ValueError(f"Cliente já existe: {cid}")

    name = (payload.get("name") or payload.get("nome") or "").strip()
    if not name:
        raise ValueError("Informe o nome / razão social")

    contatos: dict[str, str] = {}
    tel = payload.get("telefone") or payload.get("phone") or payload.get("whatsapp")
    email = payload.get("email")
    if tel:
        contatos["telefone"] = str(tel).strip()
        contatos["whatsapp"] = str(tel).strip()
    if email:
        contatos["email"] = str(email).strip()
    if isinstance(payload.get("contatos"), dict):
        contatos.update({k: str(v) for k, v in payload["contatos"].items() if v})

    client = _normalize(
        ClientProfile(
            id=cid,
            name=name,
            cnpj=payload.get("cnpj"),
            regime=payload.get("regime") or "simples_nacional",
            banco_principal=payload.get("banco_principal") or payload.get("banco") or "itau",
            contatos=contatos,
            telefone=contatos.get("telefone"),
            email=contatos.get("email"),
            tags=payload.get("tags") or ["manual"],
            uf=payload.get("uf"),
            source=payload.get("source") or "manual",
            drive_folder_hint=payload.get("drive_folder_hint"),
            radar_id=payload.get("radar_id"),
        )
    )
    save_client(clients_dir, client)
    if inbox_root:
        client_inbox(inbox_root, client.id)
    return client


def ensure_demo_clients(clients_dir: Path) -> None:
    if any(clients_dir.glob("*.json")):
        return
    demos = [
        ClientProfile(
            id="demo-servicos",
            name="Demo Serviços LTDA",
            cnpj="12.345.678/0001-90",
            regime="simples_nacional",
            banco_principal="itau",
            contatos={"whatsapp": "5511999990001", "telefone": "5511999990001", "email": "financeiro@demo.com.br"},
            telefone="5511999990001",
            email="financeiro@demo.com.br",
            tags=["demo", "servicos"],
            source="demo",
        ),
        ClientProfile(
            id="demo-comercio",
            name="Demo Comércio ME",
            cnpj="98.765.432/0001-10",
            regime="simples_nacional",
            banco_principal="bradesco",
            contatos={"whatsapp": "5511988880002", "telefone": "5511988880002", "email": "contato@democomercio.com.br"},
            telefone="5511988880002",
            email="contato@democomercio.com.br",
            tags=["demo", "comercio"],
            source="demo",
        ),
    ]
    for c in demos:
        save_client(clients_dir, c)


def client_inbox(inbox_root: Path, client_id: str) -> Path:
    p = inbox_root / client_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def as_table(clients: list[ClientProfile]) -> list[dict[str, Any]]:
    rows = []
    for c in clients:
        c = _normalize(c)
        rows.append(
            {
                "id": c.id,
                "nome": c.name,
                "name": c.name,
                "cnpj": c.cnpj,
                "regime": c.regime,
                "banco": c.banco_principal,
                "banco_principal": c.banco_principal,
                "uf": c.uf,
                "source": c.source,
                "radar_id": c.radar_id,
                "telefone": c.telefone or (c.contatos or {}).get("telefone") or (c.contatos or {}).get("whatsapp"),
                "whatsapp": (c.contatos or {}).get("whatsapp") or c.telefone,
                "email": c.email or (c.contatos or {}).get("email"),
                "drive_folder_hint": c.drive_folder_hint,
                "tags": c.tags,
            }
        )
    return rows


def _normalize(c: ClientProfile) -> ClientProfile:
    contatos = dict(c.contatos or {})
    tel = (c.telefone or contatos.get("telefone") or contatos.get("whatsapp") or "").strip() or None
    email = (c.email or contatos.get("email") or "").strip() or None
    if tel:
        contatos["telefone"] = tel
        contatos.setdefault("whatsapp", tel)
    if email:
        contatos["email"] = email
    return c.model_copy(update={"telefone": tel, "email": email, "contatos": contatos})
