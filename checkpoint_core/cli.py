"""Checkpoint Core CLI: a Git-replacement VCS. No Git in the core path.

Commands: init, identity, start, status, snapshot, diff, verify, packet, accept,
reject, rollback, log, history, show, branch, checkout, merge, remote, push, pull,
bundle, git-export, git-import, verify-history, doctor.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, objects, util
from . import autosave as autosavemod, engine, ledger as ledgermod
from . import merge as mergemod, secrets as secretscan, timeline as timelinemod
from . import sync as syncmod, verify as verifymod
from .watcher import Watcher
from .config import Config, default_config
from .diff import diff_result, tree_diff, unified, unified_result
from .ignore import DEFAULT_CHECKPOINTIGNORE
from .session import Session, ACCEPTED, REJECTED, ROLLED_BACK
from .store import CORE_DIR, NotInitialized, Repo
from .worktree import materialize, scan_to_tree


# --------------------------------------------------------------------------- util

def err(msg: str) -> None:
    print(util.red("error: ") + msg, file=sys.stderr)


def info(msg: str) -> None:
    print(msg)


def confirm(prompt: str, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _repo() -> Repo:
    return Repo.discover()


def _active(repo: Repo) -> Session:
    s = Session.active(repo)
    if s is None:
        raise SystemExit(util.red("error: ") + "no active session. Run `checkpoint-core start \"<instruction>\"`.")
    return s


def _short(oid: Optional[str]) -> str:
    return (oid or "(none)")[:12]


def _status_glyph(s: str) -> str:
    return {"added": util.green("A"), "modified": util.yellow("M"),
            "deleted": util.red("D"), "renamed": util.cyan("R")}.get(s, s[:1].upper())


# -------------------------------------------------------------------------- init

def cmd_init(args) -> int:
    root = Path.cwd()
    repo = Repo(root)
    p = repo.paths
    if p.config.exists() and not args.force:
        if not confirm("Checkpoint Core config exists. Overwrite?", args.yes):
            info("Leaving existing configuration untouched.")
            return 0

    for d in (p.base, p.objects, p.sessions, p.refs_heads, p.tmp, p.cache):
        d.mkdir(parents=True, exist_ok=True)
    if not p.ledger.exists():
        p.ledger.touch()

    branch = args.branch or "main"
    cfg = Config(default_config(project=root.name), p.config)
    cfg.data["default_branch"] = branch
    cfg.save()
    repo._config = None

    if not p.identity.exists():
        ident = {
            "id": args.email or "anon",
            "name": args.name or "",
            "email": args.email or "",
        }
        util.write_json(p.identity, ident)

    # HEAD points at an unborn default branch (no accepted snapshots yet)
    repo.set_head_to_branch(branch)

    cpignore = root / ".checkpointignore"
    if not cpignore.exists():
        cpignore.write_text(DEFAULT_CHECKPOINTIGNORE, encoding="utf-8")

    repo.write_state({"active_session": None})
    ledgermod.append(repo, "init", None, repo.identity(),
                     {"version": __version__, "branch": branch})

    info(util.green("Initialized Checkpoint Core") + " in " + util.bold(str(root)))
    info("  store:   {}/  (this is the source of truth — no Git required)".format(CORE_DIR))
    info("  branch:  {} (unborn)".format(branch))
    info("  config:  {}".format(p.config))
    info("\nNext: checkpoint-core identity --name \"You\" --email you@example.com")
    info("      checkpoint-core start \"<what you are about to do>\"")
    return 0


# ---------------------------------------------------------------------- identity

def cmd_identity(args) -> int:
    repo = _repo()
    ident = repo.identity()
    if not (args.name or args.email):
        info("id:    {}".format(ident.get("id")))
        info("name:  {}".format(ident.get("name")))
        info("email: {}".format(ident.get("email")))
        return 0
    if args.name:
        ident["name"] = args.name
    if args.email:
        ident["email"] = args.email
        ident["id"] = args.email
    util.write_json(repo.paths.identity, ident)
    ledgermod.append(repo, "identity", None, ident, {})
    info(util.green("Identity updated: ") + "{} <{}>".format(ident["name"], ident["email"]))
    return 0


# ------------------------------------------------------------------------- start

def cmd_start(args) -> int:
    repo = _repo()
    if Session.active(repo) is not None:
        err("a session is already active: {}".format(repo.active_session_id()))
        return 1
    instruction = args.instruction
    if args.prompt_file:
        instruction = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not instruction:
        err("an instruction is required: checkpoint-core start \"<instruction>\"")
        return 2

    # The session baseline is the branch head (last accepted state), Git-style.
    # Everything in the working tree since then is the session's proposed work.
    base_tree = repo.head_tree() or repo.put_object(objects.make_tree([]))
    ident = repo.identity()
    actor = {"type": "human", "id": ident.get("id", "anon"), "name": ident.get("name", "")}
    if args.actor:
        actor["type"] = args.actor
    if args.agent:
        actor = {"type": "agent", "id": args.agent, "name": args.agent}
    agent = None
    if actor["type"] == "agent" or args.model or args.tool or args.agent:
        agent = {"name": args.agent, "model": args.model, "tool": args.tool,
                 "prompt": instruction, "response_summary": None,
                 "files_touched": [], "commands_run": []}
    tags = list(args.tag or [])

    sess = Session.create(repo, instruction, actor, agent, tags, base_tree)
    repo.set_active_session(sess.id)
    ledgermod.append(repo, "session_start", sess.id, actor,
                     {"instruction": instruction, "base_tree": base_tree, "risk_tags": tags})
    timelinemod.append(repo, sess.id, "session_started",
                       {"instruction": instruction, "base_snapshot": sess.base_head})

    info(util.green("Started session ") + util.bold(sess.id))
    info("  instruction: {}".format(instruction))
    info("  branch:      {}".format(repo.head_branch() or "(detached)"))
    info("  base:        {}".format(_short(repo.head_snapshot()) if repo.head_snapshot() else "(unborn)"))
    if tags:
        info("  risk tags:   {}".format(", ".join(tags)))
    return 0


# ------------------------------------------------------------------------ status

def cmd_status(args) -> int:
    repo = _repo()
    sess = Session.active(repo)
    if sess is None:
        info("No active session on branch {}.".format(repo.head_branch() or "(detached)"))
        info("Start one with: checkpoint-core start \"<instruction>\"")
        return 0
    autosavemod.create_autosave(repo, sess, reason="status")  # opportunistic safety net
    td = tree_diff(repo, sess.base_tree, scan_to_tree(repo))
    st = td["stats"]
    wt = util.yellow("dirty") if td["files"] else util.green("clean (no changes since start)")

    info(util.bold("Session ") + util.cyan(sess.id))
    info("  instruction: {}".format(sess.data["instruction"]))
    info("  status:      {}".format(sess.status))
    info("  actor:       {} {}".format(sess.actor().get("type"), sess.actor().get("name") or ""))
    info("  branch:      {}".format(repo.head_branch() or "(detached)"))
    info("  worktree:    {}".format(wt))
    info("  changes:     {} files, +{} -{}".format(st["files_changed"], st["insertions"], st["deletions"]))
    for f in td["files"][:50]:
        info("    {} {}".format(_status_glyph(f["status"]), f["path"]))
    autos = sess.data.get("autosaves", [])
    snaps = sess.data.get("snapshots", [])
    info("  last autosave: {} ({} total)".format(autos[-1] if autos else "(none)", len(autos)))
    info("  last snapshot: {}".format(_short(snaps[-1]) if snaps else "(none)"))
    ver = verifymod.last_verification(repo, sess)
    info("  verification:  {}".format(ver.get("overall", "(not run)") if ver else "(not run)"))
    return 0


# ---------------------------------------------------------------------- snapshot

def cmd_snapshot(args) -> int:
    repo = _repo()
    sess = _active(repo)
    snap = engine.create_snapshot(repo, sess, args.message)
    ledgermod.append(repo, "snapshot", sess.id, sess.actor(),
                     {"snapshot": snap["id"], "tree": snap["tree"], "message": args.message})
    timelinemod.append(repo, sess.id, "snapshot_created",
                       {"snapshot": snap["id"], "message": args.message})
    st = snap["stats"]
    info(util.green("Snapshot ") + util.bold(_short(snap["id"])))
    if args.message:
        info("  message: {}".format(args.message))
    info("  changes: {} files, +{} -{}".format(st["files_changed"], st["insertions"], st["deletions"]))
    info("  object:  {}".format(snap["id"]))
    return 0


# -------------------------------------------------------------------------- diff

def cmd_diff(args) -> int:
    repo = _repo()
    sess = _active(repo)

    def tree_for(ref, default):
        if ref is None:
            return default
        return repo.get_object(ref)["tree"]

    base = tree_for(args.from_snapshot, sess.base_tree)
    target = tree_for(args.to_snapshot, None) if args.to_snapshot else scan_to_tree(repo)
    detect = not args.no_renames

    if args.summary or args.files:
        dr = diff_result(repo, base, target, detect_renames=detect)
        rows = (
            [("renamed", "{} -> {} ({}%)".format(r["old_path"], r["new_path"],
                                                 int(round(r["similarity"] * 100))))
             for r in dr["renamed"]]
            + [("added", p) for p in dr["added"]]
            + [("modified", p) for p in dr["modified"]]
            + [("deleted", p) for p in dr["deleted"]]
        )
        if not rows:
            info("no changes")
        for status, label in rows:
            if args.files:
                info("{}\t{}".format(status, label))
            else:
                info(" {}  {}".format(_status_glyph(status), label))
        if args.summary:
            s = dr["stats"]
            info(" {} files changed, +{} -{}".format(
                s["files_changed"], s["insertions"], s["deletions"]))
            if dr["directory_renames"]:
                for d in dr["directory_renames"]:
                    info(" dir  {} -> {} ({} files)".format(d["old_dir"] or ".", d["new_dir"] or ".", d["count"]))
    else:
        out = unified_result(repo, base, target, detect_renames=detect)
        sys.stdout.write(out if out.strip() else "no changes\n")
    return 0


# ------------------------------------------------------------------------ verify

def cmd_verify(args) -> int:
    repo = _repo()
    sess = _active(repo)
    cmds = repo.config.verification_commands()
    if not cmds:
        info(util.yellow("No verification commands configured."))
        info("Add some under `verification.commands` in {}".format(repo.paths.config))
        rec = verifymod.run_verification(repo, sess)
        ledgermod.append(repo, "verification", sess.id, sess.actor(),
                         {"overall": rec["overall"], "run_id": rec["verification_id"]})
        timelinemod.append(repo, sess.id, "verification_run",
                           {"overall": rec["overall"], "run_id": rec["verification_id"]})
        return 0
    info("Running {} verification command(s)...".format(len(cmds)))
    rec = verifymod.run_verification(repo, sess)
    for r in rec["results"]:
        glyph = util.green("PASS") if r["status"] == "passed" else util.red(r["status"].upper())
        info("  [{}] {}  ({:.2f}s)  $ {}".format(glyph, r["name"], r["duration_seconds"], r["command"]))
    info("Overall: " + (util.green(rec["overall"]) if rec["overall"] == "passed" else util.red(rec["overall"])))
    ledgermod.append(repo, "verification", sess.id, sess.actor(),
                     {"overall": rec["overall"], "run_id": rec["verification_id"]})
    timelinemod.append(repo, sess.id, "verification_run",
                       {"overall": rec["overall"], "run_id": rec["verification_id"]})
    return 0 if rec["overall"] in ("passed", "skipped") else 1


# ------------------------------------------------------------------------ packet

def cmd_packet(args) -> int:
    repo = _repo()
    sess = _active(repo)
    pkt = engine.generate_packet(repo, sess)
    ledgermod.append(repo, "packet", sess.id, sess.actor(),
                     {"changed_files": len(pkt["changed_files"]),
                      "next_action": pkt["recommended_next_action"],
                      "secrets": len(pkt["secret_findings"])})
    if args.json:
        import json
        print(json.dumps(pkt, indent=2, ensure_ascii=False))
        return 0
    info(util.bold("Change Packet ") + util.cyan(sess.id))
    info("  instruction: {}".format(pkt["instruction"]))
    info("  branch:      {}".format(pkt["branch"]))
    info("  base:        {}".format(_short(pkt["base_snapshot"]) if pkt["base_snapshot"] else "(unborn)"))
    s = pkt["stats"]
    info("  summary:     {} files, +{} -{}".format(s["files_changed"], s["insertions"], s["deletions"]))
    for f in pkt["changed_files"][:50]:
        if f["status"] == "renamed":
            info("    {} {} -> {} ({}%)".format(
                _status_glyph("renamed"), f.get("from"), f["path"],
                int(round(f.get("similarity", 1.0) * 100))))
        else:
            info("    {} {}".format(_status_glyph(f["status"]), f["path"]))
    info("  snapshots:   {}".format(len(pkt["snapshots"])))
    info("  verification: {}".format(pkt["verification"]["overall"]))
    info("  risks:       {}".format(", ".join(pkt["risks"])))
    if pkt["secret_findings"]:
        info(util.red("  SECRETS DETECTED:"))
        for fnd in pkt["secret_findings"][:20]:
            info(util.red("    {} ({}:{})".format(fnd["type"], fnd["file"], fnd["line"])))
    info("  recommended commit message: {}".format(util.bold(pkt["recommended_commit_message"])))
    info("  recommended next action:    {}".format(util.bold(pkt["recommended_next_action"])))
    return 0


# ------------------------------------------------------------------------ accept

def cmd_accept(args) -> int:
    repo = _repo()
    sess = _active(repo)
    actor = sess.actor()
    rules = repo.config.risk_rules_for(sess.data.get("risk_tags", []))

    if rules.get("require_human_accept") and actor.get("type") == "agent" and not args.force:
        err("risk rule requires a human to accept this session (actor is an agent).")
        return 1

    verification_ref = None
    force_verify = bool(rules.get("require_verification"))
    do_verify = (not args.no_verify) and (force_verify or repo.config.run_on_accept())
    if args.no_verify and force_verify and not args.force:
        err("risk rule requires verification; --no-verify not allowed without --force.")
        return 1
    if do_verify and repo.config.verification_commands():
        info("Verifying before accept...")
        rec = verifymod.run_verification(repo, sess)
        verification_ref = rec["verification_id"]
        ledgermod.append(repo, "verification", sess.id, actor,
                         {"overall": rec["overall"], "run_id": rec["verification_id"]})
        if rec["overall"] == "failed" and not args.force:
            err("verification failed. Fix issues or pass --force to accept anyway.")
            for r in rec["results"]:
                if r["status"] != "passed":
                    info(util.red("  failed: {} (exit {})".format(r["name"], r["exit_code"])))
            return 1
    elif force_verify and not args.force:
        err("risk rule requires verification but no commands are configured.")
        return 1

    if repo.config.secrets_scan():
        current = scan_to_tree(repo)
        findings = secretscan.scan_diff(unified(repo, sess.base_tree, current))
        td = tree_diff(repo, sess.base_tree, current)
        findings += secretscan.scan_paths([f["path"] for f in td["files"]])
        if findings and not args.force:
            err("possible secrets detected in the changes. Refusing to accept.")
            for f in findings[:20]:
                info(util.red("  {} ({}:{})".format(f["type"], f["file"], f["line"])))
            return 1

    pkt = engine.generate_packet(repo, sess)
    # Gate on whether history would actually change: current tree vs branch head tree.
    current_tree = scan_to_tree(repo)
    parent_tree = repo.head_tree()
    if current_tree == parent_tree:
        err("nothing to accept; the working tree matches the branch head.")
        info("Use `checkpoint-core rollback` to discard, or `reject` to close.")
        return 1
    if verification_ref is None:
        runs = sess.data.get("verifications", [])
        verification_ref = runs[-1] if runs else None

    message = args.message or pkt["recommended_commit_message"] or sess.data["instruction"]
    oid = engine.accept(repo, sess, message, verification_ref)
    ledgermod.append(repo, "accept", sess.id, actor,
                     {"snapshot": oid, "message": message, "files": len(pkt["changed_files"])})
    timelinemod.append(repo, sess.id, "accepted", {"snapshot": oid, "message": message})

    info(util.green("Accepted session ") + util.bold(sess.id))
    info("  snapshot: {}".format(_short(oid)))
    info("  branch:   {} -> {}".format(repo.head_branch(), _short(oid)))
    info("  message:  {}".format(message))
    info("  sealed:   {}".format(objects.verify_seal(repo.get_object(oid))))
    info("\nHistory advanced in Checkpoint's own store. No Git involved.")
    return 0


# ------------------------------------------------------------------------ reject

def cmd_reject(args) -> int:
    repo = _repo()
    sess = _active(repo)
    if not confirm("Reject session {} (auditable, no history written)?".format(sess.id), args.yes):
        info("Aborted.")
        return 1
    engine.reject(repo, sess, args.reason)
    ledgermod.append(repo, "reject", sess.id, sess.actor(), {"reason": args.reason})
    info(util.yellow("Rejected session ") + util.bold(sess.id))
    return 0


# ---------------------------------------------------------------------- rollback

def cmd_rollback(args) -> int:
    repo = _repo()
    sess = _active(repo)
    if args.to_snapshot:
        target_tree = repo.get_object(args.to_snapshot)["tree"]
        label = "snapshot {}".format(_short(args.to_snapshot))
    else:
        target_tree = sess.base_tree
        label = "session start"

    actions = engine.plan_rollback(repo, target_tree)
    will = args.hard or args.yes
    delete_added = args.hard and not args.keep_files

    info(util.bold("Rollback to {}".format(label)))
    info("  restore (modified/deleted since target): {}".format(len(actions["restore"])))
    for p in actions["restore"][:50]:
        info("    restore  {}".format(p))
    info("  added since target: {}".format(len(actions["added"])))
    for p in actions["added"][:50]:
        info("    {} {}".format("DELETE " if delete_added else "keep   ", p))
    if not actions["restore"] and not actions["added"]:
        info(util.green("Nothing to roll back; already at target state."))
        return 0
    if not will:
        info(util.yellow("\nPreview only. Re-run with --yes to restore, or --hard to also delete added files."))
        return 0

    pre = engine.create_snapshot(repo, sess, "pre-rollback safety snapshot")
    info(util.dim("  pre-rollback snapshot: {}".format(_short(pre["id"]))))
    result = engine.execute_rollback(repo, target_tree, delete_added)
    sess.set_status(ROLLED_BACK)
    if not args.keep_session_active:
        repo.set_active_session(None)
    ledgermod.append(repo, "rollback", sess.id, sess.actor(),
                     {"target": label, "restored": len(result["restored"]),
                      "deleted": len(result["deleted"]), "pre_rollback": pre["id"]})
    timelinemod.append(repo, sess.id, "rollback",
                       {"target": label, "restored": len(result["restored"]),
                        "deleted": len(result["deleted"]), "pre_rollback": pre["id"]})
    info(util.green("\nRolled back to {}".format(label)))
    info("  restored: {} files,  deleted: {} files".format(len(result["restored"]), len(result["deleted"])))
    info("  recover:  pre-rollback snapshot {}".format(_short(pre["id"])))
    return 0


# --------------------------------------------------------------------------- log

def cmd_log(args) -> int:
    repo = _repo()
    sids = repo.session_ids()
    if not sids:
        info("No sessions yet.")
        return 0
    active = repo.active_session_id()
    info(util.bold("{:<46} {:<13} {}".format("SESSION", "STATUS", "INSTRUCTION")))
    for sid in sids:
        try:
            s = Session.load(repo, sid)
        except FileNotFoundError:
            continue
        status = "active*" if sid == active else s.status
        if args.status and status.rstrip("*") != args.status:
            continue
        instr = (s.data.get("instruction") or "").splitlines()[0][:60]
        info("{:<46} {:<13} {}".format(sid, _color_status(status), instr))
    return 0


def _color_status(status: str) -> str:
    base = status.rstrip("*")
    color = {"active": util.cyan, "accepted": util.green,
             "rejected": util.yellow, "rolled_back": util.red}.get(base, lambda x: x)
    return color(status)


# ----------------------------------------------------------------------- history

def cmd_history(args) -> int:
    repo = _repo()
    chain = repo.history()
    if not chain:
        info("No accepted history yet on branch {}.".format(repo.head_branch() or "(detached)"))
        return 0
    info(util.bold("History of branch {} (newest first):".format(repo.head_branch() or "(detached)")))
    for oid in chain:
        snap = repo.get_object(oid)
        author = snap.get("author", {})
        info("{}  {}".format(util.yellow(_short(oid)), util.bold(snap.get("message") or "")))
        info("    {}  by {}  session {}".format(
            snap.get("timestamp", ""), author.get("name") or author.get("id"), snap.get("session")))
    return 0


# -------------------------------------------------------------------------- show

def cmd_show(args) -> int:
    repo = _repo()
    try:
        sess = Session.load(repo, args.session_id)
    except FileNotFoundError:
        err("no such session: {}".format(args.session_id))
        return 1
    d = sess.data
    info(util.bold("Session ") + util.cyan(sess.id))
    info("  instruction: {}".format(d["instruction"]))
    info("  status:      {}".format(_color_status(sess.status)))
    info("  created:     {}".format(d["created_at"]))
    info("  actor:       {} {}".format(d["actor"].get("type"), d["actor"].get("name") or ""))
    ag = d.get("agent") or {}
    if ag.get("name") or ag.get("model") or ag.get("tool"):
        info("  agent:       name={} model={} tool={}".format(ag.get("name"), ag.get("model"), ag.get("tool")))
    info("  base:        branch={} head={} tree={}".format(
        d["base"].get("branch"), _short(d["base"].get("head")), _short(d["base"].get("tree"))))
    if d.get("risk_tags"):
        info("  risk tags:   {}".format(", ".join(d["risk_tags"])))
    if d.get("result"):
        info("  result:      {}".format(d["result"]))
    info(util.bold("  snapshots ({}):".format(len(d.get("snapshots", [])))))
    for oid in d.get("snapshots", []):
        snap = repo.get_object(oid)
        info("    {}  {}".format(_short(oid), snap.get("message") or ""))
    info(util.bold("  verification runs ({}):".format(len(d.get("verifications", [])))))
    for vid in d.get("verifications", []):
        rec = util.read_json(sess.dir / "verification" / (vid + ".json"), {})
        info("    {}  {}".format(vid, rec.get("overall", "?")))
    info(util.bold("  ledger events:"))
    for e in ledgermod.for_session(repo, sess.id):
        info("    {}  {}".format(e["timestamp"], e["event_type"]))
    return 0


# ------------------------------------------------------------------------ branch

def cmd_branch(args) -> int:
    repo = _repo()
    if not args.name:
        cur = repo.head_branch()
        for b in repo.list_branches():
            head = repo.read_ref("refs/heads/{}".format(b))
            mark = "* " if b == cur else "  "
            info("{}{:<20} {}".format(mark, b, _short(head)))
        return 0
    head = repo.head_snapshot()
    if not head:
        err("cannot create a branch before the first accepted snapshot.")
        return 1
    if repo.read_ref("refs/heads/{}".format(args.name)):
        err("branch already exists: {}".format(args.name))
        return 1
    repo.update_ref("refs/heads/{}".format(args.name), head)
    ledgermod.append(repo, "branch", None, repo.identity(), {"branch": args.name, "head": head})
    info(util.green("Created branch ") + util.bold(args.name) + " at " + _short(head))
    return 0


def cmd_checkout(args) -> int:
    repo = _repo()
    if Session.active(repo) is not None:
        err("finish the active session before checking out a branch.")
        return 1
    head = repo.read_ref("refs/heads/{}".format(args.name))
    if not head:
        err("no such branch: {}".format(args.name))
        return 1
    tree = repo.get_object(head)["tree"]
    materialize(repo, tree, delete_extra=True)
    repo.set_head_to_branch(args.name)
    ledgermod.append(repo, "checkout", None, repo.identity(), {"branch": args.name, "head": head})
    info(util.green("Switched to branch ") + util.bold(args.name) + " (" + _short(head) + ")")
    return 0


# ------------------------------------------------------------------------- merge

def cmd_merge(args) -> int:
    repo = _repo()
    if Session.active(repo) is not None:
        err("finish the active session before merging.")
        return 1
    branch = repo.head_branch()
    if not branch:
        err("cannot merge with a detached HEAD.")
        return 1
    ours = repo.head_snapshot()
    theirs = repo.read_ref("refs/heads/{}".format(args.name))
    if not theirs:
        err("no such branch: {}".format(args.name))
        return 1
    if ours and (theirs == ours or repo.is_ancestor(theirs, ours)):
        info(util.green("Already up to date."))
        return 0
    if ours is None or repo.is_ancestor(ours, theirs):
        # fast-forward
        tree = repo.get_object(theirs)["tree"]
        materialize(repo, tree, delete_extra=True)
        repo.update_ref("refs/heads/{}".format(branch), theirs)
        ledgermod.append(repo, "merge", None, repo.identity(),
                         {"into": branch, "from": args.name, "type": "fast-forward", "head": theirs})
        info(util.green("Fast-forward merge ") + "{} <- {} ({})".format(branch, args.name, _short(theirs)))
        return 0

    base = repo.merge_base(ours, theirs)
    ours_tree = repo.get_object(ours)["tree"]
    theirs_tree = repo.get_object(theirs)["tree"]
    base_tree = repo.get_object(base)["tree"] if base else None
    result = mergemod.three_way(repo, ours_tree, theirs_tree, base_tree)

    if not result["clean"]:
        for path, content in result["conflict_files"].items():
            dest = repo.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        err("merge conflict in {} file(s):".format(len(result["conflicts"])))
        for p in result["conflicts"]:
            info(util.red("    CONFLICT  {}".format(p)))
        info("Resolve the markers, then start a session and accept to record the merge.")
        return 1

    materialize(repo, result["merged_tree"], delete_extra=True)
    snap = objects.make_snapshot(
        tree=result["merged_tree"], parents=[ours, theirs], session=None,
        kind=objects.KIND_ACCEPTED, message="merge {} into {}".format(args.name, branch),
        author=repo.identity(), timestamp=util.now_iso())
    snap = objects.sign(snap, repo.identity().get("id", "anon"))
    oid = repo.put_object(snap)
    repo.update_ref("refs/heads/{}".format(branch), oid)
    ledgermod.append(repo, "merge", None, repo.identity(),
                     {"into": branch, "from": args.name, "type": "three-way",
                      "head": oid, "auto_merged": len(result["auto_merged"])})
    info(util.green("Merged ") + "{} into {} ({})".format(args.name, branch, _short(oid)))
    if result.get("rename_records"):
        for r in result["rename_records"]:
            info("  renamed ({}): {} -> {}".format(r["side"], r["old_path"], r["final_path"]))
    if result["auto_merged"]:
        info("  auto-merged (line-level): {}".format(", ".join(result["auto_merged"])))
    return 0


# ------------------------------------------------------------------------ remotes

def cmd_remote(args) -> int:
    repo = _repo()
    if args.remote_cmd == "add":
        cfg = repo.config
        cfg.data.setdefault("remotes", {})[args.name] = {"type": args.type, "location": args.location}
        cfg.save()
        info(util.green("Added remote ") + "{} ({}: {})".format(args.name, args.type, args.location))
        return 0
    remotes = repo.config.remotes()
    if not remotes:
        info("No remotes configured. Add one: checkpoint-core remote add <name> --type path --location <dir>")
        return 0
    for name, spec in remotes.items():
        info("{:<16} {}: {}".format(name, spec.get("type"), spec.get("location")))
    return 0


def _resolve_remote(repo: Repo, name: str) -> Repo:
    spec = repo.config.remotes().get(name)
    if not spec:
        raise SystemExit(util.red("error: ") + "no such remote: {}".format(name))
    if spec.get("type") != "path":
        raise SystemExit(util.red("error: ") + "only 'path' remotes are supported in the MVP")
    loc = Path(spec["location"])
    remote = Repo(loc)
    if not remote.initialized:
        raise SystemExit(util.red("error: ") + "remote store is not initialized: {}".format(loc))
    return remote


def cmd_push(args) -> int:
    repo = _repo()
    remote = _resolve_remote(repo, args.remote)
    branch = args.branch or repo.head_branch()
    res = syncmod.push(repo, remote, branch)
    ledgermod.append(repo, "push", None, repo.identity(),
                     {"remote": args.remote, "branch": branch, "objects": res["objects_copied"]})
    info(util.green("Pushed ") + "{} -> {}: {} objects, head {}".format(
        branch, args.remote, res["objects_copied"], _short(res["head"])))
    return 0


def cmd_pull(args) -> int:
    repo = _repo()
    remote = _resolve_remote(repo, args.remote)
    branch = args.branch or repo.head_branch()
    res = syncmod.pull(repo, remote, branch)
    # update working tree if we are on that branch
    if repo.head_branch() == branch:
        tree = repo.get_object(res["head"])["tree"]
        materialize(repo, tree, delete_extra=True)
    ledgermod.append(repo, "pull", None, repo.identity(),
                     {"remote": args.remote, "branch": branch, "objects": res["objects_copied"]})
    info(util.green("Pulled ") + "{} <- {}: {} objects, head {}".format(
        branch, args.remote, res["objects_copied"], _short(res["head"])))
    return 0


# ------------------------------------------------------------------------ bundles

def cmd_bundle(args) -> int:
    repo = _repo()
    if args.bundle_cmd == "export":
        branch = args.branch or repo.head_branch()
        out = args.out or "{}.ckpt-bundle.tar.gz".format(branch)
        res = syncmod.export_bundle(repo, branch, Path(out))
        info(util.green("Exported bundle ") + "{} ({} objects) -> {}".format(branch, res["objects"], res["out_path"]))
        return 0
    if args.bundle_cmd == "import":
        res = syncmod.import_bundle(repo, Path(args.path), args.branch)
        info(util.green("Imported bundle ") + "branch {} ({} new objects), head {}".format(
            res["branch"], res["objects_copied"], _short(res["head"])))
        return 0
    err("unknown bundle subcommand")
    return 2


# --------------------------------------------------------------------- git bridge

def cmd_git_export(args) -> int:
    repo = _repo()
    from . import gitbridge
    if not gitbridge.git_available():
        err("git is not installed; the bridge needs git (the core does not).")
        return 1
    res = gitbridge.export_to_git(repo, Path(args.dest), args.branch)
    ledgermod.append(repo, "git_export", None, repo.identity(),
                     {"dest": res["dest"], "commits": res["commits"]})
    info(util.green("Exported to Git ") + "{}: {} commit(s)".format(res["dest"], res["commits"]))
    return 0


def cmd_git_import(args) -> int:
    repo = _repo()
    from . import gitbridge
    if not gitbridge.git_available():
        err("git is not installed; the bridge needs git (the core does not).")
        return 1
    res = gitbridge.import_from_git(repo, Path(args.source), args.branch)
    ledgermod.append(repo, "git_import", res["session"], repo.identity(),
                     {"source": str(args.source), "commits": res["commits"], "head": res["head"]})
    info(util.green("Imported from Git ") + "{}: {} commit(s) -> branch {} ({})".format(
        args.source, res["commits"], res["branch"], _short(res["head"])))
    info("Checkpoint is now the source of truth. Git is no longer required.")
    return 0


# ------------------------------------------------------------------ verify-history

def cmd_verify_history(args) -> int:
    repo = _repo()
    chain = repo.history()
    if not chain:
        info("No history to verify.")
        return 0
    broken = []
    for oid in chain:
        snap = repo.get_object(oid)
        if snap.get("kind") == objects.KIND_ACCEPTED and not objects.verify_seal(snap):
            broken.append(oid)
    if broken:
        err("{} snapshot seal(s) failed verification:".format(len(broken)))
        for oid in broken:
            info(util.red("  broken seal: {}".format(oid)))
        return 1
    info(util.green("All {} accepted snapshots have valid seals.".format(len(chain))))
    return 0


# ------------------------------------------------------------------------ doctor

def cmd_doctor(args) -> int:
    problems = 0
    try:
        repo = Repo.discover()
    except NotInitialized:
        err("not inside a Checkpoint Core repo. Run `checkpoint-core init`.")
        return 1
    checks = [
        (".checkpoint store present", repo.paths.base.exists()),
        ("HEAD present", repo.paths.head.exists()),
        ("config readable", _safe(lambda: repo.config and True)),
        ("identity present", repo.paths.identity.exists()),
        ("objects dir writable", _writable(repo.paths.objects)),
        ("ledger present", repo.paths.ledger.exists()),
        ("history seals valid", _safe(lambda: cmd_verify_history_silent(repo))),
        ("no orphaned active session", _active_ok(repo)),
        ("works without git", True),  # by construction: core never imports git
    ]
    for label, ok in checks:
        info("  [{}] {}".format(util.green("ok  ") if ok else util.red("FAIL"), label))
        if not ok:
            problems += 1
    if problems == 0:
        info(util.green("\nHealthy. Checkpoint Core is the source of truth; Git is optional."))
        return 0
    info(util.red("\n{} problem(s) found.".format(problems)))
    return 1


def cmd_verify_history_silent(repo: Repo) -> bool:
    for oid in repo.history():
        snap = repo.get_object(oid)
        if snap.get("kind") == objects.KIND_ACCEPTED and not objects.verify_seal(snap):
            return False
    return True


def _safe(fn) -> bool:
    try:
        return bool(fn())
    except Exception:
        return False


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except Exception:
        return False


def _active_ok(repo: Repo) -> bool:
    sid = repo.active_session_id()
    if not sid:
        return True
    return (repo.paths.session_dir(sid) / "session.json").exists()


# ----------------------------------------------------------- watch / autosave (Phase 2)

def cmd_watch(args) -> int:
    repo = _repo()
    sess = _active(repo)
    if not repo.config.autosave().get("enabled", True):
        err("autosave is disabled in config; enable autosave.enabled to watch.")
        return 1
    w = Watcher(repo, sess,
                debounce_ms=args.debounce_ms, poll_ms=args.poll_ms)
    info(util.green("Checkpoint is watching. ") + util.dim("You are never unsaved."))
    n = w.run(log=lambda m: info(util.dim("  " + m)))
    info("Created {} autosave(s) this run.".format(n))
    return 0


def cmd_autosave(args) -> int:
    repo = _repo()
    sub = args.autosave_cmd or "list"
    if sub == "list":
        sess = _active(repo)
        recs = autosavemod.list_autosaves(repo, sess)
        if not recs:
            info("No autosaves yet for {}.".format(sess.id))
            return 0
        info(util.bold("{:<26} {:<22} {:>7} {}".format("AUTOSAVE", "WHEN", "CHANGED", "REASON")))
        for r in recs:
            info("{:<26} {:<22} {:>7} {}".format(
                r["autosave_id"], r["timestamp"][:19], len(r["changed_paths"]), r.get("reason", "")))
        return 0
    if sub == "show":
        sess = _active(repo)
        rec = autosavemod.load_autosave(repo, sess, args.autosave_id)
        if rec is None:
            err("no such autosave: {}".format(args.autosave_id))
            return 1
        info(util.bold("Autosave ") + util.cyan(rec["autosave_id"]))
        info("  session:    {}".format(rec["session_id"]))
        info("  when:       {}".format(rec["timestamp"]))
        info("  reason:     {}".format(rec.get("reason")))
        info("  parent:     {}".format(rec.get("parent_autosave_id") or "(none)"))
        info("  tree:       {}".format(_short(rec["tree_id"])))
        info("  base:       {}".format(_short(rec.get("base_snapshot_id")) if rec.get("base_snapshot_id") else "(unborn)"))
        info("  seal valid: {}".format(autosavemod.verify_seal(rec)))
        info("  changed ({}):".format(len(rec["changed_paths"])))
        for p in rec["changed_paths"][:50]:
            info("    {}".format(p))
        diff_path = sess.dir / "autosaves" / rec["autosave_id"] / "diff.patch"
        if args.diff and diff_path.exists():
            info(util.bold("\n  diff:"))
            sys.stdout.write(diff_path.read_text(encoding="utf-8"))
        return 0
    if sub == "restore":
        sess = _active(repo)
        rec = autosavemod.load_autosave(repo, sess, args.autosave_id)
        if rec is None:
            err("no such autosave: {}".format(args.autosave_id))
            return 1
        if not confirm("Restore working tree to autosave {}?".format(args.autosave_id), args.yes):
            info("Aborted.")
            return 1
        res = autosavemod.restore_autosave(repo, sess, args.autosave_id)
        info(util.green("Restored autosave ") + util.bold(args.autosave_id))
        info("  restored: {} files,  deleted: {} files".format(len(res["restored"]), len(res["deleted"])))
        return 0
    if sub == "gc":
        sess = _active(repo)
        removed = autosavemod.gc(repo, sess)
        info(util.green("Garbage-collected {} autosave(s).".format(len(removed))))
        info("  (accepted history and snapshots are never touched)")
        return 0
    err("unknown autosave subcommand")
    return 2


# ------------------------------------------------------------------------ timeline

def cmd_timeline(args) -> int:
    repo = _repo()
    if args.session_id:
        sid = args.session_id
    else:
        sess = Session.active(repo)
        if sess is None:
            err("no active session; pass a session id: checkpoint-core timeline <session-id>")
            return 1
        sid = sess.id
    events = timelinemod.read(repo, sid)
    if not events:
        info("No timeline events for {}.".format(sid))
        return 0
    glyphs = {
        "session_started": util.cyan("start "), "autosave_created": util.dim("auto  "),
        "snapshot_created": util.yellow("snap  "), "verification_run": "verify",
        "accepted": util.green("ACCEPT"), "rollback": util.red("rollbk"),
        "recover_invoked": util.yellow("recovr"),
    }
    info(util.bold("Timeline for {}:".format(sid)))
    for e in events:
        g = glyphs.get(e["type"], e["type"][:6])
        info("  {}  {}  {}".format(e["timestamp"][:19], g, _timeline_detail(e)))
    return 0


def _timeline_detail(e) -> str:
    p = e.get("payload", {})
    t = e["type"]
    if t == "session_started":
        return p.get("instruction", "")
    if t == "autosave_created":
        return "{} ({} changed, {})".format(p.get("autosave_id", ""), p.get("changed", 0), p.get("reason", ""))
    if t == "snapshot_created":
        return "{} {}".format(_short(p.get("snapshot")), p.get("message") or "")
    if t == "verification_run":
        return "{}".format(p.get("overall"))
    if t == "accepted":
        return "{} {}".format(_short(p.get("snapshot")), p.get("message") or "")
    if t == "rollback":
        return "to {} (restored {}, deleted {})".format(p.get("target"), p.get("restored"), p.get("deleted"))
    if t == "recover_invoked":
        return p.get("note", "")
    return ""


# ------------------------------------------------------------------------- recover

def cmd_recover(args) -> int:
    repo = _repo()
    sess = Session.active(repo)
    if sess is None:
        info(util.green("No interrupted session. Nothing to recover."))
        return 0

    timelinemod.append(repo, sess.id, "recover_invoked", {"note": "recover inspected"})
    latest = autosavemod.latest(repo, sess)
    info(util.bold("Interrupted session: ") + util.cyan(sess.id))
    info("  instruction: {}".format(sess.data["instruction"]))
    info("  status:      {}".format(sess.status))
    info("  autosaves:   {}".format(len(sess.data.get("autosaves", []))))
    if latest is None:
        info(util.yellow("  No autosaves were captured for this session."))
        info("  You can continue working, or `reject` to close it.")
        return 0

    info("  latest autosave: {} ({})".format(latest["autosave_id"], latest["timestamp"][:19]))
    current_tree = scan_to_tree(repo)
    diverged = current_tree != latest["tree_id"]
    if diverged:
        td = tree_diff(repo, latest["tree_id"], current_tree)
        info(util.yellow("  working tree DIVERGES from the latest autosave "
                         "({} files differ).".format(td["stats"]["files_changed"])))
    else:
        info(util.green("  working tree matches the latest autosave."))

    target = args.to or latest["autosave_id"]
    if not args.restore:
        info("\nOptions:")
        info("  checkpoint-core recover --restore           # restore the latest autosave")
        info("  checkpoint-core recover --restore --to <id> # restore a specific autosave")
        info("  checkpoint-core autosave list               # see all autosaves")
        return 0

    if not confirm("Restore working tree to autosave {}?".format(target), args.yes):
        info("Aborted.")
        return 1
    res = autosavemod.restore_autosave(repo, sess, target)
    info(util.green("Recovered to autosave ") + util.bold(target))
    info("  restored: {} files,  deleted: {} files".format(len(res["restored"]), len(res["deleted"])))
    return 0


# ------------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="checkpoint-core",
        description="Checkpoint Core: a Git-replacement VCS for human + AI code. No Git in the core.")
    p.add_argument("--version", action="version", version="checkpoint-core {}".format(__version__))
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="initialize a Checkpoint Core repo (no Git needed)")
    sp.add_argument("--branch", help="default branch name (default: main)")
    sp.add_argument("--name", help="your name")
    sp.add_argument("--email", help="your email")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("identity", help="show or set the author identity")
    sp.add_argument("--name")
    sp.add_argument("--email")
    sp.set_defaults(func=cmd_identity)

    sp = sub.add_parser("start", help="start a session")
    sp.add_argument("instruction", nargs="?", default="")
    sp.add_argument("--prompt-file")
    sp.add_argument("--actor", choices=["human", "agent", "tool"])
    sp.add_argument("--agent")
    sp.add_argument("--model")
    sp.add_argument("--tool")
    sp.add_argument("--tag", action="append")
    sp.set_defaults(func=cmd_start)

    sub.add_parser("status", help="show the active session").set_defaults(func=cmd_status)

    sp = sub.add_parser("snapshot", help="capture a meaningful snapshot")
    sp.add_argument("--message", "-m")
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("diff", help="native diff (session start -> now, or between snapshots)")
    sp.add_argument("--from", dest="from_snapshot")
    sp.add_argument("--to", dest="to_snapshot")
    sp.add_argument("--summary", action="store_true")
    sp.add_argument("--files", action="store_true")
    sp.add_argument("--no-renames", action="store_true", help="disable rename detection")
    sp.set_defaults(func=cmd_diff)

    sub.add_parser("verify", help="run verification commands").set_defaults(func=cmd_verify)

    sp = sub.add_parser("packet", help="generate a Change Packet")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_packet)

    sp = sub.add_parser("accept", help="accept -> new accepted snapshot (native history)")
    sp.add_argument("--message", "-m")
    sp.add_argument("--no-verify", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_accept)

    sp = sub.add_parser("reject", help="reject the session (auditable, no history)")
    sp.add_argument("--reason")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_reject)

    sp = sub.add_parser("rollback", help="roll back the session safely")
    sp.add_argument("--to-start", action="store_true")
    sp.add_argument("--to-snapshot")
    sp.add_argument("--hard", action="store_true")
    sp.add_argument("--keep-files", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--keep-session-active", action="store_true")
    sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser("log", help="session history")
    sp.add_argument("--status")
    sp.set_defaults(func=cmd_log)

    sub.add_parser("history", help="accepted-snapshot history (the commit-log equivalent)").set_defaults(func=cmd_history)

    sp = sub.add_parser("show", help="full session detail")
    sp.add_argument("session_id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("branch", help="list or create branches")
    sp.add_argument("name", nargs="?")
    sp.set_defaults(func=cmd_branch)

    sp = sub.add_parser("checkout", help="switch branches (materializes the tree)")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_checkout)

    sp = sub.add_parser("merge", help="merge a branch into the current branch")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("remote", help="manage remotes")
    rsub = sp.add_subparsers(dest="remote_cmd")
    radd = rsub.add_parser("add")
    radd.add_argument("name")
    radd.add_argument("--type", default="path", choices=["path"])
    radd.add_argument("--location", required=True)
    sp.set_defaults(func=cmd_remote, remote_cmd=None)

    sp = sub.add_parser("push", help="push a branch to a remote")
    sp.add_argument("remote")
    sp.add_argument("branch", nargs="?")
    sp.set_defaults(func=cmd_push)

    sp = sub.add_parser("pull", help="pull a branch from a remote")
    sp.add_argument("remote")
    sp.add_argument("branch", nargs="?")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("bundle", help="export/import a portable bundle")
    bsub = sp.add_subparsers(dest="bundle_cmd")
    bex = bsub.add_parser("export")
    bex.add_argument("branch", nargs="?")
    bex.add_argument("--out")
    bim = bsub.add_parser("import")
    bim.add_argument("path")
    bim.add_argument("--branch")
    sp.set_defaults(func=cmd_bundle, bundle_cmd=None)

    sp = sub.add_parser("git-export", help="bridge: replay history into a Git repo")
    sp.add_argument("dest")
    sp.add_argument("--branch")
    sp.set_defaults(func=cmd_git_export)

    sp = sub.add_parser("git-import", help="bridge: import a Git repo's history")
    sp.add_argument("source")
    sp.add_argument("--branch")
    sp.set_defaults(func=cmd_git_import)

    sub.add_parser("verify-history", help="recompute and check snapshot seals").set_defaults(func=cmd_verify_history)
    sub.add_parser("doctor", help="diagnose the installation").set_defaults(func=cmd_doctor)

    # --- Phase 2: background autosave daemon, timeline, recovery ---
    sp = sub.add_parser("watch", help="continuously autosave the active session (foreground)")
    sp.add_argument("--debounce-ms", type=int, dest="debounce_ms")
    sp.add_argument("--poll-ms", type=int, dest="poll_ms")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("autosave", help="list/show/restore/gc autosaves")
    asub = sp.add_subparsers(dest="autosave_cmd")
    asub.add_parser("list")
    ashow = asub.add_parser("show")
    ashow.add_argument("autosave_id")
    ashow.add_argument("--diff", action="store_true", help="also print the diff")
    arest = asub.add_parser("restore")
    arest.add_argument("autosave_id")
    arest.add_argument("--yes", action="store_true")
    asub.add_parser("gc")
    sp.set_defaults(func=cmd_autosave, autosave_cmd=None)

    sp = sub.add_parser("timeline", help="show the session timeline")
    sp.add_argument("session_id", nargs="?")
    sp.set_defaults(func=cmd_timeline)

    sp = sub.add_parser("recover", help="detect and recover an interrupted session")
    sp.add_argument("--restore", action="store_true", help="restore the working tree")
    sp.add_argument("--to", help="restore a specific autosave id")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_recover)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except NotInitialized as exc:
        err(str(exc))
        return 2
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        return exc.code or 0
    except KeyboardInterrupt:
        err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
