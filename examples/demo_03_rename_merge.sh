#!/usr/bin/env bash
# Rename-aware, line-level merge. No Git.
source "$(dirname "$0")/_demo_lib.sh"
"$CC" init --email j@e.com >/dev/null
printf "l1\nl2\nl3\nl4\nl5\n" > code.txt
"$CC" start base >/dev/null; "$CC" accept --no-verify -m base >/dev/null
step "branch dev: rename file + edit top line"
"$CC" branch dev >/dev/null; "$CC" checkout dev >/dev/null
mv code.txt module.txt; printf "TOP\nl2\nl3\nl4\nl5\n" > module.txt
"$CC" start r >/dev/null; "$CC" accept --no-verify -m "rename+edit top" >/dev/null
step "main: edit bottom line (disjoint)"
"$CC" checkout main >/dev/null
printf "l1\nl2\nl3\nl4\nBOTTOM\n" > code.txt
"$CC" start m >/dev/null; "$CC" accept --no-verify -m "edit bottom" >/dev/null
step "merge dev -> rename detected, disjoint edits auto-merge"
"$CC" merge dev
echo "--- module.txt (merged at new path) ---"; cat module.txt
"$CC" verify-history
echo; echo "OK demo_03"
