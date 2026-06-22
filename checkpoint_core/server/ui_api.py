"""Backend-for-frontend (BFF) adapter under /ui/* for the Next.js review UI.

Returns exactly the TypeScript types in the frontend (lib/checkpoint/types.ts), computed
from the protocol data. This keeps the protocol-shaped endpoints, the CLI client, and the
existing tests untouched, and puts all UI transforms in one testable place.
"""
from __future__ import annotations

import difflib
import re as _re
from typing import Any, Dict, List, Optional

from .. import __version__, objects
from .. import fsck as fsckmod, gc as gcmod, identity as idmod, ledger as ledgermod
from .. import policy as policymod, reachable as R, sign as signmod
from ..diff import diff_result
from ..store import Repo

_NAME = _re.compile(r"^[A-Za-z0-9._-]+$")


def _repo(ctx):
    o, n = ctx.params[0], ctx.params[1]
    if not (_NAME.match(o) and _NAME.match(n)):
        return None, (400, {"error": "invalid owner/repo"}), o, n
    repo = ctx.store.get_repo(o, n)
    if repo is None:
        return None, (404, {"error": "no such repo"}), o, n
    return repo, None, o, n


def _trust_of(idrec) -> str:
    if not idrec:
        return "unknown"
    if idrec.get("revoked"):
        return "revoked"
    return "trusted" if idrec.get("trusted") else "untrusted"


def _fsck_status(repo: Repo) -> str:
    try:
        return fsckmod.check(repo, strict=False)["result"]   # healthy|warnings|corrupt
    except Exception:
        return "warnings"


def _accepted_sig_status(repo: Repo, snap_id: Optional[str]) -> str:
    if not snap_id:
        return "unsigned"
    sigs = signmod.signatures_for(repo, snap_id)
    if not sigs:
        return "unsigned"
    verdicts = [signmod.verify_record(repo, s) for s in sigs]
    if any(not v["ok"] for v in verdicts):
        return "invalid"
    return "valid"


