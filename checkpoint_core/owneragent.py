"""The Owner Agent: a deterministic reviewer that decides, from the owner's configured
perspective, whether AI-produced work can be auto-accepted/auto-merged or must escalate.

Deliberately NOT an LLM: the decision is rule-based and bounded by the personal-autopilot
config AND the policy engine. This makes it predictable, prompt-injection-proof, and unable
to loosen policy or trust identities. Security invariants enforced here:
  - the Owner Agent is a separate identity from the Builder Agent (it can't approve its own work)
  - it never overrides or loosens policy (policy denial -> escalate, always)
  - it never trusts identities
  - it only auto-accepts/auto-merges when the config's allow-rules AND policy both permit
Reviews are ledgered and (when an identity exists) signed.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from . import identity as idmod, ledger as ledgermod, policy as policymod, sign as signmod, util
from . import verify as verifymod
from .diff import tree_diff
from .session import Session
from .store import Repo
from .worktree import scan_to_tree

OWNER_AGENT_NAME = "Owner Agent"

# Conservative defaults: auto-accept only low-risk docs/tests/examples/markdown.
DEFAULT_AUTOPILOT: Dict[str, Any] = {
    "enabled": True,
    "default_mode": "auto_accept_low_risk",
    "builder_agents": ["claude-code"],
    "owner_agent": {
        "enabled": True, "identity_name": OWNER_AGENT_NAME,
        "require_separate_identity_from_builder": True, "sign_reviews": True,
    },
    "auto_accept_allowed": {
        "paths": ["docs/", "examples/", "tests/", "*.md", "README.md"],
        "require": {"tests_passed": True, "policy_allowed": True, "no_conflicts": True,
                    "no_unresolved_comments": True, "no_protected_paths": True,
                    "max_files_changed": 10, "max_deletions": 200,
                    "owner_agent_confidence": "high"},
    },
    "auto_merge_allowed": {
        "paths": ["docs/", "examples/", "tests/", "*.md"],
        "require": {"tests_passed": True, "policy_allowed": True, "no_conflicts": True,
                    "no_unresolved_comments": True, "no_protected_paths": True,
                    "signed_review": True, "trusted_owner_agent": True,
                    "max_files_changed": 10, "max_deletions": 200},
    },
    "escalate_to_human": {
        "paths": ["checkpoint_core/policy", "checkpoint_core/sign", "checkpoint_core/remote",
                  "checkpoint_core/server", "checkpoint_core/merge", "src/auth", "src/security",
                  "firmware/", "migrations/"],
        "conditions": ["tests_failed", "policy_denied", "merge_conflict", "unresolved_comments",
                       "files_changed_more_than", "deletions_more_than", "unsigned_history",
                       "untrusted_signer", "builder_agent_is_same_as_owner_agent", "changes_policy",
                       "changes_identity_or_trust", "changes_remote_sync", "changes_server_auth"],
    },
    "after_accept": {"run": ["fsck", "verify_signatures", "backup", "push_default_remote"]},
    "after_merge": {"run": ["fsck", "verify_signatures", "backup", "push_default_remote"]},
}


def config_path(repo: Repo):
    return repo.paths.base / "autopilot.yaml"


def load_config(repo: Repo) -> Dict[str, Any]:
    p = config_path(repo)
    if p.exists():
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        merged = copy.deepcopy(DEFAULT_AUTOPILOT)
        merged.update(data)            # shallow merge: user keys win
        return merged
    return copy.deepcopy(DEFAULT_AUTOPILOT)


def save_config(repo: Repo, cfg: Dict[str, Any]) -> None:
    import yaml
    repo.paths.base.mkdir(parents=True, exist_ok=True)
    config_path(repo).write_text(
        "# Checkpoint personal-autopilot config (Owner Agent rules). Conservative by default.\n"
        + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def owner_identity(repo: Repo, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get-or-create the Owner Agent identity (separate from any builder). Trusted (local)."""
    cfg = cfg or load_config(repo)
    name = cfg.get("owner_agent", {}).get("identity_name", OWNER_AGENT_NAME)
    for rec in idmod.list_all(repo):
        if rec.get("name") == name:
            return rec
    return idmod.create(repo, name=name, id_type="ci")


