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
    # "atrasad" sozinho pegava "contabilidade atrasada" e mandava pra Anne —
    # tarefa falsa. Só rota de prazos/tarefas genéricas.
    (AgentId.ANNE, ["tarefa", "prazo", "follow-up", "follow up", "agenda de"]),
    (AgentId.LUCY, ["reforma", "cbs", "ibs", "tributár", "tributar", "iva dual"]),
    (AgentId.KAREN, ["notícia", "noticia", "briefing", "mudança legal", "mudanca legal"]),
    (AgentId.PAUL, ["dre", "fluxo de caixa", "indicador", "rentabilidade", "financeiro", "margem"]),
    (AgentId.CESAR, ["certidão", "certidao", "cnd", "e-cac", "ecac", "regularidade"]),
    (AgentId.PEDRO, ["cadastro", "cadastrar", "acessorias", "acessórias", "nova empresa", "abrir empresa"]),
    (AgentId.FABIANA, ["folha", "holerite", "prolabore", "pró-labore", "salário", "salario", "rescis", "férias", "ferias", "13º", "13o"]),
    # "contabiliz*" é o que a equipe digita no chat. Sem isso caía no Anne.
    (AgentId.ALEXANDRE, [
        "lançamento", "lancamento", "lançar", "lancar",
        "razão", "razao", "partida dobrada",
        "débito e crédito", "debito e credito",
        "contabiliz", "contabilidade", "contábil", "contabil",
        "contmatic", "planilha de lançamento", "planilha de lancamento",
        "zerar atraso", "atrasada", "atrasado",
        "competência", "competencia",
    ]),
    (AgentId.FERNANDO, ["certificado digital", "certificado a1", "certificado", "renovação de certificado", "renovacao de certificado"]),
]

# Pedido de contabilidade do mês. Multiagente de verdade:
# cada especialista mastiga o que é dele; o Alexandre SÓ lança.
_CONTABIL_KEYS = (
    "contabiliz", "contabilidade", "contábil", "contabil", "contmatic",
    "lançamento", "lancamento", "lançar", "lancar", "zerar atraso",
    "fazer a contabilidade", "processar competência", "processar competencia",
)

# Ordem importa: leitores → folha → contábil. Max orquestra; Alexandre no fim.
PIPELINE_CONTABIL: list[AgentId] = [
    AgentId.XAVIER,   # XML fiscal estruturado
    AgentId.BILL,     # PDF/recibos estruturados
    AgentId.JOHN,     # OFX / conciliação (se houver extrato)
    AgentId.FABIANA,  # folha (se houver holerite)
    AgentId.ALEXANDRE,  # único que gera lançamento Contmatic
]


class MaxAgent(BaseAgent):
    id = AgentId.MAX
    name = "Max"
    role = "Gerente de Agentes e Processos"
    system_prompt = """
Você coordena a operação multiagente do escritório contábil.
Sua função é entender a demanda, escolher os agentes certos e resumir o andamento.
Nunca execute lançamentos finais sem flag de revisão humana.
Agentes disponíveis: Bella, Rachel, Greg, John, Bill, Anne, Lucy, Karen, Paul, Cesar, Xavier, Fernando, Pedro.
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

        # Contabilidade: equipe de especialistas → Alexandre lança.
        # Greg/Anne/Cesar NÃO entram aqui (cobrança/tarefa/certidão ≠ mastigar doc).
        if any(k in low for k in _CONTABIL_KEYS) or (
            "fechamento" in low
            and any(k in low for k in ("cont", "mês", "mes", "compet", "cliente", "contmatic"))
        ):
            hits = list(PIPELINE_CONTABIL)
        elif any(k in low for k in ("fechamento", "rotina do mês", "rotina do mes", "pipeline mensal")):
            hits = list(PIPELINE_CONTABIL)

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

        params = _extract_paths(text)
        params.update(_extract_competencia_e_forma(text))
        if ordered == list(PIPELINE_CONTABIL):
            reasoning = (
                "Pipeline contábil multiagente: Xavier (XML) → Bill (PDF) → "
                "John (OFX) → Fabiana (folha) → Alexandre (lança o que a equipe mastigou)"
            )
        else:
            reasoning = f"Roteamento por palavras-chave → {len(ordered)} agente(s)"
        return OrchestratorPlan(
            intent=text[:120],
            agents=ordered,
            reasoning=reasoning,
            client_id=client_id,
            params=params,
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
    # Só caminho Windows real (C:\...) — o padrão unix `/algo` pegava
    # "set/2024" e virava path falso.
    paths = re.findall(r'[A-Za-z]:\\[^\s"\']+', text)
    out: dict = {}
    if paths:
        out["paths"] = paths
    return out


def _extract_competencia_e_forma(text: str) -> dict:
    """Tira competência e forma de pagamento do pedido em português."""
    out: dict = {}
    low = (text or "").lower()
    # 2024-09 | 09/2024 | set/2024 | set/24 | setembro 2024
    meses = {
        "jan": "01", "janeiro": "01",
        "fev": "02", "fevereiro": "02",
        "mar": "03", "marco": "03", "março": "03",
        "abr": "04", "abril": "04",
        "mai": "05", "maio": "05",
        "jun": "06", "junho": "06",
        "jul": "07", "julho": "07",
        "ago": "08", "agosto": "08",
        "set": "09", "setembro": "09",
        "out": "10", "outubro": "10",
        "nov": "11", "novembro": "11",
        "dez": "12", "dezembro": "12",
    }
    if m := re.search(r"\b(20\d{2})-(\d{2})\b", low):
        out["competencia"] = f"{m.group(1)}-{m.group(2)}"
    elif m := re.search(r"\b(\d{2})/(\d{4})\b", low):
        out["competencia"] = f"{m.group(2)}-{m.group(1)}"
    elif m := re.search(
        r"\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|"
        r"janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|"
        r"setembro|outubro|novembro|dezembro)[a-z]*[/\-\s]+(\d{2,4})\b",
        low,
    ):
        mes = meses.get(m.group(1)[:3] if len(m.group(1)) >= 3 else m.group(1))
        if not mes:
            for k, v in meses.items():
                if m.group(1).startswith(k):
                    mes = v
                    break
        ano = m.group(2)
        if mes:
            out["competencia"] = f"{'20' + ano if len(ano) == 2 else ano}-{mes}"

    if re.search(r"\bcaixa\b", low):
        out["forma_pagamento"] = "caixa"
    elif re.search(r"\bbanco\b", low):
        out["forma_pagamento"] = "banco"
    return out
