"""Phase 6 tests: hardened remote sync. Run in non-git dirs (no Git dependency)."""
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


def core(p):
    from checkpoint_core.store import Repo
    return Repo(p)


@pytest.fixture(autouse=True)
def nocolor(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")


def src_repo(path, commits=2, signed=True):
    """Init + (optional) identity + N signed commits at `path`. Returns identity_id or None."""
    path.mkdir(parents=True, exist_ok=True)
    import os
    cwd = os.getcwd()
    os.chdir(path)
    try:
        run(["init"])
        ident = None
        if signed:
            from checkpoint_core import identity as I
            ident = I.create(core(path), name="Jack", id_type="human")["identity_id"]
        for i in range(commits):
            (path / "f.txt").write_text("v{}\n".format(i))
            run(["start", "c{}".format(i)])
            run(["accept", "--no-verify", "-m", "c{}".format(i)])
        return ident
    finally:
        os.chdir(cwd)


def add_origin(repo_path, remote_path):
    run(["remote", "add", "origin", "--type", "filesystem", "--path", str(remote_path)])


def make_bundle(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))


# --------------------------------------------------------------------- clone

def test_clone_filesystem_without_git(tmp_path, monkeypatch):
    a = tmp_path / "a"
    src_repo(a)
    safe = tmp_path / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    dest = tmp_path / "clone"
    monkeypatch.chdir(tmp_path)
    assert run(["clone", str(a), str(dest)]) == 0
    assert (dest / "f.txt").exists()
    monkeypatch.chdir(dest)
    assert run(["fsck"]) == 0
    assert run(["verify-signatures"]) == 0


def test_clone_preserves_history_and_signatures(tmp_path, monkeypatch):
    a = tmp_path / "a"; sid = src_repo(a)
    dest = tmp_path / "clone"
    monkeypatch.chdir(tmp_path)
    run(["clone", str(a), str(dest)])
    assert core(dest).head_snapshot() == core(a).head_snapshot()
    from checkpoint_core import sign as S
    head = core(dest).head_snapshot()
    assert S.verify_record(core(dest), S.signatures_for(core(dest), head)[0])["ok"]


def test_clone_transfers_public_identity_not_private_key(tmp_path, monkeypatch):
    a = tmp_path / "a"; sid = src_repo(a)
    dest = tmp_path / "clone"
    monkeypatch.chdir(tmp_path)
    run(["clone", str(a), str(dest)])
    from checkpoint_core import identity as I
    assert I.load(core(dest), sid) is not None          # public identity transferred
    assert I.load(core(dest), sid)["trusted"] is False  # imported untrusted
    assert not I.has_private(core(dest), sid)            # private key NOT transferred
    assert not (core(dest).paths.keys / (sid + ".key")).exists()


# --------------------------------------------------------------------- fetch

