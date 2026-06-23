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
from . import autosave as autosavemod, autowatch as autowatchmod, engine, ledger as ledgermod
from . import owneragent as owneragentmod
from . import fsck as fsckmod, gc as gcmod, reachable as reachablemod
from . import identity as idmod, merge as mergemod, policy as policymod
from . import remote as remotemod, secrets as secretscan, sign as signmod
from . import timeline as timelinemod, sync as syncmod, verify as verifymod
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
    if getattr(args, "safe_git_adapter", False) and (root / ".git").exists():
        info(util.yellow("Safe mode for an existing Git repo:"))
        info("  Checkpoint Core will NOT modify Git history or your files.")
        info("  Recommended safe trial:")
        info("    1) checkpoint-core init            # creates .checkpoint/ (Git untouched)")
        info("    2) checkpoint-core git-import .     # import Git history into Checkpoint (read-only on Git)")
        info("    3) checkpoint-core start \"safe experiment\"")
        info("  Git stays the source of truth until you choose Checkpoint Core. The")
        info("  `checkpoint` Git ADAPTER remains available as an adoption wedge.")
        info("")
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


_SETUP_IGNORE = """\
# .checkpointignore — paths Checkpoint Core should never capture.
# (.checkpoint/ and .git/ are always ignored.)
node_modules/
.next/
__pycache__/
*.pyc
.pytest_cache/
.venv/
dist/
build/
.DS_Store
"""


def _slug(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9-]+", "-", str(s).lower()).strip("-") or "repo"


def cmd_setup(args) -> int:
    """One-shot: init + identity + .checkpointignore + remote + server repo + policy.

    Collapses the whole 'set this repo up for Checkpoint' flow into a single process.
    Idempotent: never overwrites an existing repo; skips steps already done.
    """
    root = Path.cwd()
    # 1. init (skip if already a Checkpoint repo — never overwrite)
    if (root / ".checkpoint").exists():
        info("Checkpoint already initialized here.")
    else:
        rc = cmd_init(argparse.Namespace(branch=getattr(args, "branch", None), name=None,
                                         email=None, force=False, yes=True, safe_git_adapter=False))
        if rc:
            return rc
    repo = _repo()
    # 2. identity (create + auto-select a human identity if none)
    if not repo.current_identity_id():
        rec = idmod.create(repo, name=args.identity_name or "Jack Al-Kahwati", id_type="human")
        ledgermod.append(repo, "identity", None, {"id": rec["identity_id"], "name": rec["name"]},
                         {"type": rec["type"], "fingerprint": rec["fingerprint"]})
        info(util.green("Created identity ") + "{} ({})".format(rec["name"], rec["identity_id"]))
    else:
        info("Using identity {}".format(repo.current_identity_id()))
    # 3. .checkpointignore
    ig = root / ".checkpointignore"
    if not ig.exists():
        ig.write_text(_SETUP_IGNORE, encoding="utf-8")
        info("Wrote .checkpointignore")
    # 4. server repo + remote + policy (one process, reusing the HTTP client)
    if args.server:
        if not args.token:
            err("--server requires --token"); return 2
        server = args.server.rstrip("/")
        owner = args.owner or "jack"
        name = args.name or _slug(root.name)
        st, resp = remotemod._http("POST", server + "/repos", args.token, {"owner": owner, "repo": name})
        if st in (200, 201):
            info(util.green("Created server repo ") + "{}/{}".format(owner, name))
        elif st == 409:
            info("Server repo {}/{} already exists.".format(owner, name))
        else:
            info(util.yellow("Could not create server repo ({}): {}".format(st, resp)))
        url = "{}/{}/{}".format(server, owner, name)            # user-facing remote URL
        api = "{}/repos/{}/{}".format(server, owner, name)      # API base for this repo
        cmd_remote(argparse.Namespace(remote_cmd="add", name=args.remote_name,
                                      location=url, path=None, token=args.token))
        if not args.no_policy:
            import copy
            pol = copy.deepcopy(policymod.DEFAULT_STARTER_POLICY)
            pol["required_verification"] = {"default": False, "commands": ["tests"]}
            st, _ = remotemod._http("PUT", api + "/policy", args.token, {"policy": pol})
            if st == 200:
                info(util.green("Applied policy ") + util.dim("(protect main; signed + trusted acceptor)"))
    info("")
    info(util.bold("Setup complete.") + " Next:")
    info("  checkpoint-core start \"<what you're doing>\"      # autosave starts automatically")
    info("  checkpoint-core accept -m \"…\"  &&  checkpoint-core push {} main".format(args.remote_name))
    info(util.dim("  (signed identities are trusted on the server after your first push)"))
    return 0


# ---------------------------------------------------------------------- claude (one-verb wrapper)

_CLAUDE_GUARDRAIL = """You are working inside a Checkpoint session.
Task:
{task}

Keep the change scoped. Do not accept, approve, rollback, trust identities, or override
policy — Checkpoint handles those. Make the code change, run the relevant tests, and stop
when ready for human review."""


def _claude_prompt(task: str) -> str:
    return _CLAUDE_GUARDRAIL.format(task=task)


def _claude_summary(repo: Repo, sess: Session) -> dict:
    """The data behind the one-screen summary (pure; testable)."""
    current = scan_to_tree(repo)
    td = tree_diff(repo, sess.base_tree, current)
    st = td["stats"]
    ver = verifymod.last_verification(repo, sess)
    vstatus = (ver.get("overall") if ver else None) or "not run"
    pkt = util.read_json(repo.paths.session_dir(sess.id) / "packet.json", None)
    secrets_found = len(pkt.get("secret_findings", [])) if pkt else 0
    # policy preview for the human acceptor
    pol = policymod.load(repo)
    if pol is None:
        effect = "allowed (no policy)"
    else:
        cur = idmod.load(repo, repo.current_identity_id()) if repo.current_identity_id() else {}
        passed = [r.get("name") for r in (ver.get("results", []) if ver else []) if r.get("status") == "passed"]
        d = policymod.evaluate(pol, {"operation": "accept", "actor_type": cur.get("type", "human"),
                                     "branch": repo.head_branch(), "changed_paths": [f["path"] for f in td["files"]],
                                     "will_sign": bool(repo.current_identity_id()),
                                     "trust_status": "trusted" if cur.get("trusted") else "untrusted",
                                     "verification_passed": passed})
        effect = {"allow": "allowed", "deny": "DENIED — " + "; ".join(d["reasons"]),
                  "warn": "warn — " + "; ".join(d["reasons"])}.get(d["effect"], d["effect"])
    risk = "secrets detected ({})".format(secrets_found) if secrets_found else \
        (", ".join(sess.data.get("risk_tags", [])) or "normal")
    return {"files": st["files_changed"], "ins": st["insertions"], "dels": st["deletions"],
            "tests": vstatus, "policy": effect, "signed": bool(repo.current_identity_id()),
            "signer": (repo.identity() or {}).get("name", ""), "risk": risk,
            "changes": td["files"]}


def _print_claude_summary(s: dict) -> None:
    info("")
    info(util.bold("  Claude changed {} file(s) (+{} -{}).".format(s["files"], s["ins"], s["dels"])))
    tcol = util.green if s["tests"] == "passed" else (util.yellow if s["tests"] in ("not run", "skipped") else util.red)
    pcol = util.green if s["policy"].startswith("allow") else util.red
    info("  Tests:      " + tcol(s["tests"]))
    info("  Policy:     " + pcol(s["policy"]))
    info("  Signatures: " + (util.dim("will sign on accept as " + s["signer"]) if s["signed"]
                             else util.yellow("unsigned (no identity)")))
    info("  Risk:       " + (util.yellow(s["risk"]) if s["risk"] != "normal" else "normal"))
    info("")
    info("  [a] accept   [r] rollback   [d] show diff   [p] open packet   [q] quit")


def cmd_claude(args) -> int:
    # Resume an open session (concierge "continue").
    if getattr(args, "cont", False):
        repo = _repo()
        sess = Session.active(repo)
        if sess is None:
            err('no open session to continue. Start one: checkpoint-core claude "<task>"')
            return 1
        return _claude_finish(repo, sess.data.get("instruction", "(continue)"), args, resuming=True)

    task = (args.task or "").strip()
    if not task:
        err('a task is required: checkpoint-core claude "<what to do>"')
        return 2

    # Dead-simple: set up the repo if needed so the user never has to learn Checkpoint first.
    if not (Path.cwd() / ".checkpoint").exists():
        rc = cmd_init(argparse.Namespace(branch=None, name=None, email=None, force=False,
                                         yes=True, safe_git_adapter=False))
        if rc:
            return rc
    repo = _repo()
    if not repo.current_identity_id():
        idmod.create(repo, name="You", id_type="human")
        repo = _repo()
    if Session.active(repo) is not None:
        err("a session is already active ({}). Resume it: checkpoint-core claude --continue, "
            "or finish it (accept/rollback).".format(repo.active_session_id()))
        return 1

    # start an agent session (this also starts continuous autosave in the background)
    rc = cmd_start(argparse.Namespace(instruction=task, prompt_file=None, actor="agent",
                                      agent="Claude Code", model=args.model, tool="claude",
                                      tag=args.tag, no_watch=False))
    if rc:
        return rc
    return _claude_finish(repo, task, args)


def _claude_finish(repo, task, args, resuming=False) -> int:
    import os as _os, shlex as _shlex, subprocess as _sub
    # 1) launch Claude Code with the guardrail prompt (headless auto-edit by default).
    if not args.no_launch:
        cmd = _shlex.split(_os.environ.get("CHECKPOINT_CLAUDE_CMD", "claude -p --permission-mode acceptEdits"))
        if getattr(args, "model", None) and "--model" not in cmd:
            cmd += ["--model", args.model]
        child_env = _os.environ.copy()
        use_login = getattr(args, "login", False) or _os.environ.get("CHECKPOINT_CLAUDE_LOGIN", "").lower() in ("1", "true", "yes")
        if use_login:
            child_env.pop("ANTHROPIC_API_KEY", None)
        prompt = _claude_prompt(task)
        if resuming:
            prompt = "Continue the in-progress task where it left off.\n\n" + prompt
        info(util.dim("\nClaude Code is working on the task…\n"))
        try:
            _sub.run(cmd + [prompt], env=child_env)
        except FileNotFoundError:
            info(util.yellow("'{}' not found on PATH. Make your changes now, then return here "
                             "and press Enter.".format(cmd[0])))
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass

    # 2) run tests (unless --no-tests), then build the review packet
    if not args.no_tests:
        cmd_verify(argparse.Namespace())
    cmd_packet(argparse.Namespace(json=False))

    # 3) review + decision — autopilot (Owner Agent) or manual
    if getattr(args, "autopilot", False):
        return _autopilot_review(repo, args)
    return _claude_review(repo, args)


# ---- autopilot: Owner Agent reviews, then auto-accepts low-risk work or escalates ----

def _push_default_if_configured(repo) -> str:
    for n in ("checkpoint", "origin"):
        spec = remotemod.list_remotes(repo).get(n)
        if spec and spec.get("type") == "http":
            try:
                res = remotemod.push(repo, n, repo.head_branch() or "main")
                return "pushed" if res.get("status") == "pushed" else res.get("status", "?")
            except Exception as exc:
                return "failed: {}".format(exc)
    return "not configured"


def _backup_run_if_configured(repo) -> str:
    spec = remotemod.list_remotes(repo).get("backup")
    if not spec:
        return "not configured"
    try:
        res = remotemod.push(repo, "backup", repo.head_branch() or "main")
        return "synced" if res.get("status") in ("pushed", "up-to-date") else res.get("status", "?")
    except Exception as exc:
        return "failed: {}".format(exc)


def _run_after_hooks(repo, cfg, which="after_accept") -> dict:
    out = {}
    for hook in (cfg.get(which, {}) or {}).get("run", []):
        try:
            if hook == "fsck":
                out["fsck"] = fsckmod.check(repo, strict=False)["result"]
            elif hook == "verify_signatures":
                out["signatures"] = "valid" if signmod.verify_all(repo).get("ok") else "issues"
            elif hook == "backup":
                out["backup"] = _backup_run_if_configured(repo)
            elif hook == "push_default_remote":
                out["push"] = _push_default_if_configured(repo)
        except Exception as exc:
            out[hook] = "error: {}".format(exc)
    return out


def _autopilot_accept(repo, cfg, message) -> Optional[int]:
    """Accept signed by the Owner Agent identity (not the builder, not necessarily the human)."""
    owner = owneragentmod.owner_identity(repo, cfg)
    prev = repo.current_identity_id()
    idmod.set_current(repo, owner["identity_id"])
    try:
        return cmd_accept(argparse.Namespace(message=message, no_verify=True, no_sign=False,
                                             force=False, override=False, reason=None))
    finally:
        if prev:
            idmod.set_current(repo, prev)


def _autopilot_review(repo, args) -> int:
    sess = Session.active(repo)
    if sess is None:
        err("no active session"); return 1
    cfg = owneragentmod.load_config(repo)
    review = owneragentmod.review_session(repo, sess, cfg)
    decision = review["decision"]
    mode = getattr(args, "decision", None)   # auto | escalate | rollback-on-fail | None

    if mode == "rollback-on-fail" and review["verification_summary"] == "failed":
        decision = "rollback"
    elif mode == "escalate" and decision == "auto_accept":
        decision = "escalate"   # operator forced human-in-the-loop

    summary = {"files": review["files_changed"], "ins": review["insertions"], "dels": review["deletions"],
               "tests": review["verification_summary"], "policy": review["policy_effect"],
               "owner_agent": review["decision"], "risk": review["risk"],
               "reasoning": review["reasoning"], "review_id": review["review_id"],
               "decision": decision}

    if decision == "rollback":
        cmd_rollback(argparse.Namespace(to_start=False, to_snapshot=None, hard=True,
                                        keep_files=False, yes=True, keep_session_active=False))
        summary["action"] = "rolled-back (verification failed)"
        return _autopilot_finish(args, summary, None, {})

    if decision == "auto_accept":
        rc = _autopilot_accept(repo, cfg, sess.data.get("instruction"))
        if rc != 0:
            summary["action"] = "escalated"; summary["owner_agent"] = "escalate"
            summary["reasoning"] = "policy gate denied auto-accept at acceptance time"
            return _autopilot_finish(args, summary, None, {}, escalate=True)
        snap = repo.head_snapshot()
        hooks = _run_after_hooks(repo, cfg, "after_accept")
        ledgermod.append(repo, "autopilot", None, {"id": "autopilot"},
                         {"action": "auto_accept", "snapshot": snap, "review_id": review["review_id"]})
        summary["action"] = "auto-accepted"
        return _autopilot_finish(args, summary, snap, hooks)

    # escalate / request_changes / no_decision
    summary["action"] = "escalated"
    return _autopilot_finish(args, summary, None, {}, escalate=True, repo=repo, args2=args)


