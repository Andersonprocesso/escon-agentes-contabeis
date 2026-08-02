"""Pedro Henrique — Cadastro de Empresas (Sistema Acessórias é a fonte de verdade)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import acessorias as ac
from escon_agentes.tools import cadastro_extract as ce
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

    def cadastrar_de_documentos(
        self,
        origem: Path,
        *,
        criar: bool = False,
        usar_llm: bool = True,
    ) -> AgentResult:
        """Lê documentos (cartão CNPJ, contrato social…) e monta o cadastro.

        Regex resolve a maior parte sem gastar token; o LLM entra no máximo uma
        vez, só para os campos que sobraram. Não cadastra nada sem `criar=True`.
        """
        if not origem.exists():
            return self.result_fail(f"Caminho não encontrado: {origem}")

        arquivos = ce.coletar_arquivos(origem)
        if not arquivos:
            return self.result_fail(f"Nenhum PDF/TXT legível em {origem}")

        texto, ignorados = ce.ler_documentos(arquivos)
        if not texto.strip():
            return self.result_fail(
                f"Não consegui extrair texto de {len(arquivos)} arquivo(s) — "
                f"provavelmente é PDF escaneado (imagem), que exigiria OCR."
            )

        extracao = ce.extract_from_text(texto)
        campos: dict[str, Any] = dict(extracao["campos"])
        origem_campos = dict(extracao["origem"])
        chamadas_llm = 0

        ausentes = ce.faltando(campos)
        if ausentes and usar_llm and self.llm.available:
            bruto = self.think(ce.prompt_para_llm(texto, ausentes))
            chamadas_llm = 1
            achado = _json_do_texto(bruto) or {}
            for k, v in achado.items():
                if k in ausentes and v not in (None, "", "null"):
                    campos[k] = v
                    origem_campos[k] = "llm"

        faltam_obrigatorios = [c for c in ce.CAMPOS_OBRIGATORIOS if not campos.get(c)]
        cnpj = ce.only_digits(campos.get("cnpj"))

        # Duplicidade: não recadastrar quem já existe. Se a verificação falhar,
        # tratamos como "não sei" e bloqueamos a criação (fail-closed) — criar em
        # cima de um cadastro existente é pior do que não criar.
        ja_existe = None
        verificacao_falhou: str | None = None
        if cnpj and self.settings.acessorias_token:
            try:
                ja_existe = ac.get_company(self.settings.acessorias_token, cnpj)
            except ac.AcessoriasUnavailable as e:
                verificacao_falhou = str(e)
        elif not self.settings.acessorias_token:
            verificacao_falhou = "ACESSORIAS_TOKEN ausente"

        payload = ce.montar_payload_acessorias(campos)
        criado = None
        if criar:
            if faltam_obrigatorios:
                return self.result_fail(
                    f"Faltam campos obrigatórios: {', '.join(faltam_obrigatorios)}"
                )
            if ja_existe:
                return self.result_fail(
                    f"CNPJ {cnpj} já existe no Acessórias — alterar exige confirmação explícita."
                )
            if verificacao_falhou:
                return self.result_fail(
                    f"Não consegui confirmar se {cnpj or 'o CNPJ'} já existe no Acessórias "
                    f"({verificacao_falhou}). Não vou cadastrar sem essa checagem."
                )
            criado = ac.upsert_company(self.settings.acessorias_token, payload)

        linhas = [
            f"{len(arquivos)} arquivo(s) lido(s) · {len(campos)} campo(s) extraído(s) · "
            f"{chamadas_llm} chamada(s) de LLM",
        ]
        if ignorados:
            linhas.append(f"Sem texto (possível PDF escaneado): {', '.join(ignorados[:5])}")
        if ja_existe:
            linhas.append(f"ATENÇÃO: CNPJ {cnpj} já está cadastrado no Acessórias.")
        if verificacao_falhou:
            linhas.append(
                f"Não deu para checar duplicidade ({verificacao_falhou}) — criação bloqueada."
            )
        if faltam_obrigatorios:
            linhas.append(f"Faltam obrigatórios: {', '.join(faltam_obrigatorios)}")
        linhas.append(
            "Cadastro criado no Acessórias." if criado else "(Simulação — nada foi cadastrado.)"
        )

        pendente = (
            not criar and not faltam_obrigatorios and not ja_existe and not verificacao_falhou
        )
        return self.result_ok(
            "\n".join(linhas),
            data={
                "campos": campos,
                "origem_campos": origem_campos,
                "payload": payload,
                "faltando_obrigatorios": faltam_obrigatorios,
                "ja_existe": bool(ja_existe),
                "verificacao_falhou": verificacao_falhou,
                "chamadas_llm": chamadas_llm,
                "criado": criado,
            },
            needs_human=pendente,
            human_prompt=(
                "Revise os campos e rode com --criar para cadastrar no Acessórias."
                if pendente
                else None
            ),
        )

    def run(self, task: AgentTask) -> AgentResult:
        if task.input.get("mode") == "documentos":
            return self.cadastrar_de_documentos(
                Path(task.input["origem"]),
                criar=bool(task.input.get("criar")),
                usar_llm=bool(task.input.get("usar_llm", True)),
            )

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


def _json_do_texto(texto: str) -> dict | None:
    """O LLM às vezes embrulha o JSON em ```json ... ``` ou texto solto."""
    if not texto:
        return None
    m = re.search(r"\{.*\}", texto, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
