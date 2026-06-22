"""Autosave-during-active-session: detached watcher lifecycle."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LAUNCHER = str(ROOT / "bin" / "checkpoint-core")


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
    return tmp_path


def _repo(path):
    from checkpoint_core.store import Repo
    return Repo(path)


def test_running_pid_none_when_no_pidfile(repo):
    from checkpoint_core import autowatch
    assert autowatch.running_pid(_repo(repo)) is None


def test_stale_pidfile_is_cleaned(repo):
    from checkpoint_core import autowatch
    r = _repo(repo)
    pf = autowatch._pidfile(r); pf.write_text("999999")   # almost-certainly-dead PID
    assert autowatch.running_pid(r) is None
    assert not pf.exists()


def test_start_returns_none_when_autosave_disabled(repo):
    import yaml
    cfg = repo / ".checkpoint" / "config.yaml"
    d = yaml.safe_load(cfg.read_text()); d.setdefault("autosave", {})["enabled"] = False
    cfg.write_text(yaml.safe_dump(d))
    from checkpoint_core import autowatch
    assert autowatch.start(_repo(repo)) is None


def test_start_no_watch_flag_does_not_spawn(repo):
    from checkpoint_core import autowatch
    run(["start", "work", "--no-watch"])
    assert autowatch.running_pid(_repo(repo)) is None


def test_spawn_and_stop_real_watcher(repo, monkeypatch):
    from checkpoint_core import autowatch
    r = _repo(repo)
    run(["start", "work", "--no-watch"])              # active session, no auto-spawn
    monkeypatch.setattr(sys, "argv", [LAUNCHER, "start"])  # so autowatch can find the launcher
    pid = autowatch.start(r)
    try:
        assert pid and autowatch.running_pid(r) == pid
    finally:
        assert autowatch.stop(r) is True              # always clean up the bg process
    time.sleep(0.4)
    assert autowatch.running_pid(r) is None


def test_watcher_loop_condition_ends_with_session(repo):
    """The watcher loops `while active_session_id() == session.id` (watcher.py), so ending
    the session makes the loop predicate false and the watcher exits. Verify that predicate
    flips on accept — deterministic, no subprocess (subprocess self-exit is verified manually
    and by the standalone smoke; it's timing-flaky under the test runner)."""
    from checkpoint_core.session import Session
    r = _repo(repo)
    (repo / "f.txt").write_text("x\n")
    run(["start", "work", "--no-watch"])
    sess = Session.active(r)
    assert r.active_session_id() == sess.id            # loop would keep running
    run(["accept", "-m", "done"])
    assert r.active_session_id() != sess.id            # predicate now false -> watcher stops
