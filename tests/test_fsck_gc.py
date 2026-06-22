"""Phase 4 tests: object GC + fsck. Run in non-git dirs (no Git dependency)."""
import os
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


def commit(repo, path, content, msg):
    (repo / path).write_text(content)
    run(["start", msg]); assert run(["accept", "--no-verify", "-m", msg]) == 0


def base_repo(repo):
    run(["init", "--email", "j@e.com"])
    commit(repo, "a.txt", "v1\n", "c1")
    commit(repo, "a.txt", "v2\n", "c2")


def objfile(repo, oid):
    return core(repo).paths.objects / oid[:2] / oid


def backdate(repo, oid, days=30):
    p = objfile(repo, oid)
    t = time.time() - days * 86400
    os.utime(p, (t, t))


def plant_orphan(repo, content=b"orphan garbage\n", days=30):
    oid = core(repo).put_blob(content)
    backdate(repo, oid, days)
    return oid


def a_blob(repo):
    import checkpoint_core.reachable as R
    r = core(repo)
    for oid in R.iter_object_ids(r):
        if R.classify(r, oid)[0] == "blob":
            return oid
    raise AssertionError("no blob found")


def a_tree(repo):
    import checkpoint_core.reachable as R
    r = core(repo)
    for oid in R.iter_object_ids(r):
        if R.classify(r, oid)[0] == "tree":
            return oid
    raise AssertionError("no tree found")


# --------------------------------------------------------------------- fsck good

def test_fsck_healthy(repo):
    base_repo(repo)
    assert run(["fsck"]) == 0


def test_fsck_healthy_without_git(repo, monkeypatch):
    base_repo(repo)
    safe = repo / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    assert run(["fsck"]) == 0
    assert run(["gc", "--dry-run"]) == 0


# --------------------------------------------------------------- fsck corruption

def test_fsck_detects_rewritten_blob(repo):
    base_repo(repo)
    objfile(repo, a_blob(repo)).write_bytes(b"TAMPERED\n")
    assert run(["fsck"]) == 2


def test_fsck_detects_missing_blob_in_tree(repo):
    base_repo(repo)
    objfile(repo, a_blob(repo)).unlink()  # a blob a tree points to
    assert run(["fsck"]) == 2


def test_fsck_detects_missing_tree_in_snapshot(repo):
    base_repo(repo)
    objfile(repo, a_tree(repo)).unlink()
    assert run(["fsck"]) == 2


def test_fsck_detects_broken_parent_chain(repo):
    from checkpoint_core import objects, util
    base_repo(repo)
    r = core(repo)
    snap = objects.sign(objects.make_snapshot(
        tree=r.head_tree(), parents=["0" * 64], session=None,
        kind="accepted", message="orphan parent", author=r.identity(),
        timestamp=util.now_iso()), "x")
    oid = r.put_object(snap)
    r.update_ref("refs/tags/bad", oid)
    assert run(["fsck"]) == 2


def test_fsck_detects_invalid_branch_head(repo):
    base_repo(repo)
    core(repo).update_ref("refs/heads/main", "0" * 64)
    assert run(["fsck"]) == 2


def test_fsck_detects_seal_mismatch(repo):
    from checkpoint_core import objects, util
    base_repo(repo)
    r = core(repo)
    snap = objects.make_snapshot(tree=r.head_tree(), parents=[], session=None,
                                 kind="accepted", message="bad seal", author=r.identity(),
                                 timestamp=util.now_iso())
    snap["signature"] = {"algo": "sha256-seal", "author": "x", "seal": "deadbeef"}
    oid = r.put_object(snap)            # valid content hash, invalid seal
    r.update_ref("refs/tags/v", oid)
    assert run(["fsck"]) == 2


def test_fsck_detects_malformed_session_json(repo):
    base_repo(repo)
    sid = core(repo).session_ids()[0]
    (core(repo).paths.session_dir(sid) / "session.json").write_text("{not json")
    assert run(["fsck"]) == 2


