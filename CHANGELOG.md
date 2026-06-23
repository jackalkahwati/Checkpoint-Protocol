# Changelog

All notable changes to Checkpoint. Versions are tagged in Git.

## v1.2.1 — Owner Agent Autopilot completion
- `autopilot review mr_N [--decision approve|merge]`: Owner Agent reviews a merge request and
  acts only when its decision AND server policy permit (protected/policy-deny → escalate, no
  action).
- `autopilot explain [id]`: explain a past decision (reads the persisted, signed review).
- Reviews are now **persisted** (`.checkpoint/owner_reviews/<id>.json`, loadable by review or
  target id) with `ledger_event_id` and `policy_decision_id`.
- `checkpoint_core/identity/**` added to default protected paths.
- `next --json` exposes `autopilot_enabled`, `owner_agent_configured`, `last_owner_agent_review`,
  `autopilot_recommended`, `autopilot_safe_to_run`, `suggested_autopilot_command` so
  `/checkpoint` routes into autopilot.

## v1.2 — Personal Autopilot (AI-owned loop)
- `checkpoint-core claude "<task>" --autopilot` (and `autopilot claude`): Builder writes →
  **Owner Agent** reviews → auto-accept low-risk work or **escalate** with a clear reason →
  fsck + verify-signatures + backup + push after acceptance → one final screen. `--decision
  auto|escalate|rollback-on-fail`, `--json`.
- **Owner Agent** (`owneragent.py`): deterministic, policy-bounded reviewer; separate identity
  from the Builder (no self-approval); never overrides/loosens policy; never trusts identities;
  reviews are ledgered + signed. Conservative default: only docs/tests/examples/markdown
  auto-accept.
- `checkpoint-core personal init|status|daily` and `backup init|run|status|restore`
  (filesystem backup; never transfers private keys; verified; preview-before-restore).
- Policy engine: `min_approvals` now enforced on merge too.
- Docs: personal-autopilot, owner-agent, backup, daily-workflow.
- Deferred (honest): web dashboard panels for Owner Agent reviews; semantic merge;
  multi-process/TLS; hosted accounts.

## v1.1 — Merge-request CLI
- `checkpoint-core mr create|list|show|diff|comment|approve|unapprove|merge|close|status|review`
  — scriptable, agent-usable review surface over the hosted `/ui` API; `mr review` one-screen.

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
