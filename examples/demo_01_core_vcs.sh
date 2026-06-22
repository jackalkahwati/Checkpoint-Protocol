#!/usr/bin/env bash
# Core VCS: init -> start -> snapshot -> accept -> history. No Git.
source "$(dirname "$0")/_demo_lib.sh"
step "init (no Git anywhere)"; "$CC" init
step "create + select a human identity"
"$CC" identity create --name "Jack" --type human
step "start a session"; "$CC" start "make a small change"
step "edit a file"; printf "hello\nworld\n" > notes.txt
step "snapshot a meaningful state"; "$CC" snapshot -m "first checkpoint"
step "verify (no commands configured -> skipped)"; "$CC" verify
step "accept into sealed history"; "$CC" accept -m "accept first session"
step "history (native, no Git)"; "$CC" history
step "fsck with signature verification"; "$CC" fsck --verify-signatures
echo; echo "OK demo_01"
