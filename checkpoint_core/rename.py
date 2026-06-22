"""Native rename detection. No Git, deterministic.

Turns delete+add pairs into renames so diffs, merges, history, and review survive moved
files. Detects: exact renames (identical content), similar renames / rename+edit (content
similarity above a threshold), and directory renames (a consistent prefix move). Binary
files support exact rename detection only. Semantic/AST-aware detection is out of scope.
"""
from __future__ import annotations

import difflib
import posixpath
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from . import util
from .store import Repo

KIND_EXACT = "exact"
KIND_SIMILAR = "similar"
KIND_RENAME_EDIT = "rename_edit"
KIND_DIRECTORY = "directory"


def options(repo: Repo) -> Dict[str, Any]:
    cfg = repo.config.rename_detection()
    return {
        "enabled": cfg.get("enabled", True),
        "threshold": float(cfg.get("similarity_threshold", 0.60)),
        "max_candidates": int(cfg.get("max_candidates", 10000)),
        "detect_directory_renames": cfg.get("detect_directory_renames", True),
        "binary_exact_only": cfg.get("binary_exact_only", True),
    }


def _lines(repo: Repo, blob: str) -> Optional[List[str]]:
    try:
        return repo.get_blob(blob).decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None  # binary


def _record(old_path: str, new_path: str, similarity: float, old_blob: str,
            new_blob: str, kind: str, confidence: float) -> Dict[str, Any]:
    return {
        "old_path": old_path,
        "new_path": new_path,
        "similarity": round(similarity, 4),
        "old_blob_id": old_blob,
        "new_blob_id": new_blob,
        "kind": kind,
        "confidence": round(confidence, 4),
        "detected_at": util.now_iso(),
    }


def detect(repo: Repo, deleted: Dict[str, str], added: Dict[str, str],
           opts: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """deleted/added: path -> blob_id. Returns (rename_records, remaining_added, remaining_deleted)."""
    if not opts.get("enabled", True) or not deleted or not added:
        return [], sorted(added), sorted(deleted)

    dele = dict(deleted)
    add = dict(added)
    records: List[Dict[str, Any]] = []

    # 1) exact renames by content hash (works for text AND binary).
    add_by_blob: Dict[str, List[str]] = defaultdict(list)
    for p, b in add.items():
        add_by_blob[b].append(p)
    for d_path in sorted(list(dele.keys())):
        b = dele[d_path]
        if add_by_blob.get(b):
            a_path = sorted(add_by_blob[b])[0]
            add_by_blob[b].remove(a_path)
            records.append(_record(d_path, a_path, 1.0, b, b, KIND_EXACT, 1.0))
            del dele[d_path]
            del add[a_path]

    # 2) similar renames / rename+edit (text only; deterministic).
    threshold = opts.get("threshold", 0.60)
    text_del = {p: b for p, b in dele.items() if _lines(repo, b) is not None}
    text_add = {p: b for p, b in add.items() if _lines(repo, b) is not None}
    if text_del and text_add and (len(text_del) * len(text_add) <= opts.get("max_candidates", 10000)):
        # cache decoded lines once per file (bounded by candidate guard above)
        dl_cache = {p: _lines(repo, b) for p, b in text_del.items()}
        al_cache = {p: _lines(repo, b) for p, b in text_add.items()}
        pairs: List[Tuple[float, str, str]] = []
        for d_path, dlines in dl_cache.items():
            for a_path, alines in al_cache.items():
                sm = difflib.SequenceMatcher(None, dlines, alines)
                if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
                    continue
                s = sm.ratio()
                if s >= threshold:
                    pairs.append((s, d_path, a_path))
        # greedy best-first, deterministic tie-break by paths
        pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
        used_d: set = set()
        used_a: set = set()
        for s, d_path, a_path in pairs:
            if d_path in used_d or a_path in used_a:
                continue
            used_d.add(d_path)
            used_a.add(a_path)
            records.append(_record(d_path, a_path, s, dele[d_path], add[a_path],
                                   KIND_RENAME_EDIT, s))
        for d_path in used_d:
            del dele[d_path]
        for a_path in used_a:
            del add[a_path]

    # 3) directory renames: a consistent prefix move (>=2 files), then sweep leftovers.
    if opts.get("detect_directory_renames", True):
        _directory_renames(records, dele, add)

    return records, sorted(add), sorted(dele)


def _directory_renames(records: List[Dict[str, Any]], dele: Dict[str, str],
                       add: Dict[str, str]) -> None:
    # learn old_dir -> new_dir from same-basename matches already found
    moves: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in records:
        od, nd = posixpath.dirname(r["old_path"]), posixpath.dirname(r["new_path"])
        if od != nd and posixpath.basename(r["old_path"]) == posixpath.basename(r["new_path"]):
            moves[(od, nd)] += 1
    trusted = {k for k, c in moves.items() if c >= 2}
    if not trusted:
        return
    # mark already-found renames that belong to a trusted directory move
    for r in records:
        key = (posixpath.dirname(r["old_path"]), posixpath.dirname(r["new_path"]))
        if key in trusted:
            r["kind"] = KIND_DIRECTORY
    # sweep leftover same-basename files under a trusted mapping
    add_by_key = {(posixpath.dirname(p), posixpath.basename(p)): p for p in add}
    for d_path in sorted(list(dele.keys())):
        od, base = posixpath.dirname(d_path), posixpath.basename(d_path)
        matched = None
        for (o, n) in trusted:
            if o == od and (n, base) in add_by_key:
                matched = add_by_key[(n, base)]
                break
        if matched:
            records.append(_record(d_path, matched, moves_confidence(moves, od),
                                   dele[d_path], add[matched], KIND_DIRECTORY, 0.9))
            del dele[d_path]
            del add[matched]


def moves_confidence(moves: Dict[Tuple[str, str], int], old_dir: str) -> float:
    best = max((c for (o, _n), c in moves.items() if o == old_dir), default=1)
    return min(1.0, 0.5 + 0.1 * best)


def directory_summary(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in records:
        if r["kind"] == KIND_DIRECTORY:
            counts[(posixpath.dirname(r["old_path"]), posixpath.dirname(r["new_path"]))] += 1
    return [{"old_dir": o, "new_dir": n, "count": c} for (o, n), c in sorted(counts.items())]


def detect_between(repo: Repo, base_map: Dict[str, Dict[str, str]],
                   side_map: Dict[str, Dict[str, str]],
                   opts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rename records mapping base paths -> side paths (used by merge)."""
    deleted = {p: base_map[p]["blob"] for p in base_map if p not in side_map}
    added = {p: side_map[p]["blob"] for p in side_map if p not in base_map}
    records, _a, _d = detect(repo, deleted, added, opts)
    return records
