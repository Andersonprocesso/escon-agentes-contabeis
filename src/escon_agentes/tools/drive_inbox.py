"""Espelha pasta Google Drive (Radar Escon) → data/inbox/{cliente}.

Estrutura esperada (mesma do Radar):
  {GOOGLE_DRIVE_RADAR_ROOT}/
    Radar Escon/   ou raiz já apontando para ela
      {Nome Empresa}/
        Notas Fiscais-Entrada/
        Notas Fiscais-Saida/
        Notas Fiscais-Servico/
        Impostos/
        Extratos/
        ...

Se o Drive for Desktop não estiver sincronizado localmente, use `sync-inbox`
(MinIO via SSH) — é a mesma árvore de arquivos.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from escon_agentes.tools.clients import list_clients

# Subpastas úteis para Contmatic (espelho DEPARTAMENTO_POR_TIPO do Radar)
DEFAULT_SUBDIRS = (
    "Notas Fiscais-Entrada",
    "Notas Fiscais-Saida",
    "Notas Fiscais-Servico",
    "Impostos",
    "Extratos",
    "Recibos",
    "Comprovantes de Pagamento",
)

EXTENSIONS = {".xml", ".ofx", ".pdf", ".OFX", ".XML", ".PDF"}

CANDIDATE_ROOTS = [
    Path.home() / "Google Drive" / "Radar Escon",
    Path.home() / "My Drive" / "Radar Escon",
    Path.home() / "GoogleDrive" / "Radar Escon",
    Path(r"G:\Meu Drive\Radar Escon"),
    Path(r"G:\My Drive\Radar Escon"),
    Path(r"H:\Meu Drive\Radar Escon"),
    Path.home() / "OneDrive" / "Radar Escon",
]


def slug_drive(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ._-]", "", t).strip()
    return re.sub(r"\s+", " ", t) or "sem-nome"


def detect_drive_root(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    env = os.environ.get("GOOGLE_DRIVE_RADAR_ROOT") or os.environ.get("ESCON_DRIVE_ROOT")
    if env and Path(env).exists():
        return Path(env)
    for c in CANDIDATE_ROOTS:
        if c.exists():
            return c
    # tenta achar pasta "Radar Escon" em drives comuns
    for letter in "CDEFGHI":
        for mid in (
            f"{letter}:/Meu Drive/Radar Escon",
            f"{letter}:/My Drive/Radar Escon",
            f"{letter}:/Google Drive/Radar Escon",
        ):
            p = Path(mid)
            if p.exists():
                return p
    return None


def _file_sig(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


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


def find_company_folder(drive_root: Path, hint: str | None, razao: str) -> Path | None:
    """Localiza pasta da empresa sob o root do Drive."""
    if not drive_root.exists():
        return None
    candidates = []
    if hint:
        candidates.append(hint)
    candidates.append(slug_drive(razao))
    candidates.append(razao)
    # listagem case-insensitive
    try:
        children = {c.name.lower(): c for c in drive_root.iterdir() if c.is_dir()}
    except OSError:
        return None
    for name in candidates:
        if not name:
            continue
        hit = children.get(name.lower())
        if hit:
            return hit
        # prefix match (CNPJ no começo do nome)
        for k, p in children.items():
            if k.startswith(name.lower()[:20]) or name.lower() in k:
                return p
    return None


def iter_source_files(
    company_dir: Path,
    *,
    subdirs: Iterable[str] = DEFAULT_SUBDIRS,
    competencia: str | None = None,
) -> list[Path]:
    files: list[Path] = []
    # se competência AAAA-MM, tenta pastas .../AAAA/MM-AAAA/
    period_parts: list[str] = []
    if competencia and len(competencia) >= 7:
        ano, mes = competencia[:4], competencia[5:7]
        period_parts = [ano, f"{mes}-{ano}"]

    for sub in subdirs:
        base = company_dir / sub
        if not base.exists():
            continue
        if period_parts:
            target = base.joinpath(*period_parts)
            search_roots = [target] if target.exists() else [base]
        else:
            search_roots = [base]
        for root in search_roots:
            for f in root.rglob("*"):
                if f.is_file() and f.suffix in EXTENSIONS:
                    files.append(f)
    # também arquivos soltos na raiz da empresa
    for f in company_dir.iterdir():
        if f.is_file() and f.suffix in EXTENSIONS:
            files.append(f)
    return files


def sync_drive_to_inbox(
    *,
    clients_dir: Path,
    inbox_root: Path,
    drive_root: Path | None = None,
    client_id: str | None = None,
    competencia: str | None = None,
    only_new: bool = True,
    subdirs: Iterable[str] = DEFAULT_SUBDIRS,
) -> dict[str, Any]:
    root = detect_drive_root(drive_root)
    if root is None:
        return {
            "success": False,
            "summary": (
                "Pasta Google Drive do Radar não encontrada. "
                "Configure GOOGLE_DRIVE_RADAR_ROOT no .env apontando para "
                "'…/Radar Escon' (Google Drive for Desktop) ou use sync-inbox (MinIO)."
            ),
            "drive_root": None,
            "clients": [],
        }

    clients = list_clients(clients_dir)
    if client_id:
        clients = [c for c in clients if c.id == client_id]
        if not clients:
            return {
                "success": False,
                "summary": f"Cliente {client_id} não encontrado no cadastro local",
                "drive_root": str(root),
            }

    state_path = inbox_root.parent / "imports" / "drive_sync_state.json"
    state = _load_state(state_path) if only_new else {}

    report_clients: list[dict] = []
    total_copied = 0
    total_skipped = 0
    missing_folders: list[str] = []

    for c in clients:
        if c.source == "demo" or (c.tags and "demo" in c.tags):
            continue
        folder = find_company_folder(root, c.drive_folder_hint, c.name)
        if not folder:
            missing_folders.append(c.name)
            continue

        dest = inbox_root / c.id
        if competencia:
            dest = dest / competencia.replace("/", "-")
        dest.mkdir(parents=True, exist_ok=True)

        files = iter_source_files(folder, subdirs=subdirs, competencia=competencia)
        copied: list[str] = []
        skipped = 0
        for src in files:
            sig = _file_sig(src)
            key = f"{c.id}:{src}"
            if only_new and state.get(key) == sig:
                skipped += 1
                continue
            # nome único se colidir
            target = dest / src.name
            if target.exists() and target.stat().st_size == src.stat().st_size:
                state[key] = sig
                skipped += 1
                continue
            if target.exists():
                h = hashlib.md5(str(src).encode()).hexdigest()[:6]
                target = dest / f"{src.stem}_{h}{src.suffix}"
            shutil.copy2(src, target)
            state[key] = sig
            copied.append(str(target))
            total_copied += 1
        total_skipped += skipped
        report_clients.append(
            {
                "client_id": c.id,
                "name": c.name,
                "drive_folder": str(folder),
                "files_seen": len(files),
                "copied": len(copied),
                "skipped": skipped,
                "dest": str(dest),
                "samples": copied[:5],
            }
        )

    if only_new:
        _save_state(state_path, state)

    summary = (
        f"Drive {root}: {total_copied} arquivo(s) copiado(s), "
        f"{total_skipped} já sincronizado(s), "
        f"{len(report_clients)} cliente(s) com pasta, "
        f"{len(missing_folders)} sem pasta no Drive"
    )
    return {
        "success": True,
        "summary": summary,
        "drive_root": str(root),
        "copied": total_copied,
        "skipped": total_skipped,
        "missing_folders": missing_folders[:30],
        "clients": report_clients,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "state_file": str(state_path) if only_new else None,
    }


def watch_hint() -> str:
    return (
        "Para inbox automática contínua: agende "
        "`python -m escon_agentes sync-drive` (Task Scheduler a cada 15–30 min) "
        "ou rode com --watch. Exige Google Drive for Desktop com a pasta "
        "'Radar Escon' espelhada localmente."
    )
