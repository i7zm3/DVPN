function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extra,
    },
  });
}

const dynamicProviders = new Map();
const KV_PROVIDER_KEY = "providers:dynamic";
const KV_CLAIM_PREFIX = "claims:";

function nowMs() {
  return Date.now();
}

function dynamicProviderTtlMs(env) {
  const seconds = Math.max(60, Number(env.DYNAMIC_PROVIDER_TTL_SECONDS || "300"));
  return seconds * 1000;
}

function staticProvidersEnabled(env) {
  return String(env.STATIC_PROVIDERS_ENABLED || "false").toLowerCase() === "true";
}

function isFreshDynamicProvider(provider, env) {
  const ts = Number(provider?.updated_at || 0);
  if (!Number.isFinite(ts) || ts <= 0) return false;
  return nowMs() - ts <= dynamicProviderTtlMs(env);
}

function parseProviders(env) {
  try {
    const parsed = JSON.parse(env.PROVIDERS_JSON || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function randomId(prefix = "sess") {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${prefix}-${hex}`;
}

function randomChoice(arr) {
  if (!arr.length) return null;
  const idx = Math.floor(Math.random() * arr.length);
  return arr[idx];
}

function toBase64Url(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64Url(input) {
  const normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = normalized.length % 4 === 0 ? "" : "=".repeat(4 - (normalized.length % 4));
  const raw = atob(normalized + pad);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function hmacSign(secret, message) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return toBase64Url(new Uint8Array(sig));
}

async function hmacVerify(secret, message, signature) {
  try {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      enc.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    return await crypto.subtle.verify("HMAC", key, fromBase64Url(signature), enc.encode(message));
  } catch {
    return false;
  }
}

async function deriveClientIp(token, providerId) {
  const input = new TextEncoder().encode(`${token}|${providerId}`);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", input));
  const a = (digest[0] % 254) + 1;
  const b = (digest[1] % 253) + 2;
  return `10.66.${a}.${b}/32`;
}

function leasePayload(token, providerId, clientIp, exp, nonce) {
  return `${token}|${providerId}|${clientIp}|${exp}|${nonce}`;
}

async function makeLease(token, providerId, env) {
  const ttl = Math.max(60, Number(env.SESSION_TTL_SECONDS || "300"));
  const exp = Date.now() + ttl * 1000;
  const nonce = randomId("lease");
  const clientIp = await deriveClientIp(token, providerId);
  const secret = env.SESSION_HMAC_SECRET || "dev-only-change-me";
  const payload = leasePayload(token, providerId, clientIp, exp, nonce);
  const sig = await hmacSign(secret, payload);
  return {
    client_ip: clientIp,
    lease_nonce: nonce,
    lease_exp: exp,
    lease_sig: sig,
  };
}

function mergedProviders(env) {
  const staticProviders = staticProvidersEnabled(env)
    ? parseProviders(env).filter((p) => isPublicEndpoint(p.endpoint || ""))
    : [];
  const dynamic = Array.from(dynamicProviders.values()).filter(
    (p) => isPublicEndpoint(p.endpoint || "") && isFreshDynamicProvider(p, env)
  );
  const out = new Map();
  for (const p of staticProviders) out.set(p.id, p);
  for (const p of dynamic) out.set(p.id, p);
  return Array.from(out.values());
}

async function pruneDynamicProviders(env) {
  let removed = 0;
  for (const [id, p] of dynamicProviders.entries()) {
    const healthy = (p?.health || "ok") === "ok";
    const valid = isPublicEndpoint(p?.endpoint || "") && isFreshDynamicProvider(p, env) && healthy;
    if (!valid) {
      dynamicProviders.delete(id);
      removed += 1;
    }
  }
  if (removed > 0) {
    await saveDynamicProviders(env);
  }
  return removed;
}

async function loadDynamicProviders(env) {
  if (!env.NODE_POOL_KV) return;
  try {
    const raw = await env.NODE_POOL_KV.get(KV_PROVIDER_KEY);
    if (!raw) return;
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return;
    dynamicProviders.clear();
    for (const p of arr) {
      if (p && p.id && p.endpoint && p.public_key && isFreshDynamicProvider(p, env)) {
        dynamicProviders.set(p.id, p);
      }
    }
  } catch {
    // best effort
  }
}

async function saveDynamicProviders(env) {
  if (!env.NODE_POOL_KV) return;
  try {
    const payload = JSON.stringify(Array.from(dynamicProviders.values()));
    await env.NODE_POOL_KV.put(KV_PROVIDER_KEY, payload);
  } catch {
    // best effort
  }
}

function isWireGuardPublicKey(key) {
  if (typeof key !== "string") return false;
  const v = key.trim();
  return /^[A-Za-z0-9+/]{43}=$/.test(v);
}

async function loadClaims(env, providerId) {
  if (!env.NODE_POOL_KV) return [];
  try {
    const raw = await env.NODE_POOL_KV.get(`${KV_CLAIM_PREFIX}${providerId}`);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function saveClaims(env, providerId, claims) {
  if (!env.NODE_POOL_KV) return;
  await env.NODE_POOL_KV.put(`${KV_CLAIM_PREFIX}${providerId}`, JSON.stringify(claims));
}

function pruneClaims(claims) {
  const now = nowMs();
  return claims.filter((c) => Number(c?.lease_exp || 0) > now);
}

function parseEndpoint(endpoint) {
  try {
    const parsed = new URL(`udp://${endpoint}`);
    const port = Number(parsed.port || "0");
    if (!parsed.hostname || !Number.isInteger(port) || port < 1 || port > 65535) {
      return null;
    }
    return { host: parsed.hostname, port };
  } catch {
    return null;
  }
}

function isDisallowedHost(host) {
  const lowered = host.toLowerCase();
  if (lowered === "localhost" || lowered === "ip6-localhost" || lowered.endsWith(".local")) {
    return true;
  }

  const ipv4 = lowered.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ipv4) {
    const a = Number(ipv4[1]);
    const b = Number(ipv4[2]);
    if (
      a === 10 ||
      a === 127 ||
      a === 0 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168)
    ) {
      return true;
    }
    return false;
  }

  // Basic IPv6 local ranges: loopback, unique local, and link-local.
  if (lowered === "::1" || lowered.startsWith("fc") || lowered.startsWith("fd") || lowered.startsWith("fe80:")) {
    return true;
  }
  return false;
}

