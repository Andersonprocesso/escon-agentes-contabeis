"""Decide débito, crédito e histórico de um documento — sem gastar token.

A economia vem do desenho, igual ao da Raquel: as regras saem do razão real
(2.090 lançamentos), então o caso do dia a dia — DAS, folha, FGTS, combustível,
NFS-e — é resolvido por comparação de texto. O modelo só é chamado para o que
nenhuma regra reconhece, e mesmo aí uma vez por documento, nunca por linha.

O que o LLM propuser fica marcado como `origem="llm"` e `precisa_revisao=True`:
lançamento contábil errado é caro, então nada entra no Excel sem o contador ver.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Classificacao:
    debito: str
    credito: str
    historico_codigo: int
    historico_texto: str
    complemento: str = ""
    regra_id: str = ""
    origem: str = "regra"  # regra | llm | desconhecido
    confianca: str = "alta"  # alta | media | nenhuma
    precisa_revisao: bool = False
    observacao: str = ""
    # juros/multa viram lancamento proprio, nao entram no principal
    encargos: dict = field(default_factory=dict)
    # razão auxiliar: "receber"/"pagar" quando a regra cria um título em aberto,
    # ou quando o documento baixa um que já existia.
    abre_titulo: str = ""
    baixa_titulo: str = ""


@dataclass
class Documento:
    """O que já foi extraído do arquivo (data e valor NÃO vêm do LLM)."""

    caminho: str
    tipo: str  # pdf | xml | ofx
    texto: str
    data: str | None = None
    valor: float | None = None
    e_pagamento: bool | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).upper()


class Classificador:
    def __init__(self, regras_path: Path, plano_path: Path):
        dados = yaml.safe_load(regras_path.read_text(encoding="utf-8")) or {}
        # As regras que o contador ensinou vêm PRIMEIRO: são correção humana
        # sobre um caso concreto e devem vencer o palpite geral. Ex.: o boleto
        # da Alumax não diz "honorário", diz o CNPJ do escritório — nenhuma
        # regra genérica pegaria, e a pessoa ensinou uma vez.
        from escon_agentes.tools import aprendizado

        self.regras: list[dict] = (aprendizado.carregar() or []) + (dados.get("regras") or [])
        self.contas_resultado: dict = dados.get("contas_resultado") or {}
        plano = yaml.safe_load(plano_path.read_text(encoding="utf-8")) or {}
        self.contas: dict = plano.get("contas") or {}
        self.bancos: dict = plano.get("bancos") or {}
        self.historicos: dict = plano.get("historicos") or {}

    def conta_do_banco(self, banco: str | None) -> str:
        alias = self.bancos.get((banco or "itau").lower(), "banco_itau")
        return str(self.contas.get(alias, ""))

    def _resolver(self, valor: Any, banco: str | None, forma: str = "banco") -> str:
        """@banco = conta do banco; @recebimento = caixa ou banco, conforme a
        forma informada no fechamento ("via caixa" / "via banco")."""
        if isinstance(valor, str):
            if valor.startswith("@banco"):
                return self.conta_do_banco(banco)
            if valor.startswith("@recebimento"):
                if (forma or "banco").lower().startswith("caixa"):
                    return str(self.contas.get("caixa", ""))
                return self.conta_do_banco(banco)
        return str(valor)

    def _casa(self, regra: dict, doc: Documento) -> bool:
        q = regra.get("quando") or {}
        if q.get("derivado_de"):
            return False  # gerada junto com a principal, não avaliada sozinha
        if (t := q.get("tipo")) and t != doc.tipo:
            return False
        if (esperado := q.get("e_pagamento")) is not None:
            if doc.e_pagamento is None or bool(doc.e_pagamento) != bool(esperado):
                return False
        if (sentido := q.get("sentido")) and doc.extras.get("sentido") != sentido:
            return False
        if (documento := q.get("documento")) and doc.extras.get("documento") != documento:
            return False
        for chave in ("a_prazo", "tem_encargos"):
            if (esperado := q.get(chave)) is not None and bool(doc.extras.get(chave)) != bool(esperado):
                return False
        termos = q.get("contem") or []
        if termos:
            alvo = _norm(doc.texto + " " + Path(doc.caminho).name)
            if not any(_norm(x) in alvo for x in termos):
                return False
        return True

    def classificar(
        self, doc: Documento, *, banco: str | None = None, forma: str = "banco"
    ) -> Classificacao:
        for regra in self.regras:
            if not self._casa(regra, doc):
                continue
            cod = int(regra.get("historico") or 0)
            return Classificacao(
                debito=self._resolver(regra.get("debito"), banco, forma),
                credito=self._resolver(regra.get("credito"), banco, forma),
                historico_codigo=cod,
                historico_texto=self.historicos.get(cod, "") if cod else "",
                regra_id=str(regra.get("id") or ""),
                origem="regra",
                confianca="alta",
                observacao=str(regra.get("descricao") or ""),
                encargos=regra.get("encargos") or {},
                abre_titulo=str(regra.get("abre_titulo") or ""),
                baixa_titulo=str(regra.get("baixa_titulo") or ""),
            )
        return Classificacao(
            debito="", credito="", historico_codigo=0, historico_texto="",
            origem="desconhecido", confianca="nenhuma", precisa_revisao=True,
            observacao="Nenhuma regra reconheceu este documento.",
        )

    # ---------- ponte para o LLM (só quando nada casou) ----------

    def prompt_para_llm(self, doc: Documento, *, limite: int = 1800) -> str:
        """Uma pergunta só, com o plano resumido e pedindo JSON puro."""
        contas = {**{str(v): k for k, v in self.contas.items()}, **self.contas_resultado}
        catalogo = "\n".join(f"{c} = {n}" for c, n in sorted(contas.items()))
        return (
            "Você é contador. Classifique o documento abaixo em UM lançamento.\n"
            "Responda só JSON: {\"debito\":\"codigo\",\"credito\":\"codigo\",\"complemento\":\"texto curto\"}\n"
            "Use apenas códigos da lista. Se não tiver certeza, devolva "
            '{"debito":null,"credito":null}. Nunca invente conta.\n\n'
            f"CONTAS:\n{catalogo}\n\nDOCUMENTO ({doc.tipo}):\n{doc.texto[:limite]}"
        )

    def aplicar_resposta_llm(self, bruto: str) -> Classificacao | None:
        import json

        m = re.search(r"\{.*\}", bruto or "", flags=re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        deb, cred = str(d.get("debito") or ""), str(d.get("credito") or "")
        if not deb.isdigit() or not cred.isdigit():
            return None
        validas = {str(v) for v in self.contas.values()} | {str(k) for k in self.contas_resultado}
        if deb not in validas or cred not in validas:
            return None  # o modelo inventou conta: descarta
        return Classificacao(
            debito=deb, credito=cred, historico_codigo=0, historico_texto="",
            complemento=str(d.get("complemento") or "")[:60],
            origem="llm", confianca="media", precisa_revisao=True,
            observacao="Sugerido pelo modelo — confira antes de importar.",
        )
