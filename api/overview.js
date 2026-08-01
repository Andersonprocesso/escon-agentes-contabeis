const { requireAuth, setCors } = require("./auth");
const { AGENTS } = require("./agents");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

  // Snapshot leve para Vercel (ops pesadas = API Python local/VPS)
  let clientsCount = 87;
  try {
    const fs = require("fs");
    const path = require("path");
    const snap = path.join(process.cwd(), "data", "web", "clients_snapshot.json");
    if (fs.existsSync(snap)) {
      const data = JSON.parse(fs.readFileSync(snap, "utf8"));
      clientsCount = Array.isArray(data) ? data.length : data.total || clientsCount;
    }
  } catch (_) {
    /* ignore */
  }

  return res.status(200).json({
    office: "Escon Soluções Contábeis",
    priority: "Lançamentos Contmatic (zerar atraso → migrar Contábil 100% Oneflow)",
    agents_total: AGENTS.length,
    clients: clientsCount,
    regimes: "Simples Nacional + MEI",
    llm: process.env.OPENROUTER_API_KEY ? "openrouter" : "offline",
    model: process.env.OPENROUTER_MODEL || process.env.LLM_MODEL || "deepseek/deepseek-chat",
    backend_note:
      "Chat e visão geral no Vercel. Contmatic/sync Radar rodam na API Python local (python -m escon_agentes dashboard) ou VPS.",
    features: [
      "Chat multiagente (OpenRouter)",
      "Visão de agentes e papéis",
      "Solicitar serviços (via chat)",
      "Carteira de clientes (snapshot)",
    ],
  });
};

module.exports.config = { maxDuration: 10 };
