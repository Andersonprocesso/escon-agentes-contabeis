"""Lucy — Reforma Tributária."""

from __future__ import annotations

from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask


class LucyAgent(BaseAgent):
    id = AgentId.LUCY
    name = "Lucy"
    role = "Especialista em Reforma Tributária"
    system_prompt = """
Você explica a Reforma Tributária brasileira (CBS, IBS, IS) de forma simples para clientes
e equipe do escritório. Use a base de conhecimento local quando disponível.
Deixe claro que não substitui parecer formal do contador responsável.
"""

    def run(self, task: AgentTask) -> AgentResult:
        question = task.description or task.title
        knowledge = self._load_knowledge()
        context = knowledge[:8000] if knowledge else self._builtin_brief()

        if self.llm.available:
            answer = self.think(
                f"Pergunta do usuário:\n{question}\n\nUse o material de apoio:\n{context}"
            )
        else:
            answer = (
                f"{self._builtin_brief()}\n\n"
                f"Pergunta: {question}\n"
                f"(Configure XAI_API_KEY para respostas personalizadas com o modelo.)"
            )

        out = self.settings.outbox / "lucy_respostas.md"
        with out.open("a", encoding="utf-8") as f:
            f.write(f"\n## {task.title}\n\n{answer}\n")

        return self.result_ok(
            answer,
            data={"question": question},
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Validar orientação antes de enviar ao cliente.",
        )

    def _load_knowledge(self) -> str:
        parts: list[str] = []
        kdir = self.settings.knowledge_dir
        if not kdir.exists():
            return ""
        for path in sorted(kdir.glob("**/*")):
            if path.suffix.lower() in {".md", ".txt"} and path.is_file():
                parts.append(f"# {path.name}\n{path.read_text(encoding='utf-8', errors='ignore')}")
        return "\n\n".join(parts)

    def _builtin_brief(self) -> str:
        return """
## Reforma Tributária — visão prática (resumo interno Escon)

- **CBS** (federal) e **IBS** (estados/municípios) substituem gradualmente PIS, Cofins, ICMS, ISS etc.
- **IS** (Imposto Seletivo) incide sobre produtos prejudiciais à saúde/meio ambiente.
- Empresas de **serviços** e **comércio** terão impactos diferentes de crédito e alíquota efetiva.
- **Simples Nacional** terá regras específicas de transição — não assuma alíquota de regime normal.
- Ação recomendada no escritório: mapear clientes por CNAE, regime e perfil de créditos;
  preparar comunicação clara e cronograma de adequação de sistemas (NF-e, precificação, ERP).

Sempre personalize com o regime do cliente e revise legislação atualizada antes de orientar.
""".strip()
