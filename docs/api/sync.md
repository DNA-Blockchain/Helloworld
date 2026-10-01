# Sync API v1

Between `rabbitsoft/sync.py` on each device and the sync service (`deploy/cloudflare-sync`, Cloudflare
Workers + R2 + D1). Schema: [`rabbitsoftware-sync-api-v1`](../../schemas/rabbitsoftware-sync-api-v1.schema.json).

## Signing

Private routes are signed by a registered device:

| Header | Value |
|---|---|
| `X-Account`, `X-Device` | 32 hex characters each |
| `X-Time` | milliseconds since 1970; must be within 5 minutes of the service's clock |
| `X-Signature` | base64 Ed25519 signature, by the device key, of `METHOD\nPATH\nTIME\nSHA256-HEX-OF-BODY` |

## Routes

| Route | Signed | Request | Reply |
|---|---|---|---|
| `GET /health` | no | — | `{"service", "ok"}` |
| `POST /v1/devices` | by the **account key**, in the body (+ `X-Signup-Key` for new accounts until launch) | `registerRequest` | `registerReply` |
| `GET /v1/devices` | yes | — | `devicesReply` |
| `DELETE /v1/devices/{id}` | yes | — | `{"removed": id}` |
| `PUT /v1/history/{name}` | yes | encrypted bytes (AES-256-GCM, made on the device) | `{"stored", "bytes"}` |
| `GET /v1/history` | yes | — | `historyList` |
| `GET /v1/history/{name}` | yes | — | the encrypted bytes |
| `POST /v1/corpus` | yes | `corpusUpload` (1 to 200 public `record`s, https links) | `corpusUploadReply` |
| `GET /v1/corpus/batches` | no; cached for 60 s | — | `corpusBatchList` |
| `GET /v1/corpus/batches/{name}` | no; cached permanently | — | `corpusBatch` |
| `POST /v1/training` | yes | `trainingItem` (stored with no account or device) | `{"shared": true}` |
| `POST /v1/pairing` | yes | `pairingCreate` | `pairingCreated` (10 minutes) |
| `GET /v1/pairing/{slot}` | no; 5 tries | — | `pairingSlot` (only the sealed secret) |
| `GET /v1/corpus/search?q=&limit=` | no; cached for 60 s | — | `corpusSearchReply` (every word in the title or abstract; up to 50) |
| `GET /v1/corpus/stats` | no; cached for 60 s | — | `corpusStats` |
| `GET /v1/admin/training?status=&limit=` | yes, owner's account only | — | `trainingList` (pending, approved, rejected or all) |
| `POST /v1/admin/training/review` | yes, owner's account only | `trainingReview` | `trainingReviewReply` |
| `GET /v1/admin/training/export?limit=` | yes, owner's account only | — | `trainingList` (not yet exported, not rejected) |
| `POST /v1/admin/training/exported` | yes, owner's account only | `trainingExported` (after the file is on Hugging Face) | `trainingExportedReply`; 409 if the file is already recorded |
| `GET /v1/admin/stats` | yes, owner's account only | — | `adminStats` |

## Errors

Errors come as `error` (`{"error": "..."}`):

| HTTP | Meaning |
|---|---|
| 401 | unsigned, wrong signature, or clock off |
| 403 | not part of the account, sign-up closed, or not the owner |
| 409 | slot taken, too many devices, or an export file already recorded |
| 413 | over 1 MB |
| 429 | over a daily limit |
