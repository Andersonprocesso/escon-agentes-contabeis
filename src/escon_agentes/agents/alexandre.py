"""Alexandre — Lançamentos Contábeis (regras primeiro, LLM só no que sobrar)."""

from __future__ import annotations

import json
import re
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
from escon_agentes.tools import titulos as tit

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

        # Razão auxiliar: a memória do que ficou a receber/pagar. Sem ela cada
        # competência é uma ilha e nada lembra de baixar a duplicata de janeiro
        # quando o dinheiro entra em março.
        carteira = tit.abrir_carteira(self.settings.data_dir, task.client_id or "geral")
        competencia = task.input.get("competencia")
        abertos_agora: list[dict[str, Any]] = []
        baixados_agora: list[dict[str, Any]] = []
        sem_titulo: list[dict[str, Any]] = []

        lancados: list[dict[str, Any]] = []
        pendentes: list[dict[str, Any]] = []
        # Notas que existem, estão certas, e simplesmente não viram lançamento.
        # Ficam listadas para ninguém achar que sumiram.
        nao_contabilizaveis: list[dict[str, Any]] = []
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
            if motivo := doc.extras.get("nao_lancavel"):
                nao_contabilizaveis.append({
                    "arquivo": Path(doc.caminho).name,
                    "data": doc.data,
                    "valor": doc.valor,
                    "natureza": "nao_lancavel",
                    "motivo": motivo,
                })
                continue

            # O CFOP decide ANTES da regra: remessa, retorno, transferência e a
            # NF-e que só documenta cupom já lançado não geram lançamento —
            # lançá-las inventaria compra ou dobraria receita.
            if "cfop_contabiliza" in doc.extras:
                contabiliza = doc.extras["cfop_contabiliza"]
                if contabiliza is not True:
                    item = {
                        "arquivo": Path(doc.caminho).name,
                        "data": doc.data,
                        "valor": doc.valor,
                        "cfop": doc.extras.get("cfop"),
                        "natureza": doc.extras.get("natureza_cfop"),
                        "motivo": doc.extras.get("cfop_descricao"),
                        "contraparte": doc.extras.get("contraparte"),
                    }
                    if contabiliza is False:
                        nao_contabilizaveis.append(item)
                    else:
                        # None = pode gerar lançamento, mas em conta diferente
                        # da rotina (devolução, bonificação, imobilizado).
                        pendentes.append(item)
                    continue

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

            # --- razão auxiliar ---
            if cls.abre_titulo:
                novos = self._abrir_titulos(
                    carteira, doc, cls.abre_titulo, task.client_id or "geral", competencia
                )
                if novos:
                    registro["titulos"] = [t.id for t in novos]
                    abertos_agora.extend(
                        {"id": t.id, "vencimento": t.vencimento, "valor": t.valor,
                         "contraparte": t.contraparte} for t in novos
                    )
            elif cls.baixa_titulo:
                achado, motivo = self._baixar(carteira, doc, cls.baixa_titulo)
                if achado:
                    registro["titulo_baixado"] = achado.id
                    registro["complemento"] = (
                        f"Baixa dupl. {achado.numero}/{achado.parcela} "
                        f"{achado.contraparte[:24]}".strip()
                    )
                    baixados_agora.append(
                        {"id": achado.id, "valor": doc.valor, "data": doc.data}
                    )
                else:
                    # O lançamento continua — o que não pode é a baixa passar
                    # despercebida. Fica marcado para conferência.
                    registro["observacao"] = (
                        (registro.get("observacao") or "") + f" | {motivo}"
                    ).strip(" |")
                    registro["revisar_titulo"] = motivo
                    sem_titulo.append(
                        {"arquivo": registro["arquivo"], "valor": doc.valor,
                         "data": doc.data, "motivo": motivo}
                    )
                    # Grava o ajuste: é o caso da nota lançada à vista para a
                    # qual a duplicata apareceu depois. Se ficasse só no
                    # relatório da rodada, a próxima execução não saberia.
                    carteira.registrar_ajuste(
                        motivo=motivo, documento=registro["arquivo"],
                        valor=doc.valor, data=doc.data,
                    )

            # NFS de serviço (razão Jorge): 1 doc → 2 a 4 lançamentos
            # (bruto + ISS retido + INSS retido + líquido no caixa/banco).
            multi = _expandir_nfs_servico(
                doc, cls, banco=banco, forma=forma,
                classificador=self.classificador,
            )
            if multi:
                if cls.origem == "regra":
                    por_regra += len(multi) - 1  # já contou 1 acima
                lancados.extend(multi)
            else:
                lancados.append(registro)

        carteira.salvar()

        # Despesas de contrato: existem no mês mesmo sem documento na pasta.
        # Em vários meses atrasados o boleto do honorário simplesmente não
        # está lá, e sem isso o resultado do mês sai errado para mais.
        if task.client_id and competencia:
            from escon_agentes.tools import recorrentes

            for rec in recorrentes.lancamentos_da_competencia(
                self.settings.data_dir, task.client_id, competencia
            ):
                if any(l.get("regra") == rec["regra"] for l in lancados):
                    continue  # já lançada nesta rodada
                lancados.append(rec)
                por_regra += 1

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

        if nao_contabilizaveis:
            from collections import Counter

            tipos = Counter(x["natureza"] for x in nao_contabilizaveis)
            resumo += (
                f"\n{len(nao_contabilizaveis)} documento(s) não geram lançamento: "
                + ", ".join(f"{n} {t}" for t, n in tipos.most_common())
            )
            arq = saida / "notas_sem_lancamento.json"
            arq.write_text(
                json.dumps(nao_contabilizaveis, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            artefatos.append(str(arq))

        # O que ficou a receber/pagar não pode sumir no fim do processamento:
        # é justamente o que a competência isolada perdia.
        r = carteira.resumo()
        if abertos_agora or baixados_agora or r["total_titulos"]:
            resumo += (
                f"\n\nRazão auxiliar: {len(abertos_agora)} título(s) aberto(s), "
                f"{len(baixados_agora)} baixado(s).\n"
                f"  Em aberto: {r['a_receber_aberto']} a receber "
                f"(R$ {r['a_receber_saldo']:,.2f}) · "
                f"{r['a_pagar_aberto']} a pagar (R$ {r['a_pagar_saldo']:,.2f})"
            )
            if r["vencidos"]:
                resumo += (
                    f"\n  VENCIDOS: {r['vencidos']} título(s), "
                    f"R$ {r['vencidos_saldo']:,.2f}"
                )
        if sem_titulo:
            resumo += (
                f"\n  {len(sem_titulo)} baixa(s) sem título correspondente — "
                "confira antes de importar."
            )

        return self.result_ok(
            resumo,
            data={
                "lancados": lancados,
                "pendentes": pendentes,
                "nao_contabilizaveis": nao_contabilizaveis,
                "por_regra": por_regra,
                "por_llm": por_llm,
                "chamadas_llm": chamadas_llm,
                "titulos": {
                    "abertos": abertos_agora,
                    "baixados": baixados_agora,
                    "sem_correspondencia": sem_titulo,
                    "resumo": r,
                    "em_aberto": [
                        {"id": t.id, "tipo": t.tipo, "numero": t.numero,
                         "parcela": t.parcela, "vencimento": t.vencimento,
                         "saldo": t.saldo, "contraparte": t.contraparte,
                         "atraso_dias": t.vencido_em()}
                        for t in carteira.em_aberto()
                    ],
                },
            },
            artifacts=artefatos,
            needs_human=True,
            human_prompt="Revise o Excel antes de importar no Contmatic.",
        )

    # ------------------------------------------------------- razão auxiliar

    def _abrir_titulos(
        self, carteira: tit.Carteira, doc: Documento, tipo: str,
        cliente: str, competencia: str | None,
    ) -> list[tit.Titulo]:
        """Uma parcela = um título. O vencimento vem da nota quando existe.

        A NF-e já traz `<cobr><dup>` com número, vencimento e valor de cada
        parcela — informação que estava na nota e ninguém usava. Só quando ela
        falta é que o prazo é presumido, e aí o título fica marcado como tal.
        """
        if not doc.valor:
            return []
        numero = str(doc.extras.get("numero") or Path(doc.caminho).stem)[:20]
        parcelas = tit.ler_duplicatas(Path(doc.caminho)) if doc.tipo == "xml" else []
        if not parcelas:
            parcelas = tit.parcelas_presumidas(doc.valor, doc.data)
        conta = "1121101" if tipo == tit.RECEBER else "2121101"

        novos = []
        for p in parcelas:
            t = tit.Titulo(
                id=tit.montar_id(cliente, tipo, numero, str(p["parcela"])),
                tipo=tipo,
                numero=numero,
                parcela=str(p["parcela"]),
                parcelas=len(parcelas),
                contraparte=str(doc.extras.get("contraparte") or "")[:60],
                cnpj=str(doc.extras.get("contraparte_cnpj") or ""),
                emissao=doc.data,
                vencimento=p.get("vencimento"),
                valor=float(p["valor"]),
                conta=conta,
                origem=Path(doc.caminho).name,
                competencia=competencia,
                presumido=bool(p.get("presumido")),
            )
            if carteira.registrar(t):
                novos.append(t)
        return novos

    def _baixar(
        self, carteira: tit.Carteira, doc: Documento, tipo: str
    ) -> tuple[tit.Titulo | None, str]:
        """Procura o título que este pagamento liquida.

        Na dúvida NÃO baixa: se dois títulos abertos têm o mesmo valor, quem
        escolhe é a pessoa. Baixar o errado deixa o saldo total certo e a conta
        do cliente errada — o tipo de erro que ninguém enxerga no balancete.
        """
        if not doc.valor:
            return None, "sem valor para casar com título"
        cands = carteira.candidatos(tipo=tipo, valor=doc.valor, data=doc.data)
        if not cands:
            abertos = len(carteira.em_aberto(tipo))
            return None, (
                f"nenhum título de R$ {doc.valor:,.2f} em aberto "
                f"({abertos} título(s) na carteira)"
            )
        if carteira.ambiguo(cands, doc.valor, doc.data):
            ids = ", ".join(f"{c.numero}/{c.parcela}" for c in cands[:3])
            return None, f"{len(cands)} títulos indistinguíveis ({ids}) — escolha qual baixar"
        alvo = cands[0]
        carteira.baixar(
            alvo.id, valor=doc.valor, data=doc.data or "",
            documento=Path(doc.caminho).name,
        )
        return alvo, ""

    def _resolve_folder(self, task: AgentTask) -> Path:
        from escon_agentes.tools.clients import client_inbox

        if task.input.get("folder"):
            return Path(task.input["folder"])
        paths = task.input.get("paths") or []
        if paths:
            return Path(paths[0])
        if task.client_id:
            raiz = client_inbox(self.settings.inbox, task.client_id)
            # Com competência informada, ler só a pasta dela. A raiz do cliente
            # acumula o que a Raquel foi baixando do Drive: pedir jan/21 e varrer
            # tudo trouxe notas de 2026 para dentro da competência de 2021.
            comp = task.input.get("competencia")
            if comp:
                da_comp = raiz / str(comp)
                if da_comp.is_dir():
                    return da_comp
            return raiz
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

            # eSocial não é documento fiscal: evtRemun, evtPgtos e
            # evtFechaEvPer são eventos da folha. Vinham como "nota sem CFOP"
            # e enchiam os pendentes — 13 dos 17 em set/2024 da Alumax.
            if esocial := _e_esocial(arq):
                return [Documento(caminho=str(arq), tipo="xml", texto="",
                                  extras={"nao_lancavel": esocial})]

            try:
                d = xml_fiscal.parse_xml_file(arq)
            except Exception:  # noqa: BLE001
                return []
            # Os campos do Xavier sao data_emissao/valor_total — ler "data"/"valor"
            # devolvia None e mandava toda nota fiscal para pendentes.
            from escon_agentes.tools import cfop as cfop_tool

            proprio = _so_digitos(getattr(self, "_cnpj_cliente", ""))
            emit = _so_digitos(d.emit_cnpj)
            # quem emitiu decide o lancamento: cliente emitente = venda,
            # cliente destinatario = compra.
            saida = bool(proprio) and emit == proprio
            # O CFOP diz o que a operacao realmente e. Sem ele, remessa,
            # devolucao e bonificacao viravam compra — pareciam iguais olhando
            # so emitente e valor.
            info = cfop_tool.resumir(d.cfops, "saida" if saida else "entrada")
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
                        "a_prazo": _e_a_prazo(arq),
                        "emit_cnpj": emit,
                        "dest_cnpj": _so_digitos(d.dest_cnpj),
                        "numero": d.numero,
                        # quem deve / a quem se deve, para o razão auxiliar
                        "contraparte": (d.dest_nome if saida else d.emit_nome) or "",
                        "contraparte_cnpj": _so_digitos(
                            d.dest_cnpj if saida else d.emit_cnpj
                        ),
                        "cfop": info.codigo,
                        "natureza_cfop": info.natureza,
                        "cfop_contabiliza": info.contabiliza,
                        "cfop_descricao": info.descricao,
                        # retenções (NFS-e) — multi-linha no razão Jorge
                        "iss_retido": d.iss_retido,
                        "inss_retido": d.inss_retido,
                        "valor_liquido": d.valor_liquido,
                    },
                )
            ]

        texto = documents.extract_text(arq)

        # Relatório, protocolo e declaração não viram lançamento — e a folha
        # tem agente próprio. Marcar aqui evita que virem "pendente", que é
        # onde deve ficar só o que realmente falta decidir.
        #
        # Vem ANTES do teste de texto vazio: o Balancete de set/2024 da Alumax
        # não devolveu texto extraível e escapava por aqui, indo para pendentes
        # como "faltou data, valor" — sendo que o nome do arquivo já bastava.
        motivo = _nao_lancavel(texto, arq.name)
        alvo = _sem_acento(f"{arq.name} {texto[:2500]}")
        if not motivo and any(k in alvo for k in DA_FABIANA):
            motivo = "Folha de pagamento — quem lança é a Fabiana"

        if not texto.strip():
            return [
                Documento(
                    caminho=str(arq), tipo="pdf", texto="",
                    extras={"nao_lancavel": motivo} if motivo else {},
                )
            ]

        extraido = documents.process_document(arq)
        extras_pdf: dict[str, Any] = {
            "tem_encargos": _tem_encargos(texto),
            **({"nao_lancavel": motivo} if motivo else {}),
        }
        data_doc = getattr(extraido, "data", None)
        valor_doc = _para_float(getattr(extraido, "valor", None))

        # NFS-e municipal impressa (SJC etc.) — layout com bloco RETENÇÕES
        nfse_pdf = _parse_nfse_pdf(texto, self._cnpj_cliente if hasattr(self, "_cnpj_cliente") else "")
        if nfse_pdf:
            extras_pdf.update(nfse_pdf["extras"])
            data_doc = data_doc or nfse_pdf.get("data")
            valor_doc = valor_doc or nfse_pdf.get("valor")
        else:
            iss_pdf, inss_pdf = _retencoes_do_texto(texto)
            if iss_pdf or inss_pdf:
                extras_pdf["iss_retido"] = iss_pdf
                extras_pdf["inss_retido"] = inss_pdf
                extras_pdf["documento"] = "nfse"
                extras_pdf["sentido"] = "saida"

        return [
            Documento(
                caminho=str(arq),
                tipo="pdf",
                texto=texto[:6000],
                data=data_doc,
                valor=valor_doc,
                e_pagamento=_parece_pagamento(texto),
                extras=extras_pdf,
            )
        ]


