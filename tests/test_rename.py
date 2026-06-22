"""Phase 3 tests: native rename detection in diff, merge, and packets.

Run in plain directories that are NOT git repos — rename detection never calls Git.
"""
import sys
import time
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


def diff(repo, detect=True):
    """Diff the active session base -> current working tree."""
    from checkpoint_core.diff import diff_result
    from checkpoint_core.session import Session
    from checkpoint_core.worktree import scan_to_tree
    r = core(repo)
    sess = Session.active(r)
    return diff_result(r, sess.base_tree, scan_to_tree(r), detect_renames=detect)


# --------------------------------------------------------------------- diff cases

def test_exact_rename_is_rename_not_add_delete(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.py").write_text("def f():\n    return 1\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.py").rename(repo / "b.py")
    dr = diff(repo)
    assert dr["added"] == [] and dr["deleted"] == []
    assert len(dr["renamed"]) == 1
    r = dr["renamed"][0]
    assert (r["old_path"], r["new_path"]) == ("a.py", "b.py")
    assert r["kind"] == "exact" and r["similarity"] == 1.0


def test_rename_plus_edit_shows_rename_with_diff(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.py").write_text("l1\nl2\nl3\nl4\nl5\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move+edit"])
    (repo / "a.py").unlink()
    (repo / "b.py").write_text("l1\nl2\nCHANGED\nl4\nl5\n")
    dr = diff(repo)
    assert dr["added"] == [] and dr["deleted"] == []
    assert len(dr["renamed"]) == 1
    r = dr["renamed"][0]
    assert (r["old_path"], r["new_path"]) == ("a.py", "b.py")
    assert r["kind"] == "rename_edit"
    assert 0.60 <= r["similarity"] < 1.0
    from checkpoint_core.diff import unified_result
    from checkpoint_core.session import Session
    from checkpoint_core.worktree import scan_to_tree
    rr = core(repo)
    text = unified_result(rr, Session.active(rr).base_tree, scan_to_tree(rr))
    assert "rename a.py => b.py" in text
    assert "CHANGED" in text  # content diff shown


def test_binary_exact_rename(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "img.bin").write_bytes(b"\x00\x01\x02\xff" * 50)
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "img.bin").rename(repo / "image.bin")
    dr = diff(repo)
    assert len(dr["renamed"]) == 1
    assert dr["renamed"][0]["kind"] == "exact"


def test_binary_similar_rename_not_attempted(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.bin").write_bytes(b"\x00" * 1000 + b"AAAA")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.bin").unlink()
    (repo / "b.bin").write_bytes(b"\x00" * 1000 + b"BBBB")  # similar but not identical binary
    dr = diff(repo)
    # similarity is not attempted for binary -> stays add/delete
    assert dr["renamed"] == []
    assert dr["added"] == ["b.bin"] and dr["deleted"] == ["a.bin"]


def test_below_threshold_stays_add_delete(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("apple\nbanana\ncherry\ndate\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.txt").unlink()
    (repo / "b.txt").write_text("xylophone\nzebra\nquasar\nnebula\n")  # unrelated
    dr = diff(repo)
    assert dr["renamed"] == []
    assert dr["added"] == ["b.txt"] and dr["deleted"] == ["a.txt"]


def test_directory_rename_detected(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "lib").mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (repo / "lib" / name).write_text("content of {}\n".format(name))
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move dir"])
    (repo / "core").mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (repo / "lib" / name).rename(repo / "core" / name)
    (repo / "lib").rmdir()
    dr = diff(repo)
    assert len(dr["renamed"]) == 3
    assert dr["added"] == [] and dr["deleted"] == []
    assert any(d["old_dir"] == "lib" and d["new_dir"] == "core" and d["count"] == 3
               for d in dr["directory_renames"])


# --------------------------------------------------------------------- merge cases

def _setup_merge(repo):
    run(["init", "--email", "j@e.com"])


def _branch_edit_accept(repo, branch, fn, msg):
    run(["checkout", branch]); fn(); run(["start", msg]); run(["accept", "--no-verify", "-m", msg])


def test_merge_one_side_renames_other_unchanged(repo):
    _setup_merge(repo)
    (repo / "f.txt").write_text("hello\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "f.txt").rename(repo / "g.txt")
    run(["start", "rename"]); run(["accept", "--no-verify", "-m", "rename"])
    # main makes an unrelated change so it isn't a fast-forward
    run(["checkout", "main"])
    (repo / "other.txt").write_text("x\n")
    run(["start", "other"]); run(["accept", "--no-verify", "-m", "other"])
    assert run(["merge", "dev"]) == 0
    assert (repo / "g.txt").exists() and not (repo / "f.txt").exists()


def test_merge_rename_one_side_edit_other_auto_merges(repo):
    _setup_merge(repo)
    (repo / "m.py").write_text("a\nb\nc\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "m.py").rename(repo / "renamed.py")
    run(["start", "rename"]); run(["accept", "--no-verify", "-m", "rename"])
    run(["checkout", "main"])
    (repo / "m.py").write_text("a\nb\nC-edited\n")
    run(["start", "edit"]); run(["accept", "--no-verify", "-m", "edit"])
    assert run(["merge", "dev"]) == 0
    assert (repo / "renamed.py").read_text() == "a\nb\nC-edited\n"
    assert not (repo / "m.py").exists()
    assert run(["verify-history"]) == 0


def test_merge_both_rename_to_same_path(repo):
    _setup_merge(repo)
    (repo / "f.txt").write_text("l1\nl2\nl3\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "f.txt").unlink(); (repo / "renamed.txt").write_text("l1\nl2\nl3\n")  # rename only
    run(["start", "r1"]); run(["accept", "--no-verify", "-m", "r1"])
    run(["checkout", "main"])
    (repo / "f.txt").unlink(); (repo / "renamed.txt").write_text("TOP\nl2\nl3\n")  # rename + edit
    run(["start", "r2"]); run(["accept", "--no-verify", "-m", "r2"])
    assert run(["merge", "dev"]) == 0
    assert (repo / "renamed.txt").exists()


def test_merge_both_rename_different_paths_conflicts(repo):
    _setup_merge(repo)
    (repo / "f.txt").write_text("x\ny\nz\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "f.txt").rename(repo / "dev_name.txt")
    run(["start", "r1"]); run(["accept", "--no-verify", "-m", "r1"])
    run(["checkout", "main"])
    (repo / "f.txt").rename(repo / "main_name.txt")
    run(["start", "r2"]); run(["accept", "--no-verify", "-m", "r2"])
    assert run(["merge", "dev"]) == 1  # rename/rename conflict
    # both versions preserved on disk
    assert (repo / "main_name.txt").exists() and (repo / "dev_name.txt").exists()


def test_merge_rename_delete_conflict(repo):
    _setup_merge(repo)
    (repo / "doc.txt").write_text("data\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "doc.txt").rename(repo / "moved.txt")
    run(["start", "rename"]); run(["accept", "--no-verify", "-m", "rename"])
    run(["checkout", "main"])
    (repo / "doc.txt").unlink()
    run(["start", "delete"]); run(["accept", "--no-verify", "-m", "delete"])
    assert run(["merge", "dev"]) == 1  # rename/delete conflict


def test_merge_directory_rename_plus_file_edit(repo):
    _setup_merge(repo)
    (repo / "lib").mkdir()
    for n in ("a.txt", "b.txt", "c.txt"):
        (repo / "lib" / n).write_text("{}-l1\n{}-l2\n".format(n, n))
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    # dev moves lib/ -> core/
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "core").mkdir()
    for n in ("a.txt", "b.txt", "c.txt"):
        (repo / "lib" / n).rename(repo / "core" / n)
    (repo / "lib").rmdir()
    run(["start", "move dir"]); run(["accept", "--no-verify", "-m", "move dir"])
    # main edits a file in the old location
    run(["checkout", "main"])
    (repo / "lib" / "a.txt").write_text("a.txt-l1\na.txt-EDITED\n")
    run(["start", "edit a"]); run(["accept", "--no-verify", "-m", "edit a"])
    assert run(["merge", "dev"]) == 0
    # edit applied at the new (moved) location
    assert (repo / "core" / "a.txt").read_text() == "a.txt-l1\na.txt-EDITED\n"
    assert not (repo / "lib" / "a.txt").exists()
    assert run(["verify-history"]) == 0


# ------------------------------------------------------------------------ packet

def test_packet_includes_rename_records(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.py").write_text("def f():\n    return 1\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.py").rename(repo / "b.py")
    run(["packet"])
    import json
    from checkpoint_core.store import Repo
    sid = Repo(repo).active_session_id()
    pkt = json.loads((repo / ".checkpoint" / "sessions" / sid / "packet.json").read_text())
    assert any(f["status"] == "renamed" and f.get("from") == "a.py" and f["path"] == "b.py"
               for f in pkt["changed_files"])
    assert len(pkt["rename_records"]) == 1


# ----------------------------------------------------------------- no-git + perf

def test_rename_detection_without_git(repo, monkeypatch):
    safe = repo / "_nogit"
    safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    run(["init", "--email", "j@e.com"])
    (repo / "a.py").write_text("hello\nworld\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.py").rename(repo / "b.py")
    dr = diff(repo)
    assert len(dr["renamed"]) == 1


def test_rename_detection_bounded_for_large_changesets(repo):
    """Many unrelated add/deletes must not explode into O(n^2) similarity work."""
    run(["init", "--email", "j@e.com"])
    old = repo / "old"; old.mkdir()
    N = 150
    for i in range(N):
        (old / "f{}.txt".format(i)).write_text("old-unique-content-{}\n".format(i) * 3)
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "replace"])
    # delete all of old/, add an entirely different set (no real renames)
    for i in range(N):
        (old / "f{}.txt".format(i)).unlink()
    old.rmdir()
    new = repo / "new"; new.mkdir()
    for i in range(N):
        (new / "g{}.txt".format(i)).write_text("brand-new-distinct-text-{}\n".format(i) * 3)
    t0 = time.time()
    dr = diff(repo)
    elapsed = time.time() - t0
    # N*N = 22500 > default max_candidates (10000) -> similarity skipped, stays add/delete
    assert dr["renamed"] == []
    assert len(dr["added"]) == N and len(dr["deleted"]) == N
    assert elapsed < 10.0  # bounded, not pathological
