"""Phase 8 tests: hosted service API + HTTP remotes. No Git dependency."""
import base64
import io
import json
import os
import socket
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(argv):
    from checkpoint_core.cli import main
    return main(argv)


@pytest.fixture(autouse=True)
def _restore_cwd():
    cwd = os.getcwd()
    yield
    os.chdir(cwd)


def core_repo(p):
    from checkpoint_core.store import Repo
    return Repo(p)


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    from checkpoint_core.server.store import ServerStore
    from checkpoint_core.server.app import serve
    store = ServerStore.init_store(tmp_path / "srv")
    admin = store.create_token("admin", ["admin"], "*")["token"]
    port = _free_port()
    httpd = serve(store, "127.0.0.1", port)
    th = threading.Thread(target=httpd.serve_forever, daemon=True); th.start()
    time.sleep(0.15)
    yield {"store": store, "port": port, "url": "http://127.0.0.1:{}".format(port), "admin": admin}
    httpd.shutdown()


def http(method, url, token=None, body=None):
    from checkpoint_core import remote as RM
    return RM._http(method, url, token, body)


def raw_post(url, token, data, ctype="application/json"):
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype, "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def make_repo(server, owner="acme", name="app"):
    st, _ = http("POST", server["url"] + "/repos", server["admin"], {"owner": owner, "repo": name})
    return st


def populate(server, tmp, owner="acme", name="app", commits=2):
    """Create a signed local repo and push it to the server. Returns the work dir."""
    make_repo(server, owner, name)
    work = tmp / "work_{}_{}".format(owner, name)
    work.mkdir()
    cwd = os.getcwd(); os.chdir(work)
    try:
        run(["init"]); run(["identity", "create", "--name", "Jack", "--type", "human"])
        for i in range(commits):
            (work / "f.txt").write_text("v{}\n".format(i))
            run(["start", "c{}".format(i)]); run(["accept", "-m", "c{}".format(i)])
        url = "{}/{}/{}".format(server["url"], owner, name)
        run(["remote", "add", "origin", url, "--token", server["admin"]])
        run(["push", "origin", "main"])
    finally:
        os.chdir(cwd)
    return work


def repo_url(server, owner="acme", name="app"):
    return "{}/repos/{}/{}".format(server["url"], owner, name)


# ----------------------------------------------------------------- basics / auth

def test_health_version_capabilities(server):
    assert http("GET", server["url"] + "/health")[1]["status"] == "ok"
    assert http("GET", server["url"] + "/version")[1]["api"]
    assert "objects" in http("GET", server["url"] + "/capabilities")[1]["features"]


def test_create_repo(server):
    assert make_repo(server) == 201
    st, resp = http("GET", server["url"] + "/repos", server["admin"])
    assert "acme/app" in resp["repos"]


def test_token_auth_required(server):
    make_repo(server)
    st, _ = http("GET", repo_url(server) + "/refs")     # no token
    assert st == 401


def test_read_token_cannot_write_refs(server):
    make_repo(server)
    read_tok = server["store"].create_token("ro", ["repo:read"], "*")["token"]
    st, _ = http("POST", repo_url(server) + "/refs/update", read_tok,
                 {"ref": "refs/heads/main", "new_target": "x"})
    assert st == 403


def test_server_rejects_malformed_json(server):
    make_repo(server)
    st, _ = raw_post(repo_url(server) + "/objects/batch", server["admin"], b"{ not json")
    assert st == 400


# ----------------------------------------------------------------- security

def test_object_hash_mismatch_rejected(server):
    make_repo(server)
    st, resp = http("POST", repo_url(server) + "/objects/batch", server["admin"],
                    {"objects": [{"id": "a" * 64, "data_b64": base64.b64encode(b"x").decode()}]})
    assert st == 200 and resp["rejected"] and not resp["stored"]


def test_bundle_import_rejects_path_traversal(server, tmp_path):
    make_repo(server)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in [("../evil", b"x"), ("manifest.json", json.dumps({"refs": {}}).encode())]:
            ti = tarfile.TarInfo(n); ti.size = len(d); t.addfile(ti, io.BytesIO(d))
    st, resp = raw_post(repo_url(server) + "/bundles/import", server["admin"],
                        buf.getvalue(), "application/octet-stream")
    assert st == 422


