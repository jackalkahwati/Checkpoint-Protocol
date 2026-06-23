"""The Session: Checkpoint Core's central object. Mutable while active, sealed on
accept/reject. Every accepted snapshot links back to the session that produced it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SCHEMA_VERSION, util
from .store import Repo

ACTIVE = "active"
ACCEPTED = "accepted"
REJECTED = "rejected"
ROLLED_BACK = "rolled_back"
ABANDONED = "abandoned"   # superseded/stale active session, cleaned up by `session prune`


class Session:
    def __init__(self, repo: Repo, data: Dict[str, Any]):
        self.repo = repo
        self.data = data

    # ----------------------------------------------------------------- identity
    @property
    def id(self) -> str:
        return self.data["session_id"]

    @property
    def dir(self) -> Path:
        return self.repo.paths.session_dir(self.id)

    @property
    def status(self) -> str:
        return self.data.get("status", ACTIVE)

    @property
    def base_tree(self) -> str:
        return self.data["base"]["tree"]

    @property
    def base_head(self) -> Optional[str]:
        return self.data["base"]["head"]

    def actor(self) -> Dict[str, Any]:
        return self.data.get("actor", {"type": "human", "id": "anon"})

    # ----------------------------------------------------------------- creation
    @classmethod
    def create(
        cls,
        repo: Repo,
        instruction: str,
        actor: Dict[str, str],
        agent: Optional[Dict[str, Any]],
        risk_tags: List[str],
        base_tree: str,
    ) -> "Session":
        sid = util.session_id(instruction)
        if repo.paths.session_dir(sid).exists():
            n = 2
            while repo.paths.session_dir("{}_{}".format(sid, n)).exists():
                n += 1
            sid = "{}_{}".format(sid, n)

        data: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": sid,
            "instruction": instruction,
            "status": ACTIVE,
            "created_at": util.now_iso(),
            "updated_at": util.now_iso(),
            "actor": actor,
            "agent": agent or {
                "name": None, "model": None, "tool": None, "prompt": None,
                "response_summary": None, "files_touched": [], "commands_run": [],
            },
            "base": {
                "branch": repo.head_branch(),
                "head": repo.head_snapshot(),
                "tree": base_tree,
            },
            "risk_tags": risk_tags or [],
            "snapshots": [],
            "autosaves": [],
            "verifications": [],
            "result": None,
            "packet": None,
            "_counters": {"snapshot": 0, "autosave": 0, "verification": 0},
        }
        sess = cls(repo, data)
        sess.dir.mkdir(parents=True, exist_ok=True)
        (sess.dir / "verification").mkdir(exist_ok=True)
        (sess.dir / "instruction.txt").write_text(instruction.rstrip() + "\n", encoding="utf-8")
        sess.save()
        return sess

    # ----------------------------------------------------------------- load/save
    @classmethod
    def load(cls, repo: Repo, sid: str) -> "Session":
        p = repo.paths.session_dir(sid) / "session.json"
        if not p.exists():
            raise FileNotFoundError("no such session: {}".format(sid))
        return cls(repo, util.read_json(p))

    @classmethod
    def active(cls, repo: Repo) -> Optional["Session"]:
        sid = repo.active_session_id()
        if not sid:
            return None
        try:
            return cls.load(repo, sid)
        except FileNotFoundError:
            return None

    def save(self) -> None:
        self.data["updated_at"] = util.now_iso()
        util.write_json(self.dir / "session.json", self.data)

    # ------------------------------------------------------------------ helpers
    def next_seq(self, kind: str) -> int:
        c = self.data.setdefault("_counters", {})
        c[kind] = c.get(kind, 0) + 1
        return c[kind]

    def set_status(self, status: str) -> None:
        self.data["status"] = status
        self.save()
