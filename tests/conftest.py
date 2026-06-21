import subprocess
import sys
from pathlib import Path

import pytest

# Make the package importable when tests run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), text=True, capture_output=True, check=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fresh Git repo with one commit, cwd set to it."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.com")
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("v1\n")
    (tmp_path / "app.py").write_text("print('hi')\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "initial")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(argv):
    """Invoke the CLI in-process and return the exit code."""
    from checkpoint.cli import main
    return main(argv)


def set_verification(repo, commands):
    import yaml
    p = repo / ".checkpoint" / "config.yaml"
    data = yaml.safe_load(p.read_text())
    data["verification"]["commands"] = commands
    p.write_text(yaml.safe_dump(data, sort_keys=False))


def active_session_id(repo):
    import json
    state = json.loads((repo / ".checkpoint" / "state.json").read_text())
    return state["active_session"]


def only_session_id(repo):
    sessions = sorted((repo / ".checkpoint" / "sessions").iterdir())
    return sessions[0].name
