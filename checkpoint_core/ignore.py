"""Native ignore rules (no Git). gitignore-style globs from .checkpointignore.

Always ignores .checkpoint/ (the store) and .git/. Matching is intentionally simple
and predictable: fnmatch against the relative POSIX path and each path segment, with
trailing-slash patterns matching directories.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import List

ALWAYS = [".checkpoint", ".git"]

DEFAULT_CHECKPOINTIGNORE = """\
# .checkpointignore — paths Checkpoint Core should never capture.
# gitignore-style globs. .checkpoint/ and .git/ are always ignored.
# Examples:
# *.log
# build/
# node_modules/
# __pycache__/
"""


class Ignore:
    def __init__(self, patterns: List[str]):
        self.dir_patterns: List[str] = []
        self.glob_patterns: List[str] = []
        for raw in patterns:
            p = raw.strip()
            if not p or p.startswith("#"):
                continue
            if p.endswith("/"):
                self.dir_patterns.append(p.rstrip("/"))
            else:
                self.glob_patterns.append(p)

    @classmethod
    def load(cls, root: Path) -> "Ignore":
        patterns: List[str] = list(ALWAYS)
        f = Path(root) / ".checkpointignore"
        if f.exists():
            patterns += f.read_text(encoding="utf-8").splitlines()
        return cls(patterns)

    def ignored(self, rel_path: str) -> bool:
        rel = rel_path.replace("\\", "/")
        segments = rel.split("/")
        # directory-name patterns: match any segment
        for d in self.dir_patterns + [a for a in ALWAYS]:
            if d in segments:
                return True
            if fnmatch.fnmatch(rel, d) or fnmatch.fnmatch(rel, d + "/*"):
                return True
        for g in self.glob_patterns:
            if fnmatch.fnmatch(rel, g):
                return True
            # match basename too (e.g. "*.log")
            if fnmatch.fnmatch(segments[-1], g):
                return True
            # match files under a matched dir prefix
            if "/" not in g and any(fnmatch.fnmatch(seg, g) for seg in segments[:-1]):
                return True
        return False
