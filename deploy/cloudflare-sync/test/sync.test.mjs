// Runs the sync Worker's real code against an in-memory R2 bucket: node --test deploy/cloudflare-sync/test/sync.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { cleanRecords, idFor, requestMessage } from "../src/index.js";
import { fakeEnv as env } from "./fakes.mjs";

const b64 = (bytes) => Buffer.from(bytes).toString("base64");

async function keypair() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const pub = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  return { pair, pub, pubB64: b64(pub), id: await idFor(pub) };
}

async function sign(key, message) {
  return b64(new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key.pair.privateKey, new TextEncoder().encode(message))));
}

async function register(e, account, device, name = "laptop", signupKey = "letmein") {
  const time = Date.now();
  const signature = await sign(account, `register\n${account.id}\n${device.pubB64}\n${name}\n${time}`);
  return worker.fetch(new Request("https://sync.example/v1/devices", {
    method: "POST", headers: signupKey ? { "X-Signup-Key": signupKey } : {},
    body: JSON.stringify({ account_key: account.pubB64, device_key: device.pubB64, name, time, signature }),
  }), e);
}

async function call(e, method, path, account, device, body = new Uint8Array(), time = Date.now()) {
  const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
  const signature = await sign(device, await requestMessage(method, path, String(time), bytes));
  const headers = { "X-Account": account.id, "X-Device": device.id, "X-Time": String(time), "X-Signature": signature };
  if (typeof body === "string") headers["Content-Type"] = "application/json";
  return worker.fetch(new Request(`https://sync.example${path}`, { method, headers, body: method === "GET" ? undefined : bytes }), e);
}

test("new accounts need the sign-up key until launch; more devices only need the account's signature", async () => {
  const e = env();
  const [account, laptop, phone] = [await keypair(), await keypair(), await keypair()];
  assert.equal((await register(e, account, laptop, "laptop", "")).status, 403);
  const first = await register(e, account, laptop);
  assert.equal(first.status, 200);
  assert.deepEqual(await first.json(), { account: account.id, device: laptop.id });
  assert.equal((await register(e, account, phone, "phone", "")).status, 200);
  const stranger = await keypair();
  const forged = await register(e, account, stranger, "x", "");
  assert.equal(forged.status, 200);          // signed by the real account key: allowed
  const wrongKey = await keypair();
  const time = Date.now();
  const bad = await worker.fetch(new Request("https://sync.example/v1/devices", {
    method: "POST", body: JSON.stringify({ account_key: account.pubB64, device_key: wrongKey.pubB64, name: "x", time,
      signature: await sign(wrongKey, `register\n${account.id}\n${wrongKey.pubB64}\nx\n${time}`) }),
  }), e);
  assert.equal(bad.status, 401);
  assert.equal((await register(env({ OPEN_SIGNUP: "true" }), account, laptop, "laptop", "")).status, 200);
});

test("chat history is stored as the device's own encrypted bytes, for that account only", async () => {
  const e = env();
  const [account, laptop, phone] = [await keypair(), await keypair(), await keypair()];
  await register(e, account, laptop);
  await register(e, account, phone, "phone");
  const sealed = new Uint8Array([1, 2, 3, 250]);
  assert.equal((await call(e, "PUT", "/v1/history/2026-10-01-laptop.bin", account, laptop, sealed)).status, 200);
  const listing = await (await call(e, "GET", "/v1/history", account, phone)).json();
  assert.deepEqual(listing.history, [{ name: "2026-10-01-laptop.bin", bytes: 4 }]);
  const back = await call(e, "GET", "/v1/history/2026-10-01-laptop.bin", account, phone);
  assert.deepEqual(new Uint8Array(await back.arrayBuffer()), sealed);

  const other = [await keypair(), await keypair()];
  await register(e, other[0], other[1]);
  assert.deepEqual((await (await call(e, "GET", "/v1/history", other[0], other[1])).json()).history, []);

  assert.equal((await call(e, "DELETE", `/v1/devices/${laptop.id}`, account, phone)).status, 200);
  assert.equal((await call(e, "GET", "/v1/history", account, laptop)).status, 403);           // removed
  assert.equal((await call(e, "GET", "/v1/history", account, phone, new Uint8Array(), Date.now() - 600_000)).status, 401);
  const devices = (await (await call(e, "GET", "/v1/devices", account, phone)).json()).devices;
  assert.deepEqual(devices.map((d) => [d.name, d.removed]).sort(), [["laptop", true], ["phone", false]]);
});

