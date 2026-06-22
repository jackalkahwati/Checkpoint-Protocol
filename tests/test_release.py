"""v1.0 public-preview acceptance tests: CLI help, versioning, diagnostics, migrate,
bug-report redaction, demos, docs, and release hygiene."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ----------------------------------------------------------------- help / version

def test_core_help_works():
    from checkpoint_core.cli import main
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code in (0, None)


def test_server_help_works():
    from checkpoint_core.server.cli import main
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code in (0, None)


def test_console_script_callables_exist():
    import checkpoint_core.cli, checkpoint_core.server.cli, checkpoint.cli
    assert callable(checkpoint_core.cli.main)
    assert callable(checkpoint_core.server.cli.main)
    assert callable(checkpoint.cli.main)


def test_version_reports_protocol_and_store(repo, capsys):
    run(["init"])
    capsys.readouterr()                       # drop init output
    assert run(["version", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["protocol_version"] == "1.0"
    assert out["store_version_supported"] == 1
    assert "no-git" in out["features"]
    assert out["checkpoint_core"] == "1.0.0-preview"


def test_server_version_json():
    from checkpoint_core.server.cli import main
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["version", "--json"])
    out = json.loads(buf.getvalue())
    assert out["api_version"] and out["protocol_version"] == "1.0"


# ----------------------------------------------------------------- init / doctor / migrate

def test_init_in_non_git_dir(repo):
    assert not (repo / ".git").exists()
    assert run(["init"]) == 0
    assert (repo / ".checkpoint" / "HEAD").exists()


def test_doctor_json(repo, capsys):
    run(["init"])
    capsys.readouterr()                       # drop init output
    assert run(["doctor", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and "checks" in out


def test_migrate_status_plan_apply(repo, capsys):
    run(["init"])
    assert run(["migrate", "status"]) == 0
    assert run(["migrate", "plan"]) == 0
    assert run(["migrate", "apply"]) == 0
    capsys.readouterr()
    assert run(["migrate", "status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["up_to_date"] is True


# ----------------------------------------------------------------- bug-report redaction

def test_bug_report_redacts_and_excludes_keys(repo):
    import tarfile
    run(["init"])
    run(["identity", "create", "--name", "Jack", "--type", "human"])
    # put a secret into the policy file (a collected artifact) to prove redaction
    run(["policy", "init"])
    pol = repo / ".checkpoint" / "policy.yaml"
    pol.write_text(pol.read_text() + '\n# token: AKIAIOSFODNN7EXAMPLE\n')
    out = repo / "report.tar.gz"
    assert run(["bug-report", "--out", str(out)]) == 0
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert not any("keys/" in n or n.endswith(".key") for n in names)   # no private keys
        for m in tar.getmembers():
            if m.isfile():
                data = tar.extractfile(m).read()
                assert b"AKIAIOSFODNN7EXAMPLE" not in data                   # secret redacted


# ----------------------------------------------------------------- agent helper

def test_agent_begin_and_status(repo):
    run(["init"])
    (repo / "f.txt").write_text("x\n")
    assert run(["agent", "begin", "agent task", "--agent", "bot", "--model", "m1", "--tool", "Edit"]) == 0
    from checkpoint_core.store import Repo
    sid = Repo(repo).active_session_id()
    from checkpoint_core import util
    sess = util.read_json(Repo(repo).paths.session_dir(sid) / "session.json")
    assert sess["actor"]["type"] == "agent"
    assert sess["agent"]["model"] == "m1"


# ----------------------------------------------------------------- demos

def _run_demo(name):
    p = subprocess.run(["bash", str(ROOT / "examples" / name)],
                       capture_output=True, text=True, env={"NO_COLOR": "1", "PATH": __import__("os").environ["PATH"]})
    return p


def test_demo_core_vcs_runs():
    p = _run_demo("demo_01_core_vcs.sh")
    assert p.returncode == 0 and "OK demo_01" in p.stdout, p.stdout + p.stderr


def test_demo_rename_merge_runs():
    p = _run_demo("demo_03_rename_merge.sh")
    assert p.returncode == 0 and "OK demo_03" in p.stdout, p.stdout + p.stderr


def test_demo_remote_sync_runs():
    p = _run_demo("demo_05_remote_sync.sh")
    assert p.returncode == 0 and "OK demo_05" in p.stdout, p.stdout + p.stderr


def test_all_demos_present_and_valid_bash():
    for n in ("demo_01_core_vcs", "demo_02_autosave_recovery", "demo_03_rename_merge",
              "demo_04_signed_policy", "demo_05_remote_sync", "demo_06_hosted_web_ui", "demo_all"):
        f = ROOT / "examples" / (n + ".sh")
        assert f.exists()
        assert subprocess.run(["bash", "-n", str(f)]).returncode == 0  # syntax-valid


# ----------------------------------------------------------------- release hygiene

def test_release_check_script_valid():
    f = ROOT / "scripts" / "release_check.sh"
    assert f.exists()
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0


def test_ci_workflow_is_valid_yaml():
    import yaml
    f = ROOT / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(f.read_text())
    assert "jobs" in data and "test" in data["jobs"]


def test_governance_files_exist():
    for f in ("CHANGELOG.md", "RELEASE_NOTES.md", "CONTRIBUTING.md", "SECURITY.md", "ROADMAP.md"):
        assert (ROOT / f).exists()


def test_changelog_covers_v01_to_v10():
    cl = (ROOT / "CHANGELOG.md").read_text()
    assert "v1.0.0-preview" in cl and "v0.1-core" in cl


def test_release_notes_has_known_limitations():
    rn = (ROOT / "RELEASE_NOTES.md").read_text()
    assert "Known limitations" in rn


def test_security_warns_token_storage_and_no_tls():
    s = (ROOT / "SECURITY.md").read_text().lower()
    assert "localstorage" in s and "no tls" in s


def test_readme_first_screen_explains_product():
    head = "\n".join((ROOT / "README.md").read_text().splitlines()[:40]).lower()
    assert "checkpoint" in head
    assert "session" in head
    assert "git" in head           # the Git distinction is up top


def test_git_adapter_labeled_as_adapter():
    spec = (ROOT / "docs" / "checkpoint-protocol.md").read_text().lower()
    assert "adapter" in spec
    assert "not the main protocol" in spec or "adoption wedge" in spec


def test_doc_links_resolve():
    # every relative .md link in README + docs/ must point to an existing file
    md_files = [ROOT / "README.md"] + list((ROOT / "docs").glob("*.md"))
    link_re = re.compile(r"\]\(([^)]+\.md)(#[^)]*)?\)")
    missing = []
    for md in md_files:
        for m in link_re.finditer(md.read_text()):
            target = m.group(1)
            if target.startswith("http"):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                missing.append("{} -> {}".format(md.name, target))
    assert not missing, "broken doc links: " + "; ".join(missing)
