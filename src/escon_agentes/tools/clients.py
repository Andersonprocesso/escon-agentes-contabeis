"""Cadastro simples de clientes do escritório."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from escon_agentes.schema import ClientProfile


def list_clients(clients_dir: Path) -> list[ClientProfile]:
    clients_dir.mkdir(parents=True, exist_ok=True)
    result: list[ClientProfile] = []
    for path in sorted(clients_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        result.append(ClientProfile.model_validate(data))
    return result


def get_client(clients_dir: Path, client_id: str) -> ClientProfile | None:
    path = clients_dir / f"{client_id}.json"
    if not path.exists():
        return None
    return ClientProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_client(clients_dir: Path, client: ClientProfile) -> Path:
    clients_dir.mkdir(parents=True, exist_ok=True)
    path = clients_dir / f"{client.id}.json"
    path.write_text(client.model_dump_json(indent=2), encoding="utf-8")
    return path


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
            contatos={"whatsapp": "5511999990001", "email": "financeiro@demo.com.br"},
            tags=["demo", "servicos"],
        ),
        ClientProfile(
            id="demo-comercio",
            name="Demo Comércio ME",
            cnpj="98.765.432/0001-10",
            regime="simples_nacional",
            banco_principal="bradesco",
            contatos={"whatsapp": "5511988880002", "email": "contato@democomercio.com.br"},
            tags=["demo", "comercio"],
        ),
    ]
    for c in demos:
        save_client(clients_dir, c)


def client_inbox(inbox_root: Path, client_id: str) -> Path:
    p = inbox_root / client_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def as_table(clients: list[ClientProfile]) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "nome": c.name,
            "cnpj": c.cnpj,
            "regime": c.regime,
            "banco": c.banco_principal,
            "uf": c.uf,
            "source": c.source,
            "radar_id": c.radar_id,
            "whatsapp": (c.contatos or {}).get("whatsapp"),
            "drive_folder_hint": c.drive_folder_hint,
        }
        for c in clients
    ]
