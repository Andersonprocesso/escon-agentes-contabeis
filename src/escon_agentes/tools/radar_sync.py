"""Sincroniza documentos do Radar (MinIO via SSH na VPS) → data/inbox/{cliente}.

Passo 2: puxar XMLs/PDFs do MinIO do Radar para o pipeline Contmatic.
Drive do Google já espelha 100% dos docs no Radar; a fonte binária oficial é o MinIO.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from escon_agentes.tools.clients import get_client

DEFAULT_HOST = "76.13.224.42"
DEFAULT_USER = "root"
DEFAULT_KEY = Path.home() / ".ssh" / "radar_escon_vps"
DEFAULT_TIPOS = ("nfe_xml", "nfse_xml", "nfce_xml", "guia_pdf", "extrato")


def _run_remote(script: str, *, host: str, user: str, key: Path, timeout: int = 300) -> str:
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    cmd = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout=30",
        f"{user}@{host}",
        f"echo {b64} | base64 -d | bash",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"SSH falhou ({proc.returncode}): {(proc.stderr or proc.stdout or '').strip()[:800]}"
        )
    return proc.stdout


def list_docs_for_empresa(
    radar_id: str,
    *,
    competencia: str | None = None,
    tipos: tuple[str, ...] = DEFAULT_TIPOS,
    host: str = DEFAULT_HOST,
    user: str = DEFAULT_USER,
    key: Path = DEFAULT_KEY,
    limit: int = 500,
) -> list[dict[str, Any]]:
    tipos_sql = ",".join("'" + t.replace("'", "") + "'" for t in tipos)
    comp_clause = ""
    if competencia:
        comp = competencia.replace("'", "")[:7]
        comp_clause = f" AND competencia = '{comp}'"
    rid = radar_id.replace("'", "")
    sql = (
        "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM ("
        "SELECT id::text, tipo, competencia, nome_arquivo, mime_type, storage_key, tamanho_bytes "
        f"FROM documentos WHERE empresa_id = '{rid}' "
        f"AND tipo IN ({tipos_sql}){comp_clause} "
        "ORDER BY criado_em DESC "
        f"LIMIT {int(limit)}"
        ") t;"
    )
    script = f"docker exec radar-escon-db-1 psql -U radar -d radar -t -A -c \"{sql}\""
    out = _run_remote(script, host=host, user=user, key=key).strip()
    if not out:
        return []
    return json.loads(out)


def pull_storage_keys(
    items: list[dict[str, Any]],
    dest_dir: Path,
    *,
    host: str = DEFAULT_HOST,
    user: str = DEFAULT_USER,
    key: Path = DEFAULT_KEY,
) -> list[str]:
    """Baixa objetos do MinIO (via container API) e copia para dest_dir."""
    if not items:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)

    # mapa storage_key → nome local único
    mapping: list[dict[str, str]] = []
    used_names: set[str] = set()
    for it in items:
        sk = it.get("storage_key") or ""
        if not sk:
            continue
        base = Path(sk).name or "arquivo.bin"
        name = base
        n = 1
        while name.lower() in used_names:
            stem = Path(base).stem
            suf = Path(base).suffix
            name = f"{stem}_{n}{suf}"
            n += 1
        used_names.add(name.lower())
        mapping.append({"key": sk, "name": name, "tipo": it.get("tipo") or ""})

    map_b64 = base64.b64encode(json.dumps(mapping).encode()).decode()
    remote_dir = f"/tmp/escon_inbox_{os.getpid()}"

    # Script Python no host remoto (evita heredoc quebrado no docker exec)
    py_code = r'''
import json, os
from pathlib import Path
import boto3
from botocore.client import Config

mapping = json.load(open("/tmp/escon_map.json"))
out = Path("/tmp/escon_pull_out")
out.mkdir(parents=True, exist_ok=True)
endpoint = os.environ.get("S3_ENDPOINT_URL") or "http://minio:9000"
bucket = os.environ.get("S3_BUCKET") or "radar-documentos"
ak = os.environ.get("S3_ACCESS_KEY") or "minio"
sk = os.environ.get("S3_SECRET_KEY") or "minio12345"
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=ak,
    aws_secret_access_key=sk,
    config=Config(signature_version="s3v4"),
)
ok = 0
for item in mapping:
    dest = out / item["name"]
    try:
        s3.download_file(bucket, item["key"], str(dest))
        ok += 1
    except Exception as e:
        print("ERR", item["key"], type(e).__name__, e)
print("OK", ok)
'''
    py_b64 = base64.b64encode(py_code.encode()).decode()

    script = f"""
