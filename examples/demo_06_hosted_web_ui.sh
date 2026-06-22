#!/usr/bin/env bash
# Hosted API + web UI: start server, create repo/token, push, show UI URL. No Git.
source "$(dirname "$0")/_demo_lib.sh"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
"$CS" init-store srv >/dev/null
TOKEN="$("$CS" token create --store srv --name local-dev --repo jack/demo --scopes repo:read,repo:write,admin | awk '/token \(shown once\)/{print $NF}')"
step "start the hosted API + web UI on :$PORT"
"$CS" start --store srv --port "$PORT" >/dev/null 2>&1 & SPID=$!
sleep 1
step "create repo jack/demo via the API"
python3 - "$PORT" "$TOKEN" <<'PY'
import sys,json,urllib.request
p,t=sys.argv[1],sys.argv[2]
r=urllib.request.Request("http://127.0.0.1:%s/repos"%p,data=json.dumps({"owner":"jack","repo":"demo"}).encode(),
  headers={"Content-Type":"application/json","Authorization":"Bearer "+t},method="POST")
print("created:",urllib.request.urlopen(r).status)
PY
step "push a signed session over HTTP"
mkdir client; cd client; "$CC" init >/dev/null
"$CC" identity create --name Jack --type human >/dev/null
printf "v1\n" > app.txt; "$CC" start "first change" >/dev/null; "$CC" accept -m "first change" >/dev/null
"$CC" remote add origin "http://127.0.0.1:$PORT/jack/demo" --token "$TOKEN"
"$CC" push origin main
step "web UI is live"
echo "  open: http://127.0.0.1:$PORT/   (paste the token to log in)"
echo "  health: $(python3 -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:$PORT/health'))['status'])")"
kill "$SPID" 2>/dev/null || true
echo; echo "OK demo_06"
