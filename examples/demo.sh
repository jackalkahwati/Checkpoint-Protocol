#!/usr/bin/env bash
# Runnable end-to-end demo of the Checkpoint Protocol.
# Creates a throwaway Git repo in a temp dir and exercises the full lifecycle.
#
#   bash examples/demo.sh
#
set -euo pipefail

# Resolve the `checkpoint` launcher shipped in this repo.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKPOINT="$ROOT/bin/checkpoint"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "create a git repo"
git init -q
git config user.email demo@example.com
git config user.name demo
printf "exposure: auto\nfps: 30\n" > camera.yaml
printf "def drive():\n    return 'ok'\n" > autonomy.py
git add -A && git commit -qm "initial"

step "checkpoint init"
"$CHECKPOINT" init --yes

step "configure a verification command"
python3 - <<'PY'
import yaml
p = ".checkpoint/config.yaml"
d = yaml.safe_load(open(p))
d["verification"]["commands"] = [
    {"name": "syntax", "run": "python3 -m py_compile autonomy.py"},
]
yaml.safe_dump(d, open(p, "w"), sort_keys=False)
PY

step "start a session"
"$CHECKPOINT" start "fix camera exposure defaults without changing autonomy behavior" --tag hardware

step "edit files"
printf "exposure: 1/500\nfps: 30\n" > camera.yaml

step "snapshot"
"$CHECKPOINT" snapshot --message "camera config updated"

step "diff --summary"
"$CHECKPOINT" diff --summary

step "verify"
"$CHECKPOINT" verify

step "packet"
"$CHECKPOINT" packet

step "accept"
"$CHECKPOINT" accept --message "fix camera exposure defaults"

step "git history (one clean commit; .checkpoint not included)"
git log --oneline
if git ls-files | grep -q '^\.checkpoint/'; then echo "LEAK"; else echo "(.checkpoint correctly absent from git)"; fi

step "session log"
"$CHECKPOINT" log

echo
echo "Demo complete."
