"""Git import/export bridge — the ONLY component that touches Git.

Checkpoint Core never imports this module. Git is a compatibility target, not a
dependency: history lives natively in Checkpoint, and this bridge mirrors it to/from
Git on demand.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import objects, util
from .session import Session, ACCEPTED
from .store import Repo


def _git(cwd: Path, args: List[str], env: Optional[Dict[str, str]] = None,
         check: bool = True) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    if env:
        e.update(env)
    proc = subprocess.run(["git", "-C", str(cwd)] + args, text=True,
                          capture_output=True, env=e)
    if check and proc.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(" ".join(args), proc.stderr))
    return proc


def git_available() -> bool:
    from shutil import which
    return which("git") is not None


# ------------------------------------------------------------------- core -> git

def _write_tree_to(repo: Repo, tree_id: str, dest: Path) -> None:
    tmap = objects.tree_map(repo.get_object(tree_id))
    # remove existing tracked files (except .git) so deletions propagate
    for p in list(dest.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(dest).parts:
            p.unlink()
    for path, meta in tmap.items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(repo.get_blob(meta["blob"]))
        if meta.get("mode") == "100755":
            os.chmod(target, 0o755)


def export_to_git(repo: Repo, dest_dir: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    """Replay the accepted-snapshot chain into a Git repo (one commit per snapshot)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        _git(dest, ["init", "-q"])

    head = repo.read_ref("refs/heads/{}".format(branch)) if branch else repo.head_snapshot()
    chain = list(reversed(repo.history(head)))  # root -> head
    count = 0
    for oid in chain:
        snap = repo.get_object(oid)
        if snap.get("kind") != objects.KIND_ACCEPTED:
            continue
        _write_tree_to(repo, snap["tree"], dest)
        _git(dest, ["add", "-A"])
        author = snap.get("author", {})
        name = author.get("name") or author.get("id") or "checkpoint"
        email = author.get("email") or "checkpoint@local"
        ts = snap.get("timestamp", util.now_iso())
        env = {
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts,
        }
        msg = (snap.get("message") or "checkpoint snapshot")
        trailer = "\n\nCheckpoint-Session: {}\nCheckpoint-Snapshot: {}".format(
            snap.get("session"), oid)
        _git(dest, ["commit", "-q", "--allow-empty", "-m", msg + trailer], env=env)
        count += 1
    return {"dest": str(dest), "commits": count, "head": head}


# ------------------------------------------------------------------- git -> core

def import_from_git(repo: Repo, git_dir: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    """Import a Git repo's history into accepted snapshots. After this, Git is optional."""
    src = Path(git_dir)
    commits = _git(src, ["rev-list", "--reverse", "HEAD"]).stdout.split()
    target_branch = branch or repo.config.default_branch()

    # one synthetic session records the provenance of the import
    isess = Session.create(
        repo, "git import from {}".format(src.name),
        actor={"type": "tool", "id": "git-bridge", "name": "git bridge"},
        agent=None, risk_tags=["import"], base_tree=repo.head_tree() or _empty_tree(repo),
    )
    isess.data["status"] = ACCEPTED
    isess.save()

    parent: Optional[str] = repo.read_ref("refs/heads/{}".format(target_branch))
    imported = 0
    for commit in commits:
        tree_id = _import_commit_tree(repo, src, commit)
        meta = _commit_meta(src, commit)
        snap = objects.make_snapshot(
            tree=tree_id, parents=[parent] if parent else [], session=isess.id,
            kind=objects.KIND_ACCEPTED, message=meta["message"],
            author={"id": meta["email"], "name": meta["name"], "email": meta["email"]},
            timestamp=meta["date"],
        )
        snap = objects.sign(snap, meta["email"])
        oid = repo.put_object(snap)
        parent = oid
        imported += 1

    if parent:
        repo.update_ref("refs/heads/{}".format(target_branch), parent)
        if repo.head_branch() is None:
            repo.set_head_to_branch(target_branch)
    return {"branch": target_branch, "commits": imported, "head": parent, "session": isess.id}


def _empty_tree(repo: Repo) -> str:
    return repo.put_object(objects.make_tree([]))


def _import_commit_tree(repo: Repo, src: Path, commit: str) -> str:
    raw = _git(src, ["ls-tree", "-r", "-z", commit]).stdout
    entries = []
    for rec in raw.split("\0"):
        if not rec.strip():
            continue
        meta, path = rec.split("\t", 1)
        mode, _typ, sha = meta.split()
        blob = subprocess.run(["git", "-C", str(src), "cat-file", "blob", sha],
                              capture_output=True).stdout
        oid = repo.put_blob(blob)
        norm_mode = "100755" if mode == "100755" else ("120000" if mode == "120000" else "100644")
        entries.append({"path": path, "blob": oid, "mode": norm_mode})
    return repo.put_object(objects.make_tree(entries))


def _commit_meta(src: Path, commit: str) -> Dict[str, str]:
    fmt = "%an%x00%ae%x00%aI%x00%B"
    out = _git(src, ["show", "-s", "--format=" + fmt, commit]).stdout
    name, email, date, body = out.split("\0", 3)
    return {"name": name, "email": email, "date": date, "message": body.strip()}
