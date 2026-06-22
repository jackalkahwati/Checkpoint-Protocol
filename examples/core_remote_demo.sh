#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 6: hardened remote sync.
# "Build remote sync without trusting the remote. Verify everything before refs move."
# Runs in directories that are NOT git repos.
#
#   bash examples/core_remote_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }
run() { "$CC" "$@"; }

step "create an origin store and a working repo with signed history"
mkdir origin
( cd origin && "$CC" init >/dev/null )
mkdir work && cd work
"$CC" init >/dev/null
"$CC" identity create --name "Jack" --type human >/dev/null
printf "v1\n" > app.txt && "$CC" start "c1" >/dev/null && "$CC" accept -m "c1" >/dev/null
printf "v2\n" > app.txt && "$CC" start "c2" >/dev/null && "$CC" accept -m "c2" >/dev/null
"$CC" remote add origin --type filesystem --path ../origin

step "push to origin (sends only missing objects, updates remote ref atomically)"
"$CC" push origin main

step "clone origin into a fresh repo (verifies the whole graph before refs move)"
cd "$WORK"
"$CC" clone origin team-clone
cd team-clone
echo "--- history, signatures, integrity after clone ---"
"$CC" history | head -2
"$CC" verify-signatures | tail -1
"$CC" fsck | tail -1
echo "--- public identity transferred, private key did NOT ---"
ls .checkpoint/identities/ 2>/dev/null | head -1
ls .checkpoint/keys/ 2>/dev/null || echo "(no keys/ — private keys never transfer)"

step "teammate commits and pushes back"
"$CC" identity create --name "Teammate" --type human >/dev/null
"$CC" remote add origin --type filesystem --path ../origin
printf "v3\n" > app.txt && "$CC" start "c3" >/dev/null && "$CC" accept -m "c3" >/dev/null
"$CC" push origin main

step "original repo: sync status, then fetch + pull (fast-forward)"
cd "$WORK/work"
"$CC" sync status origin
echo "--- fetch writes a remote-tracking ref, NOT the local branch ---"
"$CC" fetch origin
echo "--- pull fast-forwards after verification ---"
"$CC" pull origin main
cat app.txt

step "safety: a malicious bundle is rejected before anything is imported"
cd "$WORK"
python3 - <<'PY'
import io, json, tarfile
def add(t,n,d):
    ti=tarfile.TarInfo(n); ti.size=len(d); t.addfile(ti, io.BytesIO(d))
with tarfile.open("evil.tar.gz","w:gz") as t:
    add(t, "../escape.txt", b"path traversal attempt")
    add(t, "keys/leaked.key", b"\x00"*32)
    add(t, "manifest.json", json.dumps({"refs":{}}).encode())
print("built evil.tar.gz")
PY
mkdir victim && cd victim && "$CC" init >/dev/null
echo "--- bundle verify (expect rejection) ---"
"$CC" bundle verify ../evil.tar.gz || echo "[rejected, exit $?]"
echo "--- escape file never written: ---"
ls "$WORK/escape.txt" 2>&1 || echo "(no escape.txt — path traversal blocked)"

step "non-fast-forward push is refused by default"
cd "$WORK/work"
# origin is now ahead via another push path in real life; simulate divergence is covered by tests
echo "(see tests for non-ff rejection and --force-with-lease)"

echo
echo "Demo complete. Nothing was trusted; everything was verified before refs moved."
