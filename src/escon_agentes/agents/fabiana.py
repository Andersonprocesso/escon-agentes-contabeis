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
Padrão do Diário/Razão Jorge (treino 2026-08-07):
- PROVISÃO pelo RESUMO de rubricas (Horas Normais, VT, INSS, FGTS, IRRF…)
  no último dia — SEM nome de funcionário no complemento.
- PAGAMENTOS (adiantamento dia 20 e líquido no 5º útil) INDIVIDUAIS com nome.
- RESCISÃO individual no dia da demissão.
- Pró-labore: D 3212102 / C 2141102 + INSS D 2141102 / C 2141201.
Folha que não fecha não vira lançamento.
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
        arquivos = self._resolver_arquivos_folha(task)
        if not arquivos:
            return self.result_ok(
                "Nenhuma folha/holerite nesta pasta — Fabiana sem trabalho nesta rodada.",
                data={"lancamentos": [], "pulou": True},
            )

        cliente = get_client(self.settings.clients_dir, task.client_id) if task.client_id else None
        banco = self.conta_banco(getattr(cliente, "banco_principal", None))
        reais: dict[str, dict] = task.input.get("pagamentos") or {}
        anexo = getattr(cliente, "anexo_simples", None)
        rat = float(getattr(cliente, "aliquota_rat", 0.0) or 0.0)
        patronal = anexo == 4

        todos_lancs: list[Any] = []
        resumos: list[dict] = []
        problemas_geral: list[str] = []

        for arquivo in arquivos:
            folha = ler_folha(documents.extract_text(Path(arquivo)))
            pendencias = problemas(folha)
            info = resumo(folha)
            resumos.append(info)

            # Folha que não fecha não vira lançamento: erro aqui só aparece no
            # balancete, semanas depois.
            if pendencias:
                problemas_geral.extend(
                    f"{Path(arquivo).name}: {p}" for p in pendencias[:8]
                )
                continue

            comp = task.input.get("competencia") or folha.competencia
            if not comp:
                problemas_geral.append(f"{Path(arquivo).name}: competência não identificada")
                continue
            ano, mes = int(comp[:4]), int(comp[5:7])

            lancs = self._montar(
                folha, comp, ano, mes, banco,
                patronal=patronal, rat=rat, reais=reais,
            )
            if task.input.get("provisionar", True):
                lancs += self._provisoes(folha, ano, mes)
            todos_lancs.extend(lancs)

        if problemas_geral and not todos_lancs:
            return self.result_ok(
                "Folha NÃO foi contabilizada — precisa de conferência:\n  - "
                + "\n  - ".join(problemas_geral[:12]),
                data={
                    "resumo": resumos,
                    "problemas": problemas_geral,
                    "lancamentos": [],
                },
                needs_human=True,
                human_prompt="Confira a folha; nenhum lançamento foi gerado.",
            )

        n_func = sum(int(r.get("funcionarios") or 0) for r in resumos if isinstance(r, dict))
        return self.result_ok(
            f"{len(arquivos)} arquivo(s) de folha · {n_func} funcionário(s) · "
            f"{len(todos_lancs)} lançamento(s) de folha mastigados para o Alexandre"
            + (f" · {len(problemas_geral)} problema(s)" if problemas_geral else ""),
            data={
                "resumo": resumos,
                "problemas": problemas_geral,
                "lancamentos": [
                    x if isinstance(x, dict) else x.__dict__ for x in todos_lancs
                ],
                "arquivos": [str(a) for a in arquivos],
            },
            needs_human=bool(problemas_geral) or bool(todos_lancs),
            human_prompt="Revise antes de importar; confira feriados nas datas de pagamento.",
        )

    def _resolver_arquivos_folha(self, task: AgentTask) -> list[Path]:
        """Um PDF explícito, ou busca na pasta da competência (pipeline Max)."""
        arquivo = task.input.get("arquivo")
        if arquivo and Path(arquivo).exists():
            return [Path(arquivo)]

        folder = None
        if task.input.get("folder"):
            folder = Path(task.input["folder"])
        elif task.client_id:
            from escon_agentes.tools.clients import client_inbox

            raiz = client_inbox(self.settings.inbox, task.client_id)
            comp = task.input.get("competencia")
            folder = (raiz / str(comp)) if comp and (raiz / str(comp)).is_dir() else raiz

        if not folder or not folder.exists():
            return []

        chaves = (
            "folha", "holerite", "prolabore", "pró-labore", "pro-labore",
            "pro labore", "pagamento e pro", "rescis", "trct",
        )
        achados: list[Path] = []
        for p in sorted(folder.rglob("*")):
            if not p.is_file() or p.suffix.lower() != ".pdf":
                continue
            nome = p.name.lower()
            if any(k in nome for k in chaves):
                achados.append(p)
        return achados

    def _provisoes(self, folha: Folha, ano: int, mes: int) -> list[Lancamento]:
        """Férias e 13º pelo RESUMO (totais da empresa), não por holerite.

        São cálculo, não leitura — por isso ficam separados do que veio do PDF.
        Sócio não tem férias nem 13º; demitidos no mês também ficam de fora
        (na rescisão as provisões são baixadas, não constituídas).
        """
        out: list[Lancamento] = []
        fim = _ultimo_dia(ano, mes).isoformat()
        if folha.tipo == "rescisao":
            return []
        # base = soma dos proventos dos empregados ativos (sem pró-labore / rescisão)
        base = 0.0
        for f in folha.funcionarios:
            if f.tipo == "prolabore" or f.is_rescisao:
                continue
            base += f.proventos + f.vantagens
        base = round(base, 2)
        if not base:
            return []

        ref = f"resumo comp {mes:02d}/{ano}"
        ferias = round(base * AVOS * (1 + TERCO_FERIAS), 2)
        decimo = round(base * AVOS, 2)
        out.append(Lancamento(fim, self.conta("desp_ferias"),
                              self.conta("provisao_ferias"), ferias,
                              f"Provisao ferias {ref}", "provisao", 0))
        out.append(Lancamento(fim, self.conta("desp_13"),
                              self.conta("provisao_13"), decimo,
                              f"Provisao 13o {ref}", "provisao", 0))
        out.append(Lancamento(fim, self.conta("desp_fgts"),
                              self.conta("fgts_provisao_ferias"),
                              round(ferias * FGTS_ALIQUOTA, 2),
                              f"FGTS s/ provisao ferias {ref}", "provisao", 5))
        out.append(Lancamento(fim, self.conta("desp_fgts"),
                              self.conta("fgts_provisao_13"),
                              round(decimo * FGTS_ALIQUOTA, 2),
                              f"FGTS s/ provisao 13o {ref}", "provisao", 5))
        return out

    def _montar(
        self, folha: Folha, comp: str, ano: int, mes: int, banco: str,
        *, patronal: bool = False, rat: float = 0.0,
        reais: dict[str, dict] | None = None,
    ) -> list[Lancamento]:
        """Provisão pelo RESUMO; rescisão no dia da demissão; pagamentos individuais."""
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

        # ---- Padrão do Diário/Razão Jorge (treinado em 2026-08-07) ----
        # Provisão pelo RESUMO de rubricas no último dia:
        #   Horas Normais  D 3221101 C 2141101
        #   DSR            D 3111201 C 2141101
        #   VT (desconto)  D 2141101 C 3221117
        #   INSS           D 2141101 C 2141201
        #   FGTS           D 3221107 C 2141202  (Diário também usa 3111207)
        #   IRRF           D 2141101 C 2131117
        #   Falta/vales    D 2141101 C 3111201
        # Pagamentos e adiantamentos: SEMPRE individuais.
        # Rescisão: individual no dia da demissão.
        resumo_prov: dict[tuple[str, str, int, str], float] = {}

        def add_resumo(deb: str, cred: str, valor: float, hist: int, rotulo: str) -> None:
            if not valor or valor < 0.005 or not deb or not cred:
                return
            k = (deb, cred, hist, rotulo)
            resumo_prov[k] = round(resumo_prov.get(k, 0.0) + valor, 2)

        total_inss = total_fgts = 0.0
        base_cpp = 0.0
        # adiantamentos: pagamento no dia 20 (individual) — o desconto no
        # resumo do Diário (#304) zera o líquido; aqui o líquido do holerite
        # já vem líquido do adiantamento, então só pagamos o que sobrou.
        arquivo_rescisao = folha.tipo == "rescisao"
        ref_resumo = f"resumo comp {mes:02d}/{ano}"

        c_sal = self.conta("desp_salarios")          # 3221101
        c_sal_res = self.conta("salarios_resultado") or c_sal  # 3111201
        c_pagar = self.conta("salarios_pagar")       # 2141101
        c_inss = self.conta("inss_pagar")            # 2141201
        c_fgts_desp = self.conta("desp_fgts")        # 3221107
        c_fgts = self.conta("fgts_pagar")            # 2141202
        c_vt = self.conta("desp_vale_transp")        # 3221117
        c_irrf = self.conta("irrf_pagar")            # 2131117
        c_prolab = self.conta("desp_prolabore")
        c_prolab_pagar = self.conta("prolabore_pagar")

        for f in folha.funcionarios:
            prolabore = f.tipo == "prolabore"
            rescisao = arquivo_rescisao or f.is_rescisao
            hist_prov = 1 if prolabore else 3
            quem = f"{f.nome[:34]} - comp {mes:02d}/{ano}"
            bruto = round(f.proventos + f.vantagens, 2)
            data_prov = (f.data_demissao or fim) if rescisao else fim
            pagar = self.conta(
                "rescisao_pagar" if rescisao
                else ("prolabore_pagar" if prolabore else "salarios_pagar")
            )
            desp = c_prolab if prolabore else c_sal

            if rescisao:
                # ---- RESCISÃO: individual, no dia da demissão (exceção) ----
                verbas_r = [r for r in f.rubricas if r.natureza == "rescisao"]
                soma_verbas = round(sum(r.valor for r in verbas_r), 2)
                if verbas_r:
                    for r in verbas_r:
                        out.append(Lancamento(
                            data_prov,
                            self.conta(r.conta_alias or "desp_salarios"),
                            pagar, r.valor,
                            f"{r.descricao[:40]} {quem}", "provisao", 0,
                        ))
                    residual = round(bruto - soma_verbas, 2)
                    if residual > 0.01:
                        out.append(Lancamento(
                            data_prov, desp, pagar, residual,
                            f"Rescisao residual {quem}", "provisao", hist_prov,
                        ))
                elif bruto:
                    out.append(Lancamento(
                        data_prov, desp, pagar, bruto,
                        f"Rescisao {quem}", "provisao", hist_prov,
                    ))
                for r in f.rubricas:
                    if r.natureza == "desconto" and r.conta_alias == "inss_pagar":
                        total_inss += r.valor
                        out.append(Lancamento(
                            data_prov, pagar, c_inss, r.valor,
                            f"INSS retido {quem}", "provisao", 6,
                        ))
                    elif r.natureza == "encargo" and r.conta_alias == "fgts_pagar":
                        total_fgts += r.valor
                        out.append(Lancamento(
                            data_prov, c_fgts_desp, c_fgts, r.valor,
                            f"FGTS rescisao {quem}", "provisao", 5,
                        ))
            elif prolabore:
                # ---- PRÓ-LABORE: resumo (sócio) — Diário #138/#139 ----
                if bruto:
                    add_resumo(c_prolab, c_prolab_pagar, bruto, 1, "Pro-Labore do Mes")
                for r in f.rubricas:
                    if r.natureza == "desconto" and r.conta_alias == "inss_pagar":
                        total_inss += r.valor
                        add_resumo(
                            c_prolab_pagar, c_inss, r.valor, 2,
                            "INSS sobre Pro-Labore",
                        )
            else:
                # ---- ATIVO: RESUMO por rubrica (Diário Jorge #141+) ----
                base_cpp += bruto
                # proventos: se houver rubricas classificadas, usa elas;
                # senão cai o bruto em "Horas Normais Diurnas"
                proventos_rub = [
                    r for r in f.rubricas if r.natureza == "provento" and r.valor
                ]
                if proventos_rub:
                    for r in proventos_rub:
                        alias = r.conta_alias or "desp_salarios"
                        if alias == "dsr":
                            # Diário: D 3111201 C 2141101 Horas DSR Diurnas
                            add_resumo(
                                c_sal_res, c_pagar, r.valor, 3, "Horas DSR Diurnas",
                            )
                        elif alias == "estouro":
                            add_resumo(c_sal, c_pagar, r.valor, 3, "Estouro do Mes")
                        else:
                            # Horas Normais e demais proventos de salário
                            rotulo = "Horas Normais Diurnas"
                            dlow = (r.descricao or "").lower()
                            if "hora extra" in dlow or "he " in dlow:
                                rotulo = "Horas Extras"
                            elif "ferias" in dlow or "férias" in dlow:
                                rotulo = "Ferias"
                            add_resumo(c_sal, c_pagar, r.valor, 3, rotulo)
                elif bruto:
                    add_resumo(c_sal, c_pagar, bruto, 3, "Horas Normais Diurnas")

                for r in f.rubricas:
                    if r.natureza == "desconto" and r.conta_alias == "inss_pagar":
                        total_inss += r.valor
                        add_resumo(c_pagar, c_inss, r.valor, 6, "INSS sobre Salarios")
                    elif r.natureza == "encargo" and r.conta_alias == "fgts_pagar":
                        total_fgts += r.valor
                        add_resumo(c_fgts_desp, c_fgts, r.valor, 5, "FGTS do Mes")
                    elif r.natureza == "desconto" and r.conta_alias == "desp_vale_transp":
                        # Diário #142: D 2141101 C 3221117 Vale Transporte Mes
                        add_resumo(c_pagar, c_vt, r.valor, 8, "Vale Transporte Mes")
                    elif r.natureza == "desconto" and r.conta_alias == "irrf_pagar":
                        add_resumo(c_pagar, c_irrf, r.valor, 0, "IRRF")
                    elif r.natureza == "desconto" and r.conta_alias == "falta":
                        add_resumo(c_pagar, c_sal_res, r.valor, 0, "Falta")
                    elif r.natureza == "desconto" and r.conta_alias == "vales":
                        add_resumo(
                            c_pagar, c_sal_res, r.valor, 0, "Desconto de Vales - Sem",
                        )
                    elif r.natureza == "desconto" and r.conta_alias in (
                        "adiantamento", "salarios_pagar",
                    ):
                        # pagamento individual no dia 20 (Diário)
                        out.append(Lancamento(
                            data_adiant, c_pagar, banco, r.valor,
                            f"Salario do Mes Adiantamento {quem}", "pagamento", 3,
                        ))
                    elif r.natureza == "desconto" and r.conta_alias == "sindicato_pagar":
                        add_resumo(
                            c_pagar, self.conta("sindicato_pagar"), r.valor, 0,
                            "Taxa Assistencial",
                        )

            # ---- PAGAMENTO do líquido: sempre individual ----
            liquido = round(f.liquido, 2)
            if liquido:
                data_pag = data_prov if rescisao else data_salario
                if rescisao:
                    rotulo_pag = f"Pagamento rescisao {quem}"
                elif prolabore:
                    rotulo_pag = f"Pro-Labore do Mes Pagamento {quem}"
                else:
                    rotulo_pag = f"Salario do Mes Pagamento {quem}"
                out.append(Lancamento(
                    data_pag, pagar, banco, liquido,
                    rotulo_pag, "pagamento", hist_prov,
                ))

        # Materializa o RESUMO no último dia (sem nome de funcionário)
        for (deb, cred, hist, rotulo), valor in resumo_prov.items():
            out.append(Lancamento(
                fim, deb, cred, valor,
                f"{rotulo} {ref_resumo}", "provisao", hist,
            ))

        # CPP patronal Anexo IV
        if patronal:
            valor_cpp = round(base_cpp * (CPP_PATRONAL + rat), 2)
            if valor_cpp:
                out.append(Lancamento(
                    fim, self.conta("desp_inss_patronal"),
                    c_inss, valor_cpp,
                    f"CPP patronal {CPP_PATRONAL:.0%}"
                    + (f" + RAT {rat:.2%}" if rat else "")
                    + f" {ref_resumo}", "provisao", 6,
                ))
                total_inss += valor_cpp

        if total_inss:
            out.append(Lancamento(data_inss, c_inss, banco,
                                  round(total_inss, 2),
                                  f"GPS INSS comp {mes:02d}/{ano}", "pagamento", 15))
        if total_fgts:
            ref_fgts = f"GRF FGTS comp {mes:02d}/{ano}"
            out.append(Lancamento(data_fgts, c_fgts, banco,
                                  round(total_fgts, 2), ref_fgts, "pagamento", 5))
            out += encargos("fgts", ref_fgts)
        return out
