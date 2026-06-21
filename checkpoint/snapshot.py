"""Snapshots (meaningful intermediate states) and autosaves (recovery records)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import util
from .ignore import read_checkpointignore
from .session import Session
from .store import Repo


def capture_tree(repo: Repo, name: str = "index") -> str:
    """Capture the current working tree as a Git tree SHA, respecting ignore rules."""
    excludes = read_checkpointignore(repo.root)
    return repo.git.write_worktree_tree(repo.paths.tmp_index(name), excludes)


def _manifest(repo: Repo, base_tree: str, tree: str) -> List[Dict[str, Any]]:
    """Build the changed-file manifest, storing new blobs content-addressed."""
    manifest: List[Dict[str, Any]] = []
    for status, path in repo.git.diff_name_status(base_tree, tree):
        entry: Dict[str, Any] = {"path": path, "status": status}
        if status == "D":
            entry.update({"sha256": None, "size": 0, "object": None})
        else:
            data = repo.git.cat_blob_at(tree, path)
            if data is None:
                entry.update({"sha256": None, "size": 0, "object": None})
            else:
                entry.update(repo.store_blob(data))
        manifest.append(entry)
    return manifest


def create_snapshot(repo: Repo, session: Session, message: Optional[str]) -> Dict[str, Any]:
    seq = session.next_seq("snapshot")
    snap_id = util.seq_id("snap", seq)
    tree = capture_tree(repo)
    base_tree = session.base_tree

    snap_dir = session.dir / "snapshots" / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    diff_text = repo.git.diff(base_tree, tree)
    with open(snap_dir / "diff.patch", "w", encoding="utf-8") as fh:
        fh.write(diff_text)

    manifest = _manifest(repo, base_tree, tree)
    stats = repo.git.numstat(base_tree, tree)

    snapshot = {
        "snapshot_id": snap_id,
        "session_id": session.id,
        "created_at": util.now_iso(),
        "message": message,
        "git_branch": repo.git.branch(),
        "base_tree": base_tree,
        "tree": tree,
        "diff_path": "diff.patch",
        "changed_files": manifest,
        "stats": stats,
    }
    util.write_json(snap_dir / "snapshot.json", snapshot)

    session.data["snapshots"].append(snap_id)
    session.save()
    return snapshot


def load_snapshot(repo: Repo, session: Session, snapshot_id: str) -> Dict[str, Any]:
    path = session.dir / "snapshots" / snapshot_id / "snapshot.json"
    if not path.exists():
        raise FileNotFoundError("no such snapshot: {}".format(snapshot_id))
    return util.read_json(path)


def create_autosave(repo: Repo, session: Session) -> Optional[Dict[str, Any]]:
    """Lightweight recovery record. Only stored when the tree actually changed."""
    if not repo.config.data.get("autosave", {}).get("enabled", True):
        return None
    tree = capture_tree(repo, name="autosave-index")
    autosaves = session.data.get("autosaves", [])
    # Skip if identical to the last autosave's tree.
    if autosaves:
        last = util.read_json(session.dir / "autosaves" / (autosaves[-1] + ".json"), {})
        if last.get("tree") == tree:
            return None
    seq = session.next_seq("autosave")
    auto_id = util.seq_id("auto", seq)
    record = {
        "autosave_id": auto_id,
        "session_id": session.id,
        "created_at": util.now_iso(),
        "base_tree": session.base_tree,
        "tree": tree,
        "stats": repo.git.numstat(session.base_tree, tree),
    }
    util.write_json(session.dir / "autosaves" / (auto_id + ".json"), record)
    session.data["autosaves"].append(auto_id)
    session.save()
    return record


def last_autosave(session: Session) -> Optional[Dict[str, Any]]:
    autosaves = session.data.get("autosaves", [])
    if not autosaves:
        return None
    return util.read_json(session.dir / "autosaves" / (autosaves[-1] + ".json"), None)
