"""Quadro de tarefas do escritório (Anne)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


def _board_path(tasks_dir: Path) -> Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir / "board.json"


def load_board(tasks_dir: Path) -> list[dict[str, Any]]:
    path = _board_path(tasks_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_board(tasks_dir: Path, items: list[dict[str, Any]]) -> None:
    path = _board_path(tasks_dir)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add_task(
    tasks_dir: Path,
    title: str,
    *,
    client_id: str | None = None,
    due_days: int = 3,
    owner: str = "equipe",
    priority: str = "medium",
    notes: str = "",
) -> dict[str, Any]:
    items = load_board(tasks_dir)
    item = {
        "id": str(uuid4())[:8],
        "title": title,
        "client_id": client_id,
        "owner": owner,
        "priority": priority,
        "status": "open",
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "due_at": (datetime.now() + timedelta(days=due_days)).date().isoformat(),
    }
    items.append(item)
    save_board(tasks_dir, items)
    return item


def list_stale(tasks_dir: Path, days: int = 2) -> list[dict[str, Any]]:
    items = load_board(tasks_dir)
    cutoff = datetime.now() - timedelta(days=days)
    stale = []
    for it in items:
        if it.get("status") != "open":
            continue
        updated = datetime.fromisoformat(it.get("updated_at", it["created_at"]))
        due = it.get("due_at")
        overdue = False
        if due:
            overdue = datetime.fromisoformat(due).date() < datetime.now().date()
        if updated < cutoff or overdue:
            stale.append(it)
    return stale


def close_task(tasks_dir: Path, task_id: str) -> bool:
    items = load_board(tasks_dir)
    found = False
    for it in items:
        if it["id"] == task_id:
            it["status"] = "done"
            it["updated_at"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if found:
        save_board(tasks_dir, items)
    return found


def summary_board(tasks_dir: Path) -> str:
    items = load_board(tasks_dir)
    open_items = [i for i in items if i.get("status") == "open"]
    stale = list_stale(tasks_dir)
    lines = [
        f"Tarefas abertas: {len(open_items)} | Sem atualização/atrasadas: {len(stale)}",
    ]
    for it in stale[:15]:
        lines.append(
            f"  - [{it['id']}] {it['title']} (cliente={it.get('client_id') or '-'}, "
            f"vence={it.get('due_at')}, prioridade={it.get('priority')})"
        )
    if not stale and open_items:
        for it in open_items[:10]:
            lines.append(f"  - [{it['id']}] {it['title']}")
    return "\n".join(lines)
