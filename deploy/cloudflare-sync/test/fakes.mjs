// In-memory stand-ins for R2, D1 and the Quota Durable Object, shared by the Node tests and local_server.mjs.
// The D1 stand-in is real SQLite (node:sqlite) with the real migrations applied, so the SQL is tested as written.
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

import { Quota } from "../src/index.js";

const MIGRATIONS = new URL("../migrations/", import.meta.url);

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

class FakeStatement {
  constructor(db, sql, params = []) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }
  bind(...params) {
    return new FakeStatement(this.db, this.sql, params);
  }
  async all() {
    return { success: true, results: this.db.prepare(this.sql).all(...this.params).map((r) => ({ ...r })), meta: {} };
  }
  async first() {
    return (await this.all()).results[0] ?? null;
  }
  async run() {
    const info = this.db.prepare(this.sql).run(...this.params);
    return { success: true, results: [], meta: { changes: Number(info.changes) } };
  }
  execute() {                                           // what a batch runs: rows for SELECTs, changes otherwise
    const statement = this.db.prepare(this.sql);
    if (/^\s*select/i.test(this.sql)) return { success: true, results: statement.all(...this.params).map((r) => ({ ...r })), meta: {} };
    return { success: true, results: [], meta: { changes: Number(statement.run(...this.params).changes) } };
  }
}

export class FakeD1 {
  constructor() {
    this.db = new DatabaseSync(":memory:");
    this.db.exec("PRAGMA foreign_keys = ON");          // as D1 does
    for (const file of readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort()) {
      this.db.exec(readFileSync(new URL(file, MIGRATIONS), "utf8"));
    }
  }
  prepare(sql) {
    return new FakeStatement(this.db, sql);
  }
  async batch(statements) {                             // D1 runs a batch as one transaction
    this.db.exec("BEGIN");
    try {
      const results = statements.map((s) => s.execute());
      this.db.exec("COMMIT");
      return results;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
}

export function fakeEnv(overrides = {}) {
  const store = new Map();
  const quota = new Quota({ storage: { get: async (k) => store.get(k), put: async (k, v) => store.set(k, v) } });
  return {
    SYNC: new FakeBucket(), DB: new FakeD1(), OPEN_SIGNUP: "false", SIGNUP_KEY: "letmein", ADMIN_ACCOUNT: "", QUOTAS: "{}",
    QUOTA: { idFromName: (n) => n, get: () => ({ fetch: (url, init) => quota.fetch(new Request(url, init)) }) },
    ...overrides,
  };
}
