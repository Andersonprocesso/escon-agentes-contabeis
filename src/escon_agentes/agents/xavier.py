"""Xavier — XMLs fiscais."""

from __future__ import annotations

from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import contmatic, xml_fiscal
from escon_agentes.tools.clients import client_inbox


class XavierAgent(BaseAgent):
    id = AgentId.XAVIER
    name = "Xavier"
    role = "Agente de XML Fiscal"
    system_prompt = """
Você organiza e analisa XMLs fiscais (NF-e, NFC-e, CT-e, NFS-e) dos clientes do escritório.
Identifique inconsistências, agrupe por período e prepare dados para lançamento.
Sempre recomende revisão humana antes de importar no Contmatic.
"""

    def run(self, task: AgentTask) -> AgentResult:
        folder = self._resolve_folder(task)
        if not folder.exists():
            return self.result_fail(
                f"Pasta não encontrada: {folder}. "
                f"Coloque XMLs em data/inbox/{{cliente}} ou informe o caminho."
            )

        docs = xml_fiscal.scan_folder(folder)
        if not docs:
            return self.result_ok(
                f"Nenhum XML em {folder}.",
                data={"total": 0, "folder": str(folder)},
            )

        out = self.settings.outbox / (task.client_id or "geral") / "xmls"
        report = xml_fiscal.organize_by_client(docs, out)
        summary = xml_fiscal.summary_text(report)

        artifacts = [report["report_path"]]
        # rascunho Contmatic
        rows = contmatic.rows_from_xml_summary(report.get("documentos", []))
        if rows:
            xlsx = self.settings.outbox / (task.client_id or "geral") / "lancamentos_xml_rascunho.xlsx"
            contmatic.write_lancamentos(rows, xlsx)
            artifacts.append(str(xlsx))
            summary += f"\nRascunho Contmatic: {len(rows)} lançamento(s) → {xlsx}"

        if self.llm.available:
            summary = self.think(
                f"Analise este relatório de XMLs e aponte o que o contador deve revisar:\n{summary}\n"
                f"Detalhes (amostra): {report.get('documentos', [])[:5]}"
            )

        return self.result_ok(
            summary,
            data=report,
            artifacts=artifacts,
            needs_human=True,
            human_prompt="Revisar rascunho de lançamentos Contmatic antes de importar.",
            next_agents=[AgentId.BILL, AgentId.JOHN],
        )

    def _resolve_folder(self, task: AgentTask) -> Path:
        if task.input.get("folder"):
            return Path(task.input["folder"])
        paths = task.input.get("paths") or []
        if paths:
            return Path(paths[0])
        if task.client_id:
            raiz = client_inbox(self.settings.inbox, task.client_id)
            # Só a competência: senão XML de outro mês mistura no fechamento.
            comp = task.input.get("competencia")
            if comp:
                da = raiz / str(comp)
                if da.is_dir():
                    return da
            return raiz
        return self.settings.inbox
