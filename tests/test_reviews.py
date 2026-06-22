"""Merge Requests: create, comment/resolve, mergeability, server-signed merge, conflicts."""
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
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    from checkpoint_core.server.store import ServerStore
    from checkpoint_core.server.app import serve
    store = ServerStore.init_store(tmp_path / "srv")
    admin = store.create_token("admin", ["admin"], "*")["token"]
    port = _free_port()
    httpd = serve(store, "127.0.0.1", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.15)
    yield {"store": store, "url": "http://127.0.0.1:{}".format(port), "admin": admin}
    httpd.shutdown()


def ui(server, path, method="GET", body=None):
    return http(method, "{}/ui{}".format(server["url"], path), server["admin"], body)


def _client_repo(tmp, url, token, name="w"):
    """A client repo with main accepted, a feature branch with extra work, both pushed."""
    work = tmp / name; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "a.py").write_text("".join("l{}\n".format(i) for i in range(20)))
        run(["start", "base"]); run(["accept", "-m", "base"])
        run(["branch", "feature"]); run(["checkout", "feature"])
        (work / "b.py").write_text("new feature\n")          # disjoint add -> clean merge
        run(["start", "feature work"]); run(["accept", "-m", "feature work"])
        run(["checkout", "main"])
        run(["remote", "add", "origin", url, "--token", token])
        run(["push", "origin", "main"]); run(["push", "origin", "feature"])
    finally:
        os.chdir(cwd)
    return work


def _heads(server, owner="o", repo="r"):
    return http("GET", "{}/repos/{}/{}/refs".format(server["url"], owner, repo), server["admin"])[1]["heads"]


def setup_repo(server, tmp):
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "o", "repo": "r"})
    _client_repo(tmp, "{}/o/r".format(server["url"]), server["admin"])


def test_create_list_get_review(server, tmp_path):
    setup_repo(server, tmp_path)
    feature = _heads(server)["feature"]
    st, mr = ui(server, "/repos/o/r/reviews", "POST",
                {"title": "Add feature", "source_snapshot": feature, "target_branch": "main"})
    assert st == 201 and mr["id"] == "mr_1" and mr["status"] == "open"
    st, lst = ui(server, "/repos/o/r/reviews")
    assert st == 200 and len(lst) == 1
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert st == 200
    assert d["mergeability"]["clean"] is True            # disjoint add merges clean
    assert isinstance(d["diff"], list) and d["diff"]      # shows what the MR brings
    assert d["mergeable"] is True


def test_comments_thread_and_resolve(server, tmp_path):
    setup_repo(server, tmp_path)
    feature = _heads(server)["feature"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "x", "source_snapshot": feature})
    st, c = ui(server, "/repos/o/r/reviews/mr_1/comments", "POST",
               {"body": "looks good but check b.py", "path": "b.py"})
    assert st == 201 and c["id"] == "c1" and c["resolved"] is False and c["path"] == "b.py"
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["comment_count"] == 1 and d["unresolved_count"] == 1
    ui(server, "/repos/o/r/reviews/mr_1/comments/c1/resolve", "POST", {"resolved": True})
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["unresolved_count"] == 0


def test_merge_is_signed_and_advances_target(server, tmp_path):
    setup_repo(server, tmp_path)
    feature = _heads(server)["feature"]
    before = _heads(server)["main"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "merge me", "source_snapshot": feature})
    st, res = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert st == 200 and res["status"] == "merged"
    after = _heads(server)["main"]
    assert after != before                                # target advanced
    # the merge result snapshot is signed (by the reviewer service identity)
    sigs = http("POST", "{}/repos/o/r/verify-signatures".format(server["url"]), server["admin"], {})[1]
    assert sigs["ok"] is True
    # MR is now merged + idempotent
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["status"] == "merged"
    st, again = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert again["status"] == "invalid"                   # already merged -> not open


