# Changelog

All notable changes to Checkpoint. Versions are tagged in Git.

## v1.0.0-preview — Public Developer Preview
- Packaging & metadata (pyproject classifiers, console scripts, optional `crypto`/`dev` extras).
- `checkpoint-core version` / `checkpoint-server version` (CLI/protocol/store versions, features).
- `doctor --json` (core + server); `bug-report` (redacted diagnostics, never keys/tokens).
- `migrate status|plan|apply` scaffolding (store v1, no-op).
- `agent begin|status|packet` helper; `init --safe-git-adapter` guidance.
- Six runnable demos (`examples/demo_0*.sh`, `demo_all.sh`) + `scripts/release_check.sh` + CI.
- Full docs set: quickstart, concepts, cli-reference, server, web-ui, agent-integration,
  security-model, protocol-conformance, git-bridge, faq. README rewritten for the first screen.
- No new core protocol features (by design).

## v0.9-webui
- Web review UI (no-build vanilla-JS SPA served by the API): session review surface,
  rename-aware diff viewer, policy/signature/verification/integrity panels, audit.
- Backend: serve SPA + static assets; `/diff` optional unified text.

## v0.8-hosted
- Hosted HTTP API (stdlib server): repos, refs, objects, sync, bundles, sessions, diff,
  merge-preview, identities, signatures, policy, fsck/gc, audit. API tokens + scopes.
- HTTP remotes in the client (fetch/pull/push/clone/sync status); server receipts.

## v0.7-policy
- Deterministic, opt-in policy engine (actor/path/branch/remote/override rules); enforced
  before accept/merge/push/pull/bundle-import/trust; reasoned signed overrides; `fsck --policy`.

## v0.6-remote
- Hardened remote sync (filesystem + bundles): verify before refs move, remote-tracking
  refs, fast-forward pull, `--force-with-lease`, atomic refs, bundle path/key safety.

## v0.5-trust
- Ed25519 signed identities + local trust; signed accepts/merges; `verify-signatures`,
  `trust-status`; private keys never exported/captured/collected.

## v0.4-integrity
- `fsck` (read-only integrity) and `gc` (safe, quarantined) with a reachability model.

## v0.3-renames
- Native rename detection (exact / similar / rename+edit / directory) in diff & merge.

## v0.2-daemon
- Background autosave daemon, per-session timeline, and recovery.

## v0.1-core
- Native Git-replacement VCS: content-addressed objects, the session as the core object,
  sealed accepted-snapshot history, native diff, branches, file-level merge, sync, git bridge.
