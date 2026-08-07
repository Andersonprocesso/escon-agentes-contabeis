"""Clara — Conferência dos lançamentos do Alexandre.

Roda DEPOIS do Alexandre no pipeline. Não classifica documento novo: olha o
conjunto de lançamentos e marca o que parece duplicado ou inconsistente, para
o contador (ou reprocesso) reavaliar — o caso típico é NFS em XML + PDF da
mesma nota gerando 2× o mesmo D/C/valor.

Regras de ouro:
- multi-linha da MESMA NFS (bruto + ISS + INSS + líquido) NÃO é duplicata;
- duplicata = mesma "assinatura" contábil em arquivos diferentes, ou a mesma
  linha idêntica repetida;
- alta confiança: tira o excedente da planilha e manda para reavaliação;
- média confiança: só avisa (fica nos lançados com marca).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask

_RE_NFS = re.compile(
    r"\bNFS[-\s#eE]*0*(\d{1,6})\b|\bNF[-\s#]*0*(\d{1,6})\b",
    re.IGNORECASE,
)
_RE_NUM_ARQ = re.compile(r"(?:^|[_\-\s])0*(\d{2,6})(?:[_\-\s.]|$)")


def _sem_acento(t: str) -> str:
    return (
        unicodedata.normalize("NFKD", t or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def _num(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _data_norm(d: Any) -> str:
    s = str(d or "").strip()
    if not s:
        return ""
    # DD.MM.AAAA / DD/MM/AAAA / AAAA-MM-DD → AAAA-MM-DD
    s = s.replace(".", "/").replace("-", "/")
    parts = s.split("/")
    if len(parts) == 3:
        a, b, c = parts
        if len(a) == 4:  # AAAA/MM/DD
            return f"{a}-{b.zfill(2)}-{c.zfill(2)}"
        # DD/MM/AA ou DD/MM/AAAA
        ano = c if len(c) == 4 else f"20{c.zfill(2)}"
        return f"{ano}-{b.zfill(2)}-{a.zfill(2)}"
    return s


def _nfs_de(linha: dict[str, Any]) -> str | None:
    """Número da NFS no complemento ou no nome do arquivo."""
    for campo in (linha.get("complemento"), linha.get("historico_texto"), linha.get("arquivo")):
        m = _RE_NFS.search(str(campo or ""))
        if m:
            return (m.group(1) or m.group(2) or "").lstrip("0") or "0"
    arq = Path(str(linha.get("arquivo") or "")).stem
    # "028.pdf" / "NFS_28_Premovale"
    m2 = re.search(r"(?:nfs|nf)[_\-\s]*0*(\d{1,6})", arq, re.I)
    if m2:
        return m2.group(1).lstrip("0") or "0"
    return None


def _assinatura_linha(l: dict[str, Any]) -> tuple:
    """Assinatura contábil: data + D + C + valor (centavos)."""
    return (
        _data_norm(l.get("data")),
        str(l.get("debito") or "").strip(),
        str(l.get("credito") or "").strip(),
        int(round(_num(l.get("valor")) * 100)),
    )


def _grupo_documento(l: dict[str, Any]) -> str:
    """Agrupa multi-linha da mesma NFS: por arquivo, senão por nº NFS."""
    arq = Path(str(l.get("arquivo") or "")).name
    if arq:
        return f"arq:{arq}"
    n = _nfs_de(l)
    if n:
        return f"nfs:{n}"
    return f"idx:{id(l)}"


def conferir_lancamentos(
    lancados: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analisa o conjunto e devolve o que manter / reavaliar / avisos.

    Retorno:
      manter: linhas ok para a planilha
      reavaliar: linhas tiradas (alta confiança de duplicata) p/ humano
      avisos: problemas de média confiança (ficam na planilha, só alerta)
      resumo: texto
    """
    if not lancados:
        return {
            "manter": [],
            "reavaliar": [],
            "avisos": [],
            "resumo": "Nenhum lançamento para conferir.",
            "stats": {"entrada": 0, "manter": 0, "reavaliar": 0, "avisos": 0},
        }

    # indexa com posição original
    itens = [{**dict(l), "_i": i} for i, l in enumerate(lancados)]

    # --- 1) Duplicata exata (mesma assinatura + mesmo arquivo) ---
    # multi-linha da mesma NFS tem D/C diferentes — não cai aqui.
    vistos_exatos: dict[tuple, int] = {}
    dup_exata: set[int] = set()
    for it in itens:
        key = (*_assinatura_linha(it), Path(str(it.get("arquivo") or "")).name)
        if key in vistos_exatos and key[1] and key[2] and key[3] > 0:
            dup_exata.add(it["_i"])
        else:
            vistos_exatos[key] = it["_i"]

    # --- 2) Mesma assinatura em arquivos DIFERENTES (XML + PDF da mesma nota) ---
    por_assinatura: dict[tuple, list[dict]] = defaultdict(list)
    for it in itens:
        if it["_i"] in dup_exata:
            continue
        sig = _assinatura_linha(it)
        if not sig[1] or not sig[2] or sig[3] <= 0:
            continue
        por_assinatura[sig].append(it)

    dup_cruzada: set[int] = set()
    for sig, grupo in por_assinatura.items():
        if len(grupo) < 2:
            continue
        arquivos = {Path(str(g.get("arquivo") or "")).name for g in grupo}
        if len(arquivos) < 2:
            continue  # mesmo arquivo = multi-linha legítima ou já tratado
        # mantém o primeiro (preferir XML se houver)
        def _prio(g: dict) -> tuple:
            nome = Path(str(g.get("arquivo") or "")).name.lower()
            xml_first = 0 if nome.endswith(".xml") else 1
            return (xml_first, g["_i"])

        grupo_ord = sorted(grupo, key=_prio)
        for g in grupo_ord[1:]:
            dup_cruzada.add(g["_i"])

    # --- 3) Mesmo número de NFS com o mesmo valor em arquivos diferentes ---
    # (mesmo se D/C diferirem por classificação errada)
    por_nfs_valor: dict[tuple, list[dict]] = defaultdict(list)
    for it in itens:
        if it["_i"] in dup_exata or it["_i"] in dup_cruzada:
            continue
        n = _nfs_de(it)
        v = int(round(_num(it.get("valor")) * 100))
        if not n or v <= 0:
            continue
        # só proventos "de receita" / valor principal — evita ISS/INSS do par
        # se já tem outra linha no mesmo arquivo com valor maior
        por_nfs_valor[(n, v, _data_norm(it.get("data")))].append(it)

    dup_nfs: set[int] = set()
    for key, grupo in por_nfs_valor.items():
        arquivos = {Path(str(g.get("arquivo") or "")).name for g in grupo}
        if len(arquivos) < 2:
            continue
        # se os D/C forem iguais, é a mesma duplicata da regra 2
        # se D/C diferentes, ainda assim é suspeito (mesmo valor da NFS 028 em 2 arqs)
        def _prio(g: dict) -> tuple:
            nome = Path(str(g.get("arquivo") or "")).name.lower()
            return (0 if nome.endswith(".xml") else 1, g["_i"])

        grupo_ord = sorted(grupo, key=_prio)
        # só marca se não for multi-linha do mesmo "grupo documento"
        # (bruto e líquido da mesma nota no MESMO arquivo têm valores diferentes)
        for g in grupo_ord[1:]:
            arq0 = Path(str(grupo_ord[0].get("arquivo") or "")).name
            arq1 = Path(str(g.get("arquivo") or "")).name
            if arq0 != arq1:
                dup_nfs.add(g["_i"])

    # --- 4) Avisos: mesmo valor no mesmo dia, contas diferentes, arqs diferentes ---
    avisos: list[dict[str, Any]] = []
    por_data_valor: dict[tuple, list[dict]] = defaultdict(list)
    for it in itens:
        if it["_i"] in dup_exata | dup_cruzada | dup_nfs:
            continue
        v = int(round(_num(it.get("valor")) * 100))
        d = _data_norm(it.get("data"))
        if v <= 0 or not d:
            continue
        por_data_valor[(d, v)].append(it)
    for (d, v), grupo in por_data_valor.items():
        arqs = {Path(str(g.get("arquivo") or "")).name for g in grupo}
        if len(arqs) < 2 or len(grupo) < 2:
            continue
        # contas todas iguais → já seria dup; se mistas, avisa
        pares = {(str(g.get("debito")), str(g.get("credito"))) for g in grupo}
        if len(pares) >= 2:
            avisos.append(
                {
                    "tipo": "mesmo_valor_contas_diferentes",
                    "data": d,
                    "valor": v / 100,
                    "arquivos": sorted(arqs),
                    "indices": [g["_i"] + 1 for g in grupo],  # 1-based planilha
                    "motivo": (
                        f"Mesmo valor R$ {v/100:.2f} em {d} em arquivos diferentes "
                        f"com contas distintas — confira se não é a mesma nota classificada duas vezes."
                    ),
                }
            )

    # --- monta manter / reavaliar ---
    reavaliar_idx = dup_exata | dup_cruzada | dup_nfs
    manter: list[dict[str, Any]] = []
    reavaliar: list[dict[str, Any]] = []

    for it in itens:
        i = it["_i"]
        limpo = {k: v for k, v in it.items() if k != "_i"}
        if i in reavaliar_idx:
            if i in dup_exata:
                motivo = "Linha idêntica repetida (mesma data/D/C/valor/arquivo)"
                tipo = "duplicata_exata"
            elif i in dup_cruzada:
                motivo = (
                    "Mesma partida (data/D/C/valor) em outro arquivo "
                    "— tipicamente XML + PDF da mesma NFS"
                )
                tipo = "duplicata_xml_pdf"
            else:
                motivo = (
                    "Mesmo nº de NFS e valor em outro arquivo "
                    "— possível nota dobrada"
                )
                tipo = "duplicata_nfs"
            reavaliar.append(
                {
                    **limpo,
                    "motivo": f"Clara: {motivo}",
                    "origem_conferencia": "clara",
                    "tipo_achado": tipo,
                    "indice_original": i + 1,
                }
            )
        else:
            manter.append(limpo)

    n_in = len(lancados)
    n_out = len(manter)
    n_re = len(reavaliar)
    partes = [
        f"Conferência: {n_in} lançamento(s) → {n_out} ok",
    ]
    if n_re:
        partes.append(f"{n_re} para reavaliação (duplicata)")
    if avisos:
        partes.append(f"{len(avisos)} aviso(s)")
    resumo = " · ".join(partes) + "."

    return {
        "manter": manter,
        "reavaliar": reavaliar,
        "avisos": avisos,
        "resumo": resumo,
        "stats": {
            "entrada": n_in,
            "manter": n_out,
            "reavaliar": n_re,
            "avisos": len(avisos),
            "dup_exata": len(dup_exata),
            "dup_cruzada": len(dup_cruzada),
            "dup_nfs": len(dup_nfs),
        },
    }


