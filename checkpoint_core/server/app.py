"""Checkpoint hosted API — stdlib HTTP server. No Git.

The server never trusts the client: every uploaded object is content-verified, every
received closure is checked (seals, parents, trees, signatures), and policy is evaluated
before any ref moves. Reads/writes are gated by API-token scopes; writes take a per-repo
lock and update refs atomically.
"""
from __future__ import annotations

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import objects, util
from .. import fsck as fsckmod, gc as gcmod, identity as idmod, ledger as ledgermod
from .. import policy as policymod, reachable as reachablemod, remote as remotemod
from .. import sign as signmod, sync as syncmod, timeline as timelinemod, verify as verifymod
from ..diff import diff_result
from ..merge import three_way
from ..store import Repo
from . import API_VERSION, PROTOCOL_VERSION
from .store import ServerStore

_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _scope_ok(token_scopes: List[str], required: Optional[str]) -> bool:
    if required is None:
        return True
    s = set(token_scopes or [])
    if "admin" in s or required in s:
        return True
    if required.endswith(":read") and ("repo:read" in s or "repo:write" in s):
        return True
    if required in ("refs:write", "objects:write", "identity:write", "policy:write") and "repo:write" in s:
        return True
    if required in ("refs:read", "objects:read", "identity:read", "policy:read") and "repo:write" in s:
        return True
    return False


class Ctx:
    def __init__(self, store, params, body, raw, token):
        self.store = store
        self.params = params          # regex groups
        self.body = body              # parsed JSON dict (or None)
        self.raw = raw                # raw bytes body
        self.token = token            # token record or None


# ----------------------------------------------------------------- handlers

def _repo_or_404(ctx) -> Tuple[Optional[Repo], Optional[Tuple[int, Any]]]:
    owner, name = ctx.params[0], ctx.params[1]
    if not (_NAME.match(owner) and _NAME.match(name)):
        return None, (400, {"error": "invalid owner/repo name"})
    repo = ctx.store.get_repo(owner, name)
    if repo is None:
        return None, (404, {"error": "no such repo"})
    return repo, None


from pathlib import Path as _Path
_WEB_DIR = _Path(__file__).parent / "web"
_STATIC = {
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}


def h_index(ctx):
    f = _WEB_DIR / "index.html"
    if not f.exists():
        return 200, {"error": "web UI not built"}
    return 200, ("bytes", "text/html; charset=utf-8", f.read_bytes())


def h_static(ctx):
    name = ctx.params[0]
    ctype = _STATIC.get(name)
    f = _WEB_DIR / name
    if ctype is None or not f.exists():
        return 404, {"error": "not found"}
    return 200, ("bytes", ctype, f.read_bytes())


def h_health(ctx):
    return 200, {"status": "ok"}


def h_version(ctx):
    return 200, {"api": API_VERSION, "protocol": PROTOCOL_VERSION,
                 "server_id": ctx.store.server_id()}


def h_capabilities(ctx):
    return 200, {"features": ["objects", "refs", "sync", "bundles", "sessions", "diff",
                              "merge-preview", "signatures", "identities", "policy",
                              "fsck", "gc", "audit"],
                 "transfer": "object-level", "fast_forward_default": True,
                 "no_git": True}


def h_repo_create(ctx):
    body = ctx.body or {}
    owner, name = body.get("owner"), body.get("repo")
    if not (owner and name and _NAME.match(owner) and _NAME.match(name)):
        return 400, {"error": "owner and repo are required and must be safe names"}
    if ctx.store.repo_exists(owner, name):
        return 409, {"error": "repo already exists"}
    ctx.store.create_repo(owner, name, body.get("branch", "main"))
    ctx.store.audit(owner, name, {"operation": "create_repo", "actor": ctx.token.get("token_id")})
    return 201, {"owner": owner, "repo": name, "default_branch": body.get("branch", "main")}


