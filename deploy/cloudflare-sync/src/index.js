// RabbitSoftware.inc sync service, on Cloudflare Workers with an R2 bucket.
//
// Lets one account's devices share what RabbitSoftware.inc knows, and lets the AI grow:
//
//   accounts/<id>/devices/<id>.json  each device's public key; added only with the account key's signature
//   accounts/<id>/history/<name>     chat history, ENCRYPTED ON THE DEVICE: this service only ever stores
//                                    scrambled bytes it can't read
//   corpus/batches/<name>.json       public research records from every device, readable by anyone and
//                                    cached by Cloudflare, so every device's corpus grows
//   training/<day>/<id>.json         answers people chose to share for training the next model; no account
//                                    or device is stored with them
//   pairing/<slot>.json              a short-lived code for adding a device (the code's secret half never
//                                    reaches this service)
//
// Every request that writes or reads private data is signed by a registered device (Ed25519, with the time,
// so it can't be replayed later). Creating a new account needs the SIGNUP_KEY secret until OPEN_SIGNUP is
// "true" (the public launch). Each account has daily limits so no one can fill the bucket.

const DAY_MS = 86_400_000;
const MAX_CLOCK_SKEW_MS = 300_000;
const MAX_DEVICES = 20;
const NAME_RE = /^[0-9A-Za-z._-]{1,80}$/;
const SLOT_RE = /^[A-Z2-7]{4}$/;
const ID_RE = /^[0-9a-f]{32}$/;
const DEFAULT_QUOTAS = { history: 500, corpus: 50, training: 300, pairing: 20 };

const json = (status, data, headers = {}) => Response.json(data, { status, headers });
const enc = new TextEncoder();

export function b64decode(text) {
  const raw = atob(String(text || ""));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function sha256hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function idFor(publicKey) {
  return (await sha256hex(publicKey)).slice(0, 32);
}

async function verifySignature(publicKey, signature, message) {
  try {
    const key = await crypto.subtle.importKey("raw", publicKey, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, signature, enc.encode(message));
  } catch {
    return false;
  }
}

// What a device signs for each request: method, path with query, time, and the body's SHA-256.
export async function requestMessage(method, pathAndQuery, time, body) {
  return `${method}\n${pathAndQuery}\n${time}\n${await sha256hex(body)}`;
}

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  return object ? await object.json() : null;
}

async function quota(env, account, kind) {
  const limits = { ...DEFAULT_QUOTAS, ...JSON.parse(env.QUOTAS || "{}") };
  const stub = env.QUOTA.get(env.QUOTA.idFromName("everyone"));
  const verdict = await (await stub.fetch("https://quota/check", {
    method: "POST", body: JSON.stringify({ key: `${account}|${kind}`, limit: limits[kind] }),
  })).json();
  return verdict.ok;
}

// Daily counters per account and kind. Only counts are stored.
export class Quota {
  constructor(ctx) {
    this.ctx = ctx;
  }

  async fetch(request) {
    const { key, limit, now = Date.now() } = await request.json();
    const day = new Date(now).toISOString().slice(0, 10);
    const stored = (await this.ctx.storage.get(key)) || { day, count: 0 };
    const state = stored.day === day ? stored : { day, count: 0 };
    if (state.count >= limit) return json(200, { ok: false });
    state.count += 1;
    await this.ctx.storage.put(key, state);
    return json(200, { ok: true });
  }
}

// The registered, not-removed device that signed this request, or a refusal.
async function signedDevice(request, env, body) {
  const account = request.headers.get("X-Account") || "";
  const device = request.headers.get("X-Device") || "";
  const time = Number(request.headers.get("X-Time"));
  if (!ID_RE.test(account) || !ID_RE.test(device) || !Number.isFinite(time)) return { error: json(401, { error: "sign the request" }) };
  if (Math.abs(Date.now() - time) > MAX_CLOCK_SKEW_MS) return { error: json(401, { error: "this device's clock is off by more than 5 minutes" }) };
  const record = await readJson(env.SYNC, `accounts/${account}/devices/${device}.json`);
  if (!record || record.removed) return { error: json(403, { error: "this device isn't part of the account (or was removed)" }) };
  const url = new URL(request.url);
  const message = await requestMessage(request.method, url.pathname + url.search, String(time), body);
  if (!(await verifySignature(b64decode(record.public_key), b64decode(request.headers.get("X-Signature")), message))) {
    return { error: json(401, { error: "the signature doesn't match" }) };
  }
  return { account, device, record };
}

