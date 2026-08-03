"""Lê o Razão Analítico (PDF do Contmatic) e extrai os lançamentos reais.

Serve para aprender, do histórico verdadeiro do escritório, quais pares
débito/crédito e quais históricos a Escon usa de fato — em vez de deduzir
com LLM a cada documento.

O PDF é posicional: só o texto não diz se um valor é débito ou crédito, porque
a única diferença é a coluna em que ele aparece. Por isso lemos com coordenada
(`extract_words`) e não com `extract_text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# x das colunas no layout do Contmatic (medido no cabeçalho do próprio PDF)
X_DEBITO = (340, 415)
X_CREDITO = (415, 495)

RE_CONTA_CABECALHO = re.compile(
    r"^(\d\.\d\.\d\.\d{2}\.\d{3}\.\d{5})\s+([\d-]+)\s+(.+)$"
)
RE_DATA = re.compile(r"^\d{2}/\d{2}$")
RE_VALOR = re.compile(r"^[\d.]+,\d{2}$")
RE_SALDO = re.compile(r"^[\d.]+,\d{2}[DC]$")
RE_PERIODO = re.compile(r"Período\s*:\s*(\d{2}/\d{2}/\d{4})\s*a\s*(\d{2}/\d{2}/\d{4})")


@dataclass
class Lancamento:
    conta_pagina: str  # conta reduzida "dona" da página do razão
    conta_pagina_nome: str
    contrapartida: str
    historico: str
    valor: float
    natureza: str  # "D" se a conta da página foi debitada, "C" se creditada
    data: str  # DD/MM
    lote: str
    numero: str

    @property
    def debito(self) -> str:
        return self.conta_pagina if self.natureza == "D" else self.contrapartida

    @property
    def credito(self) -> str:
        return self.contrapartida if self.natureza == "D" else self.conta_pagina


@dataclass
class Razao:
    lancamentos: list[Lancamento] = field(default_factory=list)
    periodo: tuple[str, str] | None = None
    contas: dict[str, str] = field(default_factory=dict)  # reduzida -> nome


def _num(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _so_digitos(txt: str) -> str:
    return re.sub(r"\D", "", txt or "")


def _linhas_por_y(palavras: list[dict], tolerancia: float = 2.5) -> list[list[dict]]:
    """Agrupa palavras em linhas visuais pelo topo (o PDF não traz linhas)."""
    ordenadas = sorted(palavras, key=lambda w: (round(w["top"], 1), w["x0"]))
    linhas: list[list[dict]] = []
    for w in ordenadas:
        if linhas and abs(linhas[-1][0]["top"] - w["top"]) <= tolerancia:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return [sorted(ln, key=lambda w: w["x0"]) for ln in linhas]


def _natureza(palavra: dict) -> str | None:
    centro = (palavra["x0"] + palavra["x1"]) / 2
    if X_DEBITO[0] <= centro < X_DEBITO[1]:
        return "D"
    if X_CREDITO[0] <= centro < X_CREDITO[1]:
        return "C"
    return None


def ler_razao(caminho: Path) -> Razao:
    import pdfplumber

    razao = Razao()
    conta_atual = ""
    nome_atual = ""

    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            if razao.periodo is None and (m := RE_PERIODO.search(texto)):
                razao.periodo = (m.group(1), m.group(2))

            for linha in _linhas_por_y(pagina.extract_words()):
                textos = [w["text"] for w in linha]
                bruto = " ".join(textos)

                # troca de conta: cabeçalho "1.1.1.02.002.00004 11122-04 Inter"
                if m := RE_CONTA_CABECALHO.match(bruto):
                    conta_atual = _so_digitos(m.group(2))
                    nome_atual = m.group(3).strip()
                    if conta_atual:
                        razao.contas[conta_atual] = nome_atual
                    continue

                if not textos or not RE_DATA.match(textos[0]) or not conta_atual:
                    continue

                # o valor do lançamento é o número que cai na coluna D ou C
                valor = None
                natureza = None
                for w in linha:
                    if RE_SALDO.match(w["text"]):
                        continue
                    if RE_VALOR.match(w["text"]) and (nat := _natureza(w)):
                        valor, natureza = _num(w["text"]), nat
                        break
                if valor is None or natureza is None:
                    continue

                # DATA LOTE LCT C/PART HISTORICO...
                if len(textos) < 5:
                    continue
                data, lote, numero, contrapartida = textos[0], textos[1], textos[2], textos[3]
                if not contrapartida.isdigit():
                    continue

                fim_historico = next(
                    (i for i, w in enumerate(linha) if RE_VALOR.match(w["text"]) and _natureza(w)),
                    len(linha),
                )
                historico = " ".join(w["text"] for w in linha[4:fim_historico]).strip()

                razao.lancamentos.append(
                    Lancamento(
                        conta_pagina=conta_atual,
                        conta_pagina_nome=nome_atual,
                        contrapartida=contrapartida,
                        historico=historico,
                        valor=valor,
                        natureza=natureza,
                        data=data,
                        lote=lote,
                        numero=numero,
                    )
                )
    return razao


def normalizar_historico(historico: str) -> str:
    """Tira o que muda a cada lançamento (mês, ano, nome, valor) e deixa o padrão.

    'Vale Transporte Mes Jan/2020 Paola de Freitas' -> 'vale transporte mes'
    """
    t = historico.lower()
    t = re.sub(r"\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*[/.]?\s*\d{2,4}", " ", t)
    t = re.sub(r"\b\d{1,2}/\d{2,4}\b", " ", t)
    t = re.sub(r"\b\d[\d.,]*\b", " ", t)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-zà-ú\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def resumir(razao: Razao) -> dict[str, Any]:
    """Agrupa por (débito, crédito, histórico padrão) — a regra que interessa."""
    from collections import Counter

    padroes: Counter = Counter()
    hist_por_par: dict[tuple[str, str], Counter] = {}
    for l in razao.lancamentos:
        chave = (l.debito, l.credito)
        hp = normalizar_historico(l.historico)
        padroes[(l.debito, l.credito, hp)] += 1
        hist_por_par.setdefault(chave, Counter())[hp] += 1

    return {
        "total_lancamentos": len(razao.lancamentos),
        "periodo": razao.periodo,
        "contas_no_razao": len(razao.contas),
        "padroes": padroes,
        "hist_por_par": hist_por_par,
    }
