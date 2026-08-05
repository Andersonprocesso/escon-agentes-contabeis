"""Parser do export Contmatic PlContas.TXT (modelo Escon_Lancamento)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from escon_agentes.config import PROJECT_ROOT

# Na VPS o volume monta em /app/data e o deploy não envia data/ (clientes e
# planilhas vivem só no volume). O PlContas.TXT vai em config/ para entrar no
# image/deploy; data/models/ continua válido no PC de desenvolvimento.
def _achar_plcontas() -> Path:
    candidatos = (
        PROJECT_ROOT / "config" / "PlContas.TXT",
        PROJECT_ROOT / "data" / "models" / "PlContas.TXT",
    )
    for p in candidatos:
        if p.exists():
            return p
    return candidatos[0]


DEFAULT_PLCONTAS = _achar_plcontas()
DEFAULT_CACHE = PROJECT_ROOT / "data" / "models" / "plcontas_index.json"

# Ex. balanço:   1.1.1.01.001.00001   Caixa Geral            1111101    0000...D01
# Ex. resultado: 3.1.1.01.002.00001   Salarios e ordenados   3111201C   0000...D04
#
# As contas de resultado trazem uma letra colada na reduzida (C, A, …). Exigir
# espaço logo depois fazia o parser descartar TODAS as contas 3xxx e 4xxx em
# silêncio — o plano parecia ter só Ativo e Passivo.
_LINE_RE = re.compile(
    r"^(?P<analitica>\d(?:\.\d+){5})\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<reduzida>\d{7})(?P<sufixo>[A-Z]?)\s+"
)


def parse_plcontas_text(text: str) -> list[dict[str, Any]]:
    contas: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        m = _LINE_RE.search(line)
        if not m:
            # fallback: linhas com código reduzido no meio
            m2 = re.search(
                r"^(?P<analitica>\d[\d.]+)\s+(?P<descricao>.+?)\s+(?P<reduzida>\d{7})\b",
                line,
            )
            if not m2:
                continue
            m = m2
        reduzida = int(m.group("reduzida"))
        if reduzida in seen:
            continue
        # ignora sinteticas com reduzida 0? já filtramos 7 dígitos
        desc = re.sub(r"\s+", " ", m.group("descricao")).strip()
        if not desc or desc.upper() in {"ATIVO", "PASSIVO"}:
            # ainda pode ser conta útil se tem código — mantém
            pass
        analitica = m.group("analitica").strip()
        # só contas com último segmento != 00000 costumam ser analíticas
        if analitica.endswith(".00000") or analitica.endswith(".000.00000"):
            # no arquivo, sinteticas muitas vezes NÃO têm 7 dígitos; se tiver, pular
            if ".00000" in analitica and not re.search(r"\.\d{5}$", analitica):
                continue
        # filtra grupos: reduzida presente e descrição não vazia
        if len(desc) < 2:
            continue
        seen.add(reduzida)
        contas.append(
            {
                "reduzida": reduzida,
                "analitica": analitica,
                "descricao": desc,
                "grupo": analitica.split(".")[0] if analitica else "",
            }
        )
    return contas


def parse_plcontas_file(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or DEFAULT_PLCONTAS
    if not path.exists():
        raise FileNotFoundError(f"PlContas não encontrado: {path}")
    # Contmatic export costuma ser Latin-1 / CP1252
    raw = path.read_bytes()
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1", errors="replace")
    return parse_plcontas_text(text)


def build_index(contas: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = {str(c["reduzida"]): c for c in contas}
    by_desc: dict[str, int] = {}
    for c in contas:
        key = c["descricao"].casefold()
        by_desc.setdefault(key, c["reduzida"])
    return {
        "total": len(contas),
        "source": "PlContas.TXT (Contmatic / Escon_Lancamento)",
        "by_code": by_code,
        "by_descricao": by_desc,
        "contas": contas,
    }


def load_or_build_index(
    plcontas_path: Path | None = None,
    cache_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    cache_path = cache_path or DEFAULT_CACHE
    plcontas_path = plcontas_path or _achar_plcontas()
    if cache_path.exists() and not force:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("total"):
                return data
        except json.JSONDecodeError:
            pass
    contas = parse_plcontas_file(plcontas_path)
    index = build_index(contas)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # volume só-leitura ou path sem permissão: o índice em memória basta
        pass
    return index


def lookup_codigo(descricao: str, index: dict[str, Any] | None = None) -> int | None:
    idx = index or load_or_build_index()
    return idx.get("by_descricao", {}).get(descricao.casefold())


def codigo_existe(codigo: int | str, index: dict[str, Any] | None = None) -> bool:
    idx = index or load_or_build_index()
    return str(codigo) in idx.get("by_code", {})
