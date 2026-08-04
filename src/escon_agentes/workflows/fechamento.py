"""Fechamento de uma competência (ex.: contabilidade atrasada de jan/21).

Junta os documentos daquela competência — de uma pasta do PC e/ou do Drive
(pelo espelho MinIO do Radar) —, roda o Alexandre e guarda o andamento para o
painel mostrar. O Excel fica pronto para conferir e baixar.

Cada competência vive na sua própria pasta:
    data/inbox/{cliente}/{AAAA-MM}/
assim jan/21 e fev/21 não se misturam quando se está zerando atraso.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from escon_agentes.config import Settings

EXTENSOES = {".pdf", ".xml", ".ofx", ".txt", ".csv"}
RE_COMPETENCIA = re.compile(r"^\d{4}-\d{2}$")


def normalizar_competencia(texto: str) -> str:
    """Aceita '2021-01', '01/2021' ou 'jan/21' e devolve sempre 'AAAA-MM'."""
    t = (texto or "").strip().lower()
    if RE_COMPETENCIA.match(t):
        return t
    if m := re.match(r"^(\d{2})/(\d{4})$", t):
        return f"{m.group(2)}-{m.group(1)}"
    if m := re.match(r"^(\d{2})/(\d{2})$", t):
        return f"20{m.group(2)}-{m.group(1)}"
    meses = {
        "jan": "01", "fev": "02", "mar": "03", "abr": "04", "mai": "05", "jun": "06",
        "jul": "07", "ago": "08", "set": "09", "out": "10", "nov": "11", "dez": "12",
    }
    if m := re.match(r"^([a-z]{3})[a-z]*[/\-\s]*(\d{2,4})$", t):
        mes = meses.get(m.group(1))
        ano = m.group(2)
        if mes:
            return f"{'20' + ano if len(ano) == 2 else ano}-{mes}"
    raise ValueError(f"Competência não reconhecida: {texto!r} (use AAAA-MM, 01/2021 ou jan/21)")


def pasta_da_competencia(settings: Settings, client_id: str, competencia: str) -> Path:
    return settings.inbox / client_id / competencia


def _estado_path(settings: Settings, client_id: str, competencia: str) -> Path:
    p = settings.data_dir / "fechamentos"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{client_id}_{competencia}.json"


def carregar(settings: Settings, client_id: str, competencia: str) -> dict[str, Any] | None:
    p = _estado_path(settings, client_id, competencia)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def salvar(settings: Settings, estado: dict[str, Any]) -> Path:
    p = _estado_path(settings, estado["client_id"], estado["competencia"])
    p.write_text(json.dumps(estado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def listar(settings: Settings) -> list[dict[str, Any]]:
    raiz = settings.data_dir / "fechamentos"
    if not raiz.exists():
        return []
    itens = []
    for f in sorted(raiz.glob("*.json"), reverse=True):
        try:
            itens.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return itens


def inspecionar_pasta(caminho: str) -> dict[str, Any]:
    """Confere a pasta antes de importar — evita descobrir na hora do fechamento
    que o caminho estava errado ou vazio."""
    p = Path(caminho.strip().strip('"'))
    if not p.exists():
        return {"ok": False, "erro": f"Caminho não encontrado: {p}"}
    if not p.is_dir():
        return {"ok": False, "erro": "O caminho não é uma pasta"}
    arquivos = [a for a in p.rglob("*") if a.is_file() and a.suffix.lower() in EXTENSOES]
    por_tipo: dict[str, int] = {}
    for a in arquivos:
        por_tipo[a.suffix.lower()] = por_tipo.get(a.suffix.lower(), 0) + 1
    return {
        "ok": True,
        "pasta": str(p),
        "total": len(arquivos),
        "por_tipo": por_tipo,
        "amostra": [a.name for a in arquivos[:8]],
    }


def importar_pasta(
    settings: Settings, client_id: str, competencia: str, origem: str
) -> dict[str, Any]:
    """Copia (não move) os documentos da pasta do PC para a competência.

    Copiar e não mover é proposital: o original do Anderson fica intacto.
    """
    info = inspecionar_pasta(origem)
    if not info["ok"]:
        return info
    destino = pasta_da_competencia(settings, client_id, competencia)
    destino.mkdir(parents=True, exist_ok=True)
    copiados, repetidos = 0, 0
    for arq in Path(info["pasta"]).rglob("*"):
        if not arq.is_file() or arq.suffix.lower() not in EXTENSOES:
            continue
        alvo = destino / arq.name
        if alvo.exists() and alvo.stat().st_size == arq.stat().st_size:
            repetidos += 1
            continue
        shutil.copy2(arq, alvo)
        copiados += 1
    return {"ok": True, "copiados": copiados, "ja_existiam": repetidos, "destino": str(destino)}


def importar_do_radar(
    settings: Settings, client_id: str, competencia: str, limite: int = 300
) -> dict[str, Any]:
    """Puxa os documentos da competência do Drive, pelo espelho MinIO do Radar."""
    from escon_agentes.tools.radar_sync import sync_client_inbox

    try:
        r = sync_client_inbox(
            client_id,
            clients_dir=settings.clients_dir,
            inbox_root=settings.inbox,
            competencia=competencia,
            limit=limite,
        )
    except Exception as e:  # noqa: BLE001 — VPS fora do ar não derruba o fechamento
        return {"ok": False, "erro": str(e)}
    return {"ok": True, "baixados": r.get("files_downloaded", 0), "resumo": r.get("summary", "")}



def _onedrive_listar(caminho: str, token: str) -> tuple[int, list[dict]]:
    import httpx

    url = (
        f"https://graph.microsoft.com/v1.0/me/drive/root:/{caminho}:/children"
        if caminho
        else "https://graph.microsoft.com/v1.0/me/drive/root/children"
    )
    with httpx.Client(timeout=60) as c:
        r = c.get(url, headers={"Authorization": f"Bearer {token}"}, params={"$top": "200"})
    return r.status_code, (r.json().get("value", []) if r.status_code == 200 else [])


def caminho_da_competencia(base: str, competencia: str, token: str) -> str | None:
    """Descobre a subpasta do mês dentro da pasta da empresa.

    A árvore do Anderson é `Empresas/{Empresa}/{Ano}/{MM AAAA}` (ex.:
    ".../Alumax Materiais de Construção/2021/01 2021"). Se o caminho informado
    já for o da competência, devolve ele mesmo.
    """
    base = base.strip().strip("/")
    ano, mes = competencia.split("-")
    cod, itens = _onedrive_listar(base, token)
    if cod != 200:
        return None
    nomes = {i["name"]: i for i in itens if "folder" in i}

    # já é a pasta do mês?
    if any(not "folder" in i for i in itens) and not nomes:
        return base

    if ano in nomes:  # base = pasta da empresa → desce para o ano
        cod2, itens2 = _onedrive_listar(f"{base}/{ano}", token)
        candidatos = [i["name"] for i in itens2 if "folder" in i]
        for nome in candidatos:
            if re.fullmatch(rf"0?{int(mes)}\s*[-_/]?\s*{ano}", nome.strip()) or nome.strip() == f"{mes} {ano}":
                return f"{base}/{ano}/{nome}"
        return None

    for nome in nomes:  # base já é o ano
        if nome.strip() == f"{mes} {ano}":
            return f"{base}/{nome}"
    return None


def importar_do_onedrive(
    settings: Settings, client_id: str, competencia: str, pasta_onedrive: str
) -> dict[str, Any]:
    """Baixa os documentos da competência a partir da pasta da empresa no OneDrive.

    Percorre subpastas: dentro do mês o Anderson separa em Boleto, Pgto,
    Nubank etc., e ler só o primeiro nível deixaria quase tudo para trás.
    """
    import httpx

    from escon_agentes.tools import graph_mail as gm

    try:
        token = gm.get_access_token(settings, interactive_ok=False, perfil="arquivos")
        gm.conferir_conta(token, settings, "arquivos")
    except gm.MailboxUnavailable as e:
        return {"ok": False, "erro": f"Login de arquivos indisponível: {e}"}

    alvo = caminho_da_competencia(pasta_onedrive, competencia, token)
    if not alvo:
        return {
            "ok": False,
            "erro": f"Não achei a pasta de {competencia} dentro de '{pasta_onedrive}'.",
        }

    destino = pasta_da_competencia(settings, client_id, competencia)
    destino.mkdir(parents=True, exist_ok=True)
    baixados, ignorados = 0, 0
    cab = {"Authorization": f"Bearer {token}"}

    def percorrer(caminho: str, profundidade: int = 0) -> None:
        nonlocal baixados, ignorados
        if profundidade > 4:  # trava contra árvore muito funda
            return
        cod, itens = _onedrive_listar(caminho, token)
        if cod != 200:
            return
        with httpx.Client(timeout=180) as c:
            for item in itens:
                nome = item.get("name") or ""
                if "folder" in item:
                    percorrer(f"{caminho}/{nome}", profundidade + 1)
                    continue
                link = item.get("@microsoft.graph.downloadUrl")
                if not link:
                    continue
                if Path(nome).suffix.lower() not in EXTENSOES:
                    ignorados += 1
                    continue
                arq = destino / nome
                if arq.exists() and arq.stat().st_size == int(item.get("size") or 0):
                    continue
                arq.write_bytes(c.get(link).content)
                baixados += 1

    percorrer(alvo)
    return {
        "ok": True,
        "baixados": baixados,
        "ignorados": ignorados,
        "pasta_origem": alvo,
        "destino": str(destino),
    }


def executar(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    pasta_local: str | None = None,
    usar_radar: bool = False,
    pasta_onedrive: str | None = None,
    usar_llm: bool = True,
) -> dict[str, Any]:
    """Roda o fechamento inteiro e guarda o andamento a cada etapa."""
    from escon_agentes.agents.alexandre import AlexandreAgent
    from escon_agentes.schema import AgentId, AgentTask

    competencia = normalizar_competencia(competencia)
    etapas: list[dict[str, Any]] = []
    estado: dict[str, Any] = {
        "client_id": client_id,
        "competencia": competencia,
        "iniciado_em": datetime.now().isoformat(timespec="seconds"),
        "situacao": "em_andamento",
        "etapas": etapas,
    }
    salvar(settings, estado)

    if pasta_local:
        r = importar_pasta(settings, client_id, competencia, pasta_local)
        etapas.append({"etapa": "pasta do PC", **r})
        salvar(settings, estado)

    if pasta_onedrive:
        r = importar_do_onedrive(settings, client_id, competencia, pasta_onedrive)
        etapas.append({"etapa": "OneDrive", **r})
        salvar(settings, estado)

    if usar_radar:
        r = importar_do_radar(settings, client_id, competencia)
        etapas.append({"etapa": "Drive (Radar)", **r})
        salvar(settings, estado)

    pasta = pasta_da_competencia(settings, client_id, competencia)
    documentos = [a for a in pasta.rglob("*") if a.is_file() and a.suffix.lower() in EXTENSOES] if pasta.exists() else []
    etapas.append({"etapa": "documentos reunidos", "ok": bool(documentos), "total": len(documentos)})
    salvar(settings, estado)

    if not documentos:
        estado.update(
            situacao="sem_documentos",
            resumo=f"Nenhum documento em {pasta}. Informe a pasta do PC ou marque o Drive.",
            terminado_em=datetime.now().isoformat(timespec="seconds"),
        )
        salvar(settings, estado)
        return estado

    agente = AlexandreAgent(settings=settings)
    resultado = agente.run(
        AgentTask(
            agent=AgentId.ALEXANDRE,
            title=f"Fechamento {competencia}",
            client_id=client_id,
            input={"folder": str(pasta), "competencia": competencia, "usar_llm": usar_llm},
        )
    )
    dados = resultado.data or {}
    etapas.append(
        {
            "etapa": "lançamentos (Alexandre)",
            "ok": resultado.success,
            "lancados": len(dados.get("lancados", [])),
            "pendentes": len(dados.get("pendentes", [])),
            "por_regra": dados.get("por_regra", 0),
            "chamadas_llm": dados.get("chamadas_llm", 0),
        }
    )

    # o Excel sai com nome da competência para não sobrescrever outro mês
    planilha = None
    for art in resultado.artifacts or []:
        if art.endswith(".xlsx"):
            origem = Path(art)
            alvo = origem.with_name(f"lancamentos_{competencia}.xlsx")
            if origem.exists():
                shutil.move(str(origem), str(alvo))
            planilha = str(alvo)

    estado.update(
        situacao="concluido" if resultado.success else "erro",
        resumo=resultado.summary,
        lancados=dados.get("lancados", []),
        pendentes=dados.get("pendentes", []),
        planilha=planilha,
        documentos=len(documentos),
        terminado_em=datetime.now().isoformat(timespec="seconds"),
    )
    salvar(settings, estado)
    return estado
