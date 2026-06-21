"""The .checkpoint store: directory layout, active-session pointer, and the Repo handle."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import SCHEMA_VERSION
from .config import Config
from .gitutil import Git
from . import util

CHECKPOINT_DIR = ".checkpoint"


class NotInitialized(RuntimeError):
    pass


class Paths:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.base = self.repo_root / CHECKPOINT_DIR

    @property
    def config(self) -> Path:
        return self.base / "config.yaml"

    @property
    def ledger(self) -> Path:
        return self.base / "ledger.jsonl"

    @property
    def state(self) -> Path:
        return self.base / "state.json"

    @property
    def sessions(self) -> Path:
        return self.base / "sessions"

    @property
    def objects(self) -> Path:
        return self.base / "objects"

    @property
    def cache(self) -> Path:
        return self.base / "cache"

    @property
    def tmp(self) -> Path:
        return self.base / "tmp"

    def session_dir(self, session_id: str) -> Path:
        return self.sessions / session_id

    def tmp_index(self, name: str = "index") -> Path:
        return self.tmp / name


class Repo:
    """Bundle of repo_root + git + paths + (lazy) config and state."""

    def __init__(self, repo_root: Path):
        self.root = Path(repo_root)
        self.paths = Paths(self.root)
        self.git = Git(self.root)
        self._config: Optional[Config] = None

    # ----------------------------------------------------------- discovery
    @classmethod
    def discover(cls, start: Optional[Path] = None) -> "Repo":
        """Find the enclosing Git repo and require .checkpoint to exist."""
        start = Path(start or Path.cwd())
        top = Git.toplevel(start)
        if top is None:
            raise NotInitialized(
                "Not inside a Git repository. Run `git init` then `checkpoint init`."
            )
        repo = cls(top)
        if not repo.paths.base.exists():
            raise NotInitialized(
                "Checkpoint is not initialized here. Run `checkpoint init`."
            )
        return repo

    @property
    def initialized(self) -> bool:
        return self.paths.base.exists()

    # -------------------------------------------------------------- config
    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = Config.load(self.paths.config)
        return self._config

    # --------------------------------------------------------------- state
    def read_state(self) -> Dict[str, Any]:
        return util.read_json(
            self.paths.state,
            {"schema_version": SCHEMA_VERSION, "active_session": None},
        )

    def write_state(self, state: Dict[str, Any]) -> None:
        util.write_json(self.paths.state, state)

    def active_session_id(self) -> Optional[str]:
        return self.read_state().get("active_session")

    def set_active_session(self, session_id: Optional[str]) -> None:
        state = self.read_state()
        state["active_session"] = session_id
        self.write_state(state)

    # ------------------------------------------------------- content store
    def store_blob(self, data: bytes) -> Dict[str, Any]:
        """Content-address `data` under objects/ (dedup). Returns sha/size/relpath."""
        sha = util.sha256_bytes(data)
        rel = "objects/{}/{}".format(sha[:2], sha)
        dest = self.paths.base / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
        return {"sha256": sha, "size": len(data), "object": rel}

    # ----------------------------------------------------------- sessions
    def session_ids(self) -> List[str]:
        if not self.paths.sessions.exists():
            return []
        return sorted(p.name for p in self.paths.sessions.iterdir() if p.is_dir())
