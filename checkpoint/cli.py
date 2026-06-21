"""Checkpoint CLI: argparse-based dispatch for all MVP commands."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, util
from . import ledger as ledgermod
from . import packet as packetmod
from . import restore as restoremod
from . import secrets as secretscan
from . import snapshot as snapmod
from . import verify as verifymod
from .config import Config, default_config
from .export import export_session
from .gitutil import Git
from .ignore import DEFAULT_CHECKPOINTIGNORE
from .session import (
    Session, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_ROLLED_BACK,
)
from .store import CHECKPOINT_DIR, NotInitialized, Repo


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
        ans = input(prompt + " [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _require_repo() -> Repo:
    return Repo.discover()


def _require_active(repo: Repo) -> Session:
    sess = Session.active(repo)
    if sess is None:
        raise SystemExit(util.red("error: ") + "no active session. Run `checkpoint start \"<instruction>\"`.")
    return sess


def _actor_from_args(repo: Optional[Repo], args) -> dict:
    base = {"type": "human", "name": ""}
    if repo is not None:
        try:
            base = repo.config.default_actor()
        except Exception:
            pass
    if getattr(args, "actor", None):
        base["type"] = args.actor
    if getattr(args, "agent", None):
        base["type"] = "agent"
        base["name"] = args.agent
    if getattr(args, "name", None):
        base["name"] = args.name
    return base


# -------------------------------------------------------------------------- init

def cmd_init(args) -> int:
    start = Path.cwd()
    top = Git.toplevel(start)
    if top is None:
        err("not inside a Git repository.")
        info("Checkpoint builds on Git. Run `git init` first, then `checkpoint init`.")
        return 2

    repo = Repo(top)
    paths = repo.paths
    if paths.config.exists() and not args.force:
        if not confirm("Checkpoint config already exists. Overwrite?", args.yes):
            info("Leaving existing configuration untouched.")
            # Still ensure directories/ignore exist (idempotent).
            _ensure_layout(repo)
            return 0

    _ensure_layout(repo)
    cfg = Config(default_config(project=top.name), paths.config)
    cfg.save()

    # Ensure .checkpoint/ is gitignored so internals never enter Git history.
    _ensure_gitignore(top)

    # Seed .checkpointignore if absent.
    cpignore = top / ".checkpointignore"
    if not cpignore.exists():
        with open(cpignore, "w", encoding="utf-8") as fh:
            fh.write(DEFAULT_CHECKPOINTIGNORE)

    if not paths.state.exists():
        repo.write_state({"schema_version": 1, "active_session": None})

    ledgermod.append(repo, "init", None, _actor_from_args(repo, args),
                     {"version": __version__, "project": top.name})

    info(util.green("Initialized Checkpoint") + " in " + util.bold(str(top)))
    info("  metadata: {}/".format(CHECKPOINT_DIR))
    info("  git repo: {} (branch {})".format(
        "with commits" if repo.git.has_head() else "no commits yet", repo.git.branch()))
    info("  config:   {}".format(paths.config))
    info("\nNext: checkpoint start \"<what you are about to do>\"")
    return 0


def _ensure_layout(repo: Repo) -> None:
    for d in (repo.paths.base, repo.paths.sessions, repo.paths.objects,
              repo.paths.cache, repo.paths.tmp):
        d.mkdir(parents=True, exist_ok=True)
    if not repo.paths.ledger.exists():
        repo.paths.ledger.touch()
    # Belt-and-suspenders: ensure Git ignores .checkpoint contents even if the
    # repo's root .gitignore is later edited.
    selfignore = repo.paths.base / ".gitignore"
    if not selfignore.exists():
        selfignore.write_text("*\n", encoding="utf-8")


def _ensure_gitignore(repo_root: Path) -> None:
    gi = repo_root / ".gitignore"
    entry = "{}/".format(CHECKPOINT_DIR)
    lines: List[str] = []
    if gi.exists():
        with open(gi, "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh]
        if any(ln.strip().rstrip("/") == CHECKPOINT_DIR for ln in lines):
            return
    with open(gi, "a", encoding="utf-8") as fh:
        if lines and lines[-1].strip() != "":
            fh.write("\n")
        fh.write("# Checkpoint Protocol internal state (never commit)\n")
        fh.write(entry + "\n")


# ------------------------------------------------------------------------- start

def cmd_start(args) -> int:
    repo = _require_repo()
    existing = Session.active(repo)
    if existing is not None:
        err("a session is already active: {}".format(existing.id))
        info("Accept, reject, or rollback it first (see `checkpoint status`).")
        return 1

    instruction = args.instruction
    if args.prompt_file:
        instruction = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not instruction:
        err("an instruction is required: checkpoint start \"<instruction>\"")
        return 2

    base_tree = snapmod.capture_tree(repo)
    actor = _actor_from_args(repo, args)
    agent = None
    if actor["type"] == "agent" or args.model or args.tool or args.agent:
        agent = {
            "name": args.agent, "model": args.model, "tool": args.tool,
            "prompt": instruction, "response_summary": None,
            "files_touched": [], "commands_run": [],
        }
    tags = list(args.tag or [])

    sess = Session.create(repo, instruction, actor, agent, tags, base_tree)
    repo.set_active_session(sess.id)
    ledgermod.append(repo, "session_start", sess.id, actor, {
        "instruction": instruction,
        "base_head": sess.base_head,
        "base_tree": base_tree,
        "base_clean": sess.data["git"]["base_clean"],
        "risk_tags": tags,
    })

    info(util.green("Started session ") + util.bold(sess.id))
    info("  instruction: {}".format(instruction))
    info("  branch:      {}".format(sess.data["git"]["base_branch"]))
    info("  base commit: {}".format((sess.base_head or "(none)")[:12]))
    if tags:
        info("  risk tags:   {}".format(", ".join(tags)))
    if not sess.data["git"]["base_clean"]:
        info(util.yellow("  note: working tree was dirty at start; the session diff is measured from this state."))
    return 0


# ------------------------------------------------------------------------ status

def cmd_status(args) -> int:
    repo = _require_repo()
    sess = Session.active(repo)
    if sess is None:
        info("No active session.")
        info("Start one with: checkpoint start \"<instruction>\"")
        return 0

    snapmod.create_autosave(repo, sess)  # opportunistic autosave on inspection
    current_tree = snapmod.capture_tree(repo, name="status-index")
    name_status = repo.git.diff_name_status(sess.base_tree, current_tree)
    stats = repo.git.numstat(sess.base_tree, current_tree)

    if repo.git.has_conflicts():
        wt = util.red("conflicted")
    elif name_status:
        wt = util.yellow("dirty (uncommitted session changes)")
    else:
        wt = util.green("clean (no changes since session start)")

    info(util.bold("Session ") + util.cyan(sess.id))
    info("  instruction: {}".format(sess.data["instruction"]))
    info("  status:      {}".format(sess.status))
    info("  actor:       {} {}".format(sess.actor().get("type"), sess.actor().get("name") or ""))
    info("  branch:      {}".format(repo.git.branch()))
    info("  worktree:    {}".format(wt))
    info("  changes:     {} files, +{} -{}".format(
        stats["files_changed"], stats["insertions"], stats["deletions"]))
    if name_status:
        info(util.bold("  changed files:"))
        for s, p in name_status[:50]:
            info("    {} {}".format(_status_glyph(s), p))
        if len(name_status) > 50:
            info("    ... and {} more".format(len(name_status) - 50))

    last_auto = snapmod.last_autosave(sess)
    info("  last autosave:   {}".format(last_auto["autosave_id"] if last_auto else "(none)"))
    snaps = sess.data.get("snapshots", [])
    info("  last snapshot:   {}".format(snaps[-1] if snaps else "(none)"))
    ver = verifymod.last_verification(repo, sess)
    info("  verification:    {}".format(ver.get("overall", "(not run)") if ver else "(not run)"))
    return 0


def _status_glyph(s: str) -> str:
    return {"A": util.green("A"), "M": util.yellow("M"),
            "D": util.red("D"), "R": util.cyan("R")}.get(s, s)


# ---------------------------------------------------------------------- snapshot

def cmd_snapshot(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)
    snap = snapmod.create_snapshot(repo, sess, args.message)
    ledgermod.append(repo, "snapshot", sess.id, sess.actor(), {
        "snapshot_id": snap["snapshot_id"], "tree": snap["tree"],
        "message": args.message, "stats": snap["stats"],
    })
    st = snap["stats"]
    info(util.green("Snapshot ") + util.bold(snap["snapshot_id"]))
    if args.message:
        info("  message: {}".format(args.message))
    info("  changes: {} files, +{} -{}".format(
        st["files_changed"], st["insertions"], st["deletions"]))
    return 0


# -------------------------------------------------------------------------- diff

def cmd_diff(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)

    def tree_for(ref: Optional[str], default: str) -> str:
        if ref is None:
            return default
        snap = snapmod.load_snapshot(repo, sess, ref)
        return snap["tree"]

    base = tree_for(args.from_snapshot, sess.base_tree)
    if args.to_snapshot:
        target = tree_for(args.to_snapshot, sess.base_tree)
    else:
        target = snapmod.capture_tree(repo, name="diff-index")

    if args.summary:
        out = repo.git.diff_stat(base, target)
        info(out if out else "no changes")
    elif args.files:
        ns = repo.git.diff_name_status(base, target)
        if not ns:
            info("no changes")
        for s, p in ns:
            info("{}\t{}".format(s, p))
    else:
        out = repo.git.diff(base, target)
        if out.strip():
            sys.stdout.write(out)
        else:
            info("no changes")
    return 0


# ------------------------------------------------------------------------ verify

def cmd_verify(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)
    cmds = repo.config.verification_commands()
    if not cmds:
        info(util.yellow("No verification commands configured."))
        info("Add some under `verification.commands` in {}".format(repo.paths.config))
        rec = verifymod.run_verification(repo, sess)  # records a 'skipped' run
        ledgermod.append(repo, "verification", sess.id, sess.actor(),
                         {"overall": rec["overall"], "run_id": rec["verification_run_id"]})
        return 0

    info("Running {} verification command(s)...".format(len(cmds)))
    rec = verifymod.run_verification(repo, sess)
    for r in rec["results"]:
        glyph = util.green("PASS") if r["status"] == "passed" else util.red(r["status"].upper())
        info("  [{}] {}  ({:.2f}s)  $ {}".format(glyph, r["name"], r["duration_seconds"], r["command"]))
        if r["status"] != "passed" and r["stderr_summary"]:
            for line in r["stderr_summary"].splitlines()[-8:]:
                info(util.dim("        " + line))
    overall = rec["overall"]
    info("Overall: " + (util.green(overall) if overall == "passed" else util.red(overall)))
    ledgermod.append(repo, "verification", sess.id, sess.actor(),
                     {"overall": overall, "run_id": rec["verification_run_id"]})
    return 0 if overall in ("passed", "skipped") else 1


# ------------------------------------------------------------------------ packet

def cmd_packet(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)
    pkt = packetmod.generate_packet(repo, sess)
    ledgermod.append(repo, "packet", sess.id, sess.actor(), {
        "changed_files": len(pkt["changed_files"]),
        "next_action": pkt["recommended_next_action"],
        "secrets": len(pkt["secret_findings"]),
    })

    if args.json:
        print(_dump_json(pkt))
        return 0

    info(util.bold("Change Packet ") + util.cyan(sess.id))
    info("  instruction: {}".format(pkt["instruction"]))
    info("  branch:      {}".format(pkt["branch"]))
    info("  base commit: {}".format((pkt["base_commit"] or "(none)")[:12]))
    info("  summary:     {}".format(pkt["summary"]))
    info("  files:       {}".format(len(pkt["changed_files"])))
    for f in pkt["changed_files"][:50]:
        info("    {} {}".format(_status_glyph(f["status"]), f["path"]))
    info("  snapshots:   {}".format(len(pkt["snapshots"])))
    info("  verification:{}".format(" " + pkt["verification"]["overall"]))
    info("  risks:       {}".format(", ".join(pkt["risks"])))
    if pkt["secret_findings"]:
        info(util.red("  SECRETS DETECTED:"))
        for fnd in pkt["secret_findings"][:20]:
            info(util.red("    {} ({}:{})".format(fnd["type"], fnd["file"], fnd["line"])))
    info("  recommended commit message: {}".format(util.bold(pkt["recommended_commit_message"])))
    info("  recommended next action:    {}".format(util.bold(pkt["recommended_next_action"])))
    info("\n  saved: {}".format(sess.dir / "packet.json"))
    return 0


def _dump_json(obj) -> str:
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------------ accept

def cmd_accept(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)
    actor = sess.actor()
    rules = repo.config.risk_rules_for(sess.data.get("risk_tags", []))

    # Human-accept gate for safety-critical agent work.
    if rules.get("require_human_accept") and actor.get("type") == "agent" and not args.force:
        err("risk rule requires a human to accept this session (actor is an agent).")
        info("Re-run as a human or pass --force if you are the human accepting.")
        return 1

    # Clean-worktree gate (no merge conflicts).
    if rules.get("require_clean_worktree") and repo.git.has_conflicts() and not args.force:
        err("risk rule requires a conflict-free working tree; conflicts present.")
        return 1

    # Verification.
    force_verify = bool(rules.get("require_verification"))
    do_verify = (not args.no_verify) and (force_verify or repo.config.run_on_accept())
    if args.no_verify and force_verify and not args.force:
        err("risk rule requires verification; --no-verify not allowed without --force.")
        return 1
    if do_verify:
        cmds = repo.config.verification_commands()
        if cmds:
            info("Verifying before accept...")
            rec = verifymod.run_verification(repo, sess)
            ledgermod.append(repo, "verification", sess.id, actor,
                             {"overall": rec["overall"], "run_id": rec["verification_run_id"]})
            if rec["overall"] == "failed" and not args.force:
                err("verification failed. Fix issues or pass --force to accept anyway.")
                for r in rec["results"]:
                    if r["status"] != "passed":
                        info(util.red("  failed: {} (exit {})".format(r["name"], r["exit_code"])))
                return 1
        elif force_verify and not args.force:
            err("risk rule requires verification but no commands are configured.")
            return 1

    # Secret scan.
    if repo.config.secrets_scan():
        current_tree = snapmod.capture_tree(repo, name="accept-index")
        diff_text = repo.git.diff(sess.base_tree, current_tree)
        findings = secretscan.scan_diff(diff_text)
        findings += secretscan.scan_paths(
            [p for _s, p in repo.git.diff_name_status(sess.base_tree, current_tree)])
        if findings and not args.force:
            err("possible secrets detected in the changes. Refusing to commit.")
            for f in findings[:20]:
                info(util.red("  {} ({}:{})".format(f["type"], f["file"], f["line"])))
            info("Remove the secrets, add them to .gitignore/.checkpointignore, or pass --force.")
            return 1

    # Generate/refresh packet for the recommended message + audit record.
    pkt = packetmod.generate_packet(repo, sess)

    # Stage ONLY the session's delta (base_tree -> current). This promotes the
    # session's work precisely and leaves any pre-existing, unrelated dirty files
    # untouched. .checkpoint/ is gitignored and never staged.
    current_tree = pkt["current_tree"]
    session_paths = repo.git.diff_name_only(sess.base_tree, current_tree)
    if not session_paths:
        err("nothing to commit; no changes since session start.")
        info("If you intended to discard work, use `checkpoint rollback`.")
        return 1
    repo.git.stage_paths(session_paths)
    if not repo.git.staged_changes():
        err("nothing to commit; no changes since session start.")
        info("If you intended to discard work, use `checkpoint rollback`.")
        return 1

    message = args.message or pkt["recommended_commit_message"] or sess.data["instruction"]
    new_head = repo.git.commit(message)

    sess.data["git"]["accept_head"] = new_head
    sess.set_status(STATUS_ACCEPTED)
    repo.set_active_session(None)
    ledgermod.append(repo, "accept", sess.id, actor, {
        "commit": new_head, "message": message,
        "files": len(pkt["changed_files"]),
    })

    info(util.green("Accepted session ") + util.bold(sess.id))
    info("  commit:  {}".format(new_head[:12]))
    info("  message: {}".format(message))
    info("  files:   {}".format(len(pkt["changed_files"])))
    info("\nClean Git history updated. Session closed.")
    return 0


# ---------------------------------------------------------------------- rollback

def cmd_rollback(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)

    # Resolve the target tree.
    if args.to_snapshot:
        snap = snapmod.load_snapshot(repo, sess, args.to_snapshot)
        target_tree = snap["tree"]
        target_label = "snapshot {}".format(args.to_snapshot)
    else:
        target_tree = sess.base_tree
        target_label = "session start"

    current_tree = snapmod.capture_tree(repo, name="rollback-current")
    actions = restoremod.plan(repo, target_tree, current_tree)

    will_execute = args.hard or args.yes
    delete_added = args.hard and not args.keep_files

    # Always preview.
    info(util.bold("Rollback to {}".format(target_label)))
    info("  files to restore (modified/deleted since target): {}".format(len(actions["restore"])))
    for p in actions["restore"][:50]:
        info("    restore  {}".format(p))
    info("  files added since target: {}".format(len(actions["added"])))
    for p in actions["added"][:50]:
        verb = "DELETE " if delete_added else "keep   "
        info("    {} {}".format(verb, p))

    if not actions["restore"] and not actions["added"]:
        info(util.green("Nothing to roll back; already at target state."))
        return 0

    if not will_execute:
        info(util.yellow("\nThis was a preview. Re-run with --yes to restore, "
                         "or --hard to also delete added files."))
        return 0

    # Safety: pre-rollback snapshot so the rollback itself is reversible.
    pre = snapmod.create_snapshot(repo, sess, "pre-rollback safety snapshot")
    info(util.dim("  pre-rollback snapshot: {}".format(pre["snapshot_id"])))

    result = restoremod.execute(repo, target_tree, current_tree, delete_added)
    sess.set_status(STATUS_ROLLED_BACK)
    if not args.keep_session_active:
        repo.set_active_session(None)
    ledgermod.append(repo, "rollback", sess.id, sess.actor(), {
        "target": target_label, "target_tree": target_tree,
        "restored": len(result["restored"]), "deleted": len(result["deleted"]),
        "pre_rollback_snapshot": pre["snapshot_id"],
    })

    info(util.green("\nRolled back to {}".format(target_label)))
    info("  restored: {} files".format(len(result["restored"])))
    info("  deleted:  {} files".format(len(result["deleted"])))
    info("  recover:  checkpoint show {}  (pre-rollback snapshot {})".format(
        sess.id, pre["snapshot_id"]))
    return 0


# ------------------------------------------------------------------------ reject

def cmd_reject(args) -> int:
    repo = _require_repo()
    sess = _require_active(repo)
    if not confirm("Reject session {} (keeps audit record, no Git write)?".format(sess.id), args.yes):
        info("Aborted.")
        return 1
    sess.set_status(STATUS_REJECTED)
    repo.set_active_session(None)
    ledgermod.append(repo, "reject", sess.id, sess.actor(), {"reason": args.reason})
    info(util.yellow("Rejected session ") + util.bold(sess.id))
    info("  The work remains auditable under {} but was not committed.".format(sess.dir))
    return 0


# --------------------------------------------------------------------------- log

def cmd_log(args) -> int:
    repo = _require_repo()
    sids = repo.session_ids()
    if not sids:
        info("No sessions yet.")
        return 0
    active = repo.active_session_id()
    info(util.bold("{:<44} {:<13} {}".format("SESSION", "STATUS", "INSTRUCTION")))
    for sid in sids:
        try:
            s = Session.load(repo, sid)
        except FileNotFoundError:
            continue
        status = s.status
        if sid == active:
            status = "active*"
        if args.status and status.rstrip("*") != args.status:
            continue
        instr = (s.data.get("instruction") or "").splitlines()[0]
        if len(instr) > 60:
            instr = instr[:57] + "..."
        info("{:<44} {:<13} {}".format(sid, _color_status(status), instr))
    return 0


def _color_status(status: str) -> str:
    base = status.rstrip("*")
    color = {
        "active": util.cyan, "accepted": util.green,
        "rejected": util.yellow, "rolled_back": util.red,
    }.get(base, lambda x: x)
    return color(status)


# -------------------------------------------------------------------------- show

def cmd_show(args) -> int:
    repo = _require_repo()
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
    info("  actor:       {} {}".format(d["actor"]["type"], d["actor"].get("name") or ""))
    ag = d.get("agent") or {}
    if ag.get("name") or ag.get("model") or ag.get("tool"):
        info("  agent:       name={} model={} tool={}".format(ag.get("name"), ag.get("model"), ag.get("tool")))
    g = d["git"]
    info("  branch:      {}".format(g["base_branch"]))
    info("  base commit: {}".format((g["base_head"] or "(none)")[:12]))
    info("  accept head: {}".format((g["accept_head"] or "(none)")[:12] if g["accept_head"] else "(none)"))
    if d.get("risk_tags"):
        info("  risk tags:   {}".format(", ".join(d["risk_tags"])))

    info(util.bold("  snapshots ({}):".format(len(d.get("snapshots", [])))))
    for sid in d.get("snapshots", []):
        snap = util.read_json(sess.dir / "snapshots" / sid / "snapshot.json", {})
        st = snap.get("stats", {})
        info("    {}  {}  (+{} -{})  {}".format(
            sid, snap.get("created_at", ""),
            st.get("insertions", 0), st.get("deletions", 0),
            snap.get("message") or ""))

    info(util.bold("  verification runs ({}):".format(len(d.get("verifications", [])))))
    for vid in d.get("verifications", []):
        rec = util.read_json(sess.dir / "verification" / (vid + ".json"), {})
        info("    {}  {}".format(vid, rec.get("overall", "?")))

    info(util.bold("  ledger events:"))
    for e in ledgermod.for_session(repo, sess.id):
        info("    {}  {}  {}".format(e["timestamp"], e["event_type"], e["event_id"]))
    return 0


# ------------------------------------------------------------------------ export

def cmd_export(args) -> int:
    repo = _require_repo()
    out = args.out or "{}.checkpoint.tar.gz".format(args.session_id)
    try:
        result = export_session(repo, args.session_id, Path(out))
    except FileNotFoundError:
        err("no such session: {}".format(args.session_id))
        return 1
    info(util.green("Exported ") + args.session_id + " -> " + util.bold(result["out_path"]))
    if result["secret_findings"]:
        info(util.yellow("  {} secret pattern(s) were redacted in the bundle.".format(
            len(result["secret_findings"]))))
    else:
        info("  no secrets detected.")
    return 0


# ------------------------------------------------------------------------ doctor

def cmd_doctor(args) -> int:
    problems = 0
    checks: List[tuple] = []

    git_ok = Git.is_repo(Path.cwd()) or Git.toplevel(Path.cwd()) is not None
    checks.append(("git available", _which("git")))
    checks.append(("inside a git repository", git_ok))

    top = Git.toplevel(Path.cwd())
    if top is None:
        for label, ok in checks:
            _check_line(label, ok)
        err("not inside a git repository; cannot continue diagnostics.")
        return 1

    repo = Repo(top)
    checks.append((".checkpoint present", repo.paths.base.exists()))
    checks.append(("config readable", _safe(lambda: repo.config and True)))
    checks.append((".checkpoint gitignored", _checkpoint_ignored(repo)))
    checks.append(("ledger present", repo.paths.ledger.exists()))
    checks.append(("write permission in .checkpoint", _writable(repo.paths.base)))
    checks.append(("no orphaned active session", _active_session_ok(repo)))
    checks.append(("tmp index writable", _writable(repo.paths.tmp) if repo.paths.tmp.exists() else True))

    for label, ok in checks:
        _check_line(label, ok)
        if not ok:
            problems += 1

    if problems == 0:
        info(util.green("\nAll checks passed. Checkpoint is healthy."))
        return 0
    info(util.red("\n{} problem(s) found.".format(problems)))
    if not repo.paths.base.exists():
        info("Run `checkpoint init` to initialize.")
    return 1


def _check_line(label: str, ok: bool) -> None:
    glyph = util.green("ok  ") if ok else util.red("FAIL")
    info("  [{}] {}".format(glyph, label))


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def _safe(fn) -> bool:
    try:
        return bool(fn())
    except Exception:
        return False


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except Exception:
        return False


def _checkpoint_ignored(repo: Repo) -> bool:
    proc = repo.git.run(["check-ignore", "-q", ".checkpoint"], check=False)
    return proc.returncode == 0


def _active_session_ok(repo: Repo) -> bool:
    sid = repo.active_session_id()
    if not sid:
        return True
    return (repo.paths.session_dir(sid) / "session.json").exists()


# ------------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="checkpoint",
        description="Checkpoint Protocol: AI-native change control on top of Git.",
    )
    p.add_argument("--version", action="version", version="checkpoint {}".format(__version__))
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init", help="initialize Checkpoint in the current Git repo")
    sp.add_argument("--force", action="store_true", help="overwrite existing config")
    sp.add_argument("--yes", action="store_true", help="assume yes to prompts")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("start", help="start a new session")
    sp.add_argument("instruction", nargs="?", default="", help="human-readable intent")
    sp.add_argument("--prompt-file", help="read the instruction/prompt from a file")
    sp.add_argument("--actor", choices=["human", "agent"], help="actor type")
    sp.add_argument("--agent", help="agent name (implies actor=agent)")
    sp.add_argument("--model", help="model name")
    sp.add_argument("--tool", help="tool name")
    sp.add_argument("--name", help="actor name")
    sp.add_argument("--tag", action="append", help="risk tag (repeatable)")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("status", help="show the active session state")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("snapshot", help="create a meaningful snapshot")
    sp.add_argument("--message", "-m", help="snapshot message")
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("diff", help="diff session start to current (or between snapshots)")
    sp.add_argument("--from", dest="from_snapshot", help="from snapshot id")
    sp.add_argument("--to", dest="to_snapshot", help="to snapshot id")
    sp.add_argument("--summary", action="store_true", help="show diffstat only")
    sp.add_argument("--files", action="store_true", help="show changed file names only")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("verify", help="run configured verification commands")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("packet", help="generate a Change Packet")
    sp.add_argument("--json", action="store_true", help="print packet JSON")
    sp.set_defaults(func=cmd_packet)

    sp = sub.add_parser("accept", help="accept the session into a clean Git commit")
    sp.add_argument("--message", "-m", help="commit message")
    sp.add_argument("--no-verify", action="store_true", help="skip verification")
    sp.add_argument("--force", action="store_true", help="override gates (verify/secrets/rules)")
    sp.set_defaults(func=cmd_accept)

    sp = sub.add_parser("rollback", help="roll back the session safely")
    sp.add_argument("--to-start", action="store_true", help="restore to session start (default)")
    sp.add_argument("--to-snapshot", help="restore to a snapshot id")
    sp.add_argument("--hard", action="store_true", help="execute and delete files added since target")
    sp.add_argument("--keep-files", action="store_true", help="never delete added files")
    sp.add_argument("--yes", action="store_true", help="execute the restore (non-hard)")
    sp.add_argument("--keep-session-active", action="store_true",
                    help="do not close the session after rollback")
    sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser("reject", help="reject the session (auditable, no Git write)")
    sp.add_argument("--reason", help="why it was rejected")
    sp.add_argument("--yes", action="store_true", help="assume yes")
    sp.set_defaults(func=cmd_reject)

    sp = sub.add_parser("log", help="show session history")
    sp.add_argument("--status", help="filter by status")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("show", help="show full details of a session")
    sp.add_argument("session_id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("export", help="export a portable session bundle")
    sp.add_argument("session_id")
    sp.add_argument("--out", help="output path (.tar.gz)")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("doctor", help="diagnose the Checkpoint installation")
    sp.set_defaults(func=cmd_doctor)

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
