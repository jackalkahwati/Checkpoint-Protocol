"""Secret-scan allowlist (.checkpoint/secrets-allow) + HTTP remote display."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AWS_EXAMPLE = "AKIAIOSFODNN7EXAMPLE"   # canonical AWS docs example key


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    run(["init"])
    run(["identity", "create", "--name", "Jack", "--type", "human"])
    return tmp_path


def test_filter_findings_unit():
    from checkpoint_core import secrets
    findings = [{"file": "tests/fix.py", "line": 1, "type": "aws_access_key_id"},
                {"file": "src/app.py", "line": 2, "type": "aws_access_key_id"}]
    kept = secrets.filter_findings(findings, ["tests/"])
    assert [f["file"] for f in kept] == ["src/app.py"]
    assert secrets.filter_findings(findings, []) == findings   # no allowlist -> unchanged


def test_load_allow_skips_comments_and_blanks(tmp_path):
    from checkpoint_core import secrets
    f = tmp_path / "secrets-allow"
    f.write_text("# comment\n\ntests/\ndocs/\n")
    assert secrets.load_allow(f) == ["tests", "docs"]
    assert secrets.load_allow(tmp_path / "nope") == []


def test_accept_blocked_without_allowlist(repo, tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text('KEY = "{}"\n'.format(AWS_EXAMPLE))
    run(["start", "add fixture"])
    assert run(["accept", "-m", "add fixture"]) == 1     # refused: secret detected


def test_accept_proceeds_with_allowlist(repo, tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text('KEY = "{}"\n'.format(AWS_EXAMPLE))
    (tmp_path / ".checkpoint" / "secrets-allow").write_text("tests/\n")
    run(["start", "add fixture"])
    assert run(["accept", "-m", "add fixture"]) == 0     # allowlisted -> accepted, no --force
    from checkpoint_core.store import Repo
    assert Repo(tmp_path).head_snapshot()                 # history advanced


def test_allowlist_does_not_hide_real_secrets_elsewhere(repo, tmp_path):
    (tmp_path / "tests").mkdir(); (tmp_path / "src").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text('KEY = "{}"\n'.format(AWS_EXAMPLE))
    (tmp_path / "src" / "real.py").write_text('KEY = "{}"\n'.format(AWS_EXAMPLE))
    (tmp_path / ".checkpoint" / "secrets-allow").write_text("tests/\n")
    run(["start", "mix"])
    assert run(["accept", "-m", "mix"]) == 1             # still blocked by src/real.py


def test_remote_list_shows_http_url(repo, capsys):
    run(["remote", "add", "origin", "http://127.0.0.1:9/owner/repo", "--token", "t"])
    capsys.readouterr()
    run(["remote", "list"])
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9/owner/repo" in out and "None" not in out
