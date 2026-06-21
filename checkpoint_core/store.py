"""The Checkpoint Core store: content-addressed objects, refs, HEAD, and the Repo handle.

This is the source of truth. No Git anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import util
from .objects import KIND_ACCEPTED

CORE_DIR = ".checkpoint"


class NotInitialized(RuntimeError):
    pass


class Paths:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.base = self.root / CORE_DIR

    @property
    def config(self) -> Path:
        return self.base / "config.yaml"

    @property
    def identity(self) -> Path:
        return self.base / "identity.json"

    @property
    def head(self) -> Path:
        return self.base / "HEAD"

    @property
    def refs_heads(self) -> Path:
        return self.base / "refs" / "heads"

    @property
    def refs_remotes(self) -> Path:
        return self.base / "refs" / "remotes"

    @property
    def objects(self) -> Path:
        return self.base / "objects"

    @property
    def sessions(self) -> Path:
        return self.base / "sessions"

    @property
    def ledger(self) -> Path:
        return self.base / "ledger.jsonl"

    @property
    def state(self) -> Path:
        return self.base / "state.json"

    @property
    def tmp(self) -> Path:
        return self.base / "tmp"

    @property
    def cache(self) -> Path:
        return self.base / "cache"

    def session_dir(self, sid: str) -> Path:
        return self.sessions / sid


class Repo:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.paths = Paths(self.root)
        self._config = None  # lazy

    # ---------------------------------------------------------------- discovery
    @classmethod
    def discover(cls, start: Optional[Path] = None) -> "Repo":
        cur = Path(start or Path.cwd()).resolve()
        for d in [cur] + list(cur.parents):
            if (d / CORE_DIR / "HEAD").exists():
                return cls(d)
        raise NotInitialized(
            "Not inside a Checkpoint Core repo. Run `checkpoint-core init`."
        )

    @property
    def initialized(self) -> bool:
        return self.paths.head.exists()

    # ------------------------------------------------------------- object store
    def _obj_path(self, oid: str) -> Path:
        return self.paths.objects / oid[:2] / oid

    def has_object(self, oid: str) -> bool:
        return self._obj_path(oid).exists()

    def put_blob(self, data: bytes) -> str:
        oid = util.sha256_bytes(data)
        dest = self._obj_path(oid)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
        return oid

    def get_blob(self, oid: str) -> bytes:
        with open(self._obj_path(oid), "rb") as fh:
            return fh.read()

    def put_object(self, obj: Dict[str, Any]) -> str:
        """Store a structured object as canonical JSON. Returns its SHA-256 id."""
        data = util.canonical(obj)
        oid = util.sha256_bytes(data)
        dest = self._obj_path(oid)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
        return oid

    def get_object(self, oid: str) -> Dict[str, Any]:
        with open(self._obj_path(oid), "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def all_object_ids(self) -> List[str]:
        if not self.paths.objects.exists():
            return []
        out: List[str] = []
        for sub in self.paths.objects.iterdir():
            if sub.is_dir():
                out += [p.name for p in sub.iterdir() if p.is_file()]
        return out

    # -------------------------------------------------------------------- refs
    def ref_path(self, ref: str) -> Path:
        # ref like "refs/heads/main"
        return self.paths.base / ref

    def read_ref(self, ref: str) -> Optional[str]:
        p = self.ref_path(ref)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8").strip() or None

    def update_ref(self, ref: str, oid: str) -> None:
        p = self.ref_path(ref)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(oid + "\n", encoding="utf-8")

    def delete_ref(self, ref: str) -> None:
        p = self.ref_path(ref)
        if p.exists():
            p.unlink()

    def list_branches(self) -> List[str]:
        if not self.paths.refs_heads.exists():
            return []
        return sorted(p.name for p in self.paths.refs_heads.iterdir() if p.is_file())

    # -------------------------------------------------------------------- HEAD
    def read_head(self) -> str:
        return self.paths.head.read_text(encoding="utf-8").strip()

    def set_head_to_branch(self, branch: str) -> None:
        self.paths.head.write_text("ref: refs/heads/{}\n".format(branch), encoding="utf-8")

    def set_head_detached(self, oid: str) -> None:
        self.paths.head.write_text(oid + "\n", encoding="utf-8")

    def head_branch(self) -> Optional[str]:
        h = self.read_head()
        if h.startswith("ref: refs/heads/"):
            return h[len("ref: refs/heads/"):]
        return None

    def head_snapshot(self) -> Optional[str]:
        """Resolve HEAD to an accepted-snapshot id, or None if unborn/detached-empty."""
        h = self.read_head()
        if h.startswith("ref:"):
            return self.read_ref(h[len("ref: "):].strip())
        return h or None

    def head_tree(self) -> Optional[str]:
        snap_id = self.head_snapshot()
        if not snap_id:
            return None
        return self.get_object(snap_id).get("tree")

    # ------------------------------------------------------------ history walk
    def history(self, start: Optional[str] = None) -> List[str]:
        """Accepted-snapshot ids from `start` (default HEAD) back to root, newest first."""
        head = start if start is not None else self.head_snapshot()
        if not head:
            return []
        order: List[str] = []
        seen = set()
        stack = [head]
        while stack:
            oid = stack.pop()
            if oid in seen:
                continue
            seen.add(oid)
            order.append(oid)
            snap = self.get_object(oid)
            for parent in snap.get("parents", []):
                stack.append(parent)
        # order is a DAG walk; sort by timestamp desc for display stability
        order.sort(key=lambda o: self.get_object(o).get("timestamp", ""), reverse=True)
        return order

    def ancestors(self, oid: Optional[str]) -> set:
        seen = set()
        if not oid:
            return seen
        stack = [oid]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for p in self.get_object(cur).get("parents", []):
                stack.append(p)
        return seen

    def merge_base(self, a: Optional[str], b: Optional[str]) -> Optional[str]:
        """Lowest common ancestor by latest timestamp among shared ancestors."""
        if not a or not b:
            return None
        anc_a = self.ancestors(a)
        anc_b = self.ancestors(b)
        common = anc_a & anc_b
        if not common:
            return None
        return max(common, key=lambda o: self.get_object(o).get("timestamp", ""))

    def is_ancestor(self, maybe_ancestor: str, of: str) -> bool:
        return maybe_ancestor in self.ancestors(of)

    # -------------------------------------------------------------------- state
    def read_state(self) -> Dict[str, Any]:
        return util.read_json(self.paths.state, {"active_session": None})

    def write_state(self, state: Dict[str, Any]) -> None:
        util.write_json(self.paths.state, state)

    def active_session_id(self) -> Optional[str]:
        return self.read_state().get("active_session")

    def set_active_session(self, sid: Optional[str]) -> None:
        s = self.read_state()
        s["active_session"] = sid
        self.write_state(s)

    def session_ids(self) -> List[str]:
        if not self.paths.sessions.exists():
            return []
        return sorted(p.name for p in self.paths.sessions.iterdir() if p.is_dir())

    # ------------------------------------------------------------------ config
    @property
    def config(self):
        from .config import Config
        if self._config is None:
            self._config = Config.load(self.paths.config)
        return self._config

    # ---------------------------------------------------------------- identity
    def identity(self) -> Dict[str, str]:
        return util.read_json(self.paths.identity, {"id": "anon", "name": "", "email": ""})
