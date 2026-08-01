"""CLI — Escon Agentes Contábeis."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from escon_agentes.agents import AGENT_CLASSES  # noqa: E402
from escon_agentes.config import get_settings  # noqa: E402
from escon_agentes.llm import list_model_aliases  # noqa: E402
from escon_agentes.orchestrator import Orchestrator  # noqa: E402
from escon_agentes.schema import ClientProfile  # noqa: E402
from escon_agentes.tools.clients import (  # noqa: E402
    as_table,
    ensure_demo_clients,
    list_clients,
    save_client,
)
from escon_agentes.workflows.contmatic_pipeline import run_contmatic_pipeline  # noqa: E402

app = typer.Typer(
    name="escon-agentes",
    help="Sistema multiagente contábil — Escon Soluções Contábeis",
    add_completion=False,
)
console = Console()


def _print_run(result: dict) -> None:
    console.print(
        Panel.fit(
            f"[bold]Run[/bold] {result.get('id')}  |  "
            f"status=[cyan]{result.get('status')}[/cyan]  |  "
            f"LLM={result.get('llm')}  model={result.get('model')}\n"
            f"[dim]{result.get('reasoning')}[/dim]",
            title="Escon Agentes",
        )
    )
    for r in result.get("results", []):
        color = "green" if r["success"] else "red"
        console.print(f"\n[bold {color}]● {r['agent'].upper()}[/bold {color}]")
        console.print(Markdown(r["summary"] if r["summary"].startswith("#") else r["summary"]))
        if r.get("artifacts"):
            console.print(f"  [dim]artefatos: {', '.join(r['artifacts'])}[/dim]")
        if r.get("needs_human"):
            console.print(f"  [yellow]⏸ humano: {r.get('human_prompt')}[/yellow]")
    if result.get("needs_human"):
        console.print("\n[bold yellow]Itens aguardando revisão humana:[/bold yellow]")
        for n in result["needs_human"]:
            console.print(f"  • {n}")
    if result.get("run_file"):
        console.print(f"\n[dim]Log: {result.get('run_file')}[/dim]")


@app.command()
def run(
    pedido: str = typer.Argument(..., help="Pedido em linguagem natural"),
    cliente: Optional[str] = typer.Option(None, "--cliente", "-c"),
    agente: Optional[str] = typer.Option(None, "--agente", "-a"),
    pasta: Optional[str] = typer.Option(None, "--pasta", "-p"),
    modelo: Optional[str] = typer.Option(
        None, "--modelo", "-m", help="Alias: kimi|gpt|gps|grok|deepseek|gemini|claude"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Executa um pedido via Max (ou agente específico)."""
    params = {}
    if pasta:
        params["folder"] = pasta
    orch = Orchestrator(model=modelo)
    result = orch.run(pedido, client_id=cliente, agent=agente, params=params, model=modelo)
    if json_out:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    _print_run(result)


