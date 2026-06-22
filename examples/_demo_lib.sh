# shared helpers for Checkpoint demos (sourced by demo_*.sh)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="$ROOT/bin/checkpoint-core"
CS="$ROOT/bin/checkpoint-server"
export NO_COLOR="${NO_COLOR:-1}"
DEMO_DIR="$(mktemp -d)"
cd "$DEMO_DIR"
_cleanup(){ if [ "${KEEP_DEMO:-0}" = "1" ]; then echo; echo "kept: $DEMO_DIR"; else rm -rf "$DEMO_DIR"; fi; }
trap _cleanup EXIT
step(){ echo; echo "### $*"; }
