"""gc: safe garbage collection of unreachable objects. No Git.

Never deletes anything reachable from a protected root (accepted history, branch heads,
tags, active sessions, retained autosaves/snapshots, verification/packet trees). Deletes
only unreachable objects older than the grace period, moving them to a quarantine first
for crash-safety. Runs fsck first and refuses to delete if the store is corrupt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import fsck as fsckmod
from . import reachable as R
from . import util
from .store import Repo


def collect(repo: Repo, dry_run: bool = False, aggressive: bool = False,
            force: bool = False) -> Dict[str, Any]:
    gcfg = repo.config.gc()
    grace = 0.0 if aggressive else float(gcfg.get("grace_period_days", 14))
    keep_auto = (0.0 if aggressive else float(gcfg.get("keep_autosaves_days", 14)))
    keep_rej = float(gcfg.get("keep_rejected_sessions_days", 30))
    use_quarantine = bool(gcfg.get("quarantine", True))

    skipped: Dict[str, int] = {"reachable": 0, "within_grace": 0}

    # 1) integrity gate
    fsck_report = None
    if gcfg.get("require_fsck_before_delete", True) and not force:
        fsck_report = fsckmod.check(repo, strict=False, aggressive=aggressive)
        if fsck_report["result"] == "corrupt":
            return {
                "aborted": True,
                "reason": "fsck reported corruption; refusing to gc (use --force to override)",
                "fsck": fsck_report,
                "dry_run": dry_run,
            }

    # 2) purge expired quarantine (crash-safe two-stage delete)
    purged = _purge_quarantine(repo, float(gcfg.get("quarantine_days", 7))) if not dry_run else 0

    # 3) reachability
    walk = R.compute_reachable(repo, aggressive=aggressive,
                               keep_autosaves_days=keep_auto, keep_rejected_days=keep_rej)
    reachable = walk["reachable"]

    all_ids = list(R.iter_object_ids(repo))
    objects_scanned = len(all_ids)
    candidates: List[str] = []
    for oid in all_ids:
        if oid in reachable:
            skipped["reachable"] += 1
            continue
        if R.object_age_days(repo, oid) < grace:
            skipped["within_grace"] += 1
            continue
        candidates.append(oid)

    bytes_reclaimed = sum(R.object_size(repo, oid) for oid in candidates)

    if dry_run:
        return {
            "aborted": False, "dry_run": True,
            "objects_scanned": objects_scanned, "reachable": len(reachable & set(all_ids)),
            "candidates": sorted(candidates), "quarantined": 0, "deleted": 0,
            "bytes_reclaimed": bytes_reclaimed, "skipped": skipped,
            "purged_quarantine": 0, "fsck": fsck_report,
        }

    # 4) move candidates to quarantine (or delete outright if disabled)
    quarantined = 0
    deleted = 0
    qroot = repo.paths.base / "quarantine" / util.stamp()
    manifest: List[Dict[str, Any]] = []
    for oid in candidates:
        src = R.object_file(repo, oid)
        size = R.object_size(repo, oid)
        if use_quarantine:
            dest = qroot / oid[:2] / oid
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                src.replace(dest)
                quarantined += 1
                manifest.append({"id": oid, "size": size})
            except OSError:
                pass
        else:
            try:
                src.unlink()
                deleted += 1
                manifest.append({"id": oid, "size": size})
            except OSError:
                pass

    if use_quarantine and manifest:
        util.write_json(qroot / "manifest.json", {
            "quarantined_at": util.now_iso(),
            "aggressive": aggressive,
            "objects": manifest,
        })

    report = {
        "aborted": False, "dry_run": False,
        "objects_scanned": objects_scanned, "reachable": len(reachable & set(all_ids)),
        "candidates": sorted(candidates),
        "quarantined": quarantined, "deleted": deleted,
        "bytes_reclaimed": bytes_reclaimed, "skipped": skipped,
        "purged_quarantine": purged, "fsck": fsck_report,
    }
    return report


def _purge_quarantine(repo: Repo, quarantine_days: float) -> int:
    qbase = repo.paths.base / "quarantine"
    if not qbase.exists():
        return 0
    purged = 0
    for batch in sorted(qbase.iterdir()):
        if not batch.is_dir():
            continue
        manifest = util.read_json(batch / "manifest.json", None)
        ts = manifest.get("quarantined_at") if manifest else None
        age = R._age_days(ts) if ts else _dir_age_days(batch)
        if age >= quarantine_days:
            _rmtree(batch)
            purged += 1
    return purged


def _dir_age_days(path: Path) -> float:
    try:
        return (util.now().timestamp() - path.stat().st_mtime) / 86400.0
    except OSError:
        return 1e9


def _rmtree(path: Path) -> None:
    for p in sorted(path.rglob("*"), reverse=True):
        try:
            p.unlink() if p.is_file() else p.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