def test_bundle_import_rejects_private_key(server):
    make_repo(server)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in [("keys/x.key", b"\x00" * 32), ("manifest.json", json.dumps({"refs": {}}).encode())]:
            ti = tarfile.TarInfo(n); ti.size = len(d); t.addfile(ti, io.BytesIO(d))
    st, _ = raw_post(repo_url(server) + "/bundles/import", server["admin"],
                     buf.getvalue(), "application/octet-stream")
    assert st == 422


def test_push_rejects_missing_parent_and_non_snapshot(server, tmp_path):
    from checkpoint_core import objects, util
    make_repo(server)
    # upload a snapshot whose parent does not exist
    tree = {"type": "tree", "entries": []}
    tree_b = util.canonical(tree); tree_id = util.sha256_bytes(tree_b)
    snap = objects.sign(objects.make_snapshot(tree=tree_id, parents=["0" * 64], session=None,
                        kind="accepted", message="x", author={"id": "a"}, timestamp=util.now_iso()), "a")
    snap_b = util.canonical(snap); snap_id = util.sha256_bytes(snap_b)
    http("POST", repo_url(server) + "/objects/batch", server["admin"],
         {"objects": [{"id": tree_id, "data_b64": base64.b64encode(tree_b).decode()},
                      {"id": snap_id, "data_b64": base64.b64encode(snap_b).decode()}]})
    st, resp = http("POST", repo_url(server) + "/sync/push", server["admin"],
                    {"branch": "main", "old_head": None, "new_head": snap_id})
    assert st == 422                                     # missing parent chain
    # ref to a non-snapshot (a blob)
    blob = b"hello"; bid = util.sha256_bytes(blob)
    http("POST", repo_url(server) + "/objects/batch", server["admin"],
         {"objects": [{"id": bid, "data_b64": base64.b64encode(blob).decode()}]})
    st2, _ = http("POST", repo_url(server) + "/sync/push", server["admin"],
                  {"branch": "main", "old_head": None, "new_head": bid})
    assert st2 == 422


def test_push_rejects_invalid_seal(server):
    from checkpoint_core import objects, util
    make_repo(server)
    tree = {"type": "tree", "entries": []}
    tree_b = util.canonical(tree); tree_id = util.sha256_bytes(tree_b)
    snap = objects.make_snapshot(tree=tree_id, parents=[], session=None, kind="accepted",
                                 message="x", author={"id": "a"}, timestamp=util.now_iso())
    snap["signature"] = {"algo": "sha256-seal", "author": "a", "seal": "deadbeef"}  # invalid
    snap_b = util.canonical(snap); snap_id = util.sha256_bytes(snap_b)
    http("POST", repo_url(server) + "/objects/batch", server["admin"],
         {"objects": [{"id": tree_id, "data_b64": base64.b64encode(tree_b).decode()},
                      {"id": snap_id, "data_b64": base64.b64encode(snap_b).decode()}]})
    st, _ = http("POST", repo_url(server) + "/sync/push", server["admin"],
                 {"branch": "main", "old_head": None, "new_head": snap_id})
    assert st == 422


# ----------------------------------------------------------------- HTTP remotes

def test_http_push_and_clone(server, tmp_path):
    populate(server, tmp_path)
    clone = tmp_path / "clone"
    os.chdir(str(tmp_path))
    assert run(["clone", repo_base(server), str(clone), "--token", server["admin"]]) == 0
    assert (clone / "f.txt").read_text() == "v1\n"
    os.chdir(str(clone))
    assert run(["verify-signatures"]) == 0
    assert run(["fsck"]) == 0


def repo_base(server):
    return "{}/acme/app".format(server["url"])


def test_http_fetch_writes_tracking_ref_only(server, tmp_path):
    populate(server, tmp_path)
    b = tmp_path / "b"; b.mkdir(); os.chdir(str(b)); run(["init"])
    run(["remote", "add", "origin", repo_base(server), "--token", server["admin"]])
    assert run(["fetch", "origin"]) == 0
    assert core_repo(b).read_ref("refs/remotes/origin/main") is not None
    assert core_repo(b).read_ref("refs/heads/main") is None


def test_http_pull_fast_forwards(server, tmp_path):
    populate(server, tmp_path)
    b = tmp_path / "b"; b.mkdir(); os.chdir(str(b)); run(["init"])
    run(["remote", "add", "origin", repo_base(server), "--token", server["admin"]])
    assert run(["pull", "origin", "main"]) == 0
    assert (b / "f.txt").exists()


