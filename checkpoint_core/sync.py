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
        try:
            snap = repo.get_object(sid)          # tolerate non-snapshot / malformed targets
        except Exception:
            continue
        tree_id = snap.get("tree")
        if tree_id:
            oids.add(tree_id)
            try:
                for e in repo.get_object(tree_id).get("entries", []):
                    oids.add(e["blob"])
            except Exception:
                pass
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

        # signatures for reachable snapshots (so the bundle is self-verifiable)
        signer_ids = set()
        for oid in sorted(oids):
            sdir = repo.paths.signatures / oid
            if sdir.exists():
                for f in sorted(sdir.iterdir()):
                    if f.is_file():
                        _add(tar, "signatures/{}/{}".format(oid, f.name), f.read_bytes())
                        rec = util.read_json(f, {})
                        if rec.get("signer_identity_id"):
                            signer_ids.add(rec["signer_identity_id"])

        # PUBLIC identity records only — NEVER private keys (keys/ is never touched)
        idents = 0
        idir = repo.paths.identities
        if idir.exists():
            for f in sorted(idir.iterdir()):
                if f.is_file() and f.suffix == ".json":
                    rec = util.read_json(f, {})
                    pub = dict(rec)
                    pub.pop("trusted", None)  # trust is local; imports start untrusted
                    _add(tar, "identities/{}".format(f.name),
                         json.dumps(pub, indent=2).encode("utf-8"))
                    idents += 1

        manifest = {"format": "checkpoint-core-bundle/1", "branch": branch,
                    "head": head, "objects": len(oids), "identities": idents,
                    "exported_at": util.now_iso()}
        _add(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return {"out_path": str(out_path), "objects": len(oids), "head": head, "identities": idents}


# ----------------------------------------------------- hardened bundles (Phase 6)

_ALLOWED_PREFIXES = ("objects/", "sessions/", "signatures/", "identities/", "refs/")
_ALLOWED_FILES = ("manifest.json", "ledger.jsonl")
_PEM_PRIVATE = b"PRIVATE KEY-----"


def _member_safety_error(member) -> Optional[str]:
    name = member.name
    if member.issym() or member.islnk():
        return "archive member {} is a link (rejected)".format(name)
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return "absolute path in archive: {}".format(name)
    parts = Path(name).parts
    if ".." in parts:
        return "path traversal in archive: {}".format(name)
    if "keys" in parts or name.endswith(".key"):
        return "private key material in archive: {} (rejected)".format(name)
    if not (name in _ALLOWED_FILES or any(name.startswith(p) for p in _ALLOWED_PREFIXES)):
        return "unexpected archive path: {}".format(name)
    return None


def _bundle_refs(manifest: Dict[str, Any]) -> Dict[str, str]:
    if isinstance(manifest.get("refs"), dict):
        return manifest["refs"]
    if manifest.get("branch") and manifest.get("head"):   # legacy export_bundle layout
        return {manifest["branch"]: manifest["head"]}
    return {}


def _stage_bundle(bundle_path: Path, require_signatures: bool):
    """Safely extract a bundle into a temp store and verify it. Returns (report, temp_root).

    Caller must remove temp_root. report = {ok, errors, manifest, refs, tags}.
    """
    import tempfile
    from . import remote as remotemod

    errors: List[str] = []
    temp_root = Path(tempfile.mkdtemp(prefix="ckpt-bundle-"))
    base = temp_root / ".checkpoint"
    manifest: Dict[str, Any] = {}
    try:
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                if not m.isfile():
                    if m.issym() or m.islnk():
                        errors.append(_member_safety_error(m))
                    continue
                e = _member_safety_error(m)
                if e:
                    errors.append(e)
                    continue
                data = tar.extractfile(m).read()
                if _PEM_PRIVATE in data:
                    errors.append("private key material in {} (rejected)".format(m.name))
                    continue
                dest = base / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        if errors:
            return {"ok": False, "errors": errors, "manifest": {}, "refs": {}, "tags": {}}, temp_root

        mpath = base / "manifest.json"
        if not mpath.exists():
            return {"ok": False, "errors": ["missing manifest.json"], "manifest": {},
                    "refs": {}, "tags": {}}, temp_root
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "errors": ["malformed manifest.json"], "manifest": {},
                    "refs": {}, "tags": {}}, temp_root

        trepo = Repo(temp_root)
        # verify every object's content hash matches its id
        for oid in remotemod.R.iter_object_ids(trepo):
            raw = (trepo.paths.objects / oid[:2] / oid).read_bytes()
            if util.sha256_bytes(raw) != oid:
                errors.append("object {} fails content-hash check".format(oid))

        refs = _bundle_refs(manifest)
        tags = manifest.get("tags", {}) if isinstance(manifest.get("tags"), dict) else {}
        for _name, target in list(refs.items()) + list(tags.items()):
            ok, errs = remotemod.verify_received(trepo, target, require_signatures=require_signatures)
            if not ok:
                errors.extend(errs)

        return ({"ok": not errors, "errors": errors, "manifest": manifest,
                 "refs": refs, "tags": tags}, temp_root)
    except tarfile.TarError as exc:
        return {"ok": False, "errors": ["bad archive: {}".format(exc)], "manifest": {},
                "refs": {}, "tags": {}}, temp_root


