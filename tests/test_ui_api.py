"""Tests for the /ui/* backend-for-frontend adapter and CORS that back the Next.js UI.

These assert the BFF returns exactly the shapes the frontend's TypeScript types expect,
and that CORS preflight works so a separate frontend dev server can call the API.
"""
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


def populate(server, tmp, owner="acme", name="app"):
    http("POST", server["url"] + "/repos", server["admin"], {"owner": owner, "repo": name})
    work = tmp / "w"; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        # a larger file so the rename is detected with hunks
        (work / "a.py").write_text("".join("line {}\n".format(i) for i in range(20)))
        run(["start", "add module"]); run(["accept", "-m", "add module"])
        (work / "a.py").unlink()
        (work / "b.py").write_text("".join("line {}\n".format(i) for i in range(20)).replace("line 3", "LINE 3 changed"))
        run(["start", "rename + edit"]); run(["packet"]); run(["accept", "-m", "rename module"])
        run(["remote", "add", "origin", "{}/{}/{}".format(server["url"], owner, name), "--token", server["admin"]])
        run(["push", "origin", "main"])
    finally:
        os.chdir(cwd)
    return work


def ui(server, path, method="GET", body=None):
    return http(method, "{}/ui{}".format(server["url"], path), server["admin"], body)


def base(server):
    return "/repos/acme/app"


# ----------------------------------------------------------------- CORS

def test_cors_headers_present(server):
    import urllib.request
    req = urllib.request.Request(server["url"] + "/ui/health")
    with urllib.request.urlopen(req) as r:
        assert r.headers.get("Access-Control-Allow-Origin") == "*"


def test_cors_preflight_options(server):
    st, _ = http("OPTIONS", server["url"] + "/ui/repos", server["admin"])
    assert st == 204


# ----------------------------------------------------------------- shapes

def test_ui_health_shape(server):
    st, h = ui(server, "/health")
    assert st == 200 and h["ok"] is True and "version" in h and "uptime_s" in h


def test_ui_repos_is_array_with_badges(server, tmp_path):
    populate(server, tmp_path)
    st, repos = ui(server, "/repos")
    assert st == 200 and isinstance(repos, list)
    r = next(x for x in repos if x["owner"] == "acme" and x["name"] == "app")
    for k in ("branch_count", "recent_sessions", "latest_accepted_snapshot",
              "policy_status", "signature_status", "trust_status", "fsck_status", "alerts"):
        assert k in r
    assert r["fsck_status"] in ("healthy", "warnings", "corrupt")


def test_ui_sessions_array_and_session_badges(server, tmp_path):
    populate(server, tmp_path)
    st, sessions = ui(server, base(server) + "/sessions")
    assert st == 200 and isinstance(sessions, list) and sessions
    s = sessions[0]
    for k in ("session_id", "instruction", "status", "actor_type",
              "verification_status", "policy_effect", "signature_status", "fsck_status"):
        assert k in s
    assert s["signature_status"] in ("valid", "invalid", "unsigned")
    assert s["actor_type"] in ("human", "agent", "ci", "machine", "service")


def test_ui_session_diff_has_hunks_and_renames(server, tmp_path):
    populate(server, tmp_path)
    sessions = ui(server, base(server) + "/sessions")[1]
    # the rename session is the most recent
    sid = sessions[0]["session_id"] if sessions[0]["instruction"].startswith("rename") else sessions[-1]["session_id"]
    st, diff = ui(server, base(server) + "/sessions/" + sid + "/diff")
    assert st == 200 and isinstance(diff, list) and diff
    f = diff[0]
    for k in ("old_path", "new_path", "change_type", "additions", "deletions", "hunks"):
        assert k in f
    # a 20-line file with one changed line -> detected as a rename with hunks
    assert any(d["change_type"] == "renamed" and d.get("similarity") for d in diff)


def test_ui_session_packet_and_timeline(server, tmp_path):
    populate(server, tmp_path)
    sid = ui(server, base(server) + "/sessions")[1][-1]["session_id"]
    st, pkt = ui(server, base(server) + "/sessions/" + sid + "/packet")
    assert st == 200 and (pkt is None or ("changed_paths" in pkt and "recommended_action" in pkt))
    st, tl = ui(server, base(server) + "/sessions/" + sid + "/timeline")
    assert st == 200 and isinstance(tl, list)
    assert all("type" in e and "at" in e and "title" in e for e in tl)


def test_ui_session_signatures_shape(server, tmp_path):
    populate(server, tmp_path)
    s = next(x for x in ui(server, base(server) + "/sessions")[1] if x["accepted_snapshot"])
    st, sigs = ui(server, base(server) + "/sessions/" + s["session_id"] + "/signatures")
    assert st == 200 and isinstance(sigs, list) and sigs
    sig = sigs[0]
    for k in ("signer_name", "signer_type", "trust_status", "status"):
        assert k in sig
    assert sig["status"] in ("valid", "invalid", "unsigned")
    assert sig["trust_status"] in ("trusted", "untrusted", "unknown", "revoked")


def test_ui_integrity_shape(server, tmp_path):
    populate(server, tmp_path)
    st, integ = ui(server, base(server) + "/integrity")
    assert st == 200
    for k in ("fsck_status", "seal_status", "object_count", "dangling_count",
              "corrupt_count", "missing_count", "last_gc_result"):
        assert k in integ
    assert integ["fsck_status"] == "healthy" and integ["seal_status"] == "sealed"


def test_ui_identities_and_branches(server, tmp_path):
    populate(server, tmp_path)
    st, ids = ui(server, base(server) + "/identities")
    assert st == 200 and isinstance(ids, list) and ids
    assert all("trust_status" in i and "fingerprint" in i for i in ids)
    # imported public identities arrive untrusted
    assert all("private" not in json.dumps(i).lower() for i in ids)
    st, br = ui(server, base(server) + "/branches")
    assert st == 200 and isinstance(br, list) and br[0]["name"] == "main"


def test_ui_policy_config_and_check(server, tmp_path):
    from checkpoint_core import policy as P
    populate(server, tmp_path)
    http("PUT", "{}/repos/acme/app/policy".format(server["url"]), server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    st, cfg = ui(server, base(server) + "/policy")
    assert st == 200 and "protected_branches" in cfg and "path_rules" in cfg
    st, dec = ui(server, base(server) + "/policy/check", "POST", {"operation": "accept", "actor_type": "agent"})
    assert st == 200 and dec["effect"] in ("allow", "deny", "warn")
    for k in ("matched_rules", "reasons", "required_actions", "override_available"):
        assert k in dec


def test_ui_audit_and_fsck(server, tmp_path):
    populate(server, tmp_path)
    st, au = ui(server, base(server) + "/audit")
    assert st == 200 and isinstance(au, list)
    assert all("result" in e and e["result"] in ("success", "denied", "error") for e in au)
    st, fk = ui(server, base(server) + "/fsck", "POST", {})
    assert st == 200 and fk["fsck_status"] == "healthy"


def test_ui_verify_signatures_array(server, tmp_path):
    populate(server, tmp_path)
    st, sigs = ui(server, base(server) + "/signatures/verify", "POST", {})
    assert st == 200 and isinstance(sigs, list)


def test_ui_requires_auth(server):
    st, _ = http("GET", server["url"] + "/ui/repos")   # no token
    assert st == 401


def test_ui_modules_no_git_bridge():
    import checkpoint_core.server.ui_api as u
    assert "gitbridge" not in dir(u)
