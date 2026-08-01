"""Controle de certidões (CND) — cadastro local + alertas (Cesar)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _path(data_dir: Path) -> Path:
    p = data_dir / "certidoes.json"
    return p


def load_certidoes(data_dir: Path) -> list[dict[str, Any]]:
    path = _path(data_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_certidoes(data_dir: Path, items: list[dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _path(data_dir).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_certidao(
    data_dir: Path,
    *,
    client_id: str,
    tipo: str,
    status: str,
    validade: str | None = None,
    arquivo: str | None = None,
    observacao: str = "",
) -> dict[str, Any]:
    items = load_certidoes(data_dir)
    item = {
        "client_id": client_id,
        "tipo": tipo,  # federal | estadual | municipal | fgts | trabalhista
        "status": status,  # regular | irregular | vencida | a_vencer
        "validade": validade,
        "arquivo": arquivo,
        "observacao": observacao,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # replace same client+tipo
    items = [i for i in items if not (i["client_id"] == client_id and i["tipo"] == tipo)]
    items.append(item)
    save_certidoes(data_dir, items)
    return item


def attention_list(data_dir: Path, days_ahead: int = 15) -> list[dict[str, Any]]:
    today = date.today()
    alerts: list[dict[str, Any]] = []
    for it in load_certidoes(data_dir):
        status = it.get("status", "")
        if status in {"irregular", "vencida"}:
            alerts.append({**it, "reason": status})
            continue
        val = it.get("validade")
        if val:
            try:
                d = date.fromisoformat(val[:10])
            except ValueError:
                continue
            delta = (d - today).days
            if delta < 0:
                alerts.append({**it, "reason": "vencida", "dias": delta})
            elif delta <= days_ahead:
                alerts.append({**it, "reason": "a_vencer", "dias": delta})
    return alerts


def summary_certidoes(data_dir: Path) -> str:
    items = load_certidoes(data_dir)
    alerts = attention_list(data_dir)
    lines = [f"Certidões cadastradas: {len(items)} | Precisam atenção: {len(alerts)}"]
    for a in alerts[:20]:
        lines.append(
            f"  - {a['client_id']} | {a['tipo']} | {a.get('reason')} | validade={a.get('validade')}"
        )
    return "\n".join(lines)
