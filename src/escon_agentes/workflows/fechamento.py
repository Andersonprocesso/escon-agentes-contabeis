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

# jpg/jpeg entram porque comprovantes de pagamento (DAS, GPS) vêm assim no
# OneDrive; o classificador decide se vira lançamento ou pendente.
EXTENSOES = {".pdf", ".xml", ".ofx", ".txt", ".csv", ".jpg", ".jpeg", ".png"}
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


def _parse_valor_br(v: Any) -> float | None:
    """Aceita 1234.56, '1.234,56', '1234,56' ou número."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    try:
        if "," in s and "." in s:
            # 1.234,56 → 1234.56
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except ValueError:
        return None


def _normalizar_data(data: Any) -> str:
    """Normaliza para DD.MM.AAAA (layout Contmatic). Aceita DD/MM/AA também."""
    from escon_agentes.tools.contmatic import format_data_contmatic

    s = str(data or "").strip()
    if not s:
        return ""
    out = format_data_contmatic(s)
    # se não reconheceu, devolve vazio para o validador recusar
    if out == s and not re.match(r"^\d{2}[./]\d{2}[./]\d{2,4}$", s):
        if not re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return ""
    return out


def _normalizar_linha_lancamento(l: dict[str, Any], *, origem: str = "manual") -> dict[str, Any] | None:
    """Aceita dict da Fabiana/Alexandre/painel e devolve linha padronizada.

    Sem valor numérico > 0 não entra — evita lixo na planilha.
    Data aceita DD/MM/AA, DD/MM/AAAA, AAAA-MM-DD e vira DD.MM.AAAA.
    """
    if not isinstance(l, dict):
        return None
    valor = _parse_valor_br(l.get("valor"))
    if valor is None or valor <= 0:
        return None
    debito = str(l.get("debito") or "").strip()
    credito = str(l.get("credito") or "").strip()
    if not debito or not credito:
        return None
    data = _normalizar_data(l.get("data"))
    if not data:
        return None
    hist = l.get("historico") if l.get("historico") is not None else l.get("historico_codigo")
    try:
        hist_n = int(hist or 0)
    except (TypeError, ValueError):
        hist_n = 0
    return {
        "data": data,
        "debito": debito,
        "credito": credito,
        "valor": valor,
        "historico": hist_n,
        "historico_texto": l.get("historico_texto") or "",
        "complemento": (l.get("complemento") or l.get("historico_texto") or origem)[:120],
        "regra": l.get("regra") or origem,
        "origem": l.get("origem") or origem,
        "arquivo": l.get("arquivo") or "",
        "observacao": l.get("observacao") or "",
    }


def gerar_planilha(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    lancados: list[dict[str, Any]],
) -> str | None:
    """Escreve Excel Contmatic com TODOS os lançados (Alexandre + Fabiana + manuais).

    Antes a planilha saía só do Alexandre e a folha (217 linhas) sumia no download
    mesmo aparecendo na aba Lançados.
    """
    if not lancados:
        return None
    from escon_agentes.tools import contmatic
    from escon_agentes.tools.clients import get_client

    cliente = get_client(settings.clients_dir, client_id)
    saida = settings.outbox / client_id
    saida.mkdir(parents=True, exist_ok=True)
    xlsx = saida / f"lancamentos_{competencia}.xlsx"
    linhas = []
    for i, r in enumerate(lancados, start=1):
        linhas.append(
            {
                "lancamento": i,
                "data": r.get("data"),
                "debito": r.get("debito"),
                "credito": r.get("credito"),
                "valor": r.get("valor"),
                "historico": r.get("historico") or 0,
                "complemento": r.get("complemento") or "",
                "ccdb": "",
                "cccr": "",
                "cnpj": r.get("cnpj") or "",
            }
        )
    contmatic.write_lancamentos(
        linhas,
        xlsx,
        empresa=getattr(cliente, "name", None) if cliente else None,
        competencia=competencia,
    )
    return str(xlsx)


def aplicar_manuais(
    lancados: list[dict[str, Any]],
    pendentes: list[dict[str, Any]],
    manuais: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reaplica correções humanas salvas após reprocessar o pipeline.

    Cada item de manuais: {arquivo, lancamentos: [{data, debito, credito, valor, ...}]}.
    Remove o arquivo da lista de pendentes e acrescenta as linhas nos lançados.
    """
    if not manuais:
        return lancados, pendentes
    arquivos_ok = set()
    out_lanc = list(lancados)
    # tira manuais antigos do mesmo arquivo (reprocess + reaplicar)
    out_lanc = [
        l
        for l in out_lanc
        if not (
            (l.get("origem") == "manual" or l.get("regra") == "correcao_manual")
            and any(
                (m.get("arquivo") or "") == (l.get("arquivo") or "")
                for m in manuais
            )
        )
    ]
    for m in manuais:
        arq = m.get("arquivo") or ""
        linhas = m.get("lancamentos") or []
        ok_alguma = False
        for raw in linhas:
            linha = _normalizar_linha_lancamento(
                {**raw, "arquivo": arq, "origem": "manual", "regra": "correcao_manual"},
                origem="manual",
            )
            if linha:
                out_lanc.append(linha)
                ok_alguma = True
        if ok_alguma and arq:
            arquivos_ok.add(arq)
    out_pend = [p for p in pendentes if (p.get("arquivo") or "") not in arquivos_ok]
    return out_lanc, out_pend