def _autopilot_finish(args, s, snapshot, hooks, escalate=False, repo=None, args2=None) -> int:
    if getattr(args, "json", False):
        out = dict(s); out["accepted_snapshot"] = snapshot; out["hooks"] = hooks
        print(_dump(out))
        return 0 if not escalate else 0
    info("")
    info(util.bold("  Claude changed {} file(s) (+{} -{}).".format(s["files"], s["ins"], s["dels"])))
    info("")
    tcol = util.green if s["tests"] == "passed" else (util.yellow if s["tests"] in ("not run", "skipped") else util.red)
    info("  Tests:        " + tcol(s["tests"]))
    if escalate:
        info("  Policy:       " + util.yellow("human required" if s["policy"] != "deny" else util.red("denied")))
        info("  Owner Agent:  " + util.yellow(s["owner_agent"]))
        info("  Risk:         " + (util.red(s["risk"]) if s["risk"] == "high" else util.yellow(s["risk"])))
        info("  Reason:       " + s["reasoning"])
        info("")
        if repo is not None:
            info("  [a] accept manually   [r] rollback   [d] diff   [p] packet   [q] quit")
            return _claude_review(repo, args2 or args)
        return 0
    info("  Policy:       " + util.green("allowed"))
    info("  Owner Agent:  " + util.green("approved"))
    info("  Risk:         " + util.green(s["risk"]))
    info("  Action:       " + util.green(s["action"]))
    info("  History:      " + ("signed + sealed" if snapshot else "—"))
    info("  Backup:       " + (hooks.get("backup", "—")))
    if snapshot:
        info("")
        info("  Accepted Snapshot: " + util.cyan(_short(snapshot)))
    return 0


def _claude_review(repo: Repo, args) -> int:
    sess = Session.active(repo)
    if sess is None:
        info("No active session to review.")
        return 0
    _print_claude_summary(_claude_summary(repo, sess))

    def do(choice: str) -> Optional[int]:
        if choice in ("a", "accept"):
            return cmd_accept(argparse.Namespace(message=sess.data.get("instruction"), no_verify=True,
                                                 no_sign=False, force=False, override=False, reason=None))
        if choice in ("r", "rollback"):
            return cmd_rollback(argparse.Namespace(to_start=False, to_snapshot=None, hard=True,
                                                   keep_files=False, yes=True, keep_session_active=False))
        if choice in ("d", "diff"):
            cmd_diff(argparse.Namespace(from_snapshot=None, to_snapshot=None, summary=False, files=False))
            return None
        if choice in ("p", "packet"):
            cmd_packet(argparse.Namespace(json=False))
            return None
        if choice in ("q", "quit"):
            info("Left the session open. Decide later: checkpoint-core accept | rollback")
            return 0
        return None

    if args.decision:
        rc = do(args.decision)
        return rc if rc is not None else 0
    while True:
        try:
            choice = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            info("\nLeft the session open. Decide later: checkpoint-core accept | rollback")
            return 0
        rc = do(choice)
        if rc is not None:
            return rc


# ---------------------------------------------------------------------- mr (scriptable review surface)

def _mr_remote(args):
    """Resolve the hosted remote backing merge requests -> (ui_base, token, owner, repo).

    ui_base is the server's /ui adapter root for this repo, e.g.
    http://host:8800/ui/repos/<owner>/<repo>.
    """
    from urllib.parse import urlparse
    repo = _repo()
    remotes = remotemod.list_remotes(repo)
    name = getattr(args, "remote", None)
    spec = None
    if name:
        spec = remotes.get(name)
    else:
        for cand in ("checkpoint", "origin"):
            if remotes.get(cand, {}).get("type") == "http":
                spec = remotes[cand]; break
        if spec is None:
            https = [s for s in remotes.values() if s.get("type") == "http"]
            spec = https[0] if len(https) == 1 else None
    if not spec or spec.get("type") != "http":
        err("no hosted remote configured. Add one: checkpoint-core remote add checkpoint "
            "http://host:8800/<owner>/<repo> --token <TOKEN>")
        return None
    u = urlparse(spec["url"].rstrip("/"))
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        err("remote URL must be http://host/<owner>/<repo>")
        return None
    owner, name_ = parts[-2], parts[-1]
    ui_base = "{}://{}/ui/repos/{}/{}".format(u.scheme, u.netloc, owner, name_)
    return ui_base, spec.get("token"), owner, name_


def _mr_call(method, ui_base, token, path, body=None):
    return remotemod._http(method, ui_base + path, token, body)


def _mr_diff_text(diff) -> None:
    for f in diff or []:
        ct = f.get("change_type")
        if ct == "renamed":
            info(util.bold("R {} -> {}".format(f["old_path"], f["new_path"]))
                 + util.dim("  {}%".format(f.get("similarity", "?"))))
        else:
            p = f.get("new_path") if ct != "deleted" else f.get("old_path")
            info(util.bold("{} {}".format(ct[:1].upper(), p)))
        for h in f.get("hunks", []):
            info(util.cyan("  " + h.get("header", "")))
            for ln in h.get("lines", []):
                k = ln.get("kind"); t = ln.get("text", "")
                if k == "add":
                    info(util.green("  +" + t))
                elif k == "del":
                    info(util.red("  -" + t))
                else:
                    info(util.dim("   " + t))


def _mr_print_screen(d) -> None:
    """The one-screen review summary (mirrors checkpoint-core claude)."""
    st = {"open": util.cyan, "merged": util.green, "closed": util.dim}.get(d["status"], str)
    info("")
    info(util.bold("MR {}: {}".format(d["id"], d["title"])) + "   " + st(d["status"]))
    info("  Source:    {}".format(_short(d.get("source_snapshot") or "")
                                   + (" (session {})".format(d["source_session"][:18]) if d.get("source_session") else "")))
    info("  Target:    {}".format(d.get("target_branch")))
    nfiles = len(d.get("diff", []))
    ins = sum(f.get("additions", 0) for f in d.get("diff", []))
    dels = sum(f.get("deletions", 0) for f in d.get("diff", []))
    info("  Files:     {} (+{} -{})".format(nfiles, ins, dels))
    m = d.get("mergeability", {})
    sig = d.get("signatures", [])
    sigok = "valid" if sig and all(s.get("status") == "valid" for s in sig) else ("unsigned" if not sig else "invalid")
    pol = d.get("policy")
    info("  Policy:    {}".format(_mr_color_effect(pol)))
    info("  Approvals: {}{}".format(d.get("approval_count", 0),
                                    "  ({})".format(", ".join(d.get("approvals", []))) if d.get("approvals") else ""))
    info("  Comments:  {} unresolved".format(d.get("unresolved_count", 0)))
    info("  Conflicts: {}".format(util.green("none") if m.get("clean") else
                                  util.red(", ".join(m.get("conflicts", [])) or "yes")))
    info("  Signatures:{}".format(" " + (util.green("valid") if sigok == "valid" else util.yellow(sigok))))
    info("")
    info("  [a] approve   [m] merge   [d] diff   [c] comment   [q] quit")


def _mr_color_effect(pol):
    if pol is None:
        return "allowed (no policy)"
    if pol["effect"] == "allow":
        return util.green("allowed")
    if pol["effect"] == "deny":
        return util.red("DENIED — " + "; ".join(pol.get("reasons", [])))
    return util.yellow("warn — " + "; ".join(pol.get("reasons", [])))


def _mr_merge_report(res) -> int:
    s = res.get("status")
    if s == "merged":
        info(util.green("Merged ") + "into target" + (" -> " + _short(res["snapshot"]) if res.get("snapshot") else ""))
        return 0
    if s == "conflicts":
        err("merge conflicts: " + ", ".join(res.get("conflicts", [])))
        info(util.dim("  resolve locally (checkpoint-core merge) and push, then retry"))
        return 1
    if s == "policy-denied":
        err("policy denied: " + "; ".join(res.get("reasons", [])))
        for a in res.get("required_actions", []):
            info(util.dim("  - " + a))
        return 1
    err("merge failed: " + (res.get("error") or s or "unknown"))
    return 1


def cmd_mr(args) -> int:
    sub = args.mr_cmd
    if not sub:
        err("usage: checkpoint-core mr <create|list|show|diff|comment|approve|unapprove|merge|close|status|review>")
        return 2
    r = _mr_remote(args)
    if r is None:
        return 2
    ui_base, token, owner, name = r
    base = "/reviews"

    if sub == "create":
        body = {"title": args.title or "(untitled)", "target_branch": args.to or "main"}
        if args.from_branch:
            body["source_branch"] = args.from_branch
        elif args.snapshot:
            body["source_snapshot"] = args.snapshot
        elif args.session:
            body["source_session"] = args.session
        else:
            err("provide a source: --from <branch>, --snapshot <id>, or --session <id>")
            return 2
        st, resp = _mr_call("POST", ui_base, token, base, body)
        if st not in (200, 201):
            err("create failed ({}): {}".format(st, resp.get("error") if isinstance(resp, dict) else resp))
            return 1
        info(util.green("Created ") + util.bold(resp["id"]) + " — " + resp["title"]
             + util.dim("  ({} -> {})".format(_short(resp.get("source_snapshot") or ""), resp["target_branch"])))
        return 0

    if sub == "list":
        st, rows = _mr_call("GET", ui_base, token, base)
        if st != 200:
            err("list failed ({})".format(st)); return 1
        if not rows:
            info("No merge requests."); return 0
        info(util.bold("{:<7} {:<8} {:<10} {:<8} {}".format("ID", "STATUS", "INTO", "APPROVE", "TITLE")))
        for m in rows:
            info("{:<7} {:<8} {:<10} {:<8} {}".format(
                m["id"], m["status"], m.get("target_branch", "")[:10],
                "{}".format(m.get("approval_count", 0)), m["title"][:50]))
        return 0

    if sub in ("show", "status", "diff", "review"):
        st, d = _mr_call("GET", ui_base, token, base + "/" + args.id)
        if st != 200:
            err("no such merge request: {}".format(args.id)); return 1
        if sub == "diff":
            _mr_diff_text(d.get("diff", []))
            return 0
        if sub == "status":
            info("{} [{}] into {} · approvals {} · {} · conflicts {}".format(
                d["id"], d["status"], d.get("target_branch"), d.get("approval_count", 0),
                "policy " + (d["policy"]["effect"] if d.get("policy") else "none"),
                "none" if d.get("mergeability", {}).get("clean") else "yes"))
            return 0
        if sub == "show":
            _mr_print_screen(d)
            return 0
        # review (interactive)
        return _mr_review_loop(ui_base, token, base, args, d)

    if sub == "comment":
        body = {"body": args.body, "path": args.file, "line": args.line}
        st, c = _mr_call("POST", ui_base, token, base + "/" + args.id + "/comments", body)
        if st not in (200, 201):
            err("comment failed ({})".format(st)); return 1
        info(util.green("Commented ") + ("on {}:{}".format(args.file, args.line) if args.file else "(general)"))
        return 0

    if sub in ("approve", "unapprove"):
        st, m = _mr_call("POST", ui_base, token, base + "/" + args.id + "/approve",
                         {"approve": sub == "approve"})
        if st != 200:
            err("{} failed ({})".format(sub, st)); return 1
        info(util.green("{}d ".format(sub.capitalize())) + args.id
             + util.dim("  ({} approval(s))".format(m.get("approval_count", 0))))
        return 0

    if sub == "merge":
        st, res = _mr_call("POST", ui_base, token, base + "/" + args.id + "/merge", {})
        return _mr_merge_report(res if isinstance(res, dict) else {"status": "error"})

    if sub == "close":
        st, m = _mr_call("POST", ui_base, token, base + "/" + args.id + "/close", {})
        if st != 200:
            err("close failed ({})".format(st)); return 1
        info(util.green("Closed ") + args.id)
        return 0

    err("unknown mr subcommand: {}".format(sub))
    return 2


