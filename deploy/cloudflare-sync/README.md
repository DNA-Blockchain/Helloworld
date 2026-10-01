# RabbitSoftware.inc sync service (Cloudflare Worker + R2 + D1)

This service lets one account's devices share what RabbitSoftware.inc knows, and lets the model grow from
answers people choose to share. The client is `rabbitsoft/sync.py`. In chat the commands are "create an
account", "add a device", "sync now", and so on. The owner's commands are `python rabbit.py training …`.

- **Live:** https://rabbitsoftware-sync.rabbitsoftware-gateway.workers.dev
- **Blobs:** R2 bucket `rabbitsoftware-sync` (free tier: 10 GB).
- **SQL:** D1 database `rabbitsoftware-sync` (SQLite), with its schema in `migrations/`.

## What's stored, and who can read it

| Where | Contents | Readable by |
|---|---|---|
| R2 `accounts/<id>/account.json` | the account's public key | the service |
| R2 `accounts/<id>/devices/<id>.json` | each device's public key, name, removed flag | that account's devices |
| R2 `accounts/<id>/history/<device>.bin` | chat history, **encrypted on the device** (AES-256-GCM) | only that account's devices; the service sees scrambled bytes |
| R2 `corpus/batches/<name>.json` | public research records from every device | anyone; cached by Cloudflare (list 60 s, batches permanently) |
| R2 `pairing/<slot>.json` | a sealed account secret for adding a device | anyone with the code, 5 tries within 10 minutes; R2 deletes these after a day |
| D1 `corpus_records` | every public record once (deduplicated across batches) | anyone, through `GET /v1/corpus/search` and `/v1/corpus/stats` |
| D1 `training_answers` | answers people chose to share, with **no account or device**, plus review status (pending, approved, rejected) and the export that carried each one | only the owner's account (`ADMIN_ACCOUNT`) |
| D1 `exports` | each export to the private HF dataset `rabbitsoftware-training`: file, rows, SHA-256, HF commit | only the owner's account |

### Why both

- **R2** holds blobs: encrypted files the service can't read, and immutable cached batches.
- **D1** holds what needs queries: review queues, deduplication, search, and export bookkeeping where each answer is exported exactly once (the export row and the "exported" marks are written in one transaction).

Bulk writes are single set-based statements (`json_each`), so a 200-record batch is one query, well inside D1's per-request limits.

## Who can ask

- Every private request is signed by a registered device (Ed25519), with the time. That makes replays fail, and a removed device is cut off.
- A device joins only with a signature from the account key, which comes from the recovery phrase or a pairing code.
- New accounts need `SIGNUP_KEY` until `OPEN_SIGNUP` is `"true"`, at the public launch.
- Each account has daily limits, set in `QUOTAS` (history 500, corpus 50, training 300, pairing 20). Requests are capped at 1 MB.
- `/v1/admin/*` (review, export, stats) answers only `ADMIN_ACCOUNT`.

## Settings and secrets

| Name | Kind | Meaning |
|---|---|---|
| `OPEN_SIGNUP` | var | `"false"` until launch |
| `QUOTAS` | var | daily limits per account |
| `SIGNUP_KEY` | secret | random key; the owner's copy is in `autonomous/rabbit/signup.key` (never committed) |
| `ADMIN_ACCOUNT` | secret | the owner's account ID (`python rabbit.py account` shows it); a secret so it isn't published in this repo |
| `DB` | D1 binding | database `rabbitsoftware-sync` |

To set a secret without a stray line ending, use bash:
`printf '%s' "$(tr -d '\r\n' < ../../autonomous/rabbit/signup.key)" | npx wrangler secret put SIGNUP_KEY`.
A PowerShell pipe adds `\r\n`, which makes the key not match.

R2 bucket settings: lifecycle rule `pairing-cleanup` (prefix `pairing/`, expire after 1 day). There's no
public bucket access and no S3 API token: only this Worker touches the bucket, through its binding.

## Change or redeploy

```sh
cd deploy/cloudflare-sync
node --test test/sync.test.mjs                                  # real Worker code; real SQLite in place of D1
npx wrangler d1 migrations apply rabbitsoftware-sync --remote   # schema changes first (new files in migrations/)
npx wrangler deploy
```

- **Local server:** `test/local_server.mjs` serves the real Worker code on localhost, with SQLite and the real migrations in place of D1. `tests/test_sync_client.py`, `tests/test_training_export.py` and `tests/test_api_contracts.py` use it to test the Python side end to end.
- **Schema changes:** only add new numbered files to `migrations/`; never edit one that's been applied.