def verify_bundle(bundle_path: Path, require_signatures: bool = False) -> Dict[str, Any]:
    report, temp_root = _stage_bundle(Path(bundle_path), require_signatures)
    _rmtree(temp_root)
    return report


def import_bundle(repo: Repo, bundle_path: Path, branch: Optional[str] = None,
                  require_signatures: bool = False) -> Dict[str, Any]:
    report, temp_root = _stage_bundle(Path(bundle_path), require_signatures)
    try:
        if not report["ok"]:
            return {"ok": False, "errors": report["errors"]}
        trepo = Repo(temp_root)
        copied = 0
        from . import remote as remotemod
        for oid in remotemod.R.iter_object_ids(trepo):
            if not repo.has_object(oid):
                copy = (trepo.paths.objects / oid[:2] / oid).read_bytes()
                dest = repo.paths.objects / oid[:2] / oid
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(copy)
                copied += 1
        # signatures, sessions
        for sub in ("signatures", "sessions"):
            srcdir = trepo.paths.base / sub
            if srcdir.exists():
                for p in srcdir.rglob("*"):
                    if p.is_file():
                        dest = repo.paths.base / sub / p.relative_to(srcdir)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(p.read_bytes())
        # public identities (untrusted)
        idir = trepo.paths.identities
        if idir.exists():
            for p in sorted(idir.iterdir()):
                if p.is_file() and p.suffix == ".json":
                    rec = util.read_json(p, {})
                    rec["trusted"] = False
                    rec.setdefault("revoked", False)
                    dest = repo.paths.identities / p.name
                    if not dest.exists():
                        util.write_json(dest, rec)
        # ledger merge
        lpath = trepo.paths.ledger
        if lpath.exists():
            have = {e["event_id"] for e in util.read_jsonl(repo.paths.ledger)}
            for e in util.read_jsonl(lpath):
                if e.get("event_id") not in have:
                    util.append_jsonl(repo.paths.ledger, e)
        # refs (local branches) + tags, after everything verified
        target_refs = report["refs"]
        if branch:
            target_refs = {branch: list(report["refs"].values())[0]} if report["refs"] else {}
        for name, head in target_refs.items():
            repo.update_ref("refs/heads/{}".format(name), head)
        for name, target in report["tags"].items():
            repo.update_ref("refs/tags/{}".format(name), target)
        head = next(iter(target_refs.values()), None)
        return {"ok": True, "objects_copied": copied, "refs": list(target_refs.keys()),
                "head": head, "branch": next(iter(target_refs.keys()), branch)}
    finally:
        _rmtree(temp_root)


