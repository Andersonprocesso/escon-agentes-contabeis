"""Classificação de CFOP — o que a nota realmente é.

POR QUE: o texto e a forma de pagamento enganam. Uma remessa para conserto,
uma bonificação e uma devolução parecem compra quando se olha só o emitente e
o valor — e viravam compra, criando conta a pagar que nunca seria paga.

O CFOP é a natureza declarada da operação, e é obrigatório. Ele diz, item a
item, se aquilo é venda, compra, devolução, remessa ou transferência. É a
informação certa para decidir se a nota **gera lançamento** e qual.

ESTRUTURA DO CÓDIGO
  1º dígito  = de onde vem / para onde vai
      1,2,3 = ENTRADA (1 mesmo estado, 2 outro estado, 3 exterior)
      5,6,7 = SAÍDA   (5 mesmo estado, 6 outro estado, 7 exterior)
  3 últimos  = a operação em si, e valem igual nos dois sentidos.

Por isso a tabela é indexada pelos 3 últimos dígitos, e o sentido vem do
primeiro. 201 é devolução nos dois casos: entrando é devolução de venda
(o cliente devolveu), saindo é devolução de compra (devolvemos ao fornecedor).

O QUE NÃO ESTÁ NA TABELA VIRA `desconhecido` E VAI PARA CONFERÊNCIA — nunca
é tratado como compra ou venda por presunção.
"""

from __future__ import annotations

from dataclasses import dataclass

# natureza -> gera lançamento de compra/venda automaticamente?
#   True  = contabiliza pela regra normal
#   False = não gera lançamento (a nota não é compra nem venda)
#   None  = gera, mas em conta diferente da rotina: mandar para conferência

VENDA = "venda"
COMPRA = "compra"
DEVOLUCAO_VENDA = "devolucao_venda"
DEVOLUCAO_COMPRA = "devolucao_compra"
BONIFICACAO = "bonificacao"
REMESSA = "remessa"
RETORNO = "retorno"
TRANSFERENCIA = "transferencia"
CUPOM = "cupom_fiscal"
ATIVO = "ativo_imobilizado"
USO_CONSUMO = "uso_consumo"
INDUSTRIALIZACAO = "industrializacao"
SERVICO = "servico"
FINANCEIRO = "financeiro"

# natureza -> (contabiliza, explicação para o humano)
NATUREZAS: dict[str, tuple[bool | None, str]] = {
    VENDA: (True, "Venda de mercadoria"),
    COMPRA: (True, "Compra de mercadoria"),
    DEVOLUCAO_VENDA: (None, "Devolução de venda — estorna receita, não é compra"),
    DEVOLUCAO_COMPRA: (None, "Devolução de compra — estorna a compra, não é venda"),
    BONIFICACAO: (None, "Bonificação/brinde/doação — sem contraprestação financeira"),
    REMESSA: (False, "Remessa — a mercadoria sai mas não é venda"),
    RETORNO: (False, "Retorno — a mercadoria volta, não é compra"),
    TRANSFERENCIA: (False, "Transferência entre estabelecimentos da empresa"),
    CUPOM: (False, "NF-e que apenas documenta cupons já lançados — lançar duplicaria"),
    ATIVO: (None, "Ativo imobilizado — vai para o imobilizado, não para compras"),
    USO_CONSUMO: (None, "Material de uso e consumo — despesa, não estoque"),
    INDUSTRIALIZACAO: (False, "Industrialização por encomenda — remessa/retorno"),
    SERVICO: (None, "Serviço (transporte, comunicação, energia) — conta própria"),
    FINANCEIRO: (False, "Operação sem circulação de mercadoria"),
}

# sufixo (3 últimos dígitos) -> natureza na ENTRADA, natureza na SAÍDA.
# Fonte: tabela CFOP do Convênio S/Nº de 1970 (Ajuste SINIEF 07/01).
_TABELA: dict[str, tuple[str, str]] = {}


def _reg(sufixos: str, entrada: str, saida: str) -> None:
    for s in sufixos.split():
        _TABELA[s] = (entrada, saida)


# --- compra e venda (o grosso do movimento) ---
_reg("101 102 103 104 105 106 109 110 111 112 113 114 115 116 117 118 119 120 "
     "122 123 124 125 128", COMPRA, VENDA)
# substituição tributária e diferimento: continua compra/venda
_reg("401 402 403 404 405", COMPRA, VENDA)
_reg("651 652 653 654 655 656 657 658", COMPRA, VENDA)  # combustíveis

# --- devolução / anulação ---
_reg("201 202 203 204 205 206 207 208 209 210 212", DEVOLUCAO_VENDA, DEVOLUCAO_COMPRA)
_reg("410 411 412 413 414 415", DEVOLUCAO_VENDA, DEVOLUCAO_COMPRA)  # ST
_reg("660 661 662 663 664 665 666 667", DEVOLUCAO_VENDA, DEVOLUCAO_COMPRA)
_reg("503 504 505", DEVOLUCAO_VENDA, DEVOLUCAO_COMPRA)  # anulação exportação

# --- bonificação, brinde, doação, amostra ---
_reg("910 911", BONIFICACAO, BONIFICACAO)

