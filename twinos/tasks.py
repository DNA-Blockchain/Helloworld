"""Tasks: what each one needs, the receiver's policy, and the queue of tasks waiting for the owner.

A task is built by the receiver from only its type, description and parameters. Fields a sender might
add (an approval flag, a status) are ignored, so a peer can't approve its own request.

Each task type needs one capability. The policy lists the capabilities this agent may use without
asking; every other task waits in the queue until the owner approves or denies it
(python -m twinos approve|deny). Some capabilities can never run without approval, whatever the
policy file says: running code, terminal commands, writing files, network operations, MicroPython
devices and GPU jobs.

Stored in autonomous/twinos/policy.json and autonomous/twinos/tasks.json.
"""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from atomic_io import replace_with_retry

from .locking import locked
from .protocol import canonical

TASKS = {
    "status": "read_context", "update_context": "write_context", "generate_code": "generate_code",
    "review_code": "review_code", "run_tests": "run_tests", "run_code": "run_code",
    "terminal_command": "terminal", "read_file": "file_read", "write_file": "file_write",
    "network_operation": "network", "micropython_command": "micropython", "gpu_training": "gpu_compute",
}
NEVER_AUTOMATIC = frozenset({"run_code", "terminal", "file_write", "network", "micropython", "gpu_compute"})
DEFAULT_AUTOMATIC = ("read_context",)
MAX_DESCRIPTION = 2000
MAX_PARAMETERS = 16 * 1024           # bytes of canonical JSON
MAX_WAITING_PER_PEER = 100
MAX_KEPT = 1000                      # finished tasks beyond this are dropped, oldest first


class TaskRejected(ValueError):
    """A request that can't become a task; the text is safe to send back."""


class Policy:
    def __init__(self, path: Path):
        self.path = path
        try:
            automatic = json.loads(path.read_text(encoding="utf-8")).get("automatic", list(DEFAULT_AUTOMATIC))
        except FileNotFoundError:
            automatic = list(DEFAULT_AUTOMATIC)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"automatic": automatic}, indent=2), encoding="utf-8")
        known = set(TASKS.values())
        self.ignored = sorted(c for c in automatic if c in NEVER_AUTOMATIC or c not in known)
        self.automatic = frozenset(c for c in automatic if c in known and c not in NEVER_AUTOMATIC)

    def allows(self, capability: str) -> bool:
        return capability in self.automatic


@dataclass
class Task:
    task_id: str
    task_type: str
    capability: str
    description: str
    parameters: dict
    source_agent: str
    source_message_id: str
    status: str = "waiting_approval"    # waiting_approval | approved | denied | completed | failed
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    result: dict | None = None


def build_task(task_type, description, parameters, source_agent: str, source_message_id: str) -> Task:
    if not isinstance(task_type, str) or task_type not in TASKS:
        raise TaskRejected(f"unsupported task type {task_type!r}")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION:
        raise TaskRejected(f"description must be text of at most {MAX_DESCRIPTION} characters")
    if not isinstance(parameters, dict) or len(canonical(parameters)) > MAX_PARAMETERS:
        raise TaskRejected(f"parameters must be an object of at most {MAX_PARAMETERS} bytes")
    return Task(task_id="task-" + secrets.token_hex(8), task_type=task_type, capability=TASKS[task_type],
                description=description, parameters=parameters, source_agent=source_agent,
                source_message_id=source_message_id)


class TaskQueue:
    """The task file, re-read under a lock for every change, since the server and the owner's commands
    are separate processes."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, Task]:
        try:
            return {t["task_id"]: Task(**t) for t in json.loads(self.path.read_text(encoding="utf-8"))}
        except FileNotFoundError:
            return {}

    def _save(self, tasks: dict[str, Task]) -> None:
        finished = sorted((t for t in tasks.values() if t.status in ("denied", "completed", "failed")),
                          key=lambda t: t.created_at)
        for old in finished[:max(0, len(tasks) - MAX_KEPT)]:
            del tasks[old.task_id]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(t) for t in tasks.values()], indent=2), encoding="utf-8")
        replace_with_retry(str(temporary), str(self.path))

    def add(self, task: Task) -> Task:
        with locked(self.path):
            tasks = self._load()
            if any(t.source_message_id == task.source_message_id for t in tasks.values()):
                raise TaskRejected("a task from this message already exists (replay)")
            waiting = sum(1 for t in tasks.values()
                          if t.source_agent == task.source_agent and t.status == "waiting_approval")
            if waiting >= MAX_WAITING_PER_PEER:
                raise TaskRejected(f"this agent already has {waiting} tasks waiting for approval")
            tasks[task.task_id] = task
            self._save(tasks)
        return task

    def get(self, task_id: str) -> Task | None:
        return self._load().get(task_id)

    def all(self) -> list[Task]:
        return sorted(self._load().values(), key=lambda t: t.created_at)

    def waiting(self) -> list[Task]:
        return [t for t in self.all() if t.status == "waiting_approval"]

    def decide(self, task_id: str, approve: bool) -> Task:
        with locked(self.path):
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None:
                raise KeyError(f"no task {task_id}")
            if task.status != "waiting_approval":
                raise ValueError(f"{task_id} is already {task.status}")
            task.status, task.decided_at = ("approved" if approve else "denied"), time.time()
            self._save(tasks)
        return task

    def finish(self, task_id: str, result: dict) -> Task:
        with locked(self.path):
            tasks = self._load()
            task = tasks[task_id]
            task.status = "completed" if result.get("success") else "failed"
            task.result = result
            self._save(tasks)
        return task
