"""Rollback planning and execution. Restores the working tree to a target Git tree.

Safety: callers take a pre-rollback snapshot first, and execution is preview-only
unless the caller passes execute=True.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from .store import Repo


def plan(repo: Repo, target_tree: str, current_tree: str) -> Dict[str, List[str]]:
    """Diff target vs current. Returns files to restore / delete / (added) keep."""
    restore: List[str] = []   # modified or deleted-since-target -> bring back
    added: List[str] = []     # created since target -> would be deleted by --hard
    for status, path in repo.git.diff_name_status(target_tree, current_tree):
        # status is target->current: 'A' means present now but not in target (added).
        if status == "A":
            added.append(path)
        else:  # M, D, R, T, etc. -> restore target version
            restore.append(path)
    return {"restore": restore, "added": added}


def execute(
    repo: Repo,
    target_tree: str,
    current_tree: str,
    delete_added: bool,
) -> Dict[str, Any]:
    """Restore the target tree. Optionally delete files added since the target."""
    actions = plan(repo, target_tree, current_tree)

    # Restore every file present in the target tree (overwrites modified, recreates deleted).
    repo.git.restore_tree(target_tree, repo.paths.tmp_index("rollback-index"))

    deleted: List[str] = []
    if delete_added:
        for rel in actions["added"]:
            fpath = repo.root / rel
            try:
                if fpath.exists():
                    fpath.unlink()
                    deleted.append(rel)
                    _prune_empty_dirs(repo.root, fpath.parent)
            except OSError:
                pass

    return {
        "restored": actions["restore"],
        "deleted": deleted,
        "kept": [] if delete_added else actions["added"],
    }


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
