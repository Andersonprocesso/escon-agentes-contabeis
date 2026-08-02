"""Pedro Henrique — Cadastro de Empresas (Sistema Acessórias é a fonte de verdade)."""

from __future__ import annotations

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import acessorias as ac
from escon_agentes.tools import cadastro_sync as cs
from escon_agentes.tools.clients import list_clients


class PedroAgent(BaseAgent):
    id = AgentId.PEDRO
    name = "Pedro Henrique"
    role = "Cadastro de Empresas"
    system_prompt = """
Você cuida do cadastro das empresas. O Sistema Acessórias é a fonte de verdade;
a partir dele você mantém o cadastro local dos agentes e (mediante confirmação)
o Radar Escon alinhados.

Regras invioláveis:
- Criar cadastro novo: pode.
- Alterar cadastro existente: só com confirmação humana explícita.
- Excluir: nunca por conta própria (a API do Acessórias nem expõe exclusão).
Você compara os sistemas em bloco, de forma determinística — não analisa
empresa por empresa nem gasta raciocínio em cada linha do cadastro.
"""

    def run(self, task: AgentTask) -> AgentResult:
        token = self.settings.acessorias_token
        usar_cache = bool(task.input.get("use_cache"))

        if usar_cache:
            rows = ac.load_snapshot(self.settings.data_dir)
            origem = "snapshot local"
            if not rows:
                return self.result_fail(
                    "Sem snapshot local do Acessórias — rode uma vez sem --cache para baixar."
                )
        else:
            if not token:
                return self.result_fail("ACESSORIAS_TOKEN ausente no .env")
            try:
                rows = ac.fetch_all_companies(token)
            except ac.AcessoriasUnavailable as e:
                rows = ac.load_snapshot(self.settings.data_dir)
                if not rows:
                    return self.result_fail(f"Acessórias indisponível e sem snapshot: {e}")
                origem = f"snapshot local (API falhou: {e})"
            else:
                ac.save_snapshot(self.settings.data_dir, rows)
                origem = "API Acessórias (ao vivo)"

        clients = list_clients(self.settings.clients_dir)
        plan = cs.build_local_plan(rows, clients)
        plan_path = cs.save_plan(self.settings.data_dir, plan)

        aplicar = bool(task.input.get("apply"))
        permitir_alteracoes = bool(task.input.get("allow_updates"))
        applied = {"created": [], "updated": []}
        if aplicar:
            applied = cs.apply_local_plan(
                plan,
                clients_dir=self.settings.clients_dir,
                inbox_root=self.settings.inbox,
                allow_updates=permitir_alteracoes,
            )

        resumo = f"Fonte: {origem} · {len(rows)} empresa(s) no Acessórias\n" + cs.summarize(plan)
        if aplicar:
            resumo += (
                f"\nAplicado: {len(applied['created'])} criada(s), "
                f"{len(applied['updated'])} alterada(s)."
            )
        else:
            resumo += "\n(Simulação — nada foi gravado. Use --aplicar para efetivar.)"

        pendente = bool(plan["to_update"]) and not permitir_alteracoes
        return self.result_ok(
            resumo,
            data={"plan": plan, "applied": applied, "total_acessorias": len(rows)},
            artifacts=[str(plan_path)],
            needs_human=pendente,
            human_prompt=(
                f"{len(plan['to_update'])} empresa(s) com divergência aguardando sua confirmação "
                f"(--aplicar --confirmar-alteracoes)."
                if pendente
                else None
            ),
        )
