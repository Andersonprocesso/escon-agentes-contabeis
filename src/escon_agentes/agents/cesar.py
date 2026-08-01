"""Cesar — Monitor de certidões (CND)."""

from __future__ import annotations

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import certidoes
from escon_agentes.tools import tasks as task_board


class CesarAgent(BaseAgent):
    id = AgentId.CESAR
    name = "Cesar"
    role = "Monitor de Certidões (CND)"
    system_prompt = """
Você controla certidões de regularidade fiscal dos clientes (federal, estadual, municipal, FGTS, trabalhista).
Alerta vencimentos e irregularidades. A consulta automática a portais é integração futura — use o cadastro local.
"""

    def run(self, task: AgentTask) -> AgentResult:
        action = (task.input.get("action") or "status").lower()

        if action == "upsert":
            item = certidoes.upsert_certidao(
                self.settings.data_dir,
                client_id=task.client_id or task.input.get("client_id") or "desconhecido",
                tipo=task.input.get("tipo", "federal"),
                status=task.input.get("status", "regular"),
                validade=task.input.get("validade"),
                arquivo=task.input.get("arquivo"),
                observacao=task.input.get("observacao", ""),
            )
            return self.result_ok(f"Certidão atualizada: {item}", data=item)

        alerts = certidoes.attention_list(self.settings.data_dir)
        summary = certidoes.summary_certidoes(self.settings.data_dir)

        for a in alerts:
            task_board.add_task(
                self.settings.tasks_dir,
                f"CND {a.get('reason')}: {a['client_id']} / {a['tipo']}",
                client_id=a["client_id"],
                owner="cesar",
                priority="high",
                due_days=1,
                notes=str(a),
            )

        if self.llm.available:
            summary = self.think(
                f"Monte o painel de regularidade fiscal para a equipe:\n{summary}"
            )

        return self.result_ok(
            summary,
            data={"alerts": alerts, "all": certidoes.load_certidoes(self.settings.data_dir)},
            needs_human=bool(alerts),
            human_prompt="Regularizar certidões irregulares/vencidas." if alerts else None,
            next_agents=[AgentId.ANNE] if alerts else [],
        )
