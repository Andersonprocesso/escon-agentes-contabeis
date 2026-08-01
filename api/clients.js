/**
 * Clientes — GET lista; POST cria; PATCH edita; DELETE remove.
 * Persistência:
 *  - Local / VPS: data/web/clients_live.json (merge sobre snapshot)
 *  - Vercel serverless: /tmp/clients_live.json (pode resetar em cold start)
 * Para cadastro definitivo no PC: python dashboard ou editar data/clients/*.json
 */

const fs = require("fs");
const path = require("path");
const { requireAuth, setCors } = require("./auth");

function livePath() {
  if (process.env.VERCEL) return "/tmp/escon_clients_live.json";
  return path.join(process.cwd(), "data", "web", "clients_live.json");
}

function snapshotPath() {
  return path.join(process.cwd(), "data", "web", "clients_snapshot.json");
}

function loadJson(p, fallback) {
  try {
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (_) {}
  return fallback;
}

function saveLive(list) {
  const p = livePath();
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(
      p,
      JSON.stringify({ total: list.length, clients: list, updated_at: new Date().toISOString() }, null, 2),
      "utf8"
    );
    return true;
  } catch (e) {
    console.error("saveLive", e);
    return false;
  }
}

function baseClients() {
  const snap = loadJson(snapshotPath(), { clients: [] });
  let list = Array.isArray(snap) ? snap : snap.clients || [];
  const live = loadJson(livePath(), null);
  if (live && Array.isArray(live.clients)) {
    // live sobrescreve por id; _deleted remove
    const map = new Map(list.map((c) => [c.id, { ...c }]));
    for (const c of live.clients) {
      if (c && c._deleted) {
        map.delete(c.id);
      } else if (c && c.id) {
        map.set(c.id, { ...(map.get(c.id) || {}), ...c });
      }
    }
    list = Array.from(map.values());
  }
  return list.map(normalize);
}

function normalize(c) {
  const tel = c.telefone || c.phone || c.whatsapp || "";
  const email = c.email || "";
  return {
    id: c.id,
    nome: c.nome || c.name || "",
    name: c.name || c.nome || "",
    cnpj: c.cnpj || "",
    regime: c.regime || "simples_nacional",
    banco: c.banco || c.banco_principal || "itau",
    uf: c.uf || "",
    source: c.source || "manual",
    telefone: tel,
    whatsapp: tel,
    email,
    radar_id: c.radar_id || null,
  };
}

function parseBody(req) {
  if (!req.body) return {};
  if (typeof req.body === "string") {
    try {
      return JSON.parse(req.body);
    } catch {
      return {};
    }
  }
  return req.body;
}

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  const auth = requireAuth(req);
  if (!auth.ok) return res.status(auth.status).json({ error: auth.error });

  const url = new URL(req.url, "http://localhost");
  const parts = url.pathname.replace(/^\/api\/clients\/?/, "").split("/").filter(Boolean);
  const clientId = parts[0] ? decodeURIComponent(parts[0]) : null;

  try {
    if (req.method === "GET" && !clientId) {
      const clients = baseClients();
      return res.status(200).json({
        total: clients.length,
        clients,
        persistence: process.env.VERCEL
          ? "vercel-tmp (reexporte snapshot no PC para fixar no deploy)"
          : "data/web/clients_live.json",
      });
    }

    if (req.method === "GET" && clientId) {
      const c = baseClients().find((x) => x.id === clientId);
      if (!c) return res.status(404).json({ error: "Cliente não encontrado" });
      return res.status(200).json(c);
    }

    if (req.method === "POST" && !clientId) {
      const body = parseBody(req);
      const id =
        (body.id || "").trim() ||
        String(body.cnpj || "").replace(/\D/g, "");
      if (!id) return res.status(400).json({ error: "Informe id ou cnpj" });
      const nome = (body.nome || body.name || "").trim();
      if (!nome) return res.status(400).json({ error: "Informe nome" });
      const list = baseClients();
      if (list.some((c) => c.id === id)) {
        return res.status(400).json({ error: "Cliente já existe: " + id });
      }
      const created = normalize({
        id,
        nome,
        name: nome,
        cnpj: body.cnpj || id,
        regime: body.regime || "simples_nacional",
        banco: body.banco || body.banco_principal || "itau",
        uf: body.uf || "",
        telefone: body.telefone || body.whatsapp || body.phone || "",
        email: body.email || "",
        source: body.source || "manual",
      });
      list.push(created);
      const ok = saveLive(list);
      return res.status(ok ? 200 : 500).json({
        ok,
        client: created,
        warning: process.env.VERCEL
          ? "No Vercel a gravação é temporária. Rode no PC: python dashboard + export snapshot para fixar."
          : undefined,
      });
    }

    if ((req.method === "PATCH" || req.method === "PUT") && clientId) {
      const body = parseBody(req);
      const list = baseClients();
      const idx = list.findIndex((c) => c.id === clientId);
      if (idx < 0) return res.status(404).json({ error: "Cliente não encontrado" });
      const prev = list[idx];
      const tel = body.telefone ?? body.whatsapp ?? body.phone ?? prev.telefone;
      const updated = normalize({
        ...prev,
        ...body,
        id: clientId,
        nome: body.nome || body.name || prev.nome,
        name: body.nome || body.name || prev.name,
        telefone: tel,
        email: body.email !== undefined ? body.email : prev.email,
      });
      list[idx] = updated;
      const ok = saveLive(list);
      return res.status(200).json({ ok, client: updated });
    }

    if (req.method === "DELETE" && clientId) {
      const list = baseClients().filter((c) => c.id !== clientId);
      // marca deleted para não voltar do snapshot
      const live = loadJson(livePath(), { clients: [] });
      const liveList = Array.isArray(live.clients) ? live.clients : [];
      const cleaned = liveList.filter((c) => c.id !== clientId);
      cleaned.push({ id: clientId, _deleted: true });
      // rebuild live as full list + tombstones
      const tombstones = cleaned.filter((c) => c._deleted);
      const active = list;
      const ok = saveLive([...active, ...tombstones]);
      return res.status(200).json({ ok, deleted: clientId });
    }

    return res.status(405).json({ error: "Method not allowed" });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message || "Erro clientes" });
  }
};

module.exports.config = { maxDuration: 15 };