def _so_digitos(v: Any) -> str:
    return re.sub(r"\D", "", str(v or ""))


_RE_MONEY = r"([\d.]+,\d{2})"


def _parse_nfse_pdf(texto: str, cnpj_cliente: str = "") -> dict[str, Any] | None:
    """NFS-e da prefeitura (São José dos Campos e layout parecido).

    Exemplo real 026.pdf Jorge:
      RETENÇÕES
      ISSQN (R$) IRRF ... INSS (R$) ...
      505,57 0,00 0,00 0,00 1.317,84 0,00 0,00
      Valor Serviço 11.980,35 · Valor Líquido ...
    """
    if not texto:
        return None
    up = _sem_acento(texto)
    if "nota fiscal de servicos eletronica" not in up and "nfs-e" not in up:
        return None

    # número: "01/2021 26 / E" ou "Número ... 26 / E"
    numero = None
    m_num = re.search(
        r"(?:competencia da nfs-e\s+)?numero[^\n]{0,40}?(\d{1,6})\s*/\s*[A-Z]",
        up,
        re.I,
    )
    if not m_num:
        m_num = re.search(r"\b(\d{1,6})\s*/\s*E\b", texto)
    if m_num:
        numero = m_num.group(1)

    # data emissão no topo: 04/01/2021 17:35:48
    data = None
    m_data = re.search(r"\b(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}", texto)
    if m_data:
        d, m, a = m_data.group(1).split("/")
        data = f"{a}-{m}-{d}"

    # valor do serviço (bruto)
    valor = None
    m_vs = re.search(
        r"Valor\s+Servi[cç]o[^\d]{0,40}" + _RE_MONEY,
        texto,
        re.I,
    )
    if m_vs:
        valor = _para_float(m_vs.group(1))
    if not valor:
        m_vs2 = re.search(
            r"C[AÁ]LCULO DO ISSQN\s*\n[^\d]*" + _RE_MONEY,
            texto,
            re.I,
        )
        if m_vs2:
            valor = _para_float(m_vs2.group(1))

    # bloco RETENÇÕES: 7 valores — ISSQN, IRRF, PIS, COFINS, INSS, CSLL, Outras
    iss = inss = None
    m_ret = re.search(
        r"RETEN[CÇ][OÕ]ES\s*\n[^\n]*\n\s*"
        + r"\s+".join([_RE_MONEY] * 7),
        texto,
        re.I,
    )
    if m_ret:
        vals = [_para_float(m_ret.group(i)) or 0.0 for i in range(1, 8)]
        iss = vals[0] if vals[0] > 0 else None
        inss = vals[4] if vals[4] > 0 else None

    # fallback texto "ISS Retido" (razão antigo / outros municípios)
    if not iss and not inss:
        iss, inss = _retencoes_do_texto(texto)

    liquido = None
    # Linha do total: Base | Retenções | Descontos | Valor Líquido
    m_tot = re.search(
        r"VALOR\s+TOTAL\s+DA\s+NOTA.*?"
        + _RE_MONEY
        + r"\s+"
        + _RE_MONEY
        + r"\s+"
        + _RE_MONEY
        + r"\s+"
        + _RE_MONEY,
        texto,
        re.I | re.S,
    )
    if m_tot:
        liquido = _para_float(m_tot.group(4))
    if liquido is None:
        m_liq = re.search(
            r"Valor\s+L[ií]quido\s*\(R\$\)[^\d\n]{0,10}" + _RE_MONEY, texto, re.I
        )
        if m_liq:
            liquido = _para_float(m_liq.group(1))

    # tomador (contraparte) — bloco TOMADOR DO SERVIÇO → Nome/Razão Social
    contraparte = ""
    m_tom = re.search(
        r"TOMADOR DO SERVI[CÇ]O.*?Nome/Raz[aã]o Social:\s*E-mail:\s*\n([^\n]+)",
        texto,
        re.I | re.S,
    )
    if m_tom:
        contraparte = m_tom.group(1).strip()
        # às vezes o e-mail cola na mesma linha
        contraparte = re.split(r"\s+\S+@\S+", contraparte)[0].strip()

    # emitente = prestador? Se o CNPJ do emitente é o cliente → saída (prestou)
    sentido = "saida"
    m_emit = re.search(
        r"EMITENTE DA NFS-e.*?CPF/CNPJ:\s*Inscri[^\n]*\n\s*([\d./-]+)",
        texto,
        re.I | re.S,
    )
    if m_emit and cnpj_cliente:
        if _so_digitos(m_emit.group(1)) != _so_digitos(cnpj_cliente):
            sentido = "entrada"  # cliente tomou serviço de terceiros

    return {
        "data": data,
        "valor": valor,
        "extras": {
            "documento": "nfse",
            "sentido": sentido,
            "numero": numero or "",
            "contraparte": contraparte,
            "iss_retido": iss,
            "inss_retido": inss,
            "valor_liquido": liquido,
            "nfse_pdf": True,
        },
    }


