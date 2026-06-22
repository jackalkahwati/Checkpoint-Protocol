# Quickstart (5 minutes)

Checkpoint needs **no Git** and no external services.

## Install

```bash
git clone https://github.com/jackalkahwati/Checkpoint-Protocol
cd Checkpoint-Protocol
pip install -e .            # provides checkpoint-core / checkpoint-server / checkpoint
# or, no install:  export PATH="$PWD/bin:$PATH"

checkpoint-core --help
checkpoint-core version
```

## Your first session

```bash
mkdir myproject && cd myproject
checkpoint-core init
checkpoint-core identity create --name "Jack" --type human
# (the new identity is auto-selected; otherwise: checkpoint-core identity use <id>)

checkpoint-core start "make a small change"
echo "hello world" > notes.txt
checkpoint-core snapshot -m "first checkpoint"
checkpoint-core verify
checkpoint-core accept -m "accept first session"

checkpoint-core history
checkpoint-core fsck --verify-signatures
```

You just recorded a full **work session** (instruction → snapshot → verification →
signed accept) and promoted it into clean, sealed history — without Git.

## Host it and review in the browser

```bash
checkpoint-server init-store .checkpoint-server
checkpoint-server token create --store .checkpoint-server --name local-dev \
    --repo jack/demo --scopes repo:read,repo:write,admin
checkpoint-server start --port 8800
```

Create the repo, push, and open the UI:

```bash
# create repo jack/demo (one-time)
python3 - <<'PY'
import json,urllib.request
TOKEN="PASTE_TOKEN"
r=urllib.request.Request("http://127.0.0.1:8800/repos",
  data=json.dumps({"owner":"jack","repo":"demo"}).encode(),
  headers={"Content-Type":"application/json","Authorization":"Bearer "+TOKEN},method="POST")
print(urllib.request.urlopen(r).status)
PY

checkpoint-core remote add origin http://127.0.0.1:8800/jack/demo --token PASTE_TOKEN
checkpoint-core push origin main
```

Open **http://127.0.0.1:8800/**, paste the token, and open your session to see the timeline,
diff, policy, and signatures in one place.

## Try every feature in one command

```bash
bash examples/demo_all.sh      # core, autosave+recovery, rename-merge, signed policy, remote, hosted+UI
```

Next: [concepts.md](concepts.md) · [cli-reference.md](cli-reference.md) ·
[agent-integration.md](agent-integration.md) · [faq.md](faq.md)
