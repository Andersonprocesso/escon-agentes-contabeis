"""Max — Gerente de agentes e processos (orquestrador)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask, OrchestratorPlan


ROUTING_KEYWORDS: list[tuple[AgentId, list[str]]] = [
    (AgentId.XAVIER, ["xml", "nfe", "nf-e", "nfc-e", "cte", "nfs-e", "manifestação", "manifestacao"]),
    (AgentId.BILL, ["recibo", "boleto", "pdf", "documento", "captura", "danfe", "comprovante"]),
    (AgentId.JOHN, ["concilia", "ofx", "extrato banc", "divergência", "divergencia"]),
    (AgentId.GREG, ["cobr", "extrato pendente", "solicitar extrato", "falta extrato"]),
    (AgentId.BELLA, ["whatsapp", "cliente mandou", "mensagem", "atendimento"]),
    (AgentId.RACHEL, ["e-mail", "email", "caixa de entrada", "rascunho"]),
    (AgentId.ANNE, ["tarefa", "prazo", "follow-up", "follow up", "pendência", "pendencia", "atrasad"]),
    (AgentId.LUCY, ["reforma", "cbs", "ibs", "tributár", "tributar", "iva dual"]),
    (AgentId.KAREN, ["notícia", "noticia", "briefing", "mudança legal", "mudanca legal"]),
    (AgentId.PAUL, ["dre", "fluxo de caixa", "indicador", "rentabilidade", "financeiro", "margem"]),
    (AgentId.CESAR, ["certidão", "certidao", "cnd", "e-cac", "ecac", "regularidade"]),
    (AgentId.FERNANDO, ["certificado digital", "certificado a1", "certificado", "renovação de certificado", "renovacao de certificado"]),
]


class MaxAgent(BaseAgent):
    id = AgentId.MAX
    name = "Max"
    role = "Gerente de Agentes e Processos"
    system_prompt = """
Você coordena a operação multiagente do escritório contábil.
Sua função é entender a demanda, escolher os agentes certos e resumir o andamento.
Nunca execute lançamentos finais sem flag de revisão humana.
Agentes disponíveis: Bella, Rachel, Greg, John, Bill, Anne, Lucy, Karen, Paul, Cesar, Xavier, Fernando.
"""

    def run(self, task: AgentTask) -> AgentResult:
        text = task.description or task.title
        plan = self.plan(text, client_id=task.client_id)
        status_path = self._write_status(plan, task)

        # Max sozinho só planeja / reporta status
        if task.input.get("mode") == "status":
            board = self._load_recent_runs()
            summary = "Status dos processos:\n" + board
            if self.llm.available:
                summary = self.think(
                    f"Resuma o status operacional para o gestor:\n{board}",
                    context=text,
                )
            return self.result_ok(summary, data={"plan": plan.model_dump()}, artifacts=[status_path])

        return self.result_ok(
            f"Plano: {plan.reasoning}\nAgentes: {', '.join(a.value for a in plan.agents)}",
            data={"plan": plan.model_dump()},
            artifacts=[status_path],
            next_agents=plan.agents,
        )

    def plan(self, text: str, client_id: str | None = None) -> OrchestratorPlan:
        low = text.lower()
        hits: list[AgentId] = []
        for agent_id, keys in ROUTING_KEYWORDS:
            if any(k in low for k in keys):
                hits.append(agent_id)

        # Pipeline mensal
        if any(k in low for k in ("fechamento", "mensal", "rotina do mês", "rotina do mes", "pipeline")):
            hits = [
                AgentId.GREG,
                AgentId.XAVIER,
                AgentId.BILL,
                AgentId.JOHN,
                AgentId.ANNE,
                AgentId.CESAR,
            ]

        if not hits:
            # tenta LLM se disponível
            if self.llm.available:
                raw = self.think(
                    "Classifique a demanda e retorne JSON puro: "
                    '{"agents":["xavier"],"intent":"...","reasoning":"..."}\n'
                    f"Demanda: {text}"
                )
                parsed = _try_json(raw)
                if parsed and parsed.get("agents"):
                    agents = []
                    for a in parsed["agents"]:
                        try:
                            agents.append(AgentId(a.lower()))
                        except ValueError:
                            continue
                    if agents:
                        return OrchestratorPlan(
                            intent=parsed.get("intent", text[:80]),
                            agents=agents,
                            reasoning=parsed.get("reasoning", "roteado via LLM"),
                            client_id=client_id,
                        )
            hits = [AgentId.ANNE]  # fallback seguro

        # dedupe preserving order
        seen: set[AgentId] = set()
        ordered: list[AgentId] = []
        for h in hits:
            if h not in seen:
                seen.add(h)
                ordered.append(h)

        return OrchestratorPlan(
            intent=text[:120],
            agents=ordered,
            reasoning=f"Roteamento por palavras-chave → {len(ordered)} agente(s)",
            client_id=client_id,
            params=_extract_paths(text),
        )

    def _write_status(self, plan: OrchestratorPlan, task: AgentTask) -> str:
        path = self.settings.tasks_dir / f"plan_{task.id}.json"
        path.write_text(
            json.dumps(
                {
                    "task_id": task.id,
                    "plan": plan.model_dump(),
                    "title": task.title,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return str(path)

    def _load_recent_runs(self) -> str:
        files = sorted(self.settings.tasks_dir.glob("run_*.json"), reverse=True)[:10]
        if not files:
            return "Nenhuma execução registrada ainda."
        lines = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                lines.append(
                    f"- {data.get('id')} | {data.get('status')} | "
                    f"{data.get('title', '')} | agentes={data.get('agents')}"
                )
            except json.JSONDecodeError:
                continue
        return "\n".join(lines) or "Sem dados legíveis."


def _try_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _extract_paths(text: str) -> dict:
    paths = re.findall(r'[A-Za-z]:\\[^\s"\']+|/(?:[^\s"\']+)', text)
    out: dict = {}
    if paths:
        out["paths"] = paths
    return out
