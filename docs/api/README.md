# RabbitSoftware APIs

RabbitSoftware is built from parts that talk to each other: the OS and its nodes, RabbitSoftware.inc, the
hosted model, the sync service and the user interfaces. Each connection between them is a documented,
versioned API. Its exact shape is a JSON Schema in [`schemas/`](../../schemas/), and
[`tests/test_api_contracts.py`](../../tests/test_api_contracts.py) checks real messages from each part
against it. So a change that would break another part fails the tests before it can be merged.

| API | Between | Schema | Page |
|---|---|---|---|
| Local app API v1 | user interfaces ↔ RabbitSoftware.inc | `rabbitsoftware-app-api-v1` | [app.md](app.md) |
| OS shell API v1 | desktop shell ← RabbitSoftware.inc | `rabbitsoftware-shell-api-v1` | [shell.md](shell.md) |
| Node API v1 | nodes → everything that reads them | `rabbitsoftware-node-api-v1` | [node.md](node.md) |
| Model API v1 | RabbitSoftware.inc ↔ gateway ↔ model | `rabbitsoftware-model-api-v1` | [model.md](model.md) |
| Sync API v1 | devices ↔ sync service | `rabbitsoftware-sync-api-v1` | [sync.md](sync.md) |
| Integrity v1 | integrity team → reports and readers | `rabbitsoftware-integrity-v1` | [integrity.md](integrity.md) |
| Pipeline report v1 | every pipeline store → reports, chat, dashboards | `rabbitsoftware-pipeline-report-v1` | [pipeline-report.md](pipeline-report.md) |

Check a message from code:

```python
from rabbitsoft import contracts
contracts.validate(reply, "app-api-v1", "messageReply")   # raises ValueError saying what's wrong
contracts.errors(reply, "app-api-v1", "messageReply")     # or just list the problems
```

## How an API changes

- **Adding** a field to a reply, an optional field to a request, or a new route stays in v1. It's a MINOR release. Readers must ignore fields they don't know.
- **Breaking** means renaming or removing a field, changing a type, making an optional field required, or changing a route's meaning. That needs a new `-v2` schema file alongside v1, a new route prefix (`/api/v2/`), and a MAJOR release. The v1 version keeps working until a release note says when it ends.
- Every change updates the schema, this folder and `CHANGELOG.md` in the same PR.
