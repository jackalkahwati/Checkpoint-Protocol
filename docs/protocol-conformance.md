# Protocol Conformance

The normative conformance checklist is **[checkpoint-core-protocol.md](checkpoint-core-protocol.md) §18**.

An implementation conforms to Checkpoint Core 1.0 if it: stores content-addressed
blob/tree/snapshot objects; represents history as a parent-chain of sealed `accepted`
snapshots referenced by `refs/heads/*`, each linking to its producing session; runs the
session/accept/reject/rollback flows, native diff, and (≥ file-level) merge **without Git**;
stamps an author identity and SHA-256 seal; supports content-addressed sync; provides Git
import/export as an isolated bridge; detects renames; verifies integrity (fsck) and collects
garbage safely; supports Ed25519 signing + trust; performs hardened remote sync; enforces an
opt-in policy engine; and **passes the test: with Git uninstalled, all of the above works.**

Verify locally:

    bash scripts/release_check.sh          # full suite + demos + no-Git subset
    python -m pytest -q