def _retencoes_do_texto(texto: str) -> tuple[float | None, float | None]:
    """ISS/INSS retidos no PDF (texto livre / razão / outros layouts).

    Padrão do Diário Jorge: 'NF 008 ISS Retido na Fonte 351,36'.
    """
    if not texto:
        return None, None
    iss = inss = None
    m_iss = re.search(
        r"ISS\s*Retid[oa]\s*(?:na\s*Fonte)?[^\d]{0,20}R?\$?\s*([\d.]+,\d{2}|\d+\.\d{2})",
        texto,
        re.I,
    )
    if m_iss:
        iss = _para_float(m_iss.group(1))
    m_inss = re.search(
        r"INSS\s*Retid[oa]\s*(?:na\s*Fonte)?[^\d]{0,20}R?\$?\s*([\d.]+,\d{2}|\d+\.\d{2})",
        texto,
        re.I,
    )
    if m_inss:
        inss = _para_float(m_inss.group(1))
    return iss, inss


def _expandir_nfs_servico(
    doc: Documento,
    cls: Classificacao,
    *,
    banco: str | None,
    forma: str,
    classificador: Classificador,
) -> list[dict[str, Any]] | None:
    """Multi-linha de NFS prestada — copiado do razão do Jorge (Premovale etc.).

        D 1121102 / C 4111201   valor total (Clientes Diversos × Receita)
        D 4121303 / C 1121102   ISS retido (se houver)
        D 1131910 / C 1121102   INSS retido a compensar (se houver)
        D @recebimento / C 1121102  líquido (caixa ou banco) — só à vista

    Devolve None se o documento não for NFS de serviço prestado.
    """
    ex = doc.extras or {}
    regra = (cls.regra_id or "").lower()
    eh_servico = (
        ex.get("documento") == "nfse"
        and ex.get("sentido") == "saida"
    ) or regra.startswith("servico")
    # PDF com retenções marcadas no texto
    if not eh_servico and (ex.get("iss_retido") or ex.get("inss_retido")):
        eh_servico = True
    if not eh_servico:
        return None

    bruto = float(doc.valor or 0)
    if bruto <= 0:
        return None

    iss = float(ex.get("iss_retido") or 0) or 0.0
    inss = float(ex.get("inss_retido") or 0) or 0.0
    liq_doc = ex.get("valor_liquido")
    try:
        liquido = float(liq_doc) if liq_doc not in (None, "") else None
    except (TypeError, ValueError):
        liquido = None
    if liquido is None:
        liquido = round(bruto - iss - inss, 2)
    if liquido < 0:
        liquido = 0.0

    contas = classificador.contas
    clientes = str(contas.get("clientes_diversos") or "1121102")
    receita = str(contas.get("receita_servicos") or "4111201")
    c_iss = str(contas.get("iss_retido") or "4121303")
    c_inss = str(contas.get("inss_retido_fonte") or "1131910")
    receb = classificador._resolver("@recebimento", banco, forma)

    num = str(ex.get("numero") or "").strip() or Path(doc.caminho).stem[:12]
    quem = (ex.get("contraparte") or "").strip()
    base_comp = f"NFS {num}" + (f" {quem}" if quem else "")
    arq = Path(doc.caminho).name
    data = doc.data
    a_prazo = bool(ex.get("a_prazo"))

    def linha(deb: str, cred: str, valor: float, hist: int, comp: str, regra_id: str) -> dict[str, Any]:
        return {
            "arquivo": arq,
            "data": data,
            "valor": round(float(valor), 2),
            "debito": deb,
            "credito": cred,
            "historico": hist,
            "historico_texto": classificador.historicos.get(hist, "") if hist else "",
            "complemento": comp[:120],
            "regra": regra_id,
            "origem": cls.origem,
            "observacao": "multi-linha NFS (razão Jorge)",
        }

    out: list[dict[str, Any]] = [
        linha(clientes, receita, bruto, 9, base_comp.strip(), "servico_prestado_bruto"),
    ]
    if iss > 0:
        out.append(
            linha(c_iss, clientes, iss, 0, f"NFS {num} ISS Retido na Fonte", "servico_iss_retido")
        )
    if inss > 0:
        out.append(
            linha(
                c_inss, clientes, inss, 34,
                f"NFS {num} INSS Retido na Fonte", "servico_inss_retido",
            )
        )
    # À vista: zera Clientes Diversos no caixa/banco. A prazo: deixa em aberto
    # (abre_titulo no classificador) — o líquido entra quando o extrato baixar.
    if not a_prazo and liquido > 0 and receb:
        out.append(
            linha(
                receb, clientes, liquido, 26,
                f"Valor ref: a NFS {num}", "servico_recebimento",
            )
        )
    return out


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


