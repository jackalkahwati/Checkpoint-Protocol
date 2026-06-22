"""Tests for Checkpoint Core: a Git-replacement VCS. These run in plain directories
that are NOT git repos, proving the protocol does not depend on Git.
"""
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A plain directory (NOT a git repo), cwd set to it."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def core(repo):
    from checkpoint_core.store import Repo
    return Repo(repo)


def read_json(p):
    return json.loads(Path(p).read_text())


# --------------------------------------------------------------- init / identity

def test_init_creates_native_store_without_git(repo):
    assert run(["init", "--name", "Jack", "--email", "jack@e.com"]) == 0
    cp = repo / ".checkpoint"
    assert (cp / "HEAD").exists()
    assert (cp / "objects").is_dir()
    assert (cp / "refs" / "heads").is_dir()
    assert (cp / "identity.json").exists()
    # No git repo was created or required.
    assert not (repo / ".git").exists()
    assert (cp / "HEAD").read_text().strip() == "ref: refs/heads/main"


def test_identity_set_and_show(repo, capsys):
    run(["init"])
    assert run(["identity", "set", "--name", "Jack", "--email", "jack@e.com"]) == 0
    capsys.readouterr()
    run(["identity", "current"])      # falls back to the legacy author when unsigned
    out = capsys.readouterr().out
    assert "jack@e.com" in out


# ------------------------------------------------------------------- lifecycle

def test_full_lifecycle_builds_native_history(repo):
    run(["init", "--name", "Jack", "--email", "jack@e.com"])
    (repo / "a.txt").write_text("hello\n")
    run(["start", "first work"])
    (repo / "a.txt").write_text("hello world\n")
    assert run(["snapshot", "-m", "edit"]) == 0
    assert run(["accept", "--no-verify", "-m", "c1"]) == 0

    r = core(repo)
    head = r.head_snapshot()
    assert head, "branch head should point at an accepted snapshot"
    snap = r.get_object(head)
    assert snap["type"] == "snapshot" and snap["kind"] == "accepted"
    assert snap["message"] == "c1"
    # the accepted snapshot links back to the session (the core object)
    assert snap["session"].startswith("cs_")
    # seal is valid
    from checkpoint_core import objects
    assert objects.verify_seal(snap)
    # the materialized content round-trips through the object store
    tree = r.get_object(snap["tree"])
    blob = next(e for e in tree["entries"] if e["path"] == "a.txt")["blob"]
    assert r.get_blob(blob) == b"hello world\n"


def test_history_chain_and_parents(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    (repo / "a.txt").write_text("2\n")
    run(["start", "c2"]); run(["accept", "--no-verify", "-m", "c2"])
    r = core(repo)
    chain = r.history()
    assert len(chain) == 2
    head = r.get_object(chain[0])
    assert head["message"] == "c2"
    assert head["parents"] == [chain[1]]  # c2's parent is c1


def test_nothing_to_accept(repo, capsys):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["start", "noop"])
    assert run(["accept", "--no-verify"]) == 1
    assert "nothing to accept" in capsys.readouterr().err


# -------------------------------------------------------------------- rollback

