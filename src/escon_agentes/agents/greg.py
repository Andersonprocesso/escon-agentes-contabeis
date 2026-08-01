"""Greg — Cobrança de extratos bancários."""

from __future__ import annotations

from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import tasks as task_board
from escon_agentes.tools.clients import client_inbox, list_clients


class GregAgent(BaseAgent):
    id = AgentId.GREG
    name = "Greg"
    role = "Cobrador de Extratos"
    system_prompt = """
Você cobra extratos bancários dos clientes de forma educada e insistente até o arquivo chegar.
Gere mensagens prontas para WhatsApp e e-mail. Não invente que o extrato chegou se não há arquivo.
"""

    def run(self, task: AgentTask) -> AgentResult:
        clients = list_clients(self.settings.clients_dir)
        if task.client_id:
            clients = [c for c in clients if c.id == task.client_id]

        pending = []
        messages = []
        for c in clients:
            folder = client_inbox(self.settings.inbox, c.id)
            has_ofx = any(folder.rglob("*.ofx")) or any(folder.rglob("*.OFX"))
            if has_ofx:
                continue
            pending.append(c.id)
            tel = c.telefone or (c.contatos or {}).get("telefone") or (c.contatos or {}).get("whatsapp")
            email = c.email or (c.contatos or {}).get("email")
            canal = "WhatsApp" if tel else ("e-mail" if email else "este canal")
            msg = (
                f"Olá! Aqui é o time da {self.settings.escon_office_name}. "
                f"Para fecharmos a contabilidade de {c.name}, "
                f"precisamos do extrato bancário (OFX ou PDF) deste mês. "
                f"Pode nos enviar por {canal}? Obrigado!"
            )
            if not tel and not email:
                msg += " ⚠ Cadastro sem telefone/e-mail — complete no painel de Clientes."
            messages.append(
                {
                    "client_id": c.id,
                    "name": c.name,
                    "telefone": tel,
                    "whatsapp": tel,
                    "email": email,
                    "message": msg,
                    "canais_ok": bool(tel or email),
                }
            )
            task_board.add_task(
                self.settings.tasks_dir,
                f"Aguardando extrato — {c.name}",
                client_id=c.id,
                owner="greg",
                priority="high",
                due_days=2,
                notes="Cobrança automática Greg",
            )

        summary = f"Clientes sem extrato OFX na inbox: {len(pending)}"
        if pending:
            summary += "\n" + "\n".join(f"  - {p}" for p in pending)
            summary += "\nMensagens de cobrança preparadas (não enviadas automaticamente)."
        else:
            summary += "\nTodos os clientes avaliados já têm OFX na pasta (ou não há clientes cadastrados)."

        if self.llm.available and messages:
            summary = self.think(
                "Refine as mensagens de cobrança mantendo tom profissional do escritório:\n"
                + "\n".join(m["message"] for m in messages[:5])
            )

        out = self.settings.outbox / "cobrancas_extrato.json"
        import json

        out.write_text(
            json.dumps({"pending": pending, "messages": messages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return self.result_ok(
            summary,
            data={"pending": pending, "messages": messages},
            artifacts=[str(out)],
            needs_human=bool(messages),
            human_prompt="Aprovar e enviar cobranças via WhatsApp/e-mail.",
            next_agents=[AgentId.ANNE, AgentId.BELLA] if messages else [],
        )
