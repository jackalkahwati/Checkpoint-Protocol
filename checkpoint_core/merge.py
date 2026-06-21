"""Native three-way merge with line-level diff3. No Git.

Per path, against the merge base:
  - changed on only one side          -> take that side
  - both changed identically          -> take it
  - both changed (text), disjoint lines-> auto-merge (line-level diff3)
  - both changed (text), overlapping  -> conflict markers around the overlapping hunk
  - binary changed on both sides       -> conflict
  - one side deletes, other modifies   -> conflict
Semantic / AST-aware merge and rename detection are intentionally out of scope.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional, Tuple

from . import objects
from .store import Repo


def _tmap(repo: Repo, tree: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not tree:
        return {}
    return objects.tree_map(repo.get_object(tree))


def _blob_or_none(m: Dict[str, Dict[str, str]], path: str) -> Optional[str]:
    return m[path]["blob"] if path in m else None


def _decode_lines(repo: Repo, blob: Optional[str]) -> Optional[List[str]]:
    if blob is None:
        return []
    try:
        return repo.get_blob(blob).decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None  # binary


# ----------------------------------------------------------------- diff3 core

def diff3(base: List[str], ours: List[str], theirs: List[str]) -> List[Dict[str, Any]]:
    """Three-way line merge. Returns a list of chunks:
       {"type": "stable", "lines": [...]}
       {"type": "conflict", "ours": [...], "base": [...], "theirs": [...]}
    Disjoint changes resolve to stable chunks; overlapping changes become conflicts.
    """
    map_o = _line_map(base, ours)     # base index -> ours index (for lines equal in both)
    map_t = _line_map(base, theirs)
    anchors = [i for i in range(len(base)) if i in map_o and i in map_t]

    chunks: List[Dict[str, Any]] = []
    pb = po = pt = 0  # running positions in base/ours/theirs
    for i in anchors:
        bo, to = map_o[i], map_t[i]
        _emit_region(chunks, base[pb:i], ours[po:bo], theirs[pt:to])
        # the anchor line is common to all three
        _append_stable(chunks, [base[i]])
        pb, po, pt = i + 1, bo + 1, to + 1
    # trailing region after the last anchor
    _emit_region(chunks, base[pb:], ours[po:], theirs[pt:])
    return chunks


def _line_map(base: List[str], side: List[str]) -> Dict[int, int]:
    """base_index -> side_index for lines that are equal between base and side."""
    out: Dict[int, int] = {}
    for a, b, size in difflib.SequenceMatcher(None, base, side).get_matching_blocks():
        for k in range(size):
            out[a + k] = b + k
    return out


def _emit_region(chunks: List[Dict[str, Any]], base_r: List[str],
                 ours_r: List[str], theirs_r: List[str]) -> None:
    if base_r == ours_r and base_r == theirs_r:
        _append_stable(chunks, base_r)
    elif ours_r == base_r:                 # only theirs changed
        _append_stable(chunks, theirs_r)
    elif theirs_r == base_r:               # only ours changed
        _append_stable(chunks, ours_r)
    elif ours_r == theirs_r:               # both made the same change
        _append_stable(chunks, ours_r)
    else:                                  # genuine conflict
        chunks.append({"type": "conflict", "ours": ours_r, "base": base_r, "theirs": theirs_r})


def _append_stable(chunks: List[Dict[str, Any]], lines: List[str]) -> None:
    if not lines:
        return
    if chunks and chunks[-1]["type"] == "stable":
        chunks[-1]["lines"].extend(lines)
    else:
        chunks.append({"type": "stable", "lines": list(lines)})


def render(chunks: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Render chunks to text. Returns (has_conflict, content)."""
    has_conflict = any(c["type"] == "conflict" for c in chunks)
    out: List[str] = []

    def add(lines: List[str]) -> None:
        out.extend(lines)
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"

    for c in chunks:
        if c["type"] == "stable":
            out.extend(c["lines"])
        else:
            add([])  # ensure preceding content ends with newline
            out.append("<<<<<<< ours\n")
            add(c["ours"])
            out.append("=======\n")
            add(c["theirs"])
            out.append(">>>>>>> theirs\n")
    return has_conflict, "".join(out)


