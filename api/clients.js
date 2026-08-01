const fs = require("fs");
const path = require("path");
const { requireAuth, setCors } = require("./auth");

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

  const snap = path.join(process.cwd(), "data", "web", "clients_snapshot.json");
  try {
    if (fs.existsSync(snap)) {
      const data = JSON.parse(fs.readFileSync(snap, "utf8"));
      const list = Array.isArray(data) ? data : data.clients || [];
      return res.status(200).json({ total: list.length, clients: list });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
  return res.status(200).json({
    total: 0,
    clients: [],
    note: "Gere o snapshot: python scripts/export_clients_snapshot.py",
  });
};

module.exports.config = { maxDuration: 10 };
