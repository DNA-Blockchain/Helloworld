// RabbitSoftware.inc model gateway, on Cloudflare Workers.
//
// Downloads of RabbitSoftware.inc send questions here, never straight to the Hugging Face endpoint, because
// the endpoint needs the owner's access token and that token must never ship in a public download. This
// Worker holds the token as an encrypted Cloudflare secret (HF_TOKEN) and forwards each question to the
// endpoint, with limits so strangers can't run up the bill:
//
//   - each person gets at most PER_CLIENT_PER_HOUR questions an hour,
//   - everyone together gets at most DAILY_LIMIT questions a day (the spending cap),
//   - a question is at most MAX_PROMPT_CHARS long and an answer at most MAX_TOKENS tokens.
//
// It speaks the same OpenAI-compatible API it forwards to (POST /v1/chat/completions), so hosted_ai.py works
// against either. Questions and answers are never written down. People are told apart by a SHA-256 of their
// network address, held only in memory; the only thing stored is the day's question count.
//
// The same rules as deploy/gateway/app.py (the Hugging Face Space version).

const MODEL_NAME = "rabbitsoftware";

function number(value, fallback) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function json(status, data) {
  return Response.json(data, { status });
}

// Only what the model needs goes on: the messages (checked) and a capped answer length.
export function cleanRequest(body, maxPromptChars, maxTokens) {
  const messages = body && body.messages;
  if (!Array.isArray(messages) || messages.length === 0 || messages.length > 8) {
    throw new Error("send 1 to 8 messages");
  }
  let total = 0;
  const kept = messages.map((m) => {
    if (!m || !["system", "user", "assistant"].includes(m.role) || typeof m.content !== "string") {
      throw new Error("each message needs a role (system, user or assistant) and text content");
    }
    total += m.content.length;
    return { role: m.role, content: m.content };
  });
  if (total > maxPromptChars) throw new Error(`the question is too long (at most ${maxPromptChars} characters)`);
  const wanted = Number(body.max_tokens ?? maxTokens);
  const temperature = Number(body.temperature ?? 0.2);
  if (!Number.isFinite(wanted) || !Number.isFinite(temperature)) {
    throw new Error("max_tokens and temperature must be numbers");
  }
  return {
    model: MODEL_NAME,
    messages: kept,
    max_tokens: Math.max(1, Math.min(Math.trunc(wanted) || maxTokens, maxTokens)),
    temperature: Math.max(0, Math.min(temperature, 1.5)),
    stream: false,
  };
}

// One Durable Object counts for everyone, so the limits hold across all of Cloudflare's servers.
export class Limits {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.recent = new Map(); // hashed address -> times of this hour's questions; memory only
  }

  async fetch(request) {
    const { client, perHour, daily, now = Date.now() } = await request.json();
    const day = new Date(now).toISOString().slice(0, 10);
    let state = (await this.ctx.storage.get("day")) || { day, count: 0 };
    if (state.day !== day) {
      state = { day, count: 0 };
      this.recent.clear();
    }
    if (state.count >= daily) {
      return json(200, { ok: false, reason: "the model has answered all the questions it can today; try again tomorrow (UTC)" });
    }
    const times = (this.recent.get(client) || []).filter((t) => now - t < 3_600_000);
    if (times.length >= perHour) {
      this.recent.set(client, times);
      return json(200, { ok: false, reason: "too many questions this hour; try again later" });
    }
    times.push(now);
    this.recent.set(client, times);
    state.count += 1;
    await this.ctx.storage.put("day", state);
    return json(200, { ok: true });
  }
}

async function hashed(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function forward(env, payload) {
  let url = String(env.ENDPOINT_URL || "").replace(/\/+$/, "");
  url = url.endsWith("/v1") ? `${url}/chat/completions` : `${url}/v1/chat/completions`;
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", Authorization: `Bearer ${env.HF_TOKEN}` },
      body: JSON.stringify(payload),
    });
  } catch {
    return json(503, { error: "the model couldn't be reached; it may be waking up" });
  }
  if (!response.ok) {
    // A sleeping endpoint answers 503 while it wakes; pass that on so the client can say "try again".
    return json([502, 503, 504].includes(response.status) ? 503 : 502, { error: `the model returned HTTP ${response.status}` });
  }
  return new Response(response.body, { status: 200, headers: { "Content-Type": "application/json" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json(200, { service: "RabbitSoftware.inc model gateway", ok: true, api: "POST /v1/chat/completions" });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") return json(404, { error: "not found" });
    if (!env.ENDPOINT_URL || !env.HF_TOKEN) return json(503, { error: "the gateway isn't set up yet" });

    const maxPromptChars = number(env.MAX_PROMPT_CHARS, 12000);
    if (Number(request.headers.get("Content-Length") || 0) > maxPromptChars * 4 + 4096) {
      return json(413, { error: "the question is too long" });
    }
    let payload;
    try {
      payload = cleanRequest(await request.json(), maxPromptChars, number(env.MAX_TOKENS, 400));
    } catch (error) {
      return json(400, { error: error instanceof SyntaxError ? "send JSON" : error.message });
    }

    const client = await hashed(request.headers.get("CF-Connecting-IP") || "unknown");
    const limits = env.LIMITS.get(env.LIMITS.idFromName("everyone"));
    const verdict = await (await limits.fetch("https://limits/check", {
      method: "POST",
      body: JSON.stringify({ client, perHour: number(env.PER_CLIENT_PER_HOUR, 20), daily: number(env.DAILY_LIMIT, 500) }),
    })).json();
    if (!verdict.ok) return json(429, { error: verdict.reason });
    return forward(env, payload);
  },
};
