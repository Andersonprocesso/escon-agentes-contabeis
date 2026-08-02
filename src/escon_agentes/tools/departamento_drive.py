"""Classifica um documento no departamento do Drive usado pelo Radar.

Convenção do Radar (backend/app/services/storage.py):
    {Empresa}/{Departamento}/{Ano}/{MM-AAAA}/{arquivo}

A classificação lê o CONTEÚDO, nunca o nome do arquivo: uma NFS-e chamada
"NotaFiscal ... - JUREMA ÁGUA QUENTE.pdf" parece nota de entrada, mas o
emitente é o próprio cliente e o "JUREMA" é o tomador — arquivar pelo nome
colocaria uma nota de saída na pasta de entrada.

Na dúvida devolve None: documento fiscal na pasta errada é pior que documento
esperando triagem humana.
"""

from __future__ import annotations

import re
import unicodedata

# Mesmos nomes de pasta que o Radar cria — não inventar variações.
DEPTO_IMPOSTOS = "Impostos"
DEPTO_RECIBOS = "Recibos"
DEPTO_NF_ENTRADA = "Notas Fiscais-Entrada"
DEPTO_NF_SAIDA = "Notas Fiscais-Saida"
DEPTO_NF_SERVICO = "Notas Fiscais-Servico"
DEPTO_ESOCIAL = "eSocial"
DEPTO_ECAC = "Caixa Postal e-CAC"
DEPTO_COMPROVANTES = "Comprovantes de Pagamento"
DEPTO_SITUACAO = "Situação Fiscal"
DEPTO_EXTRATOS = "Extratos"


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).lower()


def so_digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _cnpj_do_emitente(texto: str) -> str | None:
    """Pega o CNPJ que aparece logo após o bloco do emitente/prestador."""
    for marcador in ("EMITENTE DA NFS-e", "EMITENTE", "PRESTADOR DE SERVICO", "PRESTADOR"):
        idx = _norm(texto).find(_norm(marcador))
        if idx < 0:
            continue
        trecho = texto[idx : idx + 400]
        m = re.search(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b", trecho)
        if m:
            return so_digitos(m.group(1))
    return None


def classificar(texto: str, *, cnpj_cliente: str | None = None) -> tuple[str | None, str]:
    """Devolve (departamento, motivo). departamento=None → precisa de humano."""
    baixo = _norm(texto)
    cnpj_cliente = so_digitos(cnpj_cliente)

    if any(k in baixo for k in ("nfs-e", "nota fiscal de servicos", "nota fiscal de servico")):
        emitente = _cnpj_do_emitente(texto)
        if cnpj_cliente and emitente == cnpj_cliente:
            return DEPTO_NF_SERVICO, "NFS-e emitida pelo próprio cliente (serviço prestado)"
        if cnpj_cliente and emitente and emitente != cnpj_cliente:
            return DEPTO_NF_ENTRADA, "NFS-e de terceiro para o cliente (serviço tomado)"
        return DEPTO_NF_SERVICO, "NFS-e, sem confirmar emitente"

    if "danfe" in baixo or "nota fiscal eletronica" in baixo:
        emitente = _cnpj_do_emitente(texto)
        if cnpj_cliente and emitente == cnpj_cliente:
            return DEPTO_NF_SAIDA, "NF-e emitida pelo cliente"
        if cnpj_cliente and emitente and emitente != cnpj_cliente:
            return DEPTO_NF_ENTRADA, "NF-e de fornecedor"
        return None, "NF-e sem identificar emitente — precisa de conferência"

    if any(k in baixo for k in ("extrato", "saldo anterior", "lancamentos do periodo")):
        return DEPTO_EXTRATOS, "extrato bancário"
    if any(k in baixo for k in ("das - documento de arrecadacao", "darf", "guia da previdencia", "documento de arrecadacao")):
        return DEPTO_IMPOSTOS, "guia de arrecadação"
    if "comprovante" in baixo and any(k in baixo for k in ("pagamento", "transferencia", "pix")):
        return DEPTO_COMPROVANTES, "comprovante de pagamento"
    if "esocial" in baixo:
        return DEPTO_ESOCIAL, "eSocial"
    if any(k in baixo for k in ("caixa postal", "e-cac", "mensagem enviada pela rfb")):
        return DEPTO_ECAC, "comunicado e-CAC"
    if "recibo" in baixo:
        return DEPTO_RECIBOS, "recibo"

    return None, "tipo não reconhecido — precisa de triagem humana"
