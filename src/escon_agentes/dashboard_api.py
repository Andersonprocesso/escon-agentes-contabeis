"""API + dashboard web para colaboradoras da Escon."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from escon_agentes.agents import AGENT_CLASSES
from escon_agentes.config import PROJECT_ROOT, get_settings
from escon_agentes.llm import list_model_aliases
from escon_agentes.orchestrator import Orchestrator
from escon_agentes.tools import requests_board, tasks as task_board
from escon_agentes.tools.clients import (
    as_table,
    create_client,
    delete_client,
    ensure_demo_clients,
    get_client,
    list_clients,
    update_client,
)
from escon_agentes.workflows.contmatic_pipeline import run_contmatic_pipeline

# ensure_demo_clients só no bootstrap vazio (import Radar preenche a carteira)

STATIC_DIR = PROJECT_ROOT / "dashboard" / "static"



class PastaIn(BaseModel):
    caminho: str


class FechamentoIn(BaseModel):
    client_id: str
    competencia: str
    pasta_local: Optional[str] = None
    usar_radar: bool = False
    pasta_onedrive: Optional[str] = None
    # Na contabilidade atrasada a maior parte entra pelo caixa — por isso o
    # padrão aqui é caixa, e não banco como no resto do sistema.
    forma_pagamento: str = "caixa"
    usar_llm: bool = True


# Modelos de corpo ficam FORA de create_app: com `from __future__ import
# annotations` o Pydantic não resolve os tipos de classe aninhada e o FastAPI
# devolve 422 "Field required: body".
class QuickRun(BaseModel):
    pedido: str
    client_id: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    folder: Optional[str] = None


class BaixaIn(BaseModel):
    valor: float
    data: Optional[str] = None
    documento: Optional[str] = None


class EnsinarIn(BaseModel):
    """O contador explicando um pendente: 'esse boleto é honorário contábil'."""

    arquivo: str
    chave: str  # o que identifica o documento (CNPJ, nome do fornecedor)
    debito: str
    credito: str
    descricao: str = ""
    historico: int = 0
    reprocessar: bool = True  # roda a competência de novo já com a regra nova


class LancamentoLinhaIn(BaseModel):
    """Uma linha de lançamento Contmatic (o contador preenche o que faltou)."""

    data: str
    debito: str
    credito: str
    valor: float
    historico: int = 0
    complemento: str = ""


class CorrigirIn(BaseModel):
    """Corrige um pendente como 1+ lançamentos (ex.: NFS com ISS e INSS retidos).

    Diferente de 'ensinar' (que vira regra genérica 1 D/C): aqui o humano monta
    o(s) lançamento(s) deste documento e eles entram na planilha na hora.
    """

    arquivo: str
    lancamentos: list[LancamentoLinhaIn]
    # opcional: se só 1 linha e veio chave, grava regra para o próximo mês
    chave: str = ""
    descricao: str = ""
    ensinar_regra: bool = False


class DesconsiderarIn(BaseModel):
    """Marca o documento como sem efeito contábil (relatório, medição, etc.)."""

    arquivo: str
    motivo: str = ""


class ReprocessarIn(BaseModel):
    """Roda de novo a competência sem rebaixar OneDrive/Radar."""

    usar_llm: bool = False


class RecorrenteIn(BaseModel):
    """Despesa de contrato — o honorário do mês existe mesmo sem boleto."""

    descricao: str
    debito: str
    credito: str
    valor: float
    dia: int = 0  # 0 = último dia do mês
    inicio: str = ""  # AAAA-MM
    fim: str = ""
    id: str = ""


def create_app() -> FastAPI:
    app = FastAPI(
        title="Escon Agentes — Dashboard",
        description="Painel operacional para colaboradoras",
        version="0.2.0",
    )
    settings = get_settings()
    # demos só se carteira vazia (import Radar preenche ~87 empresas)
    if not list(settings.clients_dir.glob("*.json")):
        ensure_demo_clients(settings.clients_dir)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index():
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse("<h1>Dashboard não encontrado</h1>", status_code=500)
        return FileResponse(index_path)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s = get_settings()
        return {
            "ok": True,
            "office": s.escon_office_name,
            "llm_provider": s.active_provider(),
            "llm_model": s.resolve_model() if s.llm_available else None,
            "offline": s.escon_offline or not s.llm_available,
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        s = get_settings()
        runs = _list_runs(s.tasks_dir, limit=50)
        reqs = requests_board.load_requests(s.requests_dir)
        open_tasks = [
            t for t in task_board.load_board(s.tasks_dir) if t.get("status") == "open"
        ]
        waiting = [r for r in runs if r.get("status") == "waiting_human"]
        by_agent: dict[str, int] = {}
        for r in runs:
            for a in r.get("agents") or []:
                by_agent[a] = by_agent.get(a, 0) + 1

        return {
            "runs_total": len(runs),
            "runs_waiting_human": len(waiting),
            "requests_queued": sum(1 for x in reqs if x.get("status") == "queued"),
            "requests_open": sum(
                1 for x in reqs if x.get("status") in {"queued", "running", "waiting_human"}
            ),
            "tasks_open": len(open_tasks),
            "agents_activity": by_agent,
            "clients": len(list_clients(s.clients_dir)),
            "priority": "Lançamentos Contmatic (zerar atraso → migrar Oneflow)",
        }

    @app.get("/api/agents")
    def agents() -> list[dict[str, str]]:
        return [
            {"id": aid.value, "name": cls.name, "role": cls.role}
            for aid, cls in AGENT_CLASSES.items()
        ]

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        s = get_settings()
        return {
            "provider": s.active_provider(),
            "default": s.resolve_model() if s.llm_available else None,
            "aliases": list_model_aliases(s),
        }

    @app.get("/api/clients")
    def clients() -> dict[str, Any]:
        s = get_settings()
        rows = as_table(list_clients(s.clients_dir))
        if not rows:
            ensure_demo_clients(s.clients_dir)
            rows = as_table(list_clients(s.clients_dir))
        return {"total": len(rows), "clients": rows}

    class ClientIn(BaseModel):
        id: Optional[str] = None
        name: Optional[str] = None
        nome: Optional[str] = None
        cnpj: Optional[str] = None
        regime: Optional[str] = None
        banco: Optional[str] = None
        banco_principal: Optional[str] = None
        telefone: Optional[str] = None
        whatsapp: Optional[str] = None
        email: Optional[str] = None
        uf: Optional[str] = None
        tags: Optional[list[str]] = None

    @app.post("/api/clients")
    def clients_create(body: ClientIn) -> dict[str, Any]:
        s = get_settings()
        try:
            c = create_client(s.clients_dir, body.model_dump(exclude_none=True), s.inbox)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "client": as_table([c])[0]}

    @app.get("/api/clients/{client_id}")
    def clients_get(client_id: str) -> dict[str, Any]:
        s = get_settings()
        c = get_client(s.clients_dir, client_id)
        if not c:
            raise HTTPException(404, "Cliente não encontrado")
        return as_table([c])[0]

    @app.patch("/api/clients/{client_id}")
    def clients_patch(client_id: str, body: ClientIn) -> dict[str, Any]:
        s = get_settings()
        c = update_client(s.clients_dir, client_id, body.model_dump(exclude_none=True))
        if not c:
            raise HTTPException(404, "Cliente não encontrado")
        return {"ok": True, "client": as_table([c])[0]}

    @app.delete("/api/clients/{client_id}")
    def clients_delete(client_id: str, remove_inbox: bool = False) -> dict[str, Any]:
        s = get_settings()
        ok = delete_client(
            s.clients_dir,
            client_id,
            inbox_root=s.inbox,
            remove_inbox=remove_inbox,
        )
        if not ok:
            raise HTTPException(404, "Cliente não encontrado")
        return {"ok": True, "deleted": client_id}

    @app.get("/api/runs")
    def runs(limit: int = 40) -> list[dict[str, Any]]:
        s = get_settings()
        return _list_runs(s.tasks_dir, limit=limit)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        s = get_settings()
        path = s.tasks_dir / f"run_{run_id}.json"
        if not path.exists():
            # try partial match
            matches = list(s.tasks_dir.glob(f"run_{run_id}*.json"))
            if not matches:
                raise HTTPException(404, "Run não encontrado")
            path = matches[0]
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/tasks")
    def tasks() -> list[dict[str, Any]]:
        s = get_settings()
        return task_board.load_board(s.tasks_dir)

    @app.get("/api/services")
    def services() -> list[dict[str, str]]:
        return requests_board.SERVICE_CATALOG

    @app.get("/api/requests")
    def list_requests() -> list[dict[str, Any]]:
        s = get_settings()
        return requests_board.load_requests(s.requests_dir)

    class NewRequest(BaseModel):
        service_id: str
        client_id: Optional[str] = None
        notes: str = ""
        requested_by: str = "equipe"
        model: Optional[str] = None
        folder: Optional[str] = None
        execute_now: bool = True

    @app.post("/api/requests")
    def create_request(body: NewRequest) -> dict[str, Any]:
        s = get_settings()
        try:
            item = requests_board.create_request(
                s.requests_dir,
                service_id=body.service_id,
                client_id=body.client_id,
                notes=body.notes,
                requested_by=body.requested_by,
                model=body.model,
                folder=body.folder,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        if body.execute_now:
            item = _execute_request(item)
        return item

    @app.post("/api/requests/{req_id}/execute")
    def execute_request(req_id: str) -> dict[str, Any]:
        s = get_settings()
        item = requests_board.get_request(s.requests_dir, req_id)
        if not item:
            raise HTTPException(404, "Solicitação não encontrada")
        return _execute_request(item)

    @app.post("/api/run")
    def api_run(body: QuickRun) -> dict[str, Any]:
        """Pedido em linguagem natural — executa de verdade (não só conversa).

        Contabilização com cliente + competência roda o fechamento completo e
        devolve contagem de lançados/pendentes para a UI abrir a revisão.
        """
        from escon_agentes.agents.max import (
            _CONTABIL_KEYS,
            _extract_competencia_e_forma,
        )

        pedido = (body.pedido or "").strip()
        low = pedido.lower()
        extra = _extract_competencia_e_forma(pedido)
        competencia = extra.get("competencia")
        forma = extra.get("forma_pagamento") or "caixa"
        eh_contabil = any(k in low for k in _CONTABIL_KEYS) or (
            "fechamento" in low and "extrato" not in low
        )

        # Atalho operacional: contabilizar competência → workflow real
        if eh_contabil and body.client_id and competencia:
            from escon_agentes.workflows import fechamento as fx

            s = get_settings()
            try:
                # OneDrive automático (login anderson@ já autorizado) + Radar se
                # a chave SSH estiver no container. Não pede link ao usuário.
                estado = fx.executar(
                    s,
                    client_id=body.client_id,
                    competencia=competencia,
                    pasta_local=body.folder,
                    usar_onedrive=True,
                    usar_radar=True,
                    forma_pagamento=forma,
                    usar_llm=False,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

            n_lanc = len(estado.get("lancados") or [])
            n_pend = len(estado.get("pendentes") or [])
            n_docs = estado.get("documentos") or 0
            situacao = estado.get("situacao") or ""
            pipe = estado.get("pipeline") or ["alexandre"]
            reply = (
                f"Equipe acionada para {body.client_id} · {estado.get('competencia')}:\n"
                f"{' → '.join(pipe)}\n\n"
                f"Situação: {situacao}\n"
                f"Documentos: {n_docs}\n"
                f"Lançados: {n_lanc}\n"
                f"Aguardando você: {n_pend}\n\n"
            )
            # Reporta o que cada especialista fez (conceito multiagente)
            for e in estado.get("etapas") or []:
                if str(e.get("etapa") or "").startswith("agente "):
                    quem = str(e.get("etapa")).replace("agente ", "")
                    resumo_e = (e.get("resumo") or "")[:180]
                    reply += f"→ {quem}: {resumo_e}\n"
            if situacao == "sem_documentos":
                # Mostra o que cada fonte respondeu — evita a impressão de que
                # "tem OneDrive e o agente não usa".
                et_linhas = []
                for e in estado.get("etapas") or []:
                    nome = e.get("etapa") or "?"
                    if e.get("ok") is False:
                        et_linhas.append(f"· {nome}: falhou — {e.get('erro') or e}")
                    elif e.get("baixados") is not None:
                        et_linhas.append(f"· {nome}: {e.get('baixados')} baixado(s)")
                    elif e.get("copiados") is not None:
                        et_linhas.append(f"· {nome}: {e.get('copiados')} copiado(s)")
                    else:
                        et_linhas.append(f"· {nome}: {e}")
                reply += "Fontes tentadas:\n" + (
                    "\n".join(et_linhas) if et_linhas else "(nenhuma etapa registrada)"
                )
                reply += (
                    "\n\nSe o OneDrive falhou em achar a pasta, diga na aba Conferir o "
                    "caminho (ex.: Documentos/Empresas/Nome da Empresa)."
                )
            elif n_pend:
                reply += (
                    f"Há {n_pend} documento(s) sem regra. Abra a aba Conferir → "
                    "Aguardando você e ensine o Alexandre (a regra vale nos próximos meses)."
                )
            else:
                reply += (
                    "Nada pendente. Revise os lançamentos na aba Conferir e, "
                    "se estiver ok, emita a planilha do Contmatic."
                )
            if estado.get("resumo"):
                reply += f"\n\n{estado['resumo']}"

            results_ui = []
            for e in estado.get("etapas") or []:
                if str(e.get("etapa") or "").startswith("agente "):
                    quem = str(e.get("etapa")).replace("agente ", "")
                    results_ui.append(
                        {
                            "agent": quem,
                            "success": bool(e.get("ok")),
                            "summary": e.get("resumo") or "",
                            "needs_human": quem == "alexandre" and n_pend > 0,
                            "artifacts": e.get("artifacts") or [],
                            "data_keys": [],
                        }
                    )
            if not results_ui:
                results_ui = [
                    {
                        "agent": "alexandre",
                        "success": situacao in {"concluido", "sem_documentos"},
                        "summary": reply,
                        "needs_human": n_pend > 0,
                        "artifacts": [estado["planilha"]] if estado.get("planilha") else [],
                        "data_keys": ["fechamento"],
                    }
                ]
            return {
                "id": f"fx-{body.client_id}-{estado.get('competencia')}",
                "title": pedido[:120],
                "client_id": body.client_id,
                "status": "done" if situacao == "concluido" else situacao,
                "reasoning": (
                    "Pedido de contabilidade → pipeline multiagente "
                    "(Xavier→Bill→John→Fabiana→Alexandre)"
                ),
                "agents": pipe,
                "results": results_ui,
                "needs_human": [f"alexandre: {n_pend} pendente(s)"] if n_pend else [],
                "reply": reply,
                "fechamento": {
                    "client_id": body.client_id,
                    "competencia": estado.get("competencia"),
                    "total_lancados": n_lanc,
                    "total_pendentes": n_pend,
                    "situacao": situacao,
                    "abrir_revisao": situacao == "concluido",
                    "pipeline": pipe,
                },
                "llm": "regras (sem token)",
                "provider": "local",
                "model": "regras",
            }

        if eh_contabil and body.client_id and not competencia:
            reply = (
                "Vou acionar o Alexandre, mas preciso da competência.\n\n"
                "Ex.: «contabilize set/2024» ou «faça a contabilidade de 2024-09».\n"
                "Forma (opcional): diga caixa ou banco."
            )
            return {
                "id": "need-comp",
                "title": pedido[:120],
                "client_id": body.client_id,
                "status": "waiting_human",
                "reasoning": "Contabilidade pedida sem competência",
                "agents": ["alexandre"],
                "results": [
                    {
                        "agent": "max",
                        "success": True,
                        "summary": reply,
                        "needs_human": True,
                        "human_prompt": "Informar competência",
                        "artifacts": [],
                        "data_keys": [],
                    }
                ],
                "needs_human": ["Informar competência (AAAA-MM ou set/2024)"],
                "reply": reply,
                "llm": "local",
                "provider": "local",
                "model": "roteamento",
            }

        if eh_contabil and not body.client_id:
            reply = (
                "Para contabilizar preciso do cliente.\n\n"
                "Selecione o cliente no seletor do chat (ou diga o CNPJ) e a "
                "competência, ex.: «contabilize a Alumax em set/2024»."
            )
            return {
                "id": "need-client",
                "title": pedido[:120],
                "client_id": None,
                "status": "waiting_human",
                "reasoning": "Contabilidade pedida sem cliente",
                "agents": ["alexandre"],
                "results": [
                    {
                        "agent": "max",
                        "success": True,
                        "summary": reply,
                        "needs_human": True,
                        "human_prompt": "Selecionar cliente",
                        "artifacts": [],
                        "data_keys": [],
                    }
                ],
                "needs_human": ["Selecionar cliente"],
                "reply": reply,
                "llm": "local",
                "provider": "local",
                "model": "roteamento",
            }

        orch = Orchestrator(model=body.model)
        params: dict[str, Any] = {}
        if body.folder:
            params["folder"] = body.folder
        params.update(extra)
        payload = orch.run(
            pedido,
            client_id=body.client_id,
            agent=body.agent,
            params=params,
        )
        # Resposta amigável para o chat (bolha do Max)
        partes = []
        for r in payload.get("results") or []:
            quem = r.get("agent") or "?"
            partes.append(f"→ {quem}: {r.get('summary') or ''}")
        payload["reply"] = (
            (payload.get("reasoning") or "")
            + ("\n\n" if partes else "")
            + "\n\n".join(partes)
        ).strip()
        return payload

    @app.post("/api/contmatic/{client_id}")
    def api_contmatic(client_id: str, folder: Optional[str] = None) -> dict[str, Any]:
        return run_contmatic_pipeline(client_id, folder=folder)

    # ---------- Fechamento por competência (contabilidade atrasada) ----------

    @app.post("/api/pastas/inspecionar")
    def api_inspecionar_pasta(body: PastaIn) -> dict[str, Any]:
        """Confere a pasta antes de rodar — melhor descobrir agora que o
        caminho está errado do que no meio do fechamento."""
        from escon_agentes.workflows import fechamento as fx

        return fx.inspecionar_pasta(body.caminho)

    @app.post("/api/fechamentos")
    def api_fechamento_executar(body: FechamentoIn) -> dict[str, Any]:
        from escon_agentes.workflows import fechamento as fx

        s = get_settings()
        try:
            return fx.executar(
                s,
                client_id=body.client_id,
                competencia=body.competencia,
                pasta_local=body.pasta_local,
                usar_radar=body.usar_radar,
                pasta_onedrive=body.pasta_onedrive,
                forma_pagamento=body.forma_pagamento,
                usar_llm=body.usar_llm,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/fechamentos")
    def api_fechamentos() -> list[dict[str, Any]]:
        from escon_agentes.workflows import fechamento as fx

        itens = fx.listar(get_settings())
        # a lista não precisa carregar os lançamentos inteiros
        return [
            {k: v for k, v in i.items() if k not in ("lancados", "pendentes")}
            | {
                "total_lancados": len(i.get("lancados") or []),
                "total_pendentes": len(i.get("pendentes") or []),
            }
            for i in itens
        ]

    @app.get("/api/fechamentos/{client_id}/{competencia}")
    def api_fechamento(client_id: str, competencia: str) -> dict[str, Any]:
        from escon_agentes.workflows import fechamento as fx

        estado = fx.carregar(get_settings(), client_id, competencia)
        if not estado:
            raise HTTPException(status_code=404, detail="Fechamento não encontrado")
        return estado

    @app.get("/api/fechamentos/{client_id}/{competencia}/planilha")
    def api_fechamento_planilha(client_id: str, competencia: str):
        from fastapi.responses import FileResponse

        from escon_agentes.workflows import fechamento as fx

        s = get_settings()
        estado = fx.carregar(s, client_id, competencia) or {}
        lancados = estado.get("lancados") or []
        # Regenera na hora a partir do conjunto final (folha + manuais + regras).
        # Assim o download nunca fica com planilha velha do Alexandre só.
        if lancados:
            caminho = fx.gerar_planilha(
                s,
                client_id=client_id,
                competencia=competencia,
                lancados=lancados,
            )
            if caminho:
                estado["planilha"] = caminho
                fx.salvar(s, estado)
        else:
            caminho = estado.get("planilha")
        if not caminho or not Path(caminho).exists():
            raise HTTPException(status_code=404, detail="Planilha ainda não gerada")
        return FileResponse(
            caminho,
            filename=f"lancamentos_{client_id}_{competencia}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/fechamentos/{client_id}/{competencia}/corrigir")
    def api_corrigir(client_id: str, competencia: str, body: CorrigirIn) -> dict[str, Any]:
        """Pendente vira lançamento(s) editados pelo contador — entram na planilha."""
        from escon_agentes.workflows import fechamento as fx

        if not body.arquivo:
            raise HTTPException(400, "arquivo é obrigatório")
        if not body.lancamentos:
            raise HTTPException(400, "informe ao menos um lançamento")
        ensinar = None
        if body.ensinar_regra and body.chave:
            ensinar = {"chave": body.chave, "descricao": body.descricao}
        try:
            estado = fx.corrigir_pendente(
                get_settings(),
                client_id=client_id,
                competencia=competencia,
                arquivo=body.arquivo,
                lancamentos=[ln.model_dump() for ln in body.lancamentos],
                ensinar=ensinar,
            )
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"Falha ao salvar correção: {e}") from e
        return {
            "ok": True,
            "total_lancados": len(estado.get("lancados") or []),
            "total_pendentes": len(estado.get("pendentes") or []),
            "estado": estado,
        }

    @app.post("/api/fechamentos/{client_id}/{competencia}/desconsiderar")
    def api_desconsiderar(
        client_id: str, competencia: str, body: DesconsiderarIn
    ) -> dict[str, Any]:
        """Tira o documento de 'Aguardando você' → 'Sem lançamento'."""
        from escon_agentes.workflows import fechamento as fx

        if not body.arquivo:
            raise HTTPException(400, "arquivo é obrigatório")
        try:
            estado = fx.desconsiderar_pendente(
                get_settings(),
                client_id=client_id,
                competencia=competencia,
                arquivo=body.arquivo,
                motivo=body.motivo,
            )
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "total_lancados": len(estado.get("lancados") or []),
            "total_pendentes": len(estado.get("pendentes") or []),
            "estado": estado,
        }

    @app.post("/api/fechamentos/{client_id}/{competencia}/reprocessar")
    def api_reprocessar(
        client_id: str, competencia: str, body: ReprocessarIn | None = None
    ) -> dict[str, Any]:
        """Roda de novo sem rebaixar Drive — corrige data/valor e regras novas."""
        from escon_agentes.workflows import fechamento as fx

        s = get_settings()
        estado = fx.carregar(s, client_id, competencia) or {}
        try:
            novo = fx.reprocessar(
                s,
                client_id=client_id,
                competencia=competencia,
                forma_pagamento=estado.get("forma_pagamento") or "caixa",
                usar_llm=bool(body.usar_llm) if body else False,
            )
        except Exception as e:
            raise HTTPException(500, f"Falha ao reprocessar: {e}") from e
        return {
            "ok": True,
            "total_lancados": len(novo.get("lancados") or []),
            "total_pendentes": len(novo.get("pendentes") or []),
            "estado": novo,
        }

    @app.get("/api/contas")
    def api_contas() -> list[dict[str, str]]:
        """Contas para o contador escolher ao ensinar uma regra.

        Sem digitar código: escolher 3111303 de cabeça é como o plano de contas
        foi para IPI da última vez. Nome real do PlContas.TXT tem prioridade —
        o alias do yaml só entra se a conta não existir no export Contmatic.
        """
        import yaml as _yaml

        from escon_agentes.tools.plcontas_parser import load_or_build_index

        por_codigo: dict[str, dict[str, str]] = {}

        # 1) Plano Contmatic de verdade (fonte de nomes)
        try:
            idx = load_or_build_index()
            for cod, info in (idx.get("by_code") or {}).items():
                nome = (info.get("descricao") or "").strip()
                if cod and nome:
                    por_codigo[str(cod)] = {"codigo": str(cod), "nome": nome}
        except Exception:
            pass  # sem PlContas o painel ainda lista aliases do yaml

        # 2) Aliases do yaml (só preenche o que faltou no PlContas)
        plano = _yaml.safe_load(
            (PROJECT_ROOT / "config" / "plano_contas.yaml").read_text(encoding="utf-8")
        ) or {}
        for alias, cod in (plano.get("contas") or {}).items():
            c = str(cod)
            if c not in por_codigo:
                por_codigo[c] = {
                    "codigo": c,
                    "nome": alias.replace("_", " ").capitalize(),
                }

        regras = _yaml.safe_load(
            (PROJECT_ROOT / "config" / "regras_lancamento.yaml").read_text(encoding="utf-8")
        ) or {}
        for cod, nome in (regras.get("contas_resultado") or {}).items():
            c = str(cod)
            if c not in por_codigo:
                por_codigo[c] = {"codigo": c, "nome": str(nome)}

        return sorted(por_codigo.values(), key=lambda x: x["codigo"])

    @app.get("/api/fechamentos/{client_id}/{competencia}/pendente")
    def api_pendente_detalhe(client_id: str, competencia: str, arquivo: str) -> dict[str, Any]:
        """O documento como o agente o viu, com sugestões do que o identifica."""
        from escon_agentes.tools import aprendizado, documents
        from escon_agentes.workflows import fechamento as fx

        pasta = fx.pasta_da_competencia(get_settings(), client_id, competencia)
        achados = [p for p in pasta.rglob("*") if p.name == arquivo]
        if not achados:
            raise HTTPException(404, f"Documento não encontrado: {arquivo}")
        texto = documents.extract_text(achados[0])
        return {
            "arquivo": arquivo,
            "texto": texto[:4000],
            "chaves_sugeridas": aprendizado.sugerir_chaves(texto, arquivo),
        }

    @app.post("/api/fechamentos/{client_id}/{competencia}/ensinar")
    def api_ensinar(client_id: str, competencia: str, body: EnsinarIn) -> dict[str, Any]:
        """Vira regra e, se pedido, reprocessa a competência já com ela.

        Reprocessar é de propósito: a regra nova costuma resolver mais de um
        documento do mesmo fornecedor no mesmo mês.
        """
        from escon_agentes.tools import aprendizado

        try:
            regra = aprendizado.registrar(
                chave=body.chave,
                debito=body.debito,
                credito=body.credito,
                descricao=body.descricao,
                historico=body.historico,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        resultado: dict[str, Any] = {"regra": regra, "reprocessado": False}
        if body.reprocessar:
            from escon_agentes.workflows import fechamento as fx

            s = get_settings()
            estado = fx.carregar(s, client_id, competencia) or {}
            novo = fx.reprocessar(
                s,
                client_id=client_id,
                competencia=competencia,
                forma_pagamento=estado.get("forma_pagamento", "caixa"),
            )
            resultado["reprocessado"] = True
            resultado["estado"] = novo
        return resultado

    @app.get("/api/recorrentes/{client_id}")
    def api_recorrentes(client_id: str) -> list[dict[str, Any]]:
        from dataclasses import asdict as _asdict

        from escon_agentes.tools import recorrentes

        return [_asdict(r) for r in recorrentes.carregar(get_settings().data_dir, client_id)]

    @app.post("/api/recorrentes/{client_id}")
    def api_recorrente_criar(client_id: str, body: RecorrenteIn) -> dict[str, Any]:
        """Despesa de contrato: provisionada todo mês, com ou sem documento."""
        from dataclasses import asdict as _asdict

        from escon_agentes.tools import recorrentes

        rec = recorrentes.Recorrente(
            id=body.id or re.sub(r"[^a-z0-9]+", "_", body.descricao.lower()).strip("_")[:40],
            descricao=body.descricao,
            debito=body.debito,
            credito=body.credito,
            valor=body.valor,
            dia=body.dia,
            inicio=body.inicio,
            fim=body.fim,
        )
        recorrentes.registrar(get_settings().data_dir, client_id, rec)
        return _asdict(rec)

    @app.delete("/api/recorrentes/{client_id}/{rec_id}")
    def api_recorrente_remover(client_id: str, rec_id: str) -> dict[str, Any]:
        from escon_agentes.tools import recorrentes

        if not recorrentes.remover(get_settings().data_dir, client_id, rec_id):
            raise HTTPException(404, "Recorrente não encontrada")
        return {"ok": True, "removida": rec_id}

    @app.get("/api/agentes/{agente}/atividade")
    def api_agente_atividade(agente: str, limit: int = 12) -> dict[str, Any]:
        """O que este agente fez — para clicar nele e ver, não adivinhar."""
        s = get_settings()
        execucoes = [
            r for r in _list_runs(s.tasks_dir, limit=200)
            if agente in (r.get("agents") or [])
        ][:limit]
        cls = AGENT_CLASSES.get(next((a for a in AGENT_CLASSES if a.value == agente), None))
        return {
            "id": agente,
            "nome": getattr(cls, "name", agente),
            "papel": getattr(cls, "role", ""),
            "execucoes": execucoes,
            "total": len(execucoes),
        }

    @app.get("/api/titulos/{client_id}")
    def api_titulos(client_id: str, tipo: str | None = None) -> dict[str, Any]:
        """Razão auxiliar do cliente: o que ficou a receber e a pagar."""
        from escon_agentes.tools import titulos as tit

        carteira = tit.abrir_carteira(get_settings().data_dir, client_id)
        return {
            "resumo": carteira.resumo(),
            "ajustes": carteira.ajustes_abertos(),
            "titulos": [
                {
                    "id": t.id, "tipo": t.tipo, "numero": t.numero,
                    "parcela": t.parcela, "parcelas": t.parcelas,
                    "contraparte": t.contraparte, "vencimento": t.vencimento,
                    "valor": t.valor, "saldo": t.saldo, "status": t.status,
                    "atraso_dias": t.vencido_em(), "presumido": t.presumido,
                    "origem": t.origem, "competencia": t.competencia,
                }
                for t in sorted(
                    carteira.em_aberto(tipo), key=lambda x: x.vencimento or "9999"
                )
            ],
        }

    @app.post("/api/titulos/{client_id}/{titulo_id}/baixar")
    def api_baixar_titulo(client_id: str, titulo_id: str, body: BaixaIn) -> dict[str, Any]:
        """Baixa manual — para o caso em que o agente se recusou a escolher."""
        from escon_agentes.tools import titulos as tit

        carteira = tit.abrir_carteira(get_settings().data_dir, client_id)
        alvo = carteira.baixar(
            titulo_id, valor=body.valor, data=body.data or "",
            documento=body.documento or "baixa pelo painel",
            observacao="lançada manualmente",
        )
        if not alvo:
            raise HTTPException(status_code=404, detail="Título não encontrado")
        carteira.salvar()
        return {"id": alvo.id, "saldo": alvo.saldo, "status": alvo.status}

    return app


def _list_runs(tasks_dir: Path, limit: int = 40) -> list[dict[str, Any]]:
    files = sorted(tasks_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "status": data.get("status"),
                    "client_id": data.get("client_id"),
                    "agents": data.get("agents"),
                    "needs_human": data.get("needs_human"),
                    "created_at": data.get("created_at"),
                    "llm": data.get("llm"),
                    "file": str(f),
                }
            )
        except json.JSONDecodeError:
            continue
    return out


def _execute_request(item: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    req_id = item["id"]
    service = item["service_id"]
    client_id = item.get("client_id")
    notes = item.get("notes") or ""
    model = item.get("model")
    folder = item.get("folder")

    requests_board.update_request(s.requests_dir, req_id, status="running")

    try:
        if service == "whatsapp":
            summary = (
                "Atendimento WhatsApp em produção fica na Secretaria/EsconZap "
                f"({PROJECT_ROOT.parent / 'Secretaria'}). "
                "Não executar aqui para não duplicar canal."
            )
            updated = requests_board.update_request(
                s.requests_dir,
                req_id,
                status="done",
                result_summary=summary,
            )
            return updated or item

        if service == "contmatic":
            if not client_id:
                raise ValueError("Informe client_id para Contmatic")
            result = run_contmatic_pipeline(client_id, folder=folder, settings=s)
            status = "waiting_human" if result.get("needs_human") else "done"
            if not result.get("success"):
                status = "failed"
            updated = requests_board.update_request(
                s.requests_dir,
                req_id,
                status=status,
                result_summary=result.get("summary"),
                run_id=None,
            )
            # also log as run-like file
            run_path = s.tasks_dir / f"run_req_{req_id}.json"
            run_path.write_text(
                json.dumps(
                    {
                        "id": f"req_{req_id}",
                        "title": f"Contmatic {client_id}",
                        "status": status,
                        "client_id": client_id,
                        "agents": ["xavier", "bill"],
                        "results": [
                            {
                                "agent": "contmatic_pipeline",
                                "success": result.get("success"),
                                "summary": result.get("summary"),
                                "artifacts": result.get("artifacts"),
                            }
                        ],
                        "needs_human": result.get("needs_human"),
                        "created_at": result.get("started_at"),
                        "pipeline": result,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            return updated or item

        if service == "sync_drive":
            from escon_agentes.tools.drive_inbox import detect_drive_root, sync_drive_to_inbox
            from escon_agentes.tools.radar_sync import sync_client_inbox

            if detect_drive_root(s.google_drive_radar_root or None):
                result = sync_drive_to_inbox(
                    clients_dir=s.clients_dir,
                    inbox_root=s.inbox,
                    drive_root=s.google_drive_radar_root or None,
                    client_id=client_id,
                )
            elif client_id:
                result = sync_client_inbox(
                    client_id,
                    clients_dir=s.clients_dir,
                    inbox_root=s.inbox,
                    limit=100,
                )
            else:
                raise ValueError(
                    "Drive local não encontrado. Informe um cliente para sync via MinIO "
                    "ou configure GOOGLE_DRIVE_RADAR_ROOT."
                )
            status = "done" if result.get("success") is not False else "failed"
            updated = requests_board.update_request(
                s.requests_dir,
                req_id,
                status=status,
                result_summary=result.get("summary"),
            )
            return updated or item

        # Map service → natural language + agent
        agent_map = {
            "xmls": ("xavier", "Organize e analise os XMLs fiscais"),
            "documentos": ("bill", "Capture e classifique os documentos PDF da pasta"),
            "conciliar": ("john", "Concilie o extrato bancário com os lançamentos"),
            "cobrar_extratos": ("greg", "Cobre extratos bancários pendentes"),
            "tarefas": ("anne", "Mostre tarefas e prazos que precisam de atenção"),
            "certidoes": ("cesar", "Atualize e mostre certidões que precisam de atenção"),
            "reforma": ("lucy", notes or "Explique pontos da Reforma Tributária para Simples/MEI"),
            "briefing": ("karen", notes or "Prepare briefing contábil/tributário"),
            "financeiro": ("paul", "Analise o fluxo de caixa do extrato do cliente"),
        }
        if service not in agent_map:
            raise ValueError(f"Serviço não executável: {service}")

        agent, pedido = agent_map[service]
        if notes and service not in {"reforma", "briefing"}:
            pedido = f"{pedido}. {notes}"

        orch = Orchestrator(model=model)
        params: dict[str, Any] = {}
        if folder:
            params["folder"] = folder
        result = orch.run(pedido, client_id=client_id, agent=agent, params=params)

        status = result.get("status") or "done"
        summary_parts = [
            r.get("summary", "")[:400] for r in result.get("results") or []
        ]
        updated = requests_board.update_request(
            s.requests_dir,
            req_id,
            status=status,
            run_id=result.get("id"),
            result_summary=" | ".join(summary_parts)[:1000],
        )
        return updated or item

    except Exception as exc:  # noqa: BLE001
        updated = requests_board.update_request(
            s.requests_dir,
            req_id,
            status="failed",
            result_summary=str(exc),
        )
        return updated or item
