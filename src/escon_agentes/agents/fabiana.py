"""Fabiana — Folha de Pagamento (provisão na competência, pagamento na data)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from escon_agentes.agents.base import BaseAgent
from escon_agentes.config import PROJECT_ROOT
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import documents
from escon_agentes.tools.clients import get_client
from escon_agentes.tools.folha_parser import Folha, ler_folha, problemas, resumo

# Quando cada coisa é paga. O calendário da Escon, confirmado pelo Anderson.
DIA_ADIANTAMENTO = 20  # no próprio mês da competência
DIA_FGTS = 7  # mês seguinte
DIA_INSS = 20  # mês seguinte
DIA_UTIL_SALARIO = 5  # 5º dia útil do mês seguinte

# Provisões mensais. Férias = 1/12 do salário + 1/3 constitucional; 13º = 1/12.
# FGTS de 8% incide sobre as duas.
# Não se provisiona INSS patronal: a carteira da Escon é Simples Nacional, onde
# a contribuição já está dentro do DAS.
AVOS = 1 / 12
TERCO_FERIAS = 1 / 3
FGTS_ALIQUOTA = 0.08


@dataclass
class Lancamento:
    data: str
    debito: str
    credito: str
    valor: float
    complemento: str
    etapa: str  # provisao | pagamento
    historico: int = 0


def _ultimo_dia(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _dia_util(ano: int, mes: int, n: int) -> date:
    """N-ésimo dia útil do mês. Considera só fim de semana — feriado municipal
    varia por cidade e o contador ajusta na revisão."""
    d = date(ano, mes, 1)
    contados = 0
    while True:
        if d.weekday() < 5:
            contados += 1
            if contados >= n:
                return d
        d += timedelta(days=1)


def _mes_seguinte(ano: int, mes: int) -> tuple[int, int]:
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _proximo_util(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class FabianaAgent(BaseAgent):
    id = AgentId.FABIANA
    name = "Fabiana"
    role = "Folha de Pagamento"
    system_prompt = """
