#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 7: the policy engine.
# "Build policy before UI. Checkpoint should enforce allowed change, not just display it."
# Runs in a directory that is NOT a git repo.
#
#   bash examples/core_policy_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "init + turn on the policy engine (starter policy)"
"$CC" init >/dev/null
"$CC" policy init
"$CC" policy validate

step "an AI agent tries to self-accept a code change -> DENIED"
"$CC" identity create --name "build-bot" --type agent >/dev/null
mkdir -p src && printf "x\n" > src/app.py
"$CC" start "agent change" >/dev/null
"$CC" accept --no-verify || echo "[denied, exit $?]"
"$CC" reject --yes >/dev/null 2>&1 || true   # close the denied session

step "a human can accept docs with no verification -> ALLOWED"
HID="$("$CC" identity create --name "Jack" --type human | awk '/Created identity/{print $3}')"
"$CC" identity use "$HID" >/dev/null
mkdir -p docs && printf "# notes\n" > docs/readme.md
"$CC" start "write docs" >/dev/null
"$CC" policy check --operation accept
"$CC" accept -m "docs" | grep -E "ALLOW|Accepted|signed" | head -2

step "a safety-critical path needs a named verification (safety_tests) -> DENIED"
mkdir -p src/safety && printf "controller\n" > src/safety/controller.rs
"$CC" start "edit safety controller" >/dev/null
"$CC" accept || echo "[denied, exit $?]"
# keep the SAME session; just supply verification next

step "provide the required verification, then accept -> ALLOWED"
python3 - <<'PY'
import yaml, glob
p = glob.glob(".checkpoint/config.yaml")[0]
d = yaml.safe_load(open(p))
d["verification"]["commands"] = [{"name": n, "run": "exit 0"} for n in ("tests", "lint", "safety_tests")]
yaml.safe_dump(d, open(p, "w"), sort_keys=False)
PY
"$CC" verify >/dev/null
"$CC" accept -m "safety fix" | grep -E "Accepted|signed" | head -2

step "an emergency override by a trusted human (reason required, audited)"
printf "controller v2\n" > src/safety/controller.rs
# remove the required verification to force a denial we then override
python3 - <<'PY'
import yaml, glob
p = glob.glob(".checkpoint/config.yaml")[0]
d = yaml.safe_load(open(p))
d["verification"]["commands"] = [{"name": "tests", "run": "exit 0"}]   # safety_tests gone
yaml.safe_dump(d, open(p, "w"), sort_keys=False)
PY
"$CC" start "emergency safety patch" >/dev/null
echo "--- without override (denied) ---"
"$CC" accept --no-verify || echo "[denied, exit $?]"
echo "--- with a reasoned override (allowed + recorded) ---"
"$CC" accept --no-verify --override --reason "sev-1 hotfix, approved by safety lead" | grep -E "Accepted" | head -1

step "audit: every policy decision is in the ledger"
"$CC" policy audit | tail -6

echo
echo "Demo complete. Checkpoint enforced who could change what, and recorded every decision."
