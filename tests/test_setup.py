"""`checkpoint-core setup` — one-shot repo setup (init + identity + ignore + remote + server repo + policy)."""
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
    yield {"url": "http://127.0.0.1:{}".format(port), "admin": admin}
    httpd.shutdown()


def test_setup_local_only(tmp_path, monkeypatch):
    """Without --server: init + identity + .checkpointignore, no remote."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    assert run(["setup"]) == 0
    from checkpoint_core.store import Repo
    r = Repo(tmp_path)
    assert (tmp_path / ".checkpoint").exists()
    assert r.current_identity_id()                      # identity created + selected
    assert (tmp_path / ".checkpointignore").exists()
    assert "node_modules" in (tmp_path / ".checkpointignore").read_text()


def test_setup_full_with_server(server, tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    work = tmp_path / "myproj"; work.mkdir()
    monkeypatch.chdir(work)
    (work / "README.md").write_text("hi\n")
    assert run(["setup", "--server", server["url"], "--token", server["admin"]]) == 0

    # server repo created (named after the directory)
    repos = http("GET", server["url"] + "/repos", server["admin"])[1]["repos"]
    assert "jack/myproj" in repos
    # remote wired
    from checkpoint_core.store import Repo
    assert "checkpoint" in Repo(work).config.data.get("remotes", {})
    # policy applied
    st, cfg = http("GET", server["url"] + "/ui/repos/jack/myproj/policy", server["admin"])
    assert "main" in cfg["protected_branches"]
    # the whole signed flow then works in this repo
    assert run(["start", "work", "--no-watch"]) == 0
    assert run(["accept", "-m", "work"]) == 0
    assert run(["push", "checkpoint", "main"]) == 0


def test_setup_is_idempotent(server, tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    work = tmp_path / "proj2"; work.mkdir()
    monkeypatch.chdir(work)
    assert run(["setup", "--server", server["url"], "--token", server["admin"]]) == 0
    idid = __import__("checkpoint_core.store", fromlist=["Repo"]).Repo(work).current_identity_id()
    # second run: no overwrite, same identity, still succeeds
    assert run(["setup", "--server", server["url"], "--token", server["admin"]]) == 0
    assert __import__("checkpoint_core.store", fromlist=["Repo"]).Repo(work).current_identity_id() == idid


def test_setup_custom_name_and_owner(server, tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    assert run(["setup", "--server", server["url"], "--token", server["admin"],
                "--owner", "acme", "--name", "widgets", "--no-policy"]) == 0
    repos = http("GET", server["url"] + "/repos", server["admin"])[1]["repos"]
    assert "acme/widgets" in repos
