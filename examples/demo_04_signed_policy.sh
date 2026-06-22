#!/usr/bin/env bash
# Signed identity + policy: human accept allowed, agent self-accept denied. No Git.
source "$(dirname "$0")/_demo_lib.sh"
"$CC" init >/dev/null; "$CC" policy init >/dev/null
step "human accepts docs (signed) -> ALLOW"
"$CC" identity create --name Jack --type human >/dev/null
mkdir docs; printf "# hi\n" > docs/readme.md
"$CC" start "docs" >/dev/null
"$CC" accept -m "docs" | grep -E "Accepted|signed" | head -2
"$CC" reject --yes >/dev/null 2>&1 || true
step "an AI agent tries to self-accept code -> DENY"
B=$("$CC" identity create --name bot --type agent | awk '/Created identity/{print $3}')
"$CC" identity use "$B" >/dev/null
mkdir -p src; printf "x\n" > src/app.py
"$CC" start "agent change" >/dev/null
"$CC" accept --no-verify || echo "[denied by policy, as expected]"
step "audit trail of policy decisions"; "$CC" policy audit | tail -3
echo; echo "OK demo_04"
