"""Modelos de dados compartilhados."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentId(str, Enum):
    MAX = "max"
    BELLA = "bella"
    RACHEL = "rachel"
    GREG = "greg"
    JOHN = "john"
    BILL = "bill"
    ANNE = "anne"
    LUCY = "lucy"
    KAREN = "karen"
    PAUL = "paul"
    CESAR = "cesar"
    XAVIER = "xavier"
    FERNANDO = "fernando"
    ALEXANDRE = "alexandre"
    FABIANA = "fabiana"
    CLARA = "clara"  # conferência dos lançamentos (duplicatas / erros)
    PEDRO = "pedro"


class Message(BaseModel):
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    agent: AgentId
    title: str
    description: str = ""
    client_id: str | None = None
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    needs_human: bool = False
    human_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    parent_id: str | None = None
    logs: list[str] = Field(default_factory=list)

    def log(self, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {msg}")
        self.updated_at = datetime.now()


class AgentResult(BaseModel):
    success: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    needs_human: bool = False
    human_prompt: str | None = None
    next_agents: list[AgentId] = Field(default_factory=list)


class OrchestratorPlan(BaseModel):
    intent: str
    agents: list[AgentId]
    reasoning: str
    client_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ClientProfile(BaseModel):
    id: str
    name: str
    cnpj: str | None = None
    regime: str = "simples_nacional"  # simples_nacional | lucropresumido | lucroreal | mei
    banco_principal: str = "itau"
    contatos: dict[str, str] = Field(default_factory=dict)
    # Contatos diretos (também espelhados em contatos para Greg/Bella)
    telefone: str | None = None
    email: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Integração Radar Escon
    radar_id: str | None = None
    uf: str | None = None
    tipo_pessoa: str = "J"  # J | F
    # Anexo do Simples. O IV (construcao civil, limpeza, vigilancia) recolhe a
    # CPP patronal FORA do DAS, via GPS — nos demais ela ja esta no DAS.
    anexo_simples: int | None = None
    aliquota_rat: float = 0.0  # RAT ajustado pelo FAP, sai da GFIP do cliente
    procuracao_ok: bool | None = None
    monitoramento_ativo: bool | None = None
    drive_folder_hint: str | None = None  # pasta esperada no Google Drive / MinIO
    source: str | None = None  # radar | manual | demo
