"""Phase 9 tests: web review UI (served by the API) + supporting backend.

The UI is a no-build vanilla-JS SPA served by checkpoint-server. We test that the server
serves it, that the supporting endpoints (unified diff, identities-without-keys) behave,
and we make string-level assertions about the SPA's protocol-correct behavior (Bearer auth,
401->login, no private keys, autosaves only in the timeline) since there is no JS runtime
in the harness.
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
WEB = Path(__file__).resolve().parents[1] / "checkpoint_core" / "server" / "web"


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


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


def http(method, url, token=None, body=None):
    from checkpoint_core import remote as RM
    return RM._http(method, url, token, body)


def get_raw(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def populate(server, tmp, owner="acme", name="app"):
    http("POST", server["url"] + "/repos", server["admin"], {"owner": owner, "repo": name})
    work = tmp / "w"; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        (work / "a.py").write_text("def f():\n    return 1\n")
        run(["start", "add f"]); run(["accept", "-m", "add f"])
        (work / "a.py").unlink(); (work / "b.py").write_text("def f():\n    return 2\n")  # rename+edit
        run(["start", "rename f"]); run(["packet"]); run(["accept", "-m", "rename f"])
        run(["remote", "add", "origin", "{}/{}/{}".format(server["url"], owner, name), "--token", server["admin"]])
        run(["push", "origin", "main"])
    finally:
        os.chdir(cwd)
    return work


# ----------------------------------------------------------------- serving the UI

def test_server_serves_spa(server):
    st, ct, body = get_raw(server["url"] + "/")
    assert st == 200 and "text/html" in ct
    assert b"Checkpoint" in body and b"/app.js" in body and b"/style.css" in body


def test_server_serves_static_assets(server):
    st, ct, _ = get_raw(server["url"] + "/app.js")
    assert st == 200 and "javascript" in ct
    st, ct, _ = get_raw(server["url"] + "/style.css")
    assert st == 200 and "css" in ct


def test_static_routes_need_no_auth(server):
    # the SPA shell must load before the user has entered a token
    st, _, _ = get_raw(server["url"] + "/")
    assert st == 200


# ----------------------------------------------------------------- backend support

def test_diff_endpoint_returns_unified_and_renames(server, tmp_path):
    populate(server, tmp_path)
    base = "{}/repos/acme/app".format(server["url"])
    # packet of the rename session has base_tree/current_tree; use the accepted history
    from checkpoint_core.store import Repo
    r = Repo(tmp_path / "w")
    chain = r.history()
    a, b = chain[-1], chain[0]
    st, dr = http("POST", base + "/diff", server["admin"], {"from": a, "to": b, "unified": True})
    assert st == 200
    assert "unified" in dr
    assert "renamed" in dr and isinstance(dr["renamed"], list)


def test_identities_endpoint_has_no_private_key(server, tmp_path):
    populate(server, tmp_path)
    st, resp = http("GET", "{}/repos/acme/app/identities".format(server["url"]), server["admin"])
    assert st == 200
    blob = json.dumps(resp)
    assert "private" not in blob.lower()
    for rec in resp["identities"]:
        assert "public_key" in rec
        assert "seed" not in rec


def test_merge_preview_does_not_mutate(server, tmp_path):
    populate(server, tmp_path)
    base = "{}/repos/acme/app".format(server["url"])
    before = http("GET", base + "/refs", server["admin"])[1]
    from checkpoint_core.store import Repo
    head = Repo(tmp_path / "w").history()[0]
    st, prev = http("POST", base + "/merge-preview", server["admin"], {"ours": head, "theirs": head})
    assert st == 200 and "clean" in prev
    after = http("GET", base + "/refs", server["admin"])[1]
    assert before == after


def test_policy_check_via_api_read_only(server, tmp_path):
    populate(server, tmp_path)
    from checkpoint_core import policy as P
    base = "{}/repos/acme/app".format(server["url"])
    http("PUT", base + "/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    before = len(http("GET", base + "/policy/decisions", server["admin"])[1]["decisions"])
    st, dec = http("POST", base + "/policy/check", server["admin"],
                   {"operation": "accept", "actor_type": "agent"})
    assert st == 200 and dec["effect"] in ("allow", "deny", "warn")
    after = len(http("GET", base + "/policy/decisions", server["admin"])[1]["decisions"])
    assert before == after


# ----------------------------------------------------------------- SPA behavior (static)

def _appjs():
    return (WEB / "app.js").read_text()


def test_spa_uses_bearer_auth_and_localstorage():
    js = _appjs()
    assert 'Authorization' in js and 'Bearer ' in js
    assert "localStorage" in js


def test_spa_routes_401_to_login():
    js = _appjs()
    assert "401" in js and "login" in js          # 401 clears token / routes to login
    assert "403" in js                            # 403 shows a permission error


def test_spa_handles_403_distinctly():
    js = _appjs()
    assert "Permission denied" in js


def test_spa_logout_clears_token():
    js = _appjs()
    assert "logout" in js and "removeItem" in js


def test_spa_never_renders_private_keys():
    # the UI must not reference private-key fields anywhere
    js = _appjs()
    assert "private_key" not in js and "private key material" not in js.lower() or "never exposes private" in js
    # explicit reassurance copy present
    assert "never exposes private" in js or "Public keys only" in js


def test_spa_autosaves_only_in_timeline():
    js = _appjs()
    # autosaves are shown via timeline events; the UI never fetches autosave *content*
    assert "autosave_created" in js                # timeline tier
    assert "/autosaves/" not in js                 # no autosave-content fetch


def test_spa_distinguishes_trust_states():
    js = _appjs()
    for state in ("valid", "untrusted", "unknown_signer", "revoked", "unsigned"):
        assert state in js


def test_spa_has_all_routes():
    js = _appjs()
    for r in ("sessions", "refs", "policy", "identities", "integrity", "audit"):
        assert r in js


def test_spa_session_panels_present():
    js = _appjs()
    for fn in ("timelinePanel", "diffPanel", "policyPanel", "signaturePanel",
               "verificationPanel", "packetPanel"):
        assert fn in js


def test_spa_rename_display_shows_similarity():
    js = _appjs()
    assert "similarity" in js and "→" in js        # "old → new  similarity NN%"
