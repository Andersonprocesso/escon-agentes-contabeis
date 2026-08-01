# Agentes Contábeis Escon

Multiagente + **dashboard web** (GitHub + Vercel, padrão EsconManus) para a **Escon Soluções Contábeis**.

**Leia sempre:** [`docs/ESCON-CONTEXTO.md`](docs/ESCON-CONTEXTO.md) · Deploy: [`docs/DEPLOY-VERCEL.md`](docs/DEPLOY-VERCEL.md)

## Dashboard (Vercel)

- **Login** protegido (`ADMIN_PASSWORD`)
- **Chat** com Max, Xavier, Lucy, Greg… via OpenRouter
- **Clientes** (snapshot dos 87 do Radar)
- **Serviços** e atalhos de operação Contmatic

```powershell
# local: servir estático + API Python completa
$env:PYTHONPATH=".\src"
python -m escon_agentes dashboard   # http://127.0.0.1:8787

# snapshot para o painel Vercel
python scripts/export_clients_snapshot.py
```

## Mapa de sistemas (não duplicar)

| Sistema | O que faz | Onde |
|---------|-----------|------|
| **Oneflow** | DP + Fiscal 100%; Contábil em cadastro | SaaS |
| **Legado** | Contabilidades atrasadas (~R$ 1.100/mês) | até migrar Contábil |
| **Contmatic** | Importar lançamentos (Excel) | **prioridade #1 deste repo** |
| **Secretaria** | WhatsApp produção (EsconZap) | `Projetos\Secretaria` |
| **Radar Escon** | RFB/SEFAZ → Google Drive (~85 Simples + 15 MEI) | `Projetos\Radar Escon` |
| **Este repo** | Agentes Contmatic + painel colaboradoras | aqui |

## Radar → cadastro + inbox

```powershell
cd "C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon"
$env:PYTHONPATH=".\src"

# 1) Importa empresas do Postgres do Radar (SSH VPS)
python -m escon_agentes import-radar

# 2a) Inbox automática — Google Drive local (se Drive for Desktop estiver instalado)
# No .env: GOOGLE_DRIVE_RADAR_ROOT=G:\Meu Drive\Radar Escon
python -m escon_agentes sync-drive --via drive
python -m escon_agentes sync-drive --watch --interval 900   # a cada 15 min

# 2b) Sem Drive local: mesma árvore via MinIO do Radar (recomendado agora)
python -m escon_agentes sync-drive -c 07603336000198 --via minio --limit 50
# ou só XML: python -m escon_agentes sync-inbox -c 07603336000198 --limit 50

python -m escon_agentes list-clients
```

## Prioridade #1 — Contmatic

- **Aliases operacionais:** `config/plano_contas.yaml` (Contabilizador)
- **Plano completo Contmatic:** `data/models/PlContas.TXT` (importado do Escon_Lancamento)
- **Modelo de planilha:** `data/models/0001_2026_lctos.xlsx` (layout 10 colunas)
- Excel gerado: data `DD.MM.AAAA` + colunas CCDB/CCCR/CNPJ

```powershell
python -m escon_agentes plano-contas --rebuild
python -m escon_agentes contmatic -c 07603336000198
# Excel em data\outbox\{cliente}\contmatic\
```

> O projeto legado `Escon_Lancamento` já foi absorvido nos modelos acima e **pode ser excluído**.

## Dashboard (colaboradoras)

```powershell
pip install fastapi "uvicorn[standard]"
$env:PYTHONPATH=".\src"
python -m escon_agentes dashboard
# abra http://127.0.0.1:8787
```

No painel a equipe:

- vê **KPIs** (aguardando humano, fila, tarefas)
- vê **o que cada agente fez** em cada run
- **solicita serviços** (Contmatic, XML, conciliação, etc.)
- escolhe **modelo** OpenRouter (kimi, gpt/gps, grok, deepseek, gemini, claude)

## OpenRouter (multi-modelo)

```powershell
copy .env.example .env
# OPENROUTER_API_KEY=sk-or-...
# LLM_MODEL=deepseek
```

```powershell
python -m escon_agentes list-models
python -m escon_agentes run "Explique reforma para MEI" -a lucy -m kimi
```

Aliases em `config/models.yaml` (GPS = GPT).

## CLI útil

```powershell
python -m escon_agentes list-agents
python -m escon_agentes contmatic -c demo-servicos
python -m escon_agentes run "Concilie extrato" -c demo-servicos -m deepseek
python -m escon_agentes pipeline -c demo-servicos
python -m escon_agentes dashboard
```

## Integração futura

1. Radar → baixar XMLs do Drive para `data/inbox/{cliente}`  
2. Contabilizador skill → unificar regras de conta com Contmatic  
3. Secretaria → Greg/Bella só preparam texto; envio real no Chatwoot  
4. Oneflow Contábil → quando cadastro 100%, reduzir papel do legado  

## Governança

Agente **prepara**; contador **aprova** importação Contmatic e orientação fiscal.
