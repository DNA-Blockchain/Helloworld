# Model API v1

The OpenAI-compatible subset used between `hosted_ai.py` (RabbitSoftware.inc), the gateway
(`deploy/cloudflare`, or `deploy/gateway` as a Hugging Face Space) and the model endpoint (llama.cpp on
Hugging Face). Schema: [`rabbitsoftware-model-api-v1`](../../schemas/rabbitsoftware-model-api-v1.schema.json).

`POST /v1/chat/completions`

| Definition | Shape |
|---|---|
| `chatRequest` | `{"messages": [{"role": "system"\|"user"\|"assistant", "content": "..."}], "max_tokens", "temperature", "model", "stream": false}`: 1 to 8 messages |
| `chatResponse` | `{"choices": [{"message": {"content": "..."}}]}`; readers use `choices[0].message.content` |
| `error` | `{"error": "..."}` |

**What the gateway does with a request:**
- It keeps only the messages and a capped answer length.
- It forces the model name to `rabbitsoftware`.
- It enforces the limits: 20 questions per person per hour, 500 a day for everyone, questions up to 12,000 characters, answers up to 400 tokens.

**Errors:**

| HTTP | Meaning |
|---|---|
| 400 | bad request |
| 413 | too long |
| 429 | over a limit |
| 503 | the model is waking up; RabbitSoftware.inc says to try again in a minute |

RabbitSoftware.inc asks the user before **every** question it sends here.
