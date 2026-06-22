"""Working-directory engine: scan files into a native tree, materialize a tree back
to disk, and compute status. Pure Checkpoint Core — no Git.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import objects
from .ignore import Ignore
from .store import Repo


def _iter_files(root: Path, ig: Ignore):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        # prune ignored directories in place
        kept = []
        for d in dirnames:
            rel = (rel_dir + "/" + d) if rel_dir else d
            if not ig.ignored(rel) and not ig.ignored(d):
                kept.append(d)
        dirnames[:] = kept
        for fn in filenames:
            rel = (rel_dir + "/" + fn) if rel_dir else fn
            if ig.ignored(rel):
                continue
            yield rel, Path(dirpath) / fn


def scan_to_tree(repo: Repo, max_file_mb: Optional[float] = None) -> str:
    """Capture the working directory as a native tree object. Returns the tree id.

    max_file_mb: if set, files larger than this are skipped (used by autosave to stay
    cheap). Skipped paths are not represented in the tree.
    """
    ig = Ignore.load(repo.root)
    limit = int(max_file_mb * 1024 * 1024) if max_file_mb else None
    entries: List[Dict[str, str]] = []
    for rel, abspath in _iter_files(repo.root, ig):
        if abspath.is_symlink():
            # store the link target as content (mode 120000)
            data = os.readlink(abspath).encode("utf-8")
            blob = repo.put_blob(data)
            entries.append({"path": rel, "blob": blob, "mode": "120000"})
            continue
        try:
            if limit is not None and abspath.stat().st_size > limit:
                continue
            data = abspath.read_bytes()
        except OSError:
            continue
        blob = repo.put_blob(data)
        mode = "100755" if os.access(abspath, os.X_OK) else "100644"
        entries.append({"path": rel, "blob": blob, "mode": mode})
    tree = objects.make_tree(entries)
    return repo.put_object(tree)


def large_files(repo: Repo, max_file_mb: float) -> set:
    """Current non-ignored files exceeding the size limit (protected from deletion)."""
    ig = Ignore.load(repo.root)
    limit = int(max_file_mb * 1024 * 1024)
    out = set()
    for rel, abspath in _iter_files(repo.root, ig):
        try:
            if not abspath.is_symlink() and abspath.stat().st_size > limit:
                out.add(rel)
        except OSError:
            pass
    return out


def materialize(repo: Repo, tree_id: str, delete_extra: bool = False,
                only_paths: Optional[List[str]] = None,
                protect: Optional[set] = None) -> Dict[str, List[str]]:
    """Write a tree's files into the working directory.

    delete_extra: remove non-ignored working files that are not in the tree.
    only_paths: if given, restrict writes/deletes to these paths.
    protect: paths that must never be deleted (e.g. large files skipped by autosave).
    """
    tree = repo.get_object(tree_id)
    tmap = objects.tree_map(tree)
    restrict = set(only_paths) if only_paths is not None else None
    protect = protect or set()

    written: List[str] = []
    for path, meta in tmap.items():
        if restrict is not None and path not in restrict:
            continue
        dest = repo.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = repo.get_blob(meta["blob"])
        if meta.get("mode") == "120000":
            target = data.decode("utf-8")
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            os.symlink(target, dest)
        else:
            with open(dest, "wb") as fh:
                fh.write(data)
            if meta.get("mode") == "100755":
                os.chmod(dest, 0o755)
        written.append(path)

    deleted: List[str] = []
    if delete_extra:
        ig = Ignore.load(repo.root)
        current = {rel for rel, _ in _iter_files(repo.root, ig)}
        for rel in current - set(tmap.keys()):
            if restrict is not None and rel not in restrict:
                continue
            if rel in protect:
                continue
            try:
                (repo.root / rel).unlink()
                deleted.append(rel)
                _prune_empty_dirs(repo.root, (repo.root / rel).parent)
            except OSError:
                pass

    return {"written": written, "deleted": deleted}


def status(repo: Repo, base_tree: Optional[str]) -> Dict[str, Any]:
    """Compare the working directory to base_tree. Returns added/modified/deleted."""
    from .diff import tree_diff
    current = scan_to_tree(repo)
    return tree_diff(repo, base_tree, current)


def _prune_empty_dirs(root: Path, start: Path) -> None:
    cur = start
    root = root.resolve()
    while cur.resolve() != root and cur.exists():
        try:
            if not any(cur.iterdir()):
                cur.rmdir()
                cur = cur.parent
            else:
                break
        except OSError:
            break
