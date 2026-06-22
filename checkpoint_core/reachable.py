"""Object-store introspection + reachability walker. No Git.

Truth is rebuilt from objects + refs + sessions on every call (no reliance on a stale
index). The walker marks every object reachable from protected roots so fsck can report
and gc can safely collect only what is unreachable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import util
from .store import Repo

KNOWN_TYPES = ("tree", "snapshot")


# ----------------------------------------------------------------- object access

def iter_object_ids(repo: Repo):
    base = repo.paths.objects
    if not base.exists():
        return
    for sub in sorted(base.iterdir()):
        if sub.is_dir() and len(sub.name) == 2:
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    yield f.name


def object_file(repo: Repo, oid: str) -> Path:
    return repo.paths.objects / oid[:2] / oid


def object_size(repo: Repo, oid: str) -> int:
    try:
        return object_file(repo, oid).stat().st_size
    except OSError:
        return 0


def object_age_days(repo: Repo, oid: str) -> float:
    try:
        mtime = object_file(repo, oid).stat().st_mtime
    except OSError:
        return 0.0
    return (util.now().timestamp() - mtime) / 86400.0


def load_raw(repo: Repo, oid: str) -> Optional[bytes]:
    p = object_file(repo, oid)
    if not p.exists():
        return None
    return p.read_bytes()


def classify(repo: Repo, oid: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return ('snapshot'|'tree'|'blob', obj_or_None). Type is intrinsic to content."""
    raw = load_raw(repo, oid)
    if raw is None:
        return ("missing", None)
    try:
        obj = json.loads(raw.decode("utf-8"))
        if isinstance(obj, dict) and obj.get("type") in KNOWN_TYPES:
            return (obj["type"], obj)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    return ("blob", None)


# ----------------------------------------------------------------------- ages

def _age_days(iso: Optional[str]) -> float:
    if not iso:
        return 1e9
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (util.now() - dt).total_seconds() / 86400.0
    except Exception:
        return 1e9


# ----------------------------------------------------------------- reachability

def compute_reachable(repo: Repo, aggressive: bool = False,
                      keep_autosaves_days: float = 14.0,
                      keep_rejected_days: float = 30.0) -> Dict[str, Any]:
    """Walk protected roots. Returns reachable ids + bookkeeping for fsck/gc."""
    reachable: Set[str] = set()
    missing_refs: List[Dict[str, str]] = []      # referenced but absent on disk
    visited_snap: Set[str] = set()
    refs_scanned = 0
    sessions_scanned = 0

    def visit_tree(tid: Optional[str], ref_by: str) -> None:
        if not tid or tid in reachable:
            return
        reachable.add(tid)
        kind, obj = classify(repo, tid)
        if kind == "missing":
            missing_refs.append({"id": tid, "referenced_by": ref_by})
            return
        if kind == "tree" and obj:
            for e in obj.get("entries", []):
                b = e.get("blob")
                if b:
                    reachable.add(b)
                    if classify(repo, b)[0] == "missing":
                        missing_refs.append({"id": b, "referenced_by": "tree {}".format(tid)})

    def visit_snap(sid: Optional[str], ref_by: str) -> None:
        if not sid or sid in visited_snap:
            return
        visited_snap.add(sid)
        reachable.add(sid)
        kind, snap = classify(repo, sid)
        if kind == "missing":
            missing_refs.append({"id": sid, "referenced_by": ref_by})
            return
        if kind != "snapshot" or not snap:
            return
        visit_tree(snap.get("tree"), "snapshot {}".format(sid))
        for p in snap.get("parents", []) or []:
            visit_snap(p, "parent of {}".format(sid))

    # refs/heads + refs/tags
    for kind_dir in ("heads", "tags"):
        d = repo.paths.base / "refs" / kind_dir
        if d.exists():
            for ref in sorted(d.iterdir()):
                if ref.is_file():
                    refs_scanned += 1
                    visit_snap(ref.read_text(encoding="utf-8").strip() or None,
                               "ref {}/{}".format(kind_dir, ref.name))

    active = repo.active_session_id()
    for sid in repo.session_ids():
        sessions_scanned += 1
        sjson = repo.paths.session_dir(sid) / "session.json"
        try:
            sess = util.read_json(sjson, None)
        except Exception:
            continue  # malformed session.json -> contributes no roots (fsck reports it)
        if not sess:
            continue
        status = sess.get("status")
        is_active = sid == active
        if aggressive and not is_active and status in ("rejected", "rolled_back"):
            if _age_days(sess.get("created_at")) > keep_rejected_days:
                continue  # rejected/abandoned session past retention -> not protected

        base = sess.get("base", {}) or {}
        visit_tree(base.get("tree"), "session {} base".format(sid))
        visit_snap(base.get("head"), "session {} base head".format(sid))
        for s in sess.get("snapshots", []) or []:
            visit_snap(s, "session {} snapshot".format(sid))
        res = sess.get("result") or {}
        if res.get("snapshot"):
            visit_snap(res["snapshot"], "session {} result".format(sid))

        # verification record trees
        for vid in sess.get("verifications", []) or []:
            rec = util.read_json(repo.paths.session_dir(sid) / "verification" / (vid + ".json"), None)
            if rec and rec.get("tree"):
                visit_tree(rec["tree"], "verification {}".format(vid))

        # packet trees (a session artifact users inspect)
        pkt = util.read_json(repo.paths.session_dir(sid) / "packet.json", None)
        if pkt:
            visit_tree(pkt.get("base_tree"), "packet {}".format(sid))
            visit_tree(pkt.get("current_tree"), "packet {}".format(sid))

        # autosave trees within retention (active session keeps all)
        for aid in sess.get("autosaves", []) or []:
            rec = util.read_json(repo.paths.session_dir(sid) / "autosaves" / aid / "autosave.json", None)
            if not rec:
                continue
            if is_active or _age_days(rec.get("timestamp")) <= keep_autosaves_days:
                visit_tree(rec.get("tree_id"), "autosave {}".format(aid))

    return {
        "reachable": reachable,
        "missing_refs": missing_refs,
        "refs_scanned": refs_scanned,
        "sessions_scanned": sessions_scanned,
    }
