"""Native file-level three-way merge with conflict markers. No Git.

For each path, compare ours/theirs against the merge base:
  - only one side changed  -> take that side
  - both changed identically -> take it
  - both changed differently  -> CONFLICT (write standard markers, no auto-merge)
Line-level (diff3) merging is a documented future upgrade.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import objects
from .store import Repo


def _tmap(repo: Repo, tree: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not tree:
        return {}
    return objects.tree_map(repo.get_object(tree))


def _blob_or_none(m: Dict[str, Dict[str, str]], path: str) -> Optional[str]:
    return m[path]["blob"] if path in m else None


def _conflict_text(repo: Repo, ours: Optional[str], theirs: Optional[str]) -> Optional[bytes]:
    def text(blob):
        if blob is None:
            return ""
        try:
            return repo.get_blob(blob).decode("utf-8")
        except UnicodeDecodeError:
            return None
    o, t = text(ours), text(theirs)
    if o is None or t is None:
        return None  # binary conflict — cannot produce markers
    body = "<<<<<<< ours\n" + o
    if not o.endswith("\n"):
        body += "\n"
    body += "=======\n" + t
    if not t.endswith("\n"):
        body += "\n"
    body += ">>>>>>> theirs\n"
    return body.encode("utf-8")


def three_way(repo: Repo, ours_tree: Optional[str], theirs_tree: Optional[str],
              base_tree: Optional[str]) -> Dict[str, Any]:
    ours = _tmap(repo, ours_tree)
    theirs = _tmap(repo, theirs_tree)
    base = _tmap(repo, base_tree)

    all_paths = sorted(set(ours) | set(theirs) | set(base))
    merged_entries: List[Dict[str, str]] = []
    conflicts: List[str] = []
    conflict_files: Dict[str, bytes] = {}

    for path in all_paths:
        o = _blob_or_none(ours, path)
        t = _blob_or_none(theirs, path)
        b = _blob_or_none(base, path)

        if o == t:
            chosen = o
        elif o == b:        # ours unchanged from base -> take theirs
            chosen = t
        elif t == b:        # theirs unchanged from base -> take ours
            chosen = o
        else:               # both changed differently -> conflict
            conflicts.append(path)
            text = _conflict_text(repo, o, t)
            if text is not None:
                conflict_files[path] = text
            # leave "ours" version as the placeholder blob in the (unused) tree
            chosen = o
            continue

        if chosen is not None:
            mode = (ours.get(path) or theirs.get(path) or base.get(path) or {}).get("mode", "100644")
            merged_entries.append({"path": path, "blob": chosen, "mode": mode})

    clean = not conflicts
    merged_tree_id = None
    if clean:
        merged_tree_id = repo.put_object(objects.make_tree(merged_entries))

    return {
        "clean": clean,
        "conflicts": conflicts,
        "conflict_files": conflict_files,
        "merged_tree": merged_tree_id,
    }
