"""Content-addressed sync: push/pull between two stores, plus portable bundles.

Objects are immutable and addressed by SHA-256, so copying is idempotent and a
re-push/re-pull is a no-op. Works between any two stores with no central server.
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import util
from .store import Repo


def reachable_objects(repo: Repo, head: Optional[str]) -> Set[str]:
    """All object ids reachable from an accepted-snapshot head: snapshots, trees, blobs."""
    oids: Set[str] = set()
    if not head:
        return oids
    stack = [head]
    seen_snaps: Set[str] = set()
    while stack:
        sid = stack.pop()
        if sid in seen_snaps:
            continue
        seen_snaps.add(sid)
        oids.add(sid)
        snap = repo.get_object(sid)
        tree_id = snap.get("tree")
        if tree_id:
            oids.add(tree_id)
            for e in repo.get_object(tree_id).get("entries", []):
                oids.add(e["blob"])
        for p in snap.get("parents", []):
            stack.append(p)
    return oids


def referenced_sessions(repo: Repo, head: Optional[str]) -> List[str]:
    out: List[str] = []
    for sid in reachable_objects(repo, head):
        try:
            obj = repo.get_object(sid)
        except Exception:
            continue
        if obj.get("type") == "snapshot" and obj.get("session"):
            out.append(obj["session"])
    return sorted(set(out))


def _copy_object(src: Repo, dst: Repo, oid: str) -> None:
    if dst.has_object(oid):
        return
    data = (src.paths.objects / oid[:2] / oid).read_bytes()
    dest = dst.paths.objects / oid[:2] / oid
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _copy_session(src: Repo, dst: Repo, sid: str) -> None:
    sdir = src.paths.session_dir(sid)
    if not sdir.exists():
        return
    for path in sdir.rglob("*"):
        if path.is_file():
            rel = path.relative_to(sdir)
            dest = dst.paths.session_dir(sid) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())


def _merge_ledger(src: Repo, dst: Repo) -> int:
    have = {e["event_id"] for e in util.read_jsonl(dst.paths.ledger)}
    added = 0
    for e in util.read_jsonl(src.paths.ledger):
        if e["event_id"] not in have:
            util.append_jsonl(dst.paths.ledger, e)
            added += 1
    return added


def _transfer(src: Repo, dst: Repo, branch: str) -> Dict[str, Any]:
    src_head = src.read_ref("refs/heads/{}".format(branch))
    if not src_head:
        raise ValueError("source has no branch '{}'".format(branch))
    dst_head = dst.read_ref("refs/heads/{}".format(branch))
    # Fast-forward safety: refuse if dst head is not an ancestor of src head.
    if dst_head and dst_head != src_head and not src.is_ancestor(dst_head, src_head):
        # dst may also be ahead/diverged; check the other direction for a clean message
        raise ValueError(
            "non-fast-forward: '{}' has diverged. Pull and merge first.".format(branch))

    oids = reachable_objects(src, src_head)
    copied = 0
    for oid in oids:
        if not dst.has_object(oid):
            _copy_object(src, dst, oid)
            copied += 1
    for sid in referenced_sessions(src, src_head):
        _copy_session(src, dst, sid)
    events = _merge_ledger(src, dst)
    dst.update_ref("refs/heads/{}".format(branch), src_head)
    return {"objects_copied": copied, "ledger_events": events, "head": src_head}


def push(repo: Repo, remote: Repo, branch: str) -> Dict[str, Any]:
    return _transfer(repo, remote, branch)


def pull(repo: Repo, remote: Repo, branch: str) -> Dict[str, Any]:
    return _transfer(remote, repo, branch)


# ------------------------------------------------------------------------ bundles

def export_bundle(repo: Repo, branch: str, out_path: Path) -> Dict[str, Any]:
    head = repo.read_ref("refs/heads/{}".format(branch))
    if not head:
        raise ValueError("no such branch: {}".format(branch))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    oids = reachable_objects(repo, head)
    sessions = referenced_sessions(repo, head)

    with tarfile.open(out_path, "w:gz") as tar:
        for oid in sorted(oids):
            data = (repo.paths.objects / oid[:2] / oid).read_bytes()
            _add(tar, "objects/{}/{}".format(oid[:2], oid), data)
        for sid in sessions:
            sdir = repo.paths.session_dir(sid)
            for p in sorted(sdir.rglob("*")):
                if p.is_file():
                    _add(tar, "sessions/{}/{}".format(sid, p.relative_to(sdir)), p.read_bytes())
        events = [e for e in util.read_jsonl(repo.paths.ledger) if e.get("session_id") in sessions or e.get("head") == head]
        ledger_bytes = ("\n".join(json.dumps(e) for e in events) + "\n").encode("utf-8")
        _add(tar, "ledger.jsonl", ledger_bytes)
        manifest = {"format": "checkpoint-core-bundle/1", "branch": branch,
                    "head": head, "objects": len(oids), "exported_at": util.now_iso()}
        _add(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return {"out_path": str(out_path), "objects": len(oids), "head": head}


def import_bundle(repo: Repo, bundle_path: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    with tarfile.open(bundle_path, "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        target_branch = branch or manifest["branch"]
        copied = 0
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name
            data = tar.extractfile(member).read()
            if name.startswith("objects/"):
                oid = name.split("/")[-1]
                if not repo.has_object(oid):
                    dest = repo.paths.objects / oid[:2] / oid
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    copied += 1
            elif name.startswith("sessions/"):
                dest = repo.paths.base / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            elif name == "ledger.jsonl":
                have = {e["event_id"] for e in util.read_jsonl(repo.paths.ledger)}
                for line in data.decode("utf-8").splitlines():
                    if line.strip():
                        e = json.loads(line)
                        if e["event_id"] not in have:
                            util.append_jsonl(repo.paths.ledger, e)
        repo.update_ref("refs/heads/{}".format(target_branch), manifest["head"])
    return {"branch": target_branch, "head": manifest["head"], "objects_copied": copied}


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))
