"""Parser simples de OFX e CSV bancário para conciliação."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class BankTxn:
    date: str
    amount: float
    memo: str
    fitid: str | None = None
    trntype: str | None = None


def parse_ofx(path: Path) -> list[BankTxn]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Remove header SGML pré-XML se houver
    if "<OFX>" in text.upper():
        idx = text.upper().find("<OFX>")
        text = text[idx:]

    txns: list[BankTxn] = []
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, flags=re.I | re.S)
    if not blocks:
        # OFX 1.x sem fechamento
        blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|$)", text, flags=re.I | re.S)

    for block in blocks:
        def field(name: str) -> str | None:
            m = re.search(rf"<{name}>([^<\r\n]+)", block, flags=re.I)
            return m.group(1).strip() if m else None

        dt = field("DTPOSTED") or ""
        # YYYYMMDD...
        if len(dt) >= 8:
            date = f"{dt[6:8]}/{dt[4:6]}/{dt[0:4]}"
        else:
            date = dt
        amt_raw = (field("TRNAMT") or "0").replace(",", ".")
        try:
            amount = float(amt_raw)
        except ValueError:
            amount = 0.0
        memo = field("MEMO") or field("NAME") or ""
        txns.append(
            BankTxn(
                date=date,
                amount=amount,
                memo=memo,
                fitid=field("FITID"),
                trntype=field("TRNTYPE"),
            )
        )
    return txns


def parse_csv_bank(path: Path) -> list[BankTxn]:
    """CSV genérico: data, descricao, valor (ou débito/crédito)."""
    txns: list[BankTxn] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return txns
        fields = {h.lower().strip(): h for h in reader.fieldnames}

        def col(*names: str) -> str | None:
            for n in names:
                if n in fields:
                    return fields[n]
            return None

        c_date = col("data", "date", "dt")
        c_memo = col("descricao", "descrição", "memo", "historico", "histórico", "name")
        c_val = col("valor", "amount", "vlr")
        c_deb = col("debito", "débito", "debit")
        c_cred = col("credito", "crédito", "credit")

        for row in reader:
            date = (row.get(c_date) or "").strip() if c_date else ""
            memo = (row.get(c_memo) or "").strip() if c_memo else ""
            amount = 0.0
            if c_val and row.get(c_val):
                amount = _br_float(row[c_val])
            else:
                deb = _br_float(row.get(c_deb) or "0") if c_deb else 0.0
                cred = _br_float(row.get(c_cred) or "0") if c_cred else 0.0
                amount = cred - deb
            txns.append(BankTxn(date=date, amount=amount, memo=memo))
    return txns


def _br_float(s: str) -> float:
    s = str(s).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_bank_file(path: Path) -> list[BankTxn]:
    suf = path.suffix.lower()
    if suf == ".ofx":
        return parse_ofx(path)
    if suf in {".csv", ".txt"}:
        return parse_csv_bank(path)
    raise ValueError(f"Formato não suportado: {suf}")


def reconcile(
    bank: list[BankTxn],
    book: list[dict[str, Any]],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """
    book items: {date?, amount, memo?}
    Matching simples por valor (+-tolerance), depois remove pares.
    """
    bank_left = list(enumerate(bank))
    book_left = list(enumerate(book))
    matched: list[dict] = []
    used_bank: set[int] = set()
    used_book: set[int] = set()

    for bi, bt in bank_left:
        for ki, kt in book_left:
            if ki in used_book:
                continue
            bamt = float(kt.get("amount") or kt.get("valor") or 0)
            if abs(bt.amount - bamt) <= tolerance:
                matched.append(
                    {
                        "bank": asdict(bt),
                        "book": kt,
                        "diff": round(bt.amount - bamt, 2),
                    }
                )
                used_bank.add(bi)
                used_book.add(ki)
                break

    only_bank = [asdict(bank[i]) for i, _ in bank_left if i not in used_bank]
    only_book = [book[i] for i, _ in book_left if i not in used_book]

    return {
        "matched": matched,
        "only_bank": only_bank,
        "only_book": only_book,
        "stats": {
            "bank_total": len(bank),
            "book_total": len(book),
            "matched": len(matched),
            "only_bank": len(only_bank),
            "only_book": len(only_book),
        },
    }


def summary_reconcile(report: dict[str, Any]) -> str:
    s = report["stats"]
    return (
        f"Conciliação: {s['matched']} pareados | "
        f"{s['only_bank']} só no extrato | "
        f"{s['only_book']} só na contabilidade "
        f"(banco={s['bank_total']}, livro={s['book_total']})"
    )
