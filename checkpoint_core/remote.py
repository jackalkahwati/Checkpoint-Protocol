"""Hardened remote sync for Checkpoint Core. No Git.

Principle: NEVER trust the remote. A remote can advertise refs and object ids, but local
Checkpoint verifies object hashes, schemas, seals, parent chains, reachability, and
(optionally) signatures BEFORE any ref moves. Remote-tracking refs are written by fetch;
local branch heads only move on a verified fast-forward pull. Filesystem and bundle
remotes only; the model is designed so HTTP remotes can be added later.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import objects, sign as signmod, util
from . import reachable as R
from . import sync as syncmod
from .store import Repo

PROTOCOL_VERSION = "0.6"


# ----------------------------------------------------------------- remote config

def list_remotes(repo: Repo) -> Dict[str, Any]:
    return repo.config.remotes()


def get_remote(repo: Repo, name: str) -> Optional[Dict[str, Any]]:
    return repo.config.remotes().get(name)


def add_remote(repo: Repo, name: str, rtype: str, path: str, **kw) -> Dict[str, Any]:
    cfg = repo.config
    spec = {"type": rtype, "path": path}
    spec.update(kw)
    cfg.data.setdefault("remotes", {})[name] = spec
    cfg.save()
    return spec


def remove_remote(repo: Repo, name: str) -> bool:
    cfg = repo.config
    remotes = cfg.data.setdefault("remotes", {})
    if name in remotes:
        del remotes[name]
        cfg.save()
        return True
    return False


def remote_repo(spec: Dict[str, Any]) -> Repo:
    if spec.get("type") not in ("filesystem", "path"):
        raise ValueError("only filesystem remotes are supported (got {})".format(spec.get("type")))
    loc = Path(spec["path"])
    rr = Repo(loc)
    if not rr.initialized:
        raise ValueError("remote store is not initialized: {}".format(loc))
    return rr


# ----------------------------------------------------------------- atomic refs

def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.{}".format(os.getpid()))
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def atomic_update_ref(repo: Repo, ref: str, oid: str) -> None:
    _atomic_write(repo.ref_path(ref), (oid + "\n").encode("utf-8"))


# ----------------------------------------------------------------- object copy

def copy_object_verified(src: Repo, dst: Repo, oid: str) -> int:
    """Copy one object, verifying its content hash matches its id. Returns bytes written."""
    raw = (src.paths.objects / oid[:2] / oid).read_bytes()
    if util.sha256_bytes(raw) != oid:
        raise ValueError("remote object {} failed content-hash check".format(oid))
    dest = dst.paths.objects / oid[:2] / oid
    if not dest.exists():
        _atomic_write(dest, raw)
    return len(raw)


# ------------------------------------------------------- closure verification

def verify_received(repo: Repo, head: Optional[str], require_signatures: bool = False) -> Tuple[bool, List[str]]:
    """Verify the accepted-snapshot closure reachable from `head` (already in `repo`)."""
    errs: List[str] = []
    if not head:
        return True, errs
    seen: Set[str] = set()
    stack = [head]
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        kind, snap = R.classify(repo, sid)
        if kind == "missing":
            errs.append("missing object {}".format(sid))
            continue
        if kind != "snapshot":
            errs.append("ref target {} is not a snapshot ({})".format(sid, kind))
            continue
        tref = snap.get("tree")
        tkind, _ = R.classify(repo, tref) if tref else ("missing", None)
        if not tref or tkind == "missing":
            errs.append("snapshot {} -> missing tree".format(sid))
        elif tkind != "tree":
            errs.append("snapshot {} tree is not a tree".format(sid))
        else:
            for e in repo.get_object(tref).get("entries", []):
                if R.classify(repo, e.get("blob"))[0] == "missing":
                    errs.append("tree {} -> missing blob {}".format(tref, e.get("blob")))
        if snap.get("kind") == objects.KIND_ACCEPTED and not objects.verify_seal(snap):
            errs.append("snapshot {} has an invalid seal".format(sid))
        for p in snap.get("parents", []) or []:
            pk, _ = R.classify(repo, p)
            if pk == "missing":
                errs.append("snapshot {} has missing parent {} (broken chain)".format(sid, p))
            elif pk != "snapshot":
                errs.append("snapshot {} parent {} is not a snapshot".format(sid, p))
            else:
                stack.append(p)
        if require_signatures:
            sigs = signmod.signatures_for(repo, sid)
            if not sigs:
                errs.append("snapshot {} is unsigned (policy requires signatures)".format(sid))
            elif not any(signmod.verify_record(repo, s)["ok"] for s in sigs):
                errs.append("snapshot {} has no valid signature".format(sid))
    return (not errs), errs


# ----------------------------------------------------------------- aux transfer

def _snapshot_oids(src: Repo, oids: Set[str]) -> List[str]:
    out = []
    for oid in oids:
        kind, _ = R.classify(src, oid)
        if kind == "snapshot":
            out.append(oid)
    return out


def _transfer_aux(src: Repo, dst: Repo, oids: Set[str], cfg: Dict[str, Any]) -> Dict[str, int]:
    counts = {"signatures": 0, "identities": 0, "sessions": 0}
    snap_oids = _snapshot_oids(src, oids)

    # signatures for transferred snapshots
    for oid in snap_oids:
        sdir = src.paths.signatures / oid
        if sdir.exists():
            for f in sorted(sdir.iterdir()):
                if f.is_file():
                    _atomic_write(dst.paths.signatures / oid / f.name, f.read_bytes())
                    counts["signatures"] += 1

    # PUBLIC identities only (never keys/). Imported as untrusted; don't clobber local trust.
    if cfg.get("transfer_public_identities", True) and src.paths.identities.exists():
        for f in sorted(src.paths.identities.iterdir()):
            if f.is_file() and f.suffix == ".json":
                dest = dst.paths.identities / f.name
                if dest.exists():
                    continue
                rec = util.read_json(f, {})
                rec["trusted"] = False
                rec.setdefault("revoked", False)
                import json as _j
                _atomic_write(dest, _j.dumps(rec, indent=2).encode("utf-8"))
                counts["identities"] += 1

    # sessions (selective; autosaves only if explicitly enabled)
    if cfg.get("transfer_sessions", True):
        sids = set()
        for oid in snap_oids:
            try:
                s = src.get_object(oid).get("session")
            except Exception:
                s = None
            if s:
                sids.add(s)
        for sid in sids:
            _transfer_session(src, dst, sid, cfg)
            counts["sessions"] += 1
            # also copy objects the session references (base tree, intermediate snapshots,
            # verification/packet trees) so the receiver's store stays self-consistent
            for oid in _session_object_ids(src, sid):
                if not dst.has_object(oid):
                    try:
                        copy_object_verified(src, dst, oid)
                    except (ValueError, OSError):
                        pass
    return counts


def _tree_closure(src: Repo, tree_id: Optional[str]) -> Set[str]:
    out: Set[str] = set()
    if not tree_id:
        return out
    kind, obj = R.classify(src, tree_id)
    if kind != "tree" or not obj:
        return out
    out.add(tree_id)
    for e in obj.get("entries", []):
        if e.get("blob"):
            out.add(e["blob"])
    return out


def _session_object_ids(src: Repo, sid: str) -> Set[str]:
    """All objects a session references: base tree/head, snapshots, result, verification/packet trees."""
    out: Set[str] = set()
    sess = util.read_json(src.paths.session_dir(sid) / "session.json", None)
    if not sess:
        return out
    base = sess.get("base", {}) or {}
    out |= _tree_closure(src, base.get("tree"))
    if base.get("head"):
        out |= syncmod.reachable_objects(src, base["head"])
    for s in sess.get("snapshots", []) or []:
        out |= syncmod.reachable_objects(src, s)
    res = sess.get("result") or {}
    if res.get("snapshot"):
        out |= syncmod.reachable_objects(src, res["snapshot"])
    for vid in sess.get("verifications", []) or []:
        rec = util.read_json(src.paths.session_dir(sid) / "verification" / (vid + ".json"), None)
        if rec:
            out |= _tree_closure(src, rec.get("tree"))
    pkt = util.read_json(src.paths.session_dir(sid) / "packet.json", None)
    if pkt:
        out |= _tree_closure(src, pkt.get("base_tree"))
        out |= _tree_closure(src, pkt.get("current_tree"))
    return out


def _transfer_session(src: Repo, dst: Repo, sid: str, cfg: Dict[str, Any]) -> None:
    sdir = src.paths.session_dir(sid)
    if not sdir.exists():
        return
    want_packets = cfg.get("transfer_packets", True)
    want_ver = cfg.get("transfer_verification_records", True)
    want_auto = cfg.get("transfer_autosaves", False)
    for p in sorted(sdir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sdir)
        parts = rel.parts
        if parts[0] == "autosaves" and not want_auto:
            continue
        if parts[0] == "packet.json" and not want_packets:
            continue
        if parts[0] == "verification" and not want_ver:
            continue
        _atomic_write(dst.paths.session_dir(sid) / rel, p.read_bytes())


# ----------------------------------------------------------------- planning

def transfer_plan(local: Repo, remote: Repo, branch: str) -> Dict[str, Any]:
    lhead = local.read_ref("refs/heads/{}".format(branch))
    rhead = remote.read_ref("refs/heads/{}".format(branch))
    local_oids = syncmod.reachable_objects(local, lhead) if lhead else set()
    remote_oids = syncmod.reachable_objects(remote, rhead) if rhead else set()
    return {
        "branch": branch,
        "local_head": lhead,
        "remote_head": rhead,
        "missing_locally": sorted(remote_oids - local_oids),
        "missing_remotely": sorted(local_oids - remote_oids),
    }


def _relationship(repo: Repo, local_head: Optional[str], other_head: Optional[str]) -> str:
    if local_head == other_head:
        return "up-to-date"
    if other_head is None:
        return "ahead"
    if local_head is None:
        return "behind"
    if repo.is_ancestor(local_head, other_head):
        return "behind"          # other is ahead of local -> we can fast-forward to it
    if repo.is_ancestor(other_head, local_head):
        return "ahead"           # local is ahead of other
    return "diverged"


# ----------------------------------------------------------------- fetch

def fetch(repo: Repo, name: str, branches: Optional[List[str]] = None, tags: bool = False,
          verify_signatures: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    spec = get_remote(repo, name)
    if not spec:
        raise ValueError("no such remote: {}".format(name))
    rr = remote_repo(spec)
    cfg = repo.config.sync()
    require_sigs = verify_signatures or bool(spec.get("require_signed_snapshots"))
    blist = branches or rr.list_branches()
    report: Dict[str, Any] = {"remote": name, "dry_run": dry_run, "branches": [],
                              "objects_copied": 0, "refs_updated": [], "errors": []}

    for b in blist:
        rhead = rr.read_ref("refs/heads/{}".format(b))
        if not rhead:
            continue
        oids = syncmod.reachable_objects(rr, rhead)
        missing = [o for o in oids if not repo.has_object(o)]
        entry = {"branch": b, "remote_head": rhead, "missing": len(missing)}
        if dry_run:
            report["branches"].append(entry)
            continue
        # Copy what we can; a bad/missing/hash-mismatched object is simply skipped here and
        # caught by verify_received below, which then refuses the ref update.
        for o in missing:
            try:
                copy_object_verified(rr, repo, o)
                report["objects_copied"] += 1
            except (ValueError, OSError):
                continue
        _transfer_aux(rr, repo, oids, cfg)
        ok, errs = verify_received(repo, rhead, require_signatures=require_sigs)
        if not ok:
            report["errors"].extend(["{}: {}".format(b, e) for e in errs])
            entry["status"] = "rejected (verification failed)"
            report["branches"].append(entry)
            continue
        atomic_update_ref(repo, "refs/remotes/{}/{}".format(name, b), rhead)
        entry["status"] = "fetched"
        report["refs_updated"].append("refs/remotes/{}/{}".format(name, b))
        report["branches"].append(entry)

    if tags:
        _fetch_tags(repo, rr, require_sigs, report, cfg, dry_run)

    return report


def _fetch_tags(repo, rr, require_sigs, report, cfg, dry_run) -> None:
    tdir = rr.paths.base / "refs" / "tags"
    if not tdir.exists():
        return
    report.setdefault("tags", [])
    for tf in sorted(tdir.iterdir()):
        if not tf.is_file():
            continue
        target = tf.read_text(encoding="utf-8").strip()
        oids = syncmod.reachable_objects(rr, target)
        if dry_run:
            report["tags"].append({"tag": tf.name, "target": target})
            continue
        try:
            for o in oids:
                if not repo.has_object(o):
                    copy_object_verified(rr, repo, o)
        except ValueError as exc:
            report["errors"].append("tag {}: {}".format(tf.name, exc))
            continue
        _transfer_aux(rr, repo, oids, cfg)
        ok, errs = verify_received(repo, target, require_signatures=require_sigs)
        if ok:
            atomic_update_ref(repo, "refs/tags/{}".format(tf.name), target)
            report["tags"].append({"tag": tf.name, "target": target, "status": "fetched"})
        else:
            report["errors"].extend(["tag {}: {}".format(tf.name, e) for e in errs])


# ----------------------------------------------------------------- pull

def pull(repo: Repo, name: str, branch: str, verify_signatures: bool = False,
         dry_run: bool = False) -> Dict[str, Any]:
    if dry_run:
        # plan only: fetch nothing, just report relationship using current tracking ref
        rr = remote_repo(get_remote(repo, name))
        rhead = rr.read_ref("refs/heads/{}".format(branch))
        lhead = repo.read_ref("refs/heads/{}".format(branch))
        rel = "unknown"
        if rhead and lhead and repo.has_object(rhead):
            rel = _relationship(repo, lhead, rhead)
        return {"remote": name, "branch": branch, "dry_run": True, "status": "dry-run",
                "local_head": lhead, "remote_head": rhead, "relationship": rel, "updated": False}

    fetch_report = fetch(repo, name, branches=[branch], verify_signatures=verify_signatures)
    rhead = repo.read_ref("refs/remotes/{}/{}".format(name, branch))
    lhead = repo.read_ref("refs/heads/{}".format(branch))
    result = {"remote": name, "branch": branch, "dry_run": False,
              "local_head": lhead, "remote_head": rhead, "fetch": fetch_report, "updated": False}
    if fetch_report["errors"]:
        result["status"] = "fetch-failed"
        return result
    if not rhead:
        result["status"] = "no-remote-branch"
        return result
    if lhead == rhead:
        result["status"] = "up-to-date"
        return result
    if lhead is None or repo.is_ancestor(lhead, rhead):
        atomic_update_ref(repo, "refs/heads/{}".format(branch), rhead)
        result["updated"] = True
        result["status"] = "fast-forward"
        result["new_head"] = rhead
        return result
    if repo.is_ancestor(rhead, lhead):
        result["status"] = "up-to-date"   # local already ahead
        return result
    result["status"] = "diverged"
    return result


# ----------------------------------------------------------------- push

def push(repo: Repo, name: str, branch: str, tags: bool = False,
         force_with_lease: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    spec = get_remote(repo, name)
    if not spec:
        raise ValueError("no such remote: {}".format(name))
    rr = remote_repo(spec)
    cfg = repo.config.sync()
    lhead = repo.read_ref("refs/heads/{}".format(branch))
    if not lhead:
        return {"remote": name, "branch": branch, "status": "nothing-to-push", "dry_run": dry_run}
    rhead = rr.read_ref("refs/heads/{}".format(branch))

    ff = rhead is None or repo.is_ancestor(rhead, lhead)
    forced = False
    if not ff:
        if force_with_lease is None and not cfg.get("allow_force_push", False):
            return {"remote": name, "branch": branch, "status": "rejected-non-fast-forward",
                    "remote_head": rhead, "local_head": lhead, "dry_run": dry_run}
        expected = force_with_lease
        if expected in (None, ""):
            expected = repo.read_ref("refs/remotes/{}/{}".format(name, branch))
        if rhead != expected:
            return {"remote": name, "branch": branch, "status": "rejected-stale-lease",
                    "remote_head": rhead, "expected": expected, "dry_run": dry_run}
        forced = True

    oids = syncmod.reachable_objects(repo, lhead)
    missing = [o for o in oids if not rr.has_object(o)]
    result = {"remote": name, "branch": branch, "local_head": lhead, "remote_head": rhead,
              "missing_on_remote": len(missing), "forced": forced, "dry_run": dry_run}
    if dry_run:
        result["status"] = "would-push"
        return result

    for o in missing:
        copy_object_verified(repo, rr, o)
    _transfer_aux(repo, rr, oids, cfg)
    atomic_update_ref(rr, "refs/heads/{}".format(branch), lhead)
    atomic_update_ref(repo, "refs/remotes/{}/{}".format(name, branch), lhead)

    if tags:
        result["tags"] = _push_tags(repo, rr, cfg)

    result["status"] = "pushed"
    result["objects_sent"] = len(missing)
    return result


def _push_tags(repo, rr, cfg) -> List[str]:
    tdir = repo.paths.base / "refs" / "tags"
    pushed = []
    if not tdir.exists():
        return pushed
    for tf in sorted(tdir.iterdir()):
        if not tf.is_file():
            continue
        target = tf.read_text(encoding="utf-8").strip()
        for o in syncmod.reachable_objects(repo, target):
            if not rr.has_object(o):
                copy_object_verified(repo, rr, o)
        _transfer_aux(repo, rr, syncmod.reachable_objects(repo, target), cfg)
        atomic_update_ref(rr, "refs/tags/{}".format(tf.name), target)
        pushed.append(tf.name)
    return pushed


# ----------------------------------------------------------------- sync status

def sync_status(repo: Repo, name: str, branch: Optional[str] = None) -> Dict[str, Any]:
    spec = get_remote(repo, name)
    if not spec:
        raise ValueError("no such remote: {}".format(name))
    rr = remote_repo(spec)
    branches = [branch] if branch else sorted(set(repo.list_branches()) | set(rr.list_branches()))
    out = {"remote": name, "branches": []}
    for b in branches:
        lhead = repo.read_ref("refs/heads/{}".format(b))
        rhead = rr.read_ref("refs/heads/{}".format(b))
        plan = transfer_plan(repo, rr, b)
        rel = "unknown"
        # relationship requires both heads present locally to walk ancestry
        if lhead and rhead:
            if repo.has_object(rhead):
                rel = _relationship(repo, lhead, rhead)
            else:
                rel = "behind (fetch needed)"
        elif rhead and not lhead:
            rel = "behind"
        elif lhead and not rhead:
            rel = "ahead"
        else:
            rel = "absent"
        out["branches"].append({
            "branch": b, "local_head": lhead, "remote_head": rhead, "relationship": rel,
            "missing_locally": len(plan["missing_locally"]),
            "missing_remotely": len(plan["missing_remotely"]),
        })
    return out


# ----------------------------------------------------------------- bootstrap

def bootstrap_store(root: Path, branch: str = "main") -> Repo:
    """Create an empty Checkpoint store at root (used by clone)."""
    from .config import Config, default_config
    repo = Repo(root)
    p = repo.paths
    for d in (p.base, p.objects, p.sessions, p.refs_heads, p.tmp, p.cache,
              p.identities, p.signatures):
        d.mkdir(parents=True, exist_ok=True)
    if not p.ledger.exists():
        p.ledger.touch()
    cfg = Config(default_config(project=Path(root).name), p.config)
    cfg.data["default_branch"] = branch
    cfg.save()
    repo._config = None
    if not p.identity.exists():
        util.write_json(p.identity, {"id": "anon", "name": "", "email": ""})
    repo.set_head_to_branch(branch)
    repo.write_state({"active_session": None})
    return repo
