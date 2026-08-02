# Escon Soluções Contábeis — Contexto canônico (memória compartilhada)

> **Leia este arquivo no início de qualquer trabalho** sobre a Escon, agentes contábeis, Radar, Secretaria, Oneflow ou Contmatic.  
> Atualizado por humanos e por agentes (Grok / Claude / Codex).  
> Caminho do projeto de agentes: `C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon`

---

## Escritório

| Campo | Valor |
|-------|--------|
| Nome | Escon Soluções Contábeis |
| Marca digital | Escon Digital (`escondigital.com.br`) |
| Responsável | Anderson |
| Carteira | ~**85 Simples Nacional** + ~**15 MEI** (somente esses 2 regimes) |
| Prioridade atual #1 | **Lançamentos contábeis no Contmatic** (zerar atraso e migrar 100% Contábil para Oneflow) |
| Custo legado | ~**R$ 1.100/mês** no sistema antigo até concluir contabilidades atrasadas |

---

## Sistemas em uso

| Sistema | Papel | Status |
|---------|--------|--------|
| **Oneflow** | DP + Fiscal (produção); Contábil em **fase de cadastro** | Destino final 100% |
| **Sistema legado** (antigo principal ~5 anos) | Contabilidades atrasadas ainda rodam aqui | Manter até migrar; custo R$ 1.100/mês |
| **Contmatic** | Importação de lançamentos contábeis (Excel do pipeline) | Prioridade operacional #1 |
| **Planilhas** | Controle de clientes e do escritório | Em uso paralelo |
| **Radar Escon** | Consultas RFB / SEFAZ / documentos → Google Drive; empresas cadastradas | `C:\Users\ander\OneDrive\Desktop\Projetos\Radar Escon` |
| **Secretaria** (fazer.ai agents + Chatwoot/EsconZap) | Agente WhatsApp em produção | `C:\Users\ander\OneDrive\Desktop\Projetos\Secretaria` |
| **EsconZap / CRM WhatsApp** | Canal de mensagens | Já integrado à Secretaria |
| **escon-contabil** | App contábil próprio (Next + .NET) | `Projetos\escon-contabil` / produção `contabil.escondigital.com.br` |
| **Agentes Contábeis Escon** | Multiagente Contmatic + dashboard operacional | este repositório |
| **Contabilizador** (skill) | XML/OFX/PDF → Excel Contmatic | `~\.claude\skills\user\contabilizador\` |

### O que NÃO duplicar

- **WhatsApp / atendimento**: já coberto pela **Secretaria**. Bella neste repo gera rascunhos/offline; produção = Secretaria.
- **Busca RFB/SEFAZ/Drive**: **Radar Escon**. Agentes leem artefatos baixados; não reimplementar portais sem necessidade.
- **DP e Fiscal do dia a dia**: **Oneflow** (já 100%).

---

## Prioridades (ordem)

1. **Lançamentos Contmatic** — processar pasta do cliente → Excel importável → revisão humana → importar  
2. Zerar atraso no legado e **migrar Contábil para Oneflow** (eliminar R$ 1.100/mês)  
3. Dashboard operacional para colaboradoras (fluxos, status, solicitar serviços)  
4. Integração Radar → Agentes → Contmatic (**import-radar + sync-inbox já implementados**)  
5. Manter Secretaria como fronteira WhatsApp (não competir)

---

## LLM / modelos

- Provedor preferido: **OpenRouter** (`OPENROUTER_API_KEY`)
- Modelos desejados (aliases no sistema):

| Alias | Uso típico | ID OpenRouter (ajustar se mudar) |
|-------|------------|-----------------------------------|
| `kimi` | Raciocínio / longo contexto | `moonshotai/kimi-k2` |
| `gpt` / `gps` | Geral (usuário escreve GPS = GPT) | `openai/gpt-4o-mini` |
| `grok` | Geral / xAI via OpenRouter | `x-ai/grok-4` |
| `deepseek` | Custo/benefício código e texto | `deepseek/deepseek-chat` |
| `gemini` | Multimodal / Google | `google/gemini-2.5-flash` |
| `claude` | Análise cuidadosa | `anthropic/claude-sonnet-4` |

Também aceita `XAI_API_KEY` direto se quiser xAI sem OpenRouter.

---

## Agentes deste repositório (Contábil)

| ID | Foco |
|----|------|
| max | Orquestrador + status |
| xavier | XMLs fiscais |
| bill | PDFs/recibos |
| john | Conciliação OFX |
| greg | Cobrança de extratos (mensagem; envio real = Secretaria) |
| anne | Tarefas/prazos |
| cesar | Certidões (cadastro local) |
| fernando | Certificados digitais A1 (lê Radar `credenciais_serpro`, avisa 15 dias antes / vencidos) |
| pedro | Cadastro de empresas (Sistema Acessórias = fonte de verdade → cadastro local / Radar) |
| paul | Insights financeiros |
| lucy / karen | Reforma / notícias |
| bella / rachel | Rascunhos (WhatsApp produção = Secretaria) |

Pipeline Contmatic (prioridade): **Xavier → Bill → (John opcional) → Excel Contmatic → revisão humana**.

---

## Pastas e dados

```
Agentes Contabeis Escon/
  data/inbox/{cliente}/   # XML, OFX, PDF do período
  data/outbox/{cliente}/  # Excel Contmatic, índices, conciliações
  data/tasks/             # runs dos agentes + solicitações do dashboard
  data/clients/           # cadastro local (espelho; fonte rica = Radar)
  docs/ESCON-CONTEXTO.md  # ESTE arquivo (fonte de verdade narrativa)
