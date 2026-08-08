"""Demonstrativo das Contribuições Devidas à Previdência Social por FPAS (GFIP/SEFIP).

Fonte oficial dos valores de INSS (pedido Anderson / Jorge):
  - Segurado empregados e contribuintes individuais
  - Parte empresa (CPP) + RAT
  - Retenção Lei 9.711/98 abatida
  - Valor a recolher (GPS)

O PDF sai do SEFIP com o título:
  "COMPROVANTE DE DECLARAÇÃO DAS CONTRIBUIÇÕES A RECOLHER … POR FPAS"
  ou "Demonstrativo das Contribuições Devidas … por FPAS".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).upper().strip()


def _br_float(s: str) -> float:
    """'2.050,18' ou '2050.18' → float."""
    s = (s or "").strip().replace(" ", "")
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def _ultimo_valor(linha: str) -> float | None:
    """Último número no formato BR da linha (coluna TOTAL do demonstrativo)."""
    nums = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", linha)
    if not nums:
        return None
    return _br_float(nums[-1])


@dataclass
class FpasDemonstrativo:
    """Apuração do valor a recolher por FPAS (uma competência)."""

    competencia: str | None = None  # AAAA-MM
    cnpj: str | None = None
    cod_gps: str | None = None
    fpas: str | None = None
    aliq_rat: float = 0.0
    fap: float = 0.0
    rat_ajustado: float = 0.0

    # SEGURADO
    segurado_empregados: float = 0.0
    segurado_ci: float = 0.0

    # EMPRESA
    empresa_empregados: float = 0.0
    empresa_ci: float = 0.0
    rat: float = 0.0
    rat_agentes_nocivos: float = 0.0

    # Deduções
    retencao_lei_9711: float = 0.0
    salario_familia_maternidade: float = 0.0
    compensacao: float = 0.0

    valor_recolher_previdencia: float = 0.0
    valor_recolher_outras: float = 0.0
    total_recolher: float = 0.0

    fonte: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def total_segurado(self) -> float:
        return round(self.segurado_empregados + self.segurado_ci, 2)

    @property
    def total_empresa(self) -> float:
        return round(
            self.empresa_empregados
            + self.empresa_ci
            + self.rat
            + self.rat_agentes_nocivos,
            2,
        )

    @property
    def total_devido(self) -> float:
        """Créditos em INSS a recolher antes das deduções."""
        return round(self.total_segurado + self.total_empresa, 2)

    def ok(self) -> bool:
        return self.total_devido > 0.005 or self.total_recolher > 0.005


def eh_demonstrativo_fpas(nome: str, texto: str = "") -> bool:
    n = _norm(nome)
    t = _norm(texto[:2500] if texto else "")
    if "FPAS" in n and ("DEMONSTRATIVO" in n or "CONTRIBUICOES" in n):
        return True
    if "DEMONSTRATIVO DAS CONTRIBUICOES" in n:
        return True
    if "COMPROVANTE DE DECLARACAO DAS CONTRIBUICOES" in t and "FPAS" in t:
        return True
    if "APURACAO DO VALOR A RECOLHER" in t and "SEGURADO" in t and "EMPRESA" in t:
        return True
    return False


def localizar_fpas(pasta: Path) -> Path | None:
    """Primeiro PDF do Demonstrativo FPAS na pasta (ou subpastas rasas)."""
    if not pasta or not pasta.exists():
        return None
    candidatos: list[Path] = []
    for p in sorted(pasta.rglob("*.pdf")):
        if eh_demonstrativo_fpas(p.name):
            candidatos.append(p)
    if candidatos:
        return candidatos[0]
    # nome genérico: ler cabeçalho
    for p in sorted(pasta.glob("*.pdf")):
        try:
            from escon_agentes.tools import documents

            txt = documents.extract_text(p) or ""
        except Exception:
            continue
        if eh_demonstrativo_fpas(p.name, txt):
            return p
    return None


def parse_texto(texto: str, *, fonte: str = "") -> FpasDemonstrativo:
    d = FpasDemonstrativo(fonte=fonte)
    if not texto:
        d.avisos.append("PDF sem texto extraível")
        return d

    # COMP:01/2021
    m = re.search(r"COMP\s*:\s*(\d{2})\s*/\s*(\d{4})", texto, re.I)
    if m:
        d.competencia = f"{m.group(2)}-{m.group(1)}"

    m = re.search(r"INSCRI[CÇ][AÃ]O\s*:\s*([\d./-]+)", texto, re.I)
    if m:
        d.cnpj = re.sub(r"\D", "", m.group(1))

    m = re.search(r"COD\s*GPS\s*:\s*(\d+)", texto, re.I)
    if m:
        d.cod_gps = m.group(1)
    m = re.search(r"FPAS\s*:\s*(\d+)", texto, re.I)
    if m:
        d.fpas = m.group(1)

    def _pct(raw: float) -> float:
        """'3,0' ou '3,00' no cabeçalho = 3% → 0.03; '1,00' de FAP fica 1.00."""
        return raw

    m = re.search(r"ALIQ\s*RAT\s*:\s*([\d.,]+)", texto, re.I)
    if m:
        # SEFIP imprime 3,0 para 3% — guardamos em % (3.0) para exibir; cálculo usa /100
        d.aliq_rat = _br_float(m.group(1))

    m = re.search(r"FAP\s*:\s*([\d.,]+)", texto, re.I)
    if m:
        d.fap = _br_float(m.group(1))
    m = re.search(r"RAT\s*AJUSTADO\s*:\s*([\d.,]+)", texto, re.I)
    if m:
        d.rat_ajustado = _br_float(m.group(1))

    # Linhas da apuração — seções SEGURADO / EMPRESA definem o sentido de
    # "Empregados/Avulsos" e "Contribuintes Individuais".
    secao = ""
    for raw in texto.splitlines():
        line = raw.strip()
        if not line:
            continue
        n = _norm(line)

        if n == "SEGURADO" or (n.startswith("SEGURADO") and len(n) < 12):
            secao = "segurado"
            continue
        # Só o rótulo da seção ("EMPRESA"), não "EMPRESA: RAZÃO SOCIAL…"
        if n == "EMPRESA":
            secao = "empresa"
            continue
        if "APURACAO DO VALOR" in n:
            secao = "apuracao"
            continue
        if n == "OUTRAS ENTIDADES" or (
            n.startswith("OUTRAS ENTIDADES") and "RECOLHER" not in n and "VALOR" not in n and len(n) < 40
        ):
            secao = "outras"
            continue

        val = _ultimo_valor(line)
        if val is None:
            continue

        if "EMPREGADOS" in n and "AVULSO" in n:
            if secao == "segurado":
                d.segurado_empregados = val
            elif secao == "empresa":
                d.empresa_empregados = val
            continue
        if "CONTRIBUINTES INDIVIDUAIS" in n or "CONTRIBUINTES INDIV" in n:
            if secao == "segurado":
                d.segurado_ci = val
            elif secao == "empresa":
                d.empresa_ci = val
            continue
        if "AGENTES NOCIVOS" in n:
            d.rat_agentes_nocivos = val
            continue
        if re.match(r"^RAT(\s|$)", n) and "AJUSTADO" not in n and "ALIQ" not in n:
            d.rat = val
            continue
        if "RETENCAO" in n and ("9.711" in n or "9711" in n):
            d.retencao_lei_9711 = val
            continue
        if "SAL." in n and ("FAMILIA" in n or "MATERNIDADE" in n):
            d.salario_familia_maternidade = val
            continue
        if "COMPENSACAO" in n and "RECOLH" not in n:
            d.compensacao = val
            continue
        if "VALOR A RECOLHER" in n and "PREVIDENCIA" in n:
            d.valor_recolher_previdencia = val
            continue
        if "VALOR A RECOLHER" in n and "OUTRAS" in n:
            d.valor_recolher_outras = val
            continue
        if n.startswith("TOTAL A RECOLHER"):
            d.total_recolher = val
            continue

    # fallback: se TOTAL a recolher não veio, usa previdência
    if d.total_recolher < 0.005 and d.valor_recolher_previdencia >= 0:
        d.total_recolher = d.valor_recolher_previdencia

    if not d.ok() and not d.segurado_empregados and not d.empresa_empregados:
        d.avisos.append("Não achei linhas de apuração no Demonstrativo FPAS")

    return d


def ler_fpas(path: Path) -> FpasDemonstrativo:
    from escon_agentes.tools import documents

    texto = documents.extract_text(path) or ""
    return parse_texto(texto, fonte=str(path))


def as_dict(d: FpasDemonstrativo) -> dict[str, Any]:
    return {
        "competencia": d.competencia,
        "cnpj": d.cnpj,
        "cod_gps": d.cod_gps,
        "fpas": d.fpas,
        "aliq_rat": d.aliq_rat,
        "fap": d.fap,
        "rat_ajustado": d.rat_ajustado,
        "segurado_empregados": d.segurado_empregados,
        "segurado_ci": d.segurado_ci,
        "empresa_empregados": d.empresa_empregados,
        "empresa_ci": d.empresa_ci,
        "rat": d.rat,
        "rat_agentes_nocivos": d.rat_agentes_nocivos,
        "retencao_lei_9711": d.retencao_lei_9711,
        "valor_recolher_previdencia": d.valor_recolher_previdencia,
        "total_recolher": d.total_recolher,
        "total_segurado": d.total_segurado,
        "total_empresa": d.total_empresa,
        "total_devido": d.total_devido,
        "fonte": d.fonte,
        "avisos": d.avisos,
    }