Você cuida dos lançamentos da folha de pagamento.
A folha é provisionada na competência e paga depois: salário no 5º dia útil do
mês seguinte, adiantamento no dia 20 do próprio mês, FGTS no dia 7 e INSS no
dia 20 do mês seguinte.
Cada holerite é pago individualmente, identificando o empregado e a competência.
Folha que não fecha (proventos - descontos ≠ líquido) não vira lançamento.
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plano = yaml.safe_load(
            (PROJECT_ROOT / "config" / "plano_contas.yaml").read_text(encoding="utf-8")
        )
        self.contas: dict = plano.get("contas") or {}
        self.bancos: dict = plano.get("bancos") or {}
        self.historicos: dict = plano.get("historicos") or {}

    def conta(self, alias: str) -> str:
        return str(self.contas.get(alias, ""))

    def conta_banco(self, banco: str | None) -> str:
        return str(self.contas.get(self.bancos.get((banco or "itau").lower(), "banco_itau"), ""))

    def run(self, task: AgentTask) -> AgentResult:
        arquivo = task.input.get("arquivo")
        if not arquivo or not Path(arquivo).exists():
            return self.result_fail("Informe o PDF da folha em input['arquivo'].")

        folha = ler_folha(documents.extract_text(Path(arquivo)))
        pendencias = problemas(folha)
        info = resumo(folha)

        # Folha que não fecha não vira lançamento: erro aqui só aparece no
        # balancete, semanas depois.
        if pendencias:
            return self.result_ok(
                "Folha NÃO foi contabilizada — precisa de conferência:\n  - "
                + "\n  - ".join(pendencias[:10]),
                data={"resumo": info, "problemas": pendencias, "lancamentos": []},
                needs_human=True,
                human_prompt="Confira a folha; nenhum lançamento foi gerado.",
            )

        cliente = get_client(self.settings.clients_dir, task.client_id) if task.client_id else None
        banco = self.conta_banco(getattr(cliente, "banco_principal", None))
        comp = task.input.get("competencia") or folha.competencia
        if not comp:
            return self.result_fail("Competência não identificada na folha.")
        ano, mes = int(comp[:4]), int(comp[5:7])

        lancs = self._montar(folha, comp, ano, mes, banco)
        if task.input.get("provisionar", True):
            lancs += self._provisoes(folha, ano, mes)
        return self.result_ok(
            f"{info['funcionarios']} funcionário(s) · folha fecha · "
            f"{len(lancs)} lançamento(s): "
            f"{sum(1 for x in lancs if x.etapa == 'provisao')} de provisão e "
            f"{sum(1 for x in lancs if x.etapa == 'pagamento')} de pagamento.",
            data={
                "resumo": info,
                "lancamentos": [x.__dict__ for x in lancs],
            },
            needs_human=True,
            human_prompt="Revise antes de importar; confira feriados nas datas de pagamento.",
        )

    def _provisoes(self, folha: Folha, ano: int, mes: int) -> list[Lancamento]:
        """Férias e 13º: competência mensal que NÃO está na folha do mês.

        São cálculo, não leitura — por isso ficam separados do que veio do PDF.
        Sócio não tem férias nem 13º, então o pró-labore fica de fora.
        """
        out: list[Lancamento] = []
        fim = _ultimo_dia(ano, mes).isoformat()
        for f in folha.funcionarios:
            if f.tipo == "prolabore":
                continue
            base = round(f.proventos + f.vantagens, 2)
            if not base:
                continue
            quem = f"{f.nome[:34]} - comp {mes:02d}/{ano}"

            ferias = round(base * AVOS * (1 + TERCO_FERIAS), 2)
            decimo = round(base * AVOS, 2)
            out.append(Lancamento(fim, self.conta("desp_ferias"),
                                  self.conta("provisao_ferias"), ferias,
                                  f"Provisao ferias {quem}", "provisao", 0))
            out.append(Lancamento(fim, self.conta("desp_13"),
                                  self.conta("provisao_13"), decimo,
                                  f"Provisao 13o {quem}", "provisao", 0))
            out.append(Lancamento(fim, self.conta("desp_fgts"),
                                  self.conta("fgts_provisao_ferias"),
                                  round(ferias * FGTS_ALIQUOTA, 2),
                                  f"FGTS s/ provisao ferias {quem}", "provisao", 5))
            out.append(Lancamento(fim, self.conta("desp_fgts"),
                                  self.conta("fgts_provisao_13"),
                                  round(decimo * FGTS_ALIQUOTA, 2),
                                  f"FGTS s/ provisao 13o {quem}", "provisao", 5))
        return out

    def _montar(
        self, folha: Folha, comp: str, ano: int, mes: int, banco: str
    ) -> list[Lancamento]:
        """Provisão na competência; pagamento nas datas do calendário."""
        out: list[Lancamento] = []
        fim = _ultimo_dia(ano, mes).isoformat()
        ano2, mes2 = _mes_seguinte(ano, mes)
        data_salario = _dia_util(ano2, mes2, DIA_UTIL_SALARIO).isoformat()
        data_fgts = _proximo_util(date(ano2, mes2, DIA_FGTS)).isoformat()
        data_inss = _proximo_util(date(ano2, mes2, DIA_INSS)).isoformat()
        data_adiant = _proximo_util(date(ano, mes, DIA_ADIANTAMENTO)).isoformat()

        total_inss = total_fgts = total_adiant = 0.0

        for f in folha.funcionarios:
            # sócio vai para pró-labore, empregado para salários — o mesmo
            # arquivo traz os dois, então a conta é decidida por funcionário
            prolabore = f.tipo == "prolabore"
            desp = self.conta("desp_prolabore" if prolabore else "desp_salarios")
            pagar = self.conta("prolabore_pagar" if prolabore else "salarios_pagar")
            hist_prov = 1 if prolabore else 3

            # cada holerite é individual, com o nome e a competência no complemento
            quem = f"{f.nome[:34]} - comp {mes:02d}/{ano}"
            bruto = round(f.proventos + f.vantagens, 2)
            if bruto:
                out.append(Lancamento(fim, desp, pagar, bruto,
                                      f"Folha {quem}", "provisao", hist_prov))

            for r in f.rubricas:
                if r.natureza == "desconto" and r.conta_alias == "inss_pagar":
                    total_inss += r.valor
                    out.append(Lancamento(fim, pagar, self.conta("inss_pagar"), r.valor,
                                          f"INSS retido {quem}", "provisao",
                                          2 if prolabore else 6))
                elif r.natureza == "encargo" and r.conta_alias == "fgts_pagar":
                    total_fgts += r.valor
                    out.append(Lancamento(fim, self.conta("desp_fgts"),
                                          self.conta("fgts_pagar"), r.valor,
                                          f"FGTS {quem}", "provisao", 5))
                elif r.natureza == "desconto" and r.conta_alias == "salarios_pagar":
                    total_adiant += r.valor
                    out.append(Lancamento(data_adiant, pagar, banco, r.valor,
                                          f"Adiantamento {quem}", "pagamento", hist_prov))

            liquido = round(f.liquido, 2)
            if liquido:
                out.append(Lancamento(data_salario, pagar, banco, liquido,
                                      f"Pagamento {quem}", "pagamento", hist_prov))

        # guias vão em um lançamento só, é assim que são recolhidas
        if total_inss:
            out.append(Lancamento(data_inss, self.conta("inss_pagar"), banco,
                                  round(total_inss, 2),
                                  f"GPS INSS comp {mes:02d}/{ano}", "pagamento", 15))
        if total_fgts:
            out.append(Lancamento(data_fgts, self.conta("fgts_pagar"), banco,
                                  round(total_fgts, 2),
                                  f"GRF FGTS comp {mes:02d}/{ano}", "pagamento", 5))
        return out
