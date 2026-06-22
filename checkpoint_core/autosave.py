"""Autosaves: the continuous, invisible safety net.

Hierarchy (do not conflate):
  Autosave         - continuous, for recovery only. Never history, never a branch move.
  Snapshot         - user/agent-marked meaningful point, for comparison.
  Accepted snapshot- official sealed history (the commit equivalent).

Autosaves are content-addressed (tree + blobs live in the shared object store, so they
dedupe against snapshots and accepted history), but each autosave also gets a small
record directory with metadata, a copy of the tree object, and a diff for inspection.
Autosaves are written to disk immediately, so they survive process/machine crashes.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import timeline, util
from .diff import tree_diff, unified
from .session import Session
from .store import Repo
from .worktree import large_files, materialize, scan_to_tree

DAEMON_VERSION = "0.1"


def _seal(record: Dict[str, Any]) -> str:
    fields = {k: record.get(k) for k in (
        "autosave_id", "session_id", "parent_autosave_id", "timestamp",
        "tree_id", "base_snapshot_id", "changed_paths")}
    return util.canonical_sha(fields)


def verify_seal(record: Dict[str, Any]) -> bool:
    return record.get("content_seal") == _seal(record)


def _dir(repo: Repo, session: Session, autosave_id: str) -> Path:
    return session.dir / "autosaves" / autosave_id


def create_autosave(repo: Repo, session: Session, reason: str = "edit") -> Optional[Dict[str, Any]]:
    """Capture the working tree as an autosave. Deduplicates against the last one.

    Returns the record, or None when nothing changed (no new autosave written).
    """
    cfg = repo.config.autosave()
    if not cfg.get("enabled", True):
        return None
    max_mb = cfg.get("ignore_large_files_mb", 50)
    tree_id = scan_to_tree(repo, max_file_mb=max_mb)

    autos = session.data.get("autosaves", [])
    parent_id = autos[-1] if autos else None
    if parent_id:
        last = load_autosave(repo, session, parent_id)
        if last and last.get("tree_id") == tree_id:
            return None  # identical to last autosave -> skip (cheap + deduplicated)

    seq = session.next_seq("autosave")
    autosave_id = util.seq_id("auto", seq)
    td = tree_diff(repo, session.base_tree, tree_id)
    changed_paths = [f["path"] for f in td["files"]]

    record: Dict[str, Any] = {
        "autosave_id": autosave_id,
        "session_id": session.id,
        "parent_autosave_id": parent_id,
        "timestamp": util.now_iso(),
        "reason": reason,
        "changed_paths": changed_paths,
        "tree_id": tree_id,
        "base_snapshot_id": session.base_head,
        "daemon_version": DAEMON_VERSION,
    }
    record["content_seal"] = _seal(record)

    d = _dir(repo, session, autosave_id)
    d.mkdir(parents=True, exist_ok=True)
    util.write_json(d / "autosave.json", record)
    # A self-contained copy of the tree object for inspection/recovery.
    util.write_json(d / "tree.json", repo.get_object(tree_id))
    (d / "diff.patch").write_text(unified(repo, session.base_tree, tree_id), encoding="utf-8")

    session.data.setdefault("autosaves", []).append(autosave_id)
    session.save()
    timeline.append(repo, session.id, "autosave_created",
                    {"autosave_id": autosave_id, "reason": reason,
                     "changed": len(changed_paths), "tree_id": tree_id})

    gc(repo, session)
    return record


def list_autosaves(repo: Repo, session: Session) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for aid in session.data.get("autosaves", []):
        rec = load_autosave(repo, session, aid)
        if rec:
            out.append(rec)
    return out


def load_autosave(repo: Repo, session: Session, autosave_id: str) -> Optional[Dict[str, Any]]:
    p = _dir(repo, session, autosave_id) / "autosave.json"
    if not p.exists():
        return None
    return util.read_json(p)


def latest(repo: Repo, session: Session) -> Optional[Dict[str, Any]]:
    autos = session.data.get("autosaves", [])
    return load_autosave(repo, session, autos[-1]) if autos else None


def restore_autosave(repo: Repo, session: Session, autosave_id: str) -> Dict[str, Any]:
    """Restore the working tree to an autosave. Protects large (skipped) files from deletion."""
    rec = load_autosave(repo, session, autosave_id)
    if rec is None:
        raise FileNotFoundError("no such autosave: {}".format(autosave_id))
    max_mb = repo.config.autosave().get("ignore_large_files_mb", 50)
    protect = large_files(repo, max_mb)
    result = materialize(repo, rec["tree_id"], delete_extra=True, protect=protect)
    return {"restored": result["written"], "deleted": result["deleted"], "record": rec}


def gc(repo: Repo, session: Session) -> List[str]:
    """Remove old autosave records beyond keep_last AND older than keep_for_days.

    Only autosave *records* are removed; objects (blobs/trees) and accepted history are
    never touched, so accepted snapshots are always safe.
    """
    cfg = repo.config.autosave().get("gc", {}) or {}
    keep_last = int(cfg.get("keep_last", 100))
    keep_days = float(cfg.get("keep_for_days", 14))
    autos = session.data.get("autosaves", [])
    if len(autos) <= keep_last:
        return []
    cutoff = util.now() - timedelta(days=keep_days)
    candidates = autos[:-keep_last] if keep_last > 0 else list(autos)
    removed: List[str] = []
    for aid in candidates:
        rec = load_autosave(repo, session, aid)
        if rec is None:
            removed.append(aid)
            continue
        try:
            ts = _parse_ts(rec["timestamp"])
        except Exception:
            continue
        if ts < cutoff:
            _remove_dir(_dir(repo, session, aid))
            removed.append(aid)
    if removed:
        session.data["autosaves"] = [a for a in autos if a not in removed]
        session.save()
    return removed


def _parse_ts(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s)


def _remove_dir(path: Path) -> None:
    if not path.exists():
        return
    for p in sorted(path.rglob("*"), reverse=True):
        try:
            p.unlink() if p.is_file() else p.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
