"""Regras que o contador ensinou — o que o agente não sabia e agora sabe.

POR QUE EXISTE: o boleto de R$ 528 da Alumax não diz "honorário" em lugar
nenhum. Diz o beneficiário — DIAS DE PAULA ESCRITORIO DE APOIO, CNPJ
09.377.184/0001-88. Nenhuma regra genérica pegaria isso, e nenhum modelo
adivinharia com segurança. Quem sabe é a pessoa.

Então o caminho é: o documento fica pendente, a pessoa diz o que é uma vez, e
isso vira regra. Da segunda vez em diante é reconhecido de graça — inclusive
nos outros meses atrasados, que é onde está o ganho.

As regras aprendidas são avaliadas ANTES das genéricas: são correção humana
sobre um caso concreto e devem vencer o palpite geral.

Arquivo: config/regras_aprendidas.yaml (versionado — é conhecimento do
escritório, não dado operacional).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from escon_agentes.config import PROJECT_ROOT

ARQUIVO = PROJECT_ROOT / "config" / "regras_aprendidas.yaml"

# Palavras que aparecem em qualquer boleto e não identificam nada.
RUIDO = {
    "boleto", "pix", "pagador", "beneficiario", "vencimento", "valor", "documento",
    "agencia", "banco", "codigo", "nosso", "numero", "local", "pagamento", "ltda",
    "me", "epp", "sa", "eireli", "rua", "avenida", "cnpj", "cpf", "total", "data",
    "recebimento", "cobranca", "instrucoes", "autenticacao", "mecanica", "sacado",
    "quem", "vai", "receber", "pague", "sua", "leia", "seu", "celular", "qual",
    "endereco", "carteira", "especie", "aceite", "processamento", "juros",
    "multa", "desconto", "abatimento", "mora", "guia", "recolhimento",
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).upper().strip()


def carregar() -> list[dict[str, Any]]:
    if not ARQUIVO.exists():
        return []
    dados = yaml.safe_load(ARQUIVO.read_text(encoding="utf-8")) or {}
    return dados.get("regras") or []


def sugerir_chaves(texto: str, nome_arquivo: str = "") -> list[str]:
    """O que neste documento o identifica e vai se repetir no mês que vem.

    Ordem importa: CNPJ primeiro, porque é o único que não muda de grafia. Um
    nome de fornecedor pode vir com ou sem acento, abreviado, em caixa alta.
    """
    sugestoes: list[str] = []
    t = texto or ""

    # CNPJ de quem recebe — o identificador mais estável que existe
    for m in re.finditer(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", t):
        if m.group(0) not in sugestoes:
            sugestoes.append(m.group(0))

    # razão social: sequência longa de maiúsculas, sem o ruído de boleto
    for linha in _norm(t).splitlines() or [_norm(t)]:
        for trecho in re.findall(r"[A-Z][A-Z0-9 &.\-]{14,60}", linha):
            palavras = [p for p in trecho.split() if len(p) > 2]
            uteis = [p for p in palavras if p.lower() not in RUIDO]
            if len(uteis) >= 2:
                chave = " ".join(uteis[:4]).strip(" .-")
                if chave and chave not in sugestoes:
                    sugestoes.append(chave)

    if nome_arquivo:
        base = Path(nome_arquivo).stem
        if len(base) > 5 and base not in sugestoes:
            sugestoes.append(base)
    return sugestoes[:6]


def registrar(
    *,
    chave: str,
    debito: str,
    credito: str,
    descricao: str = "",
    historico: int = 0,
    tipo: str | None = None,
    confirmado_por: str = "painel",
    abre_titulo: str = "",
) -> dict[str, Any]:
    """Grava a regra. Chave repetida atualiza em vez de duplicar.

    Nunca grava sozinho: só é chamado quando a pessoa resolveu um pendente.
    Regra criada por adivinhação contamina todos os lançamentos seguintes.
    """
    chave = (chave or "").strip()
    if not chave:
        raise ValueError("Sem chave, a regra casaria com qualquer documento.")
    if not debito or not credito:
        raise ValueError("Débito e crédito são obrigatórios.")

    regras = carregar()
    nova = {
        "id": _id_para(chave),
        "quando": {"contem": [chave], **({"tipo": tipo} if tipo else {})},
        "debito": debito,
        "credito": credito,
        "historico": int(historico or 0),
        "descricao": descricao or f"Ensinado no painel: {chave}",
        "aprendida_em": date.today().isoformat(),
        "confirmado_por": confirmado_por,
    }
    if abre_titulo:
        nova["abre_titulo"] = abre_titulo

    regras = [r for r in regras if r.get("id") != nova["id"]]
    regras.append(nova)
    _gravar(regras)
    return nova


def esquecer(regra_id: str) -> bool:
    regras = carregar()
    restantes = [r for r in regras if r.get("id") != regra_id]
    if len(restantes) == len(regras):
        return False
    _gravar(restantes)
    return True


def _gravar(regras: list[dict[str, Any]]) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(
        "# Regras ensinadas pelo contador no painel.\n"
        "# Cada uma nasceu de um documento que ficou pendente e alguém explicou.\n"
        "# São avaliadas ANTES das regras genéricas de regras_lancamento.yaml.\n\n"
        + yaml.safe_dump(
            {"regras": regras}, allow_unicode=True, sort_keys=False, width=100
        ),
        encoding="utf-8",
    )


def _id_para(chave: str) -> str:
    limpo = re.sub(r"[^a-z0-9]+", "_", _norm(chave).lower()).strip("_")
    return f"aprendida_{limpo[:40]}"
