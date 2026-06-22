"""Best-effort secret scanning and redaction for shareable artifacts.

Detection is heuristic and never a guarantee. It runs before writing packets and
export bundles so secret *values* do not leave the local recovery store.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Dict, List

REDACTION = "***REDACTED***"

DEFAULT_ALLOW_TEMPLATE = """\
# .checkpoint/secrets-allow — paths where secret findings are known false positives
# (e.g. test fixtures, docs with example credentials). gitignore-style globs, one per line.
# Lines beginning with '#' are comments. Use sparingly; this disables secret detection
# for the matched paths only.
# Examples:
# tests/
# docs/
# path/to/example.py
"""

# (type, compiled regex). Patterns aim for high-signal, low-noise matches.
_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("github_token", re.compile(r"\bgh[posu]_[0-9A-Za-z]{36,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("generic_secret_assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|client[_-]?secret|access[_-]?token)\b"
        r"\s*[=:]\s*['\"][^'\"]{8,}['\"]")),
]

# Filenames that are themselves sensitive.
_SENSITIVE_FILES = re.compile(r"(^|/)(\.env(\.[\w.-]+)?|id_rsa|id_ed25519|id_dsa|\.pem|\.p12|\.pfx)$")


def _file_is_sensitive(path: str) -> bool:
    p = path.strip()
    if _SENSITIVE_FILES.search(p):
        return True
    base = p.rsplit("/", 1)[-1]
    if base == ".env" or base.startswith(".env."):
        return True
    if base.endswith((".pem", ".p12", ".pfx", ".key")):
        return True
    return False


def scan_text(text: str, source: str = "") -> List[Dict[str, object]]:
    """Return findings: {file, line, type} with no secret values."""
    findings: List[Dict[str, object]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, rx in _PATTERNS:
            if rx.search(line):
                findings.append({"file": source, "line": lineno, "type": kind})
    return findings


def scan_paths(paths: List[str]) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []
    for p in paths:
        if _file_is_sensitive(p):
            findings.append({"file": p, "line": 0, "type": "sensitive_filename"})
    return findings


def scan_diff(diff_text: str) -> List[Dict[str, object]]:
    """Scan a unified diff. Only inspects added lines (`+`)."""
    findings: List[Dict[str, object]] = []
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            current_file = line[4:].strip()
            if current_file.startswith("b/"):
                current_file = current_file[2:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            for kind, rx in _PATTERNS:
                if rx.search(line):
                    findings.append({"file": current_file, "line": 0, "type": kind})
    return findings


def redact(text: str) -> str:
    """Replace detected secret values with a redaction marker."""
    out = text
    for _kind, rx in _PATTERNS:
        out = rx.sub(REDACTION, out)
    return out


# ----------------------------------------------------------------- allowlist

def load_allow(allow_file: Path) -> List[str]:
    """Read gitignore-style path globs from a `secrets-allow` file (missing -> [])."""
    f = Path(allow_file)
    if not f.exists():
        return []
    out = []
    for raw in f.read_text(encoding="utf-8").splitlines():
        p = raw.strip()
        if p and not p.startswith("#"):
            out.append(p.rstrip("/"))
    return out


def _path_allowed(path: str, globs: List[str]) -> bool:
    rel = str(path).replace("\\", "/")
    segments = rel.split("/")
    for g in globs:
        g = g.rstrip("/")                                   # tolerate "tests/" and "tests"
        if g in segments:                                   # directory name anywhere
            return True
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g + "/*"):
            return True
        if fnmatch.fnmatch(segments[-1], g):                # basename glob (e.g. *.test.py)
            return True
    return False


def filter_findings(findings: List[Dict[str, object]], globs: List[str]) -> List[Dict[str, object]]:
    """Drop findings whose file matches an allowlist glob."""
    if not globs:
        return findings
    return [f for f in findings if not _path_allowed(str(f.get("file", "")), globs)]
