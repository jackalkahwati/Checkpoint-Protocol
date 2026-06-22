#!/usr/bin/env bash
# Filesystem remote: push / fetch / pull / clone, verified. No Git.
source "$(dirname "$0")/_demo_lib.sh"
mkdir origin; ( cd origin && "$CC" init >/dev/null )
mkdir work; cd work; "$CC" init >/dev/null
"$CC" identity create --name Jack --type human >/dev/null
printf "v1\n" > f.txt; "$CC" start c1 >/dev/null; "$CC" accept -m c1 >/dev/null
"$CC" remote add origin --type filesystem --path ../origin
step "push to the filesystem remote"; "$CC" push origin main
step "clone the remote into a fresh repo (verified)"
cd "$DEMO_DIR"; "$CC" clone origin clone >/dev/null; ( cd clone && "$CC" history | head -2 && "$CC" verify-signatures | tail -1 )
step "advance origin via the clone, then pull into work"
cd "$DEMO_DIR/clone"; printf "v2\n" > f.txt; "$CC" start c2 >/dev/null; "$CC" accept -m c2 >/dev/null
"$CC" remote add origin --type filesystem --path ../origin; "$CC" push origin main >/dev/null
cd "$DEMO_DIR/work"; "$CC" pull origin main; cat f.txt
echo; echo "OK demo_05"