def test_http_push_only_missing(server, tmp_path):
    from checkpoint_core import remote as RM
    work = populate(server, tmp_path)
    os.chdir(str(work))
    # pushing again sends 0 objects (server already has them)
    res = RM.push(core_repo(work), "origin", "main", dry_run=True)
    assert res["missing_on_remote"] == 0


def test_http_sync_status(server, tmp_path):
    populate(server, tmp_path)
    b = tmp_path / "b"; b.mkdir(); os.chdir(str(b)); run(["init"])
    run(["remote", "add", "origin", repo_base(server), "--token", server["admin"]])
    from checkpoint_core import remote as RM
    st = RM.sync_status(core_repo(b), "origin", "main")
    assert st["branches"][0]["relationship"] in ("behind", "behind (fetch needed)")


def test_http_public_identity_no_private_key(server, tmp_path):
    work = populate(server, tmp_path)
    clone = tmp_path / "clone2"; os.chdir(str(tmp_path))
    run(["clone", repo_base(server), str(clone), "--token", server["admin"]])
    from checkpoint_core import identity as I
    ids = I.list_all(core_repo(clone))
    assert ids and all(not I.has_private(core_repo(clone), r["identity_id"]) for r in ids)


def test_server_receipt_in_client_ledger(server, tmp_path):
    work = populate(server, tmp_path)
    ledger = (work / ".checkpoint" / "ledger.jsonl").read_text()
    assert any('"receipt_id"' in line for line in ledger.splitlines())


# ----------------------------------------------------------------- fast-forward

def test_server_rejects_non_fast_forward(server, tmp_path):
    populate(server, tmp_path)                           # server main = head H
    # a second client clones, both diverge; second push without fetch is non-ff
    other = tmp_path / "other"; os.chdir(str(tmp_path))
    run(["clone", repo_base(server), str(other), "--token", server["admin"]])
    # original work advances and pushes
    work = tmp_path / "work_acme_app"; os.chdir(str(work))
    (work / "f.txt").write_text("adv\n"); run(["start", "adv"]); run(["accept", "-m", "adv"])
    run(["push", "origin", "main"])
    # other advances from the OLD head and pushes -> non-ff
    os.chdir(str(other))
    run(["remote", "add", "origin", repo_base(server), "--token", server["admin"]])
    (other / "f.txt").write_text("other\n"); run(["start", "o"]); run(["accept", "-m", "o"])
    assert run(["push", "origin", "main"]) == 1


# ----------------------------------------------------------------- policy

def test_server_enforces_force_with_lease_policy(server, tmp_path):
    work = populate(server, tmp_path)
    # set a server policy that forbids force-with-lease
    import yaml
    from checkpoint_core import policy as P
    pol = dict(P.DEFAULT_STARTER_POLICY)
    pol["remote_rules"] = dict(pol["remote_rules"]); pol["remote_rules"]["allow_force_with_lease"] = False
    st, _ = http("PUT", repo_url(server) + "/policy", server["admin"], {"policy": pol})
    assert st == 200
    # a force-with-lease push is denied by policy
    cur = http("GET", repo_url(server) + "/refs", server["admin"])[1]["heads"]["main"]
    st, resp = http("POST", repo_url(server) + "/sync/push", server["admin"],
                    {"branch": "main", "old_head": cur, "new_head": cur, "force_with_lease": cur})
    assert st == 403


