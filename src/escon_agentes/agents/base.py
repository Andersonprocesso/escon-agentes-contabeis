"""Classe base dos agentes contábeis Escon."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from escon_agentes.config import Settings, get_settings
from escon_agentes.llm import LLMClient
from escon_agentes.schema import AgentId, AgentResult, AgentTask


ToolFn = Callable[..., Any]


class BaseAgent(ABC):
    id: AgentId
    name: str
    role: str
    system_prompt: str

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or LLMClient(self.settings)
        self.tools: dict[str, ToolFn] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Subclasses registram tools aqui."""

    def register_tool(self, name: str, fn: ToolFn) -> None:
        self.tools[name] = fn

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult:
        """Executa a tarefa do agente (tools + opcionalmente LLM)."""

    def think(self, user_message: str, context: str = "") -> str:
        """Consulta o LLM com o system prompt do agente."""
        system = self.system_prompt
        if context:
            system = f"{system}\n\n## Contexto operacional\n{context}"
        office = self.settings.escon_office_name
        system = (
            f"Você é {self.name}, {self.role} do escritório {office}.\n"
            f"Responda em português do Brasil, de forma objetiva e profissional.\n"
            f"Nunca invente números fiscais ou valores de impostos sem base nos dados.\n"
            f"Sempre indique quando a decisão exige revisão do contador responsável.\n\n"
            f"{system}"
        )
        return self.llm.complete(system, user_message)

    def result_ok(
        self,
        summary: str,
        data: dict | None = None,
        artifacts: list[str] | None = None,
        needs_human: bool = False,
        human_prompt: str | None = None,
        next_agents: list[AgentId] | None = None,
    ) -> AgentResult:
        return AgentResult(
            success=True,
            summary=summary,
            data=data or {},
            artifacts=artifacts or [],
            needs_human=needs_human,
            human_prompt=human_prompt,
            next_agents=next_agents or [],
        )

    def result_fail(self, summary: str, data: dict | None = None) -> AgentResult:
        return AgentResult(success=False, summary=summary, data=data or {})