function isPublicEndpoint(endpoint) {
  const parsed = parseEndpoint(endpoint);
  if (!parsed) return false;
  return !isDisallowedHost(parsed.host);
}

function parsePaidTokens(env) {
  try {
    const source = env.PAID_TOKENS_SECRET || env.PAID_TOKENS_JSON || "[]";
    const parsed = JSON.parse(source);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x) => typeof x === "string" && x.length > 0);
  } catch {
    return [];
  }
}

function isTokenPaid(token, env) {
  if (!token) return false;
  const paidTokens = parsePaidTokens(env);
  if (paidTokens.length === 0) return true;
  return paidTokens.includes(token);
}

function requestToken(request) {
  const token = request.headers.get("x-dvpn-token");
  if (token) return token.trim();
  const auth = request.headers.get("authorization") || "";
  if (auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  return "";
}

function poolAccessAllowed(request, env) {
  const token = requestToken(request);
  if (!token) {
    return { ok: false, code: 402, error: "payment_required" };
  }
  if (!isTokenPaid(token, env)) {
    return { ok: false, code: 403, error: "payment_inactive" };
  }
  return { ok: true };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    await loadDynamicProviders(env);
    await pruneDynamicProviders(env);

    if (request.method === "GET" && path === "/") {
      return json({
        ok: true,
        service: "dvpn-worker",
        endpoints: [
          "GET /health",
          "GET /providers",
          "POST /providers/approve",
          "POST /providers/register",
          "POST /providers/prune",
          "POST /providers/claim/next",
          "POST /verify",
          "POST /verify/checkout/start",
          "POST /verify/checkout/status",
          "POST /provision",
          "GET /portal",
        ],
      });
    }

    if (request.method === "GET" && path === "/health") {
      return json({ ok: true, ts: Date.now() });
    }

    if (request.method === "GET" && path === "/providers") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      const token = requestToken(request);
      const providers = mergedProviders(env);
      const enriched = [];
      for (const p of providers) {
        const lease = await makeLease(token, p.id, env);
        enriched.push({
          ...p,
          ...lease,
        });
      }
      return json(enriched);
    }

    if (request.method === "POST" && path === "/providers/approve") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const token = requestToken(request);
      if (!body.provider_id || !body.lease_nonce || !body.lease_exp || !body.lease_sig || !body.client_ip) {
        return json({ ok: false, error: "lease_fields_required" }, 400);
      }
      if (!isWireGuardPublicKey(body.client_public_key || "")) {
        return json({ ok: false, error: "client_public_key_required" }, 400);
      }
      if (typeof body.token === "string" && body.token.trim() !== token) {
        return json({ ok: false, error: "token_mismatch" }, 403);
      }
      const now = Date.now();
      const exp = Number(body.lease_exp || 0);
      if (!Number.isFinite(exp) || exp < now) {
        return json({ ok: false, error: "lease_expired" }, 403);
      }
      const secret = env.SESSION_HMAC_SECRET || "dev-only-change-me";
      const payload = leasePayload(token, String(body.provider_id), String(body.client_ip), exp, String(body.lease_nonce));
      const ok = await hmacVerify(secret, payload, String(body.lease_sig));
      if (!ok) {
        return json({ ok: false, error: "lease_signature_invalid" }, 403);
      }
      const providerId = String(body.provider_id);
      const claims = pruneClaims(await loadClaims(env, providerId));
      claims.push({
        lease_nonce: String(body.lease_nonce),
        lease_exp: exp,
        client_ip: String(body.client_ip),
        client_public_key: String(body.client_public_key).trim(),
        created_at: now,
      });
      await saveClaims(env, providerId, claims.slice(-32));
      return json({ ok: true, approved: true, phase: "control_plane_verified" });
    }

    if (request.method === "POST" && path === "/providers/register") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      if (!body.id || !body.endpoint || !body.public_key) {
        return json({ ok: false, error: "id_endpoint_public_key_required" }, 400);
      }
      if (!isPublicEndpoint(body.endpoint)) {
        return json({ ok: false, error: "endpoint_must_be_public_routable" }, 400);
      }
      dynamicProviders.set(body.id, {
        id: body.id,
        endpoint: body.endpoint,
        public_key: body.public_key,
        allowed_ips: body.allowed_ips || "0.0.0.0/0",
        health: "ok",
        meta: body.metadata || {},
        updated_at: nowMs(),
      });
      await saveDynamicProviders(env);
      return json({ ok: true, registered: true, node_id: body.id });
    }

    if (request.method === "POST" && path === "/providers/prune") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      const removed = await pruneDynamicProviders(env);
      return json({ ok: true, removed, remaining: dynamicProviders.size });
    }

    if (request.method === "POST" && path === "/providers/claim/next") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const providerId = String(body.provider_id || "").trim();
      if (!providerId) {
        return json({ ok: false, error: "provider_id_required" }, 400);
      }
      const claims = pruneClaims(await loadClaims(env, providerId));
      const claim = claims.shift() || null;
      await saveClaims(env, providerId, claims);
      return json({ ok: true, claim });
    }

    if (request.method === "POST" && path === "/verify") {
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const token = typeof body.token === "string" ? body.token.trim() : "";
      const requiredWallet = env.REQUIRED_WALLET || "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn";
      const requiredInterval = env.REQUIRED_INTERVAL || "monthly";
      const requiredPrice = Number(env.REQUIRED_PRICE_USD || "9.99");

      return json({
        active: isTokenPaid(token, env),
        wallet: requiredWallet,
        interval: requiredInterval,
        amount_usd: requiredPrice,
      });
    }

    if (request.method === "POST" && path === "/verify/checkout/start") {
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const publicBase = env.PUBLIC_BASE_URL || `${url.protocol}//${url.host}`;
      return json({
        session_id: randomId("sess"),
        user_id: body.user_id || "user",
        checkout_url: `${publicBase}/portal`,
      });
    }

    if (request.method === "POST" && path === "/verify/checkout/status") {
      const requiredWallet = env.REQUIRED_WALLET || "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn";
      const requiredInterval = env.REQUIRED_INTERVAL || "monthly";
      const requiredPrice = Number(env.REQUIRED_PRICE_USD || "9.99");
      return json({
        active: true,
        wallet: requiredWallet,
        interval: requiredInterval,
        amount_usd: requiredPrice,
      });
    }

    if (request.method === "POST" && path === "/provision") {
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      if (!body.payment_token) {
        return json({ ok: false, error: "payment_token_required" }, 403);
      }
      const providers = mergedProviders(env);
      const chosen = randomChoice(providers);
      if (!chosen) {
        return json({ ok: false, error: "no_providers_configured" }, 503);
      }
      return json({
        id: chosen.id,
        endpoint: chosen.endpoint,
        public_key: chosen.public_key,
        allowed_ips: chosen.allowed_ips || "0.0.0.0/0,::/0",
      });
    }

    if (request.method === "GET" && path === "/portal") {
      return new Response(
        "<!doctype html><html><body><h1>DVPN Payment Portal</h1><p>Checkout flow placeholder.</p></body></html>",
        { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } }
      );
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
