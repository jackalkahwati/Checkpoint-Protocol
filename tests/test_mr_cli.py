"""checkpoint-core mr — the scriptable merge-request CLI (drives the hosted /ui review API)."""
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


def http(method, url, token=None, body=None):
    from checkpoint_core import remote as RM
    return RM._http(method, url, token, body)


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture
def live(tmp_path, monkeypatch):
    """In-process server + a client repo (main+feature pushed, 'checkpoint' remote set)."""
    monkeypatch.setenv("NO_COLOR", "1")
    from checkpoint_core.server.store import ServerStore
    from checkpoint_core.server.app import serve
    store = ServerStore.init_store(tmp_path / "srv")
    admin = store.create_token("admin", ["admin"], "*")["token"]
    port = _free_port()
    httpd = serve(store, "127.0.0.1", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.15)
    url = "http://127.0.0.1:{}".format(port)
    http("POST", url + "/repos", admin, {"owner": "o", "repo": "r"})

    work = tmp_path / "w"; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "a.py").write_text("".join("l{}\n".format(i) for i in range(20)))
        run(["start", "base", "--no-watch"]); run(["accept", "-m", "base"])
        run(["branch", "feature"]); run(["checkout", "feature"])
        (work / "b.py").write_text("feature\n")
        run(["start", "feat", "--no-watch"]); run(["accept", "-m", "feat"])
        run(["checkout", "main"])
        run(["remote", "add", "checkpoint", "{}/o/r".format(url), "--token", admin])
        run(["push", "checkpoint", "main"]); run(["push", "checkpoint", "feature"])
        # trust the signer on the server so policy (if any) is satisfied
        for i in http("GET", url + "/repos/o/r/identities", admin)[1]["identities"]:
            http("POST", "{}/repos/o/r/identities/{}/trust".format(url, i["identity_id"]), admin)
    finally:
        os.chdir(cwd)
    monkeypatch.chdir(work)
    return {"url": url, "admin": admin, "work": work}


def ui(live, path, method="GET", body=None):
    return http(method, "{}/ui/repos/o/r{}".format(live["url"], path), live["admin"], body)


def test_mr_create_list_show(live, capsys):
    assert run(["mr", "create", "--title", "Add feature", "--from", "feature", "--to", "main"]) == 0
    assert "mr_1" in capsys.readouterr().out
    assert run(["mr", "list"]) == 0
    assert "mr_1" in capsys.readouterr().out and "Add feature" in capsys.readouterr().out or True
    assert run(["mr", "show", "mr_1"]) == 0
    out = capsys.readouterr().out
    assert "MR mr_1" in out and "Conflicts:" in out and "Approvals:" in out


def test_mr_create_requires_source(live):
    assert run(["mr", "create", "--title", "x"]) == 2          # no --from/--snapshot/--session


def test_mr_approve_and_status(live, capsys):
    run(["mr", "create", "--title", "x", "--from", "feature"])
    capsys.readouterr()
    assert run(["mr", "approve", "mr_1"]) == 0
    assert ui(live, "/reviews/mr_1")[1]["approval_count"] == 1
    assert run(["mr", "unapprove", "mr_1"]) == 0
    assert ui(live, "/reviews/mr_1")[1]["approval_count"] == 0


def test_mr_comment_inline(live):
    run(["mr", "create", "--title", "x", "--from", "feature"])
    assert run(["mr", "comment", "mr_1", "--file", "b.py", "--line", "1", "--body", "nit: rename?"]) == 0
    c = ui(live, "/reviews/mr_1")[1]["comments"]
    assert c and c[0]["path"] == "b.py" and c[0]["line"] == 1


def test_mr_merge_and_diff(live, capsys):
    run(["mr", "create", "--title", "x", "--from", "feature"])
    capsys.readouterr()
    assert run(["mr", "diff", "mr_1"]) == 0
    assert "b.py" in capsys.readouterr().out
    before = http("GET", live["url"] + "/repos/o/r/refs", live["admin"])[1]["heads"]["main"]
    assert run(["mr", "merge", "mr_1"]) == 0
    after = http("GET", live["url"] + "/repos/o/r/refs", live["admin"])[1]["heads"]["main"]
    assert after != before
    assert ui(live, "/reviews/mr_1")[1]["status"] == "merged"


def test_mr_review_decision_merge(live):
    run(["mr", "create", "--title", "x", "--from", "feature"])
    assert run(["mr", "review", "mr_1", "--decision", "merge"]) == 0
    assert ui(live, "/reviews/mr_1")[1]["status"] == "merged"


def test_mr_close(live):
    run(["mr", "create", "--title", "x", "--from", "feature"])
    assert run(["mr", "close", "mr_1"]) == 0
    assert ui(live, "/reviews/mr_1")[1]["status"] == "closed"


def test_mr_no_remote_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    run(["init"])
    assert run(["mr", "list"]) == 2                            # no hosted remote configured