# Documentos que aparecem na pasta do cliente e NÃO são lançamento nenhum:
# relatórios, protocolos, declarações, o próprio balancete. Numa competência
# atrasada eles enchiam a lista de pendentes e escondiam o que era de verdade.
# Cada chave é comparada com o texto E com o nome do arquivo.
NAO_LANCAVEIS: list[tuple[tuple[str, ...], str]] = [
    (("balancete", "balanco patrimonial", "demonstracao do resultado",
      "demonstrativo do resultado"),
     "Relatório contábil — é resultado da contabilidade, não documento dela"),
    # O DANFE é a representação impressa da NF-e: a nota já entra pelo XML.
    # Lançar os dois duplica. Na Alumax de jan/21 eram 43 lançamentos a mais —
    # e passavam despercebidos porque cada um, sozinho, parecia correto.
    (("documento auxiliar da nota fiscal", "danfe",
      "recebemos de", "os produtos e/ou servicos constantes da nota fiscal"),
     "DANFE — a nota já é lançada pelo XML; lançar o PDF duplicaria"),
    (("protocolo de transmissao", "protocolo de entrega", "protocolo de envio",
      "recibo de entrega de arquivo", "comprovante de transmissao",
      "conectividade social", "procuracao eletronica",
      # nome de arquivo curto comum no OneDrive
      "protocolo.pdf", "protocolo "),
     "Protocolo de transmissão — não movimenta conta"),
    (("notas emitidas", "relatorio de notas", "relacao de notas",
      "listagem de notas", "espelho de nota", "relatorionotasemitidas"),
     "Relatório de notas — as notas em si já são lidas"),
    (("sedif", "gia ", "sintegra", "efd icms", "sped fiscal", "efd contribuicoes"),
     "Declaração acessória — obrigação, não lançamento"),
    (("livro razao", "razao analitico", "livro diario"),
     "Livro contábil — saída da contabilidade, não entrada"),
    (("cartao cnpj", "comprovante de inscricao", "contrato social",
      "certidao negativa", "consulta de optantes"),
     "Documento cadastral — sem efeito contábil"),
    # Pedido Anderson 2026-08-07: planilha de medição, relatório de receita e
    # relatório de GPS não têm informação contábil para lançar.
    (("planilha de medicao", "planilha medicao", "medicao de obra",
      "boletim de medicao", "relacao de medicao"),
     "Planilha/boletim de medição — controle de obra, não lançamento"),
    (("relatorio da receita", "relatorio de receita", "resumo da receita",
      "demonstrativo de receita", "relatorio receita"),
     "Relatório da receita — espelho gerencial, não documento de lançamento"),
    (("relatorio de gps", "relatorio gps", "resumo de gps", "resumo gps",
      "demonstrativo gps", "relatorio da gps"),
     "Relatório de GPS — resumo da guia; o lançamento vem da GPS/comprovante"),
    # Controle gerencial da folha/caixa — não é documento de partida dobrada
    (("controle de valores pagos", "controle valores pagos",
      "valores pagos", "controle de pagamentos", "relacao de pagamentos",
      "controle de valores"),
     "Controle de valores pagos — planilha gerencial, sem lançamento contábil"),
]

