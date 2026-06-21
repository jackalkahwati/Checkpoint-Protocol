"""End-to-end lifecycle tests for the Checkpoint CLI."""
import json
import subprocess
import tarfile
from pathlib import Path

from conftest import run, set_verification, active_session_id, only_session_id, git


def read_json(p):
    return json.loads(Path(p).read_text())


# ------------------------------------------------------------------------- init

def test_init_creates_layout_and_gitignore(repo):
    assert run(["init", "--yes"]) == 0
    cp = repo / ".checkpoint"
    assert (cp / "config.yaml").exists()
    assert (cp / "ledger.jsonl").exists()
    assert (cp / "sessions").is_dir()
    assert (cp / "objects").is_dir()
    # .checkpoint must be gitignored.
    gi = (repo / ".gitignore").read_text()
    assert ".checkpoint/" in gi
    # belt-and-suspenders internal ignore
    assert (cp / ".gitignore").read_text().strip() == "*"
    # init recorded in ledger
    events = (cp / "ledger.jsonl").read_text().strip().splitlines()
    assert any(json.loads(e)["event_type"] == "init" for e in events)


def test_init_requires_git_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run(["init", "--yes"]) == 2
    assert "Git" in capsys.readouterr().err


# ------------------------------------------------------------------------ start

def test_start_creates_active_session(repo):
    run(["init", "--yes"])
    assert run(["start", "fix the thing", "--tag", "backend"]) == 0
    sid = active_session_id(repo)
    assert sid and sid.startswith("cp_")
    sess = read_json(repo / ".checkpoint" / "sessions" / sid / "session.json")
    assert sess["instruction"] == "fix the thing"
    assert sess["status"] == "active"
    assert sess["risk_tags"] == ["backend"]
    assert sess["git"]["base_tree"]


def test_cannot_start_two_sessions(repo, capsys):
    run(["init", "--yes"])
    run(["start", "first"])
    assert run(["start", "second"]) == 1
    assert "already active" in capsys.readouterr().err


# --------------------------------------------------------------- snapshot/diff

def test_snapshot_and_diff(repo, capsys):
    run(["init", "--yes"])
    run(["start", "edit a"])
    (repo / "a.txt").write_text("v2\n")
    (repo / "new.txt").write_text("hello\n")
    assert run(["snapshot", "-m", "did edits"]) == 0
    sid = active_session_id(repo)
    snaps = list((repo / ".checkpoint" / "sessions" / sid / "snapshots").iterdir())
    assert len(snaps) == 1
    snap = read_json(snaps[0] / "snapshot.json")
    assert snap["message"] == "did edits"
    paths = {f["path"] for f in snap["changed_files"]}
    assert paths == {"a.txt", "new.txt"}
    assert (snaps[0] / "diff.patch").read_text().strip() != ""

    capsys.readouterr()
    assert run(["diff", "--files"]) == 0
    out = capsys.readouterr().out
    assert "a.txt" in out and "new.txt" in out


def test_diff_between_snapshots(repo, capsys):
    run(["init", "--yes"])
    run(["start", "stepwise"])
    (repo / "a.txt").write_text("step1\n")
    run(["snapshot", "-m", "s1"])
    (repo / "a.txt").write_text("step2\n")
    run(["snapshot", "-m", "s2"])
    sid = active_session_id(repo)
    snap_ids = sorted(p.name for p in (repo / ".checkpoint" / "sessions" / sid / "snapshots").iterdir())
    capsys.readouterr()
    assert run(["diff", "--from", snap_ids[0], "--to", snap_ids[1], "--summary"]) == 0
    assert "a.txt" in capsys.readouterr().out


# ---------------------------------------------------------------------- verify

def test_verify_records_results(repo, capsys):
    run(["init", "--yes"])
    set_verification(repo, [
        {"name": "good", "run": "exit 0"},
        {"name": "bad", "run": "exit 5"},
    ])
    run(["start", "verify run"])
    assert run(["verify"]) == 1  # overall failed
    sid = active_session_id(repo)
    vers = list((repo / ".checkpoint" / "sessions" / sid / "verification").glob("*.json"))
    assert len(vers) == 1
    rec = read_json(vers[0])
    assert rec["overall"] == "failed"
    names = {r["name"]: r["status"] for r in rec["results"]}
    assert names == {"good": "passed", "bad": "failed"}