def create_bundle(repo: Repo, out_path: Path, branch: Optional[str] = None,
                  tags: bool = False, include_sessions: bool = True) -> Dict[str, Any]:
    """Portable bundle with manifest, objects, refs, tags, sessions, signatures, public ids."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    branches = [branch] if branch else repo.list_branches()
    refs = {}
    for b in branches:
        h = repo.read_ref("refs/heads/{}".format(b))
        if h:
            refs[b] = h
    tag_map = {}
    if tags:
        tdir = repo.paths.base / "refs" / "tags"
        if tdir.exists():
            for tf in tdir.iterdir():
                if tf.is_file():
                    tag_map[tf.name] = tf.read_text(encoding="utf-8").strip()

    oids: Set[str] = set()
    for target in list(refs.values()) + list(tag_map.values()):
        oids |= reachable_objects(repo, target)
    sessions = []
    if include_sessions:
        for target in list(refs.values()) + list(tag_map.values()):
            sessions += referenced_sessions(repo, target)
    sessions = sorted(set(sessions))
    # include objects each session references (base trees, intermediate snapshots, etc.)
    if include_sessions:
        from . import remote as remotemod
        for sid in sessions:
            oids |= remotemod._session_object_ids(repo, sid)

    with tarfile.open(out_path, "w:gz") as tar:
        for oid in sorted(oids):
            _add(tar, "objects/{}/{}".format(oid[:2], oid),
                 (repo.paths.objects / oid[:2] / oid).read_bytes())
        sig_count = 0
        for oid in sorted(oids):
            sdir = repo.paths.signatures / oid
            if sdir.exists():
                for f in sorted(sdir.iterdir()):
                    if f.is_file():
                        _add(tar, "signatures/{}/{}".format(oid, f.name), f.read_bytes())
                        sig_count += 1
        idents = 0
        if repo.paths.identities.exists():
            for f in sorted(repo.paths.identities.iterdir()):
                if f.is_file() and f.suffix == ".json":
                    rec = util.read_json(f, {})
                    rec.pop("trusted", None)
                    _add(tar, "identities/{}".format(f.name), json.dumps(rec, indent=2).encode("utf-8"))
                    idents += 1
        for sid in sessions:
            sdir = repo.paths.session_dir(sid)
            for p in sorted(sdir.rglob("*")):
                if p.is_file() and "keys" not in p.parts and not p.name.endswith(".key"):
                    if p.relative_to(sdir).parts[0] == "autosaves":
                        continue  # autosaves never bundled by default
                    _add(tar, "sessions/{}/{}".format(sid, p.relative_to(sdir)), p.read_bytes())
        events = [e for e in util.read_jsonl(repo.paths.ledger)
                  if e.get("session_id") in sessions or e.get("head") in refs.values()]
        _add(tar, "ledger.jsonl", ("\n".join(json.dumps(e) for e in events) + "\n").encode("utf-8"))

        manifest = {
            "format": "checkpoint-core-bundle/1",
            "protocol_version": "0.6",
            "bundle_id": "bundle_{}".format(util.stamp()),
            "created_at": util.now_iso(),
            "source_repo_id": repo.identity().get("id"),
            "refs": refs, "tags": tag_map,
            "objects": len(oids), "sessions": len(sessions),
            "signatures": sig_count, "identities": idents,
            # legacy single-branch fields for back-compat
            "branch": branches[0] if branches else None,
            "head": next(iter(refs.values()), None),
        }
        manifest["manifest_hash"] = util.canonical_sha(manifest)
        _add(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return {"out_path": str(out_path), "objects": len(oids), "refs": list(refs.keys()),
            "tags": list(tag_map.keys()), "identities": idents}


def _rmtree(path: Path) -> None:
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


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))
