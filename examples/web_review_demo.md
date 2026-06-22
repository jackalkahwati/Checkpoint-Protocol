# Web Review UI — end-to-end walkthrough

This walks through hosting a repo, pushing a signed AI session, and reviewing it in the
browser. No Git required.

## 1. Start the server + UI

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
export PATH="$PWD/bin:$PATH"

checkpoint-server init-store /tmp/ckpt-srv
TOKEN=$(checkpoint-server token create --store /tmp/ckpt-srv --name dev \
        --scopes repo:read,repo:write | awk '/token \(shown once\)/{print $NF}')
checkpoint-server start --store /tmp/ckpt-srv --port 8800 &
```

## 2. Create a repo (API)

```bash
python3 - "$TOKEN" <<'PY'
import sys, json, urllib.request
tok = sys.argv[1]
req = urllib.request.Request("http://127.0.0.1:8800/repos",
    data=json.dumps({"owner":"acme","repo":"app"}).encode(),
    headers={"Content-Type":"application/json","Authorization":"Bearer "+tok}, method="POST")
print("created:", urllib.request.urlopen(req).status)
PY
```

## 3. Produce a signed AI work session and push it

```bash
mkdir -p /tmp/ckpt-work && cd /tmp/ckpt-work
checkpoint-core init
checkpoint-core identity create --name "Claude Code" --type agent      # an AI agent identity
checkpoint-core identity create --name "Jack" --type human             # a human reviewer/acceptor

# (the agent works; a human accepts — agents can't self-accept under the starter policy)
printf "exposure: auto\nfps: 30\n" > camera.yaml
checkpoint-core start "fix camera exposure defaults without changing autonomy" \
    --agent "Claude Code" --model opus-4.8 --tool Edit --tag hardware
printf "exposure: 1/500\nfps: 30\n" > camera.yaml
checkpoint-core snapshot -m "tune exposure"
checkpoint-core packet
checkpoint-core identity use "$(checkpoint-core identity list | awk '/human/{print $2}' | head -1)"
checkpoint-core accept -m "fix camera exposure defaults"

checkpoint-core remote add origin http://127.0.0.1:8800/acme/app --token "$TOKEN"
checkpoint-core push origin main
```

## 4. Review in the browser

Open **http://127.0.0.1:8800/** and paste `$TOKEN` on the login screen.

- **Dashboard** lists `acme/app`.
- Open the repo → **Recent sessions** → click the session.
- The **session review page** shows, in one view:
  - the **instruction** and the **agent/model/tool** that produced the work,
  - the **timeline** (started → snapshot → accepted),
  - the **rename-aware diff** and **packet** summary,
  - the **policy decision** (allow, with matched rules),
  - **signatures & trust** (signed, signer identity + type, trusted/untrusted),
  - **verification** and **integrity** (live fsck),
  - **review actions** (Policy check / Verify signatures / fsck), with accept/reject/
    rollback shown as the exact CLI commands.

## 5. See policy stop bad work

Turn on enforcement and watch an unsigned or agent-accepted change get denied — the policy
panel shows the reasons and required actions in plain English.

```bash
cd /tmp/ckpt-work
# (locally) enable policy and try an agent self-accept -> DENY with reasons in the UI panel
```

## Cleanup

```bash
kill %1 2>/dev/null || true   # stop the server
```
