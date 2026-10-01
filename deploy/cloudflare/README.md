# RabbitSoftware.inc model gateway (Cloudflare Worker)

The public front door to the hosted model. Downloads of RabbitSoftware.inc send questions here, never
straight to the Hugging Face endpoint, because the endpoint needs an access token that must never ship
in a download.

- **Live:** https://rabbitsoftware-gateway.rabbitsoftware-gateway.workers.dev. It's unadvertised until launch, and installers don't point at it yet.
- **Forwards to:** the private Hugging Face Inference Endpoint `rabbitsoftware-model` (llama.cpp, one T4, sleeps after 15 quiet minutes).
- **API:** OpenAI-compatible, `POST /v1/chat/completions`, plus `GET /health`.

## What it enforces

| Rule | Setting (`wrangler.toml` `[vars]`) |
|---|---|
| Questions per person per hour | `PER_CLIENT_PER_HOUR` (20) |
| Questions per day, everyone together: the spending cap | `DAILY_LIMIT` (500) |
| Longest question / longest answer | `MAX_PROMPT_CHARS` (12000) / `MAX_TOKENS` (400) |
| Where to forward | `ENDPOINT_URL` |

- **Who's asking:** people are told apart by a SHA-256 of their network address, kept only in memory.
- **What's stored:** only the day's question count, in the `Limits` Durable Object. Questions and answers are never written down.
- **A sleeping endpoint:** its "starting" reply is passed on as HTTP 503, and RabbitSoftware.inc says to try again in a minute.

## Secrets

| Secret | What it is |
|---|---|
| `HF_TOKEN` | A fine-grained Hugging Face token allowed only to call Inference Endpoints. Set by the owner with `npx wrangler secret put HF_TOKEN`; never in this folder. |

## Change or redeploy

```sh
cd deploy/cloudflare
node --test test/gateway.test.mjs     # the Worker's real code against a fake endpoint
npx wrangler deploy                   # publish; settings take effect immediately
```

The same rules also exist as a Hugging Face Space (`deploy/gateway/`), which needs a PRO plan.