test("public research records grow a shared corpus anyone can read, cached by Cloudflare", async () => {
  const e = env();
  const [account, device] = [await keypair(), await keypair()];
  await register(e, account, device);
  const record = { source: "pubmed", external_id: "1", title: "Base editing", abstract: "A trial.", source_url: "https://pubmed.ncbi.nlm.nih.gov/1/", published_at: "2026", extra: "dropped" };
  const sent = await call(e, "POST", "/v1/corpus", account, device, JSON.stringify({ records: [record] }));
  assert.equal(sent.status, 200);
  const list = await worker.fetch(new Request("https://sync.example/v1/corpus/batches"), e);
  assert.equal(list.headers.get("Cache-Control"), "public, max-age=60");
  const [name] = (await list.json()).batches;
  const batch = await worker.fetch(new Request(`https://sync.example/v1/corpus/batches/${name}`), e);
  assert.match(batch.headers.get("Cache-Control"), /immutable/);
  assert.equal((await batch.json()).records[0].extra, undefined);
  assert.throws(() => cleanRecords([{ ...record, source_url: "http://not-https" }]));
  assert.equal((await call(e, "POST", "/v1/corpus", account, device, JSON.stringify({ records: [] }))).status, 400);
});

test("shared training answers carry no account, and only the owner can export them", async () => {
  const e = env();
  const [owner, ownerDevice, someone, theirDevice] = [await keypair(), await keypair(), await keypair(), await keypair()];
  await register(e, owner, ownerDevice);
  await register(e, someone, theirDevice);
  e.ADMIN_ACCOUNT = owner.id;
  const shared = await call(e, "POST", "/v1/training", someone, theirDevice,
    JSON.stringify({ question: "What is HBB?", answer: "The beta-globin gene.", rating: 1, model: "rabbitsoftware" }));
  assert.equal(shared.status, 200);
  const [key] = [...e.SYNC.objects.keys()].filter((k) => k.startsWith("training/"));
  const stored = JSON.parse(new TextDecoder().decode(e.SYNC.objects.get(key)));
  assert.equal(JSON.stringify(stored).includes(someone.id), false);
  assert.equal((await call(e, "GET", "/v1/admin/training", someone, theirDevice)).status, 403);
  const exported = await (await call(e, "GET", "/v1/admin/training", owner, ownerDevice)).json();
  assert.equal(exported.items[0].question, "What is HBB?");
  assert.equal((await call(e, "POST", "/v1/training", someone, theirDevice, JSON.stringify({ question: "x", answer: "y", rating: 5 }))).status, 400);
});

test("each account has daily limits", async () => {
  const e = env({ QUOTAS: '{"training": 2}' });
  const [account, device] = [await keypair(), await keypair()];
  await register(e, account, device);
  const share = () => call(e, "POST", "/v1/training", account, device, JSON.stringify({ question: "q", answer: "a" }));
  assert.equal((await share()).status, 200);
  assert.equal((await share()).status, 200);
  assert.equal((await share()).status, 429);
});

test("a pairing slot gives out only the sealed secret, five tries within ten minutes", async () => {
  const e = env();
  const [account, device] = [await keypair(), await keypair()];
  await register(e, account, device);
  assert.equal((await call(e, "POST", "/v1/pairing", account, device, JSON.stringify({ slot: "ABCD", sealed: "c2VhbGVk" }))).status, 200);
  assert.equal((await call(e, "POST", "/v1/pairing", account, device, JSON.stringify({ slot: "ABCD", sealed: "x" }))).status, 409);
  for (let i = 0; i < 5; i++) {
    const got = await worker.fetch(new Request("https://sync.example/v1/pairing/ABCD"), e);
    assert.deepEqual(await got.json(), { sealed: "c2VhbGVk" });
  }
  assert.equal((await worker.fetch(new Request("https://sync.example/v1/pairing/ABCD"), e)).status, 404);
  assert.equal(e.SYNC.objects.has("pairing/ABCD.json"), false);
});