async function registerDevice(request, env, body) {
  let data;
  try {
    data = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return json(400, { error: "send JSON" });
  }
  const accountKey = b64decode(data.account_key);
  const deviceKey = b64decode(data.device_key);
  const name = String(data.name || "").slice(0, 60);
  if (accountKey.length !== 32 || deviceKey.length !== 32 || !name) return json(400, { error: "send account_key, device_key and a name" });
  if (Math.abs(Date.now() - Number(data.time)) > MAX_CLOCK_SKEW_MS) return json(401, { error: "this device's clock is off by more than 5 minutes" });
  const account = await idFor(accountKey);
  const device = await idFor(deviceKey);
  const message = `register\n${account}\n${data.device_key}\n${name}\n${data.time}`;
  if (!(await verifySignature(accountKey, b64decode(data.signature), message))) return json(401, { error: "the account signature doesn't match" });

  const accountFile = `accounts/${account}/account.json`;
  if (!(await env.SYNC.head(accountFile))) {
    if (env.OPEN_SIGNUP !== "true" && (!env.SIGNUP_KEY || request.headers.get("X-Signup-Key") !== env.SIGNUP_KEY)) {
      return json(403, { error: "new accounts aren't open yet" });
    }
    await env.SYNC.put(accountFile, JSON.stringify({ account_key: data.account_key, created_at: new Date().toISOString() }));
  }
  const devices = await env.SYNC.list({ prefix: `accounts/${account}/devices/` });
  if (devices.objects.length >= MAX_DEVICES) return json(409, { error: `an account can have at most ${MAX_DEVICES} devices` });
  await env.SYNC.put(`accounts/${account}/devices/${device}.json`, JSON.stringify({
    public_key: data.device_key, name, added_at: new Date().toISOString(), removed: false,
  }));
  return json(200, { account, device });
}

const RECORD_LIMITS = { source: 32, external_id: 64, title: 500, abstract: 6000, source_url: 300, published_at: 32 };

export function cleanRecords(records) {
  if (!Array.isArray(records) || records.length === 0 || records.length > 200) throw new Error("send 1 to 200 records");
  return records.map((r) => {
    const kept = {};
    for (const [field, max] of Object.entries(RECORD_LIMITS)) {
      const value = String(r?.[field] ?? "").trim();
      if (value.length > max) throw new Error(`${field} is longer than ${max} characters`);
      kept[field] = value;
    }
    if (!kept.source || !kept.external_id || !kept.title || !/^https:\/\//.test(kept.source_url)) {
      throw new Error("each record needs a source, external_id, title and an https source_url");
    }
    return kept;
  });
}

export function cleanTraining(item) {
  const question = String(item?.question ?? "").trim();
  const answer = String(item?.answer ?? "").trim();
  const rating = Number(item?.rating ?? 0);
  const sources = Array.isArray(item?.sources) ? item.sources.slice(0, 10).map((s) => String(s).slice(0, 300)) : [];
  if (!question || question.length > 2000 || !answer || answer.length > 4000) throw new Error("send a question (up to 2000 characters) and an answer (up to 4000)");
  if (![-1, 0, 1].includes(rating)) throw new Error("rating must be -1, 0 or 1");
  return { question, answer, sources, rating, model: String(item?.model ?? "").slice(0, 64), shared_at: new Date().toISOString() };
}

