"""Phase 5 tests: signed identity & trust. Run in non-git dirs (no Git dependency)."""
import json
import os
import stat
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
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def core(repo):
    from checkpoint_core.store import Repo
    return Repo(repo)


def mk_identity(repo, name="Jack", typ="human"):
    from checkpoint_core import identity as I
    return I.create(core(repo), name=name, id_type=typ, email="x@e.com")


def signed_repo(repo):
    """init + identity + one signed accepted snapshot. Returns (repo, identity_id, snapshot_id)."""
    run(["init"])
    rec = mk_identity(repo)
    (repo / "a.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "-m", "c1"])
    return rec["identity_id"], core(repo).head_snapshot()


# --------------------------------------------------------------------- identity

def test_identity_create_generates_ed25519(repo):
    run(["init"])
    rec = mk_identity(repo)
    assert rec["key_algorithm"] == "ed25519"
    assert len(bytes.fromhex(rec["public_key"])) == 32
    assert rec["fingerprint"].startswith("SHA256:")
    from checkpoint_core import identity as I
    assert I.has_private(core(repo), rec["identity_id"])
    seed = I.private_seed(core(repo), rec["identity_id"])
    assert len(seed) == 32


def test_identity_export_excludes_private_key(repo):
    run(["init"])
    rec = mk_identity(repo)
    out = repo / "id.json"
    assert run(["identity", "export", rec["identity_id"], "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert "public_key" in data
    from checkpoint_core import identity as I
    seed_hex = I.private_seed(core(repo), rec["identity_id"]).hex()
    text = out.read_text()
    assert seed_hex not in text          # private seed never exported
    assert "seed" not in data and "private" not in text.lower()


def test_identity_import_is_untrusted(repo):
    run(["init"]); mk_identity(repo)
    # export from a separate repo, import here
    other = repo / "other"; other.mkdir()
    run(["init"])  # re-init current dir is the same; build the other repo via API
    from checkpoint_core.store import Repo
    from checkpoint_core import identity as I
    o = Repo(other)
    o.paths.base.mkdir(parents=True, exist_ok=True)
    (o.paths.base / "HEAD").write_text("ref: refs/heads/main\n")
    rec = I.create(o, name="Stranger", id_type="human")
    pubrec = I.export_record(o, rec["identity_id"])
    p = repo / "stranger.json"; p.write_text(json.dumps(pubrec))
    assert run(["identity", "import", str(p)]) == 0
    imported = I.load(core(repo), rec["identity_id"])
    assert imported is not None
    assert imported["trusted"] is False  # import never auto-trusts


def test_identity_trust_untrust(repo):
    run(["init"])
    rec = mk_identity(repo)
    from checkpoint_core import identity as I
    I.set_trust(core(repo), rec["identity_id"], False)
    assert not I.is_trusted(core(repo), rec["identity_id"])
    assert run(["identity", "trust", rec["identity_id"]]) == 0
    assert I.is_trusted(core(repo), rec["identity_id"])
    assert run(["identity", "untrust", rec["identity_id"]]) == 0
    assert not I.is_trusted(core(repo), rec["identity_id"])


# ---------------------------------------------------------------- sign / verify

def test_accept_signs_when_identity_active(repo):
    from checkpoint_core import sign as S
    sid, snap = signed_repo(repo)
    sigs = S.signatures_for(core(repo), snap)
    assert len(sigs) == 1
    assert sigs[0]["signer_identity_id"] == sid
    assert S.verify_record(core(repo), sigs[0])["ok"]


def test_verify_signatures_passes_on_valid_history(repo):
    signed_repo(repo)
    assert run(["verify-signatures"]) == 0


def _rewrite_snapshot(repo, snap_id, mutate):
    r = core(repo)
    snap = r.get_object(snap_id)
    mutate(snap)
    from checkpoint_core import util
    (r.paths.objects / snap_id[:2] / snap_id).write_bytes(util.canonical(snap))


def test_verify_signatures_fails_on_message_change(repo):
    sid, snap = signed_repo(repo)
    _rewrite_snapshot(repo, snap, lambda s: s.update({"message": "tampered"}))
    assert run(["verify-signatures"]) == 1


def test_verify_signatures_fails_on_tree_change(repo):
    sid, snap = signed_repo(repo)
    _rewrite_snapshot(repo, snap, lambda s: s.update({"tree": "0" * 64}))
    assert run(["verify-signatures"]) == 1


def test_verify_signatures_fails_on_parent_change(repo):
    sid, snap = signed_repo(repo)
    _rewrite_snapshot(repo, snap, lambda s: s.update({"parents": ["0" * 64]}))
    assert run(["verify-signatures"]) == 1


def test_verify_detects_unknown_signer(repo):
    from checkpoint_core import sign as S, identity as I
    sid, snap = signed_repo(repo)
    # remove the signer's identity record -> unknown (hint still lets sig validate)
    I.record_path(core(repo), sid).unlink()
    v = S.verify_record(core(repo), S.signatures_for(core(repo), snap)[0])
    assert v["status"] == "unknown_signer"


# ----------------------------------------------------------------- trust-status

def test_trust_status_reports_unsigned(repo, capsys):
    run(["init"])  # no identity -> unsigned accepts
    (repo / "a.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    capsys.readouterr()
    assert run(["trust-status"]) == 0
    out = capsys.readouterr().out
    assert "unsigned accepted:       1" in out


def test_trust_status_reports_untrusted_signer(repo, capsys):
    sid, snap = signed_repo(repo)
    run(["identity", "untrust", sid])
    capsys.readouterr()
    run(["trust-status"])
    assert "untrusted" in capsys.readouterr().out


# ----------------------------------------------------------------- fsck integration

def test_fsck_verify_signatures_reports(repo, capsys):
    signed_repo(repo)
    capsys.readouterr()
    assert run(["fsck", "--verify-signatures"]) == 0
    assert "signatures:" in capsys.readouterr().out


def test_fsck_require_signatures_fails_on_unsigned(repo):
    run(["init"])  # no identity
    (repo / "a.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    assert run(["fsck", "--require-signatures"]) == 2


# ----------------------------------------------------------------- export/import

def test_export_bundle_has_public_identity_no_private_key(repo):
    from checkpoint_core import identity as I
    sid, snap = signed_repo(repo)
    bundle = repo / "b.tar.gz"
    assert run(["bundle", "export", "main", "--out", str(bundle)]) == 0
    seed_hex = I.private_seed(core(repo), sid).hex()
    with tarfile.open(bundle) as tar:
        names = tar.getnames()
        assert any(n.startswith("identities/") for n in names)
        assert not any("keys/" in n for n in names)
        for m in tar.getmembers():
            if m.isfile():
                data = tar.extractfile(m).read()
                assert seed_hex.encode() not in data  # no private seed anywhere


def test_imported_bundle_verifies_signatures(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    monkeypatch.chdir(a)
    sid, snap = signed_repo(a)
    bundle = tmp_path / "b.tar.gz"
    run(["bundle", "export", "main", "--out", str(bundle)])
    monkeypatch.chdir(b)
    run(["init"])
    run(["bundle", "import", str(bundle)])
    # B has the public identity (untrusted) but verifies the signature cryptographically
    assert run(["verify-signatures"]) == 0
    from checkpoint_core import sign as S, identity as I
    rb = core(b)
    assert I.load(rb, sid)["trusted"] is False
    assert S.verify_record(rb, S.signatures_for(rb, snap)[0])["ok"]


# ----------------------------------------------------------------- bridge / keys

def test_bridge_change_does_not_invalidate_signature(repo):
    from checkpoint_core import sign as S
    sid, snap = signed_repo(repo)
    # add bridge provenance to the snapshot object (excluded from signature payload)
    _rewrite_snapshot(repo, snap, lambda s: s.update({"bridge": {"source": "git-import", "git_commit": "abc"}}))
    assert S.verify_record(core(repo), S.signatures_for(core(repo), snap)[0])["ok"]


def test_autosave_does_not_capture_private_keys(repo):
    from checkpoint_core import autosave as A
    from checkpoint_core.session import Session
    run(["init"])
    rec = mk_identity(repo)
    run(["start", "work"])
    (repo / "a.txt").write_text("draft\n")
    av = A.create_autosave(core(repo), Session.active(core(repo)), reason="edit")
    tree = core(repo).get_object(av["tree_id"])
    paths = [e["path"] for e in tree["entries"]]
    assert not any(p.endswith(".key") for p in paths)
    assert not any(p.startswith(".checkpoint/") for p in paths)  # store (incl keys/) never captured


def test_signed_history_without_git(repo, monkeypatch):
    safe = repo / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    sid, snap = signed_repo(repo)
    assert run(["verify-signatures"]) == 0


# ----------------------------------------------------------------- merge / policy

def test_signed_merge_verifies(repo):
    from checkpoint_core import sign as S
    run(["init"]); mk_identity(repo)
    (repo / "f.txt").write_text("base\n")
    run(["start", "base"]); run(["accept", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "feat.txt").write_text("feature\n")
    run(["start", "feat"]); run(["accept", "-m", "feat"])
    run(["checkout", "main"])
    (repo / "main.txt").write_text("main\n")
    run(["start", "mainwork"]); run(["accept", "-m", "main"])
    assert run(["merge", "dev"]) == 0
    head = core(repo).head_snapshot()
    assert len(S.signatures_for(core(repo), head)) == 1     # merge snapshot signed
    assert run(["verify-signatures"]) == 0


def test_trust_policy_rejects_agent_self_accept(repo):
    run(["init"])
    rec = mk_identity(repo, name="bot", typ="agent")
    run(["identity", "use", rec["identity_id"]])
    (repo / "a.txt").write_text("v1\n")
    run(["start", "agent work"])
    assert run(["accept", "--no-verify"]) == 1     # policy forbids agent acceptor


def test_revoked_identity_fails_require_signatures(repo):
    sid, snap = signed_repo(repo)
    assert run(["fsck", "--require-signatures"]) == 0   # trusted + signed -> ok
    run(["identity", "revoke", sid])
    assert run(["fsck", "--require-signatures"]) == 2   # revoked signer -> strict fail


def test_key_permissions_warning(repo, capsys):
    from checkpoint_core import identity as I
    run(["init"])
    rec = mk_identity(repo)
    kp = I.key_path(core(repo), rec["identity_id"])
    os.chmod(kp, 0o644)  # unsafe
    capsys.readouterr()
    run(["identity", "show", rec["identity_id"]])
    assert "unsafe permissions" in capsys.readouterr().out


def test_canonicalization_stable_across_key_order():
    from checkpoint_core import util
    a = util.canonical({"b": 2, "a": 1, "c": [3, 2, 1]})
    b = util.canonical({"c": [3, 2, 1], "a": 1, "b": 2})
    assert a == b