set -e
REMOTE={remote_dir}
rm -rf "$REMOTE" && mkdir -p "$REMOTE"
echo {map_b64} | base64 -d > /tmp/escon_map.json
echo {py_b64} | base64 -d > /tmp/escon_pull.py
docker cp /tmp/escon_map.json radar-escon-api-1:/tmp/escon_map.json
docker cp /tmp/escon_pull.py radar-escon-api-1:/tmp/escon_pull.py
docker exec radar-escon-api-1 rm -rf /tmp/escon_pull_out
docker exec radar-escon-api-1 mkdir -p /tmp/escon_pull_out
docker exec radar-escon-api-1 python /tmp/escon_pull.py
docker cp radar-escon-api-1:/tmp/escon_pull_out/. "$REMOTE/"
echo "REMOTE_DIR=$REMOTE"
ls -1 "$REMOTE" | wc -l
"""
    out = _run_remote(script, host=host, user=user, key=key, timeout=600)
    # log remoto (OK N / ERR ...)
    for line in out.splitlines():
        if line.strip():
            print(line)

    scp_cmd = [
        "scp",
        "-i",
        str(key),
        "-o",
        "ConnectTimeout=60",
        "-r",
        f"{user}@{host}:{remote_dir}/.",
        str(dest_dir),
    ]
    proc = subprocess.run(scp_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"scp falhou: {proc.stderr[:500]}")

    try:
        _run_remote(
            f"rm -rf {remote_dir} /tmp/escon_map.json /tmp/escon_pull.py; "
            f"docker exec radar-escon-api-1 rm -rf /tmp/escon_pull_out /tmp/escon_map.json /tmp/escon_pull.py",
            host=host,
            user=user,
            key=key,
        )
    except Exception:
        pass

    return sorted(str(p) for p in dest_dir.iterdir() if p.is_file())


def sync_client_inbox(
    client_id: str,
    *,
    clients_dir: Path,
    inbox_root: Path,
    competencia: str | None = None,
    tipos: tuple[str, ...] = DEFAULT_TIPOS,
    host: str | None = None,
    key: Path | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    client = get_client(clients_dir, client_id)
    if not client:
        raise ValueError(f"Cliente local não encontrado: {client_id}")
    if not client.radar_id:
        raise ValueError(f"Cliente {client_id} sem radar_id — rode import-radar primeiro")

    host = host or os.environ.get("RADAR_SSH_HOST", DEFAULT_HOST)
    key_path = key or Path(os.environ.get("RADAR_SSH_KEY", str(DEFAULT_KEY)))
    if not key_path.exists():
        raise FileNotFoundError(f"Chave SSH não encontrada: {key_path}")

    docs = list_docs_for_empresa(
        client.radar_id,
        competencia=competencia,
        tipos=tipos,
        host=host,
        key=key_path,
        limit=limit,
    )
    dest = inbox_root / client_id
    if competencia:
        dest = dest / competencia.replace("/", "-")
    dest.mkdir(parents=True, exist_ok=True)

    if not docs:
        return {
            "client_id": client_id,
            "radar_id": client.radar_id,
            "competencia": competencia,
            "docs_found": 0,
            "files_downloaded": 0,
            "files": [],
            "dest": str(dest),
            "summary": "Nenhum documento no Radar para os filtros.",
        }

    files = pull_storage_keys(docs, dest, host=host, key=key_path)
    by_tipo: dict[str, int] = {}
    for d in docs:
        t = d.get("tipo") or "?"
        by_tipo[t] = by_tipo.get(t, 0) + 1

    return {
        "client_id": client_id,
        "radar_id": client.radar_id,
        "name": client.name,
        "competencia": competencia,
        "docs_found": len(docs),
        "files_downloaded": len(files),
        "by_tipo": by_tipo,
        "files": files[:50],
        "dest": str(dest),
        "summary": f"{client.name}: {len(files)} arquivo(s) → {dest}",
    }


def export_empresas_via_ssh(
    dest_json: Path,
    *,
    host: str = DEFAULT_HOST,
    key: Path = DEFAULT_KEY,
) -> Path:
    script = r"""
docker exec radar-escon-db-1 psql -U radar -d radar -t -A -c "SELECT json_agg(row_to_json(t)) FROM (SELECT id::text AS radar_id, tipo_pessoa, cnpj_cpf, razao_social, regime_tributario, uf, procuracao_ok, procuracao_validade::text AS procuracao_validade, monitoramento_ativo, config_radar, criado_em::text AS criado_em FROM empresas ORDER BY razao_social) t;"
"""
    out = _run_remote(script, host=host, user=DEFAULT_USER, key=key).strip()
    m = re.search(r"\[.*\]", out, flags=re.S)
    if not m:
        raise RuntimeError("Export JSON vazio ou inválido")
    dest_json.parent.mkdir(parents=True, exist_ok=True)
    dest_json.write_text(m.group(0), encoding="utf-8")
    return dest_json
