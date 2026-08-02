"""Extração de dados cadastrais a partir de documentos (Pedro Henrique).

Economia de token por desenho: os campos do cadastro são altamente padronizados
(CNPJ, IE, CEP, datas, UF) e saem por regex — custo zero. O LLM só é chamado
UMA vez, e apenas para os campos que sobraram, devolvendo tudo num único JSON.
Nunca uma chamada por campo, nunca uma por linha.

Documento típico: Comprovante de Inscrição e de Situação Cadastral (cartão CNPJ)
da Receita Federal, mas funciona com contrato social e afins.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from escon_agentes.tools.documents import extract_text

# Campos que o cadastro no Acessórias precisa.
CAMPOS_OBRIGATORIOS = ("cnpj", "nome", "fantasia")
CAMPOS_DESEJAVEIS = (
    "uf",
    "cidade",
    "bairro",
    "endlogradouro",
    "endnumero",
    "cep",
    "inscmunicipal",
    "dtabertura",
    "fone",
    "email",
)

RE_CNPJ = re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b")
RE_CNPJ_NU = re.compile(r"\b(\d{14})\b")
RE_CEP = re.compile(r"\b(\d{5}-?\d{3})\b")
RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
RE_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
RE_FONE = re.compile(r"\(?\b(\d{2})\)?[\s.-]?(\d{4,5})[\s.-]?(\d{4})\b")
RE_UF = re.compile(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b")

# rótulo no documento → campo do cadastro
ROTULOS: list[tuple[str, tuple[str, ...]]] = [
    ("nome", ("nome empresarial", "razão social", "razao social")),
    ("fantasia", ("título do estabelecimento", "titulo do estabelecimento", "nome de fantasia", "nome fantasia")),
    ("dtabertura", ("data de abertura", "data de início de atividade", "data de inicio de atividade")),
    ("endlogradouro", ("logradouro",)),
    ("endnumero", ("número", "numero")),
    ("bairro", ("bairro/distrito", "bairro")),
    ("cidade", ("município", "municipio", "cidade")),
    ("cep", ("cep",)),
    ("uf", ("uf",)),
    ("inscmunicipal", ("inscrição municipal", "inscricao municipal")),
    ("situacao", ("situação cadastral", "situacao cadastral")),
    ("atividade", ("atividade econômica principal", "atividade economica principal")),
]

LIXO = {"", "-", "********", "*****", "n/a", "não informado", "nao informado"}


def only_digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _linhas(texto: str) -> list[str]:
    return [ln.strip() for ln in texto.splitlines()]


def _sem_parenteses(texto: str) -> str:
    """'TÍTULO DO ESTABELECIMENTO (NOME DE FANTASIA)' → 'título do estabelecimento'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", texto.lower().strip()).strip()


def _valor_apos_rotulo(linhas: list[str], rotulos: tuple[str, ...]) -> str | None:
    """No cartão CNPJ o valor vem na linha seguinte ao rótulo (ou depois de ':').

    O rótulo precisa ser a linha inteira (ignorando parênteses), senão 'NÚMERO'
    casaria com o cabeçalho 'NÚMERO DE INSCRIÇÃO' e traria o CNPJ como número
    do endereço.
    """
    for i, linha in enumerate(linhas):
        limpa = _sem_parenteses(linha)
        for rot in rotulos:
            if limpa == rot:  # linha é só o rótulo → valor está abaixo
                for prox in linhas[i + 1 : i + 4]:
                    if prox and prox.lower() not in LIXO and not _parece_rotulo(prox):
                        return prox.strip()
                break
            if limpa.startswith(rot + ":"):  # 'Rótulo: valor' na mesma linha
                resto = linha.split(":", 1)[1].strip()
                if resto and resto.lower() not in LIXO:
                    return resto
    return None


def _parece_rotulo(linha: str) -> bool:
    limpa = _sem_parenteses(linha)
    return any(limpa == r or limpa.startswith(r + ":") for _, rots in ROTULOS for r in rots)