# ---------------------------------------------------------------------- packet

def test_packet_generation(repo):
    run(["init", "--yes"])
    run(["start", "make packet", "--tag", "docs"])
    (repo / "a.txt").write_text("changed\n")
    assert run(["packet"]) == 0
    sid = active_session_id(repo)
    pkt = read_json(repo / ".checkpoint" / "sessions" / sid / "packet.json")
    assert pkt["recommended_next_action"] == "accept"
    assert pkt["instruction"] == "make packet"
    assert any(f["path"] == "a.txt" for f in pkt["changed_files"])
    assert "docs" in pkt["risks"]


# ---------------------------------------------------------------------- accept

def test_accept_creates_single_clean_commit(repo):
    run(["init", "--yes"])
    run(["start", "do work"])
    (repo / "a.txt").write_text("accepted\n")
    (repo / "fresh.txt").write_text("new\n")
    before = git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    assert run(["accept", "-m", "my commit"]) == 0
    after = git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    assert int(after) == int(before) + 1  # exactly one commit
    # commit message used
    assert git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "my commit"
    # .checkpoint not committed
    tracked = git(repo, "ls-files").stdout
    assert ".checkpoint" not in tracked
    # both session files committed and no longer dirty
    assert "fresh.txt" in tracked
    assert "a.txt" in tracked
    status = git(repo, "status", "--porcelain").stdout
    assert "a.txt" not in status     # committed, not dirty
    assert "fresh.txt" not in status
    # session closed and marked accepted
    assert active_session_id(repo) is None
    sess = read_json(repo / ".checkpoint" / "sessions" / only_session_id(repo) / "session.json")
    assert sess["status"] == "accepted"
    assert sess["git"]["accept_head"]


def test_accept_blocked_by_failing_verification(repo, capsys):
    run(["init", "--yes"])
    set_verification(repo, [{"name": "bad", "run": "exit 1"}])
    run(["start", "broken"])
    (repo / "a.txt").write_text("x\n")
    assert run(["accept"]) == 1
    assert "verification failed" in capsys.readouterr().err
    # nothing committed
    assert git(repo, "log", "--oneline").stdout.strip().count("\n") == 0


