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
    rn = [d for d in diff if d["change_type"] == "renamed" and d.get("similarity")]
    assert rn
    # similarity is a 0..100 percentage (the frontend renders `{similarity}%`), not a 0..1 fraction
    assert rn[0]["similarity"] > 1 and rn[0]["similarity"] <= 100


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


def test_ui_session_policy_reflects_verification_and_signature(server, tmp_path):
    """The per-session Policy Decision must use the session's REAL verification results,
    signature state, and acceptor trust — not a bare input that falsely reports
    'verification not passed' / 'signed accept required' for an accepted, signed, verified
    session. (Regression for the Playwright-reviewed policy-panel bug.)"""
    import yaml
    from checkpoint_core import policy as P
    http("POST", server["url"] + "/repos", server["admin"], {"owner": "v", "repo": "r"})
    work = tmp_path / "w2"; work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        cfg = work / ".checkpoint" / "config.yaml"
        d = yaml.safe_load(cfg.read_text())
        d.setdefault("verification", {})["commands"] = [
            {"name": "tests", "run": "exit 0"}, {"name": "lint", "run": "exit 0"}]
        cfg.write_text(yaml.safe_dump(d, sort_keys=False))
        (work / "app.py").write_text("x = 1\n")
        run(["start", "do work"]); run(["verify"]); run(["accept", "-m", "do work"])
        run(["remote", "add", "origin", "{}/v/r".format(server["url"]), "--token", server["admin"]])
        run(["push", "origin", "main"])
    finally:
        os.chdir(cwd)
    # configure policy and trust the signer on the server
    http("PUT", server["url"] + "/repos/v/r/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    ids = http("GET", server["url"] + "/repos/v/r/identities", server["admin"])[1]["identities"]
    for i in ids:
        http("POST", "{}/repos/v/r/identities/{}/trust".format(server["url"], i["identity_id"]), server["admin"])
    sid = http("GET", server["url"] + "/ui/repos/v/r/sessions", server["admin"])[1][0]["session_id"]
    st, dec = http("GET", "{}/ui/repos/v/r/sessions/{}/policy".format(server["url"], sid), server["admin"])
    assert st == 200
    joined = " ".join(dec["reasons"]).lower()
    assert "verification" not in joined        # verification passed -> no such reason
    assert "signed accept" not in joined       # the accept was signed -> no such reason
    assert dec["effect"] == "allow"            # signed + verified + trusted -> allow


def test_ui_identity_trust_untrust_revoke(server, tmp_path):
    """The Identities table's Trust/Revoke buttons map to /ui write endpoints; identities
    expose an `id` so the UI can address them. (Regression for cosmetic-buttons bug.)"""
    populate(server, tmp_path)
    ids = ui(server, base(server) + "/identities")[1]
    assert ids and ids[0].get("id"), "identity must expose an id for the UI to act on"
    iid = ids[0]["id"]
    b = base(server)
    # imported identities start untrusted
    assert ui(server, b + "/identities/" + iid + "/trust", "POST")[1]["trust_status"] == "trusted"
    assert ui(server, b + "/identities/" + iid + "/untrust", "POST")[1]["trust_status"] == "untrusted"
    assert ui(server, b + "/identities/" + iid + "/revoke", "POST")[1]["trust_status"] == "revoked"
    # unknown identity -> 404
    assert ui(server, b + "/identities/nope/trust", "POST")[0] == 404


def test_ui_requires_auth(server):
    st, _ = http("GET", server["url"] + "/ui/repos")   # no token
    assert st == 401


def test_ui_modules_no_git_bridge():
    import checkpoint_core.server.ui_api as u
    assert "gitbridge" not in dir(u)
