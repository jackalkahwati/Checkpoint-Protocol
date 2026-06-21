"""Native object model: blobs, trees, snapshots. Content-addressed by SHA-256.

Blobs are raw bytes. Trees and snapshots are canonical JSON. None of this depends
on Git — these are Checkpoint's own primitives.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import util

KIND_ACCEPTED = "accepted"
KIND_SNAPSHOT = "snapshot"
KIND_AUTOSAVE = "autosave"


def make_tree(entries: List[Dict[str, str]]) -> Dict[str, Any]:
    """entries: list of {path, blob, mode}. Returns a canonical tree object."""
    norm = sorted(
        ({"path": e["path"], "blob": e["blob"], "mode": e.get("mode", "100644")}
         for e in entries),
        key=lambda e: e["path"],
    )
    return {"type": "tree", "entries": norm}


def tree_map(tree: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """path -> {blob, mode} for easy lookup."""
    return {e["path"]: {"blob": e["blob"], "mode": e.get("mode", "100644")}
            for e in tree.get("entries", [])}


def make_snapshot(
    tree: str,
    parents: List[str],
    session: Optional[str],
    kind: str,
    message: Optional[str],
    author: Dict[str, str],
    timestamp: str,
    verification: Optional[str] = None,
    signature: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "type": "snapshot",
        "tree": tree,
        "parents": list(parents),
        "session": session,
        "kind": kind,
        "message": message,
        "author": author,
        "timestamp": timestamp,
        "verification": verification,
    }
    if signature is not None:
        snap["signature"] = signature
    return snap


def seal_fields(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The subset of a snapshot covered by the SHA-256 content seal (§6)."""
    return {
        "tree": snap["tree"],
        "parents": snap["parents"],
        "session": snap["session"],
        "message": snap["message"],
        "author": snap["author"],
        "timestamp": snap["timestamp"],
    }


def compute_seal(snap: Dict[str, Any]) -> str:
    return util.canonical_sha(seal_fields(snap))


def sign(snap: Dict[str, Any], author_id: str) -> Dict[str, Any]:
    """Attach a SHA-256 content seal. Returns a new dict (snap unchanged)."""
    sealed = dict(snap)
    sealed["signature"] = {
        "algo": "sha256-seal",
        "author": author_id,
        "seal": compute_seal(snap),
    }
    return sealed


def verify_seal(snap: Dict[str, Any]) -> bool:
    sig = snap.get("signature")
    if not sig or sig.get("algo") != "sha256-seal":
        return False
    return sig.get("seal") == compute_seal(snap)