def test_accept_blocked_by_secrets(repo, capsys):
    run(["init", "--yes"])
    run(["start", "leak"])
    (repo / "config.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"\n')
    assert run(["accept", "--no-verify"]) == 1
    assert "secrets detected" in capsys.readouterr().err
    # not committed
    assert "config.py" not in git(repo, "ls-files").stdout
    # but --force overrides
    assert run(["accept", "--no-verify", "--force"]) == 0
    assert "config.py" in git(repo, "ls-files").stdout


def test_accept_nothing_to_commit(repo, capsys):
    run(["init", "--yes"])
    run(["start", "noop"])
    assert run(["accept", "--no-verify"]) == 1
    assert "nothing to commit" in capsys.readouterr().err


# -------------------------------------------------------------------- rollback

def test_rollback_preview_is_non_destructive(repo, capsys):
    run(["init", "--yes"])
    run(["start", "risky"])
    (repo / "a.txt").write_text("bad\n")
    assert run(["rollback"]) == 0
    assert "preview" in capsys.readouterr().out.lower()
    assert (repo / "a.txt").read_text() == "bad\n"  # unchanged


def test_rollback_hard_restores_and_deletes_added(repo):
    run(["init", "--yes"])
    run(["start", "risky"])
    (repo / "a.txt").write_text("bad\n")
    (repo / "junk.txt").write_text("junk\n")
    assert run(["rollback", "--hard"]) == 0
    assert (repo / "a.txt").read_text() == "v1\n"     # restored
    assert not (repo / "junk.txt").exists()           # added file deleted
    sess = read_json(repo / ".checkpoint" / "sessions" / only_session_id(repo) / "session.json")
    assert sess["status"] == "rolled_back"
    # a pre-rollback safety snapshot exists
    assert sess["snapshots"]


def test_rollback_keep_files(repo):
    run(["init", "--yes"])
    run(["start", "risky"])
    (repo / "a.txt").write_text("bad\n")
    (repo / "keep.txt").write_text("keep\n")
    assert run(["rollback", "--hard", "--keep-files"]) == 0
    assert (repo / "a.txt").read_text() == "v1\n"
    assert (repo / "keep.txt").exists()  # kept


def test_rollback_to_snapshot(repo):
    run(["init", "--yes"])
    run(["start", "stepwise"])
    (repo / "a.txt").write_text("good\n")
    run(["snapshot", "-m", "good state"])
    sid = active_session_id(repo)
    snap_id = next(iter((repo / ".checkpoint" / "sessions" / sid / "snapshots").iterdir())).name
    (repo / "a.txt").write_text("broken\n")
    assert run(["rollback", "--to-snapshot", snap_id, "--hard"]) == 0
    assert (repo / "a.txt").read_text() == "good\n"


# ----------------------------------------------------------------- ignore rules

def test_respects_gitignore(repo):
    run(["init", "--yes"])
    (repo / ".gitignore").open("a").write("ignored.log\n")
    run(["start", "with ignored file"])
    (repo / "ignored.log").write_text("secret-ish noise\n")
    (repo / "tracked.txt").write_text("real\n")
    run(["snapshot", "-m", "s"])
    sid = active_session_id(repo)
    snap = next(iter((repo / ".checkpoint" / "sessions" / sid / "snapshots").iterdir()))
    paths = {f["path"] for f in read_json(snap / "snapshot.json")["changed_files"]}
    assert "tracked.txt" in paths
    assert "ignored.log" not in paths


def test_respects_checkpointignore(repo):
    run(["init", "--yes"])
    (repo / ".checkpointignore").write_text("*.tmp\n")
    run(["start", "cp ignore"])
    (repo / "scratch.tmp").write_text("noise\n")
    (repo / "real.txt").write_text("real\n")
    run(["snapshot", "-m", "s"])
    sid = active_session_id(repo)
    snap = next(iter((repo / ".checkpoint" / "sessions" / sid / "snapshots").iterdir()))
    paths = {f["path"] for f in read_json(snap / "snapshot.json")["changed_files"]}
    assert "real.txt" in paths
    assert "scratch.tmp" not in paths


# ---------------------------------------------------------------- log/show/export

def test_log_and_show(repo, capsys):
    run(["init", "--yes"])
    run(["start", "work one"])
    (repo / "a.txt").write_text("z\n")
    run(["accept", "--no-verify", "-m", "c1"])
    capsys.readouterr()
    assert run(["log"]) == 0
    assert "accepted" in capsys.readouterr().out
    sid = only_session_id(repo)
    assert run(["show", sid]) == 0
    out = capsys.readouterr().out
    assert sid in out and "work one" in out


def test_export_bundle_redacts_secrets(repo, capsys):
    run(["init", "--yes"])
    run(["start", "leaky"])
    (repo / "s.py").write_text('k = "AKIAIOSFODNN7EXAMPLE"\n')
    run(["snapshot", "-m", "snap"])
    sid = active_session_id(repo)
    out = repo / "bundle.tar.gz"
    assert run(["export", sid, "--out", str(out)]) == 0
    assert out.exists()
    with tarfile.open(out) as tar:
        for member in tar.getmembers():
            data = tar.extractfile(member)
            if data is None:
                continue
            content = data.read()
            assert b"AKIAIOSFODNN7EXAMPLE" not in content, member.name


# ---------------------------------------------------------------------- doctor

def test_doctor_healthy(repo):
    run(["init", "--yes"])
    assert run(["doctor"]) == 0


# ------------------------------------------------------------------------ agent

def test_agent_session_metadata(repo):
    run(["init", "--yes"])
    run(["start", "agent work", "--agent", "claude-code", "--model", "opus-4.8", "--tool", "Edit"])
    sid = active_session_id(repo)
    sess = read_json(repo / ".checkpoint" / "sessions" / sid / "session.json")
    assert sess["actor"]["type"] == "agent"
    assert sess["agent"]["name"] == "claude-code"
    assert sess["agent"]["model"] == "opus-4.8"
    assert sess["agent"]["tool"] == "Edit"
    assert sess["agent"]["prompt"] == "agent work"