def test_fsck_detects_broken_rename_record(repo):
    import json
    run(["init", "--email", "j@e.com"])
    (repo / "a.py").write_text("def f():\n    return 1\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["start", "move"])
    (repo / "a.py").rename(repo / "b.py")
    run(["packet"])
    sid = core(repo).active_session_id()
    pkt_path = core(repo).paths.session_dir(sid) / "packet.json"
    pkt = json.loads(pkt_path.read_text())
    pkt["rename_records"][0]["new_blob_id"] = "0" * 64
    pkt_path.write_text(json.dumps(pkt))
    assert run(["fsck"]) == 2


def test_fsck_strict_fails_on_dangling(repo):
    base_repo(repo)
    plant_orphan(repo)
    assert run(["fsck"]) == 0          # non-strict tolerates dangling
    assert run(["fsck", "--strict"]) == 2


# ------------------------------------------------------------------------- gc

def test_gc_dry_run_deletes_nothing(repo):
    base_repo(repo)
    oid = plant_orphan(repo)
    assert run(["gc", "--dry-run"]) == 0
    assert core(repo).has_object(oid)  # still present


def test_gc_deletes_unreachable_old_blob(repo):
    base_repo(repo)
    oid = plant_orphan(repo)
    assert run(["gc"]) == 0
    assert not core(repo).has_object(oid)


def test_gc_keeps_branch_head_history(repo):
    import checkpoint_core.reachable as R
    base_repo(repo)
    plant_orphan(repo)
    r = core(repo)
    head = r.head_snapshot()
    head_tree = r.head_tree()
    run(["gc"])
    assert r.has_object(head) and r.has_object(head_tree)
    assert run(["verify-history"]) == 0


def test_gc_keeps_tagged_snapshot(repo):
    from checkpoint_core import objects, util
    base_repo(repo)
    r = core(repo)
    # an accepted snapshot referenced ONLY by a tag (not on any branch)
    snap = objects.sign(objects.make_snapshot(
        tree=r.head_tree(), parents=[], session=None, kind="accepted",
        message="tagged only", author=r.identity(), timestamp=util.now_iso()), "x")
    oid = r.put_object(snap)
    r.update_ref("refs/tags/v1", oid)
    backdate(repo, oid, 30)
    assert run(["gc"]) == 0
    assert core(repo).has_object(oid)  # protected by the tag


def test_gc_keeps_active_session_autosaves(repo):
    from checkpoint_core import autosave as A
    from checkpoint_core.session import Session
    run(["init", "--email", "j@e.com"])
    commit(repo, "a.txt", "base\n", "c1")
    run(["start", "active work"])      # session stays active
    (repo / "a.txt").write_text("draft\n")
    rec = A.create_autosave(core(repo), Session.active(core(repo)), reason="edit")
    tree = rec["tree_id"]
    backdate(repo, tree, 60)           # old, but session is ACTIVE
    # force keep_autosaves_days to 0 so only "active" protection matters
    r = core(repo); r.config.data["gc"]["keep_autosaves_days"] = 0
    # use the API so our mutated config is honored
    from checkpoint_core import gc as gcmod
    gcmod.collect(r, dry_run=False, force=True)
    assert r.has_object(tree)


def test_gc_respects_autosave_retention(repo):
    from checkpoint_core import autosave as A, gc as gcmod, util
    from checkpoint_core.session import Session
    run(["init", "--email", "j@e.com"])
    commit(repo, "a.txt", "base\n", "c1")
    run(["start", "work"])
    sid = core(repo).active_session_id()   # capture the work session before accept clears it
    (repo / "a.txt").write_text("intermediate-draft\n")
    rec = A.create_autosave(core(repo), Session.active(core(repo)), reason="edit")
    tree = rec["tree_id"]
    # finish the session so it is no longer active
    (repo / "a.txt").write_text("final\n")
    run(["accept", "--no-verify", "-m", "done"])
    # the intermediate autosave tree is unique (not the accepted tree)
    assert core(repo).has_object(tree)
    # backdate the autosave record so it falls outside retention, and the object for grace
    sess = Session.load(core(repo), sid)
    aid = sess.data["autosaves"][0]
    arec_path = sess.dir / "autosaves" / aid / "autosave.json"
    arec = util.read_json(arec_path)
    from datetime import timedelta
    arec["timestamp"] = (util.now() - timedelta(days=60)).isoformat()
    util.write_json(arec_path, arec)
    backdate(repo, tree, 60)
    r = core(repo)
    r.config.data["gc"]["keep_autosaves_days"] = 14
    r.config.data["gc"]["grace_period_days"] = 14
    gcmod.collect(r, dry_run=False, force=True)
    assert not r.has_object(tree)      # aged-out autosave tree collected


def test_gc_refuses_on_corruption(repo):
    base_repo(repo)
    objfile(repo, a_blob(repo)).write_bytes(b"X\n")
    assert run(["gc"]) == 1            # aborts due to fsck corruption


def test_gc_records_ledger_event(repo):
    import json
    base_repo(repo)
    plant_orphan(repo)
    run(["gc"])
    events = [json.loads(l) for l in (core(repo).paths.ledger).read_text().splitlines() if l.strip()]
    assert any(e["event_type"] == "gc" for e in events)


def test_accepted_history_byte_identical_after_gc(repo):
    import checkpoint_core.reachable as R
    base_repo(repo)
    plant_orphan(repo)
    r = core(repo)
    reachable = R.compute_reachable(r)["reachable"]
    before = {oid: R.load_raw(r, oid) for oid in reachable if r.has_object(oid)}
    run(["gc"])
    for oid, raw in before.items():
        assert r.has_object(oid), "reachable object {} was deleted".format(oid)
        assert R.load_raw(r, oid) == raw, "reachable object {} changed".format(oid)
    assert run(["verify-history"]) == 0


def test_gc_works_without_git(repo, monkeypatch):
    base_repo(repo)
    oid = plant_orphan(repo)
    safe = repo / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    assert run(["gc"]) == 0
    assert not core(repo).has_object(oid)


# --------------------------------------------------------------------- objects

def test_objects_stats(repo, capsys):
    base_repo(repo)
    assert run(["objects", "stats"]) == 0
    out = capsys.readouterr().out
    assert "blob" in out and "tree" in out and "snapshot_accepted" in out
    assert "TOTAL" in out and "bytes" in out


def test_objects_show_blob_tree_snapshot(repo, capsys):
    base_repo(repo)
    r = core(repo)
    # snapshot
    capsys.readouterr()
    assert run(["objects", "show", r.head_snapshot()]) == 0
    out = capsys.readouterr().out
    assert "type:      snapshot" in out and "seal:" in out
    # tree
    assert run(["objects", "show", a_tree(repo)]) == 0
    assert "type:      tree" in capsys.readouterr().out
    # blob
    assert run(["objects", "show", a_blob(repo)]) == 0
    assert "type:      blob" in capsys.readouterr().out


def test_objects_list_reachability(repo, capsys):
    base_repo(repo)
    plant_orphan(repo)
    assert run(["objects", "list", "--unreachable"]) == 0
    out = capsys.readouterr().out
    assert "UNREACHABLE" in out


def test_fsck_allows_json_blob_with_type_field(repo):
    """A captured package.json with {"type":"module"} is blob content, not a corrupt
    object — fsck must not warn 'unknown type module'. (Regression: work-hub.)"""
    from checkpoint_core import fsck as fsckmod
    run(["init", "--email", "j@e.com"])
    (repo / "package.json").write_text('{\n  "name": "x",\n  "type": "module"\n}\n')
    run(["start", "add pkg"])
    assert run(["accept", "--no-verify", "-m", "add pkg"]) == 0
    rep = fsckmod.check(core(repo), strict=False)
    assert not any("unknown type" in w for w in rep["warnings"]), rep["warnings"]
    assert rep["result"] == "healthy"