# A folha tem agente próprio: mandá-la para pendentes escondia que existe
# alguém preparado para ela.
DA_FABIANA = ("folha de pagamento", "holerite", "recibo de pagamento de salario",
              "folha de prolabore", "pro-labore", "termo de rescisao", "trct")


def _e_esocial(arq: Path) -> str:
    """Evento do eSocial disfarçado de XML na pasta da competência.

    O nome do arquivo já entrega (`evtRemun`, `evtPgtos`, `evtFechaEvPer`), e
    quem cuida de folha é a Fabiana. Se o nome não disser, o namespace diz.
    """
    n = arq.name.lower()
    if n.startswith("evt") or "esocial" in n:
        return "Evento do eSocial — folha; quem cuida é a Fabiana"
    try:
        cabeca = arq.read_text(encoding="utf-8", errors="ignore")[:600].lower()
    except OSError:
        return ""
    if "esocial" in cabeca:
        return "Evento do eSocial — folha; quem cuida é a Fabiana"
    return ""


def _nao_lancavel(texto: str, nome: str) -> str:
    """Devolve o motivo se o documento não é lançamento; senão, string vazia."""
    alvo = _sem_acento(f"{nome} {texto[:2500]}")
    stem = _sem_acento(Path(nome).stem)
    # nomes curtos comuns no OneDrive: Protocolo.pdf, Balancete.pdf, SEDIF…
    if stem in ("protocolo", "balancete", "sedif", "danfe") or stem.startswith(
        ("protocolo", "balancete", "relatorionotas", "relatorio_notas",
         "planilhademedicao", "planilha_medicao", "medicao",
         "relatoriodareceita", "relatorio_receita", "relatoriodegps",
         "relatorio_gps", "resumogps")
    ):
        # cai nas chaves abaixo; se o stem já bastar, devolve motivo genérico
        pass
    for chaves, motivo in NAO_LANCAVEIS:
        if any(k in alvo for k in chaves):
            return motivo
    # stem isolado (arquivo sem texto extraível)
    if stem in ("protocolo",) or stem.startswith("protocolo"):
        return "Protocolo de transmissão — não movimenta conta"
    if stem in ("balancete",) or stem.startswith("balancete"):
        return "Relatório contábil — é resultado da contabilidade, não documento dela"
    if "medicao" in stem:
        return "Planilha/boletim de medição — controle de obra, não lançamento"
    if "receita" in stem and "relatorio" in stem:
        return "Relatório da receita — espelho gerencial, não documento de lançamento"
    if "gps" in stem and ("relatorio" in stem or "resumo" in stem):
        return "Relatório de GPS — resumo da guia; o lançamento vem da GPS/comprovante"
    if "valores" in stem and ("pago" in stem or "pagos" in stem or "controle" in stem):
        return "Controle de valores pagos — planilha gerencial, sem lançamento contábil"
    if stem.startswith("controle") and ("valor" in stem or "pagamento" in stem):
        return "Controle de valores pagos — planilha gerencial, sem lançamento contábil"
    return ""


