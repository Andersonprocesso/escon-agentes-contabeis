# Modelos Contmatic (importados do Escon_Lancamento)

Fonte original (pode ser excluída após esta importação):

`C:\Users\ander\OneDrive\Desktop\Projetos\Escon_Lancamento`

| Arquivo | Uso |
|---------|-----|
| `PlContas.TXT` | Export do plano de contas Contmatic (conta reduzida + analítica) |
| `plcontas_index.json` | Índice gerado (`python -m escon_agentes plano-contas --rebuild`) |
| `0001_2026_lctos.xlsx` | Modelo de planilha de importação (abas Lançamentos + plano) |
| `Plano de Contas.pdf` | Referência visual |
| `reference_excel_generator.py` | Código de referência do gerador antigo (não executar) |

O pipeline atual usa:

- motor `contabilizador_engine.py` + `config/plano_contas.yaml` (aliases do dia a dia)
- layout Excel do Escon_Lancamento (10 colunas, data `DD.MM.AAAA`)
- índice `PlContas.TXT` para validar/consultar códigos reais