def test_merge_conflict_is_reported_not_applied(server, tmp_path):
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "o", "repo": "r"})
    work = tmp_path / "w"; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "f.py").write_text("base\n")
        run(["start", "base"]); run(["accept", "-m", "base"])
        run(["branch", "feature"]); run(["checkout", "feature"])
        (work / "f.py").write_text("FEATURE EDIT\n")
        run(["start", "fe"]); run(["accept", "-m", "fe"])
        run(["checkout", "main"])
        (work / "f.py").write_text("MAIN EDIT\n")          # same line -> conflict
        run(["start", "me"]); run(["accept", "-m", "me"])
        run(["remote", "add", "origin", "{}/o/r".format(server["url"]), "--token", server["admin"]])
        run(["push", "origin", "main"]); run(["push", "origin", "feature"])
    finally:
        os.chdir(cwd)
    feature = _heads(server)["feature"]
    main_before = _heads(server)["main"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "conflicting", "source_snapshot": feature})
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["mergeability"]["clean"] is False and "f.py" in d["mergeability"]["conflicts"]
    assert d["mergeable"] is False
    st, res = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert st == 409 and res["status"] == "conflicts" and "f.py" in res["conflicts"]
    assert _heads(server)["main"] == main_before          # target NOT moved


def test_close_review(server, tmp_path):
    setup_repo(server, tmp_path)
    feature = _heads(server)["feature"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "x", "source_snapshot": feature})
    st, d = ui(server, "/repos/o/r/reviews/mr_1/close", "POST", {})
    assert st == 200 and d["status"] == "closed"
    st, res = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert res["status"] == "invalid"                     # can't merge a closed MR


def test_approvals_tracked(server, tmp_path):
    setup_repo(server, tmp_path)
    feature = _heads(server)["feature"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "x", "source_snapshot": feature})
    st, mr = ui(server, "/repos/o/r/reviews/mr_1/approve", "POST", {"approve": True})
    assert st == 200 and mr["approval_count"] == 1
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["approval_count"] == 1 and "admin" in d["approvals"]
    # idempotent (same author) + removable
    ui(server, "/repos/o/r/reviews/mr_1/approve", "POST", {"approve": True})
    assert ui(server, "/repos/o/r/reviews/mr_1")[1]["approval_count"] == 1
    ui(server, "/repos/o/r/reviews/mr_1/approve", "POST", {"approve": False})
    assert ui(server, "/repos/o/r/reviews/mr_1")[1]["approval_count"] == 0


def test_min_approvals_policy_gates_merge(server, tmp_path):
    import copy
    from checkpoint_core import policy as P
    setup_repo(server, tmp_path)
    pol = copy.deepcopy(P.DEFAULT_STARTER_POLICY)
    pol["required_verification"] = {"default": False, "commands": []}
    pol["path_rules"] = [{"paths": ["b.py", "*.py", "**"], "require": {"min_approvals": 2}, "label": "needs-2"}]
    http("PUT", server["url"] + "/repos/o/r/policy", server["admin"], {"policy": pol})
    # trust the signer so only approvals gate the merge
    for i in http("GET", server["url"] + "/repos/o/r/identities", server["admin"])[1]["identities"]:
        http("POST", "{}/repos/o/r/identities/{}/trust".format(server["url"], i["identity_id"]), server["admin"])
    feature = _heads(server)["feature"]
    ui(server, "/repos/o/r/reviews", "POST", {"title": "needs approvals", "source_snapshot": feature})

    # 0 approvals -> policy denies, not mergeable
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["policy"]["effect"] == "deny" and d["mergeable"] is False
    st, res = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert st == 403 and res["status"] == "policy-denied"

    # 1 approval (admin) -> still denied
    ui(server, "/repos/o/r/reviews/mr_1/approve", "POST", {"approve": True})
    assert ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})[1]["status"] == "policy-denied"

    # 2nd distinct approver -> now allowed + merges
    tok2 = server["store"].create_token("reviewer2", ["admin"], "*")["token"]
    http("POST", "{}/ui/repos/o/r/reviews/mr_1/approve".format(server["url"]), tok2, {"approve": True})
    st, d = ui(server, "/repos/o/r/reviews/mr_1")
    assert d["approval_count"] == 2 and d["policy"]["effect"] != "deny" and d["mergeable"] is True
    st, res = ui(server, "/repos/o/r/reviews/mr_1/merge", "POST", {})
    assert st == 200 and res["status"] == "merged"
