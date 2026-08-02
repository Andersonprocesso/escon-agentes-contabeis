"""Reavalia e-mails antes classificados como 'não-cliente' (Rachel).

Necessário porque a classificação depende do cadastro: um e-mail lido quando o
cliente ainda não tinha e-mail cadastrado vira 'não-cliente' por engano. Quando
o Pedro sincroniza o Acessórias, esses casos precisam ser reprocessados —
senão nota fiscal de cliente fica parada como pendência genérica.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from escon_agentes.agents.rachel import classify_category, classify_priority, default_draft_body
from escon_agentes.config import Settings
from escon_agentes.tools import graph_mail as mail
from escon_agentes.tools.clients import list_clients
from escon_agentes.workflows.email_triage import (
    _safe_filename,
    _slug,
    anexo_relevante,
    pasta_mes,
)


def _carregar_nao_clientes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for linha in path.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                out.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return out


def run_email_recheck(settings: Settings, *, aplicar: bool = False) -> dict[str, Any]:
    clients = list_clients(settings.clients_dir)
    by_email = {c.email.strip().lower(): c for c in clients if c.email}

    nao_clientes_path = settings.outbox / "emails_nao_clientes.jsonl"
    registros = _carregar_nao_clientes(nao_clientes_path)

    viraram: list[dict[str, Any]] = []
    for r in registros:
        c = by_email.get((r.get("from") or "").lower())
        if c:
            viraram.append({**r, "client_id": c.id, "client_name": c.name})

    if not aplicar or not viraram:
        return {
            "success": True,
            "summary": (
                f"{len(registros)} e-mail(s) marcados como não-cliente · "
                f"{len(viraram)} agora batem com cliente cadastrado."
                + ("" if aplicar else " (Simulação — use --aplicar.)")
            ),
            "reclassificados": viraram,
            "aplicado": False,
        }

    token = mail.get_access_token(settings, interactive_ok=False)
    staging_root = settings.outbox / "email_attachments"
    processados: list[dict[str, Any]] = []
    rascunhos = 0
    anexos = 0

    for item in viraram:
        msg = mail.find_by_internet_id(token, settings, item["message_id"])
        if not msg:
            item["erro"] = "mensagem não encontrada na caixa"
            continue
        graph_id = msg["id"]
        recebido = datetime.now()
        try:
            recebido = datetime.strptime(msg["receivedDateTime"], "%Y-%m-%dT%H:%M:%SZ")
        except (KeyError, ValueError):
            pass

        salvos: list[str] = []
        if msg.get("hasAttachments"):
            ano, mes = recebido.strftime("%Y"), pasta_mes(recebido)
            dest = staging_root / item["client_id"] / ano / mes
            for nome, conteudo in mail.get_attachments(token, settings, graph_id):
                if not anexo_relevante(nome, conteudo):
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                alvo = dest / _safe_filename(Path(nome).name)
                alvo.write_bytes(conteudo)
                salvos.append(str(alvo))
                anexos += 1

        corpo = mail.get_body_text(token, settings, graph_id)
        prioridade = classify_priority(f"{item['subject']}\n{corpo}")
        categoria = classify_category(f"{item['subject']}\n{corpo}")
        mail.create_draft_reply(
            token, settings, graph_id, default_draft_body(item["subject"], settings.escon_office_name)
        )
        rascunhos += 1
        mail.unflag_message(token, settings, graph_id)  # não é mais pendência de não-cliente

        cliente = next((c for c in clients if c.id == item["client_id"]), None)
        pasta = _slug(getattr(cliente, "drive_folder_hint", None) or item["client_name"])
        registro = {
            "message_id": item["message_id"],
            "from": item["from"],
            "subject": item["subject"],
            "date": recebido.isoformat(),
            "client_id": item["client_id"],
            "priority": prioridade,
            "category": categoria,
            "attachments": salvos,
            "staged_for_drive": f"Radar Escon/{pasta}/{recebido:%Y}/{pasta_mes(recebido)}",
            "reprocessado_em": datetime.now().isoformat(timespec="seconds"),
        }
        processados.append(registro)
        with (settings.outbox / "emails_processados.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    # reescreve a lista de não-clientes sem os que foram promovidos
    promovidos = {p["message_id"] for p in processados}
    restantes = [r for r in registros if r.get("message_id") not in promovidos]
    nao_clientes_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in restantes), encoding="utf-8"
    )

    return {
        "success": True,
        "summary": (
            f"{len(processados)} e-mail(s) reclassificados como cliente · "
            f"{rascunhos} rascunho(s) criado(s) · {anexos} anexo(s) baixado(s) · "
            f"{len(restantes)} seguem como não-cliente."
        ),
        "reclassificados": processados,
        "aplicado": True,
    }