def _last_verification(repo: Repo, sess: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from .. import util
    runs = sess.get("verifications", [])
    if not runs:
        return None
    return util.read_json(repo.paths.session_dir(sess["session_id"]) / "verification" / (runs[-1] + ".json"), None)


def _session_policy_input(repo: Repo, sess: Dict[str, Any]) -> Dict[str, Any]:
    """A faithful PolicyInput for a session: real changed paths, verification results,
    signature state, and acceptor trust — so the decision reflects what actually happened."""
    from .. import util
    pkt = util.read_json(repo.paths.session_dir(sess["session_id"]) / "packet.json", None)
    changed = [f["path"] for f in (pkt.get("changed_files", []) if pkt else [])]
    actor = sess.get("actor", {}) or {}
    accepted = (sess.get("result") or {}).get("snapshot")
    sigs = signmod.signatures_for(repo, accepted) if accepted else []
    signed = bool(sigs)
    trusted = False
    for s in sigs:
        idr = idmod.load(repo, s.get("signer_identity_id"))
        if idr and idr.get("trusted") and not idr.get("revoked"):
            trusted = True
    ver = _last_verification(repo, sess)
    passed = [r.get("name") for r in (ver.get("results", []) if ver else []) if r.get("status") == "passed"]
    return {
        "operation": "accept", "actor_type": actor.get("type", "human"),
        "branch": (sess.get("base", {}) or {}).get("branch"), "changed_paths": changed,
        "verification_passed": passed, "will_sign": signed,
        "trust_status": "trusted" if trusted else "untrusted",
    }


def _session_policy_effect(repo: Repo, sess: Dict[str, Any]) -> str:
    pol = policymod.load(repo)
    if pol is None:
        return "allow"
    return policymod.evaluate(pol, _session_policy_input(repo, sess))["effect"]


def _ui_session(repo: Repo, sess: Dict[str, Any]) -> Dict[str, Any]:
    actor = sess.get("actor", {}) or {}
    agent = sess.get("agent", {}) or {}
    base = sess.get("base", {}) or {}
    result = sess.get("result") or {}
    accepted = result.get("snapshot")
    ver = _last_verification(repo, sess)
    return {
        "session_id": sess.get("session_id"),
        "instruction": sess.get("instruction", ""),
        "status": sess.get("status", "active"),
        "actor_identity": actor.get("name") or actor.get("id") or "anon",
        "actor_type": actor.get("type", "human"),
        "agent_name": agent.get("name"),
        "model_name": agent.get("model"),
        "tool_name": agent.get("tool"),
        "started_at": sess.get("created_at", ""),
        "branch": base.get("branch") or "main",
        "base_snapshot": base.get("head") or "",
        "accepted_snapshot": accepted,
        "risk_tags": sess.get("risk_tags", []) or [],
        "verification_status": (ver.get("overall") if ver else "skipped"),
        "policy_effect": _session_policy_effect(repo, sess),
        "signature_status": _accepted_sig_status(repo, accepted),
        "fsck_status": _fsck_status(repo),
        "summary": sess.get("instruction", ""),
    }


# ----------------------------------------------------------------- diff -> DiffFile[]

def _decode(repo: Repo, blob: Optional[str]) -> Optional[List[str]]:
    if not blob:
        return []
    try:
        return repo.get_blob(blob).decode("utf-8").splitlines(keepends=True)
    except Exception:
        return None


def _hunks(old_lines, new_lines, old_path, new_path):
    hunks = []
    adds = dels = 0
    cur = None
    for line in difflib.unified_diff(old_lines, new_lines, fromfile="a/" + old_path,
                                     tofile="b/" + new_path, lineterm=""):
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("@@"):
            cur = {"header": line, "lines": []}
            hunks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            cur["lines"].append({"kind": "add", "text": line[1:]}); adds += 1
        elif line.startswith("-"):
            cur["lines"].append({"kind": "del", "text": line[1:]}); dels += 1
        else:
            cur["lines"].append({"kind": "context", "text": line[1:] if line[:1] == " " else line})
    return hunks, adds, dels


def _ui_diff_files(repo: Repo, base_tree: Optional[str], cur_tree: Optional[str]) -> List[Dict[str, Any]]:
    dr = diff_result(repo, base_tree, cur_tree)
    files = []

    def build(old_blob, new_blob, old_path, new_path, change_type, similarity=None):
        if similarity is not None and similarity <= 1:   # frontend expects a 0..100 percentage
            similarity = round(similarity * 100)
        ol, nl = _decode(repo, old_blob), _decode(repo, new_blob)
        if ol is None or nl is None:
            return {"old_path": old_path, "new_path": new_path, "change_type": "binary",
                    "similarity": similarity, "additions": 0, "deletions": 0, "hunks": []}
        hunks, adds, dels = _hunks(ol, nl, old_path, new_path)
        return {"old_path": old_path, "new_path": new_path, "change_type": change_type,
                "similarity": similarity, "additions": adds, "deletions": dels, "hunks": hunks}

    amap = objects.tree_map(repo.get_object(base_tree)) if base_tree else {}
    bmap = objects.tree_map(repo.get_object(cur_tree)) if cur_tree else {}
    for r in dr["renamed"]:
        files.append(build(r["old_blob_id"], r["new_blob_id"], r["old_path"], r["new_path"],
                           "renamed", r["similarity"]))
    for p in dr["modified"]:
        files.append(build(amap[p]["blob"], bmap[p]["blob"], p, p, "modified"))
    for p in dr["added"]:
        files.append(build(None, bmap[p]["blob"], p, p, "added"))
    for p in dr["deleted"]:
        files.append(build(amap[p]["blob"], None, p, p, "deleted"))
    return files


# ----------------------------------------------------------------- handlers

def ui_health(ctx):
    return 200, {"ok": True, "version": __version__, "uptime_s": 0}


def _repo_summary(store, owner, name, repo) -> Dict[str, Any]:
    refs = {b: repo.read_ref("refs/heads/{}".format(b)) for b in repo.list_branches()}
    head = repo.head_snapshot()
    sessions = repo.session_ids()
    # signatures across accepted history
    accepted = []
    seen = set()
    for h in refs.values():
        for oid in repo.history(h):
            if oid not in seen:
                seen.add(oid); accepted.append(oid)
    unsigned = [o for o in accepted if not signmod.signatures_for(repo, o)]
    invalid = 0
    untrusted = 0
    for o in accepted:
        for s in signmod.signatures_for(repo, o):
            v = signmod.verify_record(repo, s)
            if not v["ok"]:
                invalid += 1
            elif v["status"] in ("untrusted", "unknown_signer", "revoked"):
                untrusted += 1
    fsck = _fsck_status(repo)
    sig_status = "invalid" if invalid else ("unsigned" if unsigned else "valid")
    alerts = []
    if unsigned:
        alerts.append({"kind": "unsigned_accepted",
                       "message": "{} accepted snapshot(s) are unsigned".format(len(unsigned))})
    if fsck == "corrupt":
        alerts.append({"kind": "corrupt_store", "message": "object store has corruption"})
    if untrusted:
        alerts.append({"kind": "untrusted_signer", "message": "{} signature(s) by untrusted signers".format(untrusted)})
    return {
        "owner": owner, "name": name,
        "branch_count": len(refs), "recent_sessions": len(sessions),
        "latest_accepted_snapshot": head or "",
        "policy_status": "allow", "signature_status": sig_status,
        "trust_status": "untrusted" if untrusted else "trusted",
        "fsck_status": fsck, "alerts": alerts,
    }


def ui_list_repos(ctx):
    out = []
    scope = ctx.token.get("repo_scope", "*")
    for full in ctx.store.list_repos():
        if scope != "*" and scope != full:
            continue
        o, n = full.split("/", 1)
        repo = ctx.store.get_repo(o, n)
        if repo:
            out.append(_repo_summary(ctx.store, o, n, repo))
    return 200, out


def ui_get_repo(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    return 200, _repo_summary(ctx.store, o, n, repo)


def ui_list_sessions(ctx):
    from .. import util
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    out = []
    for sid in repo.session_ids():
        sess = util.read_json(repo.paths.session_dir(sid) / "session.json", None)
        if sess:
            out.append(_ui_session(repo, sess))
    return 200, out


def _load_session(repo, sid):
    from .. import util
    return util.read_json(repo.paths.session_dir(sid) / "session.json", None)


def ui_get_session(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sess = _load_session(repo, ctx.params[2])
    return (200, _ui_session(repo, sess)) if sess else (404, {"error": "no such session"})


def ui_timeline(ctx):
    from .. import timeline as timelinemod
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sid = ctx.params[2]
    glyph = {"session_started": "Session started", "autosave_created": "Autosave",
             "snapshot_created": "Snapshot", "verification_run": "Verification",
             "accepted": "Accepted", "rollback": "Rolled back", "recover_invoked": "Recover"}
    out = []
    for i, e in enumerate(timelinemod.read(repo, sid)):
        p = e.get("payload", {})
        out.append({
            "id": "{}-{}".format(sid, i), "type": e["type"], "at": e["timestamp"],
            "title": glyph.get(e["type"], e["type"]),
            "detail": str(p.get("instruction") or p.get("message") or p.get("autosave_id")
                          or p.get("overall") or p.get("target") or ""),
            "recovery_only": e["type"] == "autosave_created",
            "object_id": p.get("snapshot") or p.get("autosave_id"),
        })
    return 200, out


def ui_diff(ctx):
    from .. import util
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sess = _load_session(repo, ctx.params[2])
    if not sess:
        return 404, {"error": "no such session"}
    pkt = util.read_json(repo.paths.session_dir(ctx.params[2]) / "packet.json", None)
    if pkt and pkt.get("base_tree") and pkt.get("current_tree"):
        return 200, _ui_diff_files(repo, pkt["base_tree"], pkt["current_tree"])
    base = (sess.get("base", {}) or {}).get("tree")
    res = (sess.get("result") or {}).get("snapshot")
    cur = repo.get_object(res)["tree"] if res and repo.has_object(res) else None
    return 200, _ui_diff_files(repo, base, cur)


def ui_packet(ctx):
    from .. import util
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    pkt = util.read_json(repo.paths.session_dir(ctx.params[2]) / "packet.json", None)
    if not pkt:
        return 200, None
    return 200, {
        "instruction": pkt.get("instruction", ""),
        "summary": pkt.get("recommended_commit_message", ""),
        "risk_tags": [r for r in pkt.get("risks", []) if not r.startswith("secrets-detected")],
        "changed_paths": [f["path"] for f in pkt.get("changed_files", [])],
        "recommended_action": pkt.get("recommended_next_action", ""),
        "accepted_snapshot": None,
    }


def ui_verification(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sess = _load_session(repo, ctx.params[2])
    if not sess:
        return 404, {"error": "no such session"}
    rec = _last_verification(repo, sess)
    if not rec:
        return 200, []
    out = []
    for r in rec.get("results", []):
        out.append({"command": r.get("command", r.get("name", "")),
                    "status": r.get("status", "skipped"),
                    "duration_ms": int(round(r.get("duration_seconds", 0) * 1000)),
                    "summary": (r.get("stdout_summary") or "").splitlines()[-1] if r.get("stdout_summary") else "",
                    "stdout_excerpt": r.get("stdout_summary"), "stderr_excerpt": r.get("stderr_summary")})
    return 200, out


def ui_session_policy(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sess = _load_session(repo, ctx.params[2])
    if not sess:
        return 404, {"error": "no such session"}
    pol = policymod.load(repo)
    if pol is None:
        return 200, None
    # use the faithful input (real verification results, signature, acceptor trust)
    d = policymod.evaluate(pol, _session_policy_input(repo, sess))
    return 200, _ui_decision(d)


def _ui_decision(d):
    return {"effect": d["effect"], "matched_rules": d.get("rules_matched", []),
            "reasons": d.get("reasons", []), "required_actions": d.get("required_actions", []),
            "override_available": d.get("override_available", False),
            "override_used": d.get("override_used", False)}


def ui_session_signatures(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    sess = _load_session(repo, ctx.params[2])
    if not sess:
        return 404, {"error": "no such session"}
    snap = (sess.get("result") or {}).get("snapshot")
    return 200, _signatures_for_snap(repo, snap)


def _signatures_for_snap(repo, snap):
    if not snap:
        return []
    out = []
    for s in signmod.signatures_for(repo, snap):
        v = signmod.verify_record(repo, s)
        idrec = idmod.load(repo, s.get("signer_identity_id")) or {}
        out.append({
            "signer_name": idrec.get("name") or s.get("signer_identity_id", "unknown"),
            "signer_type": idrec.get("type", "human"),
            "trust_status": _trust_of(idrec),
            "status": "valid" if v["ok"] else "invalid",
            "signed_at": s.get("signed_at"),
            "fingerprint": s.get("signer_fingerprint"),
        })
    return out


def _ui_integrity(repo):
    f = fsckmod.check(repo, strict=False)
    try:
        gcrep = gcmod.collect(repo, dry_run=True)
        gc_summary = "{} reclaimable, {} bytes".format(len(gcrep.get("candidates", [])), gcrep.get("bytes_reclaimed", 0))
    except Exception:
        gc_summary = "n/a"
    sealed = all(objects.verify_seal(repo.get_object(o)) for o in repo.history()
                 if repo.get_object(o).get("kind") == objects.KIND_ACCEPTED) if repo.head_snapshot() else True
    return {"fsck_status": f["result"], "seal_status": "sealed" if sealed else "unsealed",
            "object_count": f["objects_scanned"], "dangling_count": f["dangling"],
            "corrupt_count": len(f["corrupt"]), "missing_count": len(f["missing"]),
            "last_gc_result": gc_summary}


def ui_integrity(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    return 200, _ui_integrity(repo)


def ui_fsck(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    return 200, _ui_integrity(repo)


def ui_policy_config(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    pol = policymod.load(repo) or {}
    return 200, {
        "protected_branches": pol.get("protected_branches", []),
        "path_rules": [{"pattern": ", ".join(r.get("paths", [])), "rule": r.get("label") or "rule"}
                       for r in pol.get("path_rules", [])],
        "actor_rules": [{"actor": a, "rule": ", ".join(k for k, v in caps.items() if v)}
                        for a, caps in (pol.get("actor_rules", {}) or {}).items()],
        "remote_rules": ["{}={}".format(k, v) for k, v in (pol.get("remote_rules", {}) or {}).items()],
        "override_rules": ["{}={}".format(k, v) for k, v in (pol.get("override_rules", {}) or {}).items()],
    }


def ui_policy_check(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    pol = policymod.load(repo)
    if pol is None:
        return 200, {"effect": "allow", "matched_rules": [], "reasons": [],
                     "required_actions": [], "override_available": False, "override_used": False}
    return 200, _ui_decision(policymod.evaluate(pol, ctx.body or {}))


def ui_branches(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    out = []
    for b in repo.list_branches():
        head = repo.read_ref("refs/heads/{}".format(b))
        last = None
        if head and repo.has_object(head):
            last = repo.get_object(head).get("session")
        out.append({"name": b, "accepted_snapshot": head or "", "last_session": last,
                    "ahead": 0, "behind": 0})
    return 200, out


def ui_identities(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    out = []
    for i in idmod.list_all(repo):
        out.append({"name": i.get("name") or i.get("identity_id"), "type": i.get("type", "human"),
                    "fingerprint": i.get("fingerprint", ""), "trust_status": _trust_of(i),
                    "created_at": i.get("created_at", ""), "capabilities": i.get("capabilities", [])})
    return 200, out


def ui_verify_signatures(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    # flatten all signatures across accepted history into frontend Signature[]
    out = []
    seen = set()
    for b in repo.list_branches():
        for oid in repo.history(repo.read_ref("refs/heads/{}".format(b))):
            if oid in seen:
                continue
            seen.add(oid)
            out.extend(_signatures_for_snap(repo, oid))
    return 200, out


def ui_audit(ctx):
    repo, err, o, n = _repo(ctx)
    if err:
        return err
    rows = ctx.store.read_audit(ctx.params[0], ctx.params[1])
    out = []
    for i, e in enumerate(rows):
        res = e.get("result", "success")
        result = "denied" if res in ("policy-denied", "rejected", "denied") else ("error" if res == "error" else "success")
        out.append({"id": "{}-{}".format(e.get("timestamp", ""), i), "timestamp": e.get("timestamp", ""),
                    "actor": e.get("actor", "server"), "operation": e.get("operation", ""),
                    "result": result, "ref_update": e.get("ref"), "server_receipt": e.get("receipt")})
    return 200, out


# (method, regex, handler, required_scope) — appended to the server's ROUTES
ROUTES = [
    ("GET", r"^/ui/health$", ui_health, None),
    ("GET", r"^/ui/repos$", ui_list_repos, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)$", ui_get_repo, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions$", ui_list_sessions, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/timeline$", ui_timeline, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/diff$", ui_diff, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/packet$", ui_packet, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/verification$", ui_verification, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/policy$", ui_session_policy, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)/signatures$", ui_session_signatures, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/sessions/([^/]+)$", ui_get_session, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/integrity$", ui_integrity, "repo:read"),
    ("POST", r"^/ui/repos/([^/]+)/([^/]+)/fsck$", ui_fsck, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/policy$", ui_policy_config, "policy:read"),
    ("POST", r"^/ui/repos/([^/]+)/([^/]+)/policy/check$", ui_policy_check, "policy:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/branches$", ui_branches, "refs:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/identities$", ui_identities, "identity:read"),
    ("POST", r"^/ui/repos/([^/]+)/([^/]+)/signatures/verify$", ui_verify_signatures, "repo:read"),
    ("GET", r"^/ui/repos/([^/]+)/([^/]+)/audit$", ui_audit, "repo:read"),
]
