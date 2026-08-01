const { validateCredentials, setCors, isAuthConfigured } = require("./auth");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  if (!isAuthConfigured()) {
    return res.status(503).json({
      error:
        "Autenticação não configurada. No Vercel: Settings → Environment Variables → ADMIN_PASSWORD (e opcionalmente ADMIN_USER).",
    });
  }
  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    const result = validateCredentials(body.username, body.password);
    if (!result.ok) {
      return res.status(result.status).json({ error: result.error });
    }
    return res.status(200).json({
      token: result.token,
      expiresInMs: result.expiresInMs,
      user: result.user,
    });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message || "Erro interno" });
  }
};

module.exports.config = { maxDuration: 10 };
