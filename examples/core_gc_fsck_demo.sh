#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 4: integrity checking (fsck) + safe garbage collection.
# Runs in a directory that is NOT a git repo.
#
#   bash examples/core_gc_fsck_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "build a little history"
"$CC" init --name "Jack" --email jack@example.com >/dev/null
printf "v1\n" > a.txt
"$CC" start "c1" >/dev/null && "$CC" accept --no-verify -m "c1" >/dev/null
printf "v2\n" > a.txt
"$CC" start "c2" >/dev/null && "$CC" accept --no-verify -m "c2" >/dev/null

step "objects stats — what is in the store"
"$CC" objects stats

step "fsck — is the store healthy?"
"$CC" fsck

step "create some garbage: an unreachable, aged object"
python3 - "$WORK" <<'PY'
import sys, os, time
sys.path.insert(0, "/Users/jackal-kahwati/Checkpoint Protocol")
from checkpoint_core.store import Repo
r = Repo(sys.argv[1])
oid = r.put_blob(b"left-over scratch object\n")
p = r.paths.objects / oid[:2] / oid
old = time.time() - 30 * 86400          # 30 days old
os.utime(p, (old, old))
print("planted unreachable object:", oid[:12])
PY

step "objects list --unreachable — find the garbage"
"$CC" objects list --unreachable

step "gc --dry-run — show what WOULD be collected (nothing deleted)"
"$CC" gc --dry-run

step "gc — collect it (runs fsck first, quarantines for crash-safety)"
"$CC" gc

step "history is untouched; seals still valid"
"$CC" history
"$CC" verify-history

step "now corrupt an object and watch fsck catch it (and gc refuse)"
python3 - "$WORK" <<'PY'
import sys
sys.path.insert(0, "/Users/jackal-kahwati/Checkpoint Protocol")
from checkpoint_core.store import Repo
import checkpoint_core.reachable as R
r = Repo(sys.argv[1])
for oid in R.iter_object_ids(r):
    if R.classify(r, oid)[0] == "blob":
        (r.paths.objects / oid[:2] / oid).write_bytes(b"TAMPERED\n")
        print("rewrote blob:", oid[:12]); break
PY
echo "--- fsck (expect: corrupt) ---"
"$CC" fsck || echo "[fsck exit $?]"
echo "--- gc refuses to run on a corrupt store ---"
"$CC" gc || echo "[gc exit $?]"

echo
echo "Demo complete. Integrity verified, garbage reclaimed, history never at risk."