```

Dashboard: `python -m escon_agentes dashboard` → http://127.0.0.1:8787

---

## Preferências do Anderson / Escon

- Foco em **resultado operacional** ( Contmatic, prazos, custo do legado ), não em demos sem uso.
- **Humano no loop** em lançamentos e orientações fiscais.
- Não reinventar o que Secretaria e Radar já fazem bem.
- Multi-modelo via OpenRouter; poder trocar Kimi / GPT / Grok / DeepSeek.
- Documentar decisões neste arquivo quando mudarem sistemas ou prioridades.
- Carteira só **Simples + MEI**.

---

## Como agentes (Grok/Claude/Codex) devem usar esta memória

1. Ler **este arquivo** no início de tarefas Escon.  
2. Se existir skill `escon-context`, seguir o SKILL.md.  
3. Complementar com `memory_search` / claude-mem se disponível.  
4. Ao concluir mudança estrutural, **atualizar este arquivo** (não só o chat).  
5. Projetos relacionados: listar paths absolutos Windows do Anderson (OneDrive Desktop Projetos).

---

## Changelog de contexto

| Data | Nota |
|------|------|
| 2026-08-01 | Criação: Oneflow DP/Fiscal, legado R$1100, Contmatic P1, Secretaria WhatsApp, Radar 100 empresas, OpenRouter multi-modelo, dashboard colaboradoras |
| 2026-08-01 | **Import Radar:** 87 empresas (todas `simples` no banco) → `data/clients/` + pastas `data/inbox/{cnpj}`. Comandos: `import-radar`, `sync-inbox`. Fonte VPS `76.13.224.42` / Postgres `radar-escon-db-1`. Docs MinIO espelhados no Drive (27k+). MEI ainda não aparece separado no Radar (só tag simples). |
| 2026-08-01 | **Drive→inbox:** `sync-drive --via drive|minio|auto` (+ `--watch`). Drive Desktop ainda não montado nesta máquina; fallback MinIO = mesma árvore do Drive. |
| 2026-08-01 | **Plano Contmatic unificado:** `config/plano_contas.yaml` + motor `contabilizador_engine.py` (skill Contabilizador). Códigos reais (1121101, 4111201, 1112201…). Pipeline Contmatic usa o motor completo. |
| 2026-08-01 | **Escon_Lancamento absorvido:** modelos em `data/models/` (`PlContas.TXT`, `0001_2026_lctos.xlsx`, PDF). Layout Excel 10 colunas + data `DD.MM.AAAA`. Projeto antigo em `Projetos\Escon_Lancamento` pode ser **excluído** — tudo necessário já está nos Agentes. |
| 2026-08-01 | **Dashboard Vercel:** `index.html` + `/api` (login, chat multiagente OpenRouter, agentes, clientes). Deploy: `docs/DEPLOY-VERCEL.md`. GitHub: `Andersonprocesso/escon-agentes-contabeis`. Ops pesadas (Contmatic/sync) no Python local. |
| 2026-08-01 | **Handoff Obsidian:** `Obsidian Vault/Escon/Handoff - Agentes Contabeis 2026-08-01.md` + `docs/HANDOFF.md` no repo. Usar para retomar com outra IA quando créditos acabarem. |
| 2026-08-01 | **Redesign dashboard Vercel:** tema claro/escuro persistido, navbar/sidebar refeitas, avatares (cliente + equipe), perfil de cliente no painel lateral ao clicar na linha (resumo, contato, ações), ícones SVG próprios. Corrigidos 2 bugs reais: drawer mobile não escondia (ordem de CSS/media query) e tabela de clientes estourava a largura da tela (`.main` sem `min-width:0`). Só `index.html` mudou; `dashboard/static/` e `api/*.js` intocados. |
| 2026-08-01 | **Rachel lê e-mail real:** `contato@escondigital.com.br` é Microsoft 365 (MX Outlook); IMAP bloqueado por Conditional Access/MFA moderno, sem app password disponível. Solução: app registrado no Azure AD (`Escon Raquel Email`, permissões delegadas Mail.Read/Mail.ReadWrite) + login único via device code (MSAL) + Microsoft Graph API (`src/escon_agentes/tools/graph_mail.py`). Comando `raquel-emails`: cruza remetente com `data/clients/*.json` (campo `email` — hoje só 1 de 87 preenchido), cria rascunho de resposta real na caixa (nunca envia), separa anexos por cliente/ano/mês em `data/outbox/email_attachments/` (upload pro Drive ainda manual), e marca/relata e-mails de não-clientes. Token cache em `.msal_cache/` (gitignored). |
| 2026-08-01 | **Agente Fernando Batista — certificados digitais:** lê `credenciais_serpro` do Postgres do Radar via SSH (mesmo padrão de `radar_sync.py`, só metadados — nunca o blob/senha do certificado), cruza com `radar_id` do cadastro local, avisa vencidos + a vencer em 15 dias, gera oferta de renovação (rascunho de mensagem) e tarefa no board — nunca envia direto (Secretaria/WhatsApp faz o envio real). Comando `python -m escon_agentes certificados`. Descoberta na 1ª rodada: 4 certificados já vencidos (Apolo, L C Reinaldo, Ana Gabriela, Rocha e Reinaldo). Dedupe por `radar_id+valido_ate` em `data/outbox/certificados_avisos_state.json`. |
| 2026-08-02 | **Agente Pedro Henrique — cadastro via Acessórias:** API `api.acessorias.com` (Bearer token, 100 req/min, `GET /companies/ListAll` paginado 20/pág, `POST /companies` cria+atualiza, **sem DELETE**). Sync é código puro (zero token): `cadastro-sync` compara em bloco e salva snapshot em `data/acessorias_snapshot.json` (reprocessa com `--cache`). **Campos reais ≠ documentação**: vem `Identificador`/`Razao`/`Regime` como texto (não inteiro 0-10). **113 empresas** no Acessórias vs 87 no local → aplicado: 117 clientes, **112 com e-mail** (era 1!), **19 MEI separados** (resolve gap antigo do Radar). 2 armadilhas tratadas: (a) `anjubiel.anju@gmail.com` está em 111/113 empresas (contato do escritório p/ receber envios) — filtrado via `OFFICE_CONTACT_EMAILS`, senão todo cliente ficaria com o e-mail do Anderson e quebraria a Rachel; (b) `Telefone` do Acessórias é compartilhado (30 números p/ 113 empresas) vs individual no Radar (62) — virou `FILL_ONLY_FIELDS`, nunca sobrescreve, senão quebraria cobrança do Greg no WhatsApp. Política: criar=livre, alterar=confirmação (`--aplicar --confirmar-alteracoes`), excluir=nunca. Radar ainda não recebe escrita (só diff). Falta: ler CNPJ/documentos anexados p/ cadastrar (parte com LLM). |
| 2026-08-02 | **Pedro: cadastro a partir de documentos** (`cadastro-novo <arquivo|pasta>`): lê cartão CNPJ/contrato social e extrai os campos. Regex/rótulo resolve tudo em doc padrão da RFB (13 campos, **0 chamada de LLM**); o modelo só é acionado uma vez, para os campos que sobraram, num único JSON. Sem `--criar` é simulação. **2 bugs achados e corrigidos em teste:** (a) `_unwrap_list` não reconhecia `Identificador`/`Razao` (chaves reais do GET unitário), então a checagem de duplicidade sempre dava 'não existe' e um POST passou num CNPJ existente — sem dano (dados idênticos, verificado: 113 empresas, 0 duplicatas); (b) falha na checagem era *fail-open* → agora é **fail-closed**: sem conseguir confirmar duplicidade, não cadastra. PDF escaneado (imagem) não é suportado — exigiria OCR. |
