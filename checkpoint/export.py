"""Export a portable, secret-redacted session bundle as a .tar.gz."""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import util
from . import secrets as secretscan
from .ledger import for_session
from .session import Session
from .store import Repo

# Files inside a session whose text content gets redacted before export.
_REDACT_SUFFIXES = (".patch", ".txt", ".json")


def _redact_bytes(name: str, data: bytes) -> Tuple[bytes, List[Dict[str, Any]]]:
    findings: List[Dict[str, Any]] = []
    if not name.endswith(_REDACT_SUFFIXES):
        return data, findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, findings
    findings = secretscan.scan_text(text, source=name)
    if findings:
        text = secretscan.redact(text)
    return text.encode("utf-8"), findings


def _redact_blob(name: str, data: bytes) -> Tuple[bytes, List[Dict[str, Any]]]:
    """Redact secret values in a content-addressed blob if it is decodable text."""
    findings: List[Dict[str, Any]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, findings  # binary blob: leave as-is
    findings = secretscan.scan_text(text, source=name)
    if findings:
        text = secretscan.redact(text)
    return text.encode("utf-8"), findings


def export_session(repo: Repo, session_id: str, out_path: Path) -> Dict[str, Any]:
    session = Session.load(repo, session_id)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_findings: List[Dict[str, Any]] = []
    sess_dir = session.dir

    with tarfile.open(out_path, "w:gz") as tar:
        # 1. Session tree (metadata, instruction, snapshots, diffs, verification, packet).
        for path in sorted(sess_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(sess_dir.parent)  # sessions/<id>/...
            data = path.read_bytes()
            data, findings = _redact_bytes(path.name, data)
            all_findings += findings
            _add_bytes(tar, str(rel), data)

        # 2. Ledger events for this session only.
        events = for_session(repo, session_id)
        ledger_bytes = ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")
        _add_bytes(tar, "ledger.jsonl", ledger_bytes)

        # 3. Referenced content-addressed objects (file blobs from snapshots).
        #    These are raw file contents, so scan and redact text blobs too.
        objects = _referenced_objects(session)
        for rel in sorted(objects):
            blob = repo.paths.base / rel
            if not blob.exists():
                continue
            data = blob.read_bytes()
            redacted, findings = _redact_blob(rel, data)
            all_findings += findings
            _add_bytes(tar, rel, redacted)

        # 4. Manifest.
        manifest = {
            "format": "checkpoint-session-bundle/1",
            "exported_at": util.now_iso(),
            "session_id": session_id,
            "object_count": len(objects),
            "secret_findings": all_findings,
            "redacted": bool(all_findings),
        }
        _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))

    return {"out_path": str(out_path), "secret_findings": all_findings}


def _referenced_objects(session: Session) -> List[str]:
    objects: List[str] = []
    snaps_dir = session.dir / "snapshots"
    if snaps_dir.exists():
        for snap_json in snaps_dir.rglob("snapshot.json"):
            snap = util.read_json(snap_json, {})
            for f in snap.get("changed_files", []):
                if f.get("object"):
                    objects.append(f["object"])
    return sorted(set(objects))


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))
