"""Extra ignore rules beyond .gitignore (which Git enforces during capture).

`.checkpointignore` uses gitignore-style glob lines. They are passed to Git as
`:(exclude)<pattern>` pathspecs so capture skips them.
"""
from __future__ import annotations

from pathlib import Path
from typing import List


def read_checkpointignore(repo_root: Path) -> List[str]:
    path = Path(repo_root) / ".checkpointignore"
    if not path.exists():
        return []
    patterns: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


DEFAULT_CHECKPOINTIGNORE = """\
# .checkpointignore — extra paths Checkpoint should never capture.
# gitignore-style globs. .checkpoint/ is always excluded automatically.
# Examples:
# *.log
# tmp/
# secrets/
"""
