"""Parse e organização de XMLs fiscais (NF-e, NFC-e, CT-e, NFS-e)."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
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
    # CFOP de cada item. É a natureza declarada da operação e o único jeito
    # confiável de saber que a nota é devolução, remessa ou bonificação —
    # coisas que parecem compra quando se olha só emitente e valor.
    cfops: list[str] = field(default_factory=list)
    # Retenções na NFS-e (padrão do razão Jorge: multi-linha).
    iss_retido: float | None = None
    inss_retido: float | None = None
    valor_liquido: float | None = None


def _normalizar_data(bruto: str | None) -> str | None:
    """Devolve sempre AAAA-MM-DD. A NF-e manda ISO com fuso; o CFe manda
    AAAAMMDD puro."""
    if not bruto:
        return None
    t = bruto.strip()
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return t[:10]


def detect_tipo(root: ET.Element) -> str:
    tags = {_local(el.tag).lower() for el in root.iter()}
    # CFe = Cupom Fiscal Eletronico (SAT-CF-e, varejo em SP). Sem isto o
    # documento cai em "desconhecido" e some do lancamento: numa loja de
    # balcao ele e a maior parte do movimento.
    if "cfe" in tags or "infcfe" in tags:
        return "cfe"
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


def _para_float_xml(s: str | None) -> float | None:
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(str(s).replace(",", ".").strip())
    except ValueError:
        return None


def _ler_retencoes(root: ET.Element) -> tuple[float | None, float | None, float | None]:
    """ISS e INSS retidos + líquido — tags variam por prefeitura.

    Padrão contábil (razão Jorge): bruto na receita, retenções baixam Clientes
    Diversos, líquido entra no caixa/banco.
    """
    # ISS retido
    iss = None
    for nome in (
        "ValorIssRetido", "vISSRet", "IssRetido", "ValorISSRetido",
        "vISSRetido", "BaseCalculo",  # BaseCalculo sozinho NÃO é ISS — last resort skip
    ):
        if nome == "BaseCalculo":
            continue
        v = _para_float_xml(_find_text(root, nome))
        if v and v > 0:
            iss = v
            break
    # flag IssRetido = 1 sem valor: tenta ValorISS / alíquota
    if not iss:
        flag = (_find_text(root, "IssRetido", "ISSRetido") or "").strip()
        if flag in ("1", "true", "S", "s", "sim"):
            iss = _para_float_xml(_find_text(root, "ValorISS", "vISS", "ValorIss"))

    # INSS retido (Lei 9.711/98)
    inss = None
    for nome in (
        "ValorInss", "vRetINSS", "ValorINSS", "Inss", "vINSS",
        "ValorRetidoINSS", "RetencaoINSS",
    ):
        v = _para_float_xml(_find_text(root, nome))
        if v and v > 0:
            inss = v
            break

    liquido = None
    for nome in ("ValorLiquidoNfse", "ValorLiquido", "vLiq", "ValorLiquidoNfs"):
        v = _para_float_xml(_find_text(root, nome))
        if v and v > 0:
            liquido = v
            break

    # valor dos serviços (bruto) — preferir sobre ValorLiquidoNfse como total
    return iss, inss, liquido


def parse_xml_file(path: Path) -> XmlDoc:
    tree = ET.parse(path)
    root = tree.getroot()
    tipo = detect_tipo(root)

    chave = _find_text(root, "chNFe", "chCTe", "CodigoVerificacao")
    emit = None
    dest = None
    prestador = None
    tomador = None
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "emit" and emit is None:
            emit = el
        if ln in ("dest", "toma", "toma4") and dest is None:
            dest = el
        if ln in ("PrestadorServico", "Prestador", "prestador") and prestador is None:
            prestador = el
        if ln in ("TomadorServico", "Tomador", "tomador") and tomador is None:
            tomador = el

    # NFS-e municipal: emitente costuma ser o prestador, não a tag <emit>
    if tipo == "nfse":
        if prestador is not None and emit is None:
            emit = prestador
        if tomador is not None and dest is None:
            dest = tomador

    iss_r, inss_r, liq = _ler_retencoes(root) if tipo == "nfse" else (None, None, None)

    # Bruto do serviço: ValorServicos > vServ > ValorLiquido + retenções
    valor_bruto = _find_text(
        root, "ValorServicos", "vServ", "BaseCalculo", "vNF", "vCFe", "vTPrest"
    )
    if not valor_bruto and tipo == "nfse":
        # reconstruir bruto se só veio líquido
        liq_f = liq or _para_float_xml(_find_text(root, "ValorLiquidoNfse", "ValorLiquido"))
        if liq_f is not None:
            valor_bruto = str(round(liq_f + (iss_r or 0) + (inss_r or 0), 2))
        else:
            valor_bruto = _find_text(root, "ValorLiquidoNfse", "ValorLiquido")

    return XmlDoc(
        path=str(path),
        tipo=tipo,
        chave=chave or _find_text(root, "Id"),
        emit_cnpj=_find_text(emit, "CNPJ", "CPF"),
        emit_nome=_find_text(emit, "xNome", "RazaoSocial", "NomeFantasia"),
        dest_cnpj=_find_text(dest, "CNPJ", "CPF"),
        dest_nome=_find_text(dest, "xNome", "RazaoSocial"),
        # o CFe (SAT) usa dEmi no formato AAAAMMDD e vCFe — nao dhEmi/vNF
        data_emissao=_normalizar_data(
            _find_text(root, "dhEmi", "dEmi", "DataEmissao", "DataCompetencia")
        ),
        valor_total=valor_bruto,
        numero=_find_text(root, "nNF", "nCT", "Numero", "NumeroNfse"),
        natureza=_find_text(root, "natOp", "xProd", "Discriminacao", "Descricao"),
        cfops=_ler_cfops(root),
        iss_retido=iss_r,
        inss_retido=inss_r,
        valor_liquido=liq,
    )


def _ler_cfops(root: ET.Element) -> list[str]:
    """Todos os CFOP da nota, na ordem dos itens (pode repetir)."""
    return [
        (el.text or "").strip()
        for el in root.iter()
        if _local(el.tag).upper() == "CFOP" and (el.text or "").strip()
    ]


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
