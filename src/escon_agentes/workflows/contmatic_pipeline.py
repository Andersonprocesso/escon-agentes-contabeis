"""Pipeline prioritário Contmatic — motor Contabilizador (códigos reais)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from escon_agentes.config import Settings, get_settings
from escon_agentes.tools import contmatic, documents, xml_fiscal
from escon_agentes.tools.clients import client_inbox, get_client


def run_contmatic_pipeline(
    client_id: str,
    *,
    folder: str | Path | None = None,
    banco: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    1. Processa pasta com Contabilizador (XML/OFX/PDF → códigos Contmatic)
    2. Mantém índice XML + extração PDF auxiliares
    3. Checklist de revisão humana
    """
    s = settings or get_settings()
    src = Path(folder) if folder else client_inbox(s.inbox, client_id)
    out_dir = s.outbox / client_id / "contmatic"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = get_client(s.clients_dir, client_id)
    banco_alias = banco or (client.banco_principal if client else "itau") or "itau"

    report: dict[str, Any] = {
        "client_id": client_id,
        "client_name": client.name if client else None,
        "source_folder": str(src),
        "banco": banco_alias,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
        "artifacts": [],
        "needs_human": True,
        "plano_contas": "config/plano_contas.yaml (Contabilizador/Contmatic)",
    }

    if not src.exists():
        report["success"] = False
        report["summary"] = f"Pasta não encontrada: {src}"
        return report

    # --- Motor unificado Contabilizador ---
    xlsx = out_dir / f"contmatic_{client_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    engine = contmatic.processar_pasta_contmatic(
        src,
        xlsx,
        banco=banco_alias,
        empresa=client.name if client else client_id,
    )
    report["steps"].append(
        {
            "agent": "contabilizador",
            "name": "Motor Contmatic",
            "lancamentos": engine.get("lancamentos", 0),
            "detalhes": engine.get("detalhes", [])[:30],
            "banco_codigo": engine.get("banco_codigo"),
        }
    )
    if engine.get("arquivo"):
        report["artifacts"].append(engine["arquivo"])

    # --- Índices auxiliares (Xavier/Bill) ---
    docs = xml_fiscal.scan_folder(src)
    if docs:
        xml_report = xml_fiscal.organize_by_client(docs, out_dir / "xmls")
        report["steps"].append(
            {
                "agent": "xavier",
                "name": "Índice XMLs",
                "total": xml_report.get("total", 0),
                "por_tipo": xml_report.get("por_tipo", {}),
            }
        )
        if xml_report.get("report_path"):
            report["artifacts"].append(xml_report["report_path"])

    pdf_items = documents.process_folder(src)
    if pdf_items:
        pdf_path = out_dir / "documentos_extraidos.json"
        pdf_path.write_text(json.dumps(pdf_items, ensure_ascii=False, indent=2), encoding="utf-8")
        report["artifacts"].append(str(pdf_path))
        report["steps"].append(
            {
                "agent": "bill",
                "name": "Classificação PDFs",
                "total": len(pdf_items),
            }
        )

    n_lanc = int(engine.get("lancamentos") or 0)
    checklist = {
        "cliente": client_id,
        "nome": client.name if client else None,
        "total_lancamentos": n_lanc,
        "arquivo_excel": engine.get("arquivo"),
        "banco": banco_alias,
        "banco_codigo": engine.get("banco_codigo"),
        "plano": "config/plano_contas.yaml",
        "revisar": [
            "Conferir débitos/créditos com o plano de contas do cliente no Contmatic",
            "Validar valores de NF e retidos",
            "PDFs sem texto (scan) precisam de digitação manual",
            "Não importar sem revisão do contador responsável",
            "Códigos: Contabilizador Escon (ex. 1121101 Duplicatas, 4111201 Receita Serviços)",
        ],
        "docs_sem_texto": sum(1 for i in pdf_items if i.get("doc_type") == "sem_texto"),
        "xmls_erro": sum(1 for d in docs if getattr(d, "tipo", None) == "erro"),
    }
    check_path = out_dir / "checklist_revisao.json"
    check_path.write_text(json.dumps(checklist, ensure_ascii=False, indent=2), encoding="utf-8")
    report["artifacts"].append(str(check_path))
    report["checklist"] = checklist
    report["engine"] = {k: v for k, v in engine.items() if k != "detalhes"}

    report["success"] = bool(engine.get("success"))
    report["summary"] = engine.get("summary") or (
        f"Contmatic {client_id}: {n_lanc} lançamento(s)"
    )
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")

    log_path = out_dir / "ultimo_pipeline.json"
    log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report["artifacts"].append(str(log_path))
    return report
