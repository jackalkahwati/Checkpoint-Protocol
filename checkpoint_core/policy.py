"""Deterministic policy engine. No Git.

Checkpoint should not just record what happened — it should enforce what is allowed to
happen. The engine evaluates a PolicyInput against a policy and returns a PolicyDecision
(allow | deny | warn). It is pure and read-only; callers record decisions in the ledger.

Policy is OPT-IN: if no policy is configured (`.checkpoint/policy.yaml` absent and no
`policy:` block in config), the engine is disabled and nothing is enforced.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
import re
from typing import Any, Dict, List, Optional

import yaml

from . import util
from .store import Repo

POLICY_VERSION = 1

# Operation -> actor capability key
_CAP_KEY = {
    "start": "can_start_session", "snapshot": "can_snapshot",
    "accept": "can_accept", "merge": "can_merge", "push": "can_push",
    "tag": "can_tag", "verify": "can_verify", "override": "can_override",
}


DEFAULT_STARTER_POLICY: Dict[str, Any] = {
    "version": POLICY_VERSION,
    "default_effect": "deny",
    "protected_branches": ["main", "release/*"],
    "required_signatures": {
        "accepts": True, "merges": True, "tags": True, "remote_ref_updates": True,
    },
    "required_verification": {
        "default": True,
        "commands": ["tests", "lint"],
    },
    "actor_rules": {
        "agent": {"can_start_session": True, "can_snapshot": True, "can_accept": False,
                  "can_merge": False, "can_push": False, "can_override": False},
        "human": {"can_accept": True, "can_merge": True, "can_push": True,
                  "can_override": True, "can_tag": True, "can_start_session": True,
                  "can_snapshot": True},
        "ci": {"can_verify": True, "can_accept": True, "can_merge": False,
               "can_push": False, "can_start_session": True, "can_snapshot": True},
    },
    "path_rules": [
        {"paths": ["src/safety/", "src/motor/", "firmware/**"],
         "require": {"trusted_human_acceptor": True, "signed_accept": True,
                     "verification": ["tests", "safety_tests"],
                     "forbid_agent_self_accept": True, "min_approvals": 1},
         "label": "safety-critical"},
        {"paths": ["docs/**", "*.md"],
         "require": {"verification_optional": True},
         "label": "docs"},
    ],
    "branch_rules": [
        {"branch": "main",
         "require": {"fast_forward_only": True, "signed_merge": True,
                     "trusted_acceptor": True, "no_unsigned_history": True}},
        {"branch": "release/*",
         "require": {"signed_merge": True, "trusted_human_acceptor": True,
                     "verification": ["tests", "release_checks"]}},
    ],
    "remote_rules": {
        "require_fast_forward": True, "require_signed_snapshots": True,
        "reject_unsigned_remote_history": False, "allow_force_with_lease": True,
        "allow_force_push": False,
    },
    "override_rules": {
        "allow_override": True, "require_reason": True, "require_signature": True,
        "allowed_identity_types": ["human"],
    },
}


# ----------------------------------------------------------------- load / save

def policy_path(repo: Repo):
    return repo.paths.base / "policy.yaml"


def load(repo: Repo) -> Optional[Dict[str, Any]]:
    p = policy_path(repo)
    if p.exists():
        with open(p, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    data = repo.config.data.get("policy")
    return data or None


def save_starter(repo: Repo) -> Dict[str, Any]:
    repo.paths.base.mkdir(parents=True, exist_ok=True)
    with open(policy_path(repo), "w", encoding="utf-8") as fh:
        fh.write("# Checkpoint Core policy. Presence of this file ENABLES enforcement.\n")
        fh.write(yaml.safe_dump(DEFAULT_STARTER_POLICY, sort_keys=False))
    return DEFAULT_STARTER_POLICY


def validate(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not isinstance(data, dict):
        return ["policy must be a mapping"]
    eff = data.get("default_effect", "deny")
    if eff not in ("allow", "deny", "warn"):
        errs.append("default_effect must be allow|deny|warn (got {!r})".format(eff))
    for key in ("required_signatures", "required_verification", "remote_rules",
                "override_rules", "actor_rules"):
        if key in data and not isinstance(data[key], dict):
            errs.append("{} must be a mapping".format(key))
    pr = data.get("path_rules", [])
    if pr and not isinstance(pr, list):
        errs.append("path_rules must be a list")
    else:
        for r in pr or []:
            if not isinstance(r, dict) or "paths" not in r:
                errs.append("each path_rule needs a 'paths' list")
            elif not isinstance(r["paths"], list):
                errs.append("path_rule.paths must be a list")
    br = data.get("branch_rules", [])
    if br and not isinstance(br, list):
        errs.append("branch_rules must be a list")
    else:
        for r in br or []:
            if not isinstance(r, dict) or "branch" not in r:
                errs.append("each branch_rule needs a 'branch'")
    at = data.get("actor_rules", {})
    if isinstance(at, dict):
        for t, caps in at.items():
            if not isinstance(caps, dict):
                errs.append("actor_rules.{} must be a mapping".format(t))
    return errs


# ----------------------------------------------------------------- matching

def path_matches(pattern: str, path: str) -> bool:
    pat = pattern.strip()
    path = path.strip()
    if pat.endswith("/"):
        return path == pat[:-1] or path.startswith(pat)
    if "**" in pat:
        rx = "^" + re.escape(pat).replace(r"\*\*/", "(.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
        return re.match(rx, path) is not None
    if fnmatch.fnmatch(path, pat):
        return True
    if "/" not in pat and fnmatch.fnmatch(posixpath.basename(path), pat):
        return True
    return False


def branch_matches(pattern: Optional[str], branch: Optional[str]) -> bool:
    if pattern is None or branch is None:
        return False
    return fnmatch.fnmatch(branch, pattern)


# ----------------------------------------------------------------- evaluation

def _new_req() -> Dict[str, Any]:
    return {
        "trusted_human_acceptor": False, "trusted_acceptor": False,
        "signed_accept": False, "signed_merge": False,
        "forbid_agent_self_accept": False, "fast_forward_only": False,
        "no_unsigned_history": False, "verification_optional": False,
        "verification": set(), "min_approvals": 0,
    }


def _merge_req(req: Dict[str, Any], require: Dict[str, Any]) -> None:
    for k, v in (require or {}).items():
        if k == "verification":
            req["verification"] |= set(v or [])
        elif k == "min_approvals":
            req["min_approvals"] = max(req["min_approvals"], int(v))
        elif k in req:
            req[k] = req[k] or bool(v)


def evaluate(policy: Dict[str, Any], pin: Dict[str, Any]) -> Dict[str, Any]:
    """Pure, deterministic policy evaluation. Returns a PolicyDecision dict."""
    op = pin.get("operation")
    actor_type = pin.get("actor_type") or "human"
    identity = pin.get("actor_identity") or {}
    trusted = bool(pin.get("trust_status") == "trusted" or identity.get("trusted"))
    changed = pin.get("changed_paths") or []
    will_sign = bool(pin.get("will_sign"))
    passed = set(pin.get("verification_passed") or [])

    reasons: List[str] = []
    actions: List[str] = []
    evaluated: List[str] = []
    matched: List[str] = []

    actor_rules = policy.get("actor_rules", {}) or {}
    caps = actor_rules.get(actor_type, {})
    default_effect = policy.get("default_effect", "deny")
    rs = policy.get("required_signatures", {}) or {}
    rv = policy.get("required_verification", {}) or {}
    rr = policy.get("remote_rules", {}) or {}

    # actor capability
    cap_key = _CAP_KEY.get(op)
    if cap_key is not None:
        evaluated.append("actor_rules.{}".format(actor_type))
        if cap_key in caps:
            if not caps[cap_key]:
                reasons.append("actor type '{}' may not {}".format(actor_type, op))
                actions.append("perform {} as an allowed identity type".format(op))
        elif default_effect == "deny" and op in ("accept", "merge", "push", "tag", "override"):
            reasons.append("default_effect=deny: no rule permits actor '{}' to {}".format(actor_type, op))
            actions.append("add an actor_rule allowing {} to {}".format(actor_type, op))

    # collect path + branch requirements (strictest wins = union of constraints)
    req = _new_req()
    for r in policy.get("path_rules", []) or []:
        if any(path_matches(p, cp) for p in r.get("paths", []) for cp in changed):
            matched.append(r.get("label") or "path_rule")
            evaluated.append("path_rule:{}".format(r.get("label") or "?"))
            _merge_req(req, r.get("require", {}))
    branch = pin.get("branch")
    for r in policy.get("branch_rules", []) or []:
        if branch_matches(r.get("branch"), branch):
            matched.append("branch:{}".format(r.get("branch")))
            evaluated.append("branch_rule:{}".format(r.get("branch")))
            _merge_req(req, r.get("require", {}))

    # operation-specific enforcement
    if op == "accept":
        if actor_type == "agent" and (req["forbid_agent_self_accept"] or caps.get("can_accept") is False):
            reasons.append("agent identities may not self-accept")
            actions.append("switch to a trusted human identity")
        if req["trusted_human_acceptor"]:
            if actor_type != "human":
                reasons.append("changed paths require a human acceptor (actor is {})".format(actor_type))
                actions.append("switch to a trusted human identity")
            if not trusted:
                reasons.append("changed paths require a trusted acceptor")
                actions.append("trust the accepting identity")
        elif req["trusted_acceptor"] and not trusted:
            reasons.append("policy requires a trusted acceptor")
            actions.append("trust the accepting identity")
        if (req["signed_accept"] or rs.get("accepts")) and not will_sign:
            reasons.append("a signed accept is required")
            actions.append("create/select a signing identity (checkpoint-core identity create)")
        for cmd in sorted(_required_verifications(req, rv) - passed):
            reasons.append("required verification '{}' has not passed".format(cmd))
            actions.append("run checkpoint-core verify ({})".format(cmd))
        if req["min_approvals"] > 1 and int(pin.get("approvals", 1)) < req["min_approvals"]:
            reasons.append("requires {} approvals".format(req["min_approvals"]))

    elif op == "merge":
        if (req["signed_merge"] or rs.get("merges")) and not will_sign:
            reasons.append("a signed merge is required")
            actions.append("create/select a signing identity")
        if req["trusted_human_acceptor"] and (actor_type != "human" or not trusted):
            reasons.append("merge requires a trusted human acceptor")
        elif req["trusted_acceptor"] and not trusted:
            reasons.append("merge requires a trusted acceptor")
        for cmd in sorted(_required_verifications(req, rv) - passed):
            reasons.append("required verification '{}' has not passed".format(cmd))
            actions.append("run checkpoint-core verify ({})".format(cmd))
        if req["min_approvals"] > 1 and int(pin.get("approvals", 1)) < req["min_approvals"]:
            reasons.append("requires {} approvals".format(req["min_approvals"]))
            actions.append("get {} review approval(s)".format(req["min_approvals"]))

    elif op == "push":
        ut = pin.get("ref_update_type", "fast_forward")
        if ut == "force" and not rr.get("allow_force_push", False):
            reasons.append("force push is not allowed by policy")
            actions.append("use --force-with-lease, or pull and merge")
        if ut == "force_with_lease" and not rr.get("allow_force_with_lease", True):
            reasons.append("force-with-lease is not allowed by policy")
        if rr.get("require_fast_forward") and ut not in ("fast_forward", "create") and not (
                ut == "force_with_lease" and rr.get("allow_force_with_lease", True)):
            reasons.append("policy requires fast-forward pushes")
        if rs.get("remote_ref_updates") and pin.get("history_signed") is False:
            reasons.append("policy requires signed snapshots for remote ref updates")

    elif op == "pull":
        if rr.get("reject_unsigned_remote_history") and pin.get("remote_unsigned"):
            reasons.append("remote history is unsigned; policy rejects it")
            actions.append("require the remote to sign its history")

    elif op == "bundle_import":
        if (rr.get("require_signed_snapshots") or pin.get("require_signed")) and pin.get("bundle_unsigned"):
            reasons.append("bundle history is unsigned; policy requires signatures")

    elif op == "tag":
        if rs.get("tags") and not will_sign:
            reasons.append("policy requires signed tags")
            actions.append("create/select a signing identity")

    elif op in ("trust", "revoke"):
        pass  # allowed; recorded for audit

    elif op == "override":
        orr = policy.get("override_rules", {}) or {}
        if not orr.get("allow_override", False):
            reasons.append("override is not allowed by policy")
        if orr.get("require_reason", True) and not pin.get("reason"):
            reasons.append("override requires a reason")
            actions.append("pass --reason \"...\"")
        allowed_types = orr.get("allowed_identity_types", ["human"])
        if allowed_types and actor_type not in allowed_types:
            reasons.append("actor type '{}' may not override (allowed: {})".format(
                actor_type, ", ".join(allowed_types)))
        if orr.get("require_signature") and not will_sign:
            reasons.append("override must be signed by an active identity")
            actions.append("create/select a signing identity")

    effect = "deny" if reasons else "allow"
    orr = policy.get("override_rules", {}) or {}
    override_available = (op != "override" and effect == "deny" and orr.get("allow_override", False)
                         and actor_type in (orr.get("allowed_identity_types", ["human"]) or []))

    return {
        "decision_id": "pol_{}_{}".format(util.stamp(), hashlib.sha256(os.urandom(8)).hexdigest()[:6]),
        "timestamp": util.now_iso(),
        "operation": op,
        "effect": effect,
        "actor_identity_id": identity.get("identity_id") or identity.get("id"),
        "actor_type": actor_type,
        "branch": branch,
        "rules_evaluated": evaluated,
        "rules_matched": sorted(set(matched)),
        "reasons": reasons,
        "required_actions": actions,
        "override_available": bool(override_available),
        "override_used": False,
    }


def _required_verifications(req: Dict[str, Any], rv: Dict[str, Any]) -> set:
    required = set(req["verification"])
    # default verification applies unless the change is fully docs-exempt
    docs_exempt = req["verification_optional"] and not req["verification"]
    if rv.get("default") and not docs_exempt:
        required |= set(rv.get("commands", []) or [])
    return required
