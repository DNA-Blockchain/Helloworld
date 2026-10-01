# OS shell API v1

`GET /api/v1/shell` on the local app server (see [app.md](app.md) for the headers) returns one
read-only snapshot for the desktop shell's status screens. It's built by `rabbitsoft/shell_api.py` from
files the OS already writes, and it changes nothing.
Schema: [`rabbitsoftware-shell-api-v1`](../../schemas/rabbitsoftware-shell-api-v1.schema.json).

```json
{
  "schema": "rabbitsoft-shell.v1",
  "version": "0.9.0",
  "nodes": [{"id": "node-0", "chain_blocks": 800, "chain_ok": true, "connected_peers": [1, 2], "updated_at": 1790821897.7}],
  "jobs": [{"name": "The integrity check", "running": false, "summary": "Everything checks out."}],
  "ai": {"model_server": "https://...", "account": true},
  "integrity": {"created_at": "2026-10-01T08:00:00+00:00", "ok": true}
}
```

- **`model_server`** is `null` when no model server is set.
- **`integrity`** is `null` before the first integrity report.
- **`jobs`** lists the last 10 background jobs.
