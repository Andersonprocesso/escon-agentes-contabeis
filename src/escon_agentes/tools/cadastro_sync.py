"""Motor de sincronização de cadastro (Pedro Henrique).

Acessórias = fonte de verdade. Compara em bloco contra o cadastro local dos
agentes e contra o Radar, e devolve um plano de mudanças. Tudo determinístico:
nenhuma chamada de LLM aqui — sincronizar 87 empresas custa zero token.

Política (definida pelo Anderson):
  - criação de empresa que não existe no destino → pode aplicar
  - alteração de empresa existente → só com confirmação humana
  - exclusão → nunca automática (a API do Acessórias nem expõe DELETE)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from escon_agentes.schema import ClientProfile
from escon_agentes.tools.acessorias import normalize_company, only_digits
from escon_agentes.tools.radar_import import drive_hint, format_cnpj

# Campos em que o Acessórias manda e pode sobrescrever o valor local.
SYNCED_FIELDS = ("name", "cnpj", "regime", "uf", "email")

# Campos que só são preenchidos quando o local está vazio — nunca sobrescrevem.
# `telefone`: o campo Telefone do Acessórias é o contato-de-registro do
# escritório e se repete em dezenas de empresas (30 números distintos para 113
# empresas), enquanto o telefone vindo do Radar é individual. Sobrescrever
# quebraria a cobrança de extratos do Greg no WhatsApp.
FILL_ONLY_FIELDS = ("telefone",)


def _norm_text(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


# O Radar usa um vocabulário curto (simples|presumido|real|mei); o cadastro
# local usa o longo. Comparar como texto marcaria as 87 empresas como
# "regime mudou" a cada execução e proporia sobrescrever o Radar à toa.
REGIME_PARA_RADAR = {
    "simples_nacional": "simples",
    "simples": "simples",
    "mei": "mei",
    "lucropresumido": "presumido",
    "presumido": "presumido",
    "lucroreal": "real",
    "real": "real",
}


def regime_para_radar(regime: str | None) -> str | None:
    if not regime:
        return None
    return REGIME_PARA_RADAR.get(str(regime).strip().lower())


def _same(a: Any, b: Any, *, field: str) -> bool:
    if field == "regime":
        return regime_para_radar(a) == regime_para_radar(b)
    if field in ("telefone",):
        return only_digits(str(a or "")) == only_digits(str(b or ""))
    if field == "cnpj":
        return only_digits(str(a or "")) == only_digits(str(b or ""))
    if field == "email":
        return _norm_text(a).lower() == _norm_text(b).lower()
    if field == "name":
        return _norm_text(a).upper() == _norm_text(b).upper()
    return _norm_text(a) == _norm_text(b)


def build_local_plan(
    acessorias_rows: list[dict[str, Any]],
    clients: list[ClientProfile],
) -> dict[str, Any]:
    """Diff Acessórias → cadastro local dos agentes (data/clients/*.json)."""
    by_cnpj = {only_digits(c.cnpj or c.id): c for c in clients}

    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    unchanged = 0
    sem_cnpj: list[dict[str, Any]] = []
    inativas: list[dict[str, Any]] = []

    for raw in acessorias_rows:
        src = normalize_company(raw)
        cnpj = src["cnpj"]
        if not cnpj:
            sem_cnpj.append({"nome": src["nome"], "motivo": "sem CNPJ/CPF no Acessórias"})
            continue
        # Empresa baixada/encerrada no Acessórias (Status != Ativa) não entra no
        # cadastro nem no Radar — monitorar CNPJ baixado gera consulta inútil e
        # polui a carteira. Só reportamos para o humano decidir o que fazer com
        # quem já estava cadastrado antes.
        if src.get("ativa") is False:
            inativas.append(
                {"cnpj": cnpj, "nome": src["nome"], "ja_no_cadastro": cnpj in by_cnpj}
            )
            continue

        existing = by_cnpj.get(cnpj)
        desired = {
            "name": src["nome"] or (existing.name if existing else ""),
            "cnpj": format_cnpj(cnpj),
            "regime": src["regime"],
            "uf": src["uf"],
            "telefone": src["telefone"],
            "email": src["email"],
        }
        # campo vazio no Acessórias não apaga dado já existente localmente
        desired = {k: v for k, v in desired.items() if v not in (None, "")}

        if existing is None:
            to_create.append({"cnpj": cnpj, "source": src, "fields": desired})
            continue

        diffs = {}
        for field, new_value in desired.items():
            old_value = getattr(existing, field, None)
            if field in FILL_ONLY_FIELDS and _norm_text(old_value):
                continue  # já preenchido localmente: Acessórias não sobrescreve
            if not _same(old_value, new_value, field=field):
                diffs[field] = {"de": old_value, "para": new_value}
        if diffs:
            to_update.append(
                {"client_id": existing.id, "nome": existing.name, "cnpj": cnpj, "diffs": diffs}
            )
        else:
            unchanged += 1

    acessorias_cnpjs = {only_digits(normalize_company(r)["cnpj"]) for r in acessorias_rows}
    only_local = [
        {"client_id": c.id, "nome": c.name, "cnpj": c.cnpj}
        for c in clients
        if only_digits(c.cnpj or c.id) not in acessorias_cnpjs
    ]

    return {
        "destino": "cadastro local (data/clients)",
        "to_create": to_create,
        "to_update": to_update,
        "unchanged": unchanged,
        "only_in_local": only_local,
        "sem_cnpj": sem_cnpj,
        "inativas": inativas,
    }


def build_radar_plan(
    acessorias_rows: list[dict[str, Any]],
    radar_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Diff Acessórias → Radar. Nunca aplica: só descreve o que mudaria."""
    by_cnpj = {only_digits(str(r.get("cnpj_cpf") or "")): r for r in radar_rows}

    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    unchanged = 0
    inativas: list[dict[str, Any]] = []

    for raw in acessorias_rows:
        src = normalize_company(raw)
        cnpj = src["cnpj"]
        if not cnpj:
            continue
        if src.get("ativa") is False:  # baixada no Acessórias — não vai para o Radar
            inativas.append(
                {"cnpj": cnpj, "nome": src["nome"], "ja_no_radar": cnpj in by_cnpj}
            )
            continue
        existing = by_cnpj.get(cnpj)
        if existing is None:
            to_create.append(
                {
                    "cnpj": cnpj,
                    "razao_social": src["nome"],
                    "uf": src["uf"],
                    "regime_tributario": regime_para_radar(src["regime"]),
                }
            )
            continue

        diffs = {}
        if src["nome"] and not _same(existing.get("razao_social"), src["nome"], field="name"):
            diffs["razao_social"] = {"de": existing.get("razao_social"), "para": src["nome"]}
        if src["uf"] and not _same(existing.get("uf"), src["uf"], field="uf"):
            diffs["uf"] = {"de": existing.get("uf"), "para": src["uf"]}
        if src["regime"] and not _same(existing.get("regime_tributario"), src["regime"], field="regime"):
            diffs["regime_tributario"] = {
                "de": existing.get("regime_tributario"),
                "para": regime_para_radar(src["regime"]),
            }
        if diffs:
            to_update.append(
                {
                    "radar_id": existing.get("radar_id"),
                    "razao_social": existing.get("razao_social"),
                    "cnpj": cnpj,
                    "diffs": diffs,
                }
            )
        else:
            unchanged += 1

    return {
        "destino": "Radar Escon (Postgres VPS)",
        "to_create": to_create,
        "to_update": to_update,
        "unchanged": unchanged,
        "inativas": inativas,
        "politica": "somente leitura nesta versão — aplicar exige confirmação humana",
    }


def apply_local_plan(
    plan: dict[str, Any],
    *,
    clients_dir: Path,
    inbox_root: Path,
    allow_updates: bool = False,
) -> dict[str, Any]:
    """Aplica no cadastro local. Criações livres; alterações só com allow_updates."""
    from escon_agentes.tools.clients import client_inbox, get_client, save_client

    created: list[str] = []
    updated: list[str] = []

    for item in plan.get("to_create", []):
        src = item["source"]
        cnpj = item["cnpj"]
        profile = ClientProfile(
            id=cnpj,
            name=src["nome"],
            cnpj=format_cnpj(cnpj),
            regime=src["regime"] or "simples_nacional",
            telefone=src["telefone"],
            email=src["email"],
            contatos={
                k: v
                for k, v in {
                    "telefone": src["telefone"],
                    "whatsapp": src["telefone"],
                    "email": src["email"],
                }.items()
                if v
            },
            tags=["acessorias"],
            uf=src["uf"],
            drive_folder_hint=drive_hint(src["nome"]),
            source="acessorias",
        )
        save_client(clients_dir, profile)
        client_inbox(inbox_root, profile.id)
        created.append(profile.id)

    if allow_updates:
        for item in plan.get("to_update", []):
            client = get_client(clients_dir, item["client_id"])
            if not client:
                continue
            patch = {field: change["para"] for field, change in item["diffs"].items()}
            contatos = dict(client.contatos or {})
            if "telefone" in patch:
                contatos["telefone"] = patch["telefone"]
                contatos.setdefault("whatsapp", patch["telefone"])
            if "email" in patch:
                contatos["email"] = patch["email"]
            patch["contatos"] = contatos
            save_client(clients_dir, client.model_copy(update=patch))
            updated.append(client.id)

    return {"created": created, "updated": updated}


def save_plan(data_dir: Path, plan: dict[str, Any]) -> Path:
    path = data_dir / "cadastro_sync_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"gerado_em": datetime.now().isoformat(timespec="seconds"), **plan}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def summarize(local_plan: dict[str, Any], radar_plan: dict[str, Any] | None = None) -> str:
    inativas = local_plan.get("inativas") or []
    lines = [
        f"Cadastro local: +{len(local_plan['to_create'])} nova(s), "
        f"~{len(local_plan['to_update'])} com divergência, "
        f"={local_plan['unchanged']} iguais, "
        f"{len(local_plan['only_in_local'])} só no local (não estão no Acessórias)."
    ]
    if local_plan.get("sem_cnpj"):
        lines.append(f"  ! {len(local_plan['sem_cnpj'])} empresa(s) sem CNPJ no Acessórias — ignoradas.")
    if radar_plan:
        lines.append(
            f"Radar: +{len(radar_plan['to_create'])} faltando, "
            f"~{len(radar_plan['to_update'])} com divergência, "
            f"={radar_plan['unchanged']} iguais."
        )
    return "\n".join(lines)
