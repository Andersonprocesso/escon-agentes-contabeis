"""Alexandre — Lançamentos Contábeis (regras primeiro, LLM só no que sobrar)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from escon_agentes.agents.base import BaseAgent
from escon_agentes.config import PROJECT_ROOT
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import contmatic, documents
from escon_agentes.tools.classificador_lancamento import (
    Classificador,
    Classificacao,
    Documento,
)
from escon_agentes.tools.clients import get_client

EXTENSOES = {".pdf", ".xml", ".ofx", ".txt"}


class AlexandreAgent(BaseAgent):
    id = AgentId.ALEXANDRE
    name = "Alexandre"
    role = "Lançamentos Contábeis"
    system_prompt = """
Você faz os lançamentos contábeis a partir dos documentos do cliente.
As regras vêm do razão real do escritório: DAS, folha, FGTS, pró-labore,
combustível e NFS-e você já sabe de cor — não precisa raciocinar sobre eles.
Só analise o que nenhuma regra reconheceu, e sempre marque para revisão humana.
Nunca invente conta que não esteja no plano.
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.classificador = Classificador(
            PROJECT_ROOT / "config" / "regras_lancamento.yaml",
            PROJECT_ROOT / "config" / "plano_contas.yaml",
        )

    def run(self, task: AgentTask) -> AgentResult:
        pasta = self._resolve_folder(task)
        if not pasta.exists():
            return self.result_fail(f"Pasta não encontrada: {pasta}")

        arquivos = [
            p for p in sorted(pasta.rglob("*"))
            if p.is_file() and p.suffix.lower() in EXTENSOES
        ]
        if not arquivos:
            return self.result_ok(f"Nenhum documento em {pasta}.", data={"total": 0})

        cliente = get_client(self.settings.clients_dir, task.client_id) if task.client_id else None
        banco = getattr(cliente, "banco_principal", None) or "itau"
        usar_llm = bool(task.input.get("usar_llm", True))

        lancados: list[dict[str, Any]] = []
        pendentes: list[dict[str, Any]] = []
        por_regra = 0
        por_llm = 0
        chamadas_llm = 0

        # Um OFX vira vários lançamentos (um por movimento), então a leitura
        # devolve lista. Quem sabe ler cada formato é o especialista: John
        # (ofx_parser), Xavier (xml_fiscal) e Bill (documents) — o Alexandre
        # só contabiliza o que eles estruturam.
        docs: list[Documento] = []
        for arq in arquivos:
            docs.extend(self._ler(arq))

        for doc in docs:
            cls = self.classificador.classificar(doc, banco=banco)

            if cls.origem == "desconhecido" and usar_llm and self.llm.available:
                bruto = self.think(self.classificador.prompt_para_llm(doc))
                chamadas_llm += 1
                sugestao = self.classificador.aplicar_resposta_llm(bruto)
                if sugestao:
                    cls = sugestao

            registro = {
                "arquivo": Path(doc.caminho).name,
                "data": doc.data,
                "valor": doc.valor,
                "debito": cls.debito,
                "credito": cls.credito,
                "historico": cls.historico_codigo,
                "historico_texto": cls.historico_texto,
                "complemento": cls.complemento or (doc.texto[:40] or Path(doc.caminho).stem[:40]),
                "regra": cls.regra_id,
                "origem": cls.origem,
                "observacao": cls.observacao,
            }

            # sem data ou valor não dá para lançar: o documento não foi lido direito
            faltando = [c for c in ("data", "valor") if not doc.__dict__.get(c)]
            if cls.origem == "desconhecido" or faltando or not cls.debito:
                registro["motivo"] = (
                    f"faltou {', '.join(faltando)}" if faltando else cls.observacao
                )
                pendentes.append(registro)
                continue

            if cls.origem == "regra":
                por_regra += 1
            else:
                por_llm += 1
            lancados.append(registro)

        saida = self.settings.outbox / (task.client_id or "geral")
        saida.mkdir(parents=True, exist_ok=True)
        artefatos: list[str] = []

        if lancados:
            linhas = [
                {
                    "lancamento": i,
                    "data": r["data"],
                    "debito": r["debito"],
                    "credito": r["credito"],
                    "valor": r["valor"],
                    "historico": r["historico"],
                    "complemento": r["complemento"],
                    "ccdb": "",
                    "cccr": "",
                    "cnpj": "",
                }
                for i, r in enumerate(lancados, start=1)
            ]
            xlsx = saida / "lancamentos_alexandre.xlsx"
            contmatic.write_lancamentos(
                linhas, xlsx,
                empresa=getattr(cliente, "name", None),
                competencia=task.input.get("competencia"),
            )
            artefatos.append(str(xlsx))

        if pendentes:
            pend = saida / "lancamentos_pendentes.json"
            pend.write_text(
                json.dumps(pendentes, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            artefatos.append(str(pend))

        economia = (
            f"{por_regra} de {por_regra + por_llm} lançamento(s) sem consultar o modelo"
            if (por_regra + por_llm)
            else "nada lançado"
        )
        resumo = (
            f"{len(arquivos)} documento(s) lidos · {len(lancados)} lançamento(s) "
            f"({por_regra} por regra, {por_llm} pelo modelo) · "
            f"{len(pendentes)} pendente(s) · {chamadas_llm} chamada(s) de LLM.\n"
            f"Economia: {economia}."
        )
        if pendentes:
            resumo += f"\nPendentes aguardam você: {saida / 'lancamentos_pendentes.json'}"

        return self.result_ok(
            resumo,
            data={
                "lancados": lancados,
                "pendentes": pendentes,
                "por_regra": por_regra,
                "por_llm": por_llm,
                "chamadas_llm": chamadas_llm,
            },
            artifacts=artefatos,
            needs_human=True,
            human_prompt="Revise o Excel antes de importar no Contmatic.",
        )

    def _resolve_folder(self, task: AgentTask) -> Path:
        from escon_agentes.tools.clients import client_inbox

        if task.input.get("folder"):
            return Path(task.input["folder"])
        paths = task.input.get("paths") or []
        if paths:
            return Path(paths[0])
        if task.client_id:
            return client_inbox(self.settings.inbox, task.client_id)
        return self.settings.inbox

    def _ler(self, arq: Path) -> list[Documento]:
        """Delega a leitura a quem já sabe: John (OFX), Xavier (XML), Bill (PDF)."""
        suf = arq.suffix.lower()

        if suf == ".ofx":
            from escon_agentes.tools import ofx_parser

            try:
                txns = ofx_parser.load_bank_file(arq)
            except Exception:  # noqa: BLE001 — extrato corrompido não derruba o lote
                return []
            return [
                Documento(
                    caminho=str(arq),
                    tipo="ofx",
                    texto=t.memo,
                    data=t.date,
                    valor=abs(t.amount),
                    # entrada no banco = recebimento; saída = pagamento
                    e_pagamento=t.amount < 0,
                    extras={"sinal": "credito_banco" if t.amount > 0 else "debito_banco"},
                )
                for t in txns
                if t.amount
            ]

        if suf == ".xml":
            from escon_agentes.tools import xml_fiscal

            try:
                d = xml_fiscal.parse_xml_file(arq)
            except Exception:  # noqa: BLE001
                return []
            return [
                Documento(
                    caminho=str(arq),
                    tipo="xml",
                    texto=f"{getattr(d, 'tipo', '')} {getattr(d, 'emitente', '')} "
                    f"{getattr(d, 'destinatario', '')}",
                    data=getattr(d, "data", None),
                    valor=_para_float(getattr(d, "valor", None)),
                    extras={"documento": getattr(d, "tipo", "")},
                )
            ]

        texto = documents.extract_text(arq)
        if not texto.strip():
            return [Documento(caminho=str(arq), tipo="pdf", texto="")]
        extraido = documents.process_document(arq)
        return [
            Documento(
                caminho=str(arq),
                tipo="pdf",
                texto=texto[:6000],
                data=getattr(extraido, "data", None),
                valor=_para_float(getattr(extraido, "valor", None)),
                e_pagamento=_parece_pagamento(texto),
            )
        ]


def _para_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("R$", "").replace(" ", "")
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _parece_pagamento(texto: str) -> bool:
    """Comprovante pago x guia a pagar — muda o par contábil inteiro."""
    baixo = texto.lower()
    return any(
        k in baixo
        for k in ("comprovante", "pagamento efetuado", "pago em", "autenticacao", "autenticação")
    )
