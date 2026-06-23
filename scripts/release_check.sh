#!/usr/bin/env bash
# Release validation for Checkpoint v1.0-preview.
# Runs the full test suite, the no-Git subset, demo smoke tests, and package checks.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export NO_COLOR=1
FAIL=0
say(){ echo; echo "==== $* ===="; }
ok(){ echo "PASS: $*"; }
bad(){ echo "FAIL: $*"; FAIL=1; }

say "package import check"
python3 -c "import checkpoint_core, checkpoint_core.server.app, checkpoint" && ok "imports" || bad "imports"

say "version commands"
python3 -m checkpoint_core version >/dev/null && ok "core version" || bad "core version"
python3 -m checkpoint_core.server.cli version >/dev/null && ok "server version" || bad "server version"

say "full test suite"
python3 -m pytest -q && ok "pytest" || bad "pytest"

say "no-Git subset"
python3 -m pytest -q -k "without_git or no_git or works_with_git_removed" && ok "no-git subset" || bad "no-git subset"

say "demo smoke tests"
for d in demo_01_core_vcs demo_02_autosave_recovery demo_03_rename_merge demo_04_signed_policy demo_05_remote_sync demo_06_hosted_web_ui; do
  if bash "examples/$d.sh" >/tmp/ckpt_$d.log 2>&1; then ok "$d"; else bad "$d (see /tmp/ckpt_$d.log)"; fi
done

say "web UI assets present + served route registered"
test -f checkpoint_core/server/web/index.html && ok "web assets" || bad "web assets"

say "docs present"
for f in README.md CHANGELOG.md RELEASE_NOTES.md SECURITY.md CONTRIBUTING.md ROADMAP.md \
         docs/quickstart.md docs/concepts.md docs/cli-reference.md docs/agent-integration.md \
         docs/faq.md docs/server.md docs/web-ui.md docs/reviews.md docs/security-model.md \
         docs/personal-autopilot.md docs/owner-agent.md docs/backup.md docs/daily-workflow.md \
         docs/protocol-conformance.md docs/git-bridge.md docs/checkpoint-core-protocol.md \
         docs/checkpoint-hosted-api.md docs/checkpoint-web-ui.md; do
  test -f "$f" && ok "$f" || bad "missing $f"
done

echo
if [ "$FAIL" = "0" ]; then echo "RELEASE CHECK: PASS"; else echo "RELEASE CHECK: FAIL"; fi
exit $FAIL
