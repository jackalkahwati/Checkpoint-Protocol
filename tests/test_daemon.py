"""Phase 2 tests: background autosave daemon, timeline, recovery, GC.

Run in plain directories that are NOT git repos, proving the daemon needs no Git.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def core(repo):
    from checkpoint_core.store import Repo
    return Repo(repo)


def active(repo):
    from checkpoint_core.session import Session
    return Session.active(core(repo))


def make_watcher(repo, **kw):
    from checkpoint_core.watcher import Watcher
    return Watcher(core(repo), active(repo), **kw)


# --------------------------------------------------------------- watch / debounce

def test_watch_creates_autosaves(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "work"])
    w = make_watcher(repo, debounce_ms=1000, poll_ms=10)
    (repo / "a.txt").write_text("v2\n")
    assert w.poll_once(0) is None          # edit detected, debounce starts
    rec = w.poll_once(2000)                # quiescent past debounce -> autosave
    assert rec is not None
    assert rec["autosave_id"].startswith("auto_")
    assert "a.txt" in rec["changed_paths"]


def test_rapid_edits_are_debounced(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("0\n")
    run(["start", "work"])
    w = make_watcher(repo, debounce_ms=1000, poll_ms=10)
    # a burst of edits, each within the debounce window
    for i, t in enumerate([0, 200, 400, 600, 800]):
        (repo / "a.txt").write_text("edit{}\n".format(i))
        assert w.poll_once(t) is None      # never autosaves mid-burst
    rec = w.poll_once(1900)                 # quiet for >1000ms -> exactly one autosave
    assert rec is not None
    assert w.autosaves_created == 1
    assert (repo / "a.txt").read_text() == "edit4\n"  # captured the final state


# ----------------------------------------------- isolation from accepted history

def test_autosave_does_not_alter_history_or_branch(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    r = core(repo)
    head_before = r.head_snapshot()
    branch_ref_before = r.read_ref("refs/heads/main")
    # new session + several autosaves
    run(["start", "more work"])
    sess = active(repo)
    for i in range(3):
        (repo / "a.txt").write_text("draft{}\n".format(i))
        A.create_autosave(r, sess, reason="edit")
    # history and branch head are untouched by autosaves
    assert r.head_snapshot() == head_before
    assert r.read_ref("refs/heads/main") == branch_ref_before
    # autosaves are not accepted snapshots
    assert len(r.history()) == 1


def test_verify_history_ignores_autosaves(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["start", "draft"])
    sess = active(repo)
    (repo / "a.txt").write_text("draft\n")
    rec = A.create_autosave(core(repo), sess, reason="edit")
    # tamper the autosave seal — must NOT affect accepted-history verification
    d = sess.dir / "autosaves" / rec["autosave_id"] / "autosave.json"
    from checkpoint_core import util
    obj = util.read_json(d); obj["changed_paths"] = ["tampered"]; util.write_json(d, obj)
    assert not A.verify_seal(util.read_json(d))   # autosave seal breaks
    assert run(["verify-history"]) == 0           # accepted history still valid


# ----------------------------------------------------------------- ignore rules

def test_autosave_respects_ignore_rules(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / ".checkpointignore").write_text("*.log\n")
    run(["start", "work"])
    (repo / "keep.txt").write_text("keep\n")
    (repo / "noisy.log").write_text("noise\n")
    rec = A.create_autosave(core(repo), active(repo), reason="edit")
    assert "keep.txt" in rec["changed_paths"]
    assert "noisy.log" not in rec["changed_paths"]


# ---------------------------------------------------------------- binary + restore

def test_binary_file_captured_and_restored(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    run(["start", "work"])
    original = b"\x00\x01\x02BINARY\xff\xfe"
    (repo / "img.bin").write_bytes(original)
    rec = A.create_autosave(core(repo), active(repo), reason="edit")
    assert "img.bin" in rec["changed_paths"]
    # corrupt the file, then restore from autosave
    (repo / "img.bin").write_bytes(b"corrupted")
    A.restore_autosave(core(repo), active(repo), rec["autosave_id"])
    assert (repo / "img.bin").read_bytes() == original


def test_autosave_restore_returns_state(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("good\n")
    run(["start", "work"])
    rec = A.create_autosave(core(repo), active(repo), reason="edit")
    (repo / "a.txt").write_text("bad\n")
    assert run(["autosave", "restore", rec["autosave_id"], "--yes"]) == 0
    assert (repo / "a.txt").read_text() == "good\n"


# ------------------------------------------------------------------- recovery

def test_interrupted_session_can_be_recovered(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "work.txt").write_text("starting\n")
    run(["start", "long task"])
    (repo / "work.txt").write_text("important progress\n")
    A.create_autosave(core(repo), active(repo), reason="edit")
    # simulate a crash that lost in-flight edits
    (repo / "work.txt").write_text("LOST\n")
    # recover restores the latest autosave
    assert run(["recover", "--restore", "--yes"]) == 0
    assert (repo / "work.txt").read_text() == "important progress\n"


def test_recover_without_active_session_is_noop(repo):
    run(["init", "--email", "j@e.com"])
    assert run(["recover"]) == 0


# ------------------------------------------------------------------- timeline

def test_timeline_shows_full_session_story(repo, capsys):
    from checkpoint_core import timeline
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "build feature"])
    (repo / "a.txt").write_text("v2\n")
    run(["snapshot", "-m", "checkpoint"])
    run(["verify"])  # no commands -> skipped run, still a timeline event
    run(["accept", "--no-verify", "-m", "done"])
    sid = core(repo).session_ids()[0]
    events = [e["type"] for e in timeline.read(core(repo), sid)]
    assert "session_started" in events
    assert "snapshot_created" in events
    assert "verification_run" in events
    assert "accepted" in events
    capsys.readouterr()
    assert run(["timeline", sid]) == 0
    out = capsys.readouterr().out
    assert "build feature" in out and "ACCEPT" in out


# ------------------------------------------------------------------------ gc

def test_gc_removes_old_autosaves_not_accepted_history(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("base\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    head_before = core(repo).head_snapshot()
    run(["start", "draft"])
    r = core(repo); sess = active(repo)
    # create several distinct autosaves
    ids = []
    for i in range(4):
        (repo / "a.txt").write_text("d{}\n".format(i))
        rec = A.create_autosave(r, sess, reason="edit")
        assert rec is not None
        ids.append(rec["autosave_id"])
    # force aggressive GC: keep only the last, treat everything as old
    r.config.data["autosave"]["gc"] = {"keep_last": 1, "keep_for_days": 0}
    removed = A.gc(r, sess)
    assert len(removed) == 3
    remaining = [a["autosave_id"] for a in A.list_autosaves(r, sess)]
    assert remaining == [ids[-1]]
    # the removed autosave dirs are gone
    for aid in ids[:-1]:
        assert not (sess.dir / "autosaves" / aid).exists()
    # accepted history is untouched
    assert core(repo).head_snapshot() == head_before
    assert len(core(repo).history()) == 1
    assert run(["verify-history"]) == 0


# ------------------------------------------------ no-Git operation (structural)

def test_daemon_modules_do_not_import_git_bridge():
    import checkpoint_core.autosave as a
    import checkpoint_core.watcher as w
    import checkpoint_core.timeline as t
    for mod in (a, w, t):
        assert "gitbridge" not in dir(mod), "{} must not depend on the git bridge".format(mod.__name__)


def test_autosave_works_with_git_removed_from_path(repo, monkeypatch):
    # Strip git from PATH entirely; the daemon path must not care.
    safe = repo / "_nogit_bin"
    safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "no git work"])
    (repo / "a.txt").write_text("v2\n")
    rec = A.create_autosave(core(repo), active(repo), reason="edit")
    assert rec is not None
    (repo / "a.txt").write_text("oops\n")
    A.restore_autosave(core(repo), active(repo), rec["autosave_id"])
    assert (repo / "a.txt").read_text() == "v2\n"


def test_autosave_seal_is_valid(repo):
    from checkpoint_core import autosave as A
    run(["init", "--email", "j@e.com"])
    run(["start", "work"])
    (repo / "a.txt").write_text("hello\n")
    rec = A.create_autosave(core(repo), active(repo), reason="edit")
    assert A.verify_seal(rec)
