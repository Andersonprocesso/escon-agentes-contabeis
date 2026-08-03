"""Regras que a Raquel aplica a e-mail de quem NÃO é cliente.

Comparação literal de texto, sem LLM: previsível, auditável e de graça.

Segurança: a ação mais forte é mover para a Lixeira (Itens Excluídos), que é
reversível pelo Outlook. Nunca há exclusão definitiva — remover de vez é
decisão do humano, no cliente de e-mail.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Acao = Literal["lixeira", "ignorar", "arquivar", "nenhuma"]


@dataclass
class Regra:
    de: str | None
    dominio: str | None
    assunto_contem: str | None
    acao: Acao
    pasta: str | None
    motivo: str

    def combina(self, *, remetente: str, assunto: str) -> bool:
        rem = (remetente or "").strip().lower()
        asn = (assunto or "").strip().lower()
        # Todos os critérios preenchidos precisam bater (E, não OU) — regra vaga
        # apagando e-mail errado é pior que regra que não pega nada.
        if self.de and rem != self.de.strip().lower():
            return False
        if self.dominio and not rem.endswith("@" + self.dominio.strip().lower()):
            return False
        if self.assunto_contem and self.assunto_contem.strip().lower() not in asn:
            return False
        return any((self.de, self.dominio, self.assunto_contem))


def _parse_acao(bruto: Any) -> tuple[Acao, str | None]:
    if isinstance(bruto, dict):
        if "arquivar" in bruto:
            return "arquivar", str(bruto["arquivar"])
        raise ValueError(f"ação desconhecida: {bruto}")
    texto = str(bruto or "").strip().lower()
    if texto in ("lixeira", "ignorar"):
        return texto, None  # type: ignore[return-value]
    raise ValueError(f"ação desconhecida: {bruto!r} (use lixeira, ignorar ou arquivar: Pasta)")


def carregar(caminho: Path) -> list[Regra]:
    if not caminho.exists():
        return []
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    regras: list[Regra] = []
    for item in dados.get("regras") or []:
        quando = item.get("quando") or {}
        acao, pasta = _parse_acao(item.get("fazer"))
        regras.append(
            Regra(
                de=quando.get("de"),
                dominio=quando.get("dominio"),
                assunto_contem=quando.get("assunto_contem"),
                acao=acao,
                pasta=pasta,
                motivo=item.get("motivo") or "",
            )
        )
    return regras


def decidir(regras: list[Regra], *, remetente: str, assunto: str) -> Regra | None:
    """Primeira regra que combina vence."""
    for r in regras:
        if r.combina(remetente=remetente, assunto=assunto):
            return r
    return None