def test_fetch_writes_tracking_ref_not_local_branch(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    assert run(["fetch", "origin"]) == 0
    assert core(b).read_ref("refs/remotes/origin/main") == core(a).head_snapshot()
    assert core(b).read_ref("refs/heads/main") is None   # local branch untouched


def test_fetch_copies_only_missing(tmp_path, monkeypatch):
    from checkpoint_core import remote as RM
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    r1 = RM.fetch(core(b), "origin")
    assert r1["objects_copied"] > 0
    r2 = RM.fetch(core(b), "origin")
    assert r2["objects_copied"] == 0                     # nothing new the second time


def test_fetch_dry_run_changes_nothing(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    assert run(["fetch", "origin", "--dry-run"]) == 0
    assert core(b).read_ref("refs/remotes/origin/main") is None


def test_fetched_objects_survive_gc(tmp_path, monkeypatch):
    # remote-tracking refs are part of reachability
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    run(["fetch", "origin"])
    head = core(b).read_ref("refs/remotes/origin/main")
    assert run(["gc", "--aggressive"]) == 0
    assert core(b).has_object(head)                       # not collected
    assert run(["fsck"]) == 0


# --------------------------------------------------------------------- pull

def test_pull_fast_forwards(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    assert run(["pull", "origin", "main"]) == 0
    assert core(b).head_snapshot() == core(a).head_snapshot()
    assert (b / "f.txt").exists()


def test_pull_refuses_divergent(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "clone"
    monkeypatch.chdir(tmp_path); run(["clone", str(a), str(b)])
    # diverge: a gets a new commit, b gets a different new commit
    monkeypatch.chdir(a)
    (a / "f.txt").write_text("A-side\n"); run(["start", "ca"]); run(["accept", "--no-verify", "-m", "ca"])
    monkeypatch.chdir(b)
    (b / "f.txt").write_text("B-side\n"); run(["start", "cb"]); run(["accept", "--no-verify", "-m", "cb"])
    assert run(["pull", "origin", "main"]) == 1          # divergent -> refuse


def test_pull_dry_run_changes_nothing(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"])
    add_origin(b, a)
    assert run(["pull", "origin", "main", "--dry-run"]) == 0
    assert core(b).read_ref("refs/heads/main") is None
    assert core(b).read_ref("refs/remotes/origin/main") is None


# --------------------------------------------------------------------- push

def test_push_sends_missing_and_updates_remote(tmp_path, monkeypatch):
    b = tmp_path / "remote"; b.mkdir();
    import os; cwd = os.getcwd(); os.chdir(b); run(["init"]); os.chdir(cwd)
    a = tmp_path / "a"; src_repo(a)
    monkeypatch.chdir(a); add_origin(a, b)
    assert run(["push", "origin", "main"]) == 0
    assert core(b).read_ref("refs/heads/main") == core(a).head_snapshot()


def test_push_rejects_non_fast_forward(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    run(["push", "origin", "main"])
    # remote advances independently (clone remote, commit, push back)
    c = tmp_path / "c"; monkeypatch.chdir(tmp_path); run(["clone", str(b), str(c)])
    monkeypatch.chdir(c); add_origin(c, b)
    (c / "f.txt").write_text("remote-advance\n"); run(["start", "rc"]); run(["accept", "--no-verify", "-m", "rc"])
    run(["push", "origin", "main"])
    # now a is behind; a makes its own commit and tries to push -> non-ff
    monkeypatch.chdir(a)
    (a / "f.txt").write_text("a-advance\n"); run(["start", "ac"]); run(["accept", "--no-verify", "-m", "ac"])
    assert run(["push", "origin", "main"]) == 1


def test_push_force_with_lease(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    run(["push", "origin", "main"])
    # remote diverges (another clone advances it), without `a` fetching
    c = tmp_path / "c"; monkeypatch.chdir(tmp_path); run(["clone", str(b), str(c)])
    monkeypatch.chdir(c); add_origin(c, b)
    (c / "f.txt").write_text("remote-side\n"); run(["start", "rc"]); run(["accept", "--no-verify", "-m", "rc"])
    run(["push", "origin", "main"])
    # a makes its own divergent commit (still believes remote == its tracking ref)
    monkeypatch.chdir(a)
    (a / "f.txt").write_text("a-side\n"); run(["start", "ac"]); run(["accept", "--no-verify", "-m", "ac"])
    assert run(["push", "origin", "main"]) == 1                          # non-fast-forward
    # honest stale lease (a believes remote is its old tracking ref) -> rejected
    assert run(["push", "origin", "main", "--force-with-lease"]) == 1
    # after fetching, the lease matches the real remote head -> force succeeds
    run(["fetch", "origin"])
    assert run(["push", "origin", "main", "--force-with-lease"]) == 0
    assert core(b).read_ref("refs/heads/main") == core(a).head_snapshot()


def test_push_dry_run_changes_nothing(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    assert run(["push", "origin", "main", "--dry-run"]) == 0
    assert core(b).read_ref("refs/heads/main") is None


# --------------------------------------------------------------------- tags

def test_tags_push_fetch_verify(tmp_path, monkeypatch):
    a = tmp_path / "a"; sid = src_repo(a)
    core(a).update_ref("refs/tags/v1", core(a).head_snapshot())
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    run(["push", "origin", "main", "--tags"])
    assert core(b).read_ref("refs/tags/v1") == core(a).head_snapshot()
    c = tmp_path / "c"; c.mkdir(); monkeypatch.chdir(c); run(["init"]); add_origin(c, b)
    assert run(["fetch", "origin", "--tags"]) == 0
    assert core(c).read_ref("refs/tags/v1") == core(a).head_snapshot()


# --------------------------------------------------------------- sync status / ledger

def test_sync_status_reports_relationship(tmp_path, monkeypatch, capsys):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    capsys.readouterr()
    run(["sync", "status", "origin"])
    assert "ahead" in capsys.readouterr().out          # local has commits, remote empty
    run(["push", "origin", "main"])
    capsys.readouterr()
    run(["sync", "status", "origin"])
    assert "up-to-date" in capsys.readouterr().out


def test_sync_event_recorded_in_ledger(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    b = tmp_path / "remote"; b.mkdir()
    import os; os.chdir(b); run(["init"]); os.chdir(str(a))
    monkeypatch.chdir(a); add_origin(a, b)
    run(["push", "origin", "main"])
    events = [e["event_type"] for e in
              __import__("json").loads("[" + ",".join(core(a).paths.ledger.read_text().splitlines()) + "]")]
    assert "push" in events


# ----------------------------------------------- reject bad remotes (never trust)

def _bad_remote(path, ref_target_builder):
    from checkpoint_core import remote as RM, objects, util
    rr = RM.bootstrap_store(path)
    target = ref_target_builder(rr)
    rr.update_ref("refs/heads/main", target)
    return rr


def test_fetch_rejects_ref_to_non_snapshot(tmp_path, monkeypatch):
    rr_path = tmp_path / "bad"
    _bad_remote(rr_path, lambda rr: rr.put_blob(b"i am a blob, not a snapshot\n"))
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"]); add_origin(b, rr_path)
    assert run(["fetch", "origin"]) == 1
    assert core(b).read_ref("refs/remotes/origin/main") is None   # ref NOT applied


def test_fetch_rejects_missing_parent_chain(tmp_path, monkeypatch):
    from checkpoint_core import objects, util

    def build(rr):
        tree = rr.put_object(objects.make_tree([]))
        snap = objects.sign(objects.make_snapshot(
            tree=tree, parents=["0" * 64], session=None, kind="accepted",
            message="orphan", author={"id": "x"}, timestamp=util.now_iso()), "x")
        return rr.put_object(snap)

    rr_path = tmp_path / "bad"; _bad_remote(rr_path, build)
    b = tmp_path / "b"; b.mkdir(); monkeypatch.chdir(b); run(["init"]); add_origin(b, rr_path)
    assert run(["fetch", "origin"]) == 1
    assert core(b).read_ref("refs/remotes/origin/main") is None


# --------------------------------------------------------------------- bundles

def test_bundle_create_and_import_preserve_history(tmp_path, monkeypatch):
    a = tmp_path / "a"; src_repo(a)
    bundle = tmp_path / "b.tar.gz"
    monkeypatch.chdir(a)
    assert run(["bundle", "create", "--out", str(bundle)]) == 0
    d = tmp_path / "d"; d.mkdir(); monkeypatch.chdir(d); run(["init"])
    assert run(["bundle", "import", str(bundle)]) == 0
    assert core(d).read_ref("refs/heads/main") == core(a).head_snapshot()
    assert run(["fsck"]) == 0


def test_bundle_verify_detects_corrupt_object(tmp_path):
    make_bundle(tmp_path / "bad.tar.gz", {
        "objects/aa/" + "a" * 64: b"content that does not hash to its name",
        "manifest.json": json.dumps({"refs": {}, "tags": {}}).encode(),
    })
    from checkpoint_core import sync as S
    rep = S.verify_bundle(tmp_path / "bad.tar.gz")
    assert not rep["ok"]
    assert any("content-hash" in e for e in rep["errors"])


def test_bundle_import_rejects_path_traversal(tmp_path, monkeypatch):
    make_bundle(tmp_path / "evil.tar.gz", {
        "../escape.txt": b"pwned",
        "manifest.json": json.dumps({"refs": {}}).encode(),
    })
    d = tmp_path / "d"; d.mkdir(); monkeypatch.chdir(d); run(["init"])
    assert run(["bundle", "import", str(tmp_path / "evil.tar.gz")]) == 1
    assert not (tmp_path / "escape.txt").exists()


def test_bundle_import_rejects_private_key(tmp_path, monkeypatch):
    make_bundle(tmp_path / "key.tar.gz", {
        "keys/secret.key": b"\x00" * 32,
        "manifest.json": json.dumps({"refs": {}}).encode(),
    })
    d = tmp_path / "d"; d.mkdir(); monkeypatch.chdir(d); run(["init"])
    assert run(["bundle", "import", str(tmp_path / "key.tar.gz")]) == 1


def test_bundle_import_rejects_malformed_manifest(tmp_path, monkeypatch):
    make_bundle(tmp_path / "m.tar.gz", {"manifest.json": b"{ this is not json"})
    d = tmp_path / "d"; d.mkdir(); monkeypatch.chdir(d); run(["init"])
    assert run(["bundle", "import", str(tmp_path / "m.tar.gz")]) == 1


def test_bundle_import_rejects_pem_private_key_content(tmp_path, monkeypatch):
    make_bundle(tmp_path / "pem.tar.gz", {
        "sessions/s/note.txt": b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n",
        "manifest.json": json.dumps({"refs": {}}).encode(),
    })
    d = tmp_path / "d"; d.mkdir(); monkeypatch.chdir(d); run(["init"])
    assert run(["bundle", "import", str(tmp_path / "pem.tar.gz")]) == 1


# ----------------------------------------------------------- autosave transfer

def test_autosaves_not_transferred_by_default(tmp_path, monkeypatch):
    from checkpoint_core import autosave as A
    from checkpoint_core.session import Session
    a = tmp_path / "a"; a.mkdir()
    import os; os.chdir(a); run(["init"])
    (a / "f.txt").write_text("base\n"); run(["start", "c0"]); run(["accept", "--no-verify", "-m", "c0"])
    run(["start", "work"])
    (a / "f.txt").write_text("draft\n")
    A.create_autosave(core(a), Session.active(core(a)), reason="edit")
    (a / "f.txt").write_text("final\n"); run(["accept", "--no-verify", "-m", "c1"])
    os.chdir(str(tmp_path))
    dest = tmp_path / "clone"; monkeypatch.chdir(tmp_path); run(["clone", str(a), str(dest)])
    for sid in core(dest).session_ids():
        assert not (core(dest).paths.session_dir(sid) / "autosaves").exists()


def test_autosaves_transferred_when_enabled(tmp_path, monkeypatch):
    from checkpoint_core import autosave as A, remote as RM
    from checkpoint_core.session import Session
    a = tmp_path / "a"; a.mkdir()
    import os; os.chdir(a); run(["init"])
    (a / "f.txt").write_text("base\n"); run(["start", "c0"]); run(["accept", "--no-verify", "-m", "c0"])
    run(["start", "work"]); (a / "f.txt").write_text("draft\n")
    A.create_autosave(core(a), Session.active(core(a)), reason="edit")
    (a / "f.txt").write_text("final\n"); run(["accept", "--no-verify", "-m", "c1"])
    ra = core(a); ra.config.data["sync"]["transfer_autosaves"] = True
    b = tmp_path / "remote"; RM.bootstrap_store(b)
    RM.add_remote(ra, "origin", "filesystem", str(b))
    RM.push(ra, "origin", "main")
    found = any((core(b).paths.session_dir(sid) / "autosaves").exists()
                for sid in core(b).session_ids())
    assert found


# --------------------------------------------------------- structural: no git

def test_remote_modules_do_not_import_git_bridge():
    import checkpoint_core.remote as r
    import checkpoint_core.sync as s
    assert "gitbridge" not in dir(r)
    assert "gitbridge" not in dir(s)
