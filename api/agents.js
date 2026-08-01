const { requireAuth, setCors } = require("./auth");

const AGENTS = [
  { id: "max", name: "Max", role: "Gerente de Agentes e Processos", color: "#3b9eff" },
  { id: "xavier", name: "Xavier", role: "XMLs fiscais", color: "#34d399" },
  { id: "bill", name: "Bill", role: "Captura de documentos", color: "#a78bfa" },
  { id: "john", name: "John", role: "Conciliação bancária", color: "#fbbf24" },
  { id: "greg", name: "Greg", role: "Cobrança de extratos", color: "#f87171" },
  { id: "anne", name: "Anne", role: "Tarefas e prazos", color: "#38bdf8" },
  { id: "cesar", name: "Cesar", role: "Certidões (CND)", color: "#fb923c" },
  { id: "lucy", name: "Lucy", role: "Reforma Tributária", color: "#c084fc" },
  { id: "karen", name: "Karen", role: "Notícias e briefing", color: "#2dd4bf" },
  { id: "paul", name: "Paul", role: "Diretor financeiro", color: "#60a5fa" },
  { id: "bella", name: "Bella", role: "WhatsApp (rascunhos; produção = Secretaria)", color: "#4ade80" },
  { id: "rachel", name: "Rachel", role: "E-mails", color: "#e879f9" },
];

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });
  return res.status(200).json({ agents: AGENTS, total: AGENTS.length });
};

module.exports.config = { maxDuration: 10 };
module.exports.AGENTS = AGENTS;
