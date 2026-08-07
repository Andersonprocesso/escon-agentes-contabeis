"""Registro de agentes especializados."""

from __future__ import annotations

from escon_agentes.agents.alexandre import AlexandreAgent
from escon_agentes.agents.anne import AnneAgent
from escon_agentes.agents.base import BaseAgent
from escon_agentes.agents.bella import BellaAgent
from escon_agentes.agents.bill import BillAgent
from escon_agentes.agents.cesar import CesarAgent
from escon_agentes.agents.clara import ClaraAgent
from escon_agentes.agents.fabiana import FabianaAgent
from escon_agentes.agents.fernando import FernandoAgent
from escon_agentes.agents.greg import GregAgent
from escon_agentes.agents.john import JohnAgent
from escon_agentes.agents.karen import KarenAgent
from escon_agentes.agents.lucy import LucyAgent
from escon_agentes.agents.max import MaxAgent
from escon_agentes.agents.paul import PaulAgent
from escon_agentes.agents.pedro import PedroAgent
from escon_agentes.agents.rachel import RachelAgent
from escon_agentes.agents.xavier import XavierAgent
from escon_agentes.schema import AgentId

AGENT_CLASSES: dict[AgentId, type[BaseAgent]] = {
    AgentId.MAX: MaxAgent,
    AgentId.BELLA: BellaAgent,
    AgentId.RACHEL: RachelAgent,
    AgentId.GREG: GregAgent,
    AgentId.JOHN: JohnAgent,
    AgentId.BILL: BillAgent,
    AgentId.ANNE: AnneAgent,
    AgentId.LUCY: LucyAgent,
    AgentId.KAREN: KarenAgent,
    AgentId.PAUL: PaulAgent,
    AgentId.CESAR: CesarAgent,
    AgentId.XAVIER: XavierAgent,
    AgentId.FERNANDO: FernandoAgent,
    AgentId.ALEXANDRE: AlexandreAgent,
    AgentId.FABIANA: FabianaAgent,
    AgentId.CLARA: ClaraAgent,
    AgentId.PEDRO: PedroAgent,
}


def create_agent(agent_id: AgentId, **kwargs) -> BaseAgent:
    cls = AGENT_CLASSES[agent_id]
    return cls(**kwargs)


def all_agent_ids() -> list[AgentId]:
    return list(AGENT_CLASSES.keys())
