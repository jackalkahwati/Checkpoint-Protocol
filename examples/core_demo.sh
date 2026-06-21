#!/usr/bin/env bash
# Runnable demo of Checkpoint CORE (the Git-replacement protocol).
# Runs an entire VCS lifecycle in a directory that is NOT a git repo.
#
#   bash examples/core_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "this directory is NOT a git repo"
( git rev-parse --is-inside-work-tree 2>&1 || true )

step "checkpoint-core init (no git needed)"
"$CC" init --name "Jack" --email jack@example.com

step "start a session and create files"
printf "exposure: auto\nfps: 30\n" > camera.yaml
printf "def drive():\n    return 'ok'\n" > autonomy.py
"$CC" start "scaffold camera config and autonomy stub" --tag hardware

step "snapshot, diff, accept"
printf "exposure: 1/500\nfps: 30\n" > camera.yaml
"$CC" snapshot -m "tune exposure"
"$CC" diff --summary
"$CC" accept --no-verify -m "scaffold camera + autonomy"

step "native history (no git anywhere)"
"$CC" history
"$CC" verify-history

step "branch, edit, merge — all native"
"$CC" branch experiment
"$CC" checkout experiment
printf "experiment\n" > notes.txt
"$CC" start "experiment notes"
"$CC" accept --no-verify -m "add notes"
"$CC" checkout main
"$CC" merge experiment

step "optional: mirror to Git via the bridge"
if command -v git >/dev/null 2>&1; then
  "$CC" git-export "$WORK/git-mirror"
  echo "--- git log of the mirror ---"
  git -C "$WORK/git-mirror" log --oneline
else
  echo "(git not installed — core still worked fine; the bridge is optional)"
fi

echo
echo "Demo complete. Checkpoint Core is the source of truth; Git was optional."