class ClaraAgent(BaseAgent):
    id = AgentId.CLARA
    name = "Clara"
    role = "Conferência de lançamentos"
    system_prompt = """
Você confere o conjunto de lançamentos do Alexandre antes da planilha Contmatic.
Procura duplicatas (XML+PDF da mesma NFS, linhas idênticas) e inconsistências.
Não inventa lançamento novo: só marca o que o contador deve reavaliar.
"""

    def run(self, task: AgentTask) -> AgentResult:
        # Preferência: lista já montada no handoff (fechamento); senão no input.
        lancados = (
            task.input.get("lancados")
            or (task.input.get("de_alexandre") or {}).get("lancados")
            or []
        )
        if not lancados:
            return self.result_ok(
                "Clara sem trabalho — nenhum lançamento do Alexandre nesta rodada.",
                data={"pulou": True, "manter": [], "reavaliar": [], "avisos": []},
            )

        conf = conferir_lancamentos(list(lancados))
        precisa = bool(conf["reavaliar"] or conf["avisos"])
        return self.result_ok(
            conf["resumo"],
            data={
                "conferencia": conf,
                "lancados": conf["manter"],  # lista limpa
                "reavaliar": conf["reavaliar"],
                "avisos": conf["avisos"],
                "stats": conf["stats"],
            },
            needs_human=bool(conf["reavaliar"]),
            human_prompt=(
                "Clara tirou duplicatas da planilha e mandou para reavaliação. "
                "Confira a aba Aguardando você / avisos da conferência."
                if conf["reavaliar"]
                else None
            ),
        )
