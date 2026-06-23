"""v1.2 Personal Autopilot: Owner Agent review, autopilot accept/escalate, personal, backup."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


def _repo(path):
    from checkpoint_core.store import Repo
    return Repo(path)


def _active(path):
    from checkpoint_core.session import Session
    return Session.active(_repo(path))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    run(["personal", "init", "--name", "Jack"])
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "guide.md").write_text("intro\n")
    run(["start", "base", "--no-watch"]); run(["accept", "--force", "-m", "base"])
    return tmp_path


# ---------------------------------------------------------------- Owner Agent (deterministic)

def _decide(**facts):
    from checkpoint_core import owneragent as oa
    base = {"changed_paths": [], "files_changed": 1, "deletions": 0, "tests": "passed",
            "policy_effect": "allow", "conflict_count": 0, "unresolved_comments": 0,
            "builder_is_owner": False, "signatures_status": "unsigned"}
    base.update(facts)
    from checkpoint_core.owneragent import DEFAULT_AUTOPILOT, decide
    return decide(base, DEFAULT_AUTOPILOT)


def test_docs_change_auto_accepts():
    assert _decide(changed_paths=["docs/x.md", "README.md"], files_changed=2)["decision"] == "auto_accept"


def test_tests_change_auto_accepts_when_passing():
    assert _decide(changed_paths=["tests/test_a.py"])["decision"] == "auto_accept"


def test_protected_policy_path_escalates():
    d = _decide(changed_paths=["checkpoint_core/policy/engine.py"])
    assert d["decision"] == "escalate" and d["risk"] == "high"


def test_remote_sync_code_escalates():
    assert _decide(changed_paths=["checkpoint_core/remote/http.py"])["decision"] == "escalate"


def test_failed_tests_escalate():
    assert _decide(changed_paths=["docs/x.md"], tests="failed")["decision"] == "escalate"


def test_policy_denied_escalates():
    assert _decide(changed_paths=["docs/x.md"], policy_effect="deny", policy_reasons=["x"])["decision"] == "escalate"


def test_conflicts_escalate():
    assert _decide(changed_paths=["docs/x.md"], conflict_count=1)["decision"] == "escalate"


def test_unresolved_comments_escalate():
    assert _decide(changed_paths=["docs/x.md"], unresolved_comments=2)["decision"] == "escalate"


def test_large_change_escalates():
    assert _decide(changed_paths=["docs/x.md"], files_changed=50)["decision"] == "escalate"


def test_builder_cannot_approve_itself():
    assert _decide(changed_paths=["docs/x.md"], builder_is_owner=True)["decision"] == "escalate"


def test_non_allowlisted_safe_change_is_not_auto_accepted():
    # source code that isn't protected and isn't in the allow-list -> manual, never auto-accept
    assert _decide(changed_paths=["src/app.py"])["decision"] != "auto_accept"


def test_owner_review_is_ledgered_and_signed(repo):
    from checkpoint_core import owneragent as oa, ledger as ledgermod
    (repo / "docs" / "guide.md").write_text("intro\nmore\n")
    run(["start", "edit docs", "--no-watch"])
    review = oa.review_session(_repo(repo), _active(repo))
    assert review["decision"] == "auto_accept"
    assert review.get("signed_review")                      # signed by the owner agent
    assert review["owner_agent_identity_id"] != review.get("builder_agent_identity_id")
    evs = [e for e in ledgermod.read_all(_repo(repo)) if e["event_type"] == "owner_review"]
    assert evs
    run(["rollback", "--hard", "--yes"])


# ---------------------------------------------------------------- autopilot flow

def test_autopilot_docs_auto_accepts(repo):
    (repo / "docs" / "guide.md").write_text("intro\nmore docs\n")
    before = len(_repo(repo).history())
    assert run(["claude", "update docs", "--autopilot", "--no-launch", "--no-tests", "--decision", "auto"]) == 0
    r = _repo(repo)
    assert len(r.history()) == before + 1                   # one clean accepted snapshot
    assert _active(repo) is None
    # signed by the Owner Agent (separate identity)
    from checkpoint_core import sign as signmod
    assert signmod.signatures_for(r, r.head_snapshot())


def test_autopilot_protected_path_escalates(repo):
    (repo / "checkpoint_core" / "policy").mkdir(parents=True, exist_ok=True)
    (repo / "checkpoint_core" / "policy" / "engine.py").write_text("x = 1\n")
    before = len(_repo(repo).history())
    assert run(["claude", "touch policy", "--autopilot", "--no-launch", "--no-tests", "--decision", "escalate"]) == 0
    assert len(_repo(repo).history()) == before             # NOT accepted
    assert _active(repo) is not None                        # left reviewable


def test_autopilot_decision_escalate_never_accepts(repo):
    (repo / "docs" / "guide.md").write_text("intro\nx\n")     # would auto-accept, but escalate forced
    before = len(_repo(repo).history())
    run(["claude", "docs", "--autopilot", "--no-launch", "--no-tests", "--decision", "escalate"])
    assert len(_repo(repo).history()) == before
    assert _active(repo) is not None
    run(["rollback", "--hard", "--yes"])


def test_autopilot_rollback_on_fail(repo):
    import yaml
    cfg = repo / ".checkpoint" / "config.yaml"
    d = yaml.safe_load(cfg.read_text()); d.setdefault("verification", {})["commands"] = [{"name": "tests", "run": "exit 1"}]
    cfg.write_text(yaml.safe_dump(d))
    (repo / "docs" / "guide.md").write_text("intro\nbad\n")
    before = len(_repo(repo).history())
    assert run(["claude", "docs", "--autopilot", "--no-launch", "--decision", "rollback-on-fail"]) == 0
    assert len(_repo(repo).history()) == before             # rolled back, no new history
    assert _active(repo) is None


def test_autopilot_json_output(repo, capsys):
    (repo / "docs" / "guide.md").write_text("intro\njson\n")
    run(["claude", "docs", "--autopilot", "--no-launch", "--no-tests", "--decision", "auto", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["action"] == "auto-accepted" and payload["owner_agent"] == "auto_accept"
    assert payload["accepted_snapshot"] and "risk" in payload


# ---------------------------------------------------------------- personal init / daily

def test_personal_init_creates_identities_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1"); monkeypatch.chdir(tmp_path)
    assert run(["personal", "init", "--name", "Jack"]) == 0
    from checkpoint_core import owneragent as oa, identity as idmod
    r = _repo(tmp_path)
    assert r.current_identity_id()                          # human identity
    assert any(i["name"] == oa.OWNER_AGENT_NAME for i in idmod.list_all(r))   # owner agent
    assert oa.config_path(r).exists()


def test_personal_init_no_broad_auto_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1"); monkeypatch.chdir(tmp_path)
    run(["personal", "init", "--name", "Jack"])
    from checkpoint_core import owneragent as oa
    cfg = oa.load_config(_repo(tmp_path))
    # auto-merge is limited to docs/tests/examples — never broad
    assert "src/" not in cfg["auto_merge_allowed"]["paths"]
    assert cfg["auto_merge_allowed"]["require"]["signed_review"] is True


def test_personal_daily_runs(repo, capsys):
    run(["personal", "daily"])
    out = capsys.readouterr().out
    assert "Accepted:" in out and "Escalated:" in out and "Integrity:" in out


# ---------------------------------------------------------------- backup

def test_backup_init_and_run(repo, tmp_path):
    bdir = tmp_path / "backup"; bdir.mkdir()
    assert run(["backup", "init", str(bdir)]) == 0
    assert "backup" in _repo(repo).config.remotes()
    assert run(["backup", "run"]) == 0
    # accepted history made it to the backup (object store populated)
    assert any(bdir.rglob("*"))


def test_backup_never_contains_private_keys(repo, tmp_path):
    bdir = tmp_path / "backup2"; bdir.mkdir()
    run(["backup", "init", str(bdir)]); run(["backup", "run"])
    leaked = [p for p in bdir.rglob("*") if p.suffix == ".key" or "keys" in p.parts]
    assert not leaked


def test_backup_restore_previews_before_mutating(repo, tmp_path):
    bdir = tmp_path / "backup3"; bdir.mkdir()
    run(["backup", "init", str(bdir)]); run(["backup", "run"])
    head = _repo(repo).head_snapshot()
    assert run(["backup", "restore"]) == 0                  # preview only (no --yes)
    assert _repo(repo).head_snapshot() == head              # unchanged


def test_backup_status_after_run(repo, tmp_path, capsys):
    bdir = tmp_path / "backup4"; bdir.mkdir()
    run(["backup", "init", str(bdir)]); run(["backup", "run"])
    capsys.readouterr()
    assert run(["backup", "status"]) == 0
    assert "Backup status" in capsys.readouterr().out


# ---------------------------------------------------------------- v1.2 deltas

def test_identity_path_escalates():
    assert _decide(changed_paths=["checkpoint_core/identity/store.py"])["decision"] == "escalate"


def test_review_persisted_signed_and_ledgered(repo):
    from checkpoint_core import owneragent as oa
    (repo / "docs" / "guide.md").write_text("intro\nx\n")
    run(["start", "edit", "--no-watch"])
    rev = oa.review_session(_repo(repo), _active(repo))
    assert rev.get("ledger_event_id") and "policy_decision_id" in rev and rev.get("signed_review")
    # persisted + loadable by review_id AND by target id
    r = _repo(repo)
    assert oa.load_review(r, rev["review_id"])["decision"] == rev["decision"]
    assert oa.load_review(r, rev["target_id"])["review_id"] == rev["review_id"]
    assert oa.latest_review(r)["review_id"] == rev["review_id"]
    run(["rollback", "--hard", "--yes"])


def test_autopilot_explain(repo, capsys):
    (repo / "docs" / "guide.md").write_text("intro\nexplain\n")
    run(["claude", "docs", "--autopilot", "--no-launch", "--no-tests", "--decision", "auto"])
    capsys.readouterr()
    assert run(["autopilot", "explain"]) == 0
    out = capsys.readouterr().out
    assert "Owner Agent review" in out and "decision:" in out and "reasoning:" in out


def test_next_includes_autopilot_fields(repo, capsys):
    run(["first-push", "--yes", "--dest", str(repo.parent / "bk_ap")])
    run(["next", "--json"])
    out = capsys.readouterr().out
    d = json.loads(out[out.index("{"):])
    for k in ("autopilot_enabled", "owner_agent_configured", "autopilot_recommended",
              "autopilot_safe_to_run", "suggested_autopilot_command", "last_owner_agent_review"):
        assert k in d
    assert d["autopilot_enabled"] is True and d["owner_agent_configured"] is True


def _live_mr(tmp_path, monkeypatch, feature_file, content):
    import socket, threading, time
    from checkpoint_core.server.store import ServerStore
    from checkpoint_core.server.app import serve
    from checkpoint_core import remote as RM
    store = ServerStore.init_store(tmp_path / "srv")
    admin = store.create_token("admin", ["admin"], "*")["token"]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    httpd = serve(store, "127.0.0.1", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start(); time.sleep(0.15)
    url = "http://127.0.0.1:{}".format(port)
    RM._http("POST", url + "/repos", admin, {"owner": "o", "repo": "r"})
    work = tmp_path / "w"; work.mkdir(); monkeypatch.chdir(work)
    run(["personal", "init", "--name", "Jack"])
    (work / "README.md").write_text("base\n"); run(["start", "b", "--no-watch"]); run(["accept", "--force", "-m", "b"])
    run(["branch", "feat"]); run(["checkout", "feat"])
    p = work / feature_file; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
    run(["start", "f", "--no-watch"]); run(["accept", "--force", "-m", "f"])
    run(["checkout", "main"])
    run(["remote", "add", "checkpoint", "{}/o/r".format(url), "--token", admin])
    run(["push", "checkpoint", "main"]); run(["push", "checkpoint", "feat"])
    for i in RM._http("GET", url + "/repos/o/r/identities", admin)[1]["identities"]:
        RM._http("POST", "{}/repos/o/r/identities/{}/trust".format(url, i["identity_id"]), admin)
    RM._http("POST", "{}/ui/repos/o/r/reviews".format(url), admin,
             {"title": "t", "source_branch": "feat", "target_branch": "main"})
    return httpd, url, admin


def test_autopilot_review_mr_docs_approves(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    httpd, url, admin = _live_mr(tmp_path, monkeypatch, "docs/new.md", "# docs\n")
    try:
        capsys.readouterr()
        assert run(["autopilot", "review", "mr_1", "--decision", "approve", "--json"]) == 0
        d = json.loads(capsys.readouterr().out)
        assert d["decision"] in ("auto_accept", "approve", "auto_merge")
        assert d.get("action_taken") == "approved"
    finally:
        httpd.shutdown()


def test_autopilot_review_mr_protected_escalates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    httpd, url, admin = _live_mr(tmp_path, monkeypatch, "checkpoint_core/policy/x.py", "x=1\n")
    try:
        capsys.readouterr()
        run(["autopilot", "review", "mr_1", "--decision", "approve", "--json"])
        d = json.loads(capsys.readouterr().out)
        assert d["decision"] == "escalate"
        assert "escalated" in (d.get("action_taken") or "")
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- live-shakedown regressions

def test_docs_auto_accepts_with_verify_running(repo):
    # no --no-tests: verify runs, returns "skipped" (no commands) -> must still auto-accept
    (repo / "docs" / "guide.md").write_text("intro\nverify\n")
    before = len(_repo(repo).history())
    assert run(["claude", "docs", "--autopilot", "--no-launch", "--decision", "auto"]) == 0
    assert len(_repo(repo).history()) == before + 1
    assert _active(repo) is None


def test_autopilot_backup_unreachable_accepts_locally(repo, capsys, tmp_path):
    run(["first-push", "--yes", "--dest", str(tmp_path / "bk")])
    import shutil
    shutil.rmtree(tmp_path / "bk")                       # backup vanishes mid-loop
    (repo / "docs" / "guide.md").write_text("intro\nlocal\n")
    capsys.readouterr()
    run(["claude", "docs", "--autopilot", "--no-launch", "--no-tests", "--decision", "auto"])
    out = capsys.readouterr().out
    assert "auto-accepted" in out and "not reachable" in out and "accepted locally" in out
    assert _repo(repo).head_snapshot()                  # history not corrupted


def test_single_file_protected_modules_escalate():
    # checkpoint-core's own sensitive code lives in single files, not dirs — must still escalate
    for f in ["checkpoint_core/policy.py", "checkpoint_core/sign.py", "checkpoint_core/identity.py",
              "checkpoint_core/remote.py", "checkpoint_core/server.py"]:
        assert _decide(changed_paths=[f])["decision"] == "escalate", f
    # and the allow-list is unaffected (no false escalation of docs)
    assert _decide(changed_paths=["docs/x.md", "README.md"], files_changed=2)["decision"] == "auto_accept"
