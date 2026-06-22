"""Per-session timeline: an append-only, session-scoped event log.

Distinct from the repo ledger: the timeline is the chronological story of a single
session (start, autosaves, snapshots, verification, accept, rollback, recover) and is
what `checkpoint-core timeline` renders.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import util
from .store import Repo

EVENT_TYPES = {
    "session_started", "autosave_created", "snapshot_created",
    "verification_run", "accepted", "rollback", "recover_invoked",
}


def _path(repo: Repo, session_id: str):
    return repo.paths.session_dir(session_id) / "timeline.jsonl"


def append(repo: Repo, session_id: str, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown timeline event: {}".format(event_type))
    event = {
        "type": event_type,
        "timestamp": util.now_iso(),
        "payload": payload or {},
    }
    util.append_jsonl(_path(repo, session_id), event)
    return event


def read(repo: Repo, session_id: str) -> List[Dict[str, Any]]:
    return util.read_jsonl(_path(repo, session_id))
