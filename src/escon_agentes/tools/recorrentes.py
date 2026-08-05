"""Despesas que se repetem todo mês — provisionadas sem documento.

POR QUE: o honorário contábil da Alumax é R$ 528 todo mês. O boleto pode
chegar, chegar atrasado ou não chegar; a despesa é do mês de qualquer forma.
Regime de competência: provisiona no mês em que o serviço foi prestado, e o
pagamento baixa a provisão depois.

Isso resolve um problema específico da contabilidade atrasada: em vários dos
meses parados **não existe documento nenhum** de honorário na pasta. Sem
recorrência, esses meses sairiam sem a despesa e o resultado ficaria errado
para mais.

Cada cliente tem seu arquivo: data/recorrentes/{cliente}.json
"""

from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class Recorrente:
    id: str
    descricao: str
    debito: str
    credito: str  # conta de passivo (a pagar); o pagamento baixa contra o banco
    valor: float
    dia: int = 0  # 0 = último dia do mês (padrão para provisão)
    inicio: str = ""  # AAAA-MM — antes disso não existia
    fim: str = ""  # AAAA-MM — depois disso acabou (contrato encerrado)
    historico: int = 0
    criado_em: str = field(default_factory=lambda: date.today().isoformat())

    def vale_para(self, competencia: str) -> bool:
        if self.inicio and competencia < self.inicio:
            return False
        if self.fim and competencia > self.fim:
            return False
        return True

    def data_na(self, competencia: str) -> str:
        ano, mes = int(competencia[:4]), int(competencia[5:7])
        ultimo = calendar.monthrange(ano, mes)[1]
        dia = ultimo if not self.dia else min(self.dia, ultimo)
        return date(ano, mes, dia).isoformat()


def _caminho(data_dir: Path, cliente: str) -> Path:
    return data_dir / "recorrentes" / f"{cliente}.json"


def carregar(data_dir: Path, cliente: str) -> list[Recorrente]:
    p = _caminho(data_dir, cliente)
    if not p.exists():
        return []
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [Recorrente(**r) for r in dados.get("recorrentes", [])]


def salvar(data_dir: Path, cliente: str, itens: list[Recorrente]) -> Path:
    p = _caminho(data_dir, cliente)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"cliente": cliente, "recorrentes": [asdict(i) for i in itens]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return p


def registrar(data_dir: Path, cliente: str, item: Recorrente) -> Recorrente:
    """Mesmo id substitui — corrigir o valor do contrato é rotina."""
    itens = [i for i in carregar(data_dir, cliente) if i.id != item.id]
    itens.append(item)
    salvar(data_dir, cliente, itens)
    return item


def remover(data_dir: Path, cliente: str, rec_id: str) -> bool:
    itens = carregar(data_dir, cliente)
    restantes = [i for i in itens if i.id != rec_id]
    if len(restantes) == len(itens):
        return False
    salvar(data_dir, cliente, restantes)
    return True


def lancamentos_da_competencia(
    data_dir: Path, cliente: str, competencia: str
) -> list[dict[str, Any]]:
    """As provisões do mês, no formato que o Alexandre já usa.

    Marcadas com `origem: recorrente` de propósito: na revisão dá para ver o
    que veio de documento e o que veio de contrato, e essa distinção importa
    quando o balancete não fecha.
    """
    saida = []
    for r in carregar(data_dir, cliente):
        if not r.vale_para(competencia):
            continue
        saida.append({
            "arquivo": f"(recorrente) {r.descricao}",
            "data": r.data_na(competencia),
            "valor": round(r.valor, 2),
            "debito": r.debito,
            "credito": r.credito,
            "historico": r.historico,
            "historico_texto": "",
            "complemento": f"{r.descricao} - comp {competencia[5:7]}/{competencia[:4]}",
            "regra": f"recorrente:{r.id}",
            "origem": "recorrente",
            "observacao": "Provisão mensal por contrato — não veio de documento.",
        })
    return saida
