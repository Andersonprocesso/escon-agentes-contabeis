# Análise do ebook QYON × Escon Soluções Contábeis

**Fonte:** `ebook-agentes-qyon0726.pdf` (agentes.qyon.com)  
**Escritório:** Escon Soluções Contábeis  
**Data da análise:** 2026-08-01

---

## O que o ebook propõe

O material da QYON descreve a **era dos agentes de IA**: não só chatbots que respondem, mas sistemas que **entendem um objetivo, planejam etapas, usam ferramentas e executam** fluxos da rotina contábil.

Mensagem central (relevante para a Escon):

- Menos digitação e retrabalho
- Mais interpretação, consultoria e relacionamento
- **Sempre com governança e revisão humana** em etapas críticas

### 5 frentes de ganho

| Frente | Aplicação no escritório |
|--------|-------------------------|
| Produtividade | Volume de NF-e, extratos, e-mails e cobranças |
| Precisão | Conciliação, cruzamento XML × banco × lançamentos |
| Escala | Atender mais clientes sem crescer a equipe na mesma proporção |
| Decisão | DRE, fluxo de caixa, alertas fiscais |
| Tempo estratégico | Contador foca em orientação, não em copiar/colar |

---

## Os 14 agentes do ebook → mapeamento Escon

| Agente QYON | Função | Prioridade Escon | Status neste sistema |
|-------------|--------|------------------|----------------------|
| **Bella** | Atendimento WhatsApp | Alta (já há EsconZap/CRM) | Implementado (rascunhos + fila) |
| **Rachel** | Organização de e-mails | Alta | Implementado (classificação + rascunhos) |
| **Greg** | Cobrança de extratos | Crítica (mensal) | Implementado (lista pendentes + mensagens) |
| **John** | Conciliação bancária | Crítica | Implementado (OFX × lançamentos) |
| **Bill** | Captura de documentos/recibos | Crítica | Implementado (PDF/texto → dados) |
| **Anne** | Tarefas, prazos, follow-ups | Alta | Implementado (quadro de tarefas) |
| **Lucy** | Reforma Tributária (CBS/IBS/IS) | Alta (contexto 2026+) | Implementado (knowledge + explicações) |
| **Karen** | Notícias e mudanças legais | Média | Implementado (briefing a partir de fontes) |
| **Max** | Gerente de agentes/processos | Crítica (orquestrador) | Implementado (roteamento + status) |
| **Neo** | Multifunções genéricas | Baixa p/ contábil | Fora do escopo operacional |
| **Alex** | Tutor de idiomas | Irrelevante | Fora do escopo |
| **Paul** | Diretor financeiro / indicadores | Alta (BPO/consultivo) | Implementado (análises e relatórios) |
| **Cesar** | Certidões (CND) + e-CAC | Alta | Implementado (cadastro + alertas; portal = integração futura) |
| **Xavier** | XMLs fiscais (NF-e, NFC-e, CT-e, NFS-e) | Crítica | Implementado (parse, organização, pendências) |

---

## Viabilidade: **sim, dá para fazer**

Você já tem peças que o ebook imagina “do zero”:

| Ativo Escon | Como encaixa |
|-------------|--------------|
| `escon-contabil` | Cadastro de empresas, usuários, pipeline (UX Omie) |
| EsconZap / CRM WhatsApp | Canal da Bella |
| Skill Contabilizador | Lançamentos Contmatic a partir de XML/OFX/PDF (Bill + Xavier + John) |
| EsconManus / OpenManus | Experiência com agentes genéricos |
| Radar Escon | Monitoramento operacional |
| Reforma Tributária (projeto) | Base de conhecimento da Lucy |

O sistema em `Agentes Contabeis Escon` **não substitui** o Contmatic/domínio fiscal sozinho: ele **orquestra agentes** que preparam, classificam, cobram, alertam e geram artefatos para a equipe revisar e importar.

---

## Arquitetura recomendada (implementada)

```
                    ┌─────────────┐
   humano / CLI ──► │    MAX      │  orquestrador + status
                    │  (gerente)  │
                    └──────┬──────┘
           ┌───────────────┼────────────────┐
           ▼               ▼                ▼
      Xavier/Bill      Greg/John/Cesar   Bella/Rachel
      (documentos)     (financeiro)      (comunicação)
           │               │                │
           └───────────────┼────────────────┘
                           ▼
                    Anne · Lucy · Karen · Paul
                           │
                           ▼
              data/inbox → tools → data/outbox
              (revisão humana antes de importar)
```

### Princípios de governança

1. **Agente prepara; contador aprova** — lançamentos, DAS, certidões e respostas sensíveis.
2. **Trilha de auditoria** — cada ação vira log em `data/tasks` e `outbox`.
3. **Integrações graduais** — primeiro pastas + arquivos; depois WhatsApp, e-mail, e-CAC, ERP.
4. **Um agente por domínio** — prompts e tools isolados (mais fácil auditar e treinar).

---

## O que NÃO está no MVP (e por quê)

| Item | Motivo |
|------|--------|
| Login automático e-CAC / SEFAZ | Credenciais + 2FA + risco jurídico; exige RPA dedicado e procuração |
| Envio real WhatsApp/e-mail sem API | Precisa de provedor (Evolution, Meta, Microsoft Graph) |
| Lançamento direto no Contmatic | Preferível export Excel (já é o fluxo do Contabilizador) |
| Decisão fiscal autônoma | Responsabilidade técnica do CRC; IA só apoia |

---

## Roadmap sugerido

### Fase 1 — Operação em pasta (agora)
- Xavier, Bill, John, Greg, Anne, Max rodando localmente
- Inbox de XMLs/OFX/PDFs por cliente/mês
- Export Contmatic + quadro de tarefas

### Fase 2 — Comunicação
- Bella ↔ EsconZap
- Rachel ↔ caixa do escritório (Graph/IMAP)
- Greg cobrando extratos pelo canal real

### Fase 3 — Fiscal & consultivo
- Cesar + alertas de CND
- Lucy com base da Reforma atualizada
- Paul conectado a extratos e indicadores do cliente

### Fase 4 — Integração escon-contabil
- Max como backend de “fila de agentes”
- Dashboard de processos no web app

---

## Conclusão

O ebook da QYON é um **catálogo de casos de uso**, não um produto fechado. A Escon **consegue** ter o equivalente — e em vários pontos já está adiantada (Contabilizador, WhatsApp, escon-contabil).

Este repositório materializa o **sistema multiagente do escritório**, com Max no centro e agentes especializados na rotina contábil brasileira (Simples, documentos, XML, conciliação, prazos).
