"""Signatures over canonical protocol payloads, and trust verification. No Git.

Signatures are stored EXTERNALLY (not embedded in the immutable content-addressed object)
under .checkpoint/signatures/<object_id>/<signature_id>.json, so objects can be signed
post-hoc and carry multiple signatures without changing their ids. The signed payload is a
deterministic, canonical subset of identity-affecting fields — it excludes bridge
provenance, local paths, caches, mtimes, and transient reports.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import ed25519, identity as idmod, util
from .store import Repo

PROTOCOL_VERSION = "0.5"
CANON_VERSION = 1


# ------------------------------------------------------------- canonical payloads

def snapshot_payload(snap: Dict[str, Any], snapshot_id: str, acceptor_id: str) -> Dict[str, Any]:
    """Identity-binding payload for an accepted/merge snapshot. Stable across machines."""
    return {
        "canonicalization_version": CANON_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "signed_object_type": "snapshot",
        "snapshot_id": snapshot_id,
        "tree_id": snap.get("tree"),
        "parent_ids": list(snap.get("parents", []) or []),
        "session_id": snap.get("session"),
        "message": snap.get("message"),
        "author_identity_id": (snap.get("author") or {}).get("id"),
        "acceptor_identity_id": acceptor_id,
        "verification": snap.get("verification"),
        "timestamp": snap.get("timestamp"),
        "seal_algorithm": "sha256-seal",
        # NOTE: snap.get("bridge") is intentionally excluded.
    }


def tag_payload(tag: str, snapshot_id: str, acceptor_id: str) -> Dict[str, Any]:
    return {
        "canonicalization_version": CANON_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "signed_object_type": "tag",
        "tag": tag,
        "snapshot_id": snapshot_id,
        "acceptor_identity_id": acceptor_id,
    }


# ----------------------------------------------------------------- storage

def _sig_dir(repo: Repo, oid: str) -> Path:
    return repo.paths.signatures / oid


def signatures_for(repo: Repo, oid: str) -> List[Dict[str, Any]]:
    d = _sig_dir(repo, oid)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix == ".json":
            rec = util.read_json(f, None)
            if rec:
                out.append(rec)
    return out


def iter_all(repo: Repo) -> List[Dict[str, Any]]:
    base = repo.paths.signatures
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            out.extend(signatures_for(repo, d.name))
    return out


# ----------------------------------------------------------------- signing

def _write_record(repo: Repo, oid: str, record: Dict[str, Any]) -> None:
    util.write_json(_sig_dir(repo, oid) / (record["signature_id"] + ".json"), record)


def sign_payload(repo: Repo, signed_object_type: str, signed_object_id: str,
                 payload: Dict[str, Any], signer_id: str) -> Dict[str, Any]:
    rec = idmod.load(repo, signer_id)
    if not rec:
        raise ValueError("unknown identity: {}".format(signer_id))
    seed = idmod.private_seed(repo, rec["identity_id"])
    if seed is None:
        raise ValueError("no private key for identity {} (cannot sign)".format(signer_id))
    sig = ed25519.sign(seed, util.canonical(payload))
    record = {
        "signature_id": "sig_{}_{}".format(util.stamp(), hashlib.sha256(sig).hexdigest()[:6]),
        "signer_identity_id": rec["identity_id"],
        "signer_fingerprint": rec["fingerprint"],
        "algorithm": ed25519.ALGORITHM,
        "signed_at": util.now_iso(),
        "signed_object_type": signed_object_type,
        "signed_object_id": signed_object_id,
        "canonicalization_version": CANON_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "signature": sig.hex(),
        "public_key_hint": rec["public_key"],
    }
    _write_record(repo, signed_object_id, record)
    return record


def sign_snapshot(repo: Repo, snapshot_id: str, signer_id: str) -> Dict[str, Any]:
    snap = repo.get_object(snapshot_id)
    payload = snapshot_payload(snap, snapshot_id, signer_id)
    return sign_payload(repo, "snapshot", snapshot_id, payload, signer_id)


# ----------------------------------------------------------------- verification

def _rebuild_payload(repo: Repo, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = record.get("signed_object_type")
    oid = record["signed_object_id"]
    if t == "snapshot":
        try:
            snap = repo.get_object(oid)
        except Exception:
            return None
        return snapshot_payload(snap, oid, record["signer_identity_id"])
    if t == "owner_review":
        # Owner Agent review attestation: the signed payload is the persisted review record
        # as it was at signing time (before signed_review / ledger_event_id were filled in).
        data = util.read_json(repo.paths.base / "owner_reviews" / (oid + ".json"), None)
        if not data:
            return None
        payload = dict(data)
        payload["signed_review"] = None
        payload["ledger_event_id"] = None
        return payload
    if t == "tag":
        # tag target is recorded in the signature's own payload-bound fields
        return None  # tag verification handled via stored payload (future); snapshots are primary
    return None


def verify_record(repo: Repo, record: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {ok, status, trusted, revoked, signer, reason}."""
    signer_id = record.get("signer_identity_id")
    id_rec = idmod.load(repo, signer_id)
    # public key: prefer the known identity record, else the hint embedded in the signature
    if id_rec and id_rec.get("public_key"):
        pub = bytes.fromhex(id_rec["public_key"])
        known = True
    elif record.get("public_key_hint"):
        pub = bytes.fromhex(record["public_key_hint"])
        known = False
    else:
        return {"ok": False, "status": "unknown_signer", "trusted": False,
                "revoked": False, "signer": signer_id, "reason": "no public key available"}

    payload = _rebuild_payload(repo, record)
    if payload is None:
        return {"ok": False, "status": "invalid", "trusted": False, "revoked": False,
                "signer": signer_id, "reason": "signed object missing or unsupported"}

    try:
        sig = bytes.fromhex(record["signature"])
    except Exception:
        return {"ok": False, "status": "invalid", "trusted": False, "revoked": False,
                "signer": signer_id, "reason": "malformed signature"}

    ok = ed25519.verify(pub, util.canonical(payload), sig)
    revoked = bool(id_rec and id_rec.get("revoked"))
    trusted = bool(id_rec and id_rec.get("trusted") and not revoked)
    if not ok:
        status = "invalid"
    elif not known:
        status = "unknown_signer"
    elif revoked:
        status = "revoked"
    elif not trusted:
        status = "untrusted"
    else:
        status = "valid"
    return {"ok": ok, "status": status, "trusted": trusted, "revoked": revoked,
            "signer": signer_id, "reason": status}


def verify_all(repo: Repo) -> Dict[str, Any]:
    results = []
    for rec in iter_all(repo):
        v = verify_record(repo, rec)
        results.append({"signature_id": rec["signature_id"],
                        "object": rec["signed_object_id"], **v})
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    bad = [r for r in results if not r["ok"]]
    return {"results": results, "counts": counts, "ok": not bad}
