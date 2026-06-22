"""Native diff: structured tree diff + unified content diff (difflib). No Git."""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from . import objects
from .store import Repo


def _tmap(repo: Repo, tree_id: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not tree_id:
        return {}
    return objects.tree_map(repo.get_object(tree_id))


def tree_diff(repo: Repo, a_tree: Optional[str], b_tree: Optional[str]) -> Dict[str, Any]:
    """Structured diff between two trees. Statuses: added/modified/deleted/renamed."""
    a = _tmap(repo, a_tree)
    b = _tmap(repo, b_tree)
    files: List[Dict[str, Any]] = []

    a_paths, b_paths = set(a), set(b)
    added = b_paths - a_paths
    deleted = a_paths - b_paths
    common = a_paths & b_paths

    # rename detection: a deleted path and an added path sharing a blob id
    del_by_blob = {a[p]["blob"]: p for p in deleted}
    renamed_from: Dict[str, str] = {}
    for p in list(added):
        blob = b[p]["blob"]
        if blob in del_by_blob:
            src = del_by_blob.pop(blob)
            renamed_from[p] = src
            added.discard(p)
            deleted.discard(src)

    insertions = deletions = 0
    for p in sorted(common):
        if a[p]["blob"] != b[p]["blob"]:
            ins, dele = _line_counts(repo, a[p]["blob"], b[p]["blob"])
            insertions += ins
            deletions += dele
            files.append({"path": p, "status": "modified",
                          "old_blob": a[p]["blob"], "new_blob": b[p]["blob"]})
    for p in sorted(added):
        ins, _ = _line_counts(repo, None, b[p]["blob"])
        insertions += ins
        files.append({"path": p, "status": "added", "old_blob": None, "new_blob": b[p]["blob"]})
    for p in sorted(deleted):
        _, dele = _line_counts(repo, a[p]["blob"], None)
        deletions += dele
        files.append({"path": p, "status": "deleted", "old_blob": a[p]["blob"], "new_blob": None})
    for new, src in sorted(renamed_from.items()):
        files.append({"path": new, "status": "renamed", "from": src,
                      "old_blob": a[src]["blob"], "new_blob": b[new]["blob"]})

    files.sort(key=lambda f: f["path"])
    return {
        "files": files,
        "stats": {"files_changed": len(files), "insertions": insertions, "deletions": deletions},
    }


def _decode(repo: Repo, blob: Optional[str]) -> Optional[List[str]]:
    if blob is None:
        return []
    data = repo.get_blob(blob)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary
    return text.splitlines(keepends=True)


def _line_counts(repo: Repo, a_blob: Optional[str], b_blob: Optional[str]):
    a_lines = _decode(repo, a_blob)
    b_lines = _decode(repo, b_blob)
    if a_lines is None or b_lines is None:
        return (0, 0)  # binary: counted as 1 file change, no line stats
    sm = difflib.SequenceMatcher(a=a_lines, b=b_lines)
    ins = dele = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            dele += (i2 - i1)
        if tag in ("replace", "insert"):
            ins += (j2 - j1)
    return (ins, dele)


def diff_result(repo: Repo, a_tree: Optional[str], b_tree: Optional[str],
                detect_renames: bool = True) -> Dict[str, Any]:
    """Rename-aware structured diff. Returns added/deleted/modified/renamed + stats."""
    from . import rename as renamemod
    a = _tmap(repo, a_tree)
    b = _tmap(repo, b_tree)
    a_paths, b_paths = set(a), set(b)
    raw_added = b_paths - a_paths
    raw_deleted = a_paths - b_paths
    common = a_paths & b_paths
    modified = sorted(p for p in common if a[p]["blob"] != b[p]["blob"])

    rename_records: List[Dict[str, Any]] = []
    added = sorted(raw_added)
    deleted = sorted(raw_deleted)
    if detect_renames:
        opts = renamemod.options(repo)
        rename_records, added, deleted = renamemod.detect(
            repo,
            {p: a[p]["blob"] for p in raw_deleted},
            {p: b[p]["blob"] for p in raw_added},
            opts,
        )

    ins = dele = 0
    for p in modified:
        i, d = _line_counts(repo, a[p]["blob"], b[p]["blob"])
        ins += i
        dele += d
    for p in added:
        i, _ = _line_counts(repo, None, b[p]["blob"])
        ins += i
    for p in deleted:
        _, d = _line_counts(repo, a[p]["blob"], None)
        dele += d
    for r in rename_records:
        if r["old_blob_id"] != r["new_blob_id"]:
            i, d = _line_counts(repo, r["old_blob_id"], r["new_blob_id"])
            ins += i
            dele += d

    files_changed = len(added) + len(deleted) + len(modified) + len(rename_records)
    return {
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "renamed": rename_records,
        "directory_renames": renamemod.directory_summary(rename_records) if detect_renames else [],
        "stats": {"files_changed": files_changed, "insertions": ins, "deletions": dele},
    }


def unified_result(repo: Repo, a_tree: Optional[str], b_tree: Optional[str],
                   detect_renames: bool = True) -> str:
    """Rename-aware unified diff text (rename headers + content diffs for rename+edit)."""
    dr = diff_result(repo, a_tree, b_tree, detect_renames)
    out: List[str] = []
    a = _tmap(repo, a_tree)
    b = _tmap(repo, b_tree)
    for r in dr["renamed"]:
        pct = int(round(r["similarity"] * 100))
        out.append("rename {} => {} ({}%, {})\n".format(
            r["old_path"], r["new_path"], pct, r["kind"]))
        if r["old_blob_id"] != r["new_blob_id"]:
            al = _decode(repo, r["old_blob_id"])
            bl = _decode(repo, r["new_blob_id"])
            if al is None or bl is None:
                out.append("# binary content changed\n")
            else:
                out.append("".join(difflib.unified_diff(
                    al, bl, fromfile="a/" + r["old_path"], tofile="b/" + r["new_path"])))
    for p in dr["modified"]:
        al = _decode(repo, a[p]["blob"])
        bl = _decode(repo, b[p]["blob"])
        if al is None or bl is None:
            out.append("# binary file changed: {}\n".format(p))
        else:
            out.append("".join(difflib.unified_diff(al, bl, fromfile="a/" + p, tofile="b/" + p)))
    for p in dr["added"]:
        bl = _decode(repo, b[p]["blob"])
        if bl is None:
            out.append("# binary file added: {}\n".format(p))
        else:
            out.append("".join(difflib.unified_diff([], bl, fromfile="/dev/null", tofile="b/" + p)))
    for p in dr["deleted"]:
        al = _decode(repo, a[p]["blob"])
        if al is None:
            out.append("# binary file deleted: {}\n".format(p))
        else:
            out.append("".join(difflib.unified_diff(al, [], fromfile="a/" + p, tofile="/dev/null")))
    return "".join(out)


def unified(repo: Repo, a_tree: Optional[str], b_tree: Optional[str]) -> str:
    """Unified-diff text for all changed files between two trees."""
    td = tree_diff(repo, a_tree, b_tree)
    out: List[str] = []
    for f in td["files"]:
        path = f["path"]
        a_lines = _decode(repo, f["old_blob"])
        b_lines = _decode(repo, f["new_blob"])
        if a_lines is None or b_lines is None:
            out.append("# binary file changed: {} ({})\n".format(path, f["status"]))
            continue
        frm = "a/" + (f.get("from") or path)
        to = "b/" + path
        diff = difflib.unified_diff(a_lines, b_lines, fromfile=frm, tofile=to)
        out.append("".join(diff))
    return "".join(out)
