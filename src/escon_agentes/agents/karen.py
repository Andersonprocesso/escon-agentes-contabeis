"""Karen — Monitora de notícias contábeis/tributárias."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask


class KarenAgent(BaseAgent):
    id = AgentId.KAREN
    name = "Karen"
    role = "Monitora de Notícias"
    system_prompt = """
Você prepara briefings curtos sobre mudanças contábeis e tributárias relevantes para o escritório.
Seja seletiva: só o que impacta operação ou clientes.
"""

    def run(self, task: AgentTask) -> AgentResult:
        notes_path = self.settings.knowledge_dir / "noticias_brutas.md"
        raw = ""
        if notes_path.exists():
            raw = notes_path.read_text(encoding="utf-8", errors="ignore")

        topic = task.description or task.title or "notícias contábeis e tributárias da semana"

        if self.llm.available:
            briefing = self.think(
                f"Prepare um briefing objetivo ({topic}).\n"
                f"Material local (pode estar vazio):\n{raw[:6000] or '(sem material local — use conhecimento geral e diga para validar fontes)'}"
            )
        else:
            briefing = self._template(topic, raw)

        out = self.settings.outbox / f"briefing_{datetime.now().strftime('%Y%m%d')}.md"
        out.write_text(briefing, encoding="utf-8")

        return self.result_ok(
            briefing,
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Validar fontes antes de repassar à equipe/clientes.",
        )

    def _template(self, topic: str, raw: str) -> str:
        return f"""# Briefing — {topic}
Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}
Escritório: {self.settings.escon_office_name}

## Destaques
1. Acompanhar publicações da RFB / Comitê Gestor do IBS sobre a Reforma Tributária.
2. Revisar prazos de obrigações acessórias do mês corrente.
3. Checar alterações de layout de NF-e/NFS-e e manuais do Simples Nacional.

## Material local
{raw[:2000] or '_Nenhum arquivo em data/knowledge/noticias_brutas.md. Cole links/notas lá para a Karen resumir._'}

## Próximos passos sugeridos
- Lucy: dúvidas de Reforma
- Cesar: impacto em certidões/regularidade
- Anne: prazos internos
"""
