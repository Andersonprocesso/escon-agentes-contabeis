"""Anne — Tarefas, prazos e follow-ups."""

from __future__ import annotations

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import tasks as task_board


class AnneAgent(BaseAgent):
    id = AgentId.ANNE
    name = "Anne"
    role = "Secretária de Tarefas"
    system_prompt = """
Você controla tarefas, prazos e follow-ups do escritório contábil.
Liste o que está parado, o que vence e o que precisa de cobrança interna.
"""

    def run(self, task: AgentTask) -> AgentResult:
        action = (task.input.get("action") or "status").lower()

        if action == "add" or task.input.get("new_title"):
            item = task_board.add_task(
                self.settings.tasks_dir,
                task.input.get("new_title") or task.title,
                client_id=task.client_id,
                owner=task.input.get("owner", "equipe"),
                priority=task.input.get("priority", "medium"),
                due_days=int(task.input.get("due_days", 3)),
                notes=task.description,
            )
            return self.result_ok(
                f"Tarefa criada: [{item['id']}] {item['title']} (vence {item['due_at']})",
                data=item,
            )

        if action == "close" and task.input.get("task_id"):
            ok = task_board.close_task(self.settings.tasks_dir, task.input["task_id"])
            return self.result_ok(
                f"Tarefa {task.input['task_id']}: {'encerrada' if ok else 'não encontrada'}",
                data={"closed": ok},
            )

        summary = task_board.summary_board(self.settings.tasks_dir)
        stale = task_board.list_stale(self.settings.tasks_dir)

        if self.llm.available:
            summary = self.think(
                f"Priorize a fila de trabalho do escritório:\n{summary}"
            )

        return self.result_ok(
            summary,
            data={
                "stale": stale,
                "open": [t for t in task_board.load_board(self.settings.tasks_dir) if t.get("status") == "open"],
            },
            needs_human=bool(stale),
            human_prompt="Intervir nas tarefas paradas/atrasadas." if stale else None,
        )
