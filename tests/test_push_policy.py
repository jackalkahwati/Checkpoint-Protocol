"""Hosted push must judge policy by the snapshot's signer, not a hardcoded 'ci' role.

Regression: a human-signed, human-accepted snapshot pushed to a policy-protected repo was
denied with "actor type 'ci' may not push" because the server hardcoded actor_type='ci'.
The server now derives the actor type from the pushed snapshot's signer.
"""
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
    yield {"store": store, "port": port, "url": "http://127.0.0.1:{}".format(port), "admin": admin}
    httpd.shutdown()


def _make_repo(tmp, url, token, sign=True, name="w"):
    work = tmp / name; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "app.py").write_text("x = 1\n")
        run(["start", "work"])
        run(["accept", "-m", "work"] + ([] if sign else ["--no-sign"]))
        run(["remote", "add", "origin", url, "--token", token])
    finally:
        os.chdir(cwd)
    return work


def _push(work):
    cwd = os.getcwd(); os.chdir(work)
    try:
        return run(["push", "origin", "main"])
    finally:
        os.chdir(cwd)


def test_pusher_actor_type_helper(server, tmp_path):
    """The helper returns the signer's type, not a hardcoded role."""
    from checkpoint_core.server import app as A
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "o", "repo": "r"})
    work = _make_repo(tmp_path, "{}/o/r".format(server["url"]), server["admin"], sign=True)
    _push(work)
    repo = server["store"].get_repo("o", "r")
    head = repo.head_snapshot()
    assert A._pusher_actor_type(repo, head) == "human"        # derived from the signer
    assert A._pusher_actor_type(repo, "deadbeef") == "ci"     # unknown/unsigned -> fallback


def test_human_signed_push_passes_starter_policy(server, tmp_path):
    """Regression: previously denied as 'ci may not push'; now judged by the human signer."""
    from checkpoint_core import policy as P
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "o", "repo": "r"})
    http("PUT", server["url"] + "/repos/o/r/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    work = _make_repo(tmp_path, "{}/o/r".format(server["url"]), server["admin"], sign=True)
    assert _push(work) == 0                                    # human-signed push allowed
    assert http("GET", server["url"] + "/repos/o/r/refs", server["admin"])[1]["heads"]["main"]


def test_unsigned_push_still_denied_by_policy(server, tmp_path):
    """Enforcement intact: an unsigned snapshot falls back to actor 'ci', which can't push."""
    from checkpoint_core import policy as P
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "o2", "repo": "r2"})
    http("PUT", server["url"] + "/repos/o2/r2/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    work = _make_repo(tmp_path, "{}/o2/r2".format(server["url"]), server["admin"], sign=False, name="w2")
    assert _push(work) != 0                                    # unsigned -> ci -> denied
    assert "main" not in http("GET", server["url"] + "/repos/o2/r2/refs", server["admin"])[1].get("heads", {})