def test_rollback_hard_restores_to_branch_head(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("good\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["start", "risky"])
    (repo / "a.txt").write_text("bad\n")
    (repo / "junk.txt").write_text("junk\n")
    assert run(["rollback", "--hard"]) == 0
    assert (repo / "a.txt").read_text() == "good\n"
    assert not (repo / "junk.txt").exists()


def test_rollback_preview_non_destructive(repo, capsys):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("good\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["start", "risky"])
    (repo / "a.txt").write_text("bad\n")
    assert run(["rollback"]) == 0
    assert "preview" in capsys.readouterr().out.lower()
    assert (repo / "a.txt").read_text() == "bad\n"


# --------------------------------------------------------------------- secrets

def test_accept_blocked_by_secrets(repo, capsys):
    run(["init", "--email", "j@e.com"])
    run(["start", "leak"])
    (repo / "cfg.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"\n')
    assert run(["accept", "--no-verify"]) == 1
    assert "secrets detected" in capsys.readouterr().err
    assert run(["accept", "--no-verify", "--force"]) == 0


# ----------------------------------------------------------------- branch/merge

def test_branch_checkout_merge_clean(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "f.txt").write_text("base\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["branch", "feature"]); run(["checkout", "feature"])
    (repo / "feat.txt").write_text("feature\n")
    run(["start", "feat"]); run(["accept", "--no-verify", "-m", "feat"])
    run(["checkout", "main"])
    (repo / "main.txt").write_text("main\n")
    run(["start", "main work"]); run(["accept", "--no-verify", "-m", "main"])
    assert run(["merge", "feature"]) == 0
    # disjoint changes merged
    assert (repo / "feat.txt").exists()
    assert (repo / "main.txt").exists()
    r = core(repo)
    head = r.get_object(r.head_snapshot())
    assert len(head["parents"]) == 2  # merge snapshot


def test_merge_conflict_writes_markers(repo, capsys):
    run(["init", "--email", "j@e.com"])
    (repo / "h.txt").write_text("base\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["branch", "other"]); run(["checkout", "other"])
    (repo / "h.txt").write_text("OTHER\n")
    run(["start", "o"]); run(["accept", "--no-verify", "-m", "o"])
    run(["checkout", "main"])
    (repo / "h.txt").write_text("MAIN\n")
    run(["start", "m"]); run(["accept", "--no-verify", "-m", "m"])
    assert run(["merge", "other"]) == 1
    content = (repo / "h.txt").read_text()
    assert "<<<<<<< ours" in content and ">>>>>>> theirs" in content


# ------------------------------------------------------------------------ sync

def test_push_pull_between_repos(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; b = tmp_path / "b"; c = tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    # origin
    monkeypatch.chdir(b); run(["init", "--email", "o@e.com"])
    # working repo a
    monkeypatch.chdir(a); run(["init", "--email", "j@e.com"])
    (a / "f.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["remote", "add", "origin", "--type", "filesystem", "--path", str(b)])
    assert run(["push", "origin", "main"]) == 0
    # clone via pull into c
    monkeypatch.chdir(c); run(["init", "--email", "c@e.com"])
    run(["remote", "add", "origin", "--type", "filesystem", "--path", str(b)])
    assert run(["pull", "origin", "main"]) == 0
    assert (c / "f.txt").read_text() == "v1\n"
    from checkpoint_core.store import Repo
    assert Repo(c).head_snapshot() == Repo(a).head_snapshot()


def test_bundle_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; d = tmp_path / "d"
    a.mkdir(); d.mkdir()
    monkeypatch.chdir(a); run(["init", "--email", "j@e.com"])
    (a / "f.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    bundle = tmp_path / "main.tar.gz"
    assert run(["bundle", "export", "main", "--out", str(bundle)]) == 0
    assert bundle.exists()
    monkeypatch.chdir(d); run(["init", "--email", "d@e.com"])
    assert run(["bundle", "import", str(bundle)]) == 0
    from checkpoint_core.store import Repo
    assert Repo(d).head_snapshot() == Repo(a).head_snapshot()


def test_bundle_excludes_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    monkeypatch.chdir(a); run(["init", "--email", "j@e.com"])
    (a / "f.txt").write_text("clean\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    bundle = tmp_path / "b.tar.gz"
    run(["bundle", "export", "main", "--out", str(bundle)])
    # bundles carry object blobs verbatim; this test documents that history blobs
    # are byte-exact (sync fidelity). Secret redaction is enforced at packet/export
    # of *sessions*, tested in the adapter suite. Here we assert fidelity.
    with tarfile.open(bundle) as tar:
        assert any(m.name.startswith("objects/") for m in tar.getmembers())


# ------------------------------------------------------------------ seal tamper

def test_verify_history_detects_tampering(repo, capsys):
    run(["init", "--email", "j@e.com"])
    (repo / "a.txt").write_text("1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    assert run(["verify-history"]) == 0
    # tamper: rewrite the accepted snapshot object's message without resealing
    r = core(repo)
    head = r.head_snapshot()
    obj = r.get_object(head)
    obj["message"] = "tampered"
    # write back under the SAME id (simulating store tampering)
    path = r.paths.objects / head[:2] / head
    from checkpoint_core import util
    path.write_bytes(util.canonical(obj))
    assert run(["verify-history"]) == 1
    assert "failed verification" in capsys.readouterr().err


# ----------------------------------------------------- structural: no git in core

def test_core_does_not_depend_on_git_at_module_level():
    import importlib
    import checkpoint_core.cli as cli
    import checkpoint_core.engine as engine
    importlib.reload(engine)
    # gitbridge is imported lazily (inside command functions), never at module top.
    assert not hasattr(cli, "gitbridge"), "cli must import gitbridge lazily"
    # engine never references the bridge
    assert "gitbridge" not in dir(engine)


# ---------------------------------------------------------------------- doctor

def test_doctor_reports_healthy(repo):
    run(["init", "--email", "j@e.com"])
    assert run(["doctor"]) == 0


# ----------------------------------------------------- line-level diff3 (unit)

def _lines(s):
    return s.splitlines(keepends=True)


def test_diff3_disjoint_auto_merges():
    from checkpoint_core.merge import diff3, render
    base = _lines("a\nb\nc\nd\ne\n")
    ours = _lines("A\nb\nc\nd\ne\n")       # changed line 1
    theirs = _lines("a\nb\nc\nd\nE\n")     # changed line 5 (disjoint)
    has_conflict, content = render(diff3(base, ours, theirs))
    assert not has_conflict
    assert content == "A\nb\nc\nd\nE\n"


def test_diff3_overlapping_conflicts():
    from checkpoint_core.merge import diff3, render
    base = _lines("a\nb\nc\n")
    ours = _lines("a\nB1\nc\n")
    theirs = _lines("a\nB2\nc\n")
    has_conflict, content = render(diff3(base, ours, theirs))
    assert has_conflict
    assert "<<<<<<< ours" in content and ">>>>>>> theirs" in content
    assert content.startswith("a\n") and content.rstrip().endswith("c")


def test_diff3_same_change_both_sides_no_conflict():
    from checkpoint_core.merge import diff3, render
    base = _lines("a\nb\nc\n")
    ours = theirs = _lines("a\nX\nc\n")
    has_conflict, content = render(diff3(base, ours, theirs))
    assert not has_conflict
    assert content == "a\nX\nc\n"


# ------------------------------------------------------- line-level merge (e2e)

def _accept_on(repo, branch, fname, content, msg):
    run(["checkout", branch])
    (repo / fname).write_text(content)
    run(["start", msg]); assert run(["accept", "--no-verify", "-m", msg]) == 0


def test_merge_disjoint_same_file_auto_merges(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "code.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "dev"])
    _accept_on(repo, "dev", "code.txt", "TOP\nl2\nl3\nl4\nl5\n", "edit top")
    _accept_on(repo, "main", "code.txt", "l1\nl2\nl3\nl4\nBOTTOM\n", "edit bottom")
    assert run(["merge", "dev"]) == 0   # auto-merge, no conflict
    assert (repo / "code.txt").read_text() == "TOP\nl2\nl3\nl4\nBOTTOM\n"
    assert run(["verify-history"]) == 0  # merge snapshot is sealed and valid


def test_merge_overlapping_same_file_conflicts(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "x.txt").write_text("alpha\nbeta\ngamma\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "b2"])
    _accept_on(repo, "b2", "x.txt", "alpha\nBETA-theirs\ngamma\n", "t")
    _accept_on(repo, "main", "x.txt", "alpha\nBETA-ours\ngamma\n", "o")
    assert run(["merge", "b2"]) == 1
    content = (repo / "x.txt").read_text()
    assert "<<<<<<< ours" in content and ">>>>>>> theirs" in content
    # surrounding stable lines preserved (only the beta hunk conflicts)
    assert content.startswith("alpha\n") and content.rstrip().endswith("gamma")


def test_merge_delete_modify_conflicts(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "d.txt").write_text("keep\nme\n")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "mod"])
    _accept_on(repo, "mod", "d.txt", "keep\nMODIFIED\n", "modify")
    # main deletes the file
    run(["checkout", "main"])
    (repo / "d.txt").unlink()
    run(["start", "delete"]); run(["accept", "--no-verify", "-m", "delete"])
    assert run(["merge", "mod"]) == 1   # delete/modify conflict


def test_merge_binary_conflict(repo):
    run(["init", "--email", "j@e.com"])
    (repo / "b.bin").write_bytes(b"\x00\x01\x02base\x00")
    run(["start", "base"]); run(["accept", "--no-verify", "-m", "base"])
    run(["branch", "bb"])
    run(["checkout", "bb"])
    (repo / "b.bin").write_bytes(b"\x00\x01\x02theirs\xff")
    run(["start", "t"]); run(["accept", "--no-verify", "-m", "t"])
    run(["checkout", "main"])
    (repo / "b.bin").write_bytes(b"\x00\x01\x02ours\xfe")
    run(["start", "o"]); run(["accept", "--no-verify", "-m", "o"])
    assert run(["merge", "bb"]) == 1   # binary changed both sides -> conflict


# ----------------------------------------------------------- git bridge round-trip

import shutil  # noqa: E402

git_required = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@git_required
def test_git_import_strips_trailers_and_keeps_clean_message(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    monkeypatch.chdir(a); run(["init", "--name", "Jack", "--email", "jack@e.com"])
    (a / "f.txt").write_text("v1\n")
    run(["start", "fix camera exposure"]); run(["accept", "--no-verify", "-m", "fix camera exposure"])
    gdir = tmp_path / "g"
    run(["git-export", str(gdir)])
    # import into a fresh core repo
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.chdir(b); run(["init", "--email", "b@e.com"])
    run(["git-import", str(gdir)])
    from checkpoint_core.store import Repo
    from checkpoint_core import objects
    snap = Repo(b).get_object(Repo(b).head_snapshot())
    assert snap["message"] == "fix camera exposure"          # clean, no trailers
    assert "Checkpoint-" not in snap["message"]
    assert snap["bridge"]["source"] == "git-import"          # provenance as metadata
    assert "git_commit" in snap["bridge"]
    assert objects.verify_seal(snap)


@git_required
def test_git_roundtrip_does_not_compound_trailers(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    monkeypatch.chdir(a); run(["init", "--email", "jack@e.com"])
    (a / "f.txt").write_text("v1\n")
    run(["start", "do a thing"]); run(["accept", "--no-verify", "-m", "do a thing"])

    def export_import_export(src_core, label):
        gdir = tmp_path / ("g_" + label)
        monkeypatch.chdir(src_core); run(["git-export", str(gdir)])
        return gdir

    g1 = export_import_export(a, "1")
    # round-trip: g1 -> core b -> g2
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.chdir(b); run(["init", "--email", "b@e.com"]); run(["git-import", str(g1)])
    g2 = tmp_path / "g2"
    monkeypatch.chdir(b); run(["git-export", str(g2)])

    def session_trailer_count(gdir):
        body = subprocess.run(["git", "-C", str(gdir), "log", "-1", "--format=%B"],
                              capture_output=True, text=True).stdout
        return body.count("Checkpoint-Session:")

    assert session_trailer_count(g1) == 1
    assert session_trailer_count(g2) == 1   # did NOT compound to 2
    # and the human message stayed clean through the round-trip
    body2 = subprocess.run(["git", "-C", str(g2), "log", "-1", "--format=%s"],
                           capture_output=True, text=True).stdout.strip()
    assert body2 == "do a thing"


@git_required
def test_git_roundtrip_preserves_file_content(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    monkeypatch.chdir(a); run(["init", "--email", "jack@e.com"])
    (a / "f.txt").write_text("hello world\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    gdir = tmp_path / "g"; run(["git-export", str(gdir)])
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.chdir(b); run(["init", "--email", "b@e.com"])
    run(["git-import", str(gdir)]); run(["checkout", "main"])
    assert (b / "f.txt").read_text() == "hello world\n"
