#!/usr/bin/env bash
# Demo of Checkpoint Core Phase 5: signed identity & trust (Ed25519).
# Proves WHO created and approved each change, and that history wasn't modified.
# Runs in a directory that is NOT a git repo.
#
#   bash examples/core_identity_demo.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
export NO_COLOR="${NO_COLOR:-1}"

WORK="$(mktemp -d)"
trap 'echo; echo "demo repo left at: $WORK"' EXIT
cd "$WORK"

step() { echo; echo "=== $* ==="; }

step "init + create an Ed25519 signing identity"
"$CC" init >/dev/null
"$CC" identity create --name "Jack (human)" --type human --email jack@example.com
"$CC" identity list

step "accept is signed by the active identity automatically"
printf "exposure: auto\n" > camera.yaml
"$CC" start "fix camera exposure" >/dev/null
printf "exposure: 1/500\n" > camera.yaml
"$CC" accept -m "fix camera exposure" | sed -n '1,7p'

step "verify every signature in the store"
"$CC" verify-signatures

step "trust-status: who signed what"
"$CC" trust-status

step "tamper with sealed history -> signature verification catches it"
python3 - "$WORK" <<'PY'
import sys
sys.path.insert(0, "/Users/jackal-kahwati/Checkpoint Protocol")
from checkpoint_core.store import Repo
from checkpoint_core import util
r = Repo(sys.argv[1])
oid = r.head_snapshot()
snap = r.get_object(oid)
snap["message"] = "forged message"
(r.paths.objects / oid[:2] / oid).write_bytes(util.canonical(snap))
print("rewrote accepted snapshot message:", oid[:12])
PY
echo "--- verify-signatures (expect FAIL) ---"
"$CC" verify-signatures || echo "[verify-signatures exit $?]"

step "restore the demo and show trust policy: an AGENT cannot self-accept"
# fresh repo to show policy
W2="$(mktemp -d)"; cd "$W2"
"$CC" init >/dev/null
"$CC" identity create --name "build-bot" --type agent >/dev/null
printf "x\n" > a.txt
"$CC" start "agent change" >/dev/null
echo "--- agent accept (expect policy rejection) ---"
"$CC" accept --no-verify || echo "[accept blocked by trust policy, exit $?]"

step "export a bundle: public identities travel, private keys never do"
cd "$WORK"
"$CC" bundle export main --out bundle.tar.gz >/dev/null
echo "bundle contents (note: identities/ present, keys/ absent):"
tar tzf bundle.tar.gz | grep -E 'identities/|keys/|signatures/' || true

echo
echo "Demo complete. Authorship is provable; tampering is detectable; keys never leak."
