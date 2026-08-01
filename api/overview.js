const { requireAuth, setCors } = require("./auth");
const AGENTS = require("./agents-data");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

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

  const hasKey = Boolean(
    (process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY || "").trim()
  );

  return res.status(200).json({
    office: "Escon Soluções Contábeis",
    priority: "Lançamentos Contmatic (zerar atraso → migrar Contábil 100% Oneflow)",
    agents_total: AGENTS.length,
    clients: clientsCount,
    regimes: "Simples Nacional + MEI",
    llm: hasKey ? "openrouter" : "offline",
    model:
      process.env.OPENROUTER_MODEL ||
      process.env.LLM_MODEL ||
      "openai/gpt-4o-mini",
    chat_ready: hasKey,
    backend_note: hasKey
      ? "Chat online (OpenRouter). Contmatic/sync Radar: CLI Python no PC."
      : "Chat offline: falta OPENROUTER_API_KEY no Vercel → Settings → Environment Variables → Redeploy.",
  });
};

module.exports.config = { maxDuration: 10 };
