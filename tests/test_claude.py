"""`checkpoint-core claude "<task>"` — the one-verb agent wrapper."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


def _repo(path):
    from checkpoint_core.store import Repo
    return Repo(path)


def _active(path):
    from checkpoint_core.session import Session
    return Session.active(_repo(path))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_claude(tmp_path):
    """A stand-in for Claude Code that makes a scoped edit (the wrapper appends the prompt)."""
    fc = tmp_path / "fakeclaude.sh"
    fc.write_text("#!/bin/bash\nprintf 'def feature():\\n    return 1\\n' > feature.py\n")
    fc.chmod(0o755)
    return str(fc)


def _base(repo):
    run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
    (repo / "base.py").write_text("x = 1\n")
    run(["start", "base", "--no-watch"]); run(["accept", "-m", "base"])


def test_prompt_has_guardrails():
    from checkpoint_core.cli import _claude_prompt
    p = _claude_prompt("Fix the remote sync bug")
    assert "Checkpoint session" in p
    assert "Fix the remote sync bug" in p
    assert "Do not accept" in p and "scoped" in p


def test_requires_task(repo):
    assert run(["claude", ""]) == 2


def test_accept_flow(repo, fake_claude, monkeypatch):
    _base(repo)
    monkeypatch.setenv("CHECKPOINT_CLAUDE_CMD", fake_claude)
    assert run(["claude", "add a feature", "--no-tests", "--decision", "accept"]) == 0
    r = _repo(repo)
    assert len(r.history()) == 2                      # base + the accepted claude session
    assert (repo / "feature.py").exists()             # Claude's change landed
    assert _active(repo) is None                       # session closed by accept


def test_rollback_flow(repo, fake_claude, monkeypatch):
    _base(repo)
    monkeypatch.setenv("CHECKPOINT_CLAUDE_CMD", fake_claude)
    assert run(["claude", "add a feature", "--no-tests", "--decision", "rollback"]) == 0
    r = _repo(repo)
    assert len(r.history()) == 1                      # no new accepted snapshot
    assert not (repo / "feature.py").exists()         # working tree rolled back
    assert _active(repo) is None


def test_quit_leaves_session_open(repo, monkeypatch):
    _base(repo)
    assert run(["claude", "do a thing", "--no-launch", "--no-tests", "--decision", "quit"]) == 0
    assert _active(repo) is not None                   # left open for a later decision


def test_auto_inits_fresh_dir(repo, monkeypatch):
    # no init beforehand — the wrapper sets it up so users don't learn Checkpoint first
    assert not (repo / ".checkpoint").exists()
    assert run(["claude", "first task", "--no-launch", "--no-tests", "--decision", "quit"]) == 0
    assert (repo / ".checkpoint").exists()
    r = _repo(repo)
    assert r.current_identity_id()                     # identity auto-created (so accept can sign)
    assert _active(repo) is not None
