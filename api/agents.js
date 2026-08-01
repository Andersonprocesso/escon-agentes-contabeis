const { requireAuth, setCors } = require("./auth");
const AGENTS = require("./agents-data");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });
  return res.status(200).json({ agents: AGENTS, total: AGENTS.length });
};

module.exports.config = { maxDuration: 10 };
