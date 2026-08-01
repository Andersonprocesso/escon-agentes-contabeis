"""Parse e organização de XMLs fiscais (NF-e, NFC-e, CT-e, NFS-e)."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS_STRIP = re.compile(r"\{[^}]+\}")


def _local(tag: str) -> str:
    return NS_STRIP.sub("", tag)


def _find_text(node: ET.Element | None, *names: str) -> str | None:
    if node is None:
        return None
    for el in node.iter():
        if _local(el.tag) in names and (el.text or "").strip():
            return el.text.strip()
    return None


@dataclass
class XmlDoc:
    path: str
    tipo: str  # nfe | nfce | cte | nfse | desconhecido
    chave: str | None
    emit_cnpj: str | None
    emit_nome: str | None
    dest_cnpj: str | None
    dest_nome: str | None
    data_emissao: str | None
    valor_total: str | None
    numero: str | None
    natureza: str | None


def detect_tipo(root: ET.Element) -> str:
    tags = {_local(el.tag).lower() for el in root.iter()}
    if "nfeproc" in tags or "nfe" in tags:
        # NFC-e tem mod=65
        for el in root.iter():
            if _local(el.tag) == "mod" and (el.text or "").strip() == "65":
                return "nfce"
        return "nfe"
    if "cteproc" in tags or "cte" in tags:
        return "cte"
    if "nfse" in tags or "compnfse" in tags or "tcnfse" in tags:
        return "nfse"
    return "desconhecido"


def parse_xml_file(path: Path) -> XmlDoc:
    tree = ET.parse(path)
    root = tree.getroot()
    tipo = detect_tipo(root)

    chave = _find_text(root, "chNFe", "chCTe", "CodigoVerificacao")
    emit = None
    dest = None
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "emit" and emit is None:
            emit = el
        if ln in ("dest", "toma", "toma4") and dest is None:
            dest = el

    return XmlDoc(
        path=str(path),
        tipo=tipo,
        chave=chave or _find_text(root, "Id"),
        emit_cnpj=_find_text(emit, "CNPJ", "CPF"),
        emit_nome=_find_text(emit, "xNome"),
        dest_cnpj=_find_text(dest, "CNPJ", "CPF"),
        dest_nome=_find_text(dest, "xNome"),
        data_emissao=_find_text(root, "dhEmi", "dEmi", "DataEmissao"),
        valor_total=_find_text(root, "vNF", "vTPrest", "ValorLiquidoNfse", "vServ"),
        numero=_find_text(root, "nNF", "nCT", "Numero"),
        natureza=_find_text(root, "natOp", "xProd"),
    )


def scan_folder(folder: Path) -> list[XmlDoc]:
    docs: list[XmlDoc] = []
    if not folder.exists():
        return docs
    for path in sorted(folder.rglob("*.xml")):
        try:
            docs.append(parse_xml_file(path))
        except ET.ParseError as e:
            docs.append(
                XmlDoc(
                    path=str(path),
                    tipo="erro",
                    chave=None,
                    emit_cnpj=None,
                    emit_nome=None,
                    dest_cnpj=None,
                    dest_nome=None,
                    data_emissao=None,
                    valor_total=None,
                    numero=None,
                    natureza=f"ParseError: {e}",
                )
            )
    return docs


def organize_by_client(
    docs: list[XmlDoc],
    out_dir: Path,
    client_cnpj: str | None = None,
) -> dict[str, Any]:
    """Copia XMLs para out_dir/{tipo}/{YYYY-MM}/ e gera índice JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    by_tipo: dict[str, int] = {}
    pendencias: list[str] = []

    for d in docs:
        by_tipo[d.tipo] = by_tipo.get(d.tipo, 0) + 1
        month = "sem-data"
        if d.data_emissao:
            # 2024-01-15T10:00:00-03:00 ou 2024-01-15
            month = d.data_emissao[:7].replace("/", "-")
            if len(month) < 7:
                month = "sem-data"

        dest_folder = out_dir / d.tipo / month
        dest_folder.mkdir(parents=True, exist_ok=True)
        src = Path(d.path)
        dest = dest_folder / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

        item = asdict(d)
        item["organized_path"] = str(dest)
        index.append(item)

        if d.tipo == "erro":
            pendencias.append(f"XML inválido: {d.path}")
        if client_cnpj and d.dest_cnpj and _only_digits(d.dest_cnpj) != _only_digits(client_cnpj):
            # nota emitida contra outro CNPJ — pode ser entrada do cliente se emit for fornecedor
            pass

    report = {
        "total": len(docs),
        "por_tipo": by_tipo,
        "pendencias": pendencias,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "documentos": index,
    }
    report_path = out_dir / "indice_xmls.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _only_digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def summary_text(report: dict[str, Any]) -> str:
    lines = [
        f"Total de XMLs: {report['total']}",
        "Por tipo: " + ", ".join(f"{k}={v}" for k, v in report.get("por_tipo", {}).items()),
    ]
    if report.get("pendencias"):
        lines.append("Pendências:")
        lines.extend(f"  - {p}" for p in report["pendencias"])
    return "\n".join(lines)
