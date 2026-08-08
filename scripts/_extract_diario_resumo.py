"""Extrai lançamentos de resumo da folha do Diário (treinamento)."""
import re
from pathlib import Path

import pdfplumber

path = Path(r"C:\Users\ander\Downloads\Diario.pdf")
with pdfplumber.open(path) as pdf:
    full = "\n".join((p.extract_text() or "") for p in pdf.pages)

# Bloco: DATA LCTO DEB... / CRED... / HIST
pat = re.compile(
    r"(\d{2}/\d{2})\s+(\d+)\s+(\d{7})([^\n]*?)\s*([\d.]+,\d{2})\s*\n"
    r"(\d{7})([^\n]*?)\s*([\d.]+,\d{2})\s*\n"
    r"([^\n]+)"
)
print("matches", len(pat.findall(full)))
for m in pat.finditer(full):
    data, n, d, dn, dv, c, cn, cv, hist = m.groups()
    n = int(n)
    if data != "31/01":
        continue
    if n < 138 or (165 < n < 295) or n > 312:
        continue
    hist = re.sub(r"\s+", " ", hist).strip()
    # skip pure individual names for a moment — keep resumo-ish (no "comp 01/2021" or short hist)
    is_indiv = "comp 01/2021" in hist or "comp 01/2021" in hist
    print(f"{data} #{n}: D {d} C {c}  {dv}  | {hist[:70]}")
