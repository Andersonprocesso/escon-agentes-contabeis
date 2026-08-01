/**
 * Auth compartilhada — padrão EsconManus.
 * Env: ADMIN_USER, ADMIN_PASSWORD, AUTH_SECRET (recomendado em produção)
 */

const crypto = require("crypto");

const TOKEN_TTL_MS = 12 * 60 * 60 * 1000;

function getAdminUser() {
  return (process.env.ADMIN_USER || "admin").trim().toLowerCase();
}

function getAdminPassword() {
  return process.env.ADMIN_PASSWORD || "";
}

function getAuthSecret() {
  if (process.env.AUTH_SECRET && process.env.AUTH_SECRET.trim()) {
    return process.env.AUTH_SECRET.trim();
  }
  const pw = getAdminPassword();
  if (pw) {
    return crypto.createHmac("sha256", "escon-agentes-auth-v1").update(pw).digest("hex");
  }
  return crypto
    .createHmac("sha256", "escon-agentes-auth-v1")
    .update("escon-agentes-no-secret-fallback")
    .digest("hex");
}

function isAuthConfigured() {
  return Boolean(getAdminPassword());
}

function timingSafeEqualStr(a, b) {
  const ba = Buffer.from(String(a ?? ""), "utf8");
  const bb = Buffer.from(String(b ?? ""), "utf8");
  if (ba.length !== bb.length) {
    if (ba.length) crypto.timingSafeEqual(ba, ba);
    return false;
  }
  return crypto.timingSafeEqual(ba, bb);
}

function b64url(buf) {
  return Buffer.from(buf)
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function b64urlDecode(s) {
  let t = String(s).replace(/-/g, "+").replace(/_/g, "/");
  while (t.length % 4) t += "=";
  return Buffer.from(t, "base64").toString("utf8");
}

function b64urlJson(obj) {
  return b64url(JSON.stringify(obj));
}

function signToken(payload, secret) {
  const data = b64urlJson(payload);
  const sig = b64url(crypto.createHmac("sha256", secret).update(data).digest());
  return `${data}.${sig}`;
}

function verifyToken(token, secret) {
  if (!token || typeof token !== "string" || !secret) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [data, sig] = parts;
  const expected = b64url(crypto.createHmac("sha256", secret).update(data).digest());
  if (!timingSafeEqualStr(sig, expected)) return null;
  try {
    const payload = JSON.parse(b64urlDecode(data));
    if (!payload.exp || Date.now() > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

function passwordMatches(password) {
  const envPw = getAdminPassword();
  if (!envPw) return false;
  return timingSafeEqualStr(String(password || ""), envPw);
}

function validateCredentials(username, password) {
  if (!isAuthConfigured()) {
    return {
      ok: false,
      status: 503,
      error:
        "Configure ADMIN_PASSWORD no Vercel (Settings → Environment Variables).",
    };
  }
  const user = getAdminUser();
  const given = String(username || "").trim().toLowerCase();
  if (!timingSafeEqualStr(given, user)) {
    return { ok: false, status: 401, error: "Usuário ou senha inválidos" };
  }
  if (!passwordMatches(password)) {
    return { ok: false, status: 401, error: "Usuário ou senha inválidos" };
  }
  const secret = getAuthSecret();
  const now = Date.now();
  const token = signToken(
    { sub: user, iat: now, exp: now + TOKEN_TTL_MS, role: "admin" },
    secret
  );
  return {
    ok: true,
    token,
    expiresInMs: TOKEN_TTL_MS,
    user: { username: user },
  };
}

function requireAuth(req) {
  const h = req.headers.authorization || req.headers.Authorization || "";
  const m = String(h).match(/^Bearer\s+(.+)$/i);
  if (!m) return { ok: false, status: 401, error: "Não autenticado" };
  const payload = verifyToken(m[1].trim(), getAuthSecret());
  if (!payload) return { ok: false, status: 401, error: "Sessão expirada ou inválida — faça login de novo" };
  return { ok: true, user: payload };
}

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
}

module.exports = {
  validateCredentials,
  requireAuth,
  setCors,
  isAuthConfigured,
  getAdminUser,
  TOKEN_TTL_MS,
};
