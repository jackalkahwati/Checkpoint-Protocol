#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 3: native rename detection.
# AI refactors move files constantly. Checkpoint reviews them as clean logical change,
# not delete + add. Runs in a directory that is NOT a git repo.
#
#   bash examples/core_rename_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "init + an initial module layout"
"$CC" init --name "Jack" --email jack@example.com >/dev/null
mkdir -p lib
printf 'def parse(text):\n    tokens = []\n    for line in text.splitlines():\n        tokens.append(line.strip())\n    return tokens\n' > lib/parser.py
printf 'def fmt(rows):\n    out = []\n    for r in rows:\n        out.append(str(r))\n    return "\\n".join(out)\n' > lib/format.py
printf 'def util():\n    return 3\n' > lib/util.py
"$CC" start "initial layout" >/dev/null
"$CC" accept --no-verify -m "initial layout" >/dev/null

step "an AI refactor: rename a file, edit another, move the whole package"
"$CC" start "refactor: reorganize into core/ and rename parser" >/dev/null
mkdir -p core
mv lib/parser.py core/tokenizer.py                 # pure rename + move
# edit format.py (one line in a 5-line file -> stays well above the 60% threshold)
printf 'def fmt(rows):\n    out = []\n    for r in rows:\n        out.append(repr(r))\n    return "\\n".join(out)\n' > lib/format.py
mv lib/format.py core/format.py                     # ...then move it
mv lib/util.py core/util.py                          # plain move
rmdir lib

step "diff — reviewed as renames, not delete + add"
"$CC" diff --summary

step "the change packet carries structured rename records"
"$CC" packet | sed -n '1,30p'

step "accept into sealed history"
"$CC" accept --no-verify -m "reorganize into core/, rename parser->tokenizer" >/dev/null
"$CC" verify-history

step "rename-aware merge: two branches edit disjoint regions of the moved file"
"$CC" branch hotfix >/dev/null
"$CC" checkout hotfix >/dev/null
# hotfix edits the FIRST line of the moved file
printf 'def parse(text):  # hotfix: handle None\n    tokens = []\n    for line in text.splitlines():\n        tokens.append(line.strip())\n    return tokens\n' > core/tokenizer.py
"$CC" start "hotfix tokenizer" >/dev/null
"$CC" accept --no-verify -m "hotfix tokenizer" >/dev/null
"$CC" checkout main >/dev/null
# main edits the LAST line (disjoint region) of the same moved file
printf 'def parse(text):\n    tokens = []\n    for line in text.splitlines():\n        tokens.append(line.strip())\n    return [t for t in tokens if t]\n' > core/tokenizer.py
"$CC" start "drop blank tokens" >/dev/null
"$CC" accept --no-verify -m "drop blank tokens" >/dev/null
echo "--- merge hotfix (line-level + rename aware) ---"
"$CC" merge hotfix
echo "--- core/tokenizer.py auto-merged content ---"
cat core/tokenizer.py
"$CC" verify-history

echo
echo "Demo complete. Moves and renames stayed legible; Git was never involved."
