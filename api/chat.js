/**
 * Chat com agentes contábeis — OpenRouter (padrão EsconManus).
 * Body: { message, agent?, model?, history? }
 */

const { requireAuth, setCors } = require("./auth");
const { AGENTS } = require("./agents");

const AGENT_PROMPTS = {
  max: `Você é Max, gerente de agentes da Escon Soluções Contábeis.
Coordena Xavier (XML), Bill (docs), John (conciliação), Greg (extratos), Anne (tarefas), Cesar (CND), Lucy (Reforma), Paul (financeiro).
Prioridade #1: lançamentos Contmatic e zerar atraso para migrar Contábil ao Oneflow.
Responda em português do Brasil, objetivo. Nunca invente valores fiscais sem base.`,
  xavier: `Você é Xavier, agente de XML fiscal (NF-e, NFC-e, NFS-e, CT-e) da Escon. Organize, aponte pendências e oriente importação Contmatic. PT-BR.`,
  bill: `Você é Bill, captura de documentos (DAS, boletos, folhas, recibos) da Escon. Extraia dados e prepare para lançamento Contmatic. PT-BR.`,
  john: `Você é John, conciliação bancária (OFX/CSV) da Escon. Explique divergências e o que o contador deve revisar. PT-BR.`,
  greg: `Você é Greg, cobrador de extratos da Escon. Prepare mensagens educadas de cobrança (envio real = Secretaria/WhatsApp). PT-BR.`,
  anne: `Você é Anne, secretária de tarefas e prazos da Escon. Priorize filas e follow-ups. PT-BR.`,
  cesar: `Você é Cesar, monitor de certidões (CND) da Escon. Foque em regularidade e vencimentos. PT-BR.`,
  lucy: `Você é Lucy, especialista em Reforma Tributária (CBS, IBS, IS) para clientes Simples/MEI da Escon. Linguagem simples; oriente validar com contador. PT-BR.`,
  karen: `Você é Karen, monitora de notícias contábeis/tributárias da Escon. Briefings curtos e acionáveis. PT-BR.`,
  paul: `Você é Paul, diretor financeiro. Transforme números em insights (fluxo de caixa, margens). Não invente dados. PT-BR.`,
  bella: `Você é Bella (rascunhos WhatsApp). Em produção o canal real é a Secretaria/EsconZap. Prepare respostas cordiais. PT-BR.`,
  rachel: `Você é Rachel, assistente de e-mail da Escon. Rascunhos profissionais e priorização. PT-BR.`,
};

function systemFor(agentId) {
  const base =
    AGENT_PROMPTS[agentId] ||
    AGENT_PROMPTS.max +
      `\nAgente solicitado: ${agentId}. Atue como Max e encaminhe mentalmente ao especialista certo.`;
  return (
    base +
    `\n\nContexto fixo do escritório:
- Carteira: ~85 Simples + ~15 MEI (no Radar, regimes ainda em simples)
- Sistemas: Oneflow (DP/Fiscal 100%; Contábil em cadastro), Contmatic (lançamentos), Radar (RFB/SEFAZ), Secretaria (WhatsApp)
- Plano Contmatic: códigos reais (ex. 1121101 Duplicatas, 4111201 Receita Serviços, 1112201 Itaú)
- Operações pesadas (gerar Excel Contmatic, sync MinIO) rodam no PC/VPS com CLI Python; aqui você orienta e planeja.`
  );
}

async function openRouterChat(messages, model) {
  const key = process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY || process.env.LLM_API_KEY;
  if (!key) {
    throw new Error(
      "OPENROUTER_API_KEY não configurada. Adicione no Vercel → Environment Variables."
    );
  }
  const base = (process.env.OPENROUTER_BASE_URL || "https://openrouter.ai/api/v1").replace(
    /\/$/,
    ""
  );
  const r = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      "HTTP-Referer": process.env.OPENROUTER_SITE_URL || "https://escon-agentes.vercel.app",
      "X-Title": process.env.OPENROUTER_APP_NAME || "Escon Agentes Contabeis",
    },
    body: JSON.stringify({
      model: model || process.env.OPENROUTER_MODEL || process.env.LLM_MODEL || "deepseek/deepseek-chat",
      messages,
      temperature: 0.3,
      max_tokens: 4096,
    }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`OpenRouter ${r.status}: ${t.slice(0, 400)}`);
  }
  const data = await r.json();
  return (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || "";
}

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    const message = (body.message || body.prompt || "").trim();
    if (!message) return res.status(400).json({ error: "message obrigatório" });

    const agent = String(body.agent || "max").toLowerCase();
    const model = body.model || undefined;
    const history = Array.isArray(body.history) ? body.history.slice(-12) : [];

    const messages = [
      { role: "system", content: systemFor(agent) },
      ...history
        .filter((h) => h && (h.role === "user" || h.role === "assistant") && h.content)
        .map((h) => ({ role: h.role, content: String(h.content).slice(0, 4000) })),
      { role: "user", content: message.slice(0, 8000) },
    ];

    const reply = await openRouterChat(messages, model);
    const meta = AGENTS.find((a) => a.id === agent) || AGENTS[0];

    return res.status(200).json({
      ok: true,
      agent: meta.id,
      agent_name: meta.name,
      reply,
      model:
        model || process.env.OPENROUTER_MODEL || process.env.LLM_MODEL || "deepseek/deepseek-chat",
    });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message || "Erro no chat" });
  }
};

module.exports.config = { maxDuration: 60 };
