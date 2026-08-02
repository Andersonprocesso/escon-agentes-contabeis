"""Cliente da API do Sistema Acessórias — fonte de verdade do cadastro (Pedro Henrique).

Só HTTP puro (httpx), sem LLM: buscar/gravar cadastro é determinístico e não
deve gastar token. A API cria e atualiza pelo mesmo POST /companies e não expõe
DELETE — exclusão continua manual no sistema deles.

Docs: https://api.acessorias.com/documentation
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

BASE_URL = "https://api.acessorias.com"
PAGE_SIZE = 20
RATE_LIMIT_SLEEP = 0.7  # 100 req/min => ~0.6s; folga para não tomar 429

# Contatos do próprio escritório presentes em quase toda empresa (o Anderson os
# cadastra de propósito para receber cópia dos envios de documento via
# Acessórias). Não são contato do cliente e nunca devem virar e-mail do cadastro.
OFFICE_CONTACT_EMAILS = {"anjubiel.anju@gmail.com"}
OFFICE_CONTACT_NAME_HINTS = ("escondigital",)


class AcessoriasUnavailable(RuntimeError):
    """Token ausente ou falha de comunicação com a API."""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _get(token: str, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    try:
        with httpx.Client(timeout=45) as client:
            r = client.get(url, headers=_headers(token), params=params or {})
    except httpx.HTTPError as e:
        raise AcessoriasUnavailable(f"Falha de rede em {path}: {e}") from e

    if r.status_code == 401:
        raise AcessoriasUnavailable("Token inválido/expirado (401) — gere outro no Acessórias")
    if r.status_code == 429:
        raise AcessoriasUnavailable("Limite de 100 req/min excedido (429) — aguarde e repita")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise AcessoriasUnavailable(f"{path} devolveu {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise AcessoriasUnavailable(f"Resposta não-JSON em {path}: {r.text[:200]}") from e


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """A API pode devolver lista direta ou envelope {data|empresas|companies: [...]}"""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "empresas", "companies", "result", "items"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
        # objeto único
        if any(k in payload for k in ("cnpj", "CNPJ", "nome", "Nome")):
            return [payload]
    return []


def iter_companies(
    token: str,
    *,
    include: tuple[str, ...] = ("contacts", "registrationData", "stateRegistrations"),
    ativa: str | None = None,
    max_pages: int = 200,
) -> Iterator[dict[str, Any]]:
    """Percorre GET /companies/ListAll paginado (20/página) até vir página vazia."""
    params: dict[str, Any] = {k: "1" for k in include}
    if ativa:
        params["ativa"] = ativa

    for page in range(1, max_pages + 1):
        payload = _get(token, "/companies/ListAll", {**params, "Pagina": page})
        rows = _unwrap_list(payload)
        if not rows:
            return
        yield from rows
        if len(rows) < PAGE_SIZE:
            return
        time.sleep(RATE_LIMIT_SLEEP)


def fetch_all_companies(token: str, **kwargs: Any) -> list[dict[str, Any]]:
    return list(iter_companies(token, **kwargs))


def get_company(token: str, identificador: str, *, include: tuple[str, ...] = ()) -> dict[str, Any] | None:
    params = {k: "1" for k in include}
    payload = _get(token, f"/companies/{only_digits(identificador) or identificador}", params)
    rows = _unwrap_list(payload)
    return rows[0] if rows else None


def upsert_company(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST /companies — cria ou atualiza. Exige cnpj, nome, fantasia."""
    faltando = [k for k in ("cnpj", "nome", "fantasia") if not payload.get(k)]
    if faltando:
        raise AcessoriasUnavailable(f"Campos obrigatórios ausentes: {', '.join(faltando)}")
    try:
        with httpx.Client(timeout=45) as client:
            r = client.post(f"{BASE_URL}/companies", headers=_headers(token), json=payload)
    except httpx.HTTPError as e:
        raise AcessoriasUnavailable(f"Falha de rede no POST /companies: {e}") from e

    if r.status_code == 401:
        raise AcessoriasUnavailable("Token inválido/expirado (401)")
    if r.status_code == 429:
        raise AcessoriasUnavailable("Limite de 100 req/min excedido (429)")
    if r.status_code not in (200, 201):
        raise AcessoriasUnavailable(f"POST /companies devolveu {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except json.JSONDecodeError:
        return {"ok": True}


def _pick(row: dict[str, Any], *names: str) -> Any:
    """Campos da API vêm com capitalização inconsistente entre endpoints."""
    for n in names:
        for key in (n, n.lower(), n.upper(), n.capitalize()):
            if key in row and row[key] not in (None, ""):
                return row[key]
    return None


def parse_regime(texto: str | None) -> str | None:
    """O ListAll devolve o regime como texto descritivo, não como o inteiro 0-10
    que a documentação sugere. Ex.: 'MEI - Sem Funcionário',
    'Simples Nacional - Comércio e ou Serviço - Com Pré-labore - Com Funcionários'.
    """
    if not texto:
        return None
    low = str(texto).strip().lower()
    if low.startswith("mei"):
        return "mei"
    if "simples" in low:
        return "simples_nacional"
    if "presumido" in low:
        return "lucropresumido"
    if "real" in low:
        return "lucroreal"
    return None


def is_office_contact(contato: dict[str, Any]) -> bool:
    email = str(_pick(contato, "E-mail", "email", "Email") or "").strip().lower()
    nome = str(_pick(contato, "Nome", "nome") or "").strip().lower()
    if email in OFFICE_CONTACT_EMAILS:
        return True
    return any(h in nome for h in OFFICE_CONTACT_NAME_HINTS)


def normalize_company(row: dict[str, Any]) -> dict[str, Any]:
    """Achata um registro do Acessórias no vocabulário usado pelos agentes."""
    cnpj = only_digits(str(_pick(row, "Identificador", "cnpj", "CNPJ") or ""))
    regime_raw = _pick(row, "Regime", "regime")

    # e-mail/celular do cliente: primeiro contato que não seja o do escritório
    email = None
    celular = None
    for c in _pick(row, "ContatosNaEmpresa", "contacts", "contatos") or []:
        if not isinstance(c, dict) or is_office_contact(c):
            continue
        email = email or (str(_pick(c, "E-mail", "email") or "").strip() or None)
        celular = celular or (str(_pick(c, "Celular", "celular", "fone") or "").strip() or None)

    telefone = _pick(row, "Telefone", "telefone", "fone") or celular
    status = str(_pick(row, "Status", "ativa") or "").strip()

    ies = _pick(row, "InscricoesEstaduais", "stateRegistrations") or []
    inscricao_estadual = None
    if isinstance(ies, list) and ies and isinstance(ies[0], dict):
        inscricao_estadual = _pick(ies[0], "IE", "ie")

    return {
        "acessorias_id": _pick(row, "ID", "id"),
        "cnpj": cnpj,
        "nome": str(_pick(row, "Razao", "nome", "razaosocial") or "").strip(),
        "fantasia": str(_pick(row, "Fantasia", "fantasia") or "").strip(),
        "regime": parse_regime(regime_raw),
        "regime_raw": regime_raw,
        "uf": _pick(row, "UF", "uf"),
        "email": email,
        "telefone": only_digits(str(telefone)) or None,
        "ativa": status.lower().startswith("ativ") if status else None,
        "status_raw": status or None,
        "inscricao_estadual": inscricao_estadual,
        "grupo": _pick(row, "GrupoDeEmpresas", "grupo"),
        "honorario": _pick(row, "Honorario", "honorario"),
        "cliente_desde": _pick(row, "ClienteDesde"),
        "cliente_ate": _pick(row, "ClienteAte"),
        "data_cadastro": _pick(row, "DataDoCadastro"),
    }


def save_snapshot(data_dir: Path, rows: list[dict[str, Any]]) -> Path:
    """Guarda o retorno bruto para diff/reprocesso sem gastar chamada nem token."""
    path = data_dir / "acessorias_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "acessorias_snapshot.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
