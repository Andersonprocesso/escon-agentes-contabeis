"""Bella — Atendimento WhatsApp."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import tasks as task_board


INTENT_KEYWORDS = {
    "extrato": ["extrato", "ofx", "banco"],
    "boleto_honorario": ["boleto", "honorário", "honorario", "mensalidade"],
    "documento": ["nota", "xml", "nf-e", "envie", "envio", "documento"],
    "prazo": ["prazo", "vencimento", "das", "guia"],
    "certidao": ["certidão", "certidao", "cnd"],
    "reforma": ["reforma", "cbs", "ibs"],
    "humano": ["falar com", "atendente", "urgente", "reclam"],
}


class BellaAgent(BaseAgent):
    id = AgentId.BELLA
    name = "Bella"
    role = "Atendimento WhatsApp"
    system_prompt = """
Você atende clientes do escritório contábil pelo WhatsApp.
Classifique a intenção, responda dúvidas simples e encaminhe o restante ao setor certo.
Tom: cordial, claro, sem jargão desnecessário. Não invente prazos fiscais.
"""

    def run(self, task: AgentTask) -> AgentResult:
        message = task.input.get("message") or task.description or task.title
        intent = self._classify(message)
        draft = self._draft(message, intent)

        if self.llm.available:
            draft = self.think(
                f"Cliente escreveu:\n{message}\n\n"
                f"Intenção detectada: {intent}\n"
                f"Gere a resposta WhatsApp e diga para qual setor encaminhar."
            )

        out = self.settings.outbox / "whatsapp_rascunhos.jsonl"
        record = {
            "client_id": task.client_id,
            "intent": intent,
            "inbound": message,
            "outbound_draft": draft,
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if intent in {"extrato", "documento", "certidao", "humano"}:
            task_board.add_task(
                self.settings.tasks_dir,
                f"WhatsApp ({intent}): {message[:60]}",
                client_id=task.client_id,
                owner="atendimento",
                priority="high" if intent == "humano" else "medium",
                notes=message,
            )

        next_map = {
            "extrato": [AgentId.GREG],
            "documento": [AgentId.BILL, AgentId.XAVIER],
            "certidao": [AgentId.CESAR],
            "reforma": [AgentId.LUCY],
            "prazo": [AgentId.ANNE],
        }

        return self.result_ok(
            f"Intenção: {intent}\n\nRascunho de resposta:\n{draft}",
            data=record,
            artifacts=[str(out)],
            needs_human=intent == "humano",
            human_prompt="Assumir conversa com o cliente." if intent == "humano" else "Aprovar envio da resposta.",
            next_agents=next_map.get(intent, []),
        )

    def _classify(self, text: str) -> str:
        low = text.lower()
        for intent, keys in INTENT_KEYWORDS.items():
            if any(k in low for k in keys):
                return intent
        return "geral"

    def _draft(self, message: str, intent: str) -> str:
        office = self.settings.escon_office_name
        templates = {
            "extrato": (
                f"Olá! Aqui é a {office}. Recebemos sua mensagem. "
                f"Se puder, envie o extrato em OFX ou PDF que damos andamento no fechamento."
            ),
            "boleto_honorario": (
                f"Olá! Vamos verificar o boleto de honorários e retornamos com o PDF/linha digitável."
            ),
            "documento": (
                f"Obrigada pelo envio! Vamos organizar o documento e integrar à contabilidade do período."
            ),
            "prazo": (
                f"Olá! Vamos confirmar os prazos do seu regime e retornamos com as orientações."
            ),
            "certidao": (
                f"Certo! Vamos checar a situação das certidões e avisamos se houver pendência."
            ),
            "reforma": (
                f"Posso te explicar os pontos principais da Reforma Tributária para o seu caso. "
                f"Enquanto isso, um especialista pode detalhar o impacto no seu regime."
            ),
            "humano": (
                f"Entendi. Vou encaminhar para um atendente humano da {office} continuar com você."
            ),
            "geral": (
                f"Olá! Aqui é o atendimento da {office}. "
                f"Recebemos sua mensagem e já estamos verificando. Em breve retornamos."
            ),
        }
        return templates.get(intent, templates["geral"])
