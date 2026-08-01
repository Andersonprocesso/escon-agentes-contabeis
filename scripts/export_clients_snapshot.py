"""Gera data/web/clients_snapshot.json para o dashboard Vercel (sem dados sensíveis extras)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from escon_agentes.config import get_settings  # noqa: E402
from escon_agentes.tools.clients import as_table, list_clients  # noqa: E402


def main() -> None:
    s = get_settings()
    rows = as_table(list_clients(s.clients_dir))
    # só campos públicos para o painel
    slim = [
        {
            "id": r["id"],
            "nome": r["nome"],
            "cnpj": r.get("cnpj"),
            "regime": r.get("regime"),
            "uf": r.get("uf"),
            "source": r.get("source"),
            "telefone": r.get("telefone") or r.get("whatsapp"),
            "whatsapp": r.get("whatsapp") or r.get("telefone"),
            "email": r.get("email"),
            "banco": r.get("banco"),
        }
        for r in rows
    ]
    out = ROOT / "data" / "web" / "clients_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"total": len(slim), "clients": slim}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK {len(slim)} clientes → {out}")


if __name__ == "__main__":
    main()
