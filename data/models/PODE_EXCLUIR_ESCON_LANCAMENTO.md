# Pode excluir o projeto Escon_Lancamento

**Data:** 2026-08-01  
**Status:** Importação concluída. O projeto legado **não é mais necessário**.

## Pasta legada (pode apagar)

```
C:\Users\ander\OneDrive\Desktop\Projetos\Escon_Lancamento
```

(Se ainda existir cópia em `Documents\Escon_Lancamento`, também pode apagar.)

## O que foi trazido para os Agentes Contábeis

| Item | Destino |
|------|---------|
| PlContas.TXT | `Agentes Contabeis Escon\data\models\PlContas.TXT` |
| Modelo xlsx | `...\data\models\0001_2026_lctos.xlsx` |
| PDF plano | `...\data\models\Plano de Contas.pdf` |
| Layout Excel 10 colunas | código em `src\escon_agentes\tools\contmatic.py` |
| Índice 281 contas | `data\models\plcontas_index.json` |

## Sistema único a manter

```
C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon
```

Não é necessário manter o RPA antigo (Gemini/Telegram/OneDrive Graph) — o fluxo atual é Radar → inbox → Contabilizador → Excel Contmatic → revisão no dashboard.
