"""Razão auxiliar: títulos em aberto (duplicatas e parcelas) por cliente.

POR QUE EXISTE: cada competência era processada isolada. Uma duplicata emitida
em janeiro e paga em março, ou uma compra parcelada em 10x, gerava o débito em
`1121101` (Duplicatas a receber) e nada, nunca, lembrava de dar baixa. O saldo
só crescia e a conciliação não fechava.

Aqui fica a memória: cada parcela vira um título com saldo e vencimento. O
Alexandre abre título quando lança a prazo e procura título quando vê um
recebimento. O que não bater fica visível em vez de sumir.

REGRA DE OURO: na dúvida NÃO baixa. Se dois títulos em aberto têm o mesmo
valor, o agente não escolhe — devolve os candidatos para a pessoa decidir.
Baixar o título errado é pior que não baixar: o saldo total fica certo e a
conta do cliente fica errada, o que ninguém percebe no balancete.

Arquivo por cliente: data/titulos/{cliente}.json
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Tolerância de centavos ao casar um pagamento com um título. Boleto com
# arredondamento de juros costuma fechar por 1 ou 2 centavos.
TOLERANCIA = 0.02
# Quantos dias antes/depois do vencimento um pagamento ainda é considerado
# daquele título quando o valor não identifica sozinho.
JANELA_DIAS = 60
# Prazo presumido quando a nota é a prazo mas não traz duplicata detalhada.
PRAZO_PADRAO = 30

RECEBER = "receber"
PAGAR = "pagar"


def _hoje() -> str:
    return date.today().isoformat()


def _d(texto: str | None) -> date | None:
    if not texto:
        return None
    t = str(texto)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _iso(texto: str | None) -> str | None:
    d = _d(texto)
    return d.isoformat() if d else None


@dataclass
class Baixa:
    data: str
    valor: float
    documento: str = ""
    observacao: str = ""


@dataclass
class Titulo:
    id: str
    tipo: str  # receber | pagar
    numero: str  # nº da nota / documento
    parcela: str = "1"
    parcelas: int = 1
    contraparte: str = ""
    cnpj: str = ""
    emissao: str | None = None
    vencimento: str | None = None
    valor: float = 0.0
    conta: str = ""  # 1121101 ou 2121101
    origem: str = ""  # arquivo que deu origem
    competencia: str | None = None
    # True quando o vencimento foi estimado (a nota não trazia duplicata).
    # Precisa ficar visível: cobrar por data inventada é pior que não cobrar.
    presumido: bool = False
    baixas: list[dict] = field(default_factory=list)

    @property
    def baixado(self) -> float:
        return round(sum(float(b.get("valor") or 0) for b in self.baixas), 2)

    @property
    def saldo(self) -> float:
        return round(self.valor - self.baixado, 2)

    @property
    def status(self) -> str:
        if self.saldo <= TOLERANCIA:
            return "liquidado"
        return "parcial" if self.baixado else "aberto"

    def vencido_em(self, hoje: str | None = None) -> int:
        """Dias de atraso (0 se em dia ou sem vencimento)."""
        v = _d(self.vencimento)
        if not v or self.status == "liquidado":
            return 0
        ref = _d(hoje) or date.today()
        return max(0, (ref - v).days)


class Carteira:
    """Os títulos de um cliente. Carrega, mexe e grava."""

    def __init__(self, caminho: Path, cliente: str):
        self.caminho = caminho
        self.cliente = cliente
        self.titulos: list[Titulo] = []
        if caminho.exists():
            try:
                dados = json.loads(caminho.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                dados = {}
            for t in dados.get("titulos", []):
                self.titulos.append(Titulo(**t))

    # ---------- gravação ----------

    def salvar(self) -> Path:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(
            json.dumps(
                {
                    "cliente": self.cliente,
                    "atualizado": _hoje(),
                    "titulos": [asdict(t) for t in self.titulos],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return self.caminho

    # ---------- abrir ----------

    def registrar(self, titulo: Titulo) -> bool:
        """Grava o título se ainda não existe. Devolve True se é novo.

        Idempotente de propósito: reprocessar a mesma competência é rotina
        (o Anderson roda de novo depois de corrigir um documento) e não pode
        duplicar a conta a receber.
        """
        if any(t.id == titulo.id for t in self.titulos):
            return False
        self.titulos.append(titulo)
        return True

    # ---------- consultar ----------

    def em_aberto(self, tipo: str | None = None) -> list[Titulo]:
        return [
            t for t in self.titulos
            if t.status != "liquidado" and (tipo is None or t.tipo == tipo)
        ]

    def vencidos(self, hoje: str | None = None) -> list[Titulo]:
        return [t for t in self.em_aberto() if t.vencido_em(hoje) > 0]

    def _nota(self, t: Titulo, valor: float, ref: date | None) -> tuple[float, int]:
        """Quanto este título "parece" com o pagamento: diferença em centavos,
        depois distância do vencimento. Menor é melhor."""
        centavos = round(abs(t.saldo - valor), 2)
        v = _d(t.vencimento)
        dist = abs((ref - v).days) if (ref and v) else 9999
        return (centavos, dist)

    def candidatos(
        self, *, tipo: str, valor: float, data: str | None = None
    ) -> list[Titulo]:
        """Títulos que podem corresponder a este pagamento, do melhor ao pior.

        Ordenar por (diferença de centavos, distância do vencimento) importa:
        parcelas de uma mesma nota costumam diferir por 1 centavo de
        arredondamento, e a tolerância que serve para juros fazia as três
        casarem entre si. O valor exato tem de vencer o aproximado.
        """
        ref = _d(data)
        iguais = [t for t in self.em_aberto(tipo) if abs(t.saldo - valor) <= TOLERANCIA]
        return sorted(iguais, key=lambda t: self._nota(t, valor, ref))

    def ambiguo(self, cands: list[Titulo], valor: float, data: str | None = None) -> bool:
        """Dois títulos indistinguíveis — mesmo valor e mesma distância do
        vencimento. Aqui o agente não escolhe: quem decide é a pessoa."""
        if len(cands) < 2:
            return False
        ref = _d(data)
        return self._nota(cands[0], valor, ref) == self._nota(cands[1], valor, ref)

    def baixar(
        self, titulo_id: str, *, valor: float, data: str, documento: str = "",
        observacao: str = "",
    ) -> Titulo | None:
        for t in self.titulos:
            if t.id != titulo_id:
                continue
            t.baixas.append(
                asdict(Baixa(data=_iso(data) or data, valor=round(valor, 2),
                             documento=documento, observacao=observacao))
            )
            return t
        return None

    # ---------- relatório ----------

    def resumo(self, hoje: str | None = None) -> dict[str, Any]:
        rec = self.em_aberto(RECEBER)
        pag = self.em_aberto(PAGAR)
        venc = self.vencidos(hoje)
        return {
            "cliente": self.cliente,
            "total_titulos": len(self.titulos),
            "a_receber_aberto": len(rec),
            "a_receber_saldo": round(sum(t.saldo for t in rec), 2),
            "a_pagar_aberto": len(pag),
            "a_pagar_saldo": round(sum(t.saldo for t in pag), 2),
            "vencidos": len(venc),
            "vencidos_saldo": round(sum(t.saldo for t in venc), 2),
            "vencimento_presumido": sum(1 for t in rec + pag if t.presumido),
        }


def caminho_carteira(data_dir: Path, cliente: str) -> Path:
    return data_dir / "titulos" / f"{cliente}.json"


def abrir_carteira(data_dir: Path, cliente: str) -> Carteira:
    return Carteira(caminho_carteira(data_dir, cliente), cliente)


# ---------------------------------------------------------------- duplicatas


def ler_duplicatas(caminho: Path) -> list[dict[str, Any]]:
    """Extrai as parcelas do bloco <cobr><dup> de uma NF-e.

    É a informação que já vem na nota e ninguém usava: número da parcela,
    vencimento e valor. Sem ela uma venda em 3x viraria um título só.
    """
    try:
        root = ET.parse(caminho).getroot()
    except (ET.ParseError, OSError):
        return []
    saida: list[dict[str, Any]] = []
    for node in root.iter():
        if _tag(node) != "dup":
            continue
        item = {_tag(f): (f.text or "").strip() for f in node}
        venc = _iso(item.get("dVenc"))
        try:
            valor = float(item.get("vDup") or 0)
        except ValueError:
            valor = 0.0
        if valor <= 0:
            continue
        saida.append(
            {"parcela": item.get("nDup") or str(len(saida) + 1),
             "vencimento": venc, "valor": round(valor, 2)}
        )
    return saida


def _tag(node: ET.Element) -> str:
    return node.tag.split("}")[-1]


def parcelas_presumidas(
    valor: float, emissao: str | None, quantidade: int = 1, prazo: int = PRAZO_PADRAO
) -> list[dict[str, Any]]:
    """Quando o documento diz que é a prazo mas não detalha as parcelas.

    Fica marcado como presumido: o vencimento é estimativa, e é melhor uma
    estimativa visível do que um título sem data que nunca aparece em nenhum
    relatório de vencidos.
    """
    base = _d(emissao) or date.today()
    quantidade = max(1, quantidade)
    fatia = round(valor / quantidade, 2)
    saida = []
    for i in range(quantidade):
        # a última parcela absorve a diferença de arredondamento
        v = round(valor - fatia * (quantidade - 1), 2) if i == quantidade - 1 else fatia
        saida.append(
            {"parcela": str(i + 1),
             "vencimento": (base + timedelta(days=prazo * (i + 1))).isoformat(),
             "valor": v, "presumido": True}
        )
    return saida


def montar_id(cliente: str, tipo: str, numero: str, parcela: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9]", "", f"{numero}-{parcela}") or "s-n"
    return f"{cliente}:{tipo}:{limpo}"


def formatar(titulos: list[Titulo], hoje: str | None = None) -> str:
    """Lista legível para o terminal e para o resumo do agente."""
    if not titulos:
        return "Nenhum título em aberto."
    linhas = []
    for t in sorted(titulos, key=lambda x: x.vencimento or "9999"):
        atraso = t.vencido_em(hoje)
        marca = f"  ATRASO {atraso}d" if atraso else ""
        linhas.append(
            f"  {t.vencimento or 's/venc'}  {t.tipo:8s} nº {t.numero}/{t.parcela}  "
            f"R$ {t.saldo:>10,.2f}  {t.contraparte[:28]}{marca}"
        )
    return "\n".join(linhas)
