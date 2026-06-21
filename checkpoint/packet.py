"""Generate the Change Packet: the final proposed change from a session."""
from __future__ import annotations

from typing import Any, Dict, List

from . import SCHEMA_VERSION, util
from . import secrets as secretscan
from .session import Session
from .snapshot import capture_tree
from .store import Repo
from .verify import last_verification


def _recommended_commit_message(session: Session) -> str:
    instr = session.data.get("instruction", "").strip()
    # Prefer the last snapshot message if it is more specific, else the instruction.
    first_line = instr.splitlines()[0] if instr else "checkpoint change"
    return first_line[:72]


def generate_packet(repo: Repo, session: Session) -> Dict[str, Any]:
    base_tree = session.base_tree
    current_tree = capture_tree(repo, name="packet-index")

    name_status = repo.git.diff_name_status(base_tree, current_tree)
    changed_files = [{"path": p, "status": s} for s, p in name_status]
    summary = repo.git.diff_shortstat(base_tree, current_tree) or "no changes"
    diff_text = repo.git.diff(base_tree, current_tree)

    # Secret scan (diff added-lines + sensitive filenames). Values never stored.
    findings: List[Dict[str, Any]] = []
    if repo.config.secrets_scan():
        findings = secretscan.scan_diff(diff_text)
        findings += secretscan.scan_paths([c["path"] for c in changed_files])

    verification = last_verification(repo, session)
    ver_block = {
        "overall": verification.get("overall", "not-run"),
        "runs": session.data.get("verifications", []),
    }

    risks: List[str] = list(session.data.get("risk_tags", []))
    risks.append("secrets-detected:{}".format(len(findings)))

    if findings:
        next_action = "review-secrets"
    elif ver_block["overall"] in ("failed",):
        next_action = "fix-verification"
    elif not changed_files:
        next_action = "rollback-or-close"
    else:
        next_action = "accept"

    snapshots_meta = []
    for sid in session.data.get("snapshots", []):
        snap = util.read_json(session.dir / "snapshots" / sid / "snapshot.json", {})
        snapshots_meta.append({
            "snapshot_id": sid,
            "message": snap.get("message"),
            "created_at": snap.get("created_at"),
            "stats": snap.get("stats"),
        })

    agent = session.data.get("agent", {})
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": util.now_iso(),
        "session_id": session.id,
        "instruction": session.data.get("instruction"),
        "actor": session.actor(),
        "agent": {"name": agent.get("name"), "model": agent.get("model"), "tool": agent.get("tool")},
        "branch": repo.git.branch(),
        "base_commit": session.base_head,
        "current_commit": repo.git.head(),
        "base_tree": base_tree,
        "current_tree": current_tree,
        "changed_files": changed_files,
        "summary": summary.strip(),
        "diff_ref": "git diff {} {}".format(base_tree, current_tree),
        "snapshots": snapshots_meta,
        "verification": ver_block,
        "risks": risks,
        "recommended_commit_message": _recommended_commit_message(session),
        "recommended_next_action": next_action,
        "secret_findings": findings,
    }
    util.write_json(session.dir / "packet.json", packet)
    session.data["packet"] = "packet.json"
    session.save()
    return packet
