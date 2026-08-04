"""John — Conciliação bancária."""

from __future__ import annotations

import json
from pathlib import Path

from escon_agentes.agents.base import BaseAgent
from escon_agentes.schema import AgentId, AgentResult, AgentTask
from escon_agentes.tools import ofx_parser
from escon_agentes.tools.clients import client_inbox


class JohnAgent(BaseAgent):
    id = AgentId.JOHN
    name = "John"
    role = "Conciliação Bancária"
    system_prompt = """
Você auxilia na conciliação bancária: lê OFX/CSV, cruza com lançamentos e aponta divergências.
Nunca marque conciliação como final sem revisão humana.
"""

    def run(self, task: AgentTask) -> AgentResult:
        folder = self._resolve_folder(task)
        bank_file = task.input.get("bank_file")
        book_file = task.input.get("book_file")

        bank_path = Path(bank_file) if bank_file else self._find_bank(folder)
        if not bank_path or not bank_path.exists():
            return self.result_fail(
                "Extrato OFX/CSV não encontrado. Informe bank_file ou coloque .ofx na pasta do cliente."
            )

        bank = ofx_parser.load_bank_file(bank_path)
        book: list[dict] = []
        if book_file and Path(book_file).exists():
            book = json.loads(Path(book_file).read_text(encoding="utf-8"))
        else:
            # tenta book.json na pasta
            candidate = folder / "lancamentos.json"
            if candidate.exists():
                book = json.loads(candidate.read_text(encoding="utf-8"))

        report = ofx_parser.reconcile(bank, book)
        summary = ofx_parser.summary_reconcile(report)
        summary += f"\nExtrato: {bank_path} ({len(bank)} movimentos)"
        if not book:
            summary += (
                "\n⚠ Nenhum lançamento contábil informado (book_file/lancamentos.json). "
                "Listei só o extrato; forneça o livro para cruzar."
            )
            report["bank_preview"] = [
                {"date": t.date, "amount": t.amount, "memo": t.memo} for t in bank[:50]
            ]

        # Cruza o que sobrou no extrato com o razão auxiliar. Um pagamento que
        # bate certinho com um título em aberto não é divergência: é uma baixa
        # que ainda não foi lançada. Quem faz o acerto é o Alexandre, então o
        # aviso fica gravado na carteira para ele achar na próxima rodada.
        avisos = self._conferir_titulos(task.client_id, report)
        if avisos:
            report["baixas_a_lancar"] = avisos
            summary += (
                f"\n\n{len(avisos)} movimento(s) do extrato batem com título em "
                "aberto — são baixas de duplicata que faltam na contabilidade:"
            )
            for a in avisos[:8]:
                summary += (
                    f"\n  {a['data']}  R$ {a['valor']:,.2f}  "
                    f"→ dupl. {a['titulo_numero']}/{a['titulo_parcela']} "
                    f"{a['contraparte'][:26]}"
                )

        out = self.settings.outbox / (task.client_id or "geral") / "conciliacao.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        if self.llm.available:
            summary = self.think(
                f"Explique as divergências da conciliação para o contador:\n{summary}\n"
                f"Só no banco (amostra): {report.get('only_bank', [])[:5]}\n"
                f"Só no livro (amostra): {report.get('only_book', [])[:5]}"
            )

        return self.result_ok(
            summary,
            data=report,
            artifacts=[str(out)],
            needs_human=True,
            human_prompt="Conferir itens só no extrato / só na contabilidade.",
        )

    def _conferir_titulos(self, client_id: str | None, report: dict) -> list[dict]:
        """Movimentos do extrato que correspondem a título em aberto.

        Só entra aqui o que ficou sem par na conciliação (`only_bank`): se já
        estava lançado, não há o que avisar. E só quando o título é único —
        na dúvida o John não escolhe, igual ao Alexandre.
        """
        if not client_id:
            return []
        from escon_agentes.tools import titulos as tit

        carteira = tit.abrir_carteira(self.settings.data_dir, client_id)
        if not carteira.em_aberto():
            return []

        achados: list[dict] = []
        for mov in report.get("only_bank") or []:
            valor = abs(float(mov.get("amount") or 0))
            if not valor:
                continue
            # saída do banco paga fornecedor; entrada recebe de cliente
            tipo = tit.PAGAR if float(mov.get("amount") or 0) < 0 else tit.RECEBER
            data = str(mov.get("date") or "")
            cands = carteira.candidatos(tipo=tipo, valor=valor, data=data)
            if not cands or carteira.ambiguo(cands, valor, data):
                continue
            alvo = cands[0]
            achados.append({
                "data": data, "valor": valor, "memo": str(mov.get("memo") or "")[:60],
                "titulo_id": alvo.id, "titulo_numero": alvo.numero,
                "titulo_parcela": alvo.parcela, "contraparte": alvo.contraparte,
                "vencimento": alvo.vencimento,
            })
            carteira.registrar_ajuste(
                tipo="baixa_nao_lancada",
                motivo=(
                    f"Pagamento no extrato bate com a duplicata "
                    f"{alvo.numero}/{alvo.parcela} ({alvo.contraparte[:30]}), "
                    "que continua em aberto — falta lançar a baixa."
                ),
                documento=str(mov.get("memo") or "extrato")[:60],
                valor=valor, data=data,
            )
        if achados:
            carteira.salvar()
        return achados

    def _resolve_folder(self, task: AgentTask) -> Path:
        if task.input.get("folder"):
            return Path(task.input["folder"])
        if task.client_id:
            return client_inbox(self.settings.inbox, task.client_id)
        return self.settings.inbox

    def _find_bank(self, folder: Path) -> Path | None:
        if not folder.exists():
            return None
        for pattern in ("*.ofx", "*.OFX", "*.csv"):
            found = list(folder.rglob(pattern))
            if found:
                return found[0]
        return None
