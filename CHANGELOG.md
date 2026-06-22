# Changelog

All notable changes to Checkpoint. Versions are tagged in Git.

## v1.0-preview — Public Developer Preview (review loop)
- **Merge requests**: open from a reviewed session → diff + mergeability → review thread →
  approvals → server-signed, conflict-aware, atomic merge. Inline per-line diff comments;
  approvals gated by policy `min_approvals` (now enforced on merge, not just accept).
- Web: "Merge requests" tab + MR detail page; repos **list view** toggle; Identities
  **Trust/Untrust/Revoke** wired; fast dashboard (light integrity on list).
- CLI/ops: `checkpoint-core setup` one-shot repo setup; secret-scan allowlist
  (`.checkpoint/secrets-allow`); autosave watcher auto-runs during a session; `push` returns
  a real exit code; `remote list` shows HTTP URLs; symlink-safe launchers.
- Server: `/ui/*` backend-for-frontend adapter + CORS for the Next.js frontend; hosted push
  judged by the snapshot's signer; fsck no longer warns on JSON blobs.
- Docs: `docs/reviews.md`; updated ROADMAP (v1.0→v2.0 ordered).

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
