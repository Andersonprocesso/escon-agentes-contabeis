"""Extração de dados de PDFs e textos para lançamento contábil."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExtractedDoc:
    path: str
    doc_type: str
    valor: str | None
    data: str | None
    cnpj: str | None
    descricao: str | None
    raw_preview: str


DOC_RULES: list[tuple[str, list[str]]] = [
    ("das", ["simples nacional", "pgdas", "documento de arrecadação do simples"]),
    ("darf", ["documento de arrecadação de receitas federais", "darf"]),
    ("prolabore", ["pró-labore", "pro-labore", "prolabore"]),
    ("folha", ["folha de pagamento", "holerite", "contracheque"]),
    ("fgts", ["sefip", "guia de recolhimento do fgts", "fgts"]),
    ("gps", ["guia da previdência", "gps"]),
    ("nf", ["nota fiscal", "chave de acesso", "danfe"]),
    ("boleto", ["boleto", "linha digitável", "ficha de compensação"]),
]


def extract_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            return ""
        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    if suf in {".txt", ".md", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def classify(text: str) -> str:
    low = text.lower()
    for doc_type, keys in DOC_RULES:
        if any(k in low for k in keys):
            return doc_type
    return "desconhecido"


def find_money(text: str) -> str | None:
    # Prioriza padrões comuns de total
    patterns = [
        r"(?:valor\s*(?:total|do\s*documento|cobrado)?|total\s*a\s*pagar)\s*[:R$\s]*([\d.]+,\d{2})",
        r"R\$\s*([\d.]+,\d{2})",
        r"([\d.]+,\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1)
    return None


def find_date(text: str) -> str | None:
    m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    return m.group(1) if m else None


def find_cnpj(text: str) -> str | None:
    m = re.search(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b", text)
    return m.group(1) if m else None


def process_document(path: Path) -> ExtractedDoc:
    text = extract_text(path)
    doc_type = classify(text) if text.strip() else "sem_texto"
    return ExtractedDoc(
        path=str(path),
        doc_type=doc_type,
        valor=find_money(text) if text else None,
        data=find_date(text) if text else None,
        cnpj=find_cnpj(text) if text else None,
        descricao=_first_line(text),
        raw_preview=(text[:500] if text else "(PDF escaneado ou sem texto extraível)"),
    )


def process_folder(folder: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not folder.exists():
        return results
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in {".pdf", ".txt", ".md"} and path.is_file():
            results.append(asdict(process_document(path)))
    return results


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 5:
            return line[:120]
    return None