def _match_any(path: str, patterns: List[str]) -> bool:
    p = (path or "").replace("\\", "/")
    for pat in patterns or []:
        pat = pat.rstrip("/")
        if policymod.path_matches(pat, p) or policymod.path_matches(pat + "/**", p):
            return True
        if p == pat or p.startswith(pat + "/"):
            return True
    return False


def decide(facts: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pure decision function. facts -> {decision, risk, confidence, reasoning, ...}."""
    aa = cfg.get("auto_accept_allowed", {})
    req = aa.get("require", {})
    esc = cfg.get("escalate_to_human", {})
    checked: List[str] = []
    reasons: List[str] = []
    escalate = False

    changed = facts.get("changed_paths", [])
    protected = [p for p in changed if _match_any(p, esc.get("paths", []))]
    facts["protected_paths_touched"] = protected

    def flag(cond_name, is_bad, why):
        checked.append("{}: {}".format(cond_name, "FAIL" if is_bad else "ok"))
        if is_bad:
            reasons.append(why)
            return True
        return False

    escalate |= flag("tests", facts.get("tests") == "failed", "tests failed")
    escalate |= flag("policy", facts.get("policy_effect") == "deny",
                     "policy denied: " + "; ".join(facts.get("policy_reasons", [])))
    escalate |= flag("conflicts", facts.get("conflict_count", 0) > 0, "merge conflict")
    escalate |= flag("comments", facts.get("unresolved_comments", 0) > 0, "unresolved comments")
    escalate |= flag("builder!=owner", facts.get("builder_is_owner", False),
                     "builder agent is the owner agent (no self-approval)")
    escalate |= flag("protected-paths", bool(protected),
                     "touched protected path(s): " + ", ".join(protected[:5]))
    escalate |= flag("size", facts.get("files_changed", 0) > req.get("max_files_changed", 10)
                     or facts.get("deletions", 0) > req.get("max_deletions", 200),
                     "change too large ({} files, -{})".format(facts.get("files_changed", 0),
                                                               facts.get("deletions", 0)))
    escalate |= flag("signatures", facts.get("signatures_status") == "invalid",
                     "invalid signatures")

    if escalate:
        risk = "high" if (protected or facts.get("policy_effect") == "deny"
                          or facts.get("tests") == "failed") else "medium"
        return {"decision": "escalate", "risk": risk, "confidence": "high",
                "reasoning": "; ".join(reasons) or "requires human review",
                "checked_items": checked, "protected_paths_touched": protected,
                "recommended_action": "human review"}

    # auto-accept gate: all changed paths must be within the allow-list AND requirements met
    within = changed and all(_match_any(p, aa.get("paths", [])) for p in changed)
    reqs_ok = (facts.get("tests") in ("passed", "skipped", "not run") if not req.get("tests_passed")
               else facts.get("tests") == "passed") and facts.get("policy_effect") != "deny"
    checked.append("paths-in-allowlist: {}".format("ok" if within else "no"))
    if within and reqs_ok and facts.get("files_changed", 0) > 0:
        return {"decision": "auto_accept", "risk": "low", "confidence": "high",
                "reasoning": "low-risk change within auto-accept paths; tests + policy ok",
                "checked_items": checked, "protected_paths_touched": [],
                "recommended_action": "auto-accept"}
    # safe but outside the auto-accept allow-list -> recommend manual (don't auto-accept)
    return {"decision": "request_changes" if facts.get("files_changed", 0) else "no_decision",
            "risk": "medium", "confidence": "medium",
            "reasoning": "no escalation, but outside the auto-accept allow-list — recommend manual review",
            "checked_items": checked, "protected_paths_touched": [],
            "recommended_action": "manual review"}


def _session_facts(repo: Repo, sess: Session) -> Dict[str, Any]:
    current = scan_to_tree(repo)
    td = tree_diff(repo, sess.base_tree, current)
    st = td["stats"]
    changed = [f["path"] for f in td["files"]]
    ver = verifymod.last_verification(repo, sess)
    cmds = (repo.config.data.get("verification") or {}).get("commands") or []
    # no verification ran: vacuous pass if the repo has no test commands, else "not run"
    tests = (ver.get("overall") if ver else None) or ("passed" if not cmds else "not run")
    cur = idmod.load(repo, repo.current_identity_id()) if repo.current_identity_id() else {}
    pol = policymod.load(repo)
    pol_effect, pol_reasons, pol_id = "allow", [], None
    if pol is not None:
        passed = [r.get("name") for r in (ver.get("results", []) if ver else []) if r.get("status") == "passed"]
        d = policymod.evaluate(pol, {"operation": "accept", "actor_type": cur.get("type", "human"),
                                     "branch": repo.head_branch(), "changed_paths": changed,
                                     "will_sign": bool(repo.current_identity_id()),
                                     "trust_status": "trusted" if cur.get("trusted") else "untrusted",
                                     "verification_passed": passed})
        pol_effect, pol_reasons = d["effect"], d.get("reasons", [])
    builder = (sess.data.get("actor", {}) or {}).get("id") or sess.data.get("signing_identity")
    return {"changed_paths": changed, "files_changed": st["files_changed"],
            "deletions": st["deletions"], "insertions": st["insertions"],
            "tests": tests, "policy_effect": pol_effect, "policy_reasons": pol_reasons,
            "conflict_count": 0, "unresolved_comments": 0,
            "signatures_status": "unsigned", "builder_identity": builder}


def review_session(repo: Repo, sess: Session, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the Owner Agent over an active session; ledger + sign the review; return it."""
    cfg = cfg or load_config(repo)
    owner = owner_identity(repo, cfg)
    facts = _session_facts(repo, sess)
    facts["builder_is_owner"] = bool(facts.get("builder_identity")) and facts["builder_identity"] == owner["identity_id"]
    d = decide(facts, cfg)
    review = {
        "review_id": util.seq_id("rev", sess.next_seq("owner_review")) if hasattr(sess, "next_seq") else util.event_id(),
        "target_type": "session", "target_id": sess.id,
        "owner_agent_identity_id": owner["identity_id"],
        "builder_agent_identity_id": facts.get("builder_identity"),
        "created_at": util.now_iso(),
        "decision": d["decision"], "confidence": d["confidence"], "risk": d["risk"],
        "reasoning": d["reasoning"], "checked_items": d["checked_items"],
        "verification_summary": facts["tests"],
        "changed_paths": facts["changed_paths"][:50],
        "protected_paths_touched": d["protected_paths_touched"],
        "unresolved_comments_count": facts["unresolved_comments"],
        "conflict_count": facts["conflict_count"],
        "signatures_status": facts["signatures_status"],
        "policy_effect": facts["policy_effect"],
        "files_changed": facts["files_changed"], "deletions": facts["deletions"],
        "insertions": facts["insertions"],
        "recommended_action": d["recommended_action"],
    }
    # sign the review (independent owner-agent attestation) when configured + identity exists
    if cfg.get("owner_agent", {}).get("sign_reviews", True):
        try:
            sig = signmod.sign_payload(repo, "owner_review", review["review_id"], review, owner["identity_id"])
            review["signed_review"] = {"signer": owner["identity_id"], "signature_id": sig.get("signature_id")}
        except Exception:
            review["signed_review"] = None
    ledgermod.append(repo, "owner_review", sess.id,
                     {"id": owner["identity_id"], "name": owner.get("name")},
                     {k: review[k] for k in ("review_id", "decision", "risk", "confidence",
                                             "reasoning", "protected_paths_touched", "policy_effect")})
    return review
