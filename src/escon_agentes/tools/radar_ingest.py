"""Entrega documentos ao pipeline do Radar (Rachel → Radar → Google Drive).

Em vez de subir para o Drive por fora, o anexo é entregue ao Radar do jeito
que ele já espera: `salvar_documento()` grava o binário no MinIO com a chave
determinística e faz upsert do metadado; o worker `drive.espelhar_todos`
(de hora em hora, minuto 20) leva ao Drive criando Empresa/Departamento/Ano/Mês.

Por que assim, e não upload direto:
  - o Radar já tem lock contra pastas duplicadas e passo de deduplicação;
  - `salvar_documento` é idempotente (upsert por storage_key) — reenviar não
    multiplica arquivo;
  - o espelhamento roda no servidor: não custa token nenhum.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from escon_agentes.tools import departamento_drive as dd
from escon_agentes.tools.radar_sync import DEFAULT_HOST, DEFAULT_KEY, DEFAULT_USER, _run_remote

API_CONTAINER = "radar-escon-api-1"

# Departamento (o que a gente classifica) → tipo (o que o Radar grava).
# É o inverso de DEPARTAMENTO_POR_TIPO em Radar/backend/app/services/storage.py.
# Nada no Radar faz parse por tipo — ele só roteia a pasta —, então PDF com
# tipo `nfse_xml` é seguro e cai no departamento certo.
TIPO_POR_DEPARTAMENTO = {
    dd.DEPTO_IMPOSTOS: "guia_pdf",
    dd.DEPTO_RECIBOS: "recibo_pdf",
    dd.DEPTO_NF_ENTRADA: "nfe_xml",
    dd.DEPTO_NF_SAIDA: "nfce_xml",
    dd.DEPTO_NF_SERVICO: "nfse_xml",
    dd.DEPTO_ESOCIAL: "esocial_xml",
    dd.DEPTO_ECAC: "comunicado_pdf",
    dd.DEPTO_COMPROVANTES: "comprovante_pdf",
    dd.DEPTO_SITUACAO: "sitfis_pdf",
    dd.DEPTO_EXTRATOS: "extrato",
}


def _slug_radar(texto: str) -> str:
    """Mesma função do Radar — para prever o storage_key sem gravar nada."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ._-]", "", t).strip()
    return re.sub(r"\s+", " ", t) or "sem-nome"


def prever_storage_key(empresa_nome: str, departamento: str, competencia: str, nome: str) -> str:
    ano, mes = competencia[:4], competencia[5:7]
    return f"{_slug_radar(empresa_nome)}/{departamento}/{ano}/{mes}-{ano}/{_slug_radar(nome)}"


def planejar(
    arquivos: list[Path],
    *,
    empresa_nome: str,
    radar_id: str,
    cnpj_cliente: str,
    competencia: str,
) -> list[dict[str, Any]]:
    """Classifica cada arquivo e monta o plano. Não toca em nada."""
    from escon_agentes.tools.documents import extract_text

    plano: list[dict[str, Any]] = []
    for p in arquivos:
        try:
            texto = extract_text(p)
        except Exception:  # noqa: BLE001
            texto = ""
        depto, motivo = dd.classificar(texto, cnpj_cliente=cnpj_cliente)
        tipo = TIPO_POR_DEPARTAMENTO.get(depto or "")
        plano.append(
            {
                "arquivo": str(p),
                "nome": p.name,
                "tamanho": p.stat().st_size,
                "departamento": depto,
                "motivo": motivo,
                "tipo_radar": tipo,
                "competencia": competencia,
                "empresa_nome": empresa_nome,
                "radar_id": radar_id,
                "mime": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                "storage_key_previsto": (
                    prever_storage_key(empresa_nome, depto, competencia, p.name) if depto else None
                ),
                "pronto": bool(depto and tipo and radar_id),
                "bloqueio": (
                    None
                    if depto and tipo and radar_id
                    else ("sem radar_id do cliente" if not radar_id else f"não classificado: {motivo}")
                ),
            }
        )
    return plano


def _enviar_bytes(conteudo: bytes, destino: str, *, host: str, key: Path) -> None:
    """Manda o binário por stdin do ssh — embutir no comando estoura o limite
    de linha de comando do Windows (~32 KB) em qualquer PDF real."""
    import subprocess

    cmd = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=30",
        f"{DEFAULT_USER}@{host}",
        f"cat > {shlex.quote(destino)}",
    ]
    proc = subprocess.run(cmd, input=conteudo, capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"Falha ao transferir arquivo: {proc.stderr.decode(errors='replace')[:300]}")


