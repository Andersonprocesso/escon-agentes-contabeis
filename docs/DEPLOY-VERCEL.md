# Deploy — Escon Agentes Contábeis (GitHub + Vercel)

Padrão igual ao **EsconManus**: frontend estático + API serverless Node em `/api`.

## 1. GitHub

```powershell
cd "C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon"
git init
git add .
git commit -m "Dashboard Escon Agentes Contábeis — Vercel + multiagente"
gh repo create Andersonprocesso/escon-agentes-contabeis --public --source=. --remote=origin --push
```

(Ajuste visibilidade `--private` se preferir.)

## 2. Vercel

1. [vercel.com](https://vercel.com) → **Add New Project** → importe `escon-agentes-contabeis`
2. Framework: **Other** (não Next.js)
3. Root: repositório raiz
4. **Environment Variables** (Production + Preview):

| Variável | Obrigatório | Exemplo |
|----------|-------------|---------|
| `ADMIN_PASSWORD` | sim | senha forte da equipe |
| `ADMIN_USER` | não | `admin` |
| `AUTH_SECRET` | recomendado | string aleatória longa |
| `OPENROUTER_API_KEY` | sim (chat) | `sk-or-v1-…` |
| `OPENROUTER_MODEL` | não | `deepseek/deepseek-chat` |
| `OPENROUTER_SITE_URL` | não | URL do projeto Vercel |
| `OPENROUTER_APP_NAME` | não | `Escon Agentes Contabeis` |

5. Deploy → URL tipo `https://escon-agentes-contabeis.vercel.app`

## 3. O que roda onde

| Função | Onde |
|--------|------|
| Login, chat multiagente, lista agentes, clientes (snapshot) | **Vercel** |
| Contmatic Excel, sync MinIO/Radar, pipeline arquivos | **PC ou VPS** (`python -m escon_agentes …`) |
| WhatsApp produção | **Secretaria** |

## 4. Atualizar snapshot de clientes

```powershell
$env:PYTHONPATH=".\src"
python scripts/export_clients_snapshot.py
git add data/web/clients_snapshot.json
git commit -m "Atualiza snapshot clientes Radar"
git push
```

## 5. API Python local (ops pesadas)

```powershell
$env:PYTHONPATH=".\src"
python -m escon_agentes dashboard
# http://127.0.0.1:8787
```