def h_repo_list(ctx):
    scope = ctx.token.get("repo_scope", "*")
    repos = ctx.store.list_repos()
    if scope != "*":
        repos = [r for r in repos if r == scope]
    return 200, {"repos": repos}


def h_repo_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    branches = {b: repo.read_ref("refs/heads/{}".format(b)) for b in repo.list_branches()}
    return 200, {"owner": ctx.params[0], "repo": ctx.params[1],
                 "head": repo.head_snapshot(), "branches": branches}


def h_repo_delete(ctx):
    owner, name = ctx.params[0], ctx.params[1]
    ok = ctx.store.delete_repo(owner, name)
    return (200, {"deleted": True}) if ok else (404, {"error": "no such repo"})


def h_refs_list(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    heads = {b: repo.read_ref("refs/heads/{}".format(b)) for b in repo.list_branches()}
    tags = {}
    tdir = repo.paths.base / "refs" / "tags"
    if tdir.exists():
        for t in tdir.iterdir():
            if t.is_file():
                tags[t.name] = t.read_text(encoding="utf-8").strip()
    return 200, {"heads": heads, "tags": tags}


def h_ref_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    ref = ctx.params[2]
    target = repo.read_ref(ref) if ref.startswith("refs/") else repo.read_ref("refs/heads/{}".format(ref))
    if not target:
        return 404, {"error": "no such ref"}
    return 200, {"ref": ref, "target": target}


def h_object_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    oid = ctx.params[2]
    if not re.match(r"^[0-9a-f]{64}$", oid):
        return 400, {"error": "invalid object id"}
    if not repo.has_object(oid):
        return 404, {"error": "no such object"}
    return 200, ("bytes", "application/octet-stream", (repo.paths.objects / oid[:2] / oid).read_bytes())


def h_objects_batch(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    body = ctx.body or {}
    if "get" in body:                                  # download
        out = []
        for oid in body["get"]:
            if repo.has_object(oid):
                data = (repo.paths.objects / oid[:2] / oid).read_bytes()
                out.append({"id": oid, "data_b64": base64.b64encode(data).decode("ascii")})
        return 200, {"objects": out}
    # upload (objects:write)
    if not _scope_ok(ctx.token.get("scopes", []), "objects:write"):
        return 403, {"error": "objects:write scope required"}
    stored, rejected = [], []
    with ctx.store.repo_lock(ctx.params[0], ctx.params[1]):
        for o in body.get("objects", []):
            try:
                data = base64.b64decode(o["data_b64"])
            except Exception:
                rejected.append({"id": o.get("id"), "reason": "bad base64"})
                continue
            if util.sha256_bytes(data) != o.get("id"):
                rejected.append({"id": o.get("id"), "reason": "content hash mismatch"})
                continue
            dest = repo.paths.objects / o["id"][:2] / o["id"]
            if not dest.exists():
                remotemod._atomic_write(dest, data)
            stored.append(o["id"])
    return 200, {"stored": stored, "rejected": rejected}


def h_objects_verify(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    out = {}
    for oid in (ctx.body or {}).get("ids", []):
        present = repo.has_object(oid)
        valid = present and util.sha256_bytes((repo.paths.objects / oid[:2] / oid).read_bytes()) == oid
        out[oid] = {"present": present, "hash_valid": valid}
    return 200, {"results": out}


def h_objects_stats(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    counts = {"blob": 0, "tree": 0, "snapshot": 0, "unknown": 0}
    total = 0
    for oid in reachablemod.iter_object_ids(repo):
        kind, _ = reachablemod.classify(repo, oid)
        counts[kind if kind in counts else "unknown"] += 1
        total += reachablemod.object_size(repo, oid)
    return 200, {"counts": counts, "bytes": total}


def h_sync_plan(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    have = (ctx.body or {}).get("oids", [])
    missing = [o for o in have if not repo.has_object(o)]
    return 200, {"missing": missing}


def _install_aux(repo, body):
    """Install signatures / public identities / sessions from a push body (safe)."""
    for oid, sigs in (body.get("signatures") or {}).items():
        if not re.match(r"^[0-9a-f]{64}$", oid):
            continue
        for s in sigs:
            sid = s.get("signature_id", "")
            if not re.match(r"^[A-Za-z0-9_.-]+$", sid):
                continue
            util.write_json(repo.paths.signatures / oid / (sid + ".json"), s)
    for rec in body.get("identities") or []:
        if "identity_id" not in rec or not _NAME.match(rec["identity_id"]):
            continue
        dest = repo.paths.identities / (rec["identity_id"] + ".json")
        if not dest.exists():
            rec = dict(rec)
            rec["trusted"] = False
            rec.setdefault("revoked", False)
            util.write_json(dest, rec)
    for sess in body.get("sessions") or []:
        sid = sess.get("id", "")
        if not re.match(r"^[A-Za-z0-9_.-]+$", sid):
            continue
        for rel, b64 in (sess.get("files") or {}).items():
            parts = rel.split("/")
            if ".." in parts or rel.startswith("/") or "keys" in parts or rel.endswith(".key"):
                continue
            if parts and parts[0] == "autosaves":
                continue
            try:
                data = base64.b64decode(b64)
            except Exception:
                continue
            dest = repo.paths.session_dir(sid) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)


def _apply_ref_update(ctx, repo, owner, name, branch, old, new, fwl, uploaded=0):
    """Shared verified ref update: closure -> policy -> fast-forward/lease -> atomic write."""
    pol = policymod.load(repo)
    require_sigs = bool(pol and (pol.get("required_signatures", {}) or {}).get("accepts"))
    ok, errs = remotemod.verify_received(repo, new, require_signatures=require_sigs)
    if not ok:
        ctx.store.audit(owner, name, {"operation": "ref_update", "result": "rejected", "errors": errs[:10]})
        return 422, {"error": "closure verification failed", "details": errs[:20]}

    cur = repo.read_ref("refs/heads/{}".format(branch))
    decision_ids = []
    if pol is not None:
        old_tree = repo.get_object(cur)["tree"] if cur and repo.has_object(cur) else None
        try:
            new_tree = repo.get_object(new)["tree"]
            dr = diff_result(repo, old_tree, new_tree)
            changed = dr["added"] + dr["deleted"] + dr["modified"] + [r["new_path"] for r in dr["renamed"]]
        except Exception:
            changed = []
        ut = "force_with_lease" if fwl is not None else "fast_forward"
        decision = policymod.evaluate(pol, {"operation": "push",
                                            "actor_type": _pusher_actor_type(repo, new),
                                            "branch": branch, "changed_paths": changed,
                                            "ref_update_type": ut,
                                            "history_signed": _history_signed(repo, new)})
        _record_server_policy(repo, decision)
        decision_ids.append(decision["decision_id"])
        if decision["effect"] == "deny":
            ctx.store.audit(owner, name, {"operation": "push", "result": "policy-denied",
                                          "reasons": decision["reasons"]})
            return 403, {"error": "policy denied", "reasons": decision["reasons"],
                         "required_actions": decision["required_actions"]}

    forced = False
    if fwl is not None:
        if cur != fwl:
            return 409, {"error": "stale lease", "remote_head": cur, "expected": fwl}
        forced = True
    else:
        if cur != old:
            return 409, {"error": "non-fast-forward: remote moved", "remote_head": cur}
        if cur is not None and not repo.is_ancestor(cur, new):
            return 409, {"error": "non-fast-forward"}

    remotemod.atomic_update_ref(repo, "refs/heads/{}".format(branch), new)
    receipt = {
        "receipt_id": "rcpt_" + util.stamp() + "_" + util.sha256_bytes(new.encode())[:6],
        "repo": "{}/{}".format(owner, name), "operation": "push",
        "ref_updates": [{"ref": "refs/heads/{}".format(branch), "old": cur, "new": new}],
        "objects_received": uploaded, "policy_decision_ids": decision_ids,
        "fsck_summary": {"closure": "verified"}, "created_at": util.now_iso(),
        "server_identity_id": ctx.store.server_id(), "forced": forced,
    }
    ctx.store.audit(owner, name, {"operation": "push", "result": "ok", "ref": branch,
                                  "new": new, "receipt": receipt["receipt_id"]})
    return 200, {"receipt": receipt}


def h_sync_push(ctx):
    owner, name = ctx.params[0], ctx.params[1]
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    body = ctx.body or {}
    branch, new, old = body.get("branch"), body.get("new_head"), body.get("old_head")
    fwl = body.get("force_with_lease")
    if not (branch and new):
        return 400, {"error": "branch and new_head required"}
    with ctx.store.repo_lock(owner, name):
        _install_aux(repo, body)
        return _apply_ref_update(ctx, repo, owner, name, branch, old, new, fwl,
                                 uploaded=len(body.get("uploaded", [])))


def h_refs_update(ctx):
    owner, name = ctx.params[0], ctx.params[1]
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    body = ctx.body or {}
    ref = body.get("ref", "")
    branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    new = body.get("new_target")
    if not (branch and new):
        return 400, {"error": "ref and new_target required"}
    with ctx.store.repo_lock(owner, name):
        return _apply_ref_update(ctx, repo, owner, name, branch, body.get("old_target"),
                                 new, body.get("force_with_lease"))


def h_sync_fetch(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    branch = (ctx.body or {}).get("branch")
    head = repo.read_ref("refs/heads/{}".format(branch)) if branch else repo.head_snapshot()
    if not head:
        return 404, {"error": "no such branch"}
    oids = sorted(syncmod.reachable_objects(repo, head))
    # session-referenced objects too (so the client stays self-consistent)
    sess_ids = set()
    sigs = {}
    for oid in oids:
        for s in signmod.signatures_for(repo, oid):
            sigs.setdefault(oid, []).append(s)
        try:
            o = repo.get_object(oid)
            if o.get("type") == "snapshot" and o.get("session"):
                sess_ids.add(o["session"])
        except Exception:
            pass
    extra = set()
    for sid in sess_ids:
        extra |= remotemod._session_object_ids(repo, sid)
    all_oids = sorted(set(oids) | extra)
    identities = [util.read_json(f, {}) for f in sorted(repo.paths.identities.glob("*.json"))] \
        if repo.paths.identities.exists() else []
    sessions = []
    for sid in sorted(sess_ids):
        files = {}
        sdir = repo.paths.session_dir(sid)
        for p in sdir.rglob("*"):
            if p.is_file() and p.relative_to(sdir).parts[0] != "autosaves":
                files[str(p.relative_to(sdir))] = base64.b64encode(p.read_bytes()).decode("ascii")
        sessions.append({"id": sid, "files": files})
    return 200, {"head": head, "oids": all_oids, "signatures": sigs,
                 "identities": identities, "sessions": sessions}


def h_bundle_export(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    import tempfile
    from pathlib import Path
    branch = ctx.params and None
    qbranch = ctx.query.get("branch") if hasattr(ctx, "query") else None
    out = Path(tempfile.mkdtemp()) / "bundle.tar.gz"
    syncmod.create_bundle(repo, out, branch=qbranch, tags=True)
    data = out.read_bytes()
    return 200, ("bytes", "application/gzip", data)


def h_bundle_import(ctx):
    owner, name = ctx.params[0], ctx.params[1]
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp()) / "in.tar.gz"
    tmp.write_bytes(ctx.raw or b"")
    pol = policymod.load(repo)
    require_sigs = bool(pol and (pol.get("remote_rules", {}) or {}).get("require_signed_snapshots"))
    rep = syncmod.verify_bundle(tmp, require_signatures=require_sigs)
    if not rep["ok"]:
        ctx.store.audit(owner, name, {"operation": "bundle_import", "result": "rejected"})
        return 422, {"error": "bundle verification failed", "details": rep["errors"][:20]}
    with ctx.store.repo_lock(owner, name):
        res = syncmod.import_bundle(repo, tmp, require_signatures=require_sigs)
    if not res.get("ok"):
        return 422, {"error": "bundle import failed", "details": res.get("errors", [])}
    ctx.store.audit(owner, name, {"operation": "bundle_import", "result": "ok", "refs": res.get("refs")})
    return 200, {"imported": True, "refs": res.get("refs"), "head": res.get("head")}


def h_sessions_list(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    out = []
    for sid in repo.session_ids():
        s = util.read_json(repo.paths.session_dir(sid) / "session.json", {})
        out.append({"session_id": sid, "instruction": s.get("instruction"),
                    "status": s.get("status"), "actor": s.get("actor")})
    return 200, {"sessions": out}


def h_session_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    s = util.read_json(repo.paths.session_dir(ctx.params[2]) / "session.json", None)
    return (200, s) if s else (404, {"error": "no such session"})


def h_session_timeline(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, {"events": timelinemod.read(repo, ctx.params[2])}


def h_session_packet(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    pkt = util.read_json(repo.paths.session_dir(ctx.params[2]) / "packet.json", None)
    return (200, pkt) if pkt else (404, {"error": "no packet"})


def h_diff(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    body = ctx.body or {}

    def tree_of(ref):
        if not ref:
            return None
        kind, obj = reachablemod.classify(repo, ref)
        return obj["tree"] if kind == "snapshot" else ref
    a, b = tree_of(body.get("from")), tree_of(body.get("to"))
    result = diff_result(repo, a, b)
    if body.get("unified"):
        from ..diff import unified_result
        result["unified"] = unified_result(repo, a, b)
    return 200, result


def h_merge_preview(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    body = ctx.body or {}
    ours, theirs = body.get("ours"), body.get("theirs")
    if not (ours and theirs):
        return 400, {"error": "ours and theirs required"}
    base = repo.merge_base(ours, theirs)
    res = three_way(repo, repo.get_object(ours)["tree"], repo.get_object(theirs)["tree"],
                    repo.get_object(base)["tree"] if base else None)
    return 200, {"clean": res["clean"], "conflicts": res["conflicts"],
                 "auto_merged": res["auto_merged"], "rename_records": res["rename_records"]}


def h_identities_list(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, {"identities": [idmod.public_view(r) for r in idmod.list_all(repo)]}


def h_identities_import(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    rec = (ctx.body or {}).get("identity")
    if not rec:
        return 400, {"error": "identity record required"}
    imported = idmod.import_record(repo, rec)
    return 200, {"identity_id": imported["identity_id"], "trusted": False}


def _identity_trust_op(ctx, op):
    owner, name = ctx.params[0], ctx.params[1]
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    iid = ctx.params[2]
    pol = policymod.load(repo)
    if pol is not None:
        decision = policymod.evaluate(pol, {"operation": "revoke" if op == "revoke" else "trust",
                                            "actor_type": "ci"})
        _record_server_policy(repo, decision)
        if decision["effect"] == "deny":
            return 403, {"error": "policy denied", "reasons": decision["reasons"]}
    if op == "trust":
        rec = idmod.set_trust(repo, iid, True)
    elif op == "untrust":
        rec = idmod.set_trust(repo, iid, False)
    else:
        rec = idmod.revoke(repo, iid)
    if not rec:
        return 404, {"error": "no such identity"}
    ctx.store.audit(owner, name, {"operation": "identity_" + op, "identity": iid})
    return 200, {"identity_id": iid, "op": op}


def h_signatures_list(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, {"signatures": signmod.iter_all(repo)}


def h_verify_signatures(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, signmod.verify_all(repo)


def h_policy_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, {"policy": policymod.load(repo)}


def h_policy_put(ctx):
    owner, name = ctx.params[0], ctx.params[1]
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    pol = (ctx.body or {}).get("policy")
    if pol is None:
        return 400, {"error": "policy required"}
    errs = policymod.validate(pol)
    if errs:
        return 422, {"error": "invalid policy", "details": errs}
    import yaml
    with open(policymod.policy_path(repo), "w", encoding="utf-8") as fh:
        fh.write(yaml.safe_dump(pol, sort_keys=False))
    ctx.store.audit(owner, name, {"operation": "policy_update"})
    return 200, {"updated": True}


def h_policy_check(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    pol = policymod.load(repo)
    if pol is None:
        return 200, {"effect": "allow", "note": "no policy configured"}
    decision = policymod.evaluate(pol, (ctx.body or {}))   # READ-ONLY
    return 200, decision


def h_policy_decisions(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    rows = [e["payload"] for e in ledgermod.read_all(repo) if e["event_type"] == "policy"]
    return 200, {"decisions": rows}


def h_policy_decision_get(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    did = ctx.params[2]
    for e in ledgermod.read_all(repo):
        if e["event_type"] == "policy" and e["payload"].get("decision_id") == did:
            return 200, e["payload"]
    return 404, {"error": "no such decision"}


def h_fsck(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, fsckmod.check(repo, strict=False)


def h_gc(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    dry = bool((ctx.body or {}).get("dry_run", True))
    with ctx.store.repo_lock(ctx.params[0], ctx.params[1]):
        rep = gcmod.collect(repo, dry_run=dry)
    return 200, rep


def h_audit(ctx):
    repo, err = _repo_or_404(ctx)
    if err:
        return err
    return 200, {"audit": ctx.store.read_audit(ctx.params[0], ctx.params[1])}


# ----------------------------------------------------------------- helpers

def _history_signed(repo, head) -> bool:
    for oid in repo.history(head):
        if not signmod.signatures_for(repo, oid):
            return False
    return True


def _pusher_actor_type(repo, snap) -> str:
    """The actor a push represents: the type of the pushed snapshot's signer (human/agent/
    ci/…). A hosted push transports an already-accepted snapshot, so policy should judge it
    by who signed it, not by a hardcoded role. Falls back to 'ci' when unsigned/unknown."""
    try:
        for s in signmod.signatures_for(repo, snap):
            idr = idmod.load(repo, s.get("signer_identity_id"))
            if idr and idr.get("type"):
                return idr["type"]
    except Exception:
        pass
    return "ci"


def _record_server_policy(repo, decision):
    ledgermod.append(repo, "policy", decision.get("session_id"), {"id": "server"}, {
        "operation": decision["operation"], "effect": decision["effect"],
        "decision_id": decision["decision_id"], "reasons": decision["reasons"],
        "rules_matched": decision["rules_matched"],
    })


# ----------------------------------------------------------------- routing

# (method, regex, handler, required_scope)
ROUTES: List[Tuple[str, Any, Callable, Optional[str]]] = [
    ("GET", r"^/$", h_index, None),
    ("GET", r"^/(app\.js|style\.css)$", h_static, None),
    ("GET", r"^/health$", h_health, None),
    ("GET", r"^/version$", h_version, None),
    ("GET", r"^/capabilities$", h_capabilities, None),
    ("POST", r"^/repos$", h_repo_create, "repo:write"),
    ("GET", r"^/repos$", h_repo_list, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)$", h_repo_get, "repo:read"),
    ("DELETE", r"^/repos/([^/]+)/([^/]+)$", h_repo_delete, "admin"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/refs$", h_refs_list, "refs:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/refs/update$", h_refs_update, "refs:write"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/refs/(.+)$", h_ref_get, "refs:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/objects/batch$", h_objects_batch, "objects:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/objects/verify$", h_objects_verify, "objects:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/objects/stats$", h_objects_stats, "objects:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/objects/([^/]+)$", h_object_get, "objects:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/sync/plan$", h_sync_plan, "objects:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/sync/push$", h_sync_push, "refs:write"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/sync/fetch$", h_sync_fetch, "repo:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/bundles/import$", h_bundle_import, "repo:write"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/bundles/export$", h_bundle_export, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/sessions$", h_sessions_list, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/sessions/([^/]+)/timeline$", h_session_timeline, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/sessions/([^/]+)/packet$", h_session_packet, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/sessions/([^/]+)$", h_session_get, "repo:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/diff$", h_diff, "repo:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/merge-preview$", h_merge_preview, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/identities$", h_identities_list, "identity:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/identities/import$", h_identities_import, "identity:write"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/identities/([^/]+)/trust$",
     lambda c: _identity_trust_op(c, "trust"), "identity:write"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/identities/([^/]+)/untrust$",
     lambda c: _identity_trust_op(c, "untrust"), "identity:write"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/identities/([^/]+)/revoke$",
     lambda c: _identity_trust_op(c, "revoke"), "identity:write"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/signatures$", h_signatures_list, "repo:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/verify-signatures$", h_verify_signatures, "repo:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/policy$", h_policy_get, "policy:read"),
    ("PUT", r"^/repos/([^/]+)/([^/]+)/policy$", h_policy_put, "policy:write"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/policy/check$", h_policy_check, "policy:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/policy/decisions/([^/]+)$", h_policy_decision_get, "policy:read"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/policy/decisions$", h_policy_decisions, "policy:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/fsck$", h_fsck, "repo:read"),
    ("POST", r"^/repos/([^/]+)/([^/]+)/gc$", h_gc, "repo:write"),
    ("GET", r"^/repos/([^/]+)/([^/]+)/audit$", h_audit, "repo:read"),
]

from . import ui_api as _ui_api          # BFF adapter for the Next.js review UI (/ui/*)
ROUTES = ROUTES + _ui_api.ROUTES

_COMPILED = [(m, re.compile(rx), fn, sc) for (m, rx, fn, sc) in ROUTES]


def make_handler(store: ServerStore):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        # ---- io
        def _read_body(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(length) if length else b""

        def _cors(self):
            # Dev CORS so a separate frontend dev server (e.g. Next on :3000) can call the API.
            origin = store.load_config().get("cors_origin", "*")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

        def _send_json(self, status, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, status, ctype, data):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _bearer(self):
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return auth[7:].strip()
            return None

        def _dispatch(self, method):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            path = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            raw = self._read_body()
            for (m, rx, fn, scope) in _COMPILED:
                if m != method:
                    continue
                match = rx.match(path)
                if not match:
                    continue
                # auth
                token = store.resolve_token(self._bearer()) if scope is not None else {"scopes": ["admin"], "repo_scope": "*"}
                if scope is not None:
                    if token is None:
                        return self._send_json(401, {"error": "authentication required"})
                    # repo scope check
                    groups = match.groups()
                    if len(groups) >= 2:
                        rscope = token.get("repo_scope", "*")
                        if rscope != "*" and rscope != "{}/{}".format(groups[0], groups[1]):
                            return self._send_json(403, {"error": "token not scoped to this repo"})
                    if not _scope_ok(token.get("scopes", []), scope):
                        return self._send_json(403, {"error": "missing scope: {}".format(scope)})
                # body parse
                body = None
                ctype = self.headers.get("Content-Type", "")
                if raw and "application/json" in ctype:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except Exception:
                        return self._send_json(400, {"error": "malformed JSON"})
                ctx = Ctx(store, match.groups(), body, raw, token)
                ctx.query = query
                try:
                    result = fn(ctx)
                except Exception as exc:  # pragma: no cover - defensive
                    return self._send_json(500, {"error": "server error", "detail": str(exc)})
                status, payload = result
                if isinstance(payload, tuple) and payload and payload[0] == "bytes":
                    return self._send_bytes(status, payload[1], payload[2])
                return self._send_json(status, payload)
            return self._send_json(404, {"error": "not found"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

    return Handler


def serve(store: ServerStore, host: str = "127.0.0.1", port: int = 8800):
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    return httpd
