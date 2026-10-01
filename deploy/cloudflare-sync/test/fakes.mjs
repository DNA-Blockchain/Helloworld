// In-memory stand-ins for R2 and the Quota Durable Object, shared by the Node tests and local_server.mjs.
import { Quota } from "../src/index.js";

export class FakeBucket {
  constructor() {
    this.objects = new Map();
  }
  async put(key, value) {
    const bytes = typeof value === "string" ? new TextEncoder().encode(value) : new Uint8Array(value);
    this.objects.set(key, bytes);
  }
  async get(key) {
    const bytes = this.objects.get(key);
    if (!bytes) return null;
    return { body: bytes, size: bytes.length, json: async () => JSON.parse(new TextDecoder().decode(bytes)) };
  }
  async head(key) {
    return this.objects.has(key) ? { size: this.objects.get(key).length } : null;
  }
  async delete(key) {
    this.objects.delete(key);
  }
  async list({ prefix }) {
    const objects = [...this.objects.keys()].filter((k) => k.startsWith(prefix)).sort()
      .map((key) => ({ key, size: this.objects.get(key).length }));
    return { objects, truncated: false };
  }
}

export function fakeEnv(overrides = {}) {
  const store = new Map();
  const quota = new Quota({ storage: { get: async (k) => store.get(k), put: async (k, v) => store.set(k, v) } });
  return {
    SYNC: new FakeBucket(), OPEN_SIGNUP: "false", SIGNUP_KEY: "letmein", ADMIN_ACCOUNT: "", QUOTAS: "{}",
    QUOTA: { idFromName: (n) => n, get: () => ({ fetch: (url, init) => quota.fetch(new Request(url, init)) }) },
    ...overrides,
  };
}