def test_server_records_policy_decisions(server, tmp_path):
    work = populate(server, tmp_path)
    import yaml
    from checkpoint_core import policy as P
    http("PUT", repo_url(server) + "/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    # trigger a push that the server evaluates (advance head)
    os.chdir(str(work))
    (work / "f.txt").write_text("more\n"); run(["start", "m"]); run(["accept", "-m", "m"])
    run(["push", "origin", "main"])
    st, resp = http("GET", repo_url(server) + "/policy/decisions", server["admin"])
    assert st == 200 and isinstance(resp["decisions"], list)


def test_policy_check_endpoint_read_only(server, tmp_path):
    populate(server, tmp_path)
    from checkpoint_core import policy as P
    http("PUT", repo_url(server) + "/policy", server["admin"], {"policy": P.DEFAULT_STARTER_POLICY})
    before = len(http("GET", repo_url(server) + "/policy/decisions", server["admin"])[1]["decisions"])
    http("POST", repo_url(server) + "/policy/check", server["admin"],
         {"operation": "accept", "actor_type": "agent"})
    after = len(http("GET", repo_url(server) + "/policy/decisions", server["admin"])[1]["decisions"])
    assert before == after                               # check records nothing


# ----------------------------------------------------------------- read endpoints

def test_sessions_packet_timeline_endpoints(server, tmp_path):
    work = populate(server, tmp_path)
    st, sessions = http("GET", repo_url(server) + "/sessions", server["admin"])
    assert st == 200 and sessions["sessions"]
    sid = sessions["sessions"][0]["session_id"]
    assert http("GET", repo_url(server) + "/sessions/{}/timeline".format(sid), server["admin"])[0] == 200
    # packet may be absent for a session that never ran `packet`; accept 200 or 404
    assert http("GET", repo_url(server) + "/sessions/{}/packet".format(sid), server["admin"])[0] in (200, 404)


def test_diff_endpoint_rename_aware(server, tmp_path):
    work = populate(server, tmp_path)
    r = core_repo(work)
    chain = r.history()
    a, b = chain[-1], chain[0]
    st, dr = http("POST", repo_url(server) + "/diff", server["admin"],
                  {"from": a, "to": b})
    assert st == 200 and "renamed" in dr and "modified" in dr


def test_merge_preview_does_not_mutate_refs(server, tmp_path):
    work = populate(server, tmp_path)
    r = core_repo(work)
    head = r.history()[0]
    before = http("GET", repo_url(server) + "/refs", server["admin"])[1]
    st, prev = http("POST", repo_url(server) + "/merge-preview", server["admin"],
                    {"ours": head, "theirs": head})
    assert st == 200 and "clean" in prev
    after = http("GET", repo_url(server) + "/refs", server["admin"])[1]
    assert before == after


def test_fsck_and_gc_endpoints(server, tmp_path):
    populate(server, tmp_path)
    st, rep = http("POST", repo_url(server) + "/fsck", server["admin"], {})
    assert st == 200 and rep["result"] == "healthy"
    st, gcrep = http("POST", repo_url(server) + "/gc", server["admin"], {"dry_run": True})
    assert st == 200 and gcrep["dry_run"] is True


def test_audit_records_events(server, tmp_path):
    populate(server, tmp_path)
    st, resp = http("GET", repo_url(server) + "/audit", server["admin"])
    assert st == 200 and any(e.get("operation") == "push" for e in resp["audit"])


# ----------------------------------------------------------------- concurrency

def test_concurrent_pushes_are_safe(server, tmp_path):
    from checkpoint_core import remote as RM
    make_repo(server, "acme", "conc")
    base_url = "{}/acme/conc".format(server["url"])
    # build two divergent client repos SERIALLY (chdir is process-global), each from empty
    repos = []
    for idx in range(2):
        w = tmp_path / "c{}".format(idx); w.mkdir()
        os.chdir(str(w))
        run(["init"])
        (w / "f.txt").write_text("client-{}\n".format(idx))
        run(["start", "c"]); run(["accept", "--no-verify", "-m", "c{}".format(idx)])
        run(["remote", "add", "origin", base_url, "--token", server["admin"]])
        repos.append(w)
    # push concurrently — push() takes no cwd dependency; server serializes via per-repo lock
    results = {}

    def client(idx):
        results[idx] = RM.push(core_repo(repos[idx]), "origin", "main")["status"]

    threads = [threading.Thread(target=client, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert list(results.values()).count("pushed") == 1   # exactly one wins; the other is non-ff
    st, rep = http("POST", "{}/repos/acme/conc/fsck".format(server["url"]), server["admin"], {})
    assert rep["result"] == "healthy"


# ----------------------------------------------------------------- no-git + structural

def test_server_no_git(server, tmp_path, monkeypatch):
    safe = tmp_path / "_nogit"; safe.mkdir()
    monkeypatch.setenv("PATH", str(safe))
    from shutil import which
    assert which("git") is None
    populate(server, tmp_path)
    clone = tmp_path / "clone_ng"; os.chdir(str(tmp_path))
    assert run(["clone", repo_base(server), str(clone), "--token", server["admin"]]) == 0
    os.chdir(str(clone))
    assert run(["fsck"]) == 0


def test_server_modules_no_git_bridge():
    import checkpoint_core.server.app as a
    import checkpoint_core.server.store as s
    assert "gitbridge" not in dir(a)
    assert "gitbridge" not in dir(s)
