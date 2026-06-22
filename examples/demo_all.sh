#!/usr/bin/env bash
# Run all safe demos in sequence. Set KEEP_DEMO=1 to keep temp dirs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
for d in demo_01_core_vcs demo_02_autosave_recovery demo_03_rename_merge demo_04_signed_policy demo_05_remote_sync demo_06_hosted_web_ui; do
  echo; echo "============================================================"
  echo "== $d"; echo "============================================================"
  bash "$HERE/$d.sh"
done
echo; echo "ALL DEMOS PASSED"