def extract_from_text(texto: str) -> dict[str, Any]:
    """Extrai o que der por regex/rótulo. Zero chamada de LLM aqui."""
    linhas = _linhas(texto)
    out: dict[str, Any] = {}
    origem: dict[str, str] = {}

    m = RE_CNPJ.search(texto)
    if m:
        out["cnpj"] = only_digits(m.group(1))
        origem["cnpj"] = "regex"
    else:
        m2 = RE_CNPJ_NU.search(texto)
        if m2:
            out["cnpj"] = m2.group(1)
            origem["cnpj"] = "regex"

    for campo, rotulos in ROTULOS:
        valor = _valor_apos_rotulo(linhas, rotulos)
        if valor:
            out[campo] = valor
            origem[campo] = "rotulo"

    if "cep" in out:
        out["cep"] = only_digits(out["cep"]) or None
    elif (m := RE_CEP.search(texto)):
        out["cep"] = only_digits(m.group(1))
        origem["cep"] = "regex"

    if "uf" in out:
        uf = (out["uf"] or "").strip().upper()[:2]
        out["uf"] = uf if RE_UF.fullmatch(uf) else None
        if not out["uf"]:
            out.pop("uf", None)

    if "dtabertura" in out and (m := RE_DATA.search(out["dtabertura"])):
        d, mth, y = m.group(1).split("/")
        out["dtabertura"] = f"{y}-{mth}-{d}"  # Acessórias espera YYYY-MM-DD

    if (m := RE_EMAIL.search(texto)):
        out["email"] = m.group(1).lower()
        origem["email"] = "regex"

    if (m := RE_FONE.search(texto)):
        out["fone"] = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        origem["fone"] = "regex"

    if "nome" in out and "fantasia" not in out:
        out["fantasia"] = out["nome"]  # RFB deixa vazio quando não há fantasia
        origem["fantasia"] = "copiado do nome"

    out = {k: v for k, v in out.items() if v not in (None, "") and str(v).lower() not in LIXO}
    return {"campos": out, "origem": origem}


def faltando(campos: dict[str, Any], *, incluir_desejaveis: bool = True) -> list[str]:
    alvo = list(CAMPOS_OBRIGATORIOS) + (list(CAMPOS_DESEJAVEIS) if incluir_desejaveis else [])
    return [c for c in alvo if not campos.get(c)]


def prompt_para_llm(texto: str, ausentes: list[str], *, limite_chars: int = 6000) -> str:
    """Uma única pergunta, pedindo todos os campos que faltam de uma vez."""
    return (
        "Extraia do documento abaixo APENAS os campos listados. "
        "Responda só com JSON puro, sem comentários. "
        "Use null quando o campo não estiver no documento — nunca invente.\n"
        f"Campos: {', '.join(ausentes)}\n"
        "Formatos: cnpj só dígitos; dtabertura AAAA-MM-DD; uf com 2 letras.\n\n"
        f"DOCUMENTO:\n{texto[:limite_chars]}"
    )


def ler_documentos(caminhos: list[Path]) -> tuple[str, list[str]]:
    """Concatena o texto dos documentos legíveis. Devolve (texto, ignorados)."""
    partes: list[str] = []
    ignorados: list[str] = []
    for p in caminhos:
        try:
            t = extract_text(p)
        except Exception:  # noqa: BLE001 — PDF corrompido não deve derrubar o cadastro
            t = ""
        if t.strip():
            partes.append(f"--- {p.name} ---\n{t}")
        else:
            ignorados.append(p.name)
    return "\n\n".join(partes), ignorados


def coletar_arquivos(origem: Path) -> list[Path]:
    if origem.is_file():
        return [origem]
    exts = {".pdf", ".txt", ".md", ".csv"}
    return sorted(p for p in origem.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def montar_payload_acessorias(campos: dict[str, Any]) -> dict[str, Any]:
    """Monta o corpo do POST /companies só com o que a API aceita."""
    permitidos = (
        "cnpj", "nome", "fantasia", "dtabertura", "inscmunicipal", "uf", "cep",
        "cidade", "bairro", "endlogradouro", "endnumero", "fone", "regime", "ativa",
    )
    payload = {k: v for k, v in campos.items() if k in permitidos and v not in (None, "")}
    payload["cnpj"] = only_digits(payload.get("cnpj"))
    payload.setdefault("ativa", "S")
    return payload