@app.command()
def contmatic(
    cliente: str = typer.Option(..., "--cliente", "-c"),
    pasta: Optional[str] = typer.Option(None, "--pasta", "-p"),
) -> None:
    """Prioridade #1: gera Excel Contmatic a partir da pasta do cliente."""
    result = run_contmatic_pipeline(cliente, folder=pasta)
    console.print_json(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("success"):
        console.print(f"\n[green]{result.get('summary')}[/green]")
        console.print("[yellow]Revise o Excel antes de importar no Contmatic.[/yellow]")
    else:
        console.print(f"\n[red]{result.get('summary')}[/red]")
        raise typer.Exit(1)


@app.command("list-models")
def list_models() -> None:
    """Lista aliases OpenRouter configurados."""
    s = get_settings()
    table = Table(title="Modelos (OpenRouter)")
    table.add_column("Alias")
    table.add_column("Model ID")
    for k, v in list_model_aliases(s).items():
        table.add_row(k, v)
    console.print(table)
    console.print(f"Provider ativo: [cyan]{s.active_provider()}[/cyan]")
    if s.llm_available:
        console.print(f"Modelo padrão: [cyan]{s.resolve_model()}[/cyan]")
    else:
        console.print("[yellow]Configure OPENROUTER_API_KEY no .env[/yellow]")


@app.command("list-agents")
def list_agents() -> None:
    table = Table(title="Agentes Escon")
    table.add_column("ID")
    table.add_column("Nome")
    table.add_column("Papel")
    for aid, cls in AGENT_CLASSES.items():
        table.add_row(aid.value, cls.name, cls.role)
    console.print(table)


@app.command()
def status() -> None:
    orch = Orchestrator()
    console.print(Panel(orch.status(), title="Max — Status"))


@app.command("list-clients")
def list_clients_cmd() -> None:
    s = get_settings()
    ensure_demo_clients(s.clients_dir)
    rows = as_table(list_clients(s.clients_dir))
    table = Table(title=f"Clientes ({len(rows)})")
    for col in ("id", "nome", "telefone", "email", "regime", "uf"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["id"][:14],
            (r["nome"] or "")[:32],
            (r.get("telefone") or r.get("whatsapp") or "")[:16],
            (r.get("email") or "")[:28],
            r["regime"],
            r.get("uf") or "",
        )
    console.print(table)


@app.command("edit-client")
def edit_client_cmd(
    client_id: str = typer.Argument(...),
    nome: Optional[str] = typer.Option(None, "--nome"),
    telefone: Optional[str] = typer.Option(None, "--telefone"),
    email: Optional[str] = typer.Option(None, "--email"),
    regime: Optional[str] = typer.Option(None, "--regime"),
    banco: Optional[str] = typer.Option(None, "--banco"),
    uf: Optional[str] = typer.Option(None, "--uf"),
) -> None:
    """Edita telefone, e-mail e dados do cliente (para Greg/cobranças)."""
    from escon_agentes.tools.clients import update_client

    s = get_settings()
    patch = {
        k: v
        for k, v in {
            "nome": nome,
            "telefone": telefone,
            "email": email,
            "regime": regime,
            "banco": banco,
            "uf": uf,
        }.items()
        if v is not None
    }
    if not patch:
        console.print("[yellow]Nada a alterar. Use --telefone, --email, --nome…[/yellow]")
        raise typer.Exit(1)
    c = update_client(s.clients_dir, client_id, patch)
    if not c:
        console.print(f"[red]Cliente não encontrado: {client_id}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]OK[/green] {c.name} | tel={c.telefone or '-'} | email={c.email or '-'}"
    )


@app.command("delete-client")
def delete_client_cmd(
    client_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Exclui cliente do cadastro local."""
    from escon_agentes.tools.clients import delete_client, get_client

    s = get_settings()
    c = get_client(s.clients_dir, client_id)
    if not c:
        console.print(f"[red]Não encontrado: {client_id}[/red]")
        raise typer.Exit(1)
    if not yes:
        console.print(f"Confirme exclusão de {c.name} ({client_id}) com --yes")
        raise typer.Exit(1)
    delete_client(s.clients_dir, client_id, inbox_root=s.inbox, remove_inbox=False)
    console.print(f"[green]Excluído:[/green] {client_id}")


@app.command("import-radar")
def import_radar_cmd(
    arquivo: Optional[str] = typer.Option(
        None, "--arquivo", "-f", help="JSON/CSV exportado; se omitido, busca na VPS via SSH"
    ),
    keep_demo: bool = typer.Option(True, "--keep-demo/--no-keep-demo"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Passo 1: importa empresas do Radar Escon para o cadastro local + pastas inbox."""
    from escon_agentes.tools.radar_import import import_radar_clients
    from escon_agentes.tools.radar_sync import export_empresas_via_ssh

    s = get_settings()
    if arquivo:
        path = Path(arquivo)
    else:
        path = s.data_dir / "imports" / "radar_empresas.json"
        console.print("[cyan]Exportando empresas da VPS Radar…[/cyan]")
        export_empresas_via_ssh(path)
        console.print(f"[dim]Salvo em {path}[/dim]")

    report = import_radar_clients(
        path,
        clients_dir=s.clients_dir,
        inbox_root=s.inbox,
        keep_demo=keep_demo,
        dry_run=dry_run,
    )
    console.print_json(json.dumps(report, ensure_ascii=False, indent=2))
    if not dry_run:
        console.print(
            f"[green]Import OK:[/green] {report['total']} empresas "
            f"(+{report['created']} novas, ~{report['updated']} atualizadas)"
        )


@app.command("sync-inbox")
def sync_inbox_cmd(
    cliente: str = typer.Option(..., "--cliente", "-c", help="ID local (CNPJ sem máscara)"),
    competencia: Optional[str] = typer.Option(
        None, "--competencia", "-m", help="AAAA-MM (ex.: 2026-07)"
    ),
    limit: int = typer.Option(200, "--limit"),
    tipos: Optional[str] = typer.Option(
        None, "--tipos", help="Lista separada por vírgula (default: nfe_xml,nfse_xml,nfce_xml,guia_pdf)"
    ),
) -> None:
    """Baixa XMLs/PDFs do MinIO do Radar (VPS) → data/inbox/{cliente}."""
    from escon_agentes.tools.radar_sync import DEFAULT_TIPOS, sync_client_inbox

    s = get_settings()
    t = tuple(x.strip() for x in tipos.split(",")) if tipos else DEFAULT_TIPOS
    try:
        result = sync_client_inbox(
            cliente,
            clients_dir=s.clients_dir,
            inbox_root=s.inbox,
            competencia=competencia,
            tipos=t,
            limit=limit,
        )
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print_json(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    console.print(f"[green]{result.get('summary')}[/green]")


@app.command("sync-drive")
def sync_drive_cmd(
    cliente: Optional[str] = typer.Option(None, "--cliente", "-c"),
    competencia: Optional[str] = typer.Option(None, "--competencia", "-m"),
    root: Optional[str] = typer.Option(
        None, "--root", help="Pasta local 'Radar Escon' do Google Drive for Desktop"
    ),
    via: str = typer.Option(
        "auto",
        "--via",
        help="auto | drive | minio — minio usa a mesma árvore do Drive na VPS (SSH)",
    ),
    full: bool = typer.Option(False, "--full", help="Re-copia tudo (ignora estado no modo drive)"),
    limit: int = typer.Option(100, "--limit", help="Máx. arquivos por cliente no modo minio"),
    watch: bool = typer.Option(False, "--watch", help="Loop a cada N segundos"),
    interval: int = typer.Option(900, "--interval", help="Segundos entre ciclos no --watch"),
) -> None:
    """Inbox automática: Google Drive local ou MinIO do Radar (espelho do Drive)."""
    import time

    from escon_agentes.tools.drive_inbox import detect_drive_root, sync_drive_to_inbox, watch_hint
    from escon_agentes.tools.radar_sync import sync_client_inbox

    s = get_settings()
    drive_root = root or s.google_drive_radar_root or None
    via_l = via.lower().strip()

    def once_drive() -> dict:
        return sync_drive_to_inbox(
            clients_dir=s.clients_dir,
            inbox_root=s.inbox,
            drive_root=Path(drive_root) if drive_root else None,
            client_id=cliente,
            competencia=competencia,
            only_new=not full,
        )

    def once_minio() -> dict:
        clients = list_clients(s.clients_dir)
        if cliente:
            clients = [c for c in clients if c.id == cliente]
        results = []
        total = 0
        for c in clients:
            if not c.radar_id:
                continue
            try:
                r = sync_client_inbox(
                    c.id,
                    clients_dir=s.clients_dir,
                    inbox_root=s.inbox,
                    competencia=competencia,
                    limit=limit,
                )
                total += int(r.get("files_downloaded") or 0)
                results.append(r)
            except Exception as e:  # noqa: BLE001
                results.append({"client_id": c.id, "error": str(e)})
        return {
            "success": True,
            "via": "minio",
            "summary": f"MinIO (espelho Drive): {total} arquivo(s) em {len(results)} cliente(s)",
            "total_files": total,
            "clients": results[:50],
        }

    def once() -> dict:
        mode = via_l
        if mode == "auto":
            if detect_drive_root(drive_root):
                mode = "drive"
            else:
                mode = "minio"
                console.print(
                    "[yellow]Drive local não encontrado — usando MinIO do Radar "
                    "(mesma árvore do Google Drive).[/yellow]"
                )
        if mode == "drive":
            return once_drive()
        if mode == "minio":
            return once_minio()
        raise typer.BadParameter("--via deve ser auto, drive ou minio")

    detected = detect_drive_root(drive_root)
    if detected:
        console.print(f"[dim]Drive root: {detected}[/dim]")
    elif via_l in ("auto", "drive"):
        console.print(f"[dim]{watch_hint()}[/dim]")

    if not watch:
        result = once()
        console.print_json(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        color = "green" if result.get("success") else "red"
        console.print(f"[{color}]{result.get('summary')}[/{color}]")
        if not result.get("success"):
            raise typer.Exit(1)
        return

    console.print(f"[cyan]Watch inbox automática a cada {interval}s (Ctrl+C para parar)[/cyan]")
    try:
        while True:
            result = once()
            stamp = time.strftime("%H:%M:%S")
            console.print(f"[dim]{stamp}[/dim] {result.get('summary')}")
            time.sleep(max(60, interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch encerrado.[/yellow]")


@app.command("plano-contas")
def plano_contas_cmd(
    rebuild: bool = typer.Option(False, "--rebuild", help="Reparseia PlContas.TXT"),
) -> None:
    """Mostra aliases Contabilizador + índice completo PlContas (Contmatic)."""
    from escon_agentes.tools.plano_contas import contas, historicos, load_plano, plcontas_index
    from escon_agentes.tools.plcontas_parser import load_or_build_index

    if rebuild:
        idx = load_or_build_index(force=True)
        console.print(f"[green]PlContas reindexado: {idx['total']} contas[/green]")
    else:
        idx = plcontas_index()

    plano = load_plano()
    console.print(f"[bold]Aliases operacionais:[/bold] versao={plano.get('versao')}")
    table = Table(title="Contas usadas no motor (Contabilizador)")
    table.add_column("Nome")
    table.add_column("Código")
    for k, v in sorted(contas().items(), key=lambda x: x[1]):
        table.add_row(k, str(v))
    console.print(table)

    console.print(
        f"[bold]PlContas Contmatic completo:[/bold] {idx.get('total')} contas "
        f"(data/models/PlContas.TXT)"
    )
    # amostra
    sample = (idx.get("contas") or [])[:12]
    t2 = Table(title="Amostra PlContas")
    t2.add_column("Reduzida")
    t2.add_column("Descrição")
    t2.add_column("Analítica")
    for c in sample:
        t2.add_row(str(c["reduzida"]), c["descricao"][:40], c["analitica"])
    console.print(t2)

    ht = Table(title="Históricos padrão")
    ht.add_column("Cód.")
    ht.add_column("Descrição")
    for k, v in sorted(historicos().items()):
        ht.add_row(str(k), v)
    console.print(ht)


@app.command("add-client")
def add_client(
    client_id: str = typer.Argument(...),
    nome: str = typer.Option(..., "--nome"),
    cnpj: Optional[str] = typer.Option(None, "--cnpj"),
    regime: str = typer.Option("simples_nacional", "--regime"),
    banco: str = typer.Option("itau", "--banco"),
) -> None:
    s = get_settings()
    c = ClientProfile(id=client_id, name=nome, cnpj=cnpj, regime=regime, banco_principal=banco)
    path = save_client(s.clients_dir, c)
    console.print(f"[green]Cliente salvo:[/green] {path}")


@app.command()
def pipeline(
    cliente: str = typer.Option(..., "--cliente", "-c"),
    pasta: Optional[str] = typer.Option(None, "--pasta", "-p"),
    modelo: Optional[str] = typer.Option(None, "--modelo", "-m"),
) -> None:
    """Pipeline mensal amplo (Greg → Xavier → Bill → John → Anne → Cesar)."""
    pedido = f"Execute o fechamento mensal / pipeline do cliente {cliente}"
    params = {"folder": pasta} if pasta else {}
    orch = Orchestrator(model=modelo)
    result = orch.run(pedido, client_id=cliente, params=params, model=modelo)
    console.print_json(
        json.dumps(
            {
                "id": result["id"],
                "status": result["status"],
                "agents": result["agents"],
                "needs_human": result["needs_human"],
                "summaries": {r["agent"]: r["summary"][:300] for r in result["results"]},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def dashboard(
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
) -> None:
    """Sobe o painel web para as colaboradoras (http://127.0.0.1:8787)."""
    s = get_settings()
    h = host or s.dashboard_host
    p = port or s.dashboard_port
    try:
        import uvicorn
    except ImportError as e:
        console.print("[red]Instale fastapi e uvicorn: pip install fastapi uvicorn[/red]")
        raise typer.Exit(1) from e

    console.print(
        Panel.fit(
            f"Dashboard: [bold cyan]http://{h}:{p}[/bold cyan]\n"
            f"Prioridade: Contmatic · WhatsApp produção = Secretaria",
            title="Escon Agentes",
        )
    )
    uvicorn.run(
        "escon_agentes.dashboard_api:create_app",
        factory=True,
        host=h,
        port=p,
        reload=False,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
