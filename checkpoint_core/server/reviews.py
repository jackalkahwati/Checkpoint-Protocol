"""Merge Requests (the team-review layer) for the hosted server.

A Merge Request proposes merging a session's accepted snapshot into a target branch. It
carries a review thread (comments, optionally anchored to a file/line) and a mergeability
check. Merging is performed SERVER-SIDE and signed by a per-repo "reviewer" service identity
(its private key never leaves the server), then the target ref moves atomically — the same
verify-before-move discipline as push. Policy is evaluated using the *source work's* actor
type, so human-authored, trusted, signed work can be one-click merged while agent-authored
work is gated exactly as the policy dictates.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from .. import identity as idmod, objects, policy as policymod, sign as signmod, util
from ..diff import diff_result
from ..merge import three_way
from ..remote import atomic_update_ref
from ..store import Repo

REVIEWER_NAME = "Checkpoint Reviewer"


def _dir(store, owner: str, repo: str):
    d = store.repo_path(owner, repo) / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(store, owner: str, repo: str, rid: str):
    return _dir(store, owner, repo) / (rid + ".json")


def _new_id(existing: List[str]) -> str:
    n = len(existing) + 1
    return "mr_{}".format(n)


def list_reviews(store, owner: str, repo: str) -> List[Dict[str, Any]]:
    out = []
    d = _dir(store, owner, repo)
    for f in sorted(d.glob("mr_*.json")):
        rec = util.read_json(f, None)
        if rec:
            out.append(rec)
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


def get_review(store, owner: str, repo: str, rid: str) -> Optional[Dict[str, Any]]:
    return util.read_json(_path(store, owner, repo, rid), None)


def _save(store, owner: str, repo: str, rec: Dict[str, Any]) -> None:
    util.write_json(_path(store, owner, repo, rec["id"]), rec)


def create_review(store, owner: str, repo: str, r: Repo, *, title: str, description: str,
                  source_snapshot: str, source_session: Optional[str],
                  target_branch: str, author: str, now: str) -> Dict[str, Any]:
    existing = [rec["id"] for rec in list_reviews(store, owner, repo)]
    rec = {
        "id": _new_id(existing),
        "title": title or "(untitled)",
        "description": description or "",
        "author": author or "anon",
        "source_snapshot": source_snapshot,
        "source_session": source_session,
        "target_branch": target_branch,
        "status": "open",
        "created_at": now,
        "comments": [],
        "merged_snapshot": None,
        "merged_at": None,
        "closed_at": None,
    }
    _save(store, owner, repo, rec)
    store.audit(owner, repo, {"operation": "mr_open", "mr": rec["id"], "result": "success",
                              "timestamp": now})
    return rec


def add_comment(store, owner: str, repo: str, rid: str, *, author: str, body: str,
                path: Optional[str], line: Optional[int], now: str) -> Optional[Dict[str, Any]]:
    rec = get_review(store, owner, repo, rid)
    if rec is None:
        return None
    cid = "c{}".format(len(rec["comments"]) + 1)
    comment = {"id": cid, "author": author or "anon", "body": body, "path": path,
               "line": line, "created_at": now, "resolved": False}
    rec["comments"].append(comment)
    _save(store, owner, repo, rec)
    return comment


def resolve_comment(store, owner: str, repo: str, rid: str, cid: str, resolved: bool) -> Optional[Dict[str, Any]]:
    rec = get_review(store, owner, repo, rid)
    if rec is None:
        return None
    for c in rec["comments"]:
        if c["id"] == cid:
            c["resolved"] = resolved
            _save(store, owner, repo, rec)
            return c
    return None


def close_review(store, owner: str, repo: str, rid: str, now: str) -> Optional[Dict[str, Any]]:
    rec = get_review(store, owner, repo, rid)
    if rec is None:
        return None
    if rec["status"] == "open":
        rec["status"] = "closed"
        rec["closed_at"] = now
        _save(store, owner, repo, rec)
        store.audit(owner, repo, {"operation": "mr_close", "mr": rid, "result": "success", "timestamp": now})
    return rec


def _target_head(r: Repo, branch: str) -> Optional[str]:
    return r.read_ref("refs/heads/{}".format(branch))


def mergeability(r: Repo, rec: Dict[str, Any]) -> Dict[str, Any]:
    """Compute clean/conflicts for merging the source snapshot into the target branch head."""
    source = rec["source_snapshot"]
    head = _target_head(r, rec["target_branch"])
    if not source or not r.has_object(source):
        return {"clean": False, "conflicts": [], "auto_merged": [], "reason": "source snapshot missing"}
    if head is None:
        # empty target: fast-forward / first content
        return {"clean": True, "conflicts": [], "auto_merged": [], "fast_forward": True,
                "already_merged": False}
    if head == source or r.is_ancestor(source, head):
        return {"clean": True, "conflicts": [], "auto_merged": [], "already_merged": True}
    base = r.merge_base(head, source)
    res = three_way(r, r.get_object(head)["tree"], r.get_object(source)["tree"],
                    r.get_object(base)["tree"] if base else None)
    return {"clean": res["clean"], "conflicts": res["conflicts"],
            "auto_merged": res["auto_merged"], "rename_records": res["rename_records"],
            "fast_forward": r.is_ancestor(head, source), "already_merged": False}


def _reviewer_identity(r: Repo) -> Dict[str, Any]:
    """Per-repo service identity that signs MR merges. Created once; key stays server-side."""
    for rec in idmod.list_all(r):
        if rec.get("name") == REVIEWER_NAME:
            return rec
    return idmod.create(r, name=REVIEWER_NAME, id_type="ci")


def _source_actor_type(r: Repo, store, owner: str, repo: str, rec: Dict[str, Any]) -> str:
    sid = rec.get("source_session")
    if sid:
        sess = util.read_json(r.paths.session_dir(sid) / "session.json", None)
        if sess:
            return (sess.get("actor", {}) or {}).get("type", "human")
    return "human"


def merge_review(store, owner: str, repo: str, r: Repo, rid: str, *, now: str) -> Dict[str, Any]:
    """Perform a verified, signed server-side merge of the MR into its target branch.

    Returns {"status": merged|conflicts|policy-denied|invalid, ...}.
    """
    rec = get_review(store, owner, repo, rid)
    if rec is None:
        return {"status": "invalid", "error": "no such merge request"}
    if rec["status"] != "open":
        return {"status": "invalid", "error": "merge request is {}".format(rec["status"])}
    source = rec["source_snapshot"]
    m = mergeability(r, rec)
    if m.get("already_merged"):
        rec["status"] = "merged"; rec["merged_snapshot"] = _target_head(r, rec["target_branch"]); rec["merged_at"] = now
        _save(store, owner, repo, rec)
        return {"status": "merged", "snapshot": rec["merged_snapshot"], "already_merged": True}
    if not m["clean"]:
        return {"status": "conflicts", "conflicts": m["conflicts"]}

    # policy (evaluated as the source work's actor; the merge will be signed + trusted)
    pol = policymod.load(r)
    if pol is not None:
        try:
            dr = diff_result(r, r.get_object(_target_head(r, rec["target_branch"]))["tree"] if _target_head(r, rec["target_branch"]) else None,
                             r.get_object(source)["tree"])
            changed = dr["added"] + dr["deleted"] + dr["modified"] + [x["new_path"] for x in dr["renamed"]]
        except Exception:
            changed = []
        decision = policymod.evaluate(pol, {
            "operation": "merge", "actor_type": _source_actor_type(r, store, owner, repo, rec),
            "branch": rec["target_branch"], "changed_paths": changed,
            "will_sign": True, "trust_status": "trusted"})
        if decision["effect"] == "deny":
            store.audit(owner, repo, {"operation": "mr_merge", "mr": rid, "result": "policy-denied",
                                      "reasons": decision["reasons"], "timestamp": now})
            return {"status": "policy-denied", "reasons": decision["reasons"],
                    "required_actions": decision.get("required_actions", [])}

    head = _target_head(r, rec["target_branch"])
    with store.repo_lock(owner, repo):
        if _target_head(r, rec["target_branch"]) != head:
            return {"status": "invalid", "error": "target moved; refresh and retry"}
        reviewer = _reviewer_identity(r)
        if m.get("fast_forward"):
            new_oid = source                          # target is an ancestor: fast-forward
        else:
            base = r.merge_base(head, source) if head else None
            res = three_way(r, r.get_object(head)["tree"], r.get_object(source)["tree"],
                            r.get_object(base)["tree"] if base else None)
            snap = objects.make_snapshot(
                tree=res["merged_tree"], parents=[head, source], session=rec.get("source_session"),
                kind=objects.KIND_ACCEPTED,
                message="Merge {}: {}".format(rid, rec["title"]),
                author={"type": "ci", "id": reviewer["identity_id"], "name": REVIEWER_NAME},
                timestamp=now)
            snap = objects.sign(snap, reviewer["identity_id"])     # SHA-256 content seal
            new_oid = r.put_object(snap)
            signmod.sign_snapshot(r, new_oid, reviewer["identity_id"])  # Ed25519 authorship
        atomic_update_ref(r, "refs/heads/{}".format(rec["target_branch"]), new_oid)

    rec["status"] = "merged"; rec["merged_snapshot"] = new_oid; rec["merged_at"] = now
    _save(store, owner, repo, rec)
    store.audit(owner, repo, {"operation": "mr_merge", "mr": rid, "result": "success",
                              "ref": rec["target_branch"], "snapshot": new_oid, "timestamp": now})
    return {"status": "merged", "snapshot": new_oid}
