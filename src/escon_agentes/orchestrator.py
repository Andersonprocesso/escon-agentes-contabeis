"""Orquestrador Max — executa planos multiagente com trilha de auditoria."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from escon_agentes.agents import create_agent
from escon_agentes.agents.max import MaxAgent
from escon_agentes.config import Settings, get_settings
from escon_agentes.llm import LLMClient
from escon_agentes.schema import AgentId, AgentResult, AgentTask, TaskStatus
from escon_agentes.tools.clients import ensure_demo_clients


class Orchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = model
        self.llm = LLMClient(self.settings, model=model)
        self.max = MaxAgent(self.settings, self.llm)
        ensure_demo_clients(self.settings.clients_dir)

    def run(
        self,
        request: str,
        *,
        client_id: str | None = None,
        agent: str | None = None,
        params: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """
        Processa um pedido em linguagem natural.
        Se `agent` for informado, pula o roteamento e executa só aquele agente.
        `model`: alias OpenRouter (kimi, gpt, gps, grok, deepseek, gemini, claude) ou id completo.
        """
        run_id = str(uuid4())[:8]
        params = dict(params or {})
        if client_id:
            params.setdefault("client_id", client_id)

        llm = self.llm.with_model(model or self.model) if (model or self.model) else self.llm
        max_agent = MaxAgent(self.settings, llm) if llm is not self.llm else self.max

        if agent:
            try:
                agents = [AgentId(agent.lower())]
            except ValueError:
                return {
                    "id": run_id,
                    "status": TaskStatus.FAILED.value,
                    "error": f"Agente desconhecido: {agent}",
                }
            reasoning = f"Agente forçado: {agent}"
        else:
            plan = max_agent.plan(request, client_id=client_id)
            agents = plan.agents
            reasoning = plan.reasoning
            for k, v in plan.params.items():
                params.setdefault(k, v)

        results: list[dict[str, Any]] = []
        needs_human: list[str] = []

        for aid in agents:
            task = AgentTask(
                agent=aid,
                title=request[:100],
                description=request,
                client_id=client_id,
                input=params,
                status=TaskStatus.RUNNING,
            )
            task.log(f"Iniciando {aid.value}")
            try:
                agent_inst = create_agent(aid, settings=self.settings, llm=llm)
                result: AgentResult = agent_inst.run(task)
                task.status = TaskStatus.WAITING_HUMAN if result.needs_human else TaskStatus.DONE
                task.output = result.model_dump()
                task.needs_human = result.needs_human
                task.human_note = result.human_prompt
                task.log("OK" if result.success else "FALHA")
            except Exception as exc:  # noqa: BLE001
                result = AgentResult(success=False, summary=f"Erro: {exc}")
                task.status = TaskStatus.FAILED
                task.log(str(exc))

            entry = {
                "agent": aid.value,
                "success": result.success,
                "summary": result.summary,
                "needs_human": result.needs_human,
                "human_prompt": result.human_prompt,
                "artifacts": result.artifacts,
                "data_keys": list(result.data.keys()),
                "task_id": task.id,
            }
            results.append(entry)
            if result.needs_human:
                needs_human.append(f"{aid.value}: {result.human_prompt or 'revisar'}")

        status = TaskStatus.WAITING_HUMAN if needs_human else TaskStatus.DONE
        model_label = llm.model_id if llm.available else "offline"
        payload = {
            "id": run_id,
            "title": request[:120],
            "client_id": client_id,
            "status": status.value,
            "reasoning": reasoning,
            "agents": [a.value for a in agents],
            "results": results,
            "needs_human": needs_human,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "llm": "online" if llm.available else "offline",
            "provider": llm.provider,
            "model": model_label,
        }

        out = self.settings.tasks_dir / f"run_{run_id}.json"
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        payload["run_file"] = str(out)
        return payload

    def status(self) -> str:
        task = AgentTask(
            agent=AgentId.MAX,
            title="Status operacional",
            description="Mostre o status dos processos",
            input={"mode": "status"},
        )
        result = self.max.run(task)
        return result.summary