def enviar(item: dict[str, Any], *, host: str = DEFAULT_HOST, key: Path = DEFAULT_KEY) -> dict[str, Any]:
    """Entrega um documento chamando `salvar_documento` dentro do container."""
    conteudo = Path(item["arquivo"]).read_bytes()
    remoto = f"/tmp/escon_ingest_{abs(hash(item['arquivo'])) % 10**10}.bin"
    _enviar_bytes(conteudo, remoto, host=host, key=key)

    py = f'''
import asyncio, sys, uuid

# rodando de /tmp, o sys.path[0] é /tmp — o pacote `app` do Radar está em /code
sys.path.insert(0, "/code")

from app.services.storage import salvar_documento
from app.workers.db import worker_session

with open("/tmp/entrada.bin", "rb") as fh:
    CONTEUDO = fh.read()

async def main():
    async with worker_session() as db:
        doc = await salvar_documento(
            db,
            empresa_id=uuid.UUID({item["radar_id"]!r}),
            tipo={item["tipo_radar"]!r},
            nome_arquivo={item["nome"]!r},
            mime_type={item["mime"]!r},
            conteudo=CONTEUDO,
            competencia={item["competencia"]!r},
        )
        await db.commit()
        print("OK|" + str(doc.id) + "|" + doc.storage_key)

asyncio.run(main())
'''
    py_b64 = base64.b64encode(py.encode("utf-8")).decode("ascii")
    script = (
        f"set -e\n"
        f"docker cp {shlex.quote(remoto)} {API_CONTAINER}:/tmp/entrada.bin\n"
        f"echo {py_b64} | base64 -d > /tmp/escon_ingest.py\n"
        f"docker cp /tmp/escon_ingest.py {API_CONTAINER}:/tmp/escon_ingest.py\n"
        # -w /code: o pacote `app` do Radar vive lá; rodando de /tmp o import falha
        f"docker exec -w /code {API_CONTAINER} python /tmp/escon_ingest.py\n"
        f"rm -f {shlex.quote(remoto)} /tmp/escon_ingest.py\n"
        f"docker exec {API_CONTAINER} rm -f /tmp/entrada.bin /tmp/escon_ingest.py\n"
    )
    saida = _run_remote(script, host=host, user=DEFAULT_USER, key=key, timeout=300)
    linha = next((l for l in saida.splitlines() if l.startswith("OK|")), None)
    if not linha:
        raise RuntimeError(f"Radar não confirmou o envio: {saida.strip()[-400:]}")
    _, doc_id, storage_key = linha.split("|", 2)
    return {"documento_id": doc_id, "storage_key": storage_key}


def competencia_de(data: datetime) -> str:
    return f"{data:%Y-%m}"


ESCRITORIO_ID = "734c20df-9355-405e-85cb-b2910f44633a"


def criar_empresas_no_radar(
    empresas: list[dict[str, Any]],
    *,
    host: str = DEFAULT_HOST,
    key: Path = DEFAULT_KEY,
) -> dict[str, Any]:
    """Cria empresas no Radar usando o schema `EmpresaCreate` dele.

    Reusar o schema traz de graça a validação de dígito verificador de CNPJ/CPF
    e os defaults corretos (config_radar, monitoramento_ativo). A checagem de
    duplicidade repete a do endpoint e ainda há UniqueConstraint no banco.
    """
    payload = [
        {
            "cnpj_cpf": e["cnpj"],
            "razao_social": e["razao_social"],
            "uf": (e.get("uf") or None),
            "regime_tributario": e.get("regime_tributario"),
        }
        for e in empresas
    ]

    # A lista vai por arquivo, não embutida no script: com algumas dezenas de
    # empresas o base64 do script estoura o limite de linha de comando do Windows.
    _enviar_bytes(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "/tmp/escon_empresas.json",
        host=host,
        key=key,
    )

    py = f'''
import asyncio, json, sys, uuid
sys.path.insert(0, "/code")

from sqlalchemy import select
from app.models import Empresa
from app.schemas.empresa import EmpresaCreate
from app.workers.db import worker_session

with open("/tmp/escon_empresas.json", encoding="utf-8") as fh:
    ENTRADA = json.load(fh)
ESCRITORIO = uuid.UUID({ESCRITORIO_ID!r})

async def main():
    criadas, ignoradas, invalidas = [], [], []
    async with worker_session() as db:
        for item in ENTRADA:
            try:
                dados = EmpresaCreate(**item)
            except Exception as e:
                invalidas.append({{"cnpj": item["cnpj_cpf"], "erro": str(e)[:160]}})
                continue
            existe = await db.scalar(select(Empresa.id).where(
                Empresa.escritorio_id == ESCRITORIO,
                Empresa.cnpj_cpf == dados.cnpj_cpf,
            ))
            if existe:
                ignoradas.append(dados.cnpj_cpf)
                continue
            emp = Empresa(escritorio_id=ESCRITORIO, **dados.model_dump(exclude={{"certificado"}}))
            db.add(emp)
            await db.flush()
            criadas.append({{"cnpj": dados.cnpj_cpf, "radar_id": str(emp.id),
                             "razao_social": dados.razao_social}})
        await db.commit()
    print("RESULTADO|" + json.dumps(
        {{"criadas": criadas, "ignoradas": ignoradas, "invalidas": invalidas}}, ensure_ascii=False))

asyncio.run(main())
'''
    py_b64 = base64.b64encode(py.encode("utf-8")).decode("ascii")
    script = (
        "set -e\n"
        f"echo {py_b64} | base64 -d > /tmp/escon_empresas.py\n"
        f"docker cp /tmp/escon_empresas.json {API_CONTAINER}:/tmp/escon_empresas.json\n"
        f"docker cp /tmp/escon_empresas.py {API_CONTAINER}:/tmp/escon_empresas.py\n"
        f"docker exec -w /code {API_CONTAINER} python /tmp/escon_empresas.py\n"
        f"rm -f /tmp/escon_empresas.py /tmp/escon_empresas.json\n"
        f"docker exec {API_CONTAINER} rm -f /tmp/escon_empresas.py /tmp/escon_empresas.json\n"
    )
    saida = _run_remote(script, host=host, user=DEFAULT_USER, key=key, timeout=300)
    linha = next((l for l in saida.splitlines() if l.startswith("RESULTADO|")), None)
    if not linha:
        raise RuntimeError(f"Radar não confirmou a criação: {saida.strip()[-400:]}")
    return json.loads(linha.split("|", 1)[1])
