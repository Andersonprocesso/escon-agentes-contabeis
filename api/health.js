/** Health sem auth — diagnóstico rápido do deploy. */
const { setCors, isAuthConfigured } = require("./auth");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  const hasOr = Boolean(
    (process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY || "").trim()
  );
  return res.status(200).json({
    ok: true,
    service: "escon-agentes-contabeis",
    auth_configured: isAuthConfigured(),
    openrouter_configured: hasOr,
    model: process.env.OPENROUTER_MODEL || process.env.LLM_MODEL || "openai/gpt-4o-mini",
    time: new Date().toISOString(),
  });
};

module.exports.config = { maxDuration: 5 };
