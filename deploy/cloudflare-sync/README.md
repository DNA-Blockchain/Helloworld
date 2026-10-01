# RabbitSoftware.inc sync service (Cloudflare Worker + R2)

Lets one account's devices share what RabbitSoftware.inc knows, and lets the model grow from answers
people choose to share. The client is `rabbitsoft/sync.py`; in chat it's "create an account", "add a
device", "sync now", and so on.

- **Live:** https://rabbitsoftware-sync.rabbitsoftware-gateway.workers.dev
- **Bucket:** R2 `rabbitsoftware-sync`, on the free tier of 10 GB.

## What's stored, and who can read it

| R2 path | Contents | Readable by |
|---|---|---|
| `accounts/<id>/account.json` | the account's public key | the service |
| `accounts/<id>/devices/<id>.json` | each device's public key, name, removed flag | that account's devices |
| `accounts/<id>/history/<device>.bin` | chat history, **encrypted on the device** (AES-256-GCM) | only that account's devices; the service sees scrambled bytes |
| `corpus/batches/<name>.json` | public research records from every device | anyone; cached by Cloudflare (list 60 s, batches permanently) |
| `training/<day>/<id>.json` | answers people chose to share, with **no account or device** | only the owner's account (`ADMIN_ACCOUNT`), for export to the private HF dataset `rabbitsoftware-training` |
| `pairing/<slot>.json` | a sealed account secret for adding a device | anyone with the code, 5 tries within 10 minutes; R2 deletes these after a day |

## Who can ask

- Every private request is signed by a registered device (Ed25519), with the time. That makes replays fail, and a removed device is cut off.
- A device joins only with a signature from the account key, which comes from the recovery phrase or a pairing code.
- New accounts need `SIGNUP_KEY` until `OPEN_SIGNUP` is `"true"`, at the public launch.
- Each account has daily limits, set in `QUOTAS` (history 500, corpus 50, training 300, pairing 20). Requests are capped at 1 MB.

## Settings and secrets

| Name | Kind | Meaning |
|---|---|---|
| `OPEN_SIGNUP` | var | `"false"` until launch |
| `ADMIN_ACCOUNT` | var | the owner's account ID (`rabbit account` shows it); empty until the owner's account exists |
| `QUOTAS` | var | daily limits per account |
| `SIGNUP_KEY` | secret | random key; the owner's copy is in `autonomous/rabbit/signup.key` (never committed) |

To set the secret without a stray line ending, use bash:
`printf '%s' "$(tr -d '\r\n' < ../../autonomous/rabbit/signup.key)" | npx wrangler secret put SIGNUP_KEY`.
A PowerShell pipe adds `\r\n`, which makes the key not match.

R2 bucket settings: lifecycle rule `pairing-cleanup` (prefix `pairing/`, expire after 1 day). There are
no public bucket access and no S3 API tokens: only this Worker touches the bucket, through its binding.

## Change or redeploy

```sh
cd deploy/cloudflare-sync
node --test test/sync.test.mjs        # the Worker's real code against an in-memory bucket
npx wrangler deploy
```

`test/local_server.mjs` serves the real Worker code on localhost, so `tests/test_sync_client.py` can test
the Python client end to end.
