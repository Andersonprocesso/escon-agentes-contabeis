"""Leitura da folha de pagamento / pró-labore (Marcos).

Por que a folha tem um leitor só dela: uma nota fiscal vira UM lançamento, mas
uma folha vira um conjunto que precisa **fechar** — proventos menos descontos
tem de bater com o líquido. Se um valor sai errado, o balancete não fecha e o
erro só aparece semanas depois.

Por isso aqui a conferência vem antes da contabilização: folha que não fecha
não vira lançamento nenhum, vai para revisão humana.

Layout observado (Contmatic Folha, Escon):
    Func: 1 CARLOS ALEXANDRE DE PAULA ...
    85 1 Pro-Labore 30 Dias 1.250,00   1950 3 INSS 11,00 % 137,50
    Proventos: 1.250,00 Vantagens: 0,00 Descontos: 137,50 Líquido: 1.112,50
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Marcador FORTE de rescisão. "rescis" solto aparece em folha comum (rubricas,
# rodapé do sistema) e fazia a folha inteira virar rescisão — os 27 empregados
# do Jorge foram parar em "Rescisão a pagar".
RE_RESCISAO = re.compile(
    r"(termo de rescis\w*\s+do\s+contrato|TRCT|termo de homologa\w*|"
    r"demonstrativo de rescis\w*)",
    re.IGNORECASE,
)
RE_FUNC = re.compile(r"Func:\s*(\d+)\s+(.+?)\s+Adm", re.IGNORECASE)
RE_TOTAIS = re.compile(
    r"Proventos:\s*([\d.,]+).*?Vantagens:\s*([\d.,]+).*?Descontos:\s*([\d.,]+).*?"
    r"L[ií]quido:\s*([\d.,]+)",
    re.IGNORECASE | re.DOTALL,
)
RE_COMPETENCIA = re.compile(r"Per[ií]odo:\s*\d{2}/(\d{2})/(\d{4})", re.IGNORECASE)
RE_VALOR = re.compile(r"[\d.]+,\d{2}")
# Linhas de cabeçalho trazem valores que NÃO são rubrica ("Salário: 1.250,00"
# no cargo, bases de imposto). Contá-las dobrava o provento.
PREFIXOS_CABECALHO = (
    "cargo:", "filial:", "empresa:", "endereco:", "endereço:", "bairro:",
    "inscricao", "inscrição", "base ", "bases", "normal", "irrf ", "inss ",
    "total rateio", "rateio:", "usuario:", "usuário:", "periodo:", "período:",
)

# rubrica → (natureza, alias da conta). Alias resolvido em plano_contas.yaml.
# Aprendido do razão real: pró-labore D 3212102 / C 2141102 e o INSS sai do
# passivo do pró-labore contra INSS a recolher.
RUBRICAS: list[tuple[tuple[str, ...], str, str]] = [
    # ---- verbas de rescisão ----
    # Indenizatórias não sofrem INSS/IRRF e têm conta própria; misturá-las com
    # salário distorce a base de encargos.
    (("aviso previo indenizado", "aviso previo ind"), "rescisao", "desp_aviso_previo"),
    (("ferias indenizadas", "ferias proporcionais", "ferias vencidas"),
     "rescisao", "desp_ferias"),
    (("13o proporcional", "13 proporcional", "gratificacao natalina prop"),
     "rescisao", "desp_13"),
    (("saldo de salario", "saldo salario"), "rescisao", "desp_salarios"),
    (("multa fgts", "multa 40", "multa rescisoria", "indenizacao 40"),
     "rescisao", "desp_multa_fgts"),

    (("pro-labore", "pro labore", "prolabore"), "provento", "desp_prolabore"),
    # "Horas Normais Diurnas" e o provento principal na folha da Escon — sem
    # esta chave o salario do mes nao era reconhecido, so os descontos.
    (("horas normais", "horas diurnas", "horas trabalhadas"), "provento", "desp_salarios"),
    (("hora extra", "horas extras", "he "), "provento", "desp_salarios"),
    (("salario", "salário", "ordenado"), "provento", "desp_salarios"),
    (("dsr", "descanso semanal"), "provento", "desp_salarios"),
    # "13" sozinho casava dentro de qualquer numero (137,50 virava 13o salario)
    (("13o salario", "13º salario", "decimo terceiro", "gratificacao natalina"),
     "provento", "desp_salarios"),
    (("ferias", "férias"), "provento", "desp_salarios"),
    (("inss",), "desconto", "inss_pagar"),
    (("irrf", "imposto de renda"), "desconto", "irrf_pagar"),
    (("vale transporte", "vale-transporte", "vt"), "desconto", "desp_vale_transp"),
    (("desconto adiantamento", "adiantamento salarial", "adiantamento"),
     "desconto", "salarios_pagar"),
    (("taxa assistencial", "contribuicao sindical", "mensalidade sindical",
      "contribuicao confederativa"), "desconto", "sindicato_pagar"),
    (("fgts",), "encargo", "fgts_pagar"),
]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).lower().strip()


def _num(t: str | None) -> float:
    if not t:
        return 0.0
    return float(t.replace(".", "").replace(",", "."))


@dataclass
class Rubrica:
    descricao: str
    valor: float
    natureza: str  # provento | desconto | encargo
    conta_alias: str | None


@dataclass
class Funcionario:
    codigo: str
    nome: str
    proventos: float = 0.0
    vantagens: float = 0.0
    descontos: float = 0.0
    liquido: float = 0.0
    rubricas: list[Rubrica] = field(default_factory=list)
    # socio recebe pro-labore, empregado recebe salario: contas diferentes.
    # O arquivo costuma trazer os dois juntos ("Folha de Pagamento e Pro labore").
    tipo: str = "folha"

    @property
    def fecha(self) -> bool:
        """proventos + vantagens - descontos == líquido (1 centavo de folga)."""
        return abs((self.proventos + self.vantagens - self.descontos) - self.liquido) <= 0.01

    @property
    def diferenca(self) -> float:
        return round((self.proventos + self.vantagens - self.descontos) - self.liquido, 2)


@dataclass
class Folha:
    competencia: str | None = None
    funcionarios: list[Funcionario] = field(default_factory=list)
    tipo: str = "folha"  # folha | prolabore

    @property
    def fecha(self) -> bool:
        return bool(self.funcionarios) and all(f.fecha for f in self.funcionarios)

    @property
    def total_proventos(self) -> float:
        return round(sum(f.proventos + f.vantagens for f in self.funcionarios), 2)

    @property
    def total_descontos(self) -> float:
        return round(sum(f.descontos for f in self.funcionarios), 2)

    @property
    def total_liquido(self) -> float:
        return round(sum(f.liquido for f in self.funcionarios), 2)


def _classificar_rubrica(descricao: str) -> tuple[str, str | None]:
    d = _norm(descricao)
    for chaves, natureza, alias in RUBRICAS:
        if any(k in d for k in chaves):
            return natureza, alias
    return "desconhecida", None


def ler_folha(texto: str) -> Folha:
    folha = Folha()
    if m := RE_COMPETENCIA.search(texto):
        folha.competencia = f"{m.group(2)}-{m.group(1)}"
    if "pro-labore" in _norm(texto) or "prolabore" in _norm(texto):
        folha.tipo = "prolabore"
    if RE_RESCISAO.search(texto):
        folha.tipo = "rescisao"

    # cada funcionário começa em "Func:" e vai até o próximo
    marcas = list(RE_FUNC.finditer(texto))
    for i, m in enumerate(marcas):
        ini = m.end()
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        bloco = texto[ini:fim]

        f = Funcionario(codigo=m.group(1), nome=m.group(2).strip()[:60])
        if tot := RE_TOTAIS.search(bloco):
            f.proventos, f.vantagens = _num(tot.group(1)), _num(tot.group(2))
            f.descontos, f.liquido = _num(tot.group(3)), _num(tot.group(4))

        # rubricas: linhas antes do bloco de totais
        corpo = bloco[: tot.start()] if tot else bloco
        for linha in corpo.splitlines():
            crua = linha.strip()
            if not crua or not RE_VALOR.search(crua):
                continue
            if _norm(crua).startswith(PREFIXOS_CABECALHO):
                continue  # cabeçalho, não rubrica
            # uma linha pode trazer provento e desconto juntos:
            # "85 1 Pro-Labore 30 Dias 1.250,00  1950 3 INSS 11,00 % 137,50"
            baixo = _norm(crua)
            usados: set[int] = set()  # posicao do valor ja atribuida a uma rubrica
            for chaves, natureza, alias in RUBRICAS:
                pos = min(
                    (baixo.find(k) for k in chaves if baixo.find(k) >= 0),
                    default=-1,
                )
                if pos < 0:
                    continue
                # valor da rubrica = primeiro número depois do nome dela
                seguinte = RE_VALOR.search(crua, pos)
                if not seguinte:
                    continue
                valor = _num(seguinte.group(0))
                # "INSS 11,00 %" — pula o percentual e pega o valor seguinte
                if "%" in crua[seguinte.end() : seguinte.end() + 4]:
                    depois = RE_VALOR.search(crua, seguinte.end())
                    valor = _num(depois.group(0)) if depois else valor
                if seguinte.start() in usados:
                    continue  # este valor ja foi de uma rubrica mais especifica
                if valor:
                    usados.add(seguinte.start())
                    f.rubricas.append(
                        Rubrica(descricao=crua[:70], valor=valor,
                                natureza=natureza, conta_alias=alias)
                    )

        # só entra quem tem número: página de cabeçalho não é funcionário
        if any(r.conta_alias == "desp_prolabore" for r in f.rubricas):
            f.tipo = "prolabore"
        if f.proventos or f.liquido:
            folha.funcionarios.append(f)
    return folha


def problemas(folha: Folha) -> list[str]:
    """O que impede de contabilizar. Lista vazia = pode lançar."""
    fora = []
    if not folha.funcionarios:
        fora.append("Nenhum funcionário reconhecido no arquivo.")
    for f in folha.funcionarios:
        if not f.fecha:
            fora.append(
                f"{f.nome}: proventos {f.proventos:.2f} - descontos {f.descontos:.2f} "
                f"≠ líquido {f.liquido:.2f} (diferença {f.diferenca:+.2f})"
            )
        if not f.rubricas:
            fora.append(f"{f.nome}: nenhuma rubrica reconhecida.")
    return fora


def resumo(folha: Folha) -> dict[str, Any]:
    return {
        "tipo": folha.tipo,
        "competencia": folha.competencia,
        "funcionarios": len(folha.funcionarios),
        "proventos": folha.total_proventos,
        "descontos": folha.total_descontos,
        "liquido": folha.total_liquido,
        "fecha": folha.fecha,
        "problemas": problemas(folha),
    }
