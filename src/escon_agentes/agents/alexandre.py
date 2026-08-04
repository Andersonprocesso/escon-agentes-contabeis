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
        # guardado para o _ler saber se a nota e de venda ou de compra
        self._cnpj_cliente = getattr(cliente, "cnpj", None) or (task.client_id or "")
        usar_llm = bool(task.input.get("usar_llm", True))
        # "caixa" ou "banco" — quem pede a competência informa como recebeu
        forma = str(task.input.get("forma_pagamento") or "banco").lower()

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
            cls = self.classificador.classificar(doc, banco=banco, forma=forma)

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
            # Os campos do Xavier sao data_emissao/valor_total — ler "data"/"valor"
            # devolvia None e mandava toda nota fiscal para pendentes.
            proprio = _so_digitos(getattr(self, "_cnpj_cliente", ""))
            emit = _so_digitos(d.emit_cnpj)
            # quem emitiu decide o lancamento: cliente emitente = venda,
            # cliente destinatario = compra.
            saida = bool(proprio) and emit == proprio
            return [
                Documento(
                    caminho=str(arq),
                    tipo="xml",
                    texto=f"{d.tipo} {d.emit_nome or ''} {d.dest_nome or ''} {d.natureza or ''}",
                    data=d.data_emissao,
                    valor=_para_float(d.valor_total),
                    extras={
                        "documento": d.tipo,
                        "sentido": "saida" if saida else "entrada",
                        "a_prazo": _tem_parcelamento(arq),
                        "emit_cnpj": emit,
                        "dest_cnpj": _so_digitos(d.dest_cnpj),
                        "numero": d.numero,
                    },
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
                extras={"tem_encargos": _tem_encargos(texto)},
            )
        ]


def _so_digitos(v: Any) -> str:
    import re as _re

    return _re.sub(r"\D", "", str(v or ""))


def _para_float(v: Any) -> float | None:
    """Converte valor de documento, respeitando cada convenção.

    XML fiscal usa ponto decimal ("20.70"); PDF e extrato em português usam
    vírgula ("1.234,56"). Tratar todo ponto como milhar transformava R$ 20,70
    em R$ 2.070,00 — cem vezes maior, em todas as notas.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    if "," in t:  # formato brasileiro: ponto é milhar, vírgula é decimal
        t = t.replace(".", "").replace(",", ".")
    # só com pontos: já é decimal (padrão dos XML), não mexe
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


def _tem_parcelamento(arq: Path) -> bool:
    """NF-e parcelada vira conta a receber, não caixa.

    O bloco <cobr><dup> traz uma tag por parcela; indPag=1 também marca prazo.
    Sem isso, uma venda em 3x entraria como se tivesse sido paga à vista.
    """
    try:
        conteudo = arq.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "<dup>" in conteudo or "<dup " in conteudo or "<indPag>1</indPag>" in conteudo


def _tem_encargos(texto: str) -> bool:
    """Duplicata paga em atraso traz juros e/ou multa no comprovante — eles
    viram receita própria, não podem se misturar ao principal."""
    baixo = texto.lower()
    return any(k in baixo for k in ("juros", "multa", "mora", "acrescimo", "acréscimo"))
