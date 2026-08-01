"""Importação de empresas do Radar Escon → cadastro local + pastas inbox."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from escon_agentes.schema import ClientProfile
from escon_agentes.tools.clients import client_inbox, save_client


REGIME_MAP = {
    "simples": "simples_nacional",
    "simples_nacional": "simples_nacional",
    "mei": "mei",
    "presumido": "lucropresumido",
    "lucropresumido": "lucropresumido",
    "real": "lucroreal",
    "lucroreal": "lucroreal",
}


def slug_id(razao: str, cnpj: str | None = None) -> str:
    """ID estável e legível: cnpj14 ou slug do nome."""
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) >= 11:
        return digits
    t = unicodedata.normalize("NFKD", razao or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t[:48] or "cliente").strip("-")


def format_cnpj(cnpj: str | None) -> str | None:
    if not cnpj:
        return None
    d = re.sub(r"\D", "", cnpj)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return cnpj


def drive_hint(razao: str) -> str:
    """Espelha a lógica de pasta do Radar (storage._slug)."""
    t = unicodedata.normalize("NFKD", razao or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ._-]", "", t).strip()
    return re.sub(r"\s+", " ", t) or "sem-nome"


def map_regime(raw: str | None) -> str:
    if not raw:
        return "simples_nacional"
    return REGIME_MAP.get(raw.strip().lower(), raw.strip().lower())


def row_to_client(row: dict[str, Any]) -> ClientProfile:
    razao = (row.get("razao_social") or row.get("name") or row.get("nome") or "").strip()
    cnpj_raw = row.get("cnpj_cpf") or row.get("cnpj") or ""
    radar_id = row.get("radar_id") or row.get("id")
    cfg = row.get("config_radar") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = {}

    contatos: dict[str, str] = {}
    tel = None
    email = None
    if isinstance(cfg, dict):
        if cfg.get("whatsapp"):
            tel = str(cfg["whatsapp"]).strip()
            contatos["whatsapp"] = tel
            contatos["telefone"] = tel
        if cfg.get("telefone"):
            tel = str(cfg["telefone"]).strip()
            contatos["telefone"] = tel
            contatos.setdefault("whatsapp", tel)
        if cfg.get("email"):
            email = str(cfg["email"]).strip()
            contatos["email"] = email

    client_id = slug_id(razao, str(cnpj_raw))
    tags = ["radar"]
    regime = map_regime(row.get("regime_tributario") or row.get("regime"))
    tags.append(regime)

    return ClientProfile(
        id=client_id,
        name=razao,
        cnpj=format_cnpj(str(cnpj_raw)) if cnpj_raw else None,
        regime=regime,
        contatos=contatos,
        telefone=tel,
        email=email,
        tags=tags,
        radar_id=str(radar_id) if radar_id else None,
        uf=(row.get("uf") or None),
        tipo_pessoa=row.get("tipo_pessoa") or "J",
        procuracao_ok=row.get("procuracao_ok"),
        monitoramento_ativo=row.get("monitoramento_ativo"),
        drive_folder_hint=drive_hint(razao),
        source="radar",
    )


def load_radar_export(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and "empresas" in data:
            return list(data["empresas"])
        if isinstance(data, list):
            return data
        raise ValueError("JSON inválido: espere lista ou {empresas: [...]}")
    # CSV
    reader = csv.DictReader(text.splitlines())
    return list(reader)


def import_radar_clients(
    export_path: Path,
    *,
    clients_dir: Path,
    inbox_root: Path,
    keep_demo: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = load_radar_export(export_path)
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    by_regime: dict[str, int] = {}

    # remove demos só se não keep_demo e houver dados reais
    if not dry_run and not keep_demo:
        for p in clients_dir.glob("demo-*.json"):
            p.unlink()

    for row in rows:
        client = row_to_client(row)
        by_regime[client.regime] = by_regime.get(client.regime, 0) + 1
        dest = clients_dir / f"{client.id}.json"
        if dest.exists():
            existing = json.loads(dest.read_text(encoding="utf-8"))
            # preserva banco, tags e contatos manuais (telefone/e-mail editados no painel)
            if existing.get("banco_principal"):
                client.banco_principal = existing["banco_principal"]
            extra_tags = [
                t for t in (existing.get("tags") or []) if t not in client.tags and t != "demo"
            ]
            client.tags = list(dict.fromkeys(client.tags + extra_tags))
            ex_cont = existing.get("contatos") or {}
            cont = dict(client.contatos or {})
            for k in ("telefone", "whatsapp", "email"):
                if ex_cont.get(k) and not cont.get(k):
                    cont[k] = ex_cont[k]
            if existing.get("telefone") and not client.telefone:
                cont["telefone"] = existing["telefone"]
                cont.setdefault("whatsapp", existing["telefone"])
            if existing.get("email") and not client.email:
                cont["email"] = existing["email"]
            client = client.model_copy(
                update={
                    "contatos": cont,
                    "telefone": client.telefone or existing.get("telefone") or cont.get("telefone"),
                    "email": client.email or existing.get("email") or cont.get("email"),
                }
            )
            updated.append(client.id)
        else:
            created.append(client.id)

        if not dry_run:
            save_client(clients_dir, client)
            client_inbox(inbox_root, client.id)

    index = {
        "source": str(export_path),
        "total": len(rows),
        "created": len(created),
        "updated": len(updated),
        "skipped": len(skipped),
        "by_regime": by_regime,
        "created_ids": created[:20],
        "updated_ids": updated[:20],
    }
    if not dry_run:
        clients_dir.mkdir(parents=True, exist_ok=True)
        (clients_dir.parent / "imports" / "last_import_report.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        report_path = clients_dir.parent / "imports" / "last_import_report.json"
        report_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        index["report"] = str(report_path)
    return index
