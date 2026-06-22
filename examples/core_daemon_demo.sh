#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 2: the background autosave daemon + timeline + recovery.
# Runs in a directory that is NOT a git repo. "You are never unsaved."
#
#   bash examples/core_daemon_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "init + start a session (no git)"
"$CC" init --name "Jack" --email jack@example.com >/dev/null
printf "draft 0\n" > notes.txt
"$CC" start "write the design notes"

step "run the autosave daemon in the background (fast poll for the demo)"
"$CC" watch --debounce-ms 300 --poll-ms 100 &
WATCH_PID=$!
sleep 0.5

step "edit repeatedly — the daemon debounces and captures quiet points"
for i in 1 2 3; do
  printf "draft %s\nmore content line %s\n" "$i" "$i" > notes.txt
  sleep 0.5   # let the working tree go quiet so an autosave is written
done
sleep 0.5

step "stop the daemon"
kill "$WATCH_PID" 2>/dev/null || true
wait "$WATCH_PID" 2>/dev/null || true

step "autosaves captured automatically"
"$CC" autosave list

step "simulate a crash that loses in-flight work"
printf "GARBAGE — work lost\n" > notes.txt
echo "notes.txt is now:"; cat notes.txt

step "recover: detect the interrupted session"
"$CC" recover

step "recover --restore: bring back the last autosaved state"
"$CC" recover --restore --yes
echo "notes.txt restored to:"; cat notes.txt

step "mark a meaningful snapshot, then accept into sealed history"
"$CC" snapshot -m "design notes drafted" >/dev/null
"$CC" accept --no-verify -m "write design notes"

step "timeline: the full story of the session"
SID="$("$CC" log | awk 'NR==2{print $1}')"
"$CC" timeline "$SID"

step "history stays clean — autosaves never became commits"
"$CC" history
"$CC" verify-history

echo
echo "Demo complete. Git was never involved; nothing was ever unsaved."
