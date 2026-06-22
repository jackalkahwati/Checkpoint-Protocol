#!/usr/bin/env bash
# Continuous autosave + crash recovery. No Git.
source "$(dirname "$0")/_demo_lib.sh"
"$CC" init >/dev/null
printf "draft 0\n" > work.txt
"$CC" start "long task" >/dev/null
step "run the autosave daemon in the background (fast poll)"
"$CC" watch --debounce-ms 300 --poll-ms 100 & WPID=$!
sleep 0.5
step "edit repeatedly; the daemon debounces and autosaves quiet points"
for i in 1 2 3; do printf "draft %s\nmore %s\n" "$i" "$i" > work.txt; sleep 0.5; done
sleep 0.4
kill "$WPID" 2>/dev/null || true; wait "$WPID" 2>/dev/null || true
step "autosaves captured"; "$CC" autosave list
step "simulate a crash that loses in-flight work"; printf "GARBAGE\n" > work.txt
step "recover the latest autosave"; "$CC" recover --restore --yes
echo "recovered work.txt:"; cat work.txt
echo; echo "OK demo_02"
