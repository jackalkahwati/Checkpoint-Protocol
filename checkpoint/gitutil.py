"""Thin wrapper over the `git` CLI. Checkpoint never re-implements Git logic.

State capture uses a temporary index so the user's real index is never disturbed:
    GIT_INDEX_FILE=<tmp> git read-tree HEAD   (if HEAD exists)
    GIT_INDEX_FILE=<tmp> git add -A -- . <excludes>
    GIT_INDEX_FILE=<tmp> git write-tree       -> tree SHA
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Git's empty-tree object hash (sha1 repos). Used as base when there is no HEAD.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = Path(root)

    # -------------------------------------------------------------- core runner
    def run(
        self,
        args: List[str],
        check: bool = True,
        index_file: Optional[Path] = None,
        capture: bool = True,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if index_file is not None:
            env["GIT_INDEX_FILE"] = str(index_file)
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(self.root),
            env=env,
            text=True,
            capture_output=capture,
        )
        if check and proc.returncode != 0:
            raise GitError(
                "git " + " ".join(args) + " failed:\n" + (proc.stderr or proc.stdout or "")
            )
        return proc

    def out(self, args: List[str], **kw) -> str:
        return self.run(args, **kw).stdout.strip()

    # ------------------------------------------------------------- repo queries
    @staticmethod
    def is_repo(path: Path) -> bool:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            text=True,
            capture_output=True,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    @staticmethod
    def toplevel(path: Path) -> Optional[Path]:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            return None
        return Path(proc.stdout.strip())

    def has_head(self) -> bool:
        return self.run(["rev-parse", "--verify", "-q", "HEAD"], check=False).returncode == 0

    def head(self) -> Optional[str]:
        if not self.has_head():
            return None
        return self.out(["rev-parse", "HEAD"])

    def branch(self) -> str:
        # symbolic-ref reports the branch name even on an unborn branch (no commits).
        name = self.out(["symbolic-ref", "--short", "-q", "HEAD"], check=False)
        if name:
            return name
        name = self.out(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        return name or "(detached)"

    def status_porcelain(self) -> str:
        return self.out(["status", "--porcelain"])

    def is_clean(self) -> bool:
        return self.status_porcelain() == ""

    def has_conflicts(self) -> bool:
        # porcelain conflict markers: UU, AA, DD, AU, UA, DU, UD
        for line in self.status_porcelain().splitlines():
            code = line[:2]
            if code in ("UU", "AA", "DD", "AU", "UA", "DU", "UD"):
                return True
        return False

    # --------------------------------------------------- working-tree -> tree
    def write_worktree_tree(self, index_file: Path, excludes: Optional[List[str]] = None) -> str:
        """Capture the current non-ignored working tree as a Git tree object SHA."""
        index_file = Path(index_file)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        if index_file.exists():
            index_file.unlink()
        # Seed from HEAD so deletions are represented relative to committed state.
        if self.has_head():
            self.run(["read-tree", "HEAD"], index_file=index_file)
        # .checkpoint/ is gitignored (and carries its own `*` ignore) so it is
        # skipped automatically. Extra .checkpointignore patterns are exclude pathspecs.
        extra = []
        for pat in excludes or []:
            pat = pat.strip()
            if pat and not pat.startswith("#"):
                extra.append(":(exclude)" + pat)
        if extra:
            self.run(["add", "-A", "--", "."] + extra, index_file=index_file)
        else:
            self.run(["add", "-A"], index_file=index_file)
        return self.out(["write-tree"], index_file=index_file)

    # ----------------------------------------------------------------- diffs
    def diff(self, a: str, b: str, paths: Optional[List[str]] = None) -> str:
        args = ["diff", a, b]
        if paths:
            args += ["--"] + paths
        return self.run(args).stdout

    def diff_stat(self, a: str, b: str) -> str:
        return self.out(["diff", "--stat", a, b])

    def diff_shortstat(self, a: str, b: str) -> str:
        return self.out(["diff", "--shortstat", a, b])

    def diff_name_status(self, a: str, b: str) -> List[Tuple[str, str]]:
        """Return [(status, path), ...] between two trees. Renames -> ('R', newpath)."""
        raw = self.out(["diff", "--name-status", "-M", a, b])
        out: List[Tuple[str, str]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            code = parts[0]
            if code.startswith("R") and len(parts) >= 3:
                out.append(("R", parts[2]))
            elif len(parts) >= 2:
                out.append((code[0], parts[1]))
        return out

    def diff_name_only(self, a: str, b: str) -> List[str]:
        """Changed paths between two trees, without rename detection (renames -> add+delete)."""
        raw = self.out(["diff", "--name-only", a, b])
        return [ln for ln in raw.splitlines() if ln.strip()]

    def numstat(self, a: str, b: str) -> Dict[str, int]:
        """Aggregate insertions/deletions/files between two trees."""
        raw = self.out(["diff", "--numstat", a, b])
        ins = dele = files = 0
        for line in raw.splitlines():
            if not line.strip():
                continue
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            files += 1
            if cols[0].isdigit():
                ins += int(cols[0])
            if cols[1].isdigit():
                dele += int(cols[1])
        return {"files_changed": files, "insertions": ins, "deletions": dele}

    # ------------------------------------------------------------ object read
    def cat_blob_at(self, tree: str, path: str) -> Optional[bytes]:
        """Read a file's bytes from a tree, or None if absent."""
        proc = subprocess.run(
            ["git", "cat-file", "blob", "{}:{}".format(tree, path)],
            cwd=str(self.root),
            capture_output=True,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout

    # --------------------------------------------------------------- restore
    def restore_tree(self, tree: str, index_file: Path) -> None:
        """Materialize all files of `tree` into the working tree (overwrite/create)."""
        index_file = Path(index_file)
        if index_file.exists():
            index_file.unlink()
        index_file.parent.mkdir(parents=True, exist_ok=True)
        self.run(["read-tree", tree], index_file=index_file)
        self.run(["checkout-index", "-a", "-f"], index_file=index_file)

    # ----------------------------------------------------------------- commit
    def add_all(self) -> None:
        self.run(["add", "-A"])

    def stage_paths(self, paths: List[str]) -> None:
        """Stage exactly these paths (including deletions). No-op if empty."""
        if not paths:
            return
        self.run(["add", "-A", "--"] + paths)

    def commit(self, message: str, allow_empty: bool = False) -> str:
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self.run(args)
        return self.head() or ""

    def staged_changes(self) -> bool:
        return self.run(["diff", "--cached", "--quiet"], check=False).returncode != 0
