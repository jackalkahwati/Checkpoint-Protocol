"""Concierge: checkpoint-core next / first-push / web, and claude --continue."""
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


def _repo(p):
    from checkpoint_core.store import Repo
    return Repo(p)


def _active(p):
    from checkpoint_core.session import Session
    return Session.active(_repo(p))


def nextj(capsys):
    run(["next", "--json"])
    out = capsys.readouterr().out
    return json.loads(out[out.index("{"):])


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init_base(repo):
    run(["personal", "init", "--name", "Jack"])
    (repo / "README.md").write_text("# Repo\n")
    run(["start", "base", "--no-watch"]); run(["accept", "--force", "-m", "base"])


# ---------------------------------------------------------------- next

def test_next_uninitialized(repo, capsys):
    d = nextj(capsys)
    assert d["initialized"] is False and d["recommended_action"] == "init"


def test_next_initialized_reports_health(repo, capsys):
    _init_base(repo)
    d = nextj(capsys)
    assert d["initialized"] and d["status"] == "clean"
    assert d["policy"] in ("active", "none") and d["integrity"] == "healthy"
    assert "signatures" in d


def test_next_detects_first_push_needed(repo, capsys):
    _init_base(repo)
    d = nextj(capsys)
    assert d["first_push_needed"] is True and d["recommended_action"] == "first_push"


def test_next_no_first_push_after_completion(repo, capsys, tmp_path):
    _init_base(repo)
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])
    d = nextj(capsys)
    assert d["first_push_done"] is True and d["first_push_needed"] is False
    assert d["recommended_action"] != "first_push"


def test_next_detects_open_session_resume(repo, capsys, tmp_path):
    _init_base(repo)
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])   # past first-push -> directions surface
    (repo / "x.py").write_text("y\n")
    run(["start", "do work", "--no-watch"])
    d = nextj(capsys)
    assert d["active_session"] and d["recommended_action"] == "resume"
    run(["rollback", "--hard", "--yes"])


def test_next_detects_dirty_without_session(repo, capsys, tmp_path):
    _init_base(repo)
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])
    (repo / "loose.py").write_text("z\n")          # dirty, no active session
    d = nextj(capsys)
    assert d["dirty_no_session"] is True and d["recommended_action"] == "create_session"


def test_next_detects_backup_behind(repo, capsys, tmp_path):
    _init_base(repo)
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])
    (repo / "more.md").write_text("more\n")          # accept new work -> local ahead of backup
    run(["start", "more", "--no-watch"]); run(["accept", "--force", "-m", "more"])
    d = nextj(capsys)
    assert d["backup"]["status"] == "behind" and d["recommended_action"] == "backup"


# ---------------------------------------------------------------- first-push

def test_first_push_status_false_then_true(repo, capsys, tmp_path):
    _init_base(repo)
    run(["first-push", "--status"]); assert "not done" in capsys.readouterr().out
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])
    run(["first-push", "--status"]); assert "done" in capsys.readouterr().out


def test_first_push_marks_done_and_idempotent(repo, capsys, tmp_path):
    _init_base(repo)
    assert run(["first-push", "--yes", "--dest", str(tmp_path / "bk")]) == 0
    assert _repo(repo).config.data["personal"]["first_push_done"] is True
    run(["first-push", "--yes"]); assert "already completed" in capsys.readouterr().out


def test_first_push_no_private_keys_or_autosaves(repo, tmp_path):
    _init_base(repo)
    bk = tmp_path / "bk"
    run(["first-push", "--yes", "--dest", str(bk)])
    leaked = [p for p in bk.rglob("*") if p.suffix == ".key" or "keys" in p.parts]
    assert not leaked
    assert not any("autosaves" in p.parts for p in bk.rglob("*"))


# ---------------------------------------------------------------- web + continue

def test_web_prints_url(repo, capsys):
    run(["web"])
    out = capsys.readouterr().out
    assert "localhost:3000" in out and "localhost:8800" in out


def test_claude_continue_resumes_open_session(repo):
    _init_base(repo)
    (repo / "x.py").write_text("a\n")
    run(["claude", "build x", "--no-launch", "--no-tests", "--decision", "quit"])
    sid = _active(repo).id
    # --continue resumes the SAME session (no error, no new session)
    assert run(["claude", "--continue", "--no-launch", "--no-tests", "--decision", "quit"]) == 0
    assert _active(repo).id == sid
    run(["rollback", "--hard", "--yes"])


def test_claude_continue_without_session_errors(repo):
    _init_base(repo)
    assert run(["claude", "--continue", "--no-launch"]) == 1


# ---------------------------------------------------------------- open MR detection (live server)

def test_next_detects_open_mr(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    from checkpoint_core.server.store import ServerStore
    from checkpoint_core.server.app import serve
    from checkpoint_core import remote as RM
    store = ServerStore.init_store(tmp_path / "srv")
    admin = store.create_token("admin", ["admin"], "*")["token"]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    httpd = serve(store, "127.0.0.1", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start(); time.sleep(0.15)
    url = "http://127.0.0.1:{}".format(port)
    RM._http("POST", url + "/repos", admin, {"owner": "o", "repo": "r"})
    work = tmp_path / "w"; work.mkdir(); monkeypatch.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "a.py").write_text("x\n"); run(["start", "b", "--no-watch"]); run(["accept", "-m", "b"])
        run(["branch", "feat"]); run(["checkout", "feat"])
        (work / "c.py").write_text("c\n"); run(["start", "f", "--no-watch"]); run(["accept", "-m", "f"])
        run(["checkout", "main"])
        run(["remote", "add", "checkpoint", "{}/o/r".format(url), "--token", admin])
        run(["push", "checkpoint", "main"]); run(["push", "checkpoint", "feat"])
        r = _repo(work); r.config.data.setdefault("personal", {})["first_push_done"] = True; r.config.save()
        RM._http("POST", "{}/ui/repos/o/r/reviews".format(url), admin,
                 {"title": "feat", "source_branch": "feat", "target_branch": "main"})
        capsys.readouterr()
        d = nextj(capsys)
        assert d["open_mrs_available"] is True and len(d["open_mrs"]) == 1
        assert d["recommended_action"] == "review"
    finally:
        httpd.shutdown()
