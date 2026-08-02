"""Fernando Batista — Monitor de Certificados Digitais (A1)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import certificados_digitais as certs
from escon_agentes.tools import tasks as task_board
from escon_agentes.tools.clients import list_clients

WINDOW_DAYS = 15


def _load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


class FernandoAgent(BaseAgent):
    id = AgentId.FERNANDO
    name = "Fernando Batista"
    role = "Monitor de Certificados Digitais"
    system_prompt = """
Você controla os certificados digitais A1 dos clientes cadastrados no Radar Escon.
Avisa 15 dias antes do vencimento (e sinaliza com urgência os já vencidos), oferecendo a
renovação do certificado. Você prepara a mensagem/oferta — o envio real ao cliente
(WhatsApp) é feito pela Secretaria, e o e-mail (se houver) pode ser rascunhado pela Rachel.
Nunca envie mensagens você mesmo.
"""

    def run(self, task: AgentTask) -> AgentResult:
        try:
            items = certs.fetch_from_radar()
            certs.save_local(self.settings.data_dir, items)
            source = "radar (SSH ao vivo)"
        except Exception as e:  # noqa: BLE001
            items = certs.load_local(self.settings.data_dir)
            source = f"cache local (SSH falhou: {e})"
            if not items:
                return self.result_fail(
                    f"Sem dados de certificados: SSH ao Radar falhou e não há cache local. {e}"
                )

        clients = list_clients(self.settings.clients_dir)
        by_radar_id = {c.radar_id: c for c in clients if c.radar_id}
        alerts = certs.attention_list(items, clients_by_radar_id=by_radar_id, days_ahead=WINDOW_DAYS)

        avisos_path = self.settings.outbox / "certificados_avisos.jsonl"
        state_path = self.settings.outbox / "certificados_avisos_state.json"
        state = _load_state(state_path)

        offers: list[dict] = []
        new_offers = 0
        for a in alerts:
            mensagem = certs.draft_renewal_message(
                razao_social=a["razao_social"],
                valido_ate=a.get("valido_ate", ""),
                dias=a["dias"],
                office_name=self.settings.escon_office_name,
            )
            offer = {
                "radar_id": a.get("radar_id"),
                "client_id": a.get("client_id"),
                "razao_social": a["razao_social"],
                "valido_ate": a.get("valido_ate"),
                "dias": a["dias"],
                "reason": a["reason"],
                "telefone": a.get("telefone"),
                "email": a.get("email"),
                "mensagem_oferta": mensagem,
            }
            offers.append(offer)

            # dedupe: mesmo certificado (radar_id + validade) só gera tarefa/oferta uma vez;
            # se for renovado, valido_ate muda no Radar e a chave muda naturalmente.
            key = f"{a.get('radar_id')}:{a.get('valido_ate')}"
            if key in state:
                continue
            new_offers += 1
            state[key] = datetime.now().isoformat(timespec="seconds")

            with avisos_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(offer, ensure_ascii=False) + "\n")

            priority = "critical" if a["reason"] == "vencido" else "high"
            task_board.add_task(
                self.settings.tasks_dir,
                f"Certificado A1 {a['reason']}: {a['razao_social']} (valido_ate={a.get('valido_ate')})",
                client_id=a.get("client_id"),
                owner="fernando",
                priority=priority,
                due_days=1 if a["reason"] == "vencido" else max(a["dias"], 1),
                notes=mensagem,
            )

        _save_state(state_path, state)

        summary = certs.summary_certificados(items, alerts)
        summary = f"Fonte: {source}\n{summary}"
        if self.llm.available and alerts:
            summary = self.think(
                f"Monte um resumo executivo dos certificados digitais que precisam de atenção "
                f"(vencidos são urgência máxima):\n{summary}"
            )

        return self.result_ok(
            summary,
            data={"alerts": alerts, "offers": offers, "total_certificados": len(items)},
            artifacts=[str(avisos_path)] if offers else [],
            needs_human=bool(alerts),
            human_prompt=(
                "Enviar oferta de renovação aos clientes via Secretaria (WhatsApp) "
                "e/ou pedir à Rachel um rascunho de e-mail para quem tem e-mail cadastrado."
                if alerts
                else None
            ),
            next_agents=[AgentId.ANNE] if alerts else [],
        )