# ------------------------------------------------------------- per-file merge

def _merge_file(repo: Repo, base_blob: Optional[str], ours_blob: Optional[str],
                theirs_blob: Optional[str]) -> Dict[str, Any]:
    """Merge a single path that changed on both sides. Returns:
       {"conflict": bool, "content": bytes|None, "blob": <new blob id>|None, "reason": str}
    """
    # delete/modify conflict
    if ours_blob is None or theirs_blob is None:
        present = theirs_blob if ours_blob is None else ours_blob
        side = "theirs" if ours_blob is None else "ours"
        lines = _decode_lines(repo, present)
        if lines is None:
            return {"conflict": True, "content": repo.get_blob(present),
                    "blob": None, "reason": "delete/modify (binary)"}
        body = "<<<<<<< ours\n" + ("" if side == "ours" else "(deleted)\n")
        if side == "ours":
            body += "".join(lines)
            if not body.endswith("\n"):
                body += "\n"
        body += "=======\n"
        if side == "theirs":
            body += "".join(lines)
            if not body.endswith("\n"):
                body += "\n"
        else:
            body += "(deleted)\n"
        body += ">>>>>>> theirs\n"
        return {"conflict": True, "content": body.encode("utf-8"),
                "blob": None, "reason": "delete/modify"}

    base_lines = _decode_lines(repo, base_blob)
    ours_lines = _decode_lines(repo, ours_blob)
    theirs_lines = _decode_lines(repo, theirs_blob)
    if ours_lines is None or theirs_lines is None or base_lines is None:
        # binary on at least one side -> cannot line-merge
        return {"conflict": True, "content": repo.get_blob(ours_blob),
                "blob": None, "reason": "binary"}

    chunks = diff3(base_lines, ours_lines, theirs_lines)
    has_conflict, content = render(chunks)
    if has_conflict:
        return {"conflict": True, "content": content.encode("utf-8"),
                "blob": None, "reason": "overlapping"}
    blob_id = repo.put_blob(content.encode("utf-8"))
    return {"conflict": False, "content": content.encode("utf-8"),
            "blob": blob_id, "reason": "auto-merged"}


# ----------------------------------------------------------------- top level

def three_way(repo: Repo, ours_tree: Optional[str], theirs_tree: Optional[str],
              base_tree: Optional[str]) -> Dict[str, Any]:
    ours = _tmap(repo, ours_tree)
    theirs = _tmap(repo, theirs_tree)
    base = _tmap(repo, base_tree)

    all_paths = sorted(set(ours) | set(theirs) | set(base))
    entries: List[Dict[str, str]] = []
    conflicts: List[str] = []
    conflict_files: Dict[str, bytes] = {}
    auto_merged: List[str] = []

    for path in all_paths:
        o = _blob_or_none(ours, path)
        t = _blob_or_none(theirs, path)
        b = _blob_or_none(base, path)

        if o == t:
            chosen = o
        elif o == b:
            chosen = t
        elif t == b:
            chosen = o
        else:
            res = _merge_file(repo, b, o, t)
            if res["conflict"]:
                conflicts.append(path)
                conflict_files[path] = res["content"]
                continue
            chosen = res["blob"]
            auto_merged.append(path)

        if chosen is not None:
            mode = (ours.get(path) or theirs.get(path) or base.get(path) or {}).get("mode", "100644")
            entries.append({"path": path, "blob": chosen, "mode": mode})

    clean = not conflicts
    merged_tree_id = repo.put_object(objects.make_tree(entries)) if clean else None
    return {
        "clean": clean,
        "conflicts": conflicts,
        "conflict_files": conflict_files,
        "auto_merged": auto_merged,
        "merged_tree": merged_tree_id,
    }
