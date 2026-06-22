"""Phase 7 tests: policy engine. Run in non-git dirs (no Git dependency)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture(autouse=True)
def nocolor(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def core(p):
    from checkpoint_core.store import Repo
    return Repo(p)


def set_verification(repo, names):
    import yaml
    p = repo / ".checkpoint" / "config.yaml"
    d = yaml.safe_load(p.read_text())
    d["verification"]["commands"] = [{"name": n, "run": "exit 0"} for n in names]
    p.write_text(yaml.safe_dump(d, sort_keys=False))


def mk_human(repo, name="Jack"):
    from checkpoint_core import identity as I
    return I.create(core(repo), name=name, id_type="human")["identity_id"]


def policy_events(repo):
    return [e for e in __import__("json").loads(
        "[" + ",".join(core(repo).paths.ledger.read_text().splitlines()) + "]")
        if e["event_type"] == "policy"]


# ----------------------------------------------------------------- validate

def test_policy_validate_accepts_valid(repo):
    run(["init"]); run(["policy", "init"])
    assert run(["policy", "validate"]) == 0


def test_policy_validate_rejects_malformed(repo):
    run(["init"]); run(["policy", "init"])
    (repo / ".checkpoint" / "policy.yaml").write_text("default_effect: bogus\npath_rules: 5\n")
    assert run(["policy", "validate"]) == 1


# ----------------------------------------------------------------- evaluator (unit)

def test_default_deny_blocks_accept_without_allow_rule():
    from checkpoint_core import policy as P
    pol = {"default_effect": "deny", "actor_rules": {}}
    d = P.evaluate(pol, {"operation": "accept", "actor_type": "human"})
    assert d["effect"] == "deny"


def test_path_glob_matching_deterministic():
    from checkpoint_core import policy as P
    assert P.path_matches("src/safety/", "src/safety/controller.rs")
    assert P.path_matches("firmware/**", "firmware/boot/main.c")
    assert P.path_matches("*.md", "docs/readme.md")
    assert P.path_matches("docs/**", "docs/guide/intro.md")
    assert not P.path_matches("src/safety/", "src/motor/x.rs")
    # deterministic: same inputs, same result
    assert P.path_matches("firmware/**", "firmware/a/b/c.c") == P.path_matches("firmware/**", "firmware/a/b/c.c")


def test_strictest_matching_rule_wins():
    from checkpoint_core import policy as P
    pol = {
        "default_effect": "deny",
        "actor_rules": {"human": {"can_accept": True}},
        "path_rules": [
            {"paths": ["x/**"], "require": {"verification_optional": True}, "label": "lax"},
            {"paths": ["x/**"], "require": {"trusted_human_acceptor": True, "signed_accept": True},
             "label": "strict"},
        ],
    }
    d = P.evaluate(pol, {"operation": "accept", "actor_type": "human",
                         "actor_identity": {"trusted": False}, "changed_paths": ["x/y.txt"],
                         "will_sign": False})
    # strict rule's requirements win despite the lax rule also matching
    assert d["effect"] == "deny"
    assert any("trusted" in r for r in d["reasons"])
    assert any("signed accept" in r for r in d["reasons"])


def test_push_rejects_force_push_by_policy():
    from checkpoint_core import policy as P
    pol = P.DEFAULT_STARTER_POLICY
    d = P.evaluate(pol, {"operation": "push", "actor_type": "human",
                         "ref_update_type": "force"})
    assert d["effect"] == "deny"


def test_push_allows_force_with_lease_when_policy_allows():
    from checkpoint_core import policy as P
    pol = P.DEFAULT_STARTER_POLICY
    d = P.evaluate(pol, {"operation": "push", "actor_type": "human",
                         "ref_update_type": "force_with_lease"})
    assert d["effect"] == "allow"


def test_release_branch_requires_release_checks():
    from checkpoint_core import policy as P
    pol = P.DEFAULT_STARTER_POLICY
    d = P.evaluate(pol, {"operation": "merge", "actor_type": "human",
                         "actor_identity": {"trusted": True}, "branch": "release/1",
                         "will_sign": True, "verification_passed": ["tests"]})
    assert d["effect"] == "deny"
    assert any("release_checks" in r for r in d["reasons"])


def test_json_output_is_stable_and_deterministic():
    from checkpoint_core import policy as P
    pin = {"operation": "accept", "actor_type": "agent", "changed_paths": ["src/x"]}
    a = P.evaluate(P.DEFAULT_STARTER_POLICY, pin)
    b = P.evaluate(P.DEFAULT_STARTER_POLICY, pin)
    assert a["effect"] == b["effect"] and a["reasons"] == b["reasons"]
    json.dumps(a)  # serializable


# ----------------------------------------------------------------- accept integration

def test_human_accept_docs_allowed(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "docs").mkdir(); (repo / "docs" / "x.md").write_text("# hi\n")
    run(["start", "docs"])
    assert run(["accept", "-m", "docs"]) == 0


def test_agent_self_accept_denied(repo):
    from checkpoint_core import identity as I
    run(["init"]); run(["policy", "init"])
    rec = I.create(core(repo), name="bot", id_type="agent")
    I.set_current(core(repo), rec["identity_id"])
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "agent work"])
    assert run(["accept", "--no-verify"]) == 1


def test_missing_verification_blocks_accept(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    assert run(["accept", "--no-verify"]) == 1     # tests/lint not passed


def test_passing_verification_allows_accept(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    set_verification(repo, ["tests", "lint"])
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    assert run(["accept"]) == 0                     # accept runs tests+lint, both pass


def test_safety_path_requires_trusted_human(repo):
    from checkpoint_core import identity as I
    run(["init"]); run(["policy", "init"])
    hid = mk_human(repo)
    I.set_trust(core(repo), hid, False)             # untrusted human
    set_verification(repo, ["tests", "lint", "safety_tests"])
    (repo / "src" / "safety").mkdir(parents=True)
    (repo / "src" / "safety" / "c.rs").write_text("ctrl\n")
    run(["start", "safety"])
    assert run(["accept"]) == 1                      # untrusted -> denied


def test_safety_path_requires_signed_accept(repo):
    run(["init"]); run(["policy", "init"])           # no identity -> unsigned
    set_verification(repo, ["tests", "lint", "safety_tests"])
    (repo / "src" / "safety").mkdir(parents=True)
    (repo / "src" / "safety" / "c.rs").write_text("ctrl\n")
    run(["start", "safety"])
    assert run(["accept"]) == 1                      # unsigned -> denied


def test_safety_path_requires_named_verification(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    set_verification(repo, ["tests", "lint"])        # safety_tests NOT configured
    (repo / "src" / "safety").mkdir(parents=True)
    (repo / "src" / "safety" / "c.rs").write_text("ctrl\n")
    run(["start", "safety"])
    assert run(["accept"]) == 1                      # safety_tests missing
    # now provide it
    set_verification(repo, ["tests", "lint", "safety_tests"])
    assert run(["accept"]) == 0


# ----------------------------------------------------------------- override

def test_override_requires_reason(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    # denied (missing verification); override without reason still denied
    assert run(["accept", "--no-verify", "--override"]) == 1


def test_override_by_agent_denied(repo):
    from checkpoint_core import identity as I
    run(["init"]); run(["policy", "init"])
    rec = I.create(core(repo), name="bot", id_type="agent")
    I.set_current(core(repo), rec["identity_id"])
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "agent work"])
    assert run(["accept", "--no-verify", "--override", "--reason", "trust me"]) == 1


def test_override_by_trusted_human_allowed_and_recorded(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src" / "safety").mkdir(parents=True)
    (repo / "src" / "safety" / "c.rs").write_text("ctrl\n")
    run(["start", "safety"])
    # would be denied (safety_tests missing) but a trusted human overrides with a reason
    assert run(["accept", "--no-verify", "--override", "--reason", "hotfix approved"]) == 0
    evs = policy_events(repo)
    assert any(e["payload"].get("override_used") for e in evs)


# ----------------------------------------------------------------- ledger / explain / read-only

def test_policy_decisions_written_to_ledger(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    run(["accept", "--no-verify"])                   # denied -> decision recorded
    assert len(policy_events(repo)) >= 1


def test_policy_explain_shows_rules_and_reasons(repo, capsys):
    run(["init"]); run(["policy", "init"])
    (repo / "src" / "safety").mkdir(parents=True)
    (repo / "src" / "safety" / "c.rs").write_text("ctrl\n")
    run(["start", "safety"])
    capsys.readouterr()
    run(["policy", "check", "--operation", "accept"])
    out = capsys.readouterr().out
    assert "DENY" in out and "safety-critical" in out


def test_policy_check_is_read_only(repo):
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    before = len(policy_events(repo))
    run(["policy", "check", "--operation", "accept"])
    assert len(policy_events(repo)) == before        # check records nothing


def test_identity_trust_records_policy_decision(repo):
    run(["init"]); run(["policy", "init"])
    hid = mk_human(repo)
    before = len(policy_events(repo))
    run(["identity", "trust", hid])
    assert len(policy_events(repo)) > before


# ----------------------------------------------------------------- merge / remote integration

def test_protected_main_requires_signed_merge(repo):
    run(["init"]); run(["policy", "init"])           # no identity -> unsigned merges
    (repo / "f.txt").write_text("base\n")
    # need an identity to create the first accepts? accepts under policy require signing.
    mk_human(repo)
    set_verification(repo, ["tests", "lint"])
    run(["start", "base"]); run(["accept", "-m", "base"])
    run(["branch", "dev"]); run(["checkout", "dev"])
    (repo / "feat.txt").write_text("feat\n"); run(["start", "f"]); run(["accept", "-m", "f"])
    run(["checkout", "main"])
    (repo / "main.txt").write_text("m\n"); run(["start", "mw"]); run(["accept", "-m", "mw"])
    # remove the signing identity so the merge would be unsigned -> policy denies
    core(repo).paths.current_identity.unlink()
    assert run(["merge", "dev"]) == 1


def test_pull_refuses_unsigned_remote_history_when_required(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    import os; os.chdir(a)
    run(["init"])
    (a / "f.txt").write_text("v1\n"); run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    b = tmp_path / "b"; b.mkdir(); os.chdir(b); run(["init"]); run(["policy", "init"])
    # require signed remote history
    import yaml
    pol = yaml.safe_load((b / ".checkpoint" / "policy.yaml").read_text())
    pol["remote_rules"]["reject_unsigned_remote_history"] = True
    (b / ".checkpoint" / "policy.yaml").write_text(yaml.safe_dump(pol))
    run(["remote", "add", "origin", "--type", "filesystem", "--path", str(a)])
    assert run(["pull", "origin", "main"]) == 1       # a's history is unsigned


def test_bundle_import_rejects_unsigned_when_policy_requires(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a = tmp_path / "a"; a.mkdir()
    import os; os.chdir(a); run(["init"])
    (a / "f.txt").write_text("v1\n"); run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    bundle = tmp_path / "b.tar.gz"; run(["bundle", "create", "--out", str(bundle)])
    d = tmp_path / "d"; d.mkdir(); os.chdir(d); run(["init"]); run(["policy", "init"])
    assert run(["bundle", "import", str(bundle)]) == 1   # unsigned history, policy requires signed


# ----------------------------------------------------------------- fsck integration

def test_fsck_policy_reports_violations(repo):
    run(["init"])                                    # no policy yet -> unsigned accept allowed
    (repo / "f.txt").write_text("v1\n")
    run(["start", "c1"]); run(["accept", "--no-verify", "-m", "c1"])
    run(["policy", "init"])                          # now require signed accepts
    assert run(["fsck", "--policy"]) == 0            # violations reported, not "corrupt"
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(["fsck", "--policy"])
    assert "VIOLATION" in buf.getvalue()


# ----------------------------------------------------------------- no-git

def test_policy_works_without_git(repo, monkeypatch):
    safe = repo / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    run(["init"]); run(["policy", "init"]); mk_human(repo)
    (repo / "src").mkdir(); (repo / "src" / "a.py").write_text("x\n")
    run(["start", "feature"])
    assert run(["accept", "--no-verify"]) == 1       # policy denies (missing verification)
    set_verification(repo, ["tests", "lint"])
    assert run(["accept"]) == 0
