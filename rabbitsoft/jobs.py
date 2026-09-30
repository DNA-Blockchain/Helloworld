"""Long tasks RabbitSoftware.inc starts: one-off jobs (the self-tests) and a service (the research agent).

A job runs in the background with its output in a log file, so the conversation carries on; the next
reply mentions it when it finishes. The research agent is a service: it keeps running after the
assistant closes, and a pid file records which process it is. Before stopping a process, its command
line is checked, so a reused process id can never stop something else.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Job:
    name: str
    log: Path
    started: float = field(default_factory=time.time)
    finished: float | None = None
    exit_code: int | None = None
    summary: str = ""
    reported: bool = False

    def describe(self) -> str:
        if self.finished is None:
            return f"{self.name}: running for {time.time() - self.started:.0f} seconds."
        return f"{self.name}: finished. {self.summary}"


class Jobs:
    def __init__(self, folder: Path):
        self.folder = folder
        self.items: list[Job] = []
        self.lock = threading.Lock()

    def start(self, name: str, command: list[str], cwd: Path,
              summarize: Callable[[Job], str] = lambda job: f"Exit code {job.exit_code}.") -> Job:
        self.folder.mkdir(parents=True, exist_ok=True)
        job = Job(name, self.folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{name.replace(' ', '-')}.log")
        out = open(job.log, "w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(command, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   creationflags=NO_WINDOW, env={**os.environ, "PYTHONIOENCODING": "utf-8"})

        def wait():
            job.exit_code = process.wait()
            out.close()
            try:
                job.summary = summarize(job)
            except Exception as error:          # a summary that fails must not hide that the job finished
                job.summary = f"Exit code {job.exit_code} (couldn't summarize: {error})."
            job.finished = time.time()

        with self.lock:
            self.items.append(job)
        threading.Thread(target=wait, daemon=True).start()
        return job

    def running(self, name: str) -> Job | None:
        with self.lock:
            return next((j for j in self.items if j.name == name and j.finished is None), None)

    def newly_finished(self) -> list[Job]:
        """Finished jobs not mentioned yet; each is returned once."""
        with self.lock:
            done = [j for j in self.items if j.finished is not None and not j.reported]
            for j in done:
                j.reported = True
            return done


# -- the research agent as a service ---------------------------------------------------------------

def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows; ask for its exit code instead.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                                  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _command_line(pid: int) -> str:
    if sys.platform == "win32":
        result = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                                capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)
        return result.stdout.strip()
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


class Service:
    """A long-running process started by the assistant, found again through its pid file."""

    def __init__(self, name: str, folder: Path, command: list[str], cwd: Path, marker: str):
        self.name, self.folder, self.command, self.cwd, self.marker = name, folder, command, cwd, marker
        self.pid_file = folder / f"{name}.pid"
        self.log = folder / f"{name}.log"

    def pid(self) -> int | None:
        """The service's process id if it's running and really is this service."""
        try:
            info = json.loads(self.pid_file.read_text())
        except (OSError, ValueError):
            return None
        pid = info.get("pid")
        if isinstance(pid, int) and _alive(pid) and self.marker in _command_line(pid):
            return pid
        return None

    def start(self) -> int:
        self.folder.mkdir(parents=True, exist_ok=True)
        out = open(self.log, "a", encoding="utf-8", errors="replace")
        out.write(f"\n--- started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        out.flush()
        flags = NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(self.command, cwd=self.cwd, stdout=out, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=flags,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                   start_new_session=sys.platform != "win32")
        out.close()
        self.pid_file.write_text(json.dumps({"pid": process.pid, "started": time.time()}))
        return process.pid

    def stop(self) -> bool:
        pid = self.pid()
        if pid is None:
            return False
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            os.kill(pid, 15)
        self.pid_file.unlink(missing_ok=True)
        return True
