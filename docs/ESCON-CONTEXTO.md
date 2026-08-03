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
| 2026-08-02 | **Rachel × Pedro (efeito em cadeia) + convenção do Drive:** `raquel-recheck` reavalia e-mails marcados como 'não-cliente' depois que o cadastro muda — necessário porque a classificação depende do cadastro (e-mail lido com cadastro vazio vira não-cliente por engano). Achou o caso real: nota fiscal da Nascimento de Araujo (klinger@klctur.com.br) estava parada como pendência genérica; reprocessada → rascunho criado, estrela removida, 2 PDFs baixados. **Convenção real do Drive descoberta** (`Radar/backend/app/services/storage.py`): `{Empresa}/{Departamento}/{Ano}/{MM-AAAA}/` — tem nível de **departamento** (Impostos, Notas Fiscais-Entrada/Saida/Servico, Extratos, eSocial, e-CAC, Recibos, Comprovantes, Situação Fiscal) e mês é `07-2026`, não `07-Julho`. Corrigido. Novo `departamento_drive.py` classifica por **conteúdo, nunca pelo nome**: o arquivo 'NotaFiscal … - JUREMA ÁGUA QUENTE.pdf' parecia entrada, mas o emitente é o próprio cliente → é `Notas Fiscais-Servico` (saída). Também filtra `image001.png` (assinatura de e-mail). **Pendente:** upload ao Drive — ver nota seguinte sobre reusar o pipeline do Radar. |
| 2026-08-02 | **Ponte Rachel → Radar → Drive** (`anexos-para-drive`): em vez de subir ao Drive por fora, o anexo é entregue ao pipeline do Radar chamando a **própria função dele** (`salvar_documento` dentro do container `radar-escon-api-1` via SSH) — herda sha256, storage_key determinístico, upsert idempotente e o worker `drive.espelhar_todos` (de hora em hora, min 20) leva ao Drive com lock anti-duplicata. Custo zero de token (roda no servidor). Departamento vira `tipo` do Radar (Notas Fiscais-Servico→`nfse_xml` etc.); nada no Radar faz parse por tipo, então PDF com tipo `*_xml` é seguro — verificado. Testado E2E: 2 NFS-e da Nascimento de Araujo → MinIO → Drive (`drive_file_id` preenchido, 32.047 bytes íntegros). Não classificado = fica parado para humano, nunca chuta pasta. Aprendizados de infra: binário vai por **stdin do ssh** (embutir no comando estoura o limite ~32 KB do Windows) e o script precisa de `sys.path.insert(0,'/code')`. Também: `cli.py` força stdout UTF-8 (cp1252 derrubava comandos ao imprimir '→'/'⏸'). **Lição:** não criar pastas no Drive na mão — o Radar cria a árvore dele e as minhas viraram duplicatas vazias. |
| 2026-08-03 | **Pedro fecha o lado Radar** (`cadastro-radar`): `build_radar_plan` era código morto (nunca chamado) — agora tem comando com diff. Cria empresas faltantes reusando o schema `EmpresaCreate` do Radar (herda validação de dígito verificador do CNPJ e defaults de `config_radar`/`monitoramento_ativo`); **alterações nunca são aplicadas**, só reportadas. **Bug corrigido:** o Radar usa vocabulário curto de regime (`simples`) e o cadastro local o longo (`simples_nacional`) — a comparação textual marcava **83 de 87 empresas como divergentes** e proporia sobrescrever o Radar à toa; com `regime_para_radar()` caiu para 4 divergências reais. Aplicado: **30 empresas criadas no Radar** → `import-radar` → **117 clientes, todos com radar_id (era 30 sem)**. Isso destrava o `anexos-para-drive`, que exige radar_id. Divergências reais que sobraram (não tocadas): 2 MEIs que o Radar tem como `simples`, 1 UF (SP vs MG), 1 razão social. Infra: payload grande vai por arquivo/stdin — embutir no script estoura o limite de linha de comando do Windows. |
| 2026-08-03 | **Correções pós-uso (Anderson conferiu):** (1) **Pedro importava empresa baixada** — `normalize_company` já extraía `ativa` (Status do Acessórias), mas os planos ignoravam; 8 inativas entraram no cadastro e no Radar (ex.: Margarete Vilma, baixada em 06/10/2025). Corrigido: `build_local_plan`/`build_radar_plan` pulam `Status != Ativa` e reportam em `inativas`. Cadastro local: 117 → **109**. (2) **Dashboard mostrava 87** — o snapshot `data/web/clients_snapshot.json` nunca foi reexportado após o sync; agora 109. `scripts/export_clients_snapshot.py` também ganhou o fix de UTF-8. (3) **Pedro e Fernando faltavam no dashboard Vercel** (`api/agents-data.js` + persona em `api/chat.js` + equipe no prompt do Max). (4) **Rachel não é automática** — só roda por comando; não há agendamento. Ela cria rascunho **apenas para cliente cadastrado**; remetente desconhecido é marcado/reportado. (5) **Abas Destaques/Outros do Outlook não são problema** — o Graph lê a Inbox inteira (verificado: `inferenceClassification` 11 focused / 0 other). O que existe são ~40 pastas com regras movendo e-mail para fora da Inbox (Importante 1572, Certificados 1053, IRPF 617…) — Rachel hoje só lê a Caixa de Entrada. |
| 2026-08-03 | **Raquel automática + regras treináveis:** `config/regras_email.yaml` (editável pelo Anderson, comparação literal — sem LLM, sem token). Ações: `lixeira` (move para Itens Excluídos, **reversível** — nunca exclusão definitiva), `arquivar: Pasta`, `ignorar`. **Cliente cadastrado nunca é tocado por regra** — sempre rascunho + anexo. `--reaplicar-regras` reavalia e-mails já vistos quando uma regra nova é criada (não refaz rascunho de cliente, evitando duplicata). Agendamento: `scripts/raquel.bat` (log em `data/logs/raquel.log`); a tarefa do Windows deve ser criada pelo próprio Anderson. `get_access_token` na triagem passou a usar `interactive_ok=False` — rodando pelo agendador não há quem digite o código, então falha rápido em vez de travar. Testado: 3 e-mails tratados por regra, confirmados na Lixeira e fora da Caixa de Entrada. |
| 2026-08-03 | **Raquel agendada — 3 armadilhas do Agendador do Windows** (custaram várias tentativas, ficam registradas): (1) `schtasks /tr` com aspas simples no PowerShell **quebra o caminho no espaço** ('...\Agentes' virou o executável e 'Contabeis Escon\...' virou argumento) — usar `New-ScheduledTaskAction`/`Register-ScheduledTask`, que não sofre com aspas; (2) `.bat` criado por heredoc do bash sai com **LF misturado e acentos UTF-8**, que o `cmd.exe` não digere — reescrito em ASCII puro com CRLF e **caminhos absolutos** (inclusive o do `python.exe`), sem depender de PATH nem de diretório de trabalho; (3) **`DisallowStartIfOnBatteries` é `True` por padrão** — no notebook na bateria o Windows pula a tarefa e ainda reporta `LastTaskResult = 0`, dando falsa impressão de sucesso. Corrigido com `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable`. Confirmado funcionando: tarefa executa de hora em hora e grava em `data/logs/raquel.log`. |
| 2026-08-03 | **Raquel estava na CAIXA ERRADA (erro grave) + 2 problemas de dados no cadastro:** (1) o login por device code foi feito como `anderson@escondigital.com.br` e o código usa `/me` — então rascunhos, marcações e movimentações aconteceram na **caixa pessoal**, não em `contato@`. Causa: ao tomar 403 em `/users/{mailbox}` eu troquei para `/me` sem validar identidade. Corrigido com `conferir_caixa()`, que **aborta** se o UPN do token ≠ `MS_GRAPH_MAILBOX` (divergência é falha, nunca aviso). Para trocar: apagar `.msal_cache/` e logar como `contato@`. (2) **3 clientes cadastrados com e-mail do próprio escritório** (inclusive a Escon como cliente dela mesma, e Margarida com `contato@`) — por isso notificações internas de quarentena (`Junk:`) viraram rascunho. (3) **11 e-mails pertencem a mais de uma empresa** (ex.: `anapaula.rangel1@outlook.com` em 5) — arquivar no palpite mandaria nota fiscal para a pasta da empresa errada. Ambos tratados em `indice_por_email()`: e-mail do domínio do escritório nunca identifica cliente, e e-mail ambíguo vira pendência explícita para o humano dizer de qual empresa é. Efeito: 74 e-mails identificam cliente com segurança, 11 bloqueados. |
| 2026-08-03 | **Agente Alexandre (lançamentos) + razão destrinchado:** `razao_parser.py` lê o Razão Analítico em PDF por **posição de coluna** (só o texto não diz se o valor é débito ou crédito) e extraiu **2.090 lançamentos reais** (2020+2022, 68 contas nomeadas). Deles saiu `config/regras_lancamento.yaml` (25 regras): DAS, folha, FGTS, pró-labore, combustível, energia, NFS-e etc. já vêm com débito/crédito/histórico prontos — **zero token no caso do dia a dia**. LLM só no que nenhuma regra reconhece, 1 chamada por documento, e a resposta é **descartada se citar conta fora do plano**. Data e valor nunca vêm do modelo. **Divisão de trabalho definida:** Xavier lê XML, John lê OFX e concilia (não lança), Bill lê PDF — só o Alexandre contabiliza, consumindo o que eles estruturam (sem duplicar parser). **ACHADO GRAVE:** `config/plano_contas.yaml` tem contas erradas — manda Simples Nacional para *IPI a recolher* (2131101) e pró-labore para *FGTS a recolher* (2141202); os códigos corretos são 2131115 e 2141102. As despesas (4121301/4121101/4121401/4121501) sequer existem; as reais são 3221101/3212102/3221107/4121205. `PlContas.TXT` só tem Ativo/Passivo — nenhuma conta de resultado. Razões copiados para `data/models/`. Plano de execução: Obsidian `Escon/Plano - Agentes Lancamentos Contabeis`. |
| 2026-08-03 | **Plano de contas corrigido — e correção de um erro meu:** eu havia concluído que `PlContas.TXT` estava truncado (só Ativo/Passivo). **Estava errado**: o arquivo sempre teve as contas de resultado; o `plcontas_parser.py` é que as descartava em silêncio, porque contas 3xxx/4xxx trazem uma **letra colada na reduzida** (`3111201C`, `4111101A`) e o regex exigia espaço. Corrigido: o índice passou de 266 → **477 contas**, com **cobertura total** das 68 usadas no razão. Com o plano completo, a auditoria do `config/plano_contas.yaml` confirmou o problema grave e maior do que eu havia dito: **22 de 37 contas erradas** — `simples_nacional` caía em *IPI a recolher*, `desp_salarios` em *IPI*, `prolabore_pagar` em *FGTS a recolher*, e 17 simplesmente não existiam. Todas corrigidas contra o uso real do razão; hoje **0 contas inexistentes**. `PlContas.TXT` substituído pela exportação nova (477 contas). Token da API Contmatic guardado no `.env`: `api.contmatic.com.br` responde, mas os endpoints do plano de contas ainda não foram descobertos (404 nos palpites) — falta a documentação. |
| 2026-08-03 | **API Contmatic Phoenix conectada** (`contmatic_api.py`): base `https://api.contmatic.com.br/public`, auth `Authorization: Bearer <token>` (token puro dá 401, apesar da doc dizer `apiKey`). Autentica como ESCON SOLUCOES CONTABEIS e lista **124 empresas** com `apelido` (Escon = `0001`, Nascimento de Araujo = `0088`) — o apelido é a chave dos demais serviços. **Liberado:** `/v1/clientes/self`, `/v1/empresas`, `/v1/usuarios`, `/v1/metadatas`, `/v1/cargos`, `/v1/horarios`. **Bloqueado:** `/v1/planocontas/{apelido}/{ano}` e `/v1/lancamentos/{apelido}/{ano}` — o Contmatic responde 422 *"O sistema ACESSORIA não pode usar este serviço"*: o token é do produto Acessórias, e esses dois pertencem ao Contábil. Para o Alexandre puxar o plano por empresa (hoje é um arquivo fixo, igual para todos) e enviar lançamento direto, é preciso um token emitido para o **Contábil**. `montar_lancamento()` já monta o corpo do POST, mas não envia — gravação em produção exige aprovação humana. |
| 2026-08-03 | **Fechamento por competência no painel local** (`workflows/fechamento.py` + tela no `dashboard/static/`): para zerar contabilidade atrasada. Escolhe cliente + competência (aceita `jan/21`, `01/2021`, `2021-01`), aponta **pasta do PC**, **pasta do OneDrive** e/ou **Drive via Radar**; roda o Alexandre e mostra o andamento etapa por etapa; no fim dá para **conferir e baixar a planilha** do Contmatic. Cada competência tem pasta própria (`data/inbox/{cliente}/{AAAA-MM}/`) para jan/21 não se misturar com fev/21, e o Excel sai nomeado por competência. Endpoints: `POST /api/pastas/inspecionar` (confere antes de rodar), `POST/GET /api/fechamentos`, `GET /api/fechamentos/{cliente}/{comp}/planilha`. **Precisa ser o painel local** — o do Vercel não lê pasta do PC. Testado E2E: 2 documentos → 3 lançamentos por regra, 0 LLM, planilha de 5.835 bytes baixada. Achado: com `from __future__ import annotations`, modelo Pydantic declarado **dentro** de `create_app()` faz o FastAPI tratar o corpo como query param (422) — precisa ficar no nível do módulo. **OneDrive:** código pronto, mas exige adicionar `Files.Read.All` ao app do Azure (o login atual só tem Mail.Read/ReadWrite) e refazer o login. |
