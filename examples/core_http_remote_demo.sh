#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 8: the hosted service API + HTTP remotes.
# "Build the hosted API without weakening the protocol. Server verifies before refs move."
# Runs with no Git installed.
#
#   bash examples/core_http_remote_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
CS="$ROOT/bin/checkpoint-server"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
SRV_PID=""
cleanup() { [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null || true; echo; echo "demo left at: $WORK"; }
trap cleanup EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "init a server store + create a write token"
"$CS" init-store srv >/dev/null
TOKEN="$("$CS" token create --store srv --name dev --scopes repo:read,repo:write | awk '/token \(shown once\)/{print $NF}')"
echo "token: ${TOKEN:0:16}..."

step "start the hosted API on port $PORT"
"$CS" start --store srv --port "$PORT" >/dev/null 2>&1 &
SRV_PID=$!
sleep 1
echo "health: $(python3 -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:$PORT/health'))['status'])")"

step "create a repo on the server (POST /repos)"
python3 - "$PORT" "$TOKEN" <<'PY'
import sys, json, urllib.request
port, tok = sys.argv[1], sys.argv[2]
req = urllib.request.Request("http://127.0.0.1:%s/repos" % port,
    data=json.dumps({"owner":"acme","repo":"app"}).encode(),
    headers={"Content-Type":"application/json","Authorization":"Bearer "+tok}, method="POST")
print("created:", urllib.request.urlopen(req).status)
PY

URL="http://127.0.0.1:$PORT/acme/app"

step "build signed history locally and PUSH over HTTP"
mkdir client && cd client
"$CC" init >/dev/null
"$CC" identity create --name "Jack" --type human >/dev/null
printf "v1\n" > app.txt; "$CC" start "c1" >/dev/null; "$CC" accept -m "c1" >/dev/null
printf "v2\n" > app.txt; "$CC" start "c2" >/dev/null; "$CC" accept -m "c2" >/dev/null
"$CC" remote add origin "$URL" --token "$TOKEN"
"$CC" push origin main
echo "--- a server receipt is now in the client ledger ---"
grep -o '"receipt_id": "[^"]*"' .checkpoint/ledger.jsonl | tail -1

step "CLONE over HTTP into a fresh repo (server graph verified before refs move)"
cd "$WORK"
"$CC" clone "$URL" team-clone --token "$TOKEN"
cd team-clone
"$CC" history | head -2
"$CC" verify-signatures | tail -1
"$CC" fsck | tail -1
echo "app.txt -> $(cat app.txt)"

step "the server enforces the protocol: a hash-mismatched object is rejected"
python3 - "$PORT" "$TOKEN" <<'PY'
import sys, json, base64, urllib.request, urllib.error
port, tok = sys.argv[1], sys.argv[2]
body = json.dumps({"objects":[{"id":"a"*64,"data_b64":base64.b64encode(b"not matching").decode()}]}).encode()
req = urllib.request.Request("http://127.0.0.1:%s/repos/acme/app/objects/batch" % port,
    data=body, headers={"Content-Type":"application/json","Authorization":"Bearer "+tok}, method="POST")
resp = json.load(urllib.request.urlopen(req))
print("stored:", resp["stored"], "rejected:", [r["reason"] for r in resp["rejected"]])
PY

step "server-side audit log"
python3 - "$PORT" "$TOKEN" <<'PY'
import sys, json, urllib.request
port, tok = sys.argv[1], sys.argv[2]
req = urllib.request.Request("http://127.0.0.1:%s/repos/acme/app/audit" % port,
    headers={"Authorization":"Bearer "+tok})
for e in json.load(urllib.request.urlopen(req))["audit"][-5:]:
    print(" ", e.get("timestamp","")[:19], e.get("operation"), e.get("result",""))
PY

echo
echo "Demo complete. The hosted API moved verified, signed history over HTTP without Git."
