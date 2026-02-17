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

function mergedProviders(env) {
  const staticProviders = parseProviders(env).filter((p) => isPublicEndpoint(p.endpoint || ""));
  const dynamic = Array.from(dynamicProviders.values()).filter((p) => isPublicEndpoint(p.endpoint || ""));
  const out = new Map();
  for (const p of staticProviders) out.set(p.id, p);
  for (const p of dynamic) out.set(p.id, p);
  return Array.from(out.values());
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
      if (p && p.id && p.endpoint && p.public_key) {
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
    const parsed = JSON.parse(env.PAID_TOKENS_JSON || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x) => typeof x === "string" && x.length > 0);
  } catch {
    return [];
  }
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
  const paidTokens = parsePaidTokens(env);
  if (paidTokens.length > 0 && !paidTokens.includes(token)) {
    return { ok: false, code: 403, error: "payment_inactive" };
  }
  return { ok: true };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    await loadDynamicProviders(env);

    if (request.method === "GET" && path === "/") {
      return json({
        ok: true,
        service: "dvpn-worker",
        endpoints: [
          "GET /health",
          "GET /providers",
          "POST /providers/approve",
          "POST /providers/register",
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
      const providers = mergedProviders(env);
      return json(providers);
    }

    if (request.method === "POST" && path === "/providers/approve") {
      const gate = poolAccessAllowed(request, env);
      if (!gate.ok) return json({ ok: false, error: gate.error }, gate.code);
      return json({ ok: true, approved: true });
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
        updated_at: Date.now(),
      });
      await saveDynamicProviders(env);
      return json({ ok: true, registered: true, node_id: body.id });
    }

    if (request.method === "POST" && path === "/verify") {
      let body = {};
      try {
        body = await request.json();
      } catch {
        return json({ ok: false, error: "invalid_json" }, 400);
      }
      const requiredWallet = env.REQUIRED_WALLET || "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn";
      const requiredInterval = env.REQUIRED_INTERVAL || "monthly";
      const requiredPrice = Number(env.REQUIRED_PRICE_USD || "9.99");

      return json({
        active: Boolean(body.token),
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