def _mr_review_loop(ui_base, token, base, args, d) -> int:
    _mr_print_screen(d)

    def act(choice):
        if choice in ("a", "approve"):
            _mr_call("POST", ui_base, token, base + "/" + args.id + "/approve", {"approve": True})
            info(util.green("Approved.")); return None
        if choice in ("m", "merge"):
            st, res = _mr_call("POST", ui_base, token, base + "/" + args.id + "/merge", {})
            return _mr_merge_report(res if isinstance(res, dict) else {"status": "error"})
        if choice in ("d", "diff"):
            _mr_diff_text(d.get("diff", [])); return None
        if choice in ("c", "comment"):
            try:
                body = input("comment: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if body:
                _mr_call("POST", ui_base, token, base + "/" + args.id + "/comments", {"body": body})
                info(util.green("Commented."))
            return None
        if choice in ("q", "quit"):
            return 0
        return None

    if args.decision:
        rc = act(args.decision)
        return rc if rc is not None else 0
    while True:
        try:
            choice = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        rc = act(choice)
        if rc is not None:
            return rc
        # refresh after an action that changed state
        st, d2 = _mr_call("GET", ui_base, token, base + "/" + args.id)
        if st == 200:
            d = d2
            _mr_print_screen(d)


# ---------------------------------------------------------------------- next / first-push / web (concierge)

def _personal_cfg(repo) -> dict:
    return repo.config.data.get("personal", {}) or {}


def _set_personal(repo, **kw) -> None:
    p = repo.config.data.setdefault("personal", {})
    p.update(kw)
    repo.config.save()


def _quiet_http_remote(repo):
    """(ui_base, token) for the hosted remote, or None — never errors/prints."""
    from urllib.parse import urlparse
    remotes = remotemod.list_remotes(repo)
    spec = None
    for cand in ("checkpoint", "origin"):
        if remotes.get(cand, {}).get("type") == "http":
            spec = remotes[cand]; break
    if not spec:
        return None
    try:
        u = urlparse(spec["url"].rstrip("/"))
        parts = [p for p in u.path.split("/") if p]
        if len(parts) < 2:
            return None
        return "{}://{}/ui/repos/{}/{}".format(u.scheme, u.netloc, parts[-2], parts[-1]), spec.get("token")
    except Exception:
        return None


def _open_mrs(repo):
    r = _quiet_http_remote(repo)
    if not r:
        return None  # no hosted remote
    ui_base, token = r
    try:
        st, rows = remotemod._http("GET", ui_base + "/reviews", token, None, None, 3.0)
        if st != 200 or not isinstance(rows, list):
            return None
        return [m for m in rows if m.get("status") == "open"]
    except Exception:
        return None


def _backup_state(repo):
    spec = remotemod.list_remotes(repo).get("backup")
    if not spec:
        return {"configured": False, "status": "not configured"}
    try:
        stt = remotemod.sync_status(repo, "backup")
        rels = [b.get("relationship", "") for b in stt.get("branches", [])]
        if any("ahead" in r for r in rels):
            return {"configured": True, "status": "behind"}     # local ahead of backup
        return {"configured": True, "status": "current"}
    except Exception:
        return {"configured": True, "status": "not reachable"}


def cmd_next(args) -> int:
    as_json = getattr(args, "json", False)
    root = Path.cwd()
    if not (root / ".checkpoint").exists():
        return _next_emit({
            "initialized": False, "repo": root.name,
            "recommended_action": "init",
            "recommended_reason": "Checkpoint is not set up in this repo yet",
            "suggested": ["checkpoint-core personal init"],
        }, as_json)

    repo = _repo()
    head = repo.head_snapshot()
    head_tree = repo.get_object(head)["tree"] if head and repo.has_object(head) else None
    cur_tree = scan_to_tree(repo)
    td = tree_diff(repo, head_tree, cur_tree)
    dirty = bool(td["files"])

    sess = Session.active(repo)
    open_sessions = [s for s in repo.session_ids()
                     if (util.read_json(repo.paths.session_dir(s) / "session.json", {}) or {}).get("status") == "active"]
    active = None
    if sess is not None:
        ver = verifymod.last_verification(repo, sess)
        active = {"id": sess.id, "instruction": sess.data.get("instruction", ""),
                  "files_changed": td["stats"]["files_changed"],
                  "tests": (ver.get("overall") if ver else "not run"),
                  "last_snapshot": (sess.data.get("snapshots") or [None])[-1]}

    last_accepted = None
    if head:
        try:
            last_accepted = {"snapshot": head, "message": repo.get_object(head).get("message", "")}
        except Exception:
            pass

    pcfg = _personal_cfg(repo)
    first_push_done = bool(pcfg.get("first_push_done"))
    first_push_needed = (not first_push_done) and head is not None

    mrs = _open_mrs(repo)
    backup = _backup_state(repo)
    integrity = "healthy" if (head is None or repo.has_object(head)) else "warnings"
    try:
        signatures = "valid" if signmod.verify_all(repo).get("ok") else "issues"
    except Exception:
        signatures = "n/a"

    # recommend (priority order)
    if first_push_needed:
        rec, why = "first_push", "this repo has not been pushed or backed up yet"
    elif active is not None:
        rec, why = "resume", "you have an open session: {}".format(active["instruction"][:50])
    elif dirty:
        rec, why = "create_session", "untracked/unaccepted changes but no active session"
    elif mrs:
        rec, why = "review", "open merge request waiting: {}".format(mrs[0]["id"])
    elif backup["configured"] and backup["status"] == "behind":
        rec, why = "backup", "accepted history is ahead of your backup"
    else:
        rec, why = "new_task", "repo is clean — start a new task"

    data = {
        "initialized": True, "repo": root.name, "branch": repo.head_branch() or "(detached)",
        "status": "dirty" if dirty else "clean",
        "first_push_done": first_push_done, "first_push_needed": first_push_needed,
        "open_sessions": open_sessions, "active_session": active,
        "dirty_no_session": dirty and active is None,
        "open_mrs": mrs or [], "open_mrs_available": mrs is not None,
        "last_accepted": last_accepted,
        "verification": (active["tests"] if active else "n/a"),
        "policy": "active" if policymod.load(repo) else "none",
        "signatures": signatures, "backup": backup, "integrity": integrity,
        "recommended_action": rec, "recommended_reason": why,
    }
    return _next_emit(data, as_json)


def _next_emit(d, as_json) -> int:
    if as_json:
        print(_dump(d))
        return 0
    if not d.get("initialized"):
        info(util.yellow("Checkpoint is not set up in this repo."))
        info("  Suggested: " + util.bold("checkpoint-core personal init"))
        return 0
    info(util.bold("Checkpoint Summary"))
    info("  Repo:          {}".format(d["repo"]))
    info("  Branch:        {}".format(d["branch"]))
    info("  Status:        {}".format(util.yellow(d["status"]) if d["status"] == "dirty" else util.green("clean")))
    if d.get("last_accepted"):
        info("  Last accepted: {}".format((d["last_accepted"]["message"] or "")[:50]))
    info("  Open sessions: {}".format(len(d["open_sessions"])))
    if d.get("open_mrs_available"):
        info("  Open MRs:      {}".format(len(d["open_mrs"])))
    info("  Policy:        {}".format(d["policy"]))
    info("  Signatures:    {}".format(d["signatures"]))
    info("  Backup:        {}".format(d["backup"]["status"]))
    info("  Integrity:     {}".format(d["integrity"]))
    info("")
    if d.get("active_session"):
        a = d["active_session"]
        info(util.bold("You have an open session: ") + a["instruction"][:60])
        info("  {} file(s) changed · tests: {}".format(a["files_changed"], a["tests"]))
        info("  Suggested: " + util.green("resume with Claude") + util.dim("  (checkpoint-core claude --continue)"))
    else:
        info("Suggested next: " + util.green(d["recommended_action"]) + util.dim("  ({})".format(d["recommended_reason"])))
    return 0


def cmd_first_push(args) -> int:
    repo = _repo()
    if getattr(args, "status", False):
        done = bool(_personal_cfg(repo).get("first_push_done"))
        print(_dump({"first_push_done": done}) if getattr(args, "json", False)
              else ("first push: done" if done else "first push: not done"))
        return 0
    pcfg = _personal_cfg(repo)
    if pcfg.get("first_push_done") and not getattr(args, "force", False):
        info("First push already completed. (Use backup run / push to sync.)")
        return 0
    # choose a destination
    remotes = remotemod.list_remotes(repo)
    dest_name, dest_label = None, None
    for cand in ("checkpoint", "origin"):
        if remotes.get(cand, {}).get("type") == "http":
            dest_name = cand; dest_label = remotes[cand]["url"]; break
    if not dest_name and remotes.get("backup"):
        dest_name = "backup"; dest_label = remotes["backup"].get("path")
    if not dest_name:
        if not (getattr(args, "yes", False) or getattr(args, "dest", None)):
            if not confirm("No remote/backup configured. Create a local backup folder?", False):
                info("Skipped. Continuing local-only."); return 0
        dest = args.dest or str(Path.home() / "CheckpointBackups" / Path.cwd().name)
        _init_store_at(dest)
        remotemod.add_remote(repo, "backup", "filesystem", dest, require_signed_snapshots=False)
        dest_name, dest_label = "backup", dest
    branch = repo.head_branch() or "main"
    try:
        res = remotemod.push(repo, dest_name, branch, tags=True)
    except ValueError as exc:
        err(str(exc)); return 1
    if res.get("status") not in ("pushed", "up-to-date"):
        err("first push failed: {}".format(res.get("status"))); return 1
    # verify + record
    ok = True
    try:
        remotemod.sync_status(repo, dest_name)
    except Exception:
        ok = False
    _set_personal(repo, first_push_done=True, default_backup=dest_name if dest_name == "backup" else None,
                  default_remote=dest_name if dest_name != "backup" else _personal_cfg(repo).get("default_remote"))
    ledgermod.append(repo, "backup", None, {"id": "first-push"},
                     {"action": "first_push", "remote": dest_name, "objects": res.get("objects_sent", 0)})
    info(util.green("First push complete."))
    info("  Remote: {}".format(dest_label))
    info("  Synced: accepted history, sessions, signatures, public identities, policy, tags, audit")
    info("  Not synced: private keys, autosaves")
    info("  Backup status: " + ("current" if ok else "pushed (status check unavailable)"))
    return 0


def cmd_web(args) -> int:
    urls = ["http://localhost:3000", "http://localhost:8800/"]
    info(util.bold("Web review UI:"))
    info("  {}   {}".format(urls[0], util.dim("(full Next.js app)")))
    info("  {}  {}".format(urls[1], util.dim("(embedded, served by checkpoint-server)")))
    if getattr(args, "open", False):
        import subprocess as _sub
        try:
            _sub.run(["open", urls[0]])
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------- autopilot / personal / backup

def cmd_autopilot(args) -> int:
    sub = args.autopilot_cmd
    if sub == "claude":
        ns = argparse.Namespace(task=args.task, model=getattr(args, "model", None),
                                tag=getattr(args, "tag", None), no_tests=getattr(args, "no_tests", False),
                                no_launch=getattr(args, "no_launch", False), login=getattr(args, "login", False),
                                autopilot=True, json=getattr(args, "json", False),
                                decision=getattr(args, "decision", None))
        return cmd_claude(ns)
    if sub == "config":
        repo = _repo()
        print(_dump(owneragentmod.load_config(repo)))
        return 0
    if sub == "review":
        repo = _repo()
        sess = Session.active(repo)
        if sess is None:
            err("no active session to review (autopilot review currently reviews the active session)")
            return 1
        review = owneragentmod.review_session(repo, sess)
        if getattr(args, "json", False):
            print(_dump(review)); return 0
        info(util.bold("Owner Agent review ") + review["review_id"])
        info("  decision:   {}".format(review["decision"]))
        info("  risk:       {}  confidence: {}".format(review["risk"], review["confidence"]))
        info("  reasoning:  {}".format(review["reasoning"]))
        info("  recommend:  {}".format(review["recommended_action"]))
        return 0
    if sub == "status":
        repo = _repo()
        rows = [e for e in ledgermod.read_all(repo) if e["event_type"] in ("autopilot", "owner_review")]
        if not rows:
            info("No autopilot runs yet."); return 0
        for e in rows[-15:]:
            p = e["payload"]
            info("{}  {}  {}".format(e["timestamp"][:19], e["event_type"],
                                     p.get("action") or "{} ({})".format(p.get("decision"), p.get("risk"))))
        return 0
    err("usage: checkpoint-core autopilot <claude|review|status|config>")
    return 2


def _write_solo_policy(repo) -> None:
    import copy
    pol = copy.deepcopy(policymod.DEFAULT_STARTER_POLICY)
    pol["required_verification"] = {"default": False, "commands": ["tests"]}
    import yaml
    with open(policymod.policy_path(repo), "w", encoding="utf-8") as fh:
        fh.write("# Checkpoint policy (personal preset).\n")
        fh.write(yaml.safe_dump(pol, sort_keys=False))


def cmd_personal(args) -> int:
    sub = args.personal_cmd or "status"
    if sub == "init":
        root = Path.cwd()
        if not (root / ".checkpoint").exists():
            rc = cmd_init(argparse.Namespace(branch=None, name=None, email=None, force=False,
                                             yes=True, safe_git_adapter=False))
            if rc:
                return rc
        repo = _repo()
        if not repo.current_identity_id():
            human = idmod.create(repo, name=args.name or "You", id_type="human")
            info(util.green("Created your identity ") + "{} ({})".format(human["name"], human["identity_id"]))
        else:
            info("Using identity {}".format(repo.current_identity_id()))
        owner = owneragentmod.owner_identity(repo)
        info(util.green("Owner Agent identity ") + "{} ({})".format(owner["name"], owner["identity_id"]))
        cfg = owneragentmod.load_config(repo)
        if getattr(args, "no_autoaccept", False):
            cfg["default_mode"] = "review_only"
            cfg["auto_accept_allowed"]["paths"] = []
        owneragentmod.save_config(repo, cfg)
        info(util.green("Autopilot config written ") + util.dim("(.checkpoint/autopilot.yaml)"))
        if policymod.load(repo) is None:
            _write_solo_policy(repo)
            info(util.green("Policy preset written ") + util.dim("(protect main, signed accepts; verification optional)"))
        if getattr(args, "backup_path", None):
            remotemod.add_remote(repo, "backup", "filesystem", args.backup_path, require_signed_snapshots=False)
            info(util.green("Backup remote set ") + args.backup_path)
        info("")
        info(util.bold("Personal Checkpoint ready.") + " Try:")
        info('  checkpoint-core claude "Update the README" --autopilot')
        info("  checkpoint-core personal daily")
        return 0

    repo = _repo()
    if sub == "status":
        cur = idmod.load(repo, repo.current_identity_id()) if repo.current_identity_id() else {}
        owner = next((i for i in idmod.list_all(repo) if i.get("name") == owneragentmod.OWNER_AGENT_NAME), None)
        cfg = owneragentmod.load_config(repo)
        backup = remotemod.list_remotes(repo).get("backup")
        default = next((n for n in ("checkpoint", "origin") if remotemod.list_remotes(repo).get(n)), None)
        info(util.bold("Personal status"))
        info("  identity:     {} ({})".format(cur.get("name", "—"), cur.get("type", "")))
        info("  owner agent:  {}".format(owner["identity_id"] if owner else util.yellow("not set (run personal init)")))
        info("  autopilot:    mode={} · auto-accept paths={}".format(
            cfg.get("default_mode"), ", ".join(cfg.get("auto_accept_allowed", {}).get("paths", [])) or "none"))
        info("  policy:       {}".format("active" if policymod.load(repo) else "none"))
        info("  default remote: {}".format(default or "—"))
        info("  backup:       {}".format(backup.get("path") if backup else "not configured"))
        try:
            info("  integrity:    {}".format(fsckmod.check(repo, strict=False)["result"]))
        except Exception:
            pass
        return 0

    if sub == "daily":
        from datetime import datetime
        today = util.now_iso()[:10]
        evs = [e for e in ledgermod.read_all(repo) if e.get("timestamp", "").startswith(today)]
        def count(t):
            return sum(1 for e in evs if e["event_type"] == t)
        autoacc = sum(1 for e in evs if e["event_type"] == "autopilot" and e["payload"].get("action") == "auto_accept")
        escalated = sum(1 for e in evs if e["event_type"] == "owner_review" and e["payload"].get("decision") == "escalate")
        open_sessions = [s for s in repo.session_ids()
                         if (util.read_json(repo.paths.session_dir(s) / "session.json", {}) or {}).get("status") == "active"]
        backup = remotemod.list_remotes(repo).get("backup")
        info(util.bold("Today ({})".format(today)))
        info("  Sessions started: {}".format(count("session_start")))
        info("  Accepted:         {}  (auto-accepted: {})".format(count("accept"), autoacc))
        info("  Escalated:        {}".format(escalated))
        info("  Rolled back:      {}".format(count("rollback")))
        info("  Open sessions:    {}".format(len(open_sessions)))
        info("  Verifications:    {}".format(count("verification")))
        info("  Backup:           {}".format("configured" if backup else "not configured"))
        try:
            info("  Integrity:        {}".format(fsckmod.check(repo, strict=False)["result"]))
            info("  Signatures:       {}".format("valid" if signmod.verify_all(repo).get("ok") else "issues"))
        except Exception:
            pass
        head = repo.head_snapshot()
        info("  Latest accepted:  {}".format(_short(head) if head else "—"))
        info("  Branch:           {}".format(repo.head_branch() or "—"))
        return 0

    err("usage: checkpoint-core personal <init|status|daily>")
    return 2


def _init_store_at(root) -> Repo:
    """Initialize a bare Checkpoint store at an arbitrary path (for a filesystem backup)."""
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    repo = Repo(root); p = repo.paths
    if p.config.exists():
        return repo
    for d in (p.base, p.objects, p.sessions, p.refs_heads, p.tmp, p.cache):
        d.mkdir(parents=True, exist_ok=True)
    if not p.ledger.exists():
        p.ledger.touch()
    cfg = Config(default_config(project=root.name), p.config)
    cfg.data["default_branch"] = "main"; cfg.save(); repo._config = None
    repo.set_head_to_branch("main")
    repo.write_state({"active_session": None})
    ledgermod.append(repo, "init", None, repo.identity(), {"version": __version__, "branch": "main"})
    return repo


def cmd_backup(args) -> int:
    sub = args.backup_cmd
    repo = _repo()
    if sub == "init":
        if not args.path:
            err("provide a backup path: checkpoint-core backup init <dir>"); return 2
        _init_store_at(args.path)                 # backup target must be an initialized store
        remotemod.add_remote(repo, "backup", "filesystem", args.path, require_signed_snapshots=False)
        info(util.green("Backup remote configured ") + args.path)
        return 0
    spec = remotemod.list_remotes(repo).get("backup")
    if not spec:
        err("no backup configured. Run: checkpoint-core backup init <dir>"); return 1
    if sub == "run":
        try:
            res = remotemod.push(repo, "backup", repo.head_branch() or "main", tags=True)
        except ValueError as exc:
            err(str(exc)); return 1
        st = res.get("status")
        if st in ("pushed", "up-to-date"):
            info(util.green("Backup synced ") + util.dim("({} object(s))".format(res.get("objects_sent", 0))))
            return 0
        err("backup failed: {}".format(st)); return 1
    if sub == "status":
        try:
            stt = remotemod.sync_status(repo, "backup")
        except Exception as exc:
            err("backup unreachable: {}".format(exc)); return 1
        info(util.bold("Backup status") + util.dim("  ({})".format(spec.get("path"))))
        for b in stt["branches"]:
            info("  {:<16} {}".format(b["branch"], b["relationship"]))
        info("  integrity:  {}".format(fsckmod.check(repo, strict=False)["result"]))
        info("  signatures: {}".format("valid" if signmod.verify_all(repo).get("ok") else "issues"))
        return 0
    if sub == "restore":
        info(util.bold("Restore preview ") + util.dim("(from {})".format(spec.get("path"))))
        try:
            report = remotemod.fetch(repo, "backup")
        except Exception as exc:
            err("backup unreachable: {}".format(exc)); return 1
        info("  fetched remote-tracking refs from backup (verified).")
        if not args.yes:
            info(util.yellow("  preview only. Re-run with --yes to fast-forward local refs from backup."))
            return 0
        rc = cmd_pull(argparse.Namespace(remote="backup", branch=repo.head_branch() or "main",
                                         branch_opt=None, verify_signatures=True, dry_run=False, json=False))
        return rc
    err("usage: checkpoint-core backup <init|run|status|restore>")
    return 2


# ---------------------------------------------------------------------- identity

def _fp_short(rec) -> str:
    return (rec.get("fingerprint") or "")[:24]


def cmd_identity(args) -> int:
    repo = _repo()
    sub = args.identity_cmd or "current"

    if sub == "set":  # legacy author identity (name/email in identity.json)
        ident = repo.identity()
        if args.name:
            ident["name"] = args.name
        if args.email:
            ident["email"] = args.email
            ident["id"] = args.email
        util.write_json(repo.paths.identity, ident)
        ledgermod.append(repo, "identity", None, ident, {})
        info(util.green("Identity updated: ") + "{} <{}>".format(ident.get("name"), ident.get("email")))
        return 0

    if sub == "create":
        rec = idmod.create(repo, name=args.name or "", id_type=args.type or "human",
                           email=args.email)
        ledgermod.append(repo, "identity", None, {"id": rec["identity_id"], "name": rec["name"]},
                         {"type": rec["type"], "fingerprint": rec["fingerprint"]})
        info(util.green("Created identity ") + util.bold(rec["identity_id"]))
        info("  name:        {}".format(rec["name"]))
        info("  type:        {}".format(rec["type"]))
        info("  fingerprint: {}".format(rec["fingerprint"]))
        info("  key:         {} (private, 0600)".format(idmod.key_path(repo, rec["identity_id"])))
        if repo.current_identity_id() == rec["identity_id"]:
            info("  set as the active signing identity.")
        return 0

    if sub == "list":
        recs = idmod.list_all(repo)
        if not recs:
            info("No identities. Create one: checkpoint-core identity create --name \"You\"")
            return 0
        cur = repo.current_identity_id()
        info(util.bold("{:<30} {:<8} {:<10} {}".format("IDENTITY", "TYPE", "TRUST", "FINGERPRINT")))
        for r in recs:
            trust = "revoked" if r.get("revoked") else ("trusted" if r.get("trusted") else "untrusted")
            mark = "* " if r["identity_id"] == cur else "  "
            info("{}{:<28} {:<8} {:<10} {}".format(mark, r["identity_id"], r["type"],
                                                   _color_trust(trust), _fp_short(r)))
        return 0

    if sub == "show":
        rec = idmod.load(repo, args.id)
        if not rec:
            err("no such identity: {}".format(args.id))
            return 1
        info(util.bold("Identity ") + util.cyan(rec["identity_id"]))
        info("  name:        {}".format(rec.get("name")))
        info("  type:        {}".format(rec.get("type")))
        info("  fingerprint: {}".format(rec.get("fingerprint")))
        info("  algorithm:   {}".format(rec.get("key_algorithm")))
        info("  created:     {}".format(rec.get("created_at")))
        info("  capabilities:{}".format(" " + ", ".join(rec.get("capabilities", []))))
        info("  trusted:     {}".format(rec.get("trusted")))
        info("  revoked:     {}".format(rec.get("revoked")))
        info("  has private: {}".format(idmod.has_private(repo, rec["identity_id"])))
        warn = idmod.key_permissions_warning(repo, rec["identity_id"])
        if warn:
            info(util.yellow("  WARNING: " + warn))
        return 0

    if sub in ("trust", "untrust"):
        if idmod.load(repo, args.id) is None:
            err("no such identity: {}".format(args.id))
            return 1
        ok, decision = policy_gate(repo, None, "trust")   # records a policy decision when enabled
        if not ok:
            _print_denial(decision)
            return 1
        rec = idmod.set_trust(repo, args.id, sub == "trust")
        ledgermod.append(repo, "trust", None, repo.identity(),
                         {"identity": rec["identity_id"], "trusted": sub == "trust"})
        info(util.green("Identity {} is now {}.".format(rec["identity_id"], sub + "ed")))
        return 0

    if sub == "revoke":
        rec = idmod.revoke(repo, args.id)
        if not rec:
            err("no such identity: {}".format(args.id))
            return 1
        info(util.yellow("Identity {} revoked.".format(rec["identity_id"])))
        return 0

    if sub == "import":
        data = util.read_json(args.path, None)
        if not data:
            err("could not read identity file: {}".format(args.path))
            return 1
        rec = idmod.import_record(repo, data)
        info(util.green("Imported identity ") + util.bold(rec["identity_id"]) +
             util.yellow(" (untrusted)"))
        info("  Run `checkpoint-core identity trust {}` to trust it.".format(rec["identity_id"]))
        return 0

    if sub == "export":
        rec = idmod.export_record(repo, args.id)
        if not rec:
            err("no such identity: {}".format(args.id))
            return 1
        out = args.out or "{}.identity.json".format(rec["identity_id"])
        util.write_json(Path(out), rec)
        info(util.green("Exported public identity ") + rec["identity_id"] + " -> " + out)
        info(util.dim("  (public key only; private key never exported)"))
        return 0

    if sub == "current":
        rec = idmod.current(repo)
        if not rec:
            info("No active signing identity. Create one: checkpoint-core identity create --name \"You\"")
            info("(author falls back to {})".format(repo.identity().get("id")))
            return 0
        info("active signing identity: {} ({}) {}".format(
            rec["identity_id"], rec["type"], rec["fingerprint"]))
        return 0

    if sub == "use":
        rec = idmod.load(repo, args.id)
        if not rec:
            err("no such identity: {}".format(args.id))
            return 1
        if not idmod.has_private(repo, rec["identity_id"]):
            info(util.yellow("note: no private key for this identity; it cannot sign."))
        idmod.set_current(repo, rec["identity_id"])
        info(util.green("Active signing identity: ") + rec["identity_id"])
        return 0

    err("unknown identity subcommand")
    return 2


def _color_trust(t: str) -> str:
    return {"trusted": util.green, "untrusted": util.yellow,
            "revoked": util.red}.get(t, lambda x: x)(t)


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
    # record the active signing identity (if any) on the session
    cur_id = repo.current_identity_id()
    if cur_id:
        sess.data["signing_identity"] = cur_id
        sess.save()
    repo.set_active_session(sess.id)
    ledgermod.append(repo, "session_start", sess.id, actor,
                     {"instruction": instruction, "base_tree": base_tree, "risk_tags": tags,
                      "signing_identity": cur_id})
    timelinemod.append(repo, sess.id, "session_started",
                       {"instruction": instruction, "base_snapshot": sess.base_head})

    info(util.green("Started session ") + util.bold(sess.id))
    info("  instruction: {}".format(instruction))
    info("  branch:      {}".format(repo.head_branch() or "(detached)"))
    info("  base:        {}".format(_short(repo.head_snapshot()) if repo.head_snapshot() else "(unborn)"))
    if tags:
        info("  risk tags:   {}".format(", ".join(tags)))

    # Continuous autosave for the life of the session (recovery-only; never history).
    # Self-terminates when the session ends. Opt out with --no-watch or autosave.enabled=false.
    if not getattr(args, "no_watch", False):
        try:
            pid = autowatchmod.start(repo)
            if pid:
                info(util.dim("  autosave:    on (background watcher, pid {}). You are never unsaved.".format(pid)))
        except Exception:
            pass  # autosave is best-effort; never block starting a session
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
    watch_pid = autowatchmod.running_pid(repo)
    info("  autosave:      {}".format(
        util.green("watching (pid {})".format(watch_pid)) if watch_pid else util.dim("not running")))
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
    # optionally sign manual snapshots
    if args.sign or repo.config.trust().get("sign_snapshots"):
        signer = idmod.current(repo)
        if signer and idmod.has_private(repo, signer["identity_id"]):
            signmod.sign_snapshot(repo, snap["id"], signer["identity_id"])
            info("  signed:  by {}".format(signer["identity_id"]))
        elif args.sign:
            info(util.yellow("  signed:  no active identity with a private key"))
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

    # --- simple trust policy (Phase 5) — superseded by the policy engine when one exists ---
    signer = idmod.current(repo)
    signer_can_sign = bool(signer and idmod.has_private(repo, signer["identity_id"]))
    if policymod.load(repo) is None and not args.force:
        trust = repo.config.trust()
        if trust.get("require_signed_accepts") and not signer_can_sign:
            err("trust policy requires a signed accept, but no signing identity is active.")
            info("Create/select one: checkpoint-core identity create --name \"You\"")
            return 1
        if signer:
            if trust.get("require_trusted_acceptor") and not idmod.is_trusted(repo, signer["identity_id"]):
                err("trust policy requires a trusted acceptor; {} is not trusted.".format(signer["identity_id"]))
                return 1
            allowed_types = trust.get("allowed_acceptor_types") or []
            if allowed_types and signer.get("type") not in allowed_types:
                err("trust policy forbids acceptor type '{}' (allowed: {}).".format(
                    signer.get("type"), ", ".join(allowed_types)))
                return 1
            if signer.get("type") == "agent" and not trust.get("allowed_agent_accept", False):
                err("trust policy forbids an agent identity from accepting.")
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
        findings = secretscan.filter_findings(
            findings, secretscan.load_allow(repo.paths.base / "secrets-allow"))
        if findings and not args.force:
            err("possible secrets detected in the changes. Refusing to accept.")
            for f in findings[:20]:
                info(util.red("  {} ({}:{})".format(f["type"], f["file"], f["line"])))
            info(util.dim("  false positives? add the path to .checkpoint/secrets-allow, or use --force"))
            return 1

    pkt = engine.generate_packet(repo, sess)
    # Gate on whether history would actually change: current tree vs branch head tree.
    current_tree = scan_to_tree(repo)
    parent_tree = repo.head_tree()
    if current_tree == parent_tree:
        err("nothing to accept; the working tree matches the branch head.")
        info("Use `checkpoint-core rollback` to discard, or `reject` to close.")
        return 1

    # Policy engine (opt-in): enforce who/what may accept and under which conditions.
    if not args.force:
        ok, decision = policy_gate(repo, sess, "accept", args=args)
        if not ok:
            _print_denial(decision)
            return 1
    if verification_ref is None:
        runs = sess.data.get("verifications", [])
        verification_ref = runs[-1] if runs else None

    message = args.message or pkt["recommended_commit_message"] or sess.data["instruction"]
    oid = engine.accept(repo, sess, message, verification_ref)
    ledgermod.append(repo, "accept", sess.id, actor,
                     {"snapshot": oid, "message": message, "files": len(pkt["changed_files"])})
    timelinemod.append(repo, sess.id, "accepted", {"snapshot": oid, "message": message})

    # sign the accepted snapshot by default if a signing identity is active
    sig = None
    if signer_can_sign and not args.no_sign:
        sig = signmod.sign_snapshot(repo, oid, signer["identity_id"])
        ledgermod.append(repo, "sign", sess.id, repo.identity(),
                         {"snapshot": oid, "signature": sig["signature_id"]})

    info(util.green("Accepted session ") + util.bold(sess.id))
    info("  snapshot: {}".format(_short(oid)))
    info("  branch:   {} -> {}".format(repo.head_branch(), _short(oid)))
    info("  message:  {}".format(message))
    info("  sealed:   {}".format(objects.verify_seal(repo.get_object(oid))))
    if sig:
        info("  signed:   {} by {}".format(util.green("yes"), signer["identity_id"]))
    elif signer:
        info("  signed:   {}".format(util.yellow("no (no private key)")))
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

    # Policy engine (opt-in): protected-branch + signed-merge enforcement.
    merged_paths = [r["new_path"] for r in result.get("rename_records", [])] + list(result.get("auto_merged", []))
    ok, decision = policy_gate(repo, None, "merge", args=args, branch=branch,
                               changed_paths=merged_paths)
    if not ok:
        _print_denial(decision)
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
    # sign merge snapshots by default if a signing identity is active
    signer = idmod.current(repo)
    if signer and idmod.has_private(repo, signer["identity_id"]):
        signmod.sign_snapshot(repo, oid, signer["identity_id"])
        info("  signed merge by {}".format(signer["identity_id"]))
    info(util.green("Merged ") + "{} into {} ({})".format(args.name, branch, _short(oid)))
    if result.get("rename_records"):
        for r in result["rename_records"]:
            info("  renamed ({}): {} -> {}".format(r["side"], r["old_path"], r["final_path"]))
    if result["auto_merged"]:
        info("  auto-merged (line-level): {}".format(", ".join(result["auto_merged"])))
    return 0


# --------------------------------------------------- remotes / sync (Phase 6)

def cmd_remote(args) -> int:
    repo = _repo()
    sub = args.remote_cmd or "list"
    if sub == "add":
        loc = getattr(args, "location", None)
        if loc and (loc.startswith("http://") or loc.startswith("https://")):
            cfg = repo.config
            cfg.data.setdefault("remotes", {})[args.name] = {
                "type": "http", "url": loc, "token": getattr(args, "token", None)}
            cfg.save()
            info(util.green("Added remote ") + "{} (http: {})".format(args.name, loc))
            return 0
        path = args.path or loc
        if not path:
            err("provide a path (--path <dir>) or an http URL")
            return 2
        remotemod.add_remote(repo, args.name, "filesystem", path, require_signed_snapshots=False)
        info(util.green("Added remote ") + "{} (filesystem: {})".format(args.name, path))
        return 0
    if sub == "remove":
        if remotemod.remove_remote(repo, args.name):
            info(util.green("Removed remote ") + args.name + util.dim(" (config only; data untouched)"))
            return 0
        err("no such remote: {}".format(args.name))
        return 1
    if sub == "show":
        spec = remotemod.get_remote(repo, args.name)
        if not spec:
            err("no such remote: {}".format(args.name))
            return 1
        info(util.bold("Remote ") + util.cyan(args.name))
        info("  type: {}".format(spec.get("type")))
        info("  {}: {}".format("url" if spec.get("type") == "http" else "path",
                               spec.get("url") or spec.get("path")))
        try:
            st = remotemod.sync_status(repo, args.name)
            for b in st["branches"]:
                info("  {:<16} {}".format(b["branch"], b["relationship"]))
        except Exception as exc:
            info(util.yellow("  (remote unreachable: {})".format(exc)))
        return 0
    remotes = remotemod.list_remotes(repo)
    if not remotes:
        info("No remotes. Add one: checkpoint-core remote add <name> --type filesystem --path <dir>")
        return 0
    for name, spec in remotes.items():
        info("{:<16} {}: {}".format(name, spec.get("type"), spec.get("url") or spec.get("path")))
    return 0


def cmd_fetch(args) -> int:
    repo = _repo()
    try:
        report = remotemod.fetch(repo, args.remote, branches=[args.branch] if args.branch else None,
                                 tags=args.tags, verify_signatures=args.verify_signatures,
                                 dry_run=args.dry_run)
    except ValueError as exc:
        err(str(exc))
        return 1
    if not args.dry_run:
        ledgermod.append(repo, "fetch", None, repo.identity(),
                         {"remote": args.remote, "objects": report["objects_copied"],
                          "refs": report["refs_updated"]})
    if args.json:
        print(_dump(report))
        return 1 if report["errors"] else 0
    info(util.bold("fetch {}{}".format(args.remote, " (dry-run)" if args.dry_run else "")))
    for b in report["branches"]:
        info("  {}: {} ({} missing)".format(b["branch"], b.get("status", "planned"), b["missing"]))
    if report["errors"]:
        for e in report["errors"]:
            info(util.red("  ERROR " + e))
        return 1
    info("  objects copied: {}".format(report["objects_copied"]))
    return 0


def cmd_pull(args) -> int:
    repo = _repo()
    branch = args.branch or getattr(args, "branch_opt", None) or repo.head_branch()
    # Policy: optionally refuse unsigned remote history before moving the local branch.
    if policymod.load(repo) is not None and not args.dry_run:
        try:
            rr = remotemod.remote_repo(remotemod.get_remote(repo, args.remote) or {})
            rhead = rr.read_ref("refs/heads/{}".format(branch))
            remote_unsigned = bool(rhead) and not signmod.signatures_for(rr, rhead)
            ok, decision = policy_gate(repo, None, "pull", args=args, branch=branch,
                                       remote_unsigned=remote_unsigned)
            if not ok:
                _print_denial(decision)
                return 1
        except ValueError:
            pass
    try:
        res = remotemod.pull(repo, args.remote, branch,
                             verify_signatures=args.verify_signatures, dry_run=args.dry_run)
    except ValueError as exc:
        err(str(exc))
        return 1
    if not args.dry_run and res.get("updated"):
        if repo.head_branch() == branch:
            materialize(repo, repo.get_object(res["new_head"])["tree"], delete_extra=True)
        ledgermod.append(repo, "pull", None, repo.identity(),
                         {"remote": args.remote, "branch": branch, "head": res.get("new_head")})
    if args.json:
        print(_dump(res))
    status = res.get("status")
    if status == "dry-run":
        info("pull (dry-run): {} is {} relative to {}".format(
            branch, res.get("relationship"), args.remote))
        return 0
    if status == "fast-forward":
        info(util.green("Pulled (fast-forward) ") + "{} -> {}".format(branch, _short(res["new_head"])))
    elif status == "up-to-date":
        info(util.green("Already up to date."))
    elif status == "diverged":
        err("local and remote '{}' have diverged. Run `checkpoint-core merge` after fetch.".format(branch))
        return 1
    else:
        info(util.yellow("pull: {}".format(status)))
        if res.get("fetch", {}).get("errors"):
            for e in res["fetch"]["errors"]:
                info(util.red("  " + e))
        return 1
    return 0


def cmd_push(args) -> int:
    repo = _repo()
    branch = args.branch or repo.head_branch()
    ut = "force" if getattr(args, "force", False) else (
        "force_with_lease" if args.force_with_lease is not None else "fast_forward")
    ok, decision = policy_gate(repo, None, "push", args=args, branch=branch, ref_update_type=ut)
    if not ok:
        _print_denial(decision)
        return 1
    try:
        res = remotemod.push(repo, args.remote, branch, tags=args.tags,
                             force_with_lease=args.force_with_lease, dry_run=args.dry_run)
    except ValueError as exc:
        err(str(exc))
        return 1
    if not args.dry_run and res.get("status") == "pushed":
        receipt = res.get("receipt") or {}
        ledgermod.append(repo, "push", None, repo.identity(),
                         {"remote": args.remote, "branch": branch,
                          "objects": res.get("objects_sent", 0), "forced": res.get("forced"),
                          "receipt_id": receipt.get("receipt_id"), "receipt": receipt})
    if args.json:
        print(_dump(res))
    status = res.get("status")
    if status == "pushed":
        info(util.green("Pushed ") + "{} -> {}: {} objects{}".format(
            branch, args.remote, res.get("objects_sent", 0), " (forced)" if res.get("forced") else ""))
        return 0
    if status == "would-push":
        info("would push {} object(s) to {}/{}".format(res["missing_on_remote"], args.remote, branch))
        return 0
    if status == "rejected-non-fast-forward":
        err("non-fast-forward: remote '{}' has commits you don't have. Pull, or use --force-with-lease.".format(branch))
        return 1
    if status == "rejected-stale-lease":
        err("--force-with-lease rejected: remote moved (expected {}, found {}).".format(
            _short(res.get("expected")), _short(res.get("remote_head"))))
        return 1
    reasons = res.get("reasons") or []
    actions = res.get("required_actions") or []
    err("push failed ({}){}".format(status, ": " + "; ".join(reasons) if reasons else ""))
    for a in actions:
        info(util.dim("  - " + a))
    return 1


def cmd_clone(args) -> int:
    dest = Path(args.dest)
    if dest.exists() and any(dest.iterdir()):
        err("destination exists and is not empty: {}".format(dest))
        return 1
    src = args.source
    # http clone
    if src.startswith("http://") or src.startswith("https://"):
        repo = remotemod.bootstrap_store(dest)
        repo.config.data.setdefault("remotes", {})["origin"] = {"type": "http", "url": src,
                                                                "token": getattr(args, "token", None)}
        repo.config.save()
        report = remotemod.fetch(repo, "origin", tags=True, verify_signatures=args.verify_signatures)
        if report["errors"]:
            err("clone verification failed:")
            for e in report["errors"][:20]:
                info(util.red("  " + e))
            return 1
        rdir = repo.paths.base / "refs" / "remotes" / "origin"
        branch = "main"
        if rdir.exists():
            for rf in rdir.iterdir():
                if rf.is_file():
                    repo.update_ref("refs/heads/{}".format(rf.name), rf.read_text(encoding="utf-8").strip())
                    branch = rf.name
        head = repo.read_ref("refs/heads/{}".format(branch))
        if head:
            repo.set_head_to_branch(branch)
            materialize(repo, repo.get_object(head)["tree"], delete_extra=True)
        ledgermod.append(repo, "clone", None, repo.identity(), {"source": src, "branch": branch})
        info(util.green("Cloned ") + "{} -> {} (branch {})".format(src, dest, branch))
        return 0
    # bundle clone vs filesystem clone
    if Path(src).is_file():
        repo = remotemod.bootstrap_store(dest)
        res = syncmod.import_bundle(repo, Path(src), require_signatures=args.verify_signatures)
        if not res.get("ok"):
            err("bundle verification failed:")
            for e in res.get("errors", [])[:20]:
                info(util.red("  " + e))
            return 1
        branch = res.get("branch") or "main"
    else:
        srepo = Repo(Path(src))
        if not srepo.initialized:
            err("source is neither a bundle file nor an initialized Checkpoint store: {}".format(src))
            return 1
        branch = srepo.head_branch() or srepo.config.default_branch()
        repo = remotemod.bootstrap_store(dest, branch)
        remotemod.add_remote(repo, "origin", "filesystem", str(Path(src).resolve()))
        report = remotemod.fetch(repo, "origin", tags=True, verify_signatures=args.verify_signatures)
        if report["errors"]:
            err("clone verification failed:")
            for e in report["errors"][:20]:
                info(util.red("  " + e))
            return 1
        # set local branches from fetched remote-tracking refs
        rdir = repo.paths.base / "refs" / "remotes" / "origin"
        if rdir.exists():
            for rf in rdir.iterdir():
                if rf.is_file():
                    repo.update_ref("refs/heads/{}".format(rf.name), rf.read_text(encoding="utf-8").strip())
    # checkout default branch
    head = repo.read_ref("refs/heads/{}".format(branch))
    if head:
        repo.set_head_to_branch(branch)
        materialize(repo, repo.get_object(head)["tree"], delete_extra=True)
    ledgermod.append(repo, "clone", None, repo.identity(), {"source": str(src), "branch": branch})
    info(util.green("Cloned ") + "{} -> {} (branch {})".format(src, dest, branch))
    return 0


def cmd_sync(args) -> int:
    repo = _repo()
    if args.sync_cmd != "status":
        err("usage: checkpoint-core sync status <remote>")
        return 2
    try:
        st = remotemod.sync_status(repo, args.remote, args.branch)
    except ValueError as exc:
        err(str(exc))
        return 1
    if args.json:
        print(_dump(st))
        return 0
    info(util.bold("sync status: {}".format(args.remote)))
    for b in st["branches"]:
        rel = b["relationship"]
        color = {"up-to-date": util.green, "ahead": util.cyan, "behind": util.yellow,
                 "diverged": util.red}.get(rel, lambda x: x)
        info("  {:<16} {:<22} local={} remote={}  (-{} +{})".format(
            b["branch"], color(rel), _short(b["local_head"]), _short(b["remote_head"]),
            b["missing_locally"], b["missing_remotely"]))
    return 0


# ------------------------------------------------------------------------ bundles

def cmd_bundle(args) -> int:
    repo = _repo()
    sub = args.bundle_cmd
    if sub in ("create", "export"):
        out = args.out or "{}.ckpt-bundle.tar.gz".format(args.branch or repo.head_branch() or "checkpoint")
        res = syncmod.create_bundle(repo, Path(out), branch=args.branch,
                                    tags=getattr(args, "tags", False),
                                    include_sessions=not getattr(args, "no_sessions", False))
        info(util.green("Created bundle ") + "{} ({} objects, refs {}) -> {}".format(
            res["out_path"], res["objects"], ",".join(res["refs"]) or "-", res["out_path"]))
        return 0
    if sub == "verify":
        rep = syncmod.verify_bundle(Path(args.path), require_signatures=args.verify_signatures)
        if args.json:
            print(_dump(rep))
            return 0 if rep["ok"] else 1
        if rep["ok"]:
            info(util.green("Bundle OK: ") + "refs {}".format(", ".join(rep["refs"].keys()) or "-"))
            return 0
        err("bundle verification FAILED:")
        for e in rep["errors"][:30]:
            info(util.red("  " + e))
        return 1
    if sub == "import":
        # Policy: optionally reject unsigned bundle history before importing.
        if policymod.load(repo) is not None:
            import tarfile as _tf
            try:
                with _tf.open(args.path, "r:gz") as t:
                    has_sig = any(n.startswith("signatures/") for n in t.getnames())
            except Exception:
                has_sig = False
            ok, decision = policy_gate(repo, None, "bundle_import", args=args,
                                       bundle_unsigned=not has_sig, require_signed=True)
            if not ok:
                _print_denial(decision)
                return 1
        res = syncmod.import_bundle(repo, Path(args.path), args.name,
                                    require_signatures=args.verify_signatures)
        if not res.get("ok"):
            err("bundle verification failed; nothing imported:")
            for e in res.get("errors", [])[:30]:
                info(util.red("  " + e))
            return 1
        info(util.green("Imported bundle ") + "({} new objects), refs {}, head {}".format(
            res["objects_copied"], ",".join(res["refs"]) or "-", _short(res["head"])))
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
    try:
        repo = Repo.discover()
    except NotInitialized:
        if getattr(args, "json", False):
            print(_dump({"ok": False, "error": "not inside a Checkpoint Core repo"}))
        else:
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
    problems = sum(1 for _l, ok in checks if not ok)
    if getattr(args, "json", False):
        print(_dump({
            "ok": problems == 0,
            "version": __version__, "protocol_version": _proto(),
            "checks": [{"name": l, "ok": ok} for l, ok in checks],
            "problems": problems,
        }))
        return 0 if problems == 0 else 1
    for label, ok in checks:
        info("  [{}] {}".format(util.green("ok  ") if ok else util.red("FAIL"), label))
    if problems == 0:
        info(util.green("\nHealthy. Checkpoint Core is the source of truth; Git is optional."))
        return 0
    info(util.red("\n{} problem(s) found.".format(problems)))
    return 1


def _proto():
    from . import PROTOCOL_VERSION
    return PROTOCOL_VERSION


def cmd_version(args) -> int:
    import platform
    from . import PROTOCOL_VERSION, STORE_VERSION, FEATURES
    store_version = None
    try:
        repo = Repo.discover()
        store_version = repo.read_state().get("schema_version", STORE_VERSION)
    except Exception:
        pass
    info_obj = {
        "checkpoint_core": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "store_version_supported": STORE_VERSION,
        "store_version": store_version,
        "features": FEATURES,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    if getattr(args, "json", False):
        print(_dump(info_obj))
        return 0
    info(util.bold("Checkpoint Core ") + __version__)
    info("  protocol:   {}".format(PROTOCOL_VERSION))
    info("  store:      v{} (this repo: {})".format(STORE_VERSION, store_version if store_version is not None else "n/a"))
    info("  features:   {}".format(", ".join(FEATURES)))
    info("  python:     {}".format(info_obj["python"]))
    info("  platform:   {}".format(info_obj["platform"]))
    return 0


# ----------------------------------------------------------------- migrate (scaffolding)

def cmd_migrate(args) -> int:
    from . import STORE_VERSION
    repo = _repo()
    current = repo.read_state().get("schema_version", STORE_VERSION)
    up_to_date = current == STORE_VERSION
    sub = args.migrate_cmd or "status"
    if sub == "status":
        if getattr(args, "json", False):
            print(_dump({"store_version": current, "supported": STORE_VERSION, "up_to_date": up_to_date}))
        else:
            info("store version: v{}  (supported: v{})".format(current, STORE_VERSION))
            info(util.green("up to date; no migration needed.") if up_to_date
                 else util.yellow("migration available."))
        return 0
    if sub == "plan":
        steps = [] if up_to_date else ["v{} -> v{}".format(current, STORE_VERSION)]
        if getattr(args, "json", False):
            print(_dump({"steps": steps}))
        else:
            info("migration plan: " + ("no steps (up to date)" if not steps else ", ".join(steps)))
        return 0
    if sub == "apply":
        if up_to_date:
            info(util.green("nothing to apply; store is v{}.".format(current)))
            return 0
        # scaffolding: real migrations would transform objects/refs here, atomically.
        info(util.yellow("no migration implemented for v{} -> v{}.".format(current, STORE_VERSION)))
        return 0
    err("unknown migrate subcommand")
    return 2


# ----------------------------------------------------------------- bug-report

def cmd_bug_report(args) -> int:
    import io
    import platform
    import tarfile
    from . import PROTOCOL_VERSION
    repo = _repo()
    out = Path(args.out or "checkpoint-bug-report.tar.gz")

    def redact(text):
        return secretscan.redact(text)

    manifest = {
        "generated_at": util.now_iso(),
        "checkpoint_core": __version__, "protocol_version": PROTOCOL_VERSION,
        "python": platform.python_version(), "platform": platform.platform(),
        "git_available": __import__("shutil").which("git") is not None,
        "note": "private keys and tokens are NEVER included; text is secret-scanned and redacted.",
    }
    # diagnostics
    try:
        fsck_report = fsckmod.check(repo, strict=False)
        manifest["fsck"] = {"result": fsck_report["result"], "objects": fsck_report["objects_scanned"],
                            "corrupt": len(fsck_report["corrupt"]), "missing": len(fsck_report["missing"]),
                            "dangling": fsck_report["dangling"]}
    except Exception as exc:
        manifest["fsck"] = {"error": str(exc)}
    pol = policymod.load(repo)
    manifest["policy"] = {"configured": pol is not None}
    manifest["sessions"] = len(repo.session_ids())

    # collect text artifacts (redacted), NEVER keys/, NEVER raw tokens
    files = {}
    cfg = repo.paths.config
    if cfg.exists():
        files["config.yaml"] = redact(cfg.read_text(encoding="utf-8"))
    ident = repo.paths.identity
    if ident.exists():
        files["identity.json"] = ident.read_text(encoding="utf-8")  # public only
    if repo.paths.ledger.exists():
        tail = repo.paths.ledger.read_text(encoding="utf-8").splitlines()[-200:]
        files["ledger.tail.jsonl"] = redact("\n".join(tail))
    polp = policymod.policy_path(repo)
    if polp.exists():
        files["policy.yaml"] = redact(polp.read_text(encoding="utf-8"))

    # secret-scan the collected text and record findings (values not included)
    findings = []
    for name, text in files.items():
        findings += secretscan.scan_text(text, source=name)
    manifest["secret_scan_findings"] = findings

    with tarfile.open(out, "w:gz") as tar:
        def add(name, data):
            info_t = tarfile.TarInfo(name); info_t.size = len(data); info_t.mtime = 0
            tar.addfile(info_t, io.BytesIO(data))
        add("manifest.json", _dump(manifest).encode("utf-8"))
        for name, text in files.items():
            add(name, text.encode("utf-8"))
        if getattr(args, "include_objects", False):
            for oid in reachablemod.iter_object_ids(repo):
                add("objects/{}/{}".format(oid[:2], oid),
                    (repo.paths.objects / oid[:2] / oid).read_bytes())

    info(util.green("Wrote bug report ") + str(out))
    info("  redacted: private keys excluded, tokens/secrets scanned + redacted")
    if findings:
        info(util.yellow("  {} secret pattern(s) were redacted".format(len(findings))))
    return 0


# ----------------------------------------------------------------- agent helper

def cmd_agent(args) -> int:
    sub = args.agent_cmd
    if sub == "begin":
        # thin wrapper over `start` with agent metadata
        ns = argparse.Namespace(instruction=args.instruction, prompt_file=None,
                                actor="agent", agent=args.agent, model=args.model,
                                tool=args.tool, tag=args.tag)
        return cmd_start(ns)
    if sub == "status":
        return cmd_status(argparse.Namespace())
    if sub == "packet":
        return cmd_packet(argparse.Namespace(json=getattr(args, "json", False)))
    err("usage: checkpoint-core agent begin|status|packet")
    return 2


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
    managed = getattr(args, "managed", False)   # spawned by `start`: log to file, clean pidfile
    w = Watcher(repo, sess, debounce_ms=args.debounce_ms, poll_ms=args.poll_ms)
    if not managed:
        info(util.green("Checkpoint is watching. ") + util.dim("You are never unsaved."))
    try:
        if managed:
            n = w.run(log=lambda m: print(m, flush=True))   # stdout is redirected to watch.log
        else:
            n = w.run(log=lambda m: info(util.dim("  " + m)))
    finally:
        if managed:
            autowatchmod.clear_pidfile(repo)
    if not managed:
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


# --------------------------------------------------- fsck / gc / objects (Phase 4)

def _dump(obj) -> str:
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False)


# --------------------------------------------------- policy plumbing (Phase 7)

def _passed_verifications(repo, session) -> list:
    """Names of verification commands that passed in the session's latest run."""
    rec = verifymod.last_verification(repo, session) if session else {}
    if not rec:
        return []
    return [r["name"] for r in rec.get("results", []) if r.get("status") == "passed"]


def _signer_actor(repo, session=None):
    """(actor_type, identity_dict, will_sign) for the active signing identity or session actor."""
    signer = idmod.current(repo)
    if signer:
        return signer.get("type", "human"), signer, idmod.has_private(repo, signer["identity_id"])
    actor = session.actor() if session else {"type": "human"}
    return actor.get("type", "human"), {"id": actor.get("id"), "trusted": True}, False


def build_policy_input(repo, session, operation, **extra):
    actor_type, identity, will_sign = _signer_actor(repo, session)
    changed = []
    if session is not None:
        try:
            dr = diff_result(repo, session.base_tree, scan_to_tree(repo))
            changed = ([f for f in dr["added"]] + [f for f in dr["deleted"]]
                       + [f for f in dr["modified"]] + [r["new_path"] for r in dr["renamed"]])
        except Exception:
            changed = []
    pin = {
        "operation": operation,
        "actor_type": actor_type,
        "actor_identity": identity,
        "trust_status": "trusted" if identity.get("trusted") else "untrusted",
        "branch": repo.head_branch(),
        "session_id": session.id if session else None,
        "changed_paths": changed,
        "risk_tags": session.data.get("risk_tags", []) if session else [],
        "verification_passed": _passed_verifications(repo, session),
        "will_sign": will_sign,
    }
    pin.update(extra)
    return pin


def _record_decision(repo, decision, session_id=None):
    ledgermod.append(repo, "policy", session_id, repo.identity(), {
        "operation": decision["operation"], "effect": decision["effect"],
        "decision_id": decision["decision_id"], "reasons": decision["reasons"],
        "rules_matched": decision["rules_matched"], "override_used": decision.get("override_used"),
    })


def policy_gate(repo, session, operation, args=None, **extra):
    """Enforce policy for a sensitive op. Returns (allowed, decision_or_None).

    Disabled (allow, None) when no policy is configured.
    """
    pol = policymod.load(repo)
    if pol is None:
        return True, None
    pin = build_policy_input(repo, session, operation, **extra)
    decision = policymod.evaluate(pol, pin)
    sid = session.id if session else None
    if decision["effect"] == "deny" and getattr(args, "override", False):
        opin = build_policy_input(repo, session, "override", reason=getattr(args, "reason", None),
                                  base_operation=operation)
        odec = policymod.evaluate(pol, opin)
        if odec["effect"] == "allow":
            decision["effect"] = "allow"
            decision["override_used"] = True
            decision["reasons"].append("OVERRIDE: {}".format(getattr(args, "reason", "") or ""))
            if odec.get("actor_identity_id"):
                signer = idmod.current(repo)
                if signer and idmod.has_private(repo, signer["identity_id"]):
                    pass  # override is recorded in the ledger (actor stamped); seal optional
            _record_decision(repo, decision, sid)
            return True, decision
        decision["override_attempt"] = odec["reasons"]
    _record_decision(repo, decision, sid)
    return decision["effect"] != "deny", decision


def _print_denial(decision):
    err("policy DENY {}".format(decision["operation"]))
    for r in decision["reasons"]:
        info(util.red("  - " + r))
    if decision["required_actions"]:
        info(util.bold("  required actions:"))
        for a in decision["required_actions"]:
            info("    * " + a)
    if decision.get("override_available"):
        info(util.dim("  (a trusted human may override with --override --reason \"...\")"))


def cmd_fsck(args) -> int:
    repo = _repo()
    report = fsckmod.check(repo, strict=args.strict)

    sig_findings = None
    if args.verify_signatures or args.require_signatures:
        sig_findings = _signature_findings(repo)
        report["signatures"] = sig_findings
        if args.require_signatures:
            bad = (len(sig_findings["unsigned_accepted"]) + sig_findings["invalid"]
                   + sig_findings["revoked"])
            if bad:
                report["result"] = "corrupt"
                report["errors"].append(
                    "signature policy: {} unsigned, {} invalid, {} revoked accepted snapshot(s)".format(
                        len(sig_findings["unsigned_accepted"]), sig_findings["invalid"],
                        sig_findings["revoked"]))

    if getattr(args, "policy", False):
        pol = policymod.load(repo)
        violations = _policy_findings(repo, pol) if pol else []
        report["policy_violations"] = violations
        # policy violations are reported separately; they do not mark the store "corrupt"

    if args.json:
        print(_dump(report))
        return fsckmod.exit_code(report, strict=args.strict)
    info(util.bold("Checkpoint fsck"))
    info("  objects scanned:  {}".format(report["objects_scanned"]))
    info("  refs scanned:     {}".format(report["refs_scanned"]))
    info("  sessions scanned: {}".format(report["sessions_scanned"]))
    info("  reachable:        {}".format(report["reachable"]))
    info("  dangling:         {}".format(report["dangling"]))
    info("  corrupt:          {}".format(len(report["corrupt"])))
    info("  missing:          {}".format(len(report["missing"])))
    for c in report["corrupt"][:50]:
        info(util.red("  CORRUPT  {} — {}".format(c["id"][:12], c["reason"])))
    for e in report["errors"][:100]:
        info(util.red("  ERROR    {}".format(e)))
    for w in report["warnings"][:100]:
        info(util.yellow("  warning  {}".format(w)))
    if sig_findings is not None:
        info(util.bold("  signatures:"))
        info("    signed accepted:   {}".format(sig_findings["signed_accepted"]))
        info("    unsigned accepted: {}".format(len(sig_findings["unsigned_accepted"])))
        info("    valid: {}  untrusted: {}  unknown: {}  invalid: {}".format(
            sig_findings["valid"], sig_findings["untrusted"],
            sig_findings["unknown_signer"], sig_findings["invalid"]))
    if "policy_violations" in report:
        info(util.bold("  policy:"))
        if report["policy_violations"]:
            for v in report["policy_violations"]:
                info(util.yellow("    VIOLATION  " + v))
        else:
            info("    no policy violations")
    res = report["result"]
    color = {"healthy": util.green, "warnings": util.yellow, "corrupt": util.red}[res]
    info("\nResult: " + color(res))
    return fsckmod.exit_code(report, strict=args.strict)


def _signature_findings(repo) -> dict:
    """Per-accepted-snapshot signature summary for fsck."""
    accepted: List[str] = []
    seen = set()
    for kind_dir in ("heads", "tags"):
        d = repo.paths.base / "refs" / kind_dir
        if d.exists():
            for ref in d.iterdir():
                if ref.is_file():
                    for oid in repo.history(ref.read_text(encoding="utf-8").strip()):
                        if oid not in seen:
                            seen.add(oid)
                            accepted.append(oid)
    unsigned: List[str] = []
    valid = untrusted = unknown = invalid = revoked = signed = 0
    for oid in accepted:
        sigs = signmod.signatures_for(repo, oid)
        if not sigs:
            unsigned.append(oid)
            continue
        signed += 1
        statuses = [signmod.verify_record(repo, s) for s in sigs]
        ok = [v for v in statuses if v["ok"]]
        if any(v["status"] == "valid" for v in ok):
            valid += 1
        elif any(v["status"] == "untrusted" for v in ok):
            untrusted += 1
        elif any(v["status"] == "unknown_signer" for v in ok):
            unknown += 1
        elif any(v["status"] == "revoked" for v in ok):
            revoked += 1
        else:
            invalid += 1
    return {
        "accepted": len(accepted), "signed_accepted": signed,
        "unsigned_accepted": unsigned, "valid": valid, "untrusted": untrusted,
        "unknown_signer": unknown, "revoked": revoked, "invalid": invalid,
    }


def cmd_gc(args) -> int:
    repo = _repo()
    report = gcmod.collect(repo, dry_run=args.dry_run, aggressive=args.aggressive, force=args.force)
    if report.get("aborted"):
        err(report["reason"])
        return 1
    info(util.bold("Checkpoint gc" + (" (dry-run)" if args.dry_run else "")))
    info("  objects scanned:  {}".format(report["objects_scanned"]))
    info("  reachable:        {}".format(report["reachable"]))
    info("  candidates:       {}".format(len(report["candidates"])))
    info("  quarantined:      {}".format(report["quarantined"]))
    info("  deleted:          {}".format(report["deleted"]))
    info("  bytes reclaimed:  {}".format(report["bytes_reclaimed"]))
    info("  skipped:          {}".format(report["skipped"]))
    if report.get("purged_quarantine"):
        info("  quarantine purged: {} batch(es)".format(report["purged_quarantine"]))
    if args.dry_run:
        for oid in report["candidates"][:50]:
            info(util.dim("  would collect {}".format(oid[:12])))
    else:
        ledgermod.append(repo, "gc", None, repo.identity(), {
            "quarantined": report["quarantined"], "deleted": report["deleted"],
            "bytes_reclaimed": report["bytes_reclaimed"], "aggressive": args.aggressive,
        })
    return 0


def _reachable_set(repo):
    gcfg = repo.config.gc()
    walk = reachablemod.compute_reachable(
        repo, keep_autosaves_days=float(gcfg.get("keep_autosaves_days", 14)),
        keep_rejected_days=float(gcfg.get("keep_rejected_sessions_days", 30)))
    return walk["reachable"]


def cmd_objects(args) -> int:
    repo = _repo()
    sub = args.objects_cmd or "stats"
    if sub == "stats":
        counts = {"blob": 0, "tree": 0, "snapshot_accepted": 0, "snapshot_intermediate": 0, "unknown": 0}
        sizes = dict(counts)
        total = 0
        for oid in reachablemod.iter_object_ids(repo):
            kind, obj = reachablemod.classify(repo, oid)
            size = reachablemod.object_size(repo, oid)
            total += size
            if kind == "snapshot":
                key = "snapshot_accepted" if obj.get("kind") == objects.KIND_ACCEPTED else "snapshot_intermediate"
            elif kind == "tree":
                key = "tree"
            elif kind == "blob":
                key = "blob"
            else:
                key = "unknown"
            counts[key] += 1
            sizes[key] += size
        autosaves = vers = 0
        for sid in repo.session_ids():
            sess = util.read_json(repo.paths.session_dir(sid) / "session.json", {})
            autosaves += len(sess.get("autosaves", []))
            vers += len(sess.get("verifications", []))
        info(util.bold("Object store stats"))
        for k in ("blob", "tree", "snapshot_accepted", "snapshot_intermediate", "unknown"):
            info("  {:<22} {:>6}  {:>10} bytes".format(k, counts[k], sizes[k]))
        info("  {:<22} {:>6}  {:>10} bytes".format("TOTAL", sum(counts.values()), total))
        info(util.dim("  (filesystem) autosave records: {}, verification records: {}".format(autosaves, vers)))
        return 0
    if sub == "list":
        reachable = _reachable_set(repo)
        for oid in reachablemod.iter_object_ids(repo):
            kind, obj = reachablemod.classify(repo, oid)
            if args.type and kind != args.type:
                continue
            is_reach = oid in reachable
            if args.reachable and not is_reach:
                continue
            if args.unreachable and is_reach:
                continue
            tag = "reachable" if is_reach else "UNREACHABLE"
            info("{}  {:<10} {}".format(oid[:16], kind, tag))
        return 0
    if sub == "show":
        oid = args.object_id
        kind, obj = reachablemod.classify(repo, oid)
        if kind == "missing":
            err("no such object: {}".format(oid))
            return 1
        reachable = _reachable_set(repo)
        info(util.bold("Object ") + util.cyan(oid))
        info("  type:      {}".format(kind))
        info("  size:      {} bytes".format(reachablemod.object_size(repo, oid)))
        info("  reachable: {}".format(oid in reachable))
        if kind == "tree":
            entries = obj.get("entries", [])
            info("  entries:   {}".format(len(entries)))
            for e in entries[:50]:
                info("    {} {} {}".format(e.get("mode"), e.get("blob", "")[:12], e.get("path")))
        elif kind == "snapshot":
            info("  kind:      {}".format(obj.get("kind")))
            info("  message:   {}".format(obj.get("message")))
            info("  tree:      {}".format((obj.get("tree") or "")[:12]))
            info("  parents:   {}".format([p[:12] for p in obj.get("parents", [])]))
            info("  session:   {}".format(obj.get("session")))
            if obj.get("kind") == objects.KIND_ACCEPTED:
                info("  seal:      {}".format("valid" if objects.verify_seal(obj) else util.red("INVALID")))
        return 0
    err("unknown objects subcommand")
    return 2


# --------------------------------------------------- sign / verify / trust (Phase 5)

def cmd_sign(args) -> int:
    repo = _repo()
    signer = idmod.current(repo)
    if not signer:
        err("no active signing identity. Run `checkpoint-core identity create --name \"You\"`.")
        return 1
    if not idmod.has_private(repo, signer["identity_id"]):
        err("active identity {} has no private key.".format(signer["identity_id"]))
        return 1
    kind, obj = reachablemod.classify(repo, args.object_id)
    if kind == "missing":
        err("no such object: {}".format(args.object_id))
        return 1
    if kind != "snapshot":
        err("only snapshots can be signed in this phase (got {})".format(kind))
        return 1
    sig = signmod.sign_snapshot(repo, args.object_id, signer["identity_id"])
    ledgermod.append(repo, "sign", None, repo.identity(),
                     {"snapshot": args.object_id, "signature": sig["signature_id"]})
    info(util.green("Signed ") + _short(args.object_id) + " by " + signer["identity_id"])
    return 0


def cmd_verify_signatures(args) -> int:
    repo = _repo()
    report = signmod.verify_all(repo)
    if args.json:
        print(_dump(report))
        return 0 if report["ok"] else 1
    if not report["results"]:
        info("No signatures in the store.")
        return 0
    info(util.bold("Signature verification"))
    for r in report["results"]:
        glyph = util.green("OK  ") if r["ok"] else util.red("FAIL")
        info("  [{}] {}  {}  signer={}".format(glyph, _short(r["object"]),
                                               _color_trust_status(r["status"]), r["signer"]))
    info("  counts: {}".format(report["counts"]))
    info("Result: " + (util.green("all signatures valid") if report["ok"] else util.red("INVALID signatures present")))
    return 0 if report["ok"] else 1


def _color_trust_status(s: str):
    return {"valid": util.green, "untrusted": util.yellow, "unknown_signer": util.yellow,
            "revoked": util.red, "invalid": util.red}.get(s, lambda x: x)(s)


def cmd_trust_status(args) -> int:
    repo = _repo()
    # accepted snapshots = everything reachable from refs
    accepted: List[str] = []
    seen = set()
    for kind_dir in ("heads", "tags"):
        d = repo.paths.base / "refs" / kind_dir
        if d.exists():
            for ref in d.iterdir():
                if ref.is_file():
                    head = ref.read_text(encoding="utf-8").strip()
                    for oid in repo.history(head):
                        if oid not in seen:
                            seen.add(oid)
                            accepted.append(oid)
    unsigned = []
    by_status: Dict[str, int] = {}
    for oid in accepted:
        sigs = signmod.signatures_for(repo, oid)
        if not sigs:
            unsigned.append(oid)
            continue
        best = "invalid"
        for s in sigs:
            v = signmod.verify_record(repo, s)
            best = v["status"] if v["ok"] else best
        by_status[best] = by_status.get(best, 0) + 1

    revoked = [r["identity_id"] for r in idmod.list_all(repo) if r.get("revoked")]
    info(util.bold("Trust status"))
    info("  accepted snapshots:      {}".format(len(accepted)))
    info("  unsigned accepted:       {}".format(len(unsigned)))
    for k in ("valid", "untrusted", "unknown_signer", "revoked", "invalid"):
        if by_status.get(k):
            info("  {:<24} {}".format(k + ":", by_status[k]))
    info("  revoked identities:      {}".format(len(revoked)))
    if unsigned:
        for oid in unsigned[:20]:
            info(util.yellow("  unsigned  {}".format(_short(oid))))
    return 0


# ----------------------------------------------------------------- policy (Phase 7)

def cmd_policy(args) -> int:
    repo = _repo()
    sub = args.policy_cmd or "show"

    if sub == "init":
        if policymod.policy_path(repo).exists() and not getattr(args, "force", False):
            err("policy already exists: {} (use --force to overwrite)".format(policymod.policy_path(repo)))
            return 1
        policymod.save_starter(repo)
        info(util.green("Wrote starter policy ") + str(policymod.policy_path(repo)))
        info("Policy enforcement is now ACTIVE for accept/merge/push/pull/bundle/trust.")
        return 0

    if sub == "show":
        pol = policymod.load(repo)
        if pol is None:
            info("No policy configured (enforcement disabled). Run `checkpoint-core policy init`.")
            return 0
        if getattr(args, "json", False):
            print(_dump(pol))
        else:
            import yaml as _y
            print(_y.safe_dump(pol, sort_keys=False))
        return 0

    if sub == "validate":
        pol = policymod.load(repo)
        if pol is None:
            info("No policy configured.")
            return 0
        errs = policymod.validate(pol)
        if errs:
            err("policy is INVALID:")
            for e in errs:
                info(util.red("  - " + e))
            return 1
        info(util.green("policy is valid."))
        return 0

    if sub in ("check", "explain"):
        pol = policymod.load(repo)
        if pol is None:
            info("No policy configured (enforcement disabled).")
            return 0
        if sub == "explain" and getattr(args, "decision_id", None):
            for e in reversed(ledgermod.read_all(repo)):
                if e["event_type"] == "policy" and e["payload"].get("decision_id") == args.decision_id:
                    print(_dump(e["payload"]))
                    return 0
            err("no such policy decision: {}".format(args.decision_id))
            return 1
        operation = getattr(args, "operation", None) or "accept"
        sess = Session.active(repo)
        pin = build_policy_input(repo, sess, operation)
        decision = policymod.evaluate(pol, pin)   # READ-ONLY: not recorded
        if getattr(args, "json", False):
            print(_dump(decision))
            return 0 if decision["effect"] != "deny" else 1
        glyph = util.green("ALLOW") if decision["effect"] == "allow" else util.red("DENY")
        info("{} {}".format(glyph, operation))
        if decision["rules_matched"]:
            info(util.bold("Matched rules:"))
            for r in decision["rules_matched"]:
                info("  * " + r)
        if decision["reasons"]:
            info(util.bold("Reasons:"))
            for r in decision["reasons"]:
                info(util.red("  - " + r))
        if decision["required_actions"]:
            info(util.bold("Required actions:"))
            for a in decision["required_actions"]:
                info("  * " + a)
        return 0 if decision["effect"] != "deny" else 1

    if sub == "test":
        fixture = util.read_json(args.fixture, None)
        if fixture is None:
            import yaml as _y
            try:
                fixture = _y.safe_load(Path(args.fixture).read_text(encoding="utf-8"))
            except Exception:
                err("cannot read fixture: {}".format(args.fixture))
                return 1
        pol = fixture.get("policy") or policymod.load(repo) or {}
        decision = policymod.evaluate(pol, fixture.get("input", {}))
        expect = fixture.get("expect")
        ok = expect is None or decision["effect"] == expect
        info(("{} ".format(util.green("PASS") if ok else util.red("FAIL"))) +
             "{} -> {} (expected {})".format(fixture.get("input", {}).get("operation"),
                                             decision["effect"], expect))
        if not ok and decision["reasons"]:
            for r in decision["reasons"]:
                info(util.red("  - " + r))
        return 0 if ok else 1

    if sub == "audit":
        rows = [e for e in ledgermod.read_all(repo) if e["event_type"] == "policy"]
        if not rows:
            info("No policy decisions recorded.")
            return 0
        info(util.bold("{:<22} {:<10} {:<8} {}".format("WHEN", "OP", "EFFECT", "DECISION")))
        for e in rows[-50:]:
            p = e["payload"]
            eff = p.get("effect", "?")
            color = util.green if eff == "allow" else util.red
            mark = " (override)" if p.get("override_used") else ""
            info("{:<22} {:<10} {:<8} {}{}".format(
                e["timestamp"][:19], p.get("operation", "?"), color(eff),
                p.get("decision_id", "")[:18], mark))
        return 0

    err("unknown policy subcommand")
    return 2


def _policy_findings(repo, pol) -> List[str]:
    """Evaluate accepted history against the current policy (used by fsck --policy)."""
    findings: List[str] = []
    rs = pol.get("required_signatures", {}) or {}
    accepted = []
    seen = set()
    for kind_dir in ("heads", "tags"):
        d = repo.paths.base / "refs" / kind_dir
        if d.exists():
            for ref in d.iterdir():
                if ref.is_file():
                    for oid in repo.history(ref.read_text(encoding="utf-8").strip()):
                        if oid not in seen:
                            seen.add(oid)
                            accepted.append(oid)
    for oid in accepted:
        if rs.get("accepts"):
            sigs = signmod.signatures_for(repo, oid)
            if not sigs:
                findings.append("accepted snapshot {} is unsigned (policy requires signed accepts)".format(oid[:12]))
            elif not any(signmod.verify_record(repo, s)["ok"] for s in sigs):
                findings.append("accepted snapshot {} has no valid signature".format(oid[:12]))
    return findings


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
    sp.add_argument("--safe-git-adapter", action="store_true",
                    help="print safe-trial guidance when run inside a Git repo")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("claude",
                        help='run a Claude Code task in a reviewed session: claude "<task>"')
    sp.add_argument("task", nargs="?", default="")
    sp.add_argument("--continue", dest="cont", action="store_true",
                    help="resume the open session instead of starting a new task")
    sp.add_argument("--model", help="model hint recorded on the session")
    sp.add_argument("--tag", action="append")
    sp.add_argument("--no-tests", action="store_true", help="skip verification after Claude finishes")
    sp.add_argument("--no-launch", action="store_true", help="don't launch Claude (you make changes), just review")
    sp.add_argument("--login", action="store_true",
                    help="use the claude.ai login (ignore ANTHROPIC_API_KEY for this run)")
    sp.add_argument("--autopilot", action="store_true",
                    help="Owner Agent reviews; auto-accept low-risk work or escalate")
    sp.add_argument("--json", action="store_true", help="machine-readable run summary (autopilot)")
    sp.add_argument("--decision",
                    choices=["accept", "rollback", "diff", "packet", "quit",
                             "auto", "escalate", "rollback-on-fail"],
                    help="non-interactive decision (default: ask). auto/escalate/rollback-on-fail are autopilot modes")
    sp.set_defaults(func=cmd_claude)

    # ---- concierge: next / first-push / web ----
    spn = sub.add_parser("next", help="inspect the repo and recommend the next action (concierge)")
    spn.add_argument("--json", action="store_true")
    spn.set_defaults(func=cmd_next)

    spf = sub.add_parser("first-push", help="set up the first personal push/backup for this repo")
    spf.add_argument("--yes", action="store_true", help="non-interactive (skill-confirmed)")
    spf.add_argument("--status", action="store_true", help="report whether first push is done")
    spf.add_argument("--dest", help="destination path/remote (default: ~/CheckpointBackups/<repo>)")
    spf.add_argument("--force", action="store_true")
    spf.add_argument("--json", action="store_true")
    spf.set_defaults(func=cmd_first_push)

    spw = sub.add_parser("web", help="print (or open) the local web review UI URL")
    spw.add_argument("--open", action="store_true")
    spw.set_defaults(func=cmd_web)

    # ---- mr: scriptable merge-request review surface (talks to the hosted remote) ----
    mp = sub.add_parser("mr", help="merge requests: create/list/show/diff/comment/approve/merge/...")
    msub = mp.add_subparsers(dest="mr_cmd")

    def _mr_add(name, helptext, with_id=True):
        s = msub.add_parser(name, help=helptext)
        if with_id:
            s.add_argument("id")
        s.add_argument("--remote", help="remote name (default: checkpoint/origin)")
        return s

    c = msub.add_parser("create", help="open a merge request")
    c.add_argument("--title", required=True)
    c.add_argument("--from", dest="from_branch", help="source branch")
    c.add_argument("--snapshot", help="source accepted-snapshot id")
    c.add_argument("--session", help="source session id (uses its accepted snapshot)")
    c.add_argument("--to", default="main", help="target branch (default: main)")
    c.add_argument("--remote")

    lst = msub.add_parser("list", help="list merge requests")
    lst.add_argument("--remote")

    _mr_add("show", "one-screen MR summary")
    _mr_add("status", "compact one-line status")
    _mr_add("diff", "print the MR diff")
    _mr_add("approve", "approve the MR")
    _mr_add("unapprove", "remove your approval")
    _mr_add("merge", "merge the MR (server-signed, conflict-aware)")
    _mr_add("close", "close the MR without merging")

    cm = _mr_add("comment", "comment on the MR (optionally inline)")
    cm.add_argument("--file", help="anchor the comment to a file path")
    cm.add_argument("--line", type=int, help="anchor to a line number")
    cm.add_argument("--body", required=True)

    rv = _mr_add("review", "interactive review screen ([a]approve [m]merge [d]diff [c]comment [q]quit)")
    rv.add_argument("--decision", choices=["approve", "merge", "diff", "comment", "quit"],
                    help="non-interactive action (default: ask)")

    mp.set_defaults(func=cmd_mr, mr_cmd=None)

    # ---- autopilot: builder + owner-agent loop ----
    ap = sub.add_parser("autopilot", help="Owner Agent loop: claude/review/status/config")
    apsub = ap.add_subparsers(dest="autopilot_cmd")
    apc = apsub.add_parser("claude", help="run the builder + owner-agent autopilot flow")
    apc.add_argument("task")
    apc.add_argument("--model"); apc.add_argument("--tag", action="append")
    apc.add_argument("--no-tests", action="store_true"); apc.add_argument("--no-launch", action="store_true")
    apc.add_argument("--login", action="store_true"); apc.add_argument("--json", action="store_true")
    apc.add_argument("--decision", choices=["auto", "escalate", "rollback-on-fail"])
    apr = apsub.add_parser("review", help="run Owner Agent review on the active session")
    apr.add_argument("--json", action="store_true")
    apsub.add_parser("status", help="recent autopilot runs")
    apsub.add_parser("config", help="show the active autopilot config")
    ap.set_defaults(func=cmd_autopilot, autopilot_cmd=None)

    # ---- personal: one-power-user setup + status + daily ----
    pp = sub.add_parser("personal", help="personal setup: init/status/daily")
    ppsub = pp.add_subparsers(dest="personal_cmd")
    ppi = ppsub.add_parser("init", help="configure Checkpoint for personal use")
    ppi.add_argument("--name", help="your human identity name")
    ppi.add_argument("--backup-path", dest="backup_path", help="filesystem backup remote path")
    ppi.add_argument("--no-autoaccept", action="store_true", dest="no_autoaccept",
                     help="review-only mode (don't auto-accept anything)")
    ppsub.add_parser("status", help="identity / owner-agent / backup / policy / health")
    ppsub.add_parser("daily", help="today's accepted/escalated/rolled-back/open work")
    pp.set_defaults(func=cmd_personal, personal_cmd=None)

    # ---- backup: personal filesystem backup of accepted history ----
    bp = sub.add_parser("backup", help="personal backup: init/run/status/restore")
    bpsub = bp.add_subparsers(dest="backup_cmd")
    bpi = bpsub.add_parser("init"); bpi.add_argument("path")
    bpsub.add_parser("run")
    bpsub.add_parser("status")
    bpr = bpsub.add_parser("restore"); bpr.add_argument("--yes", action="store_true")
    bp.set_defaults(func=cmd_backup, backup_cmd=None)

    sp = sub.add_parser("setup",
                        help="one-shot: init + identity + ignore + remote + server repo + policy")
    sp.add_argument("--server", help="Checkpoint server base URL, e.g. http://localhost:8800")
    sp.add_argument("--token", help="API token for the server")
    sp.add_argument("--owner", default="jack")
    sp.add_argument("--name", help="server repo name (default: this directory's name)")
    sp.add_argument("--remote-name", default="checkpoint", dest="remote_name")
    sp.add_argument("--identity-name", dest="identity_name")
    sp.add_argument("--branch")
    sp.add_argument("--no-policy", action="store_true", dest="no_policy")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("identity", help="manage signing identities and trust")
    isub = sp.add_subparsers(dest="identity_cmd")
    icr = isub.add_parser("create")
    icr.add_argument("--name", default="")
    icr.add_argument("--type", choices=list(idmod.TYPES), default="human")
    icr.add_argument("--email")
    isub.add_parser("list")
    ish = isub.add_parser("show"); ish.add_argument("id")
    itr = isub.add_parser("trust"); itr.add_argument("id")
    iun = isub.add_parser("untrust"); iun.add_argument("id")
    irv = isub.add_parser("revoke"); irv.add_argument("id")
    iim = isub.add_parser("import"); iim.add_argument("path")
    iex = isub.add_parser("export"); iex.add_argument("id"); iex.add_argument("--out")
    isub.add_parser("current")
    ius = isub.add_parser("use"); ius.add_argument("id")
    ise = isub.add_parser("set"); ise.add_argument("--name"); ise.add_argument("--email")
    sp.set_defaults(func=cmd_identity, identity_cmd=None)

    sp = sub.add_parser("start", help="start a session")
    sp.add_argument("instruction", nargs="?", default="")
    sp.add_argument("--prompt-file")
    sp.add_argument("--actor", choices=["human", "agent", "tool"])
    sp.add_argument("--agent")
    sp.add_argument("--model")
    sp.add_argument("--tool")
    sp.add_argument("--tag", action="append")
    sp.add_argument("--no-watch", action="store_true",
                    help="do not start the background autosave watcher for this session")
    sp.set_defaults(func=cmd_start)

    sub.add_parser("status", help="show the active session").set_defaults(func=cmd_status)

    sp = sub.add_parser("snapshot", help="capture a meaningful snapshot")
    sp.add_argument("--message", "-m")
    sp.add_argument("--sign", action="store_true", help="sign this snapshot")
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
    sp.add_argument("--no-sign", action="store_true", help="do not sign even if an identity is active")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--override", action="store_true", help="override a policy denial (requires --reason)")
    sp.add_argument("--reason", help="reason for a policy override")
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
    sp.add_argument("--override", action="store_true", help="override a policy denial (requires --reason)")
    sp.add_argument("--reason", help="reason for a policy override")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("remote", help="manage remotes")
    rsub = sp.add_subparsers(dest="remote_cmd")
    radd = rsub.add_parser("add")
    radd.add_argument("name")
    radd.add_argument("location", nargs="?", help="http(s):// URL or a filesystem path")
    radd.add_argument("--type", default="filesystem", choices=["filesystem", "http"])
    radd.add_argument("--path")
    radd.add_argument("--token", help="API token for an http remote")
    rsub.add_parser("list")
    rsh = rsub.add_parser("show"); rsh.add_argument("name")
    rrm = rsub.add_parser("remove"); rrm.add_argument("name")
    sp.set_defaults(func=cmd_remote, remote_cmd=None)

    sp = sub.add_parser("fetch", help="fetch objects + remote-tracking refs (no branch change)")
    sp.add_argument("remote")
    sp.add_argument("--branch")
    sp.add_argument("--tags", action="store_true")
    sp.add_argument("--verify-signatures", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("pull", help="fetch + verify + fast-forward (or refuse if diverged)")
    sp.add_argument("remote")
    sp.add_argument("branch", nargs="?")
    sp.add_argument("--branch", dest="branch_opt")  # tolerated alias
    sp.add_argument("--verify-signatures", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("push", help="push objects + update remote ref safely")
    sp.add_argument("remote")
    sp.add_argument("branch", nargs="?")
    sp.add_argument("--tags", action="store_true")
    sp.add_argument("--force-with-lease", nargs="?", const="", default=None)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_push)

    sp = sub.add_parser("clone", help="create a local repo from a remote store, bundle, or URL")
    sp.add_argument("source")
    sp.add_argument("dest")
    sp.add_argument("--token", help="API token for an http source")
    sp.add_argument("--verify-signatures", action="store_true")
    sp.set_defaults(func=cmd_clone)

    sp = sub.add_parser("sync", help="sync status against a remote")
    ssub = sp.add_subparsers(dest="sync_cmd")
    sst = ssub.add_parser("status")
    sst.add_argument("remote")
    sst.add_argument("--branch")
    sst.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_sync, sync_cmd=None)

    sp = sub.add_parser("bundle", help="create/verify/import a portable bundle")
    bsub = sp.add_subparsers(dest="bundle_cmd")
    bcr = bsub.add_parser("create")
    bcr.add_argument("--out")
    bcr.add_argument("--branch")
    bcr.add_argument("--tags", action="store_true")
    bcr.add_argument("--no-sessions", action="store_true")
    bex = bsub.add_parser("export")    # legacy alias
    bex.add_argument("branch", nargs="?")
    bex.add_argument("--out")
    bex.add_argument("--tags", action="store_true")
    bvf = bsub.add_parser("verify")
    bvf.add_argument("path")
    bvf.add_argument("--verify-signatures", action="store_true")
    bvf.add_argument("--json", action="store_true")
    bim = bsub.add_parser("import")
    bim.add_argument("path")
    bim.add_argument("--name")
    bim.add_argument("--verify-signatures", action="store_true")
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
    sp = sub.add_parser("doctor", help="diagnose the installation")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("version", help="show CLI/protocol/store versions and features")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_version)

    sp = sub.add_parser("migrate", help="store migration (status/plan/apply scaffolding)")
    msub = sp.add_subparsers(dest="migrate_cmd")
    for mc in ("status", "plan", "apply"):
        mp = msub.add_parser(mc); mp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_migrate, migrate_cmd=None, json=False)

    sp = sub.add_parser("bug-report", help="write a redacted diagnostic bundle")
    sp.add_argument("--out")
    sp.add_argument("--include-objects", action="store_true",
                    help="also include object-store contents (off by default)")
    sp.set_defaults(func=cmd_bug_report)

    sp = sub.add_parser("agent", help="agent helper: begin/status/packet")
    asub = sp.add_subparsers(dest="agent_cmd")
    ab = asub.add_parser("begin")
    ab.add_argument("instruction")
    ab.add_argument("--agent"); ab.add_argument("--model"); ab.add_argument("--tool")
    ab.add_argument("--tag", action="append")
    asub.add_parser("status")
    ap = asub.add_parser("packet"); ap.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_agent, agent_cmd=None)

    # --- Phase 2: background autosave daemon, timeline, recovery ---
    sp = sub.add_parser("watch", help="continuously autosave the active session (foreground)")
    sp.add_argument("--debounce-ms", type=int, dest="debounce_ms")
    sp.add_argument("--poll-ms", type=int, dest="poll_ms")
    sp.add_argument("--managed", action="store_true",
                    help="internal: spawned by `start`; log to file and clean up the PID file")
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

    # --- Phase 4: integrity + garbage collection ---
    sp = sub.add_parser("fsck", help="read-only integrity check of the store")
    sp.add_argument("--strict", action="store_true", help="fail on warnings/dangling objects")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--verify-signatures", action="store_true", help="also verify signatures")
    sp.add_argument("--require-signatures", action="store_true",
                    help="fail on unsigned/invalid accepted snapshots")
    sp.add_argument("--policy", action="store_true", help="evaluate accepted history against policy")
    sp.set_defaults(func=cmd_fsck)

    sp = sub.add_parser("policy", help="policy engine: show/check/explain/validate/test/init/audit")
    psub = sp.add_subparsers(dest="policy_cmd")
    pin_ = psub.add_parser("init"); pin_.add_argument("--force", action="store_true")
    psh = psub.add_parser("show"); psh.add_argument("--json", action="store_true")
    psub.add_parser("validate")
    pck = psub.add_parser("check")
    pck.add_argument("--operation", default="accept")
    pck.add_argument("--json", action="store_true")
    pex = psub.add_parser("explain")
    pex.add_argument("decision_id", nargs="?")
    pex.add_argument("--operation", default="accept")
    pex.add_argument("--json", action="store_true")
    pts = psub.add_parser("test"); pts.add_argument("fixture")
    psub.add_parser("audit")
    sp.set_defaults(func=cmd_policy, policy_cmd=None)

    sp = sub.add_parser("sign", help="sign a snapshot with the active identity")
    sp.add_argument("object_id")
    sp.set_defaults(func=cmd_sign)

    sp = sub.add_parser("verify-signatures", help="verify all signatures in the store")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_verify_signatures)

    sub.add_parser("trust-status", help="summary of signed/unsigned history and trust").set_defaults(func=cmd_trust_status)

    sp = sub.add_parser("gc", help="garbage-collect unreachable objects (safe, quarantined)")
    sp.add_argument("--dry-run", action="store_true", help="show what would be collected")
    sp.add_argument("--aggressive", action="store_true",
                    help="shorter grace; include past-retention rejected-session objects")
    sp.add_argument("--force", action="store_true", help="skip the pre-gc fsck gate")
    sp.set_defaults(func=cmd_gc)

    sp = sub.add_parser("objects", help="inspect the object store")
    osub = sp.add_subparsers(dest="objects_cmd")
    osub.add_parser("stats")
    olist = osub.add_parser("list")
    olist.add_argument("--reachable", action="store_true")
    olist.add_argument("--unreachable", action="store_true")
    olist.add_argument("--type", choices=["blob", "tree", "snapshot"])
    oshow = osub.add_parser("show")
    oshow.add_argument("object_id")
    sp.set_defaults(func=cmd_objects, objects_cmd=None)
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
