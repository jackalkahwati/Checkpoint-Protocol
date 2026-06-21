"""Session model: create, load, save, and helpers for the active session."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SCHEMA_VERSION, util
from .store import Repo

STATUS_ACTIVE = "active"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_ROLLED_BACK = "rolled_back"


class Session:
    def __init__(self, repo: Repo, data: Dict[str, Any]):
        self.repo = repo
        self.data = data

    # ------------------------------------------------------------- identity
    @property
    def id(self) -> str:
        return self.data["session_id"]

    @property
    def dir(self) -> Path:
        return self.repo.paths.session_dir(self.id)

    @property
    def status(self) -> str:
        return self.data.get("status", STATUS_ACTIVE)

    # ------------------------------------------------------------- creation
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
        # Guard against same-second collisions.
        if repo.paths.session_dir(sid).exists():
            n = 2
            while repo.paths.session_dir("{}_{}".format(sid, n)).exists():
                n += 1
            sid = "{}_{}".format(sid, n)

        git = repo.git
        data: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": sid,
            "instruction": instruction,
            "status": STATUS_ACTIVE,
            "created_at": util.now_iso(),
            "updated_at": util.now_iso(),
            "actor": {"type": actor.get("type", "human"), "name": actor.get("name", "")},
            "agent": agent or {
                "name": None, "model": None, "tool": None,
                "prompt": None, "response_summary": None,
                "files_touched": [], "commands_run": [],
            },
            "git": {
                "base_branch": git.branch(),
                "base_head": git.head(),
                "base_tree": base_tree,
                "base_clean": git.is_clean(),
                "accept_head": None,
            },
            "risk_tags": risk_tags or [],
            "snapshots": [],
            "autosaves": [],
            "verifications": [],
            "packet": None,
            "_counters": {"snapshot": 0, "autosave": 0, "verification": 0},
        }
        sess = cls(repo, data)
        sess.dir.mkdir(parents=True, exist_ok=True)
        (sess.dir / "snapshots").mkdir(exist_ok=True)
        (sess.dir / "autosaves").mkdir(exist_ok=True)
        (sess.dir / "verification").mkdir(exist_ok=True)
        with open(sess.dir / "instruction.txt", "w", encoding="utf-8") as fh:
            fh.write(instruction.rstrip() + "\n")
        sess.save()
        return sess

    # ------------------------------------------------------------- load/save
    @classmethod
    def load(cls, repo: Repo, session_id: str) -> "Session":
        path = repo.paths.session_dir(session_id) / "session.json"
        if not path.exists():
            raise FileNotFoundError("no such session: {}".format(session_id))
        return cls(repo, util.read_json(path))

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

    # ------------------------------------------------------------- counters
    def next_seq(self, kind: str) -> int:
        counters = self.data.setdefault("_counters", {})
        counters[kind] = counters.get(kind, 0) + 1
        return counters[kind]

    # --------------------------------------------------------------- status
    def set_status(self, status: str) -> None:
        self.data["status"] = status
        self.save()

    # ------------------------------------------------------------- git refs
    @property
    def base_tree(self) -> str:
        return self.data["git"]["base_tree"]

    @property
    def base_head(self) -> Optional[str]:
        return self.data["git"]["base_head"]

    def actor(self) -> Dict[str, Any]:
        return self.data.get("actor", {"type": "human", "name": ""})