async function listAll(bucket, prefix) {
  const objects = [];
  let cursor;
  do {
    const page = await bucket.list({ prefix, cursor });
    objects.push(...page.objects);
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return objects;
}

async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length > 1_048_576) return json(413, { error: "at most 1 MB per request" });

  if (method === "GET" && (path === "/" || path === "/health")) return json(200, { service: "RabbitSoftware.inc sync", ok: true });

  // Public: the shared research corpus (public records), cached at Cloudflare's edge.
  if (method === "GET" && path === "/v1/corpus/batches") {
    const names = (await listAll(env.SYNC, "corpus/batches/")).map((o) => o.key.slice("corpus/batches/".length));
    return json(200, { batches: names }, { "Cache-Control": "public, max-age=60" });
  }
  let m;
  if (method === "GET" && (m = path.match(/^\/v1\/corpus\/batches\/([0-9A-Za-z._-]{1,80})$/))) {
    const object = await env.SYNC.get(`corpus/batches/${m[1]}`);
    if (!object) return json(404, { error: "no such batch" });
    return new Response(object.body, { headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=31536000, immutable" } });
  }

  // A new device joining an account (signed by the account key from the recovery phrase or pairing code).
  if (method === "POST" && path === "/v1/devices") return registerDevice(request, env, body);

  // A new device fetching its pairing slot: only the encrypted account secret; the code's secret half
  // never reaches this service. Five tries, ten minutes.
  if (method === "GET" && (m = path.match(/^\/v1\/pairing\/([A-Z2-7]{4})$/))) {
    const key = `pairing/${m[1]}.json`;
    const slot = await readJson(env.SYNC, key);
    if (!slot || slot.expires_at < Date.now() || slot.attempts >= 5) {
      if (slot) await env.SYNC.delete(key);
      return json(404, { error: "that pairing code has expired; make a new one on your other device" });
    }
    slot.attempts += 1;
    await env.SYNC.put(key, JSON.stringify(slot));
    return json(200, { sealed: slot.sealed });
  }

  // Everything else: signed by a registered device.
  const who = await signedDevice(request, env, body);
  if (who.error) return who.error;
  const { account } = who;
  let data = null;
  if (body.length && request.headers.get("Content-Type") === "application/json") {
    try {
      data = JSON.parse(new TextDecoder().decode(body));
    } catch {
      return json(400, { error: "send JSON" });
    }
  }

  if (method === "GET" && path === "/v1/devices") {
    const devices = [];
    for (const o of await listAll(env.SYNC, `accounts/${account}/devices/`)) {
      const d = await readJson(env.SYNC, o.key);
      devices.push({ device: o.key.split("/").pop().replace(".json", ""), name: d.name, added_at: d.added_at, removed: d.removed });
    }
    return json(200, { devices });
  }
  if (method === "DELETE" && (m = path.match(/^\/v1\/devices\/([0-9a-f]{32})$/))) {
    const key = `accounts/${account}/devices/${m[1]}.json`;
    const d = await readJson(env.SYNC, key);
    if (!d) return json(404, { error: "no such device" });
    await env.SYNC.put(key, JSON.stringify({ ...d, removed: true, removed_at: new Date().toISOString() }));
    return json(200, { removed: m[1] });
  }

  if (method === "PUT" && (m = path.match(/^\/v1\/history\/([0-9A-Za-z._-]{1,80})$/))) {
    if (!(await quota(env, account, "history"))) return json(429, { error: "too many history uploads today" });
    await env.SYNC.put(`accounts/${account}/history/${m[1]}`, body);
    return json(200, { stored: m[1], bytes: body.length });
  }
  if (method === "GET" && path === "/v1/history") {
    const items = (await listAll(env.SYNC, `accounts/${account}/history/`)).map((o) => ({ name: o.key.split("/").pop(), bytes: o.size }));
    return json(200, { history: items });
  }
  if (method === "GET" && (m = path.match(/^\/v1\/history\/([0-9A-Za-z._-]{1,80})$/))) {
    const object = await env.SYNC.get(`accounts/${account}/history/${m[1]}`);
    if (!object) return json(404, { error: "no such history file" });
    return new Response(object.body, { headers: { "Content-Type": "application/octet-stream" } });
  }

  if (method === "POST" && path === "/v1/corpus") {
    let records;
    try {
      records = cleanRecords(data?.records);
    } catch (error) {
      return json(400, { error: error.message });
    }
    if (!(await quota(env, account, "corpus"))) return json(429, { error: "too many corpus uploads today" });
    const name = `${new Date().toISOString().replace(/[:.]/g, "")}-${crypto.randomUUID().slice(0, 8)}.json`;
    await env.SYNC.put(`corpus/batches/${name}`, JSON.stringify({ records }));
    return json(200, { batch: name, records: records.length });
  }

  if (method === "POST" && path === "/v1/training") {
    let item;
    try {
      item = cleanTraining(data);
    } catch (error) {
      return json(400, { error: error.message });
    }
    if (!(await quota(env, account, "training"))) return json(429, { error: "too many shared answers today" });
    const key = `training/${item.shared_at.slice(0, 10)}/${crypto.randomUUID()}.json`;
    await env.SYNC.put(key, JSON.stringify(item));   // no account or device is stored with it
    return json(200, { shared: true });
  }

  if (method === "POST" && path === "/v1/pairing") {
    const slot = String(data?.slot || "");
    const sealed = String(data?.sealed || "");
    if (!SLOT_RE.test(slot) || !sealed || sealed.length > 1024) return json(400, { error: "send a slot and the sealed secret" });
    if (await env.SYNC.head(`pairing/${slot}.json`)) return json(409, { error: "that slot is taken; try again" });
    if (!(await quota(env, account, "pairing"))) return json(429, { error: "too many pairing codes today" });
    await env.SYNC.put(`pairing/${slot}.json`, JSON.stringify({ sealed, expires_at: Date.now() + 600_000, attempts: 0 }));
    return json(200, { slot, expires_in: 600 });
  }

  // The owner exporting shared training answers to the private Hugging Face dataset.
  if (method === "GET" && path === "/v1/admin/training") {
    if (!env.ADMIN_ACCOUNT || account !== env.ADMIN_ACCOUNT) return json(403, { error: "only the owner's account can export training data" });
    const after = url.searchParams.get("after") || "";
    const keys = (await listAll(env.SYNC, "training/")).map((o) => o.key).filter((k) => k > after).sort().slice(0, 500);
    const items = [];
    for (const key of keys) items.push({ key, ...(await readJson(env.SYNC, key)) });
    return json(200, { items });
  }

  return json(404, { error: "not found" });
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch (error) {
      return json(500, { error: `the sync service hit an error (${error.name})` });
    }
  },
};
