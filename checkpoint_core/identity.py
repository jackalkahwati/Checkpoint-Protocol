"""Identities, Ed25519 keypairs, and the local trust store. No Git.

An identity is a human, AI agent, CI runner, machine, or service that can sign protocol
events. Public IdentityRecords live in .checkpoint/identities/; private seeds live in
.checkpoint/keys/ with 0600 permissions and are NEVER exported, captured by autosave, or
seen by gc/fsck reachability (they are not objects, and .checkpoint/ is never scanned).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ed25519, util
from .store import Repo

TYPES = ("human", "agent", "ci", "machine", "service")


# ---------------------------------------------------------------------- helpers

def _hex(b: bytes) -> str:
    return b.hex()


def _unhex(s: str) -> bytes:
    return bytes.fromhex(s)


def record_path(repo: Repo, identity_id: str) -> Path:
    return repo.paths.identities / (identity_id + ".json")


def key_path(repo: Repo, identity_id: str) -> Path:
    return repo.paths.keys / (identity_id + ".key")


def has_private(repo: Repo, identity_id: str) -> bool:
    return key_path(repo, identity_id).exists()


# --------------------------------------------------------------------- creation

def create(repo: Repo, name: str, id_type: str = "human",
           email: Optional[str] = None, labels: Optional[List[str]] = None,
           capabilities: Optional[List[str]] = None) -> Dict[str, Any]:
    if id_type not in TYPES:
        raise ValueError("invalid identity type: {}".format(id_type))
    seed, pub = ed25519.generate()
    fp = ed25519.fingerprint(pub)
    identity_id = "id_{}_{}".format(id_type, ed25519.short_fingerprint(pub))
    record = {
        "identity_id": identity_id,
        "name": name,
        "type": id_type,
        "public_key": _hex(pub),
        "key_algorithm": ed25519.ALGORITHM,
        "fingerprint": fp,
        "created_at": util.now_iso(),
        "labels": labels or [],
        "capabilities": capabilities or _default_capabilities(id_type),
        "revoked": False,
        "revoked_at": None,
        "trusted": True,            # locally-created identities are trusted by default
        "metadata": {"email": email} if email else {},
    }
    repo.paths.identities.mkdir(parents=True, exist_ok=True)
    repo.paths.keys.mkdir(parents=True, exist_ok=True)
    util.write_json(record_path(repo, identity_id), record)
    kp = key_path(repo, identity_id)
    with open(kp, "wb") as fh:
        fh.write(seed)
    try:
        os.chmod(kp, 0o600)
    except OSError:
        pass
    # a private-key directory should also be tight
    try:
        os.chmod(repo.paths.keys, 0o700)
    except OSError:
        pass
    if repo.current_identity_id() is None:
        set_current(repo, identity_id)
    return record


def _default_capabilities(id_type: str) -> List[str]:
    base = ["sign"]
    if id_type in ("human", "ci"):
        base += ["accept", "merge", "tag"]
    return base


# ----------------------------------------------------------------- load / list

def load(repo: Repo, id_or_fp: str) -> Optional[Dict[str, Any]]:
    p = record_path(repo, id_or_fp)
    if p.exists():
        return util.read_json(p, None)
    # allow lookup by fingerprint or short fingerprint
    for rec in list_all(repo):
        if rec.get("fingerprint") == id_or_fp or rec.get("fingerprint", "").endswith(id_or_fp):
            return rec
    return None


def list_all(repo: Repo) -> List[Dict[str, Any]]:
    d = repo.paths.identities
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix == ".json":
            rec = util.read_json(f, None)
            if rec:
                out.append(rec)
    return out


def public_key(repo: Repo, identity_id: str) -> Optional[bytes]:
    rec = load(repo, identity_id)
    if not rec:
        return None
    return _unhex(rec["public_key"])


def private_seed(repo: Repo, identity_id: str) -> Optional[bytes]:
    kp = key_path(repo, identity_id)
    if not kp.exists():
        return None
    return kp.read_bytes()


# --------------------------------------------------------------------- trust

def set_trust(repo: Repo, identity_id: str, trusted: bool) -> Optional[Dict[str, Any]]:
    rec = load(repo, identity_id)
    if not rec:
        return None
    rec["trusted"] = trusted
    util.write_json(record_path(repo, rec["identity_id"]), rec)
    return rec


def revoke(repo: Repo, identity_id: str) -> Optional[Dict[str, Any]]:
    rec = load(repo, identity_id)
    if not rec:
        return None
    rec["revoked"] = True
    rec["revoked_at"] = util.now_iso()
    util.write_json(record_path(repo, rec["identity_id"]), rec)
    return rec


def is_trusted(repo: Repo, identity_id: str) -> bool:
    rec = load(repo, identity_id)
    return bool(rec and rec.get("trusted") and not rec.get("revoked"))


# ----------------------------------------------------------------- import/export

def public_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """Strip any private/local-only bits. (Never contains a private key anyway.)"""
    out = dict(record)
    out.pop("trusted", None)  # trust is local; imports start untrusted
    return out


def export_record(repo: Repo, identity_id: str) -> Optional[Dict[str, Any]]:
    rec = load(repo, identity_id)
    return public_view(rec) if rec else None


def import_record(repo: Repo, record: Dict[str, Any]) -> Dict[str, Any]:
    """Import a public identity. Imported identities are UNTRUSTED by default."""
    if "identity_id" not in record or "public_key" not in record:
        raise ValueError("invalid identity record")
    rec = dict(record)
    rec["trusted"] = False              # importing never implies trust
    rec.setdefault("revoked", False)
    repo.paths.identities.mkdir(parents=True, exist_ok=True)
    util.write_json(record_path(repo, rec["identity_id"]), rec)
    return rec


# ----------------------------------------------------------------- current id

def set_current(repo: Repo, identity_id: str) -> None:
    repo.paths.current_identity.write_text(identity_id + "\n", encoding="utf-8")


def current(repo: Repo) -> Optional[Dict[str, Any]]:
    cid = repo.current_identity_id()
    return load(repo, cid) if cid else None


# ----------------------------------------------------------------- key hygiene

def key_permissions_warning(repo: Repo, identity_id: str) -> Optional[str]:
    """Return a warning string if the private key file is group/other readable."""
    kp = key_path(repo, identity_id)
    if not kp.exists():
        return None
    try:
        mode = stat.S_IMODE(kp.stat().st_mode)
    except OSError:
        return None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return "private key {} has unsafe permissions {:o} (should be 600)".format(kp.name, mode)
    return None
