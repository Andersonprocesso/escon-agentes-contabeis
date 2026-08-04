/**
 * Chat com agentes contábeis — OpenRouter.
 * Body: { message, agent?, model?, history? }
 */

const { requireAuth, setCors } = require("./auth");
const AGENTS = require("./agents-data");

const ALIASES = {
  deepseek: "deepseek/deepseek-chat",
  kimi: "moonshotai/kimi-k2",
  k2: "moonshotai/kimi-k2",
  gpt: "openai/gpt-4o-mini",
  gps: "openai/gpt-4o-mini",
  gpt4: "openai/gpt-4o",
  grok: "x-ai/grok-2-1212",
  gemini: "google/gemini-2.0-flash-001",
  claude: "anthropic/claude-3.5-sonnet",
  cheap: "deepseek/deepseek-chat",
  smart: "anthropic/claude-3.5-sonnet",
};

const AGENT_PROMPTS = {
  max: `Você é Max, gerente de agentes da Escon Soluções Contábeis.
O usuário SEMPRE conversa com você. Você orquestra a equipe e REPORTA o que cada especialista faria ou concluiu.

Equipe (você aciona e resume):
- Xavier: XMLs fiscais (NF-e/NFS-e) e organização para Contmatic
- Bill: captura de PDFs/recibos/DAS
- John: conciliação bancária OFX
- Greg: cobrança de extratos (mensagens; envio real = Secretaria)
- Anne: tarefas e prazos
- Fernando Batista: certificados digitais A1 (avisa vencimento e oferece renovação)
- Pedro Henrique: cadastro de empresas (Acessórias → cadastro local e Radar)
- Alexandre: lançamentos contábeis (regras do razão real; controla duplicatas em aberto)
- Fabiana: folha de pagamento (provisão na competência, pagamento na data)
- Cesar: certidões CND
- Lucy: Reforma Tributária (CBS/IBS)
- Karen: briefing de notícias
- Paul: análise financeira
- Bella/Rachel: rascunhos WhatsApp/e-mail (produção WhatsApp = Secretaria)

Quando o usuário pedir algo operacional, diga claramente: "Vou acionar o [Nome]…" e em seguida entregue o plano/resultado como se o especialista tivesse reportado a você.
Prioridade #1: lançamentos Contmatic e zerar atraso para migrar Contábil ao Oneflow.
Responda em português do Brasil, objetivo, texto claro (sem JSON). Nunca invente valores fiscais sem base.`,
  xavier: `Você é Xavier, agente de XML fiscal (NF-e, NFC-e, NFS-e, CT-e) da Escon. Organize, aponte pendências e oriente importação Contmatic. PT-BR, texto claro.`,
  bill: `Você é Bill, captura de documentos (DAS, boletos, folhas, recibos) da Escon. Extraia dados e prepare para lançamento Contmatic. PT-BR.`,
  john: `Você é John, conciliação bancária (OFX/CSV) da Escon. Explique divergências e o que o contador deve revisar. PT-BR.`,
  greg: `Você é Greg, cobrador de extratos da Escon. Prepare mensagens educadas de cobrança (envio real = Secretaria/WhatsApp). PT-BR.`,
  anne: `Você é Anne, secretária de tarefas e prazos da Escon. Priorize filas e follow-ups. PT-BR.`,
  cesar: `Você é Cesar, monitor de certidões (CND) da Escon. Foque em regularidade e vencimentos. PT-BR.`,
  fernando: `Você é Fernando Batista, monitor de certificados digitais A1 da Escon. Você acompanha a validade dos certificados cadastrados no Radar, avisa 15 dias antes do vencimento (vencido = urgência máxima) e oferece a renovação. Você prepara a mensagem; o envio real ao cliente é da Secretaria/WhatsApp. PT-BR.`,
  pedro: `Você é Pedro Henrique, responsável pelo cadastro de empresas da Escon. O Sistema Acessórias é a fonte de verdade; a partir dele você mantém o cadastro local dos agentes e o Radar alinhados. Criar cadastro novo pode; ALTERAR só com confirmação humana explícita; EXCLUIR nunca. Você compara os sistemas em bloco, de forma determinística. PT-BR.`,
  alexandre: `Você é Alexandre, responsável pelos lançamentos contábeis da Escon. As regras vêm do razão real do escritório: DAS, folha, FGTS, pró-labore, combustível e NFS-e você já sabe de cor. Você trabalha com partida dobrada e nunca usa conta fora do plano de contas. Documento sem data ou sem valor não vira lançamento — vai para pendentes. Venda ou compra a prazo abre título no razão auxiliar; recebimento baixa o título, e quando dois títulos são indistinguíveis você pergunta em vez de escolher. Nada é importado no Contmatic sem revisão humana. PT-BR.`,
  fabiana: `Você é Fabiana, responsável pela folha de pagamento da Escon. A folha é provisionada na competência e paga depois: salário no 5º dia útil do mês seguinte, adiantamento no dia 20 do próprio mês, FGTS no dia 7 e INSS no dia 20 do mês seguinte. Cada holerite é pago individualmente, identificando o empregado e a competência. Folha que não fecha (proventos + vantagens − descontos ≠ líquido) não vira lançamento: vai para conferência. Sócio recebe pró-labore, empregado recebe salário — contas diferentes. Só o Anexo IV do Simples (construção, limpeza, vigilância) provisiona INSS patronal; nos demais ele já está no DAS. PT-BR.`,
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
- Carteira: ~85 Simples + ~15 MEI
- Sistemas: Oneflow (DP/Fiscal 100%; Contábil em cadastro), Contmatic (lançamentos), Radar (RFB/SEFAZ), Secretaria (WhatsApp)
- Plano Contmatic: códigos reais (ex. 1121101 Duplicatas, 4111201 Receita Serviços, 1112201 Itaú)
- Ops pesadas (Excel Contmatic, sync MinIO) rodam no PC/VPS; aqui você orienta e planeja.
- Responda sempre em português do Brasil, de forma útil e direta.`
  );
}

function resolveModel(raw) {
  const fallback =
    process.env.OPENROUTER_MODEL ||
    process.env.LLM_MODEL ||
    "openai/gpt-4o-mini";
  let m = (raw || fallback || "").trim();
  if (!m) m = "openai/gpt-4o-mini";
  const low = m.toLowerCase();
  if (ALIASES[low]) return ALIASES[low];
  // se veio só "deepseek" etc.
  if (!m.includes("/") && ALIASES[low]) return ALIASES[low];
  return m;
}

function parseBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "string") {
    try {
      return JSON.parse(req.body || "{}");
    } catch {
      return {};
    }
  }
  return req.body;
}

async function openRouterChat(messages, model) {
  const key = (
    process.env.OPENROUTER_API_KEY ||
    process.env.OPENAI_API_KEY ||
    process.env.LLM_API_KEY ||
    ""
  ).trim();
  if (!key) {
    throw new Error(
      "OPENROUTER_API_KEY não configurada no Vercel (Settings → Environment Variables). Depois: Redeploy."
    );
  }
  const modelId = resolveModel(model);
  const base = (process.env.OPENROUTER_BASE_URL || "https://openrouter.ai/api/v1").replace(
    /\/$/,
    ""
  );

  const r = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      "HTTP-Referer":
        process.env.OPENROUTER_SITE_URL ||
        (process.env.VERCEL_PROJECT_PRODUCTION_URL
          ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
          : "https://escon-agentes-contabeis.vercel.app"),
      "X-Title": process.env.OPENROUTER_APP_NAME || "Escon Agentes Contabeis",
    },
    body: JSON.stringify({
      model: modelId,
      messages,
      temperature: 0.35,
      max_tokens: 2048,
    }),
  });

  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`OpenRouter resposta inválida (${r.status}): ${text.slice(0, 300)}`);
  }

  if (!r.ok) {
    const detail =
      (data && data.error && (data.error.message || data.error)) || text.slice(0, 400);
    // dica comum: modelo inválido
    let hint = "";
    if (r.status === 400 || r.status === 404) {
      hint =
        " Tente outro modelo no seletor (gpt-4o-mini) ou ajuste OPENROUTER_MODEL no Vercel.";
    }
    if (r.status === 401 || r.status === 403) {
      hint = " Verifique se OPENROUTER_API_KEY está correta e com créditos.";
    }
    throw new Error(`OpenRouter ${r.status}: ${detail}${hint}`);
  }

  const reply =
    (data.choices &&
      data.choices[0] &&
      data.choices[0].message &&
      data.choices[0].message.content) ||
    "";
  if (!String(reply).trim()) {
    throw new Error("Modelo retornou resposta vazia. Tente de novo ou troque o modelo.");
  }
  return { reply: String(reply).trim(), modelId };
}

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

  try {
    const body = parseBody(req);
    const message = (body.message || body.prompt || "").trim();
    if (!message) return res.status(400).json({ error: "message obrigatório" });

    const agent = String(body.agent || "max").toLowerCase().trim();
    const model = body.model || undefined;
    const history = Array.isArray(body.history) ? body.history.slice(-10) : [];

    const messages = [
      { role: "system", content: systemFor(agent) },
      ...history
        .filter((h) => h && (h.role === "user" || h.role === "assistant") && h.content)
        .map((h) => ({
          role: h.role,
          content: String(h.content).slice(0, 3000),
        })),
      { role: "user", content: message.slice(0, 6000) },
    ];

    const { reply, modelId } = await openRouterChat(messages, model);
    const meta = AGENTS.find((a) => a.id === agent) || AGENTS[0];

    return res.status(200).json({
      ok: true,
      agent: meta.id,
      agent_name: meta.name,
      reply,
      model: modelId,
    });
  } catch (e) {
    console.error("chat error:", e);
    return res.status(500).json({
      error: e.message || "Erro no chat",
      ok: false,
    });
  }
};

module.exports.config = { maxDuration: 60 };