def aplicar_desconsiderados(
    pendentes: list[dict[str, Any]],
    nao_contabilizaveis: list[dict[str, Any]],
    desconsiderados: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tira da fila 'Aguardando você' o que o humano marcou como sem efeito contábil.

    Sobrevive ao reprocessar — senão o relatório de medição volta todo mês.
    """
    if not desconsiderados:
        return pendentes, nao_contabilizaveis
    arqs = {(d.get("arquivo") or "") for d in desconsiderados if d.get("arquivo")}
    if not arqs:
        return pendentes, nao_contabilizaveis

    out_pend = [p for p in pendentes if (p.get("arquivo") or "") not in arqs]
    ja = {(n.get("arquivo") or "") for n in nao_contabilizaveis}
    out_ign = list(nao_contabilizaveis)
    for d in desconsiderados:
        arq = d.get("arquivo") or ""
        if not arq or arq in ja:
            continue
        out_ign.append(
            {
                "arquivo": arq,
                "data": d.get("data"),
                "valor": d.get("valor"),
                "natureza": "desconsiderado",
                "motivo": d.get("motivo")
                or "Desconsiderado por você — sem informação contábil",
            }
        )
        ja.add(arq)
    return out_pend, out_ign


def editar_lancado(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    indice: int,
    campos: dict[str, Any],
) -> dict[str, Any]:
    """Edita um lançamento já na aba Lançados (conferência final)."""
    estado = carregar(settings, client_id, competencia)
    if not estado:
        raise FileNotFoundError(f"Fechamento {client_id}/{competencia} não encontrado")
    lancados = list(estado.get("lancados") or [])
    if indice < 0 or indice >= len(lancados):
        raise ValueError(f"Índice {indice} fora da lista (0..{len(lancados) - 1})")

    atual = dict(lancados[indice])
    merged = {
        **atual,
        "data": campos.get("data", atual.get("data")),
        "debito": campos.get("debito", atual.get("debito")),
        "credito": campos.get("credito", atual.get("credito")),
        "valor": campos.get("valor", atual.get("valor")),
        "historico": campos.get("historico", atual.get("historico") or 0),
        "complemento": campos.get(
            "complemento", atual.get("complemento") or atual.get("historico_texto") or ""
        ),
        "arquivo": atual.get("arquivo") or "",
        "origem": atual.get("origem") or "manual",
        "regra": atual.get("regra") or "edicao_manual",
        "observacao": (atual.get("observacao") or "") + " · editado na conferência",
    }
    linha = _normalizar_linha_lancamento(merged, origem="manual")
    if not linha:
        raise ValueError(
            "Dados inválidos: informe data, débito, crédito e valor > 0."
        )
    # preserva metadados úteis
    linha["arquivo"] = atual.get("arquivo") or ""
    linha["regra"] = atual.get("regra") or "edicao_manual"
    linha["origem"] = "manual"
    linha["observacao"] = merged["observacao"][:200]
    lancados[indice] = linha

    planilha = gerar_planilha(
        settings, client_id=client_id, competencia=competencia, lancados=lancados
    )
    estado.update(lancados=lancados, planilha=planilha, situacao="concluido")
    salvar(settings, estado)
    return estado


def remover_lancados(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    indice: int | None = None,
    arquivo: str | None = None,
    desconsiderar_doc: bool = False,
) -> dict[str, Any]:
    """Remove 1 lançamento (índice) ou todos do mesmo arquivo (NFS multi-linha).

    Se desconsiderar_doc=True e há arquivo, o documento entra em desconsiderados
    para não voltar no reprocessar (caso NFS cancelada já lançada por engano).
    """
    estado = carregar(settings, client_id, competencia)
    if not estado:
        raise FileNotFoundError(f"Fechamento {client_id}/{competencia} não encontrado")
    lancados = list(estado.get("lancados") or [])

    if arquivo:
        arq = arquivo
        # aceita só o nome do arquivo
        novos = [
            l
            for l in lancados
            if (l.get("arquivo") or "") != arq
            and Path(l.get("arquivo") or "").name != Path(arq).name
        ]
        if len(novos) == len(lancados):
            raise ValueError(f"Nenhum lançamento com arquivo {arquivo!r}")
        lancados = novos
    elif indice is not None:
        if indice < 0 or indice >= len(lancados):
            raise ValueError(f"Índice {indice} fora da lista")
        arq = lancados[indice].get("arquivo") or ""
        del lancados[indice]
    else:
        raise ValueError("Informe indice ou arquivo")

    desconsiderados = list(estado.get("desconsiderados") or [])
    if desconsiderar_doc and arq:
        desconsiderados = [d for d in desconsiderados if (d.get("arquivo") or "") != arq]
        desconsiderados.append(
            {
                "arquivo": Path(arq).name,
                "motivo": "Removido na conferência (ex.: NFS cancelada)",
            }
        )
        # tira de pendentes se ainda estiver
        pendentes = [
            p
            for p in (estado.get("pendentes") or [])
            if (p.get("arquivo") or "") != Path(arq).name
        ]
        nao = list(estado.get("nao_contabilizaveis") or [])
        pendentes, nao = aplicar_desconsiderados(pendentes, nao, desconsiderados)
        estado["pendentes"] = pendentes
        estado["nao_contabilizaveis"] = nao
        estado["desconsiderados"] = desconsiderados

    planilha = gerar_planilha(
        settings, client_id=client_id, competencia=competencia, lancados=lancados
    )
    estado.update(lancados=lancados, planilha=planilha, situacao="concluido")
    salvar(settings, estado)
    return estado


def achar_documento(
    settings: Settings,
    client_id: str,
    competencia: str,
    arquivo: str,
) -> Path | None:
    """Localiza o PDF/XML na pasta da competência (para visualizar na conferência)."""
    if not arquivo:
        return None
    pasta = pasta_da_competencia(settings, client_id, competencia)
    if not pasta.exists():
        return None
    nome = Path(arquivo).name
    # match exato pelo nome
    for p in pasta.rglob("*"):
        if p.is_file() and p.name == nome:
            return p
    # match case-insensitive
    low = nome.lower()
    for p in pasta.rglob("*"):
        if p.is_file() and p.name.lower() == low:
            return p
    return None


def desconsiderar_pendente(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    arquivo: str,
    motivo: str = "",
) -> dict[str, Any]:
    """Humano marca o documento como sem lançamento (relatório, medição, etc.)."""
    estado = carregar(settings, client_id, competencia)
    if not estado:
        raise FileNotFoundError(f"Fechamento {client_id}/{competencia} não encontrado")
    if not arquivo:
        raise ValueError("arquivo é obrigatório")

    pendentes = list(estado.get("pendentes") or [])
    achado = next((p for p in pendentes if (p.get("arquivo") or "") == arquivo), None)
    # aceita match por nome final se veio com path
    if not achado:
        achado = next(
            (
                p
                for p in pendentes
                if Path(p.get("arquivo") or "").name == Path(arquivo).name
            ),
            None,
        )
        if achado:
            arquivo = achado.get("arquivo") or arquivo

    motivo_final = (motivo or "").strip() or (
        f"Desconsiderado — {(achado or {}).get('motivo') or 'sem informação contábil'}"
    )[:160]

    desconsiderados = [
        d for d in (estado.get("desconsiderados") or []) if (d.get("arquivo") or "") != arquivo
    ]
    desconsiderados.append(
        {
            "arquivo": arquivo,
            "motivo": motivo_final,
            "data": (achado or {}).get("data"),
            "valor": (achado or {}).get("valor"),
        }
    )

    # também remove de manuais se alguém tinha tentado corrigir antes
    manuais = [m for m in (estado.get("manuais") or []) if (m.get("arquivo") or "") != arquivo]

    pendentes, nao = aplicar_desconsiderados(
        pendentes,
        list(estado.get("nao_contabilizaveis") or []),
        desconsiderados,
    )
    # se o arquivo ainda estiver em lancados por engano, não mexe — desconsiderar
    # é só para a fila de pendentes

    estado.update(
        pendentes=pendentes,
        nao_contabilizaveis=nao,
        desconsiderados=desconsiderados,
        manuais=manuais,
        situacao="concluido",
    )
    salvar(settings, estado)
    return estado


def corrigir_pendente(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    arquivo: str,
    lancamentos: list[dict[str, Any]],
    ensinar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Humano completa o(s) lançamento(s) de um documento com falha.

    Um pendente pode virar N linhas (ex.: NFS com ISS + INSS retidos + líquido).
    Opcionalmente grava a 1ª linha como regra aprendida (casos simples 1:1).
    """
    estado = carregar(settings, client_id, competencia)
    if not estado:
        raise FileNotFoundError(f"Fechamento {client_id}/{competencia} não encontrado")

    # pendente pode vir com path; normaliza para o nome guardado na lista
    pendentes_brutos = list(estado.get("pendentes") or [])
    arq_match = arquivo
    for p in pendentes_brutos:
        pa = p.get("arquivo") or ""
        if pa == arquivo or Path(pa).name == Path(arquivo).name:
            arq_match = pa
            break

    linhas_ok: list[dict[str, Any]] = []
    erros: list[str] = []
    for i, raw in enumerate(lancamentos, start=1):
        linha = _normalizar_linha_lancamento(
            {**raw, "arquivo": arq_match, "origem": "manual", "regra": "correcao_manual"},
            origem="manual",
        )
        if linha:
            linhas_ok.append(linha)
        else:
            erros.append(
                f"linha {i}: precisa data, débito, crédito e valor > 0 "
                f"(recebido data={raw.get('data')!r} valor={raw.get('valor')!r} "
                f"D={raw.get('debito')!r} C={raw.get('credito')!r})"
            )
    if not linhas_ok:
        raise ValueError(
            "Nenhum lançamento válido. "
            + ("; ".join(erros[:3]) if erros else "Preencha data, débito, crédito e valor.")
        )

    manuais = list(estado.get("manuais") or [])
    manuais = [m for m in manuais if (m.get("arquivo") or "") != arq_match]
    manuais.append({"arquivo": arq_match, "lancamentos": linhas_ok})

    # se estava desconsiderado e o humano corrigiu, tira da lista de ignorados
    desconsiderados = [
        d
        for d in (estado.get("desconsiderados") or [])
        if (d.get("arquivo") or "") != arq_match
    ]

    lancados, pendentes = aplicar_manuais(
        list(estado.get("lancados") or []),
        pendentes_brutos,
        manuais,
    )

    regra = None
    if ensinar and ensinar.get("chave"):
        from escon_agentes.tools import aprendizado

        # regra simples 1:1 = primeira linha (casos multi-linha ficam só no manual)
        primeira = linhas_ok[0]
        if len(linhas_ok) == 1:
            regra = aprendizado.registrar(
                chave=str(ensinar["chave"]),
                debito=primeira["debito"],
                credito=primeira["credito"],
                descricao=str(ensinar.get("descricao") or primeira.get("complemento") or ""),
                historico=int(primeira.get("historico") or 0),
            )

    planilha = gerar_planilha(
        settings, client_id=client_id, competencia=competencia, lancados=lancados
    )
    estado.update(
        lancados=lancados,
        pendentes=pendentes,
        manuais=manuais,
        desconsiderados=desconsiderados,
        planilha=planilha,
        situacao="concluido",
    )
    salvar(settings, estado)
    return estado


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

    # O caminho informado JÁ é a pasta do mês? Decidir pelo nome dela, não pelo
    # conteúdo: a pasta de setembro/2024 da Alumax tem 18 PDFs E as subpastas
    # "Emitida", "Recebida" e "ESOCIAL" — a checagem antiga ("só arquivos,
    # nenhuma pasta") não reconhecia, e o fechamento dizia que a competência
    # não existia estando dentro dela.
    if _e_pasta_do_mes(base.rsplit("/", 1)[-1], ano, mes):
        return base

    cod, itens = _onedrive_listar(base, token)
    if cod != 200:
        return None
    nomes = {i["name"]: i for i in itens if "folder" in i}

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
        if _e_pasta_do_mes(nome, ano, mes):
            return f"{base}/{nome}"
    return None


def _e_pasta_do_mes(nome: str, ano: str, mes: str) -> bool:
    """"09 2024", "9-2024", "09_2024", "092024" — o Anderson escreve de
    formas diferentes conforme o ano, então aceitar as variações."""
    n = (nome or "").strip()
    return bool(re.fullmatch(rf"0?{int(mes)}\s*[-_/.]?\s*{ano}", n))


# Árvores reais do OneDrive do Anderson (perfil arquivos = anderson@).
# O chat não pede o caminho: o agente descobre a pasta da empresa sozinho.
_ONEDRIVE_BASES = (
    "Documentos/Empresas",
    "Anderson Ramos/Empresas",
    "Anderson Ramos/Pessoal/Empresas",
    "PUBLICO/Empresas",
)


def _norm_nome(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", (s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def descobrir_pasta_onedrive(
    settings: Settings, client_id: str, token: str | None = None
) -> dict[str, Any]:
    """Acha a pasta da empresa no OneDrive sem o humano colar o caminho.

    Usa o nome do cadastro (e drive_folder_hint se houver) e varre as árvores
    Empresas/* conhecidas. Quem tem login de arquivos já autorizado não precisa
    passar link.
    """
    from escon_agentes.tools import graph_mail as gm
    from escon_agentes.tools.clients import get_client

    cliente = get_client(settings.clients_dir, client_id)
    if not cliente:
        return {"ok": False, "erro": f"Cliente {client_id} não encontrado no cadastro"}

    if token is None:
        try:
            token = gm.get_access_token(settings, interactive_ok=False, perfil="arquivos")
            gm.conferir_conta(token, settings, "arquivos")
        except gm.MailboxUnavailable as e:
            return {"ok": False, "erro": f"Login de arquivos indisponível: {e}"}

    alvos = [
        getattr(cliente, "drive_folder_hint", None) or "",
        getattr(cliente, "name", None) or getattr(cliente, "nome", None) or "",
    ]
    # CNPJ formatado às vezes está no nome da pasta Contmatic (ex. " - 0061")
    nomes_norm = {_norm_nome(a) for a in alvos if a and len(_norm_nome(a)) >= 4}
    if not nomes_norm:
        return {"ok": False, "erro": "Cadastro sem nome para buscar no OneDrive"}

    # palavras significativas (ignora LTDA, ME, etc.)
    stop = {"ltda", "me", "epp", "sa", "eireli", "de", "da", "do", "dos", "das", "e"}
    tokens_cli = set()
    for n in nomes_norm:
        tokens_cli |= {w for w in n.split() if len(w) > 2 and w not in stop}

    melhores: list[tuple[int, str]] = []
    for base in _ONEDRIVE_BASES:
        cod, itens = _onedrive_listar(base, token)
        if cod != 200:
            continue
        for it in itens:
            if "folder" not in it:
                continue
            nome = it.get("name") or ""
            nn = _norm_nome(nome)
            score = 0
            if nn in nomes_norm:
                score = 100
            else:
                toks = {w for w in nn.split() if len(w) > 2 and w not in stop}
                comuns = tokens_cli & toks
                if len(comuns) >= 2:
                    score = 40 + 10 * len(comuns)
                elif len(comuns) == 1 and len(tokens_cli) <= 2:
                    score = 25
            if score:
                melhores.append((score, f"{base}/{nome}"))

    if not melhores:
        return {
            "ok": False,
            "erro": (
                "Não achei a pasta da empresa no OneDrive "
                f"(procurei em {', '.join(_ONEDRIVE_BASES)})."
            ),
            "nome_buscado": next(iter(nomes_norm), ""),
        }

    melhores.sort(key=lambda x: (-x[0], x[1]))
    return {
        "ok": True,
        "pasta": melhores[0][1],
        "score": melhores[0][0],
        "candidatos": [p for _, p in melhores[:5]],
    }


def importar_do_onedrive(
    settings: Settings,
    client_id: str,
    competencia: str,
    pasta_onedrive: str | None = None,
) -> dict[str, Any]:
    """Baixa os documentos da competência a partir da pasta da empresa no OneDrive.

    Percorre subpastas: dentro do mês o Anderson separa em Boleto, Pgto,
    Nubank etc., e ler só o primeiro nível deixaria quase tudo para trás.

    Se `pasta_onedrive` vier vazia, descobre sozinho pelo nome do cliente —
    o login de arquivos já está autorizado na VPS.
    """
    import httpx

    from escon_agentes.tools import graph_mail as gm

    try:
        token = gm.get_access_token(settings, interactive_ok=False, perfil="arquivos")
        gm.conferir_conta(token, settings, "arquivos")
    except gm.MailboxUnavailable as e:
        return {"ok": False, "erro": f"Login de arquivos indisponível: {e}"}

    descoberta = None
    if not (pasta_onedrive or "").strip():
        descoberta = descobrir_pasta_onedrive(settings, client_id, token=token)
        if not descoberta.get("ok"):
            return descoberta
        pasta_onedrive = descoberta["pasta"]

    alvo = caminho_da_competencia(pasta_onedrive, competencia, token)
    if not alvo:
        return {
            "ok": False,
            "erro": f"Não achei a pasta de {competencia} dentro de '{pasta_onedrive}'.",
            "pasta_empresa": pasta_onedrive,
            "descoberta": descoberta,
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
        "pasta_empresa": pasta_onedrive,
        "destino": str(destino),
        "descoberta": descoberta,
    }


def executar(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    pasta_local: str | None = None,
    usar_radar: bool = False,
    pasta_onedrive: str | None = None,
    usar_onedrive: bool | None = None,
    forma_pagamento: str = "banco",
    usar_llm: bool = True,
) -> dict[str, Any]:
    """Roda o fechamento inteiro e guarda o andamento a cada etapa.

    Na VPS o caminho natural é OneDrive (login anderson@) e/ou Radar. Se
    `usar_onedrive` não for passado, entra sozinho quando não há pasta do PC
    — o chat não pede link; o agente descobre a pasta pelo nome do cliente.
    """
    competencia = normalizar_competencia(competencia)
    # default: tenta OneDrive se não veio pasta do PC (caso home office / VPS)
    if usar_onedrive is None:
        usar_onedrive = not pasta_local
    # Correções humanas da rodada anterior (multi-lançamento por pendente).
    # Guardar ANTES de sobrescrever o estado — senão o reprocessar apaga o que
    # o contador já digitou. Desconsiderados (relatório/medição) também.
    prev = carregar(settings, client_id, competencia) or {}
    manuais_anteriores = list(prev.get("manuais") or [])
    desconsiderados_anteriores = list(prev.get("desconsiderados") or [])
    etapas: list[dict[str, Any]] = []
    estado: dict[str, Any] = {
        "client_id": client_id,
        "competencia": competencia,
        "iniciado_em": datetime.now().isoformat(timespec="seconds"),
        "situacao": "em_andamento",
        "etapas": etapas,
        "manuais": manuais_anteriores,
        "desconsiderados": desconsiderados_anteriores,
    }
    salvar(settings, estado)

    if pasta_local:
        r = importar_pasta(settings, client_id, competencia, pasta_local)
        etapas.append({"etapa": "pasta do PC", **r})
        salvar(settings, estado)

    if usar_onedrive or pasta_onedrive:
        r = importar_do_onedrive(
            settings, client_id, competencia, pasta_onedrive or None
        )
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

    # --- Equipe multiagente (conceito: especialista mastiga → Alexandre lança) ---
    pedido = (
        f"Fechamento contábil multiagente {competencia} "
        f"cliente {client_id} forma {forma_pagamento}"
    )
    run = _rodar_pipeline_fixa(
        settings,
        client_id=client_id,
        pasta=pasta,
        competencia=competencia,
        forma_pagamento=forma_pagamento,
        usar_llm=usar_llm,
        pedido=pedido,
    )

    dados: dict[str, Any] = {}
    planilha = None
    ok_alex = False
    for r in run.get("results") or []:
        etapas.append(
            {
                "etapa": f"agente {r.get('agent')}",
                "ok": bool(r.get("success")),
                "resumo": (r.get("summary") or "")[:500],
                "artifacts": r.get("artifacts") or [],
                "pulou": bool((r.get("data") or {}).get("pulou")),
            }
        )
        if r.get("agent") == "alexandre":
            dados = r.get("data") or {}
            ok_alex = bool(r.get("success"))
            for art in r.get("artifacts") or []:
                if str(art).endswith(".xlsx"):
                    origem = Path(art)
                    alvo = origem.with_name(f"lancamentos_{competencia}.xlsx")
                    if origem.exists() and origem != alvo:
                        shutil.move(str(origem), str(alvo))
                        planilha = str(alvo)
                    else:
                        planilha = str(art)

    # Folha da Fabiana entra nos lançados (Alexandre marca folha como "quem
    # lança é a Fabiana" e NÃO gera linha). Antes só entrava no estado da UI —
    # a planilha Excel saía sem as 200+ linhas de folha.
    folha_extra: list[dict[str, Any]] = []
    problemas_folha: list[dict[str, Any]] = []
    for r in run.get("results") or []:
        if r.get("agent") != "fabiana":
            continue
        data_f = r.get("data") or {}
        for l in data_f.get("lancamentos") or []:
            if isinstance(l, dict):
                folha_extra.append(l)
        for prob in data_f.get("problemas") or []:
            # "arquivo.pdf: folha não fecha" → pendente editável no painel
            if isinstance(prob, str) and ":" in prob:
                arq, motivo = prob.split(":", 1)
                problemas_folha.append(
                    {
                        "arquivo": arq.strip(),
                        "data": "",
                        "valor": None,
                        "debito": "",
                        "credito": "",
                        "motivo": motivo.strip(),
                        "origem": "fabiana",
                    }
                )
            elif isinstance(prob, str):
                problemas_folha.append(
                    {
                        "arquivo": "folha",
                        "data": "",
                        "valor": None,
                        "debito": "",
                        "credito": "",
                        "motivo": prob,
                        "origem": "fabiana",
                    }
                )

    lancados = list(dados.get("lancados") or [])
    for l in folha_extra:
        linha = _normalizar_linha_lancamento(
            {
                **l,
                "arquivo": l.get("arquivo") or "folha",
                "regra": "fabiana_folha",
                "origem": "fabiana",
                "complemento": l.get("complemento") or "folha",
            },
            origem="fabiana",
        )
        if linha:
            lancados.append(linha)

    pendentes = list(dados.get("pendentes") or [])
    # Problemas de folha (não fecha, TRCT sem parser…) entram em Aguardando você
    # como lançamento incompleto para o humano completar.
    arqs_pend = {(p.get("arquivo") or "") for p in pendentes}
    for pf in problemas_folha:
        if pf["arquivo"] not in arqs_pend:
            pendentes.append(pf)
            arqs_pend.add(pf["arquivo"])

    # Correções manuais de rodadas anteriores sobrevivem ao reprocessar
    manuais = list(manuais_anteriores)
    if manuais:
        lancados, pendentes = aplicar_manuais(lancados, pendentes, manuais)

    # Documentos que o humano desconsiderou (medição, relatório GPS…)
    nao_contab = list(dados.get("nao_contabilizaveis") or [])
    desconsiderados = list(desconsiderados_anteriores)
    if desconsiderados:
        pendentes, nao_contab = aplicar_desconsiderados(
            pendentes, nao_contab, desconsiderados
        )

    # SEMPRE regenera a planilha a partir do conjunto final (Alexandre+Fabiana+manuais)
    planilha_full = gerar_planilha(
        settings, client_id=client_id, competencia=competencia, lancados=lancados
    )
    if planilha_full:
        planilha = planilha_full

    partes = [
        f"→ {r.get('agent')}: {(r.get('summary') or '')[:220]}"
        for r in (run.get("results") or [])
    ]
    resumo_equipe = "\n".join(partes)
    if folha_extra:
        resumo_equipe += f"\n→ planilha: {len(folha_extra)} lançamento(s) de folha incluído(s)"

    estado.update(
        situacao="concluido" if ok_alex else "erro",
        resumo=resumo_equipe,
        lancados=lancados,
        pendentes=pendentes,
        manuais=manuais,
        desconsiderados=desconsiderados,
        planilha=planilha,
        documentos=len(documentos),
        nao_contabilizaveis=nao_contab,
        titulos=(dados.get("titulos") or {}).get("resumo", {}),
        forma_pagamento=forma_pagamento,
        pipeline=[r.get("agent") for r in (run.get("results") or [])],
        run_id=run.get("id"),
        total_folha=len(folha_extra),
        terminado_em=datetime.now().isoformat(timespec="seconds"),
    )
    salvar(settings, estado)
    return estado


def _rodar_pipeline_fixa(
    settings: Settings,
    *,
    client_id: str,
    pasta: Path,
    competencia: str,
    forma_pagamento: str,
    usar_llm: bool,
    pedido: str,
) -> dict[str, Any]:
    """Xavier → Bill → John → Fabiana → Alexandre, com handoff de dados."""
    from escon_agentes.agents import create_agent
    from escon_agentes.agents.max import PIPELINE_CONTABIL
    from escon_agentes.schema import AgentResult, AgentTask

    results: list[dict[str, Any]] = []
    handoff: dict[str, Any] = {
        "folder": str(pasta),
        "competencia": competencia,
        "forma_pagamento": forma_pagamento,
        "usar_llm": usar_llm,
        "client_id": client_id,
    }
    handoff_artifacts: list[str] = []

    for aid in PIPELINE_CONTABIL:
        task = AgentTask(
            agent=aid,
            title=pedido[:100],
            description=pedido,
            client_id=client_id,
            input={
                **handoff,
                "artifacts": list(handoff_artifacts),
                "equipe_ja_rodou": [r["agent"] for r in results],
            },
        )
        try:
            result: AgentResult = create_agent(aid, settings=settings).run(task)
        except Exception as exc:  # noqa: BLE001
            result = AgentResult(success=False, summary=f"Erro: {exc}")

        entry = {
            "agent": aid.value,
            "success": result.success,
            "summary": result.summary,
            "needs_human": result.needs_human,
            "human_prompt": result.human_prompt,
            "artifacts": list(result.artifacts or []),
            "data_keys": list((result.data or {}).keys()),
            # data completa fica no estado do fechamento (UI / Max report)
            "data": result.data or {},
        }
        results.append(entry)

        if result.data:
            handoff[f"de_{aid.value}"] = result.data
            if aid.value == "xavier" and result.data.get("documentos"):
                handoff["xmls_estruturados"] = result.data["documentos"]
            if aid.value == "bill" and result.data.get("items"):
                handoff["docs_estruturados"] = result.data["items"]
            if aid.value == "john":
                handoff["conciliacao"] = result.data
            if aid.value == "fabiana" and result.data.get("lancamentos"):
                handoff["folha_lancamentos"] = result.data["lancamentos"]
        for art in result.artifacts or []:
            if art and art not in handoff_artifacts:
                handoff_artifacts.append(art)

    return {
        "id": f"pipe-{client_id}-{competencia}",
        "agents": [a.value for a in PIPELINE_CONTABIL],
        "results": results,
        "reasoning": (
            "Pipeline contábil multiagente: Xavier→Bill→John→Fabiana→Alexandre"
        ),
    }


def reprocessar(
    settings: Settings,
    *,
    client_id: str,
    competencia: str,
    forma_pagamento: str = "caixa",
    usar_llm: bool = False,
) -> dict[str, Any]:
    """Roda o Alexandre de novo sobre os documentos que já estão na pasta.

    Serve para depois de ensinar uma regra: os arquivos já foram baixados, e
    baixar 113 documentos do OneDrive de novo só para reclassificar seria
    desperdício. Sem LLM por padrão — se o humano acabou de ensinar, o que
    faltava não era palpite.
    """
    return executar(
        settings,
        client_id=client_id,
        competencia=competencia,
        pasta_local=None,
        usar_radar=False,
        pasta_onedrive=None,
        forma_pagamento=forma_pagamento,
        usar_llm=usar_llm,
    )
