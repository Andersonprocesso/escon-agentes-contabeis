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
# INSS patronal (CPP 20%) só é provisionado no **Anexo IV** do Simples —
# construção civil, limpeza, vigilância —, onde a contribuição fica FORA do DAS
# e é recolhida em GPS. Nos demais anexos ela já está no DAS e provisionar
# duplicaria a despesa.
CPP_PATRONAL = 0.20
# Encargos por atraso: viram lançamento próprio, nunca somam ao principal —
# senão a guia fica com valor diferente do que foi provisionado e a conta a
# pagar não zera.
CONTA_JUROS = "juros_mora"
CONTA_MULTA = "multa_mora"
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

        # Datas reais informadas por quem pagou. Ex.:
        #   {"fgts": {"data": "2020-09-15", "juros": 12.50, "multa": 33.34}}
        # Sem isso vale o calendário padrão.
        reais: dict[str, dict] = task.input.get("pagamentos") or {}

        # Anexo IV recolhe patronal por fora; o cadastro do cliente diz qual é
        anexo = getattr(cliente, "anexo_simples", None)
        rat = float(getattr(cliente, "aliquota_rat", 0.0) or 0.0)
        patronal = anexo == 4

        lancs = self._montar(folha, comp, ano, mes, banco,
                             patronal=patronal, rat=rat, reais=reais)
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
        if folha.tipo == "rescisao":
            return []  # na rescisão as provisões são baixadas, não constituídas
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
        self, folha: Folha, comp: str, ano: int, mes: int, banco: str,
        *, patronal: bool = False, rat: float = 0.0,
        reais: dict[str, dict] | None = None,
    ) -> list[Lancamento]:
        """Provisão na competência; pagamento nas datas do calendário."""
        out: list[Lancamento] = []
        fim = _ultimo_dia(ano, mes).isoformat()
        ano2, mes2 = _mes_seguinte(ano, mes)
        data_salario = _dia_util(ano2, mes2, DIA_UTIL_SALARIO).isoformat()
        data_fgts = _proximo_util(date(ano2, mes2, DIA_FGTS)).isoformat()
        data_inss = _proximo_util(date(ano2, mes2, DIA_INSS)).isoformat()
        data_adiant = _proximo_util(date(ano, mes, DIA_ADIANTAMENTO)).isoformat()

        reais = reais or {}

        def quando(chave: str, padrao: str) -> str:
            """Data real do comprovante, quando informada."""
            return str((reais.get(chave) or {}).get("data") or padrao)

        def encargos(chave: str, referencia: str) -> list[Lancamento]:
            """Juros e multa de pagamento em atraso, cada um em conta própria."""
            info = reais.get(chave) or {}
            data = str(info.get("data") or "")
            saida: list[Lancamento] = []
            for campo, alias in (("juros", CONTA_JUROS), ("multa", CONTA_MULTA)):
                valor = round(float(info.get(campo) or 0), 2)
                if valor:
                    saida.append(Lancamento(data, self.conta(alias), banco, valor,
                                            f"{campo.capitalize()} atraso {referencia}",
                                            "pagamento", 0))
            return saida

        data_salario = quando("salario", data_salario)
        data_fgts = quando("fgts", data_fgts)
        data_inss = quando("inss", data_inss)
        data_adiant = quando("adiantamento", data_adiant)

        total_inss = total_fgts = total_adiant = 0.0

        for f in folha.funcionarios:
            # sócio vai para pró-labore, empregado para salários — o mesmo
            # arquivo traz os dois, então a conta é decidida por funcionário
            prolabore = f.tipo == "prolabore"
            rescisao = folha.tipo == "rescisao"
            desp = self.conta("desp_prolabore" if prolabore else "desp_salarios")
            # rescisão tem conta a pagar própria: separa do salário do mês e
            # deixa visível o que ainda falta quitar com o desligado
            pagar = self.conta(
                "rescisao_pagar" if rescisao
                else ("prolabore_pagar" if prolabore else "salarios_pagar")
            )
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
                elif r.natureza == "rescisao":
                    # cada verba com sua conta; indenizatórias não geram encargo
                    out.append(Lancamento(fim, self.conta(r.conta_alias or "desp_salarios"),
                                          pagar, r.valor,
                                          f"{r.descricao[:28]} {quem}", "provisao", 0))
                elif r.natureza == "desconto" and r.conta_alias == "salarios_pagar":
                    total_adiant += r.valor
                    out.append(Lancamento(data_adiant, pagar, banco, r.valor,
                                          f"Adiantamento {quem}", "pagamento", hist_prov))

            liquido = round(f.liquido, 2)
            if liquido:
                out.append(Lancamento(data_salario, pagar, banco, liquido,
                                      f"Pagamento {quem}", "pagamento", hist_prov))

        # CPP patronal: só Anexo IV. Entra como despesa da empresa, não como
        # retenção do empregado, e engorda a mesma GPS.
        if patronal:
            base_cpp = round(sum(f.proventos + f.vantagens for f in folha.funcionarios), 2)
            valor_cpp = round(base_cpp * (CPP_PATRONAL + rat), 2)
            if valor_cpp:
                out.append(Lancamento(fim, self.conta("desp_inss_patronal"),
                                      self.conta("inss_pagar"), valor_cpp,
                                      f"CPP patronal {CPP_PATRONAL:.0%}"
                                      + (f" + RAT {rat:.2%}" if rat else "")
                                      + f" comp {mes:02d}/{ano}", "provisao", 6))
                total_inss += valor_cpp

        # guias vão em um lançamento só, é assim que são recolhidas
        if total_inss:
            out.append(Lancamento(data_inss, self.conta("inss_pagar"), banco,
                                  round(total_inss, 2),
                                  f"GPS INSS comp {mes:02d}/{ano}", "pagamento", 15))
        if total_fgts:
            ref_fgts = f"GRF FGTS comp {mes:02d}/{ano}"
            out.append(Lancamento(data_fgts, self.conta("fgts_pagar"), banco,
                                  round(total_fgts, 2), ref_fgts, "pagamento", 5))
            out += encargos("fgts", ref_fgts)
        return out
