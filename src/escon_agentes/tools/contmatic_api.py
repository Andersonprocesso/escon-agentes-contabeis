"""API Public do Contmatic Phoenix — https://api.contmatic.com.br/public

Autenticação: header `Authorization: Bearer <token>`. O token puro, sem
"Bearer", devolve 401 (apesar de a documentação declarar `apiKey`).

ATENÇÃO — o token atual é do produto **Acessórias** e o Contmatic recusa os
serviços do Contábil com: "O sistema ACESSORIA não pode usar este serviço."

    liberado:  /v1/clientes/self  /v1/empresas  /v1/usuarios
               /v1/metadatas  /v1/cargos  /v1/horarios
    bloqueado: /v1/planocontas/{apelido}/{ano}   (GET  — plano por empresa)
               /v1/lancamentos/{apelido}/{ano}   (POST — enviar lançamentos)

Para o Alexandre usar o plano de contas por empresa e mandar lançamento direto,
é preciso um token emitido para o sistema **Contábil**, não para o Acessórias.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://api.contmatic.com.br/public"


class ContmaticIndisponivel(RuntimeError):
    """Falha de autenticação, permissão ou rede na API do Contmatic."""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(token: str, caminho: str, params: dict | None = None) -> Any:
    if not token:
        raise ContmaticIndisponivel("CONTMATIC_TOKEN ausente no .env")
    with httpx.Client(timeout=60) as c:
        r = c.get(BASE + caminho, headers=_headers(token), params=params)
    if r.status_code == 401:
        raise ContmaticIndisponivel("Token inválido ou expirado (401)")
    if r.status_code == 422:
        detalhe = ""
        try:
            detalhe = r.json().get("detail", "")
        except Exception:  # noqa: BLE001
            pass
        raise ContmaticIndisponivel(
            f"Serviço recusado pelo Contmatic: {detalhe.strip() or '422'}"
        )
    if r.status_code != 200:
        raise ContmaticIndisponivel(f"{r.status_code} em {caminho}: {r.text[:200]}")
    return r.json()


def quem_sou(token: str) -> dict[str, Any]:
    return _get(token, "/v1/clientes/self")


def listar_empresas(token: str, *, ativo: bool | None = None) -> list[dict[str, Any]]:
    """Todas as empresas do escritório — traz `apelido`, que é a chave usada
    nos demais serviços (ex.: Escon = '0001')."""
    params: dict[str, Any] = {"size": 300}  # 300 e o maximo aceito; acima disso da 422
    if ativo is not None:
        params["ativo"] = ativo
    dados = _get(token, "/v1/empresas", params)
    return dados if isinstance(dados, list) else []


def plano_de_contas(token: str, apelido: str, ano: int) -> list[dict[str, Any]]:
    """Plano de contas da empresa no ano — cada item traz `reduzida`,
    `conta`, `descricao` e os históricos padrão vinculados.

    Hoje bloqueado para o token do Acessórias (ver aviso no topo do módulo).
    """
    dados = _get(token, f"/v1/planocontas/{apelido}/{ano}")
    return dados if isinstance(dados, list) else []


def montar_lancamento(
    *, data: str, valor: float, debito: int, credito: int, complemento: str
) -> dict[str, Any]:
    """Monta o corpo aceito por POST /v1/lancamentos/{apelido}/{ano}.

    Só monta — não envia. Mandar lançamento para o Contmatic é gravação em
    produção e depende de aprovação humana, além de um token do Contábil.
    """
    return {
        "data": data,
        "valor": round(float(valor), 2),
        "lancamentosDebitos": [
            {"reduzida": int(debito), "valor": round(float(valor), 2), "complemento": complemento}
        ],
        "lancamentosCreditos": [
            {"reduzida": int(credito), "valor": round(float(valor), 2), "complemento": complemento}
        ],
    }
