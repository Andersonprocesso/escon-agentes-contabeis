"""Plano de contas Contmatic (códigos reais da skill Contabilizador)."""

from __future__ import annotations

from typing import Any

import yaml

from escon_agentes.config import CONFIG_DIR

_CACHE: dict[str, Any] | None = None

# Fallback idêntico ao Contabilizador se o YAML não carregar
_FALLBACK_CONTAS = {
    "caixa": 1111101,
    "banco_itau": 1112201,
    "banco_bradesco": 1112202,
    "banco_cef": 1112203,
    "banco_inter": 1112204,
    "banco_bb": 1112205,
    "banco_santander": 1112206,
    "banco_sicoob": 1112207,
    "banco_mercadopago": 1112208,
    "banco_nubank": 1112211,
    "duplicatas_receber": 1121101,
    "inss_retido_fonte": 1131910,
    "fornecedores": 2111101,
    "simples_nacional": 2131101,
    "inss_pagar": 2131201,
    "fgts_pagar": 2131202,
    "salarios_pagar": 2141101,
    "prolabore_pagar": 2141202,
    "receita_produtos": 4111103,
    "receita_servicos": 4111201,
    "desp_prolabore": 4121101,
    "desp_inss_prolabore": 4121201,
    "desp_salarios": 4121301,
    "desp_fgts": 4121401,
    "desp_simples": 4121501,
    "desp_aluguel": 4122101,
    "desp_energia": 4122201,
    "desp_agua": 4122202,
    "desp_telefone": 4122301,
    "desp_honorario": 4122401,
    "desp_material_escr": 4122501,
    "desp_combustivel": 4122601,
    "desp_manutencao": 4122701,
    "desp_publicidade": 4122801,
    "desp_vale_transp": 4122901,
    "desp_alimentacao": 4123001,
    "desp_depreciacao": 4123101,
}

_FALLBACK_BANCOS = {
    "itau": "banco_itau",
    "bradesco": "banco_bradesco",
    "cef": "banco_cef",
    "inter": "banco_inter",
    "bb": "banco_bb",
    "santander": "banco_santander",
    "sicoob": "banco_sicoob",
    "nubank": "banco_nubank",
    "mercadopago": "banco_mercadopago",
}


def load_plano() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = CONFIG_DIR / "plano_contas.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {
            "contas": _FALLBACK_CONTAS,
            "bancos": _FALLBACK_BANCOS,
            "historicos": {},
        }
    data.setdefault("contas", _FALLBACK_CONTAS)
    data.setdefault("bancos", _FALLBACK_BANCOS)
    _CACHE = data
    return data


def contas() -> dict[str, int]:
    return dict(load_plano()["contas"])


def conta(nome: str) -> int:
    c = contas()
    if nome not in c:
        raise KeyError(f"Conta desconhecida no plano Contmatic: {nome}")
    return int(c[nome])


def banco_codigo(alias: str = "itau") -> int:
    plano = load_plano()
    key = (plano.get("bancos") or {}).get(alias.lower(), "banco_itau")
    return conta(key)


def historicos() -> dict[int, str]:
    h = load_plano().get("historicos") or {}
    return {int(k): str(v) for k, v in h.items()}


def as_contabilizador_c() -> dict[str, int]:
    """Dict no formato `C` do Contabilizador (para monkey-patch / testes)."""
    return contas()


def plcontas_index() -> dict[str, Any]:
    """Índice completo do PlContas.TXT importado do Escon_Lancamento."""
    from escon_agentes.tools.plcontas_parser import load_or_build_index

    return load_or_build_index()


def validar_codigo_contmatic(codigo: int | str) -> bool:
    from escon_agentes.tools.plcontas_parser import codigo_existe

    return codigo_existe(codigo)
