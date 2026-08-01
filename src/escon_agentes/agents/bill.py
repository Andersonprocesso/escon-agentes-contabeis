"""Bill — Captura de documentos e recibos."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import documents
from escon_agentes.tools.clients import client_inbox


class BillAgent(BaseAgent):
    id = AgentId.BILL
    name = "Bill"
    role = "Captura de Documentos"
    system_prompt = """
Você transforma PDFs, recibos e comprovantes em dados estruturados para lançamento contábil.
Classifique o tipo (DAS, DARF, boleto, folha, etc.), extraia valor/data/CNPJ e liste o que falta digitar.
"""

    def run(self, task: AgentTask) -> AgentResult:
        folder = self._resolve_folder(task)
        items = documents.process_folder(folder)
        single = task.input.get("file")
        if single:
            p = Path(single)
            if p.exists():
                items = [documents.process_document(p).__dict__]

        if not items:
            return self.result_ok(
                f"Nenhum PDF/TXT encontrado em {folder}.",
                data={"total": 0},
            )

        out_dir = self.settings.outbox / (task.client_id or "geral")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "documentos_extraidos.json"
        out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

        by_type: dict[str, int] = {}
        for it in items:
            by_type[it["doc_type"]] = by_type.get(it["doc_type"], 0) + 1

        lines = [f"Documentos processados: {len(items)}"]
        for k, v in sorted(by_type.items()):
            lines.append(f"  - {k}: {v}")
        sem_texto = sum(1 for i in items if i["doc_type"] == "sem_texto")
        if sem_texto:
            lines.append(f"  ⚠ {sem_texto} arquivo(s) sem texto (possível scan) — revisar manualmente.")

        summary = "\n".join(lines)
        if self.llm.available:
            summary = self.think(
                f"Organize estes documentos para a equipe de lançamentos:\n{summary}\n"
                f"Amostra: {items[:5]}"
            )

        return self.result_ok(
            summary,
            data={"items": items, "por_tipo": by_type},
            artifacts=[str(out_path)],
            needs_human=True,
            human_prompt="Conferir valores extraídos e completar lançamentos.",
        )

    def _resolve_folder(self, task: AgentTask) -> Path:
        if task.input.get("folder"):
            return Path(task.input["folder"])
        if task.client_id:
            return client_inbox(self.settings.inbox, task.client_id)
        return self.settings.inbox
