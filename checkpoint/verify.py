"""Run configured verification commands and store structured results."""
from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, List

from . import util
from .session import Session
from .snapshot import capture_tree
from .store import Repo


def run_verification(repo: Repo, session: Session) -> Dict[str, Any]:
    commands = repo.config.verification_commands()
    seq = session.next_seq("verification")
    run_id = util.seq_id("ver", seq)
    tree = capture_tree(repo, name="verify-index")

    results: List[Dict[str, Any]] = []
    overall = "passed"
    if not commands:
        overall = "skipped"

    for cmd in commands:
        name = cmd.get("name", cmd.get("run", "command"))
        run = cmd["run"]
        started = util.now_iso()
        t0 = time.time()
        try:
            proc = subprocess.run(
                run, shell=True, cwd=str(repo.root),
                text=True, capture_output=True,
            )
            exit_code = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
            status = "passed" if exit_code == 0 else "failed"
        except Exception as exc:  # pragma: no cover - defensive
            exit_code = -1
            stdout, stderr = "", str(exc)
            status = "error"
        duration = round(time.time() - t0, 3)
        if status != "passed":
            overall = "failed"
        results.append({
            "name": name,
            "command": run,
            "exit_code": exit_code,
            "status": status,
            "duration_seconds": duration,
            "stdout_summary": util.summarize_text(stdout),
            "stderr_summary": util.summarize_text(stderr),
            "started_at": started,
            "finished_at": util.now_iso(),
        })

    record = {
        "verification_run_id": run_id,
        "session_id": session.id,
        "created_at": util.now_iso(),
        "tree": tree,
        "overall": overall,
        "results": results,
    }
    util.write_json(session.dir / "verification" / (run_id + ".json"), record)
    session.data["verifications"].append(run_id)
    session.save()
    return record


def last_verification(repo: Repo, session: Session) -> Dict[str, Any]:
    runs = session.data.get("verifications", [])
    if not runs:
        return {}
    path = session.dir / "verification" / (runs[-1] + ".json")
    return util.read_json(path, {})
