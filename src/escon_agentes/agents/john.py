"""John — Conciliação bancária."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import ofx_parser
from escon_agentes.tools.clients import client_inbox


class JohnAgent(BaseAgent):
    id = AgentId.JOHN
    name = "John"
    role = "Conciliação Bancária"
    system_prompt = """
Você auxilia na conciliação bancária: lê OFX/CSV, cruza com lançamentos e aponta divergências.
Nunca marque conciliação como final sem revisão humana.
"""

    def run(self, task: AgentTask) -> AgentResult:
        folder = self._resolve_folder(task)
        bank_file = task.input.get("bank_file")
        book_file = task.input.get("book_file")

        bank_path = Path(bank_file) if bank_file else self._find_bank(folder)
        if not bank_path or not bank_path.exists():
            return self.result_fail(
                "Extrato OFX/CSV não encontrado. Informe bank_file ou coloque .ofx na pasta do cliente."
            )

        bank = ofx_parser.load_bank_file(bank_path)
        book: list[dict] = []
        if book_file and Path(book_file).exists():
            book = json.loads(Path(book_file).read_text(encoding="utf-8"))
        else:
            # tenta book.json na pasta
            candidate = folder / "lancamentos.json"
            if candidate.exists():
                book = json.loads(candidate.read_text(encoding="utf-8"))

        report = ofx_parser.reconcile(bank, book)
        summary = ofx_parser.summary_reconcile(report)
        summary += f"\nExtrato: {bank_path} ({len(bank)} movimentos)"
        if not book:
            summary += (
                "\n⚠ Nenhum lançamento contábil informado (book_file/lancamentos.json). "
                "Listei só o extrato; forneça o livro para cruzar."
            )
            report["bank_preview"] = [
                {"date": t.date, "amount": t.amount, "memo": t.memo} for t in bank[:50]
            ]

        out = self.settings.outbox / (task.client_id or "geral") / "conciliacao.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        if self.llm.available:
            summary = self.think(
                f"Explique as divergências da conciliação para o contador:\n{summary}\n"
                f"Só no banco (amostra): {report.get('only_bank', [])[:5]}\n"
                f"Só no livro (amostra): {report.get('only_book', [])[:5]}"
            )

        return self.result_ok(
            summary,
            data=report,
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Conferir itens só no extrato / só na contabilidade.",
        )

    def _resolve_folder(self, task: AgentTask) -> Path:
        if task.input.get("folder"):
            return Path(task.input["folder"])
        if task.client_id:
            return client_inbox(self.settings.inbox, task.client_id)
        return self.settings.inbox

    def _find_bank(self, folder: Path) -> Path | None:
        if not folder.exists():
            return None
        for pattern in ("*.ofx", "*.OFX", "*.csv"):
            found = list(folder.rglob(pattern))
            if found:
                return found[0]
        return None
