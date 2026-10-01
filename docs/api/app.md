# Local app API v1

Between a user interface on this PC (the web page now; the RabbitSoftware.inc app and the OS shell
later) and RabbitSoftware.inc. Served by `rabbitsoft/web.py` on **http://127.0.0.1:8792** only.
Schema: [`rabbitsoftware-app-api-v1`](../../schemas/rabbitsoftware-app-api-v1.schema.json).

Every request needs the header `X-Rabbit: 1` and a `Host` of `127.0.0.1` or `localhost`. Together these
stop other websites open in the same browser from using it.

| Route | Request | Reply |
|---|---|---|
| `POST /api/v1/message` | `messageRequest`: `{"session": "<uuid>", "text": "..."}` | `messageReply`: `{"text", "choices": [...], "confirm": bool}` |
| `POST /api/v1/poll` | `messageRequest` (text ignored) | `pollReply`: `{"text"}`; empty means nothing new |
| `GET /api/v1/status` | — | `statusReply`: `{"nodes", "chain"}`, one sentence each |
| `GET /api/v1/shell` | — | see [shell.md](shell.md) |

- **Sessions:** use one session (a UUID) per browser tab.
- **`choices`:** show them as numbered buttons; sending the number picks one.
- **`confirm`:** when it's true, the next message should be yes or no. Nothing that changes anything or sends data off the PC happens without that yes.
- **Errors:** they come as `error` (`{"error": "..."}`) with HTTP 400, 403 or 404.
- **Old routes:** `/api/message`, `/api/poll` and `/api/status` still work as aliases.
