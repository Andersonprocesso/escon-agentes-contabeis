"""Solicitações de serviço do dashboard (colaboradoras)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# Catálogo de serviços que a equipe pode pedir
SERVICE_CATALOG: list[dict[str, str]] = [
    {
        "id": "contmatic",
        "label": "Lançamentos Contmatic (prioridade)",
        "description": "Processa pasta do cliente com motor Contabilizador (códigos reais Contmatic)",
        "agent_hint": "contabilizador",
    },
    {
        "id": "sync_drive",
        "label": "Sincronizar Drive/Radar → inbox",
        "description": "Copia XMLs/PDFs do Google Drive (ou MinIO do Radar) para a inbox do cliente",
        "agent_hint": "sync",
    },
    {
        "id": "xmls",
        "label": "Organizar XMLs fiscais",
        "description": "Xavier organiza NF-e/NFS-e e gera índice",
        "agent_hint": "xavier",
    },
    {
        "id": "documentos",
        "label": "Capturar PDFs e recibos",
        "description": "Bill extrai dados de DAS, boletos, folhas etc.",
        "agent_hint": "bill",
    },
    {
        "id": "conciliar",
        "label": "Conciliação bancária",
        "description": "John cruza OFX com lançamentos",
        "agent_hint": "john",
    },
    {
        "id": "cobrar_extratos",
        "label": "Cobrar extratos pendentes",
        "description": "Greg lista pendências e prepara mensagens (envio via Secretaria)",
        "agent_hint": "greg",
    },
    {
        "id": "tarefas",
        "label": "Revisar prazos e tarefas",
        "description": "Anne mostra o que está parado",
        "agent_hint": "anne",
    },
    {
        "id": "certidoes",
        "label": "Painel de certidões",
        "description": "Cesar lista CND irregulares/a vencer",
        "agent_hint": "cesar",
    },
    {
        "id": "reforma",
        "label": "Dúvida Reforma Tributária",
        "description": "Lucy explica CBS/IBS (validar com contador)",
        "agent_hint": "lucy",
    },
    {
        "id": "briefing",
        "label": "Briefing de notícias",
        "description": "Karen resume mudanças relevantes",
        "agent_hint": "karen",
    },
    {
        "id": "financeiro",
        "label": "Análise financeira do extrato",
        "description": "Paul gera insights a partir do OFX",
        "agent_hint": "paul",
    },
    {
        "id": "whatsapp",
        "label": "Atendimento WhatsApp",
        "description": "Usar Secretaria/EsconZap (produção) — não o multiagente local",
        "agent_hint": "secretaria",
    },
]


def _path(requests_dir: Path) -> Path:
    requests_dir.mkdir(parents=True, exist_ok=True)
    return requests_dir / "board.json"


def load_requests(requests_dir: Path) -> list[dict[str, Any]]:
    path = _path(requests_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_requests(requests_dir: Path, items: list[dict[str, Any]]) -> None:
    _path(requests_dir).write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_request(
    requests_dir: Path,
    *,
    service_id: str,
    client_id: str | None = None,
    notes: str = "",
    requested_by: str = "equipe",
    model: str | None = None,
    folder: str | None = None,
) -> dict[str, Any]:
    catalog = {s["id"]: s for s in SERVICE_CATALOG}
    if service_id not in catalog:
        raise ValueError(f"Serviço desconhecido: {service_id}")

    items = load_requests(requests_dir)
    item = {
        "id": str(uuid4())[:8],
        "service_id": service_id,
        "service_label": catalog[service_id]["label"],
        "agent_hint": catalog[service_id]["agent_hint"],
        "client_id": client_id,
        "notes": notes,
        "folder": folder,
        "requested_by": requested_by,
        "model": model,
        "status": "queued",  # queued | running | waiting_human | done | failed | cancelled
        "run_id": None,
        "result_summary": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.insert(0, item)
    save_requests(requests_dir, items)
    return item


def update_request(requests_dir: Path, req_id: str, **fields: Any) -> dict[str, Any] | None:
    items = load_requests(requests_dir)
    for it in items:
        if it["id"] == req_id:
            it.update(fields)
            it["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_requests(requests_dir, items)
            return it
    return None


def get_request(requests_dir: Path, req_id: str) -> dict[str, Any] | None:
    for it in load_requests(requests_dir):
        if it["id"] == req_id:
            return it
    return None
