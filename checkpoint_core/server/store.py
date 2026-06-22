"""Server-side storage: repos, tokens, per-repo locks, and audit logs. No Git."""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .. import util
from ..store import Repo
from .. import remote as remotemod

SERVER_DIR = ".checkpoint-server"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ServerStore:
    _locks: Dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, base: Path):
        self.base = Path(base)

    # ----------------------------------------------------------------- layout
    @property
    def config_path(self) -> Path:
        return self.base / "config.yaml"

    @property
    def repos_dir(self) -> Path:
        return self.base / "repos"

    @property
    def initialized(self) -> bool:
        return self.config_path.exists()

    @classmethod
    def init_store(cls, base: Path) -> "ServerStore":
        s = cls(Path(base))
        for d in (s.base, s.repos_dir, s.base / "tmp", s.base / "locks"):
            d.mkdir(parents=True, exist_ok=True)
        if not s.config_path.exists():
            s.save_config({
                "version": 1,
                "server_id": "srv_" + secrets.token_hex(8),
                "tokens": {},
            })
        return s

    # ----------------------------------------------------------------- config
    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {"version": 1, "server_id": "srv_unknown", "tokens": {}}
        with open(self.config_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def save_config(self, data: Dict[str, Any]) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        os.replace(tmp, self.config_path)

    def server_id(self) -> str:
        return self.load_config().get("server_id", "srv_unknown")

    # ------------------------------------------------------------------ tokens
    def create_token(self, name: str, scopes: List[str], repo_scope: str = "*") -> Dict[str, Any]:
        token = "ckpt_" + secrets.token_urlsafe(32)
        cfg = self.load_config()
        token_id = "tok_" + util.stamp() + "_" + secrets.token_hex(3)
        cfg.setdefault("tokens", {})[token_id] = {
            "token_id": token_id, "token_hash": hash_token(token), "name": name,
            "created_at": util.now_iso(), "scopes": scopes, "repo_scope": repo_scope,
            "revoked": False,
        }
        self.save_config(cfg)
        return {"token_id": token_id, "token": token, "scopes": scopes, "repo_scope": repo_scope}

    def revoke_token(self, token_id: str) -> bool:
        cfg = self.load_config()
        rec = cfg.get("tokens", {}).get(token_id)
        if not rec:
            return False
        rec["revoked"] = True
        self.save_config(cfg)
        return True

    def list_tokens(self) -> List[Dict[str, Any]]:
        return list(self.load_config().get("tokens", {}).values())

    def resolve_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        h = hash_token(token)
        for rec in self.load_config().get("tokens", {}).values():
            if rec.get("token_hash") == h and not rec.get("revoked"):
                return rec
        return None

    # ------------------------------------------------------------------- repos
    def repo_path(self, owner: str, repo: str) -> Path:
        # owner/repo are validated by the caller against a safe charset
        return self.repos_dir / owner / repo

    def repo_exists(self, owner: str, repo: str) -> bool:
        return (self.repo_path(owner, repo) / ".checkpoint" / "HEAD").exists()

    def create_repo(self, owner: str, repo: str, branch: str = "main") -> Repo:
        path = self.repo_path(owner, repo)
        if self.repo_exists(owner, repo):
            raise ValueError("repo already exists")
        path.mkdir(parents=True, exist_ok=True)
        return remotemod.bootstrap_store(path, branch)

    def get_repo(self, owner: str, repo: str) -> Optional[Repo]:
        if not self.repo_exists(owner, repo):
            return None
        return Repo(self.repo_path(owner, repo))

    def list_repos(self) -> List[str]:
        out = []
        if self.repos_dir.exists():
            for o in sorted(self.repos_dir.iterdir()):
                if o.is_dir():
                    for r in sorted(o.iterdir()):
                        if (r / ".checkpoint" / "HEAD").exists():
                            out.append("{}/{}".format(o.name, r.name))
        return out

    def delete_repo(self, owner: str, repo: str) -> bool:
        path = self.repo_path(owner, repo)
        if not path.exists():
            return False
        for p in sorted(path.rglob("*"), reverse=True):
            try:
                p.unlink() if p.is_file() else p.rmdir()
            except OSError:
                pass
        try:
            path.rmdir()
        except OSError:
            pass
        return True

    # ------------------------------------------------------------------- audit
    def audit(self, owner: str, repo: str, event: Dict[str, Any]) -> None:
        path = self.repo_path(owner, repo) / "audit.jsonl"
        rec = {"timestamp": util.now_iso(), **event}
        util.append_jsonl(path, rec)

    def read_audit(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        return util.read_jsonl(self.repo_path(owner, repo) / "audit.jsonl")

    # ------------------------------------------------------------------- locks
    @contextmanager
    def repo_lock(self, owner: str, repo: str):
        key = "{}/{}".format(owner, repo)
        with ServerStore._locks_guard:
            lock = ServerStore._locks.setdefault(key, threading.Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
