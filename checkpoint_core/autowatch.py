"""Detached autosave watcher lifecycle.

When a session starts, spawn a background `checkpoint-core watch` process so edits are
continuously autosaved (recovery-only, never history). The watcher self-terminates when the
session ends (Watcher.run loops while the session is active), so no shutdown hook is needed
in accept/reject/rollback. A PID file makes the watcher discoverable and prevents doubles.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .store import Repo


def _run_dir(repo: Repo) -> Path:
    d = repo.paths.base / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pidfile(repo: Repo) -> Path:
    return _run_dir(repo) / "watch.pid"


def _logfile(repo: Repo) -> Path:
    return _run_dir(repo) / "watch.log"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def running_pid(repo: Repo) -> Optional[int]:
    """The live watcher PID for this repo, or None. Cleans up a stale PID file."""
    pf = _pidfile(repo)
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        pf.unlink(missing_ok=True)
        return None
    if _alive(pid):
        return pid
    pf.unlink(missing_ok=True)
    return None


def start(repo: Repo, debounce_ms: Optional[int] = None, poll_ms: Optional[int] = None) -> Optional[int]:
    """Spawn a detached autosave watcher for the active session. Idempotent.

    Returns the PID (existing or new), or None if autosave is disabled.
    """
    if not repo.config.autosave().get("enabled", True):
        return None
    existing = running_pid(repo)
    if existing:
        return existing
    launcher = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not launcher or not os.path.exists(launcher):
        return None  # can't locate the CLI launcher; skip silently
    argv = [sys.executable, launcher, "watch", "--managed"]
    if debounce_ms is not None:
        argv += ["--debounce-ms", str(debounce_ms)]
    if poll_ms is not None:
        argv += ["--poll-ms", str(poll_ms)]
    log = open(_logfile(repo), "a", buffering=1)
    proc = subprocess.Popen(
        argv, cwd=str(repo.root), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        start_new_session=True,  # detach: survives the parent command exiting
    )
    _pidfile(repo).write_text(str(proc.pid))
    return proc.pid


def stop(repo: Repo) -> bool:
    """Stop the watcher if running (it normally self-exits when the session ends)."""
    pid = running_pid(repo)
    if pid is None:
        return False
    try:
        os.kill(pid, 15)
    except OSError:
        pass
    _pidfile(repo).unlink(missing_ok=True)
    return True


def clear_pidfile(repo: Repo) -> None:
    _pidfile(repo).unlink(missing_ok=True)
