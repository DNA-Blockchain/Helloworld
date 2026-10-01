// Runs the Worker's real code against a fake Hugging Face endpoint: node --test deploy/cloudflare/test/
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import worker, { Limits, cleanRequest } from "../src/index.js";

function fakeEnv(overrides = {}) {
  const store = new Map();
  const limits = new Limits({ storage: { get: async (k) => store.get(k), put: async (k, v) => store.set(k, v) } }, {});
  return {
    ENDPOINT_URL: "https://endpoint.example",
    HF_TOKEN: "secret",
    PER_CLIENT_PER_HOUR: "2",
    DAILY_LIMIT: "3",
    LIMITS: { idFromName: (name) => name, get: () => ({ fetch: (url, init) => limits.fetch(new Request(url, init)) }) },
    ...overrides,
  };
}

const sent = [];
const realFetch = globalThis.fetch;
function fakeEndpoint(status = 200) {
  globalThis.fetch = async (url, init) => {
    sent.push({ url, auth: init.headers.Authorization, body: JSON.parse(init.body) });
    if (status !== 200) return new Response("busy", { status });
    return Response.json({ choices: [{ message: { content: "Answer from the endpoint." } }] });
  };
}
afterEach(() => {
  globalThis.fetch = realFetch;
  sent.length = 0;
});

function ask(env, text, ip = "203.0.113.5") {
  return worker.fetch(new Request("https://gateway.example/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": ip },
    body: JSON.stringify({ model: "anything", messages: [{ role: "user", content: text }], max_tokens: 5000, tools: ["x"] }),
  }), env);
}

test("only the messages and a capped length go on", () => {
  assert.deepEqual(cleanRequest({ messages: [{ role: "user", content: "hi", x: 1 }], max_tokens: 9999, temperature: 9 }, 100, 400),
    { model: "rabbitsoftware", messages: [{ role: "user", content: "hi" }], max_tokens: 400, temperature: 1.5, stream: false });
  for (const bad of [{}, { messages: [] }, { messages: [{ role: "tool", content: "x" }] }, { messages: [{ role: "user", content: "x".repeat(101) }] }]) {
    assert.throws(() => cleanRequest(bad, 100, 400));
  }
});

test("a question reaches the endpoint with the secret token, and the answer comes back", async () => {
  fakeEndpoint();
  const response = await ask(fakeEnv(), "What is base editing?");
  assert.equal(response.status, 200);
  assert.equal((await response.json()).choices[0].message.content, "Answer from the endpoint.");
  assert.equal(sent[0].url, "https://endpoint.example/v1/chat/completions");
  assert.equal(sent[0].auth, "Bearer secret");
  assert.equal(sent[0].body.max_tokens, 400);
  assert.equal(sent[0].body.tools, undefined);
});

test("each person and each day are limited", async () => {
  fakeEndpoint();
  const env = fakeEnv();
  assert.equal((await ask(env, "1")).status, 200);
  assert.equal((await ask(env, "2")).status, 200);
  const third = await ask(env, "3");
  assert.equal(third.status, 429);
  assert.match((await third.json()).error, /too many questions this hour/);
  assert.equal((await ask(env, "4", "198.51.100.7")).status, 200);       // someone else still can
  const capped = await ask(env, "5", "192.0.2.9");
  assert.equal(capped.status, 429);
  assert.match((await capped.json()).error, /all the questions it can today/);
  assert.equal(sent.length, 3);
});

test("a sleeping endpoint is reported as 503 so the client says it's starting", async () => {
  fakeEndpoint(503);
  const response = await ask(fakeEnv(), "wake up");
  assert.equal(response.status, 503);
});

test("bad requests and other paths are refused without reaching the endpoint", async () => {
  fakeEndpoint();
  const env = fakeEnv();
  const notJson = await worker.fetch(new Request("https://g.example/v1/chat/completions", { method: "POST", body: "{" }), env);
  assert.equal(notJson.status, 400);
  assert.equal((await worker.fetch(new Request("https://g.example/other", { method: "POST", body: "{}" }), env)).status, 404);
  assert.equal((await worker.fetch(new Request("https://g.example/health"), env)).status, 200);
  assert.equal((await ask(fakeEnv({ HF_TOKEN: "" }), "hi")).status, 503);
  assert.equal(sent.length, 0);
});