def _sem_acento(t: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def _parece_pagamento(texto: str) -> bool:
    """Comprovante pago x guia a pagar — muda o par contábil inteiro."""
    baixo = texto.lower()
    return any(
        k in baixo
        for k in ("comprovante", "pagamento efetuado", "pago em", "autenticacao", "autenticação")
    )


def _e_a_prazo(arq: Path) -> bool:
    """A nota é a prazo? Quem responde é o vencimento da duplicata.

    Regra do Anderson, e ela é exata: **duplicata com vencimento diferente da
    emissão é a prazo** — vira Fornecedores/Duplicatas a receber e abre título.
    Duplicata vencendo no dia da emissão, ou nota sem duplicata nenhuma, é à
    vista: entra direto em caixa ou banco.

    A simples existência do bloco <dup> não bastava. A NF 44.141 da Estoque do
    Lojista traz duplicata 001 vencendo 13/01/2021, o mesmo dia da emissão: foi
    paga na hora, mas virava conta a pagar que nunca seria baixada.
    """
    try:
        conteudo = arq.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    emissao = None
    if m := re.search(r"<d[Ehm]{1,2}Emi>([\d-]{10})", conteudo):
        emissao = m.group(1)
    parcelas = _ler_duplicatas_seguro(arq)
    if parcelas:
        # basta uma parcela vencendo depois da emissão para ser a prazo
        return any(p.get("vencimento") and p["vencimento"] != emissao for p in parcelas)
    # sem duplicata detalhada: só o indPag explícito indica prazo
    return "<indPag>1</indPag>" in conteudo


def _ler_duplicatas_seguro(arq: Path) -> list[dict[str, Any]]:
    from escon_agentes.tools import titulos as _t

    try:
        return _t.ler_duplicatas(arq)
    except Exception:  # noqa: BLE001 — XML torto não derruba o lote
        return []


def _tem_encargos(texto: str) -> bool:
    """Duplicata paga em atraso traz juros e/ou multa no comprovante — eles
    viram receita própria, não podem se misturar ao principal."""
    baixo = texto.lower()
    return any(k in baixo for k in ("juros", "multa", "mora", "acrescimo", "acréscimo"))
