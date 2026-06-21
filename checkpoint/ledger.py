"""Append-only ledger (JSONL). Events are never edited in place."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import util
from .store import Repo

EVENT_TYPES = {
    "init", "session_start", "snapshot", "autosave",
    "verification", "packet", "accept", "reject", "rollback",
}


def append(
    repo: Repo,
    event_type: str,
    session_id: Optional[str],
    actor: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown event_type: {}".format(event_type))
    event = {
        "event_id": util.event_id(),
        "event_type": event_type,
        "session_id": session_id,
        "timestamp": util.now_iso(),
        "actor": actor or {"type": "human", "name": ""},
        "git_branch": repo.git.branch(),
        "git_head": repo.git.head(),
        "payload": payload or {},
    }
    util.append_jsonl(repo.paths.ledger, event)
    return event


def read_all(repo: Repo) -> List[Dict[str, Any]]:
    return util.read_jsonl(repo.paths.ledger)


def for_session(repo: Repo, session_id: str) -> List[Dict[str, Any]]:
    return [e for e in read_all(repo) if e.get("session_id") == session_id]
