"""Shared helpers: time, ids, hashing, canonical serialization, json/jsonl io, styling.

No Git, no third-party deps beyond PyYAML (used only by config.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- time

def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat()


def stamp(dt: Optional[datetime] = None) -> str:
    return (dt or now()).strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------- ids

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_words: int = 6, max_len: int = 40) -> str:
    words = _SLUG_RE.sub(" ", (text or "").lower()).split()
    slug = "_".join(words[:max_words])[:max_len].strip("_")
    return slug or "session"


def session_id(instruction: str, dt: Optional[datetime] = None) -> str:
    return "cs_{}_{}".format(stamp(dt), slugify(instruction))


def seq_id(prefix: str, seq: int, dt: Optional[datetime] = None) -> str:
    return "{}_{}_{:03d}".format(prefix, stamp(dt), seq)


def event_id(dt: Optional[datetime] = None) -> str:
    return "evt_{}_{}".format(stamp(dt), hashlib.sha256(os.urandom(16)).hexdigest()[:6])


# --------------------------------------------------------- hashing / canonical form

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    """Deterministic JSON encoding used for content addressing of structured objects."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha(obj: Any) -> str:
    return sha256_bytes(canonical(obj))


# -------------------------------------------------------------------------- io

def read_json(path: Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def summarize_text(text: str, max_lines: int = 40, max_chars: int = 4000) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ["... [truncated] ..."] + lines[-max_lines:]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = "... [truncated] ...\n" + out[-max_chars:]
    return out


# ---------------------------------------------------------------- terminal styling

_NO_COLOR = bool(os.environ.get("NO_COLOR")) or not os.isatty(1)


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else "\033[{}m{}\033[0m".format(code, text)


def bold(t: str) -> str:
    return _c("1", t)


def green(t: str) -> str:
    return _c("32", t)


def red(t: str) -> str:
    return _c("31", t)


def yellow(t: str) -> str:
    return _c("33", t)


def dim(t: str) -> str:
    return _c("2", t)


def cyan(t: str) -> str:
    return _c("36", t)
