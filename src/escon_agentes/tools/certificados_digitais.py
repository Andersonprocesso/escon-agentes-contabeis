"""Certificados digitais A1 dos clientes — fonte de verdade é o Radar Escon
(tabela `credenciais_serpro`, tipo='certificado_a1'), lido via SSH (mesmo
padrão de radar_sync.py). Nunca lê o blob criptografado (senha/arquivo do
certificado) — só metadados (validade, fingerprint).

Cache local em data/certificados_digitais.json (mesmo padrão de certidoes.py)
para a Fernando/dashboard funcionarem mesmo sem SSH disponível no momento.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from escon_agentes.tools.radar_sync import DEFAULT_HOST, DEFAULT_KEY, DEFAULT_USER, _run_remote


def _path(data_dir: Path) -> Path:
    return data_dir / "certificados_digitais.json"


def load_local(data_dir: Path) -> list[dict[str, Any]]:
    path = _path(data_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_local(data_dir: Path, items: list[dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _path(data_dir).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_from_radar(
    *,
    host: str = DEFAULT_HOST,
    user: str = DEFAULT_USER,
    key: Path = DEFAULT_KEY,
) -> list[dict[str, Any]]:
    """Lê validade dos certificados A1 direto do Postgres do Radar (só metadados)."""
    script = r"""
docker exec radar-escon-db-1 psql -U radar -d radar -t -A -c "SELECT json_agg(row_to_json(t)) FROM (SELECT e.id::text AS radar_id, e.razao_social, e.cnpj_cpf, c.valido_ate::text AS valido_ate, c.fingerprint FROM credenciais_serpro c JOIN empresas e ON e.id = c.empresa_id WHERE c.tipo = 'certificado_a1' ORDER BY c.valido_ate ASC NULLS LAST) t;"
"""
    out = _run_remote(script, host=host, user=user, key=key).strip()
    m = re.search(r"\[.*\]", out, flags=re.S)
    if not m:
        return []
    return json.loads(m.group(0))


def attention_list(
    items: list[dict[str, Any]],
    *,
    clients_by_radar_id: dict[str, Any] | None = None,
    days_ahead: int = 15,
) -> list[dict[str, Any]]:
    today = date.today()
    clients_by_radar_id = clients_by_radar_id or {}
    alerts: list[dict[str, Any]] = []
    for it in items:
        val = it.get("valido_ate")
        if not val:
            continue
        try:
            d = date.fromisoformat(val[:10])
        except ValueError:
            continue
        dias = (d - today).days
        if dias > days_ahead:
            continue
        client = clients_by_radar_id.get(it.get("radar_id"))
        alerts.append(
            {
                **it,
                "dias": dias,
                "reason": "vencido" if dias < 0 else "a_vencer",
                "client_id": getattr(client, "id", None),
                "telefone": getattr(client, "telefone", None),
                "email": getattr(client, "email", None),
            }
        )
    return alerts


def draft_renewal_message(*, razao_social: str, valido_ate: str, dias: int, office_name: str) -> str:
    nome = razao_social.strip().title()
    validade_fmt = valido_ate
    try:
        validade_fmt = date.fromisoformat(valido_ate[:10]).strftime("%d/%m/%Y")
    except ValueError:
        pass
    if dias < 0:
        return (
            f"Olá! O certificado digital A1 da {nome} venceu em {validade_fmt} "
            f"({abs(dias)} dia(s) atrás) e precisa ser renovado com urgência para evitar "
            f"bloqueios em NF-e, eSocial e outras obrigações. A {office_name} já pode cuidar "
            f"da renovação — posso agendar?"
        )
    return (
        f"Olá! O certificado digital A1 da {nome} vence em {validade_fmt} "
        f"(em {dias} dia(s)). A {office_name} já pode providenciar a renovação para não haver "
        f"interrupção nas obrigações fiscais. Quer que a gente agende?"
    )


def summary_certificados(items: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> str:
    vencidos = sum(1 for a in alerts if a["reason"] == "vencido")
    a_vencer = sum(1 for a in alerts if a["reason"] == "a_vencer")
    lines = [
        f"Certificados A1 monitorados: {len(items)} | "
        f"Vencidos: {vencidos} | A vencer em até 15 dias: {a_vencer}"
    ]
    for a in alerts[:30]:
        lines.append(
            f"  - {a['razao_social']} | validade={a.get('valido_ate')} | "
            f"{a['reason']} ({a['dias']:+d}d) | cliente_local={a.get('client_id') or 'não achado'}"
        )
    return "\n".join(lines)