# --- remessa e retorno ---
_reg("901 902 903 924 925", INDUSTRIALIZACAO, INDUSTRIALIZACAO)
_reg("904 905 915 917 920 922 934", REMESSA, REMESSA)
_reg("906 907 916 918 919 921 923", RETORNO, RETORNO)
_reg("908 909 912 913 914", REMESSA, REMESSA)  # remessa p/ exposição, depósito etc.
_reg("931 932 933", SERVICO, SERVICO)

# --- transferência entre estabelecimentos ---
_reg("151 152 153 154 155 156 157 158 159", TRANSFERENCIA, TRANSFERENCIA)
_reg("408 409", TRANSFERENCIA, TRANSFERENCIA)
_reg("552 557", TRANSFERENCIA, TRANSFERENCIA)

# --- imobilizado e uso/consumo ---
_reg("551 553 554 555", ATIVO, ATIVO)
_reg("556 557", USO_CONSUMO, USO_CONSUMO)
_reg("406 407", ATIVO, ATIVO)  # ST sobre imobilizado/consumo

# --- serviços de transporte, comunicação e energia ---
_reg("251 252 253 254 255 256 257 258", SERVICO, SERVICO)  # energia
_reg("301 302 303 304 305 306 307", SERVICO, SERVICO)  # comunicação
_reg("351 352 353 354 355 356 357 359 360", SERVICO, SERVICO)  # transporte

# --- CFOP que documenta cupom fiscal já lançado ---
# 5929/1929: "lançamento efetuado em decorrência de emissão de documento
# fiscal relativo a operação registrada em equipamento ECF/SAT". A venda já
# entrou pelo cupom; lançar a NF-e de novo dobraria a receita.
_reg("929 928", CUPOM, CUPOM)

# --- sem circulação / regularização ---
_reg("949", "", "")  # "outra entrada/saída não especificada": ambíguo de propósito
_reg("605 606 601 602 603", FINANCEIRO, FINANCEIRO)  # transferência de crédito
_reg("926 927", FINANCEIRO, FINANCEIRO)  # ativo imobilizado / baixa por perda


@dataclass
class CfopInfo:
    codigo: str
    sentido: str  # entrada | saida | desconhecido
    natureza: str  # venda | compra | devolucao_* | ...
    contabiliza: bool | None  # True | False | None (revisar)
    descricao: str

    @property
    def gera_lancamento(self) -> bool:
        return self.contabiliza is True

    @property
    def precisa_revisao(self) -> bool:
        return self.contabiliza is None


def classificar(codigo: str | None, sentido: str | None = None) -> CfopInfo:
    """Diz o que aquele CFOP é. Código fora da tabela vira `desconhecido`.

    `sentido` é o NOSSO lado da operação ("entrada" se o cliente é o
    destinatário, "saida" se é o emitente) e prevalece sobre o primeiro dígito.

    Isso não é detalhe: **o CFOP é escrito por quem emitiu a nota**. A nota de
    compra que o cliente recebe do fornecedor vem com 5102 — venda, na ótica do
    fornecedor. Ler o primeiro dígito faria toda compra virar venda. O que vale
    é o sufixo (a operação) combinado com o lado em que o cliente está.
    """
    c = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(c) != 4:
        return CfopInfo(c, sentido or "desconhecido", "desconhecido", None,
                        "CFOP ausente ou malformado — conferir a nota")
    if sentido not in ("entrada", "saida"):
        sentido = "entrada" if c[0] in "123" else ("saida" if c[0] in "567" else "desconhecido")
    par = _TABELA.get(c[1:])
    if not par:
        return CfopInfo(c, sentido, "desconhecido", None,
                        f"CFOP {c} não está na tabela — classificar manualmente")
    natureza = par[0] if sentido == "entrada" else par[1]
    if not natureza:
        return CfopInfo(c, sentido, "desconhecido", None,
                        f"CFOP {c} é genérico ('outras') — depende do que foi movimentado")
    contabiliza, descricao = NATUREZAS.get(natureza, (None, natureza))
    return CfopInfo(c, sentido, natureza, contabiliza, descricao)


def resumir(codigos: list[str], sentido: str | None = None) -> CfopInfo:
    """A natureza da nota inteira, a partir dos CFOP dos itens.

    Nota com CFOP misturado (venda + bonificação na mesma nota, por exemplo)
    não é decidida por maioria: vai para conferência. Dividir o valor entre
    naturezas diferentes exige olhar item a item, e chutar ali erraria o valor
    de cada conta.
    """
    infos = [classificar(c, sentido) for c in codigos if c]
    if not infos:
        return CfopInfo("", sentido or "desconhecido", "desconhecido", None,
                        "Nota sem CFOP — conferir")
    naturezas = {i.natureza for i in infos}
    if len(naturezas) == 1:
        return infos[0]
    return CfopInfo(
        "/".join(sorted({i.codigo for i in infos}))[:40],
        infos[0].sentido, "misto", None,
        "Nota com CFOP de naturezas diferentes ("
        + ", ".join(sorted(naturezas)) + ") — separar item a item",
    )
