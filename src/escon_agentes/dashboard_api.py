"""API + dashboard web para colaboradoras da Escon."""

from __future__ import annotations

import json
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
    usar_llm: bool = True


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

    class QuickRun(BaseModel):
        pedido: str
        client_id: Optional[str] = None
        agent: Optional[str] = None
        model: Optional[str] = None
        folder: Optional[str] = None

    @app.post("/api/run")
    def api_run(body: QuickRun) -> dict[str, Any]:
        orch = Orchestrator(model=body.model)
        params = {}
        if body.folder:
            params["folder"] = body.folder
        return orch.run(
            body.pedido,
            client_id=body.client_id,
            agent=body.agent,
            params=params,
        )

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

        estado = fx.carregar(get_settings(), client_id, competencia) or {}
        caminho = estado.get("planilha")
        if not caminho or not Path(caminho).exists():
            raise HTTPException(status_code=404, detail="Planilha ainda não gerada")
        return FileResponse(
            caminho,
            filename=f"lancamentos_{client_id}_{competencia}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

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
