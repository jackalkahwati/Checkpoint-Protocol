"""High-level operations over native objects: snapshot, autosave, accept, reject,
rollback, packet. The accept path is where history grows — entirely without Git.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import objects, util
from . import secrets as secretscan
from .diff import diff_result, tree_diff, unified
from .session import Session, ACCEPTED, REJECTED, ROLLED_BACK
from .store import Repo
from .verify import last_verification
from .worktree import materialize, scan_to_tree


# --------------------------------------------------------------------- snapshots

def create_snapshot(repo: Repo, session: Session, message: Optional[str],
                    kind: str = objects.KIND_SNAPSHOT) -> Dict[str, Any]:
    """Create a meaningful snapshot object (NOT an autosave). See autosave.py for autosaves."""
    tree = scan_to_tree(repo)
    snap = objects.make_snapshot(
        tree=tree, parents=[session.base_head] if session.base_head else [],
        session=session.id, kind=kind, message=message,
        author=repo.identity(), timestamp=util.now_iso(),
    )
    oid = repo.put_object(snap)
    td = tree_diff(repo, session.base_tree, tree)
    session.data["snapshots"].append(oid)
    session.save()
    return {"id": oid, "tree": tree, "stats": td["stats"], "message": message}


# ----------------------------------------------------------------------- packet

def _recommended_message(session: Session) -> str:
    instr = (session.data.get("instruction") or "").strip()
    return (instr.splitlines()[0] if instr else "checkpoint change")[:72]


def generate_packet(repo: Repo, session: Session) -> Dict[str, Any]:
    base = session.base_tree
    current = scan_to_tree(repo)
    dr = diff_result(repo, base, current)
    changed_files = (
        [{"path": p, "status": "added"} for p in dr["added"]]
        + [{"path": p, "status": "deleted"} for p in dr["deleted"]]
        + [{"path": p, "status": "modified"} for p in dr["modified"]]
        + [{"path": r["new_path"], "status": "renamed", "from": r["old_path"],
            "similarity": r["similarity"], "kind": r["kind"]} for r in dr["renamed"]]
    )

    findings: List[Dict[str, Any]] = []
    if repo.config.secrets_scan():
        findings = secretscan.scan_diff(unified(repo, base, current))
        findings += secretscan.scan_paths([f["path"] for f in changed_files])

    ver = last_verification(repo, session)
    if findings:
        next_action = "review-secrets"
    elif ver.get("overall") == "failed":
        next_action = "fix-verification"
    elif not changed_files:
        next_action = "rollback-or-close"
    else:
        next_action = "accept"

    agent = session.data.get("agent", {})
    packet = {
        "schema_version": 1,
        "generated_at": util.now_iso(),
        "session_id": session.id,
        "instruction": session.data.get("instruction"),
        "actor": session.actor(),
        "agent": {"name": agent.get("name"), "model": agent.get("model"), "tool": agent.get("tool")},
        "branch": session.data["base"].get("branch"),
        "base_snapshot": session.base_head,
        "base_tree": base,
        "current_tree": current,
        "changed_files": changed_files,
        "rename_records": dr["renamed"],
        "directory_renames": dr["directory_renames"],
        "stats": dr["stats"],
        "diff_ref": "checkpoint-core diff",
        "snapshots": session.data.get("snapshots", []),
        "verification": {"overall": ver.get("overall", "not-run"),
                         "runs": session.data.get("verifications", [])},
        "risks": list(session.data.get("risk_tags", [])) + ["secrets-detected:{}".format(len(findings))],
        "recommended_commit_message": _recommended_message(session),
        "recommended_next_action": next_action,
        "secret_findings": findings,
    }
    util.write_json(session.dir / "packet.json", packet)
    session.data["packet"] = "packet.json"
    session.save()
    return packet


# ----------------------------------------------------------------------- accept

def accept(repo: Repo, session: Session, message: str,
           verification_ref: Optional[str]) -> str:
    """Create an accepted snapshot, advance the branch, seal it. Returns snapshot id."""
    tree = scan_to_tree(repo)
    parent = repo.head_snapshot()
    parents = [parent] if parent else []
    snap = objects.make_snapshot(
        tree=tree, parents=parents, session=session.id, kind=objects.KIND_ACCEPTED,
        message=message, author=repo.identity(), timestamp=util.now_iso(),
        verification=verification_ref,
    )
    snap = objects.sign(snap, repo.identity().get("id", "anon"))
    oid = repo.put_object(snap)

    branch = repo.head_branch()
    if branch:
        repo.update_ref("refs/heads/{}".format(branch), oid)
    else:
        repo.set_head_detached(oid)

    session.data["result"] = {"kind": ACCEPTED, "snapshot": oid}
    session.set_status(ACCEPTED)
    repo.set_active_session(None)
    return oid


def reject(repo: Repo, session: Session, reason: Optional[str]) -> None:
    session.data["result"] = {"kind": REJECTED, "reason": reason}
    session.set_status(REJECTED)
    repo.set_active_session(None)


# --------------------------------------------------------------------- rollback

def plan_rollback(repo: Repo, target_tree: str) -> Dict[str, List[str]]:
    current = scan_to_tree(repo)
    td = tree_diff(repo, target_tree, current)
    restore = [f["path"] for f in td["files"] if f["status"] in ("modified", "deleted", "renamed")]
    added = [f["path"] for f in td["files"] if f["status"] == "added"]
    return {"restore": restore, "added": added}


def execute_rollback(repo: Repo, target_tree: str, delete_added: bool) -> Dict[str, Any]:
    result = materialize(repo, target_tree, delete_extra=delete_added)
    return {"restored": result["written"], "deleted": result["deleted"]}
