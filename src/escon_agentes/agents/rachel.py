"""Rachel — Assistente de e-mail."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask


def classify_priority(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("urgente", "prazo hoje", "bloqueio", "fiscalização", "intima")):
        return "critical"
    if any(k in low for k in ("vencimento", "extrato", "certidão", "das", "darf")):
        return "high"
    return "medium"


def classify_category(text: str) -> str:
    low = text.lower()
    if "extrato" in low:
        return "documentos_bancarios"
    if any(k in low for k in ("nota", "xml", "nf")):
        return "documentos_fiscais"
    if any(k in low for k in ("boleto", "honor")):
        return "financeiro"
    if any(k in low for k in ("dúvida", "duvida", "como", "reforma")):
        return "duvidas"
    return "geral"


def default_draft_body(subject: str, office_name: str) -> str:
    return (
        f"Prezado(a),\n\n"
        f"Agradecemos o contato com a {office_name}. "
        f"Recebemos sua mensagem e daremos andamento.\n\n"
        f"Atenciosamente,\nEquipe {office_name}"
    )


class RachelAgent(BaseAgent):
    id = AgentId.RACHEL
    name = "Rachel"
    role = "Assistente de E-mail"
    system_prompt = """
Você organiza e-mails do escritório contábil: prioridade, classificação e rascunho de resposta.
Mantenha tom profissional e peça aprovação humana antes de enviar.
"""

    def run(self, task: AgentTask) -> AgentResult:
        subject = task.input.get("subject") or task.title
        body = task.input.get("body") or task.description
        priority = self._priority(subject + "\n" + body)
        category = self._category(subject + "\n" + body)

        draft = f"Assunto: Re: {subject}\n\n" + default_draft_body(
            subject, self.settings.escon_office_name
        )

        if self.llm.available:
            draft = self.think(
                f"Classificação: {category} | Prioridade: {priority}\n"
                f"Assunto: {subject}\nCorpo:\n{body}\n\n"
                f"Gere um rascunho de resposta profissional em português."
            )

        out = self.settings.outbox / "emails_rascunhos.jsonl"
        record = {
            "subject": subject,
            "priority": priority,
            "category": category,
            "draft": draft,
            "client_id": task.client_id,
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return self.result_ok(
            f"[{priority.upper()}] {category} — {subject}\n\nRascunho:\n{draft}",
            data=record,
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Revisar e enviar e-mail.",
        )

    def _priority(self, text: str) -> str:
        return classify_priority(text)

    def _category(self, text: str) -> str:
        return classify_category(text)
