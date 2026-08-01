"""Paul — Diretor financeiro / insights."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import ofx_parser
from escon_agentes.tools.clients import client_inbox


class PaulAgent(BaseAgent):
    id = AgentId.PAUL
    name = "Paul"
    role = "Diretor Financeiro"
    system_prompt = """
Você transforma dados financeiros em insights claros: fluxo de caixa, concentração de despesas,
alertas de saldo e oportunidades de organização.
Não invente números que não estejam nos arquivos.
"""

    def run(self, task: AgentTask) -> AgentResult:
        folder = self._folder(task)
        bank_path = self._find_bank(folder)
        metrics: dict = {"client_id": task.client_id}

        if bank_path:
            txns = ofx_parser.load_bank_file(bank_path)
            credits = [t for t in txns if t.amount > 0]
            debits = [t for t in txns if t.amount < 0]
            metrics.update(
                {
                    "arquivo": str(bank_path),
                    "qtd_lancamentos": len(txns),
                    "total_entradas": round(sum(t.amount for t in credits), 2),
                    "total_saidas": round(sum(t.amount for t in debits), 2),
                    "saldo_liquido_periodo": round(sum(t.amount for t in txns), 2),
                    "maiores_saidas": sorted(
                        [{"memo": t.memo, "amount": t.amount, "date": t.date} for t in debits],
                        key=lambda x: x["amount"],
                    )[:10],
                }
            )
            summary = (
                f"Fluxo do período ({bank_path.name}):\n"
                f"  Entradas: R$ {metrics['total_entradas']:,.2f}\n"
                f"  Saídas:   R$ {metrics['total_saidas']:,.2f}\n"
                f"  Líquido:  R$ {metrics['saldo_liquido_periodo']:,.2f}\n"
                f"  Movimentos: {metrics['qtd_lancamentos']}"
            ).replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            summary = (
                "Sem extrato OFX/CSV na pasta do cliente. "
                "Envie dados ou rode Greg para cobrar extratos."
            )
            metrics["warning"] = "sem_extrato"

        if self.llm.available:
            summary = self.think(
                f"Gere análise gerencial objetiva com recomendações práticas:\n"
                f"{json.dumps(metrics, ensure_ascii=False, default=str)}\n"
                f"Pedido: {task.description or task.title}"
            )

        out = self.settings.outbox / (task.client_id or "geral") / "analise_financeira.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        return self.result_ok(
            summary,
            data=metrics,
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Validar análise antes de compartilhar com o cliente.",
        )

    def _folder(self, task: AgentTask) -> Path:
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
