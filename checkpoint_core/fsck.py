"""fsck: read-only integrity check of the Checkpoint store. No Git, never mutates.

Walks refs -> snapshots -> trees -> blobs and verifies hashes, seals, references,
parent chains, sessions, timeline, and rename records. Returns a structured report and a
result of healthy | warnings | corrupt.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import objects, util
from . import reachable as R
from .store import Repo


def check(repo: Repo, strict: bool = False, aggressive: bool = False) -> Dict[str, Any]:
    fcfg = repo.config.fsck()
    gcfg = repo.config.gc()
    errors: List[str] = []
    warnings: List[str] = []
    corrupt: List[Dict[str, str]] = []
    missing: List[Dict[str, str]] = []

    all_ids = list(R.iter_object_ids(repo))
    objects_scanned = len(all_ids)

    # type map for conflicting-type detection: oid -> set of expected types from references
    expected_types: Dict[str, set] = {}

    def expect(oid: str, typ: str, ref_by: str) -> None:
        expected_types.setdefault(oid, set()).add(typ)

    # 1) hash integrity + classification of every object on disk
    classified: Dict[str, str] = {}
    for oid in all_ids:
        raw = R.load_raw(repo, oid)
        if raw is None:
            continue
        if fcfg.get("verify_object_hashes", True) and util.sha256_bytes(raw) != oid:
            corrupt.append({"id": oid, "reason": "content hash does not match id (rewritten/corrupt)"})
        kind, _ = R.classify(repo, oid)
        classified[oid] = kind

    # 2) walk reachability (also surfaces referenced-but-missing objects)
    walk = R.compute_reachable(
        repo, aggressive=aggressive,
        keep_autosaves_days=float(gcfg.get("keep_autosaves_days", 14)),
        keep_rejected_days=float(gcfg.get("keep_rejected_sessions_days", 30)),
    )
    reachable = walk["reachable"]
    for m in walk["missing_refs"]:
        missing.append(m)
        errors.append("missing object {} (referenced by {})".format(m["id"], m["referenced_by"]))

    # 3) structural checks on every snapshot/tree object present
    for oid in all_ids:
        kind = classified.get(oid, "blob")
        if kind == "snapshot":
            snap = repo.get_object(oid)
            # tree must exist and be a tree
            tref = snap.get("tree")
            expect(tref, "tree", oid)
            tkind, _ = R.classify(repo, tref) if tref else ("missing", None)
            if tref and tkind == "missing":
                errors.append("snapshot {} -> missing tree {}".format(oid, tref))
            elif tref and tkind != "tree":
                errors.append("snapshot {} -> object {} is not a tree ({})".format(oid, tref, tkind))
            # parents must exist and be snapshots
            for p in snap.get("parents", []) or []:
                expect(p, "snapshot", oid)
                pk, _ = R.classify(repo, p)
                if pk == "missing":
                    errors.append("snapshot {} has missing parent {} (broken chain)".format(oid, p))
                elif pk != "snapshot":
                    errors.append("snapshot {} parent {} is not a snapshot ({})".format(oid, p, pk))
            # accepted snapshots must carry a valid seal
            if snap.get("kind") == objects.KIND_ACCEPTED and fcfg.get("verify_seals", True):
                if not objects.verify_seal(snap):
                    errors.append("accepted snapshot {} has an invalid seal".format(oid))
        elif kind == "tree":
            tree = repo.get_object(oid)
            for e in tree.get("entries", []):
                b = e.get("blob")
                expect(b, "blob", oid)
                if b and R.classify(repo, b)[0] == "missing":
                    errors.append("tree {} -> missing blob {} ({})".format(oid, b, e.get("path")))

    # 4) refs point at valid accepted snapshots
    refs_scanned = 0
    for kind_dir in ("heads", "tags"):
        d = repo.paths.base / "refs" / kind_dir
        if d.exists():
            for ref in sorted(d.iterdir()):
                if not ref.is_file():
                    continue
                refs_scanned += 1
                target = ref.read_text(encoding="utf-8").strip()
                k, snap = R.classify(repo, target)
                if k == "missing":
                    errors.append("ref {}/{} -> missing snapshot {}".format(kind_dir, ref.name, target))
                elif k != "snapshot":
                    errors.append("ref {}/{} -> {} is not a snapshot".format(kind_dir, ref.name, target))
                elif snap.get("kind") != objects.KIND_ACCEPTED:
                    errors.append("ref {}/{} -> snapshot {} is not 'accepted'".format(kind_dir, ref.name, target))

    # 5) sessions, timeline, rename records
    sessions_scanned = 0
    for sid in repo.session_ids():
        sjson = repo.paths.session_dir(sid) / "session.json"
        try:
            sess = util.read_json(sjson, None)
        except Exception:
            errors.append("session {} has malformed session.json".format(sid))
            continue
        if sess is None:
            errors.append("session {} has missing session.json".format(sid))
            continue
        sessions_scanned += 1

        if fcfg.get("verify_timeline", True):
            tl = repo.paths.session_dir(sid) / "timeline.jsonl"
            if tl.exists():
                try:
                    for ev in util.read_jsonl(tl):
                        if "type" not in ev or "timestamp" not in ev:
                            warnings.append("session {} timeline event missing fields".format(sid))
                except Exception:
                    errors.append("session {} has malformed timeline.jsonl".format(sid))

        if fcfg.get("verify_renames", True):
            pkt = util.read_json(repo.paths.session_dir(sid) / "packet.json", None)
            if pkt:
                for r in pkt.get("rename_records", []) or []:
                    for key in ("old_blob_id", "new_blob_id"):
                        b = r.get(key)
                        if b and R.classify(repo, b)[0] == "missing":
                            errors.append("session {} rename record references missing blob {}".format(sid, b))

    # 6) conflicting-type ids
    for oid, types in expected_types.items():
        if len(types) > 1:
            errors.append("object {} is referenced as conflicting types: {}".format(oid, sorted(types)))

    # 7) unknown object types (structured but not tree/snapshot)
    import json as _json
    for oid in all_ids:
        raw = R.load_raw(repo, oid)
        if raw is None:
            continue
        try:
            obj = _json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(obj, dict) and "type" in obj and obj["type"] not in R.KNOWN_TYPES:
            warnings.append("object {} has unknown type '{}'".format(oid, obj["type"]))

    # 8) reachability accounting (dangling = unreachable, present on disk)
    present = set(all_ids)
    unreachable = sorted(present - reachable)
    if strict and unreachable:
        for oid in unreachable:
            warnings.append("dangling object {}".format(oid))

    # result
    if corrupt or errors:
        result = "corrupt"
    elif warnings and strict:
        result = "corrupt"  # strict promotes warnings to a failing result
    elif warnings:
        result = "warnings"
    else:
        result = "healthy"

    return {
        "objects_scanned": objects_scanned,
        "refs_scanned": refs_scanned,
        "sessions_scanned": sessions_scanned,
        "reachable": len(reachable & present),
        "dangling": len(unreachable),
        "corrupt": corrupt,
        "missing": missing,
        "warnings": warnings,
        "errors": errors,
        "result": result,
    }


def exit_code(report: Dict[str, Any], strict: bool = False) -> int:
    if report["result"] == "corrupt":
        return 2
    if report["result"] == "warnings" and strict:
        return 1
    return 0
