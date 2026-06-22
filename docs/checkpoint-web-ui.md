# Checkpoint Web Review UI

Version: 0.9 (MVP)

> **GitHub reviews commits. Checkpoint reviews work sessions.** This UI shows what GitHub
> cannot: session → prompt → autosaves → snapshots → verification → policy → signatures →
> accept/merge.

## Stack & rationale

A **no-build, dependency-free, vanilla-JS single-page app** (`index.html` + `style.css` +
`app.js`) served directly by `checkpoint-server`. No node/npm, no bundler, no framework.

This is a deliberate, consistent choice: every phase of Checkpoint held to *stdlib-only,
zero-dependency, works-offline, fully-testable*. A React/Vite/TS build would add a Node
toolchain and a build step the project has avoided everywhere (the same reason Phase 8
chose stdlib `http.server` over FastAPI). The SPA talks to the v0.8 HTTP API, uses
**hash-based routing** (so only `/` is served), and is testable from the Python harness.
Swapping in a framework later is straightforward — the API contract is unchanged.

## Running locally

```bash
# 1. start the API + UI
checkpoint-server init-store .checkpoint-server
checkpoint-server token create --store .checkpoint-server --name dev \
    --scopes repo:read,repo:write
checkpoint-server start --port 8800

# 2. open the UI
open http://127.0.0.1:8800/        # paste the token on the login screen
```

The UI is served at `/`; assets at `/app.js` and `/style.css` (no auth). All data comes
from the authenticated v0.8 API.

## Authentication

Token entry on `/login`. The token is stored in browser **localStorage on this device
only** (dev MVP — the UI warns about this) and sent as `Authorization: Bearer <token>`.
**401** clears the token and returns to login; **403** shows a distinct permission error.
Logout clears the stored token. No OAuth, no accounts, no billing.

## Routes (hash-based)

```
#/login
#/repos
#/repos/:owner/:repo
#/repos/:owner/:repo/sessions
#/repos/:owner/:repo/sessions/:sessionId      ← the main product surface
#/repos/:owner/:repo/refs
#/repos/:owner/:repo/policy
#/repos/:owner/:repo/identities
#/repos/:owner/:repo/integrity
#/repos/:owner/:repo/audit
```

## Session review page (the point of the product)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ fix camera exposure defaults                                                │
│ [accepted] [human · Jack] [model · opus-4.8] [trusted ✓] [policy allow]     │
│ cs_20260622_…_fix_camera_exposure                                          │
├───────────────┬───────────────────────────────┬───────────────────────────┤
│ TIMELINE      │ PACKET SUMMARY                │ POLICY DECISION            │
│ ● started     │ recommended: accept           │ ALLOW accept               │
│ ○ autosave    │ files: 2 (+4 −2)              │ matched: [docs] [main]     │
│ ◆ snapshot    │ risks: hardware               │                            │
│ ◍ verification│                               │ SIGNATURES & TRUST         │
│ ● ACCEPTED    │ DIFF (rename-aware)           │ trusted ✓  verified yes    │
│               │ R src/a.py → src/b.py  82%    │ signer id_human_…  human   │
│               │ M config/camera.yaml          │                            │
│               │ <unified hunks, colorized>    │ VERIFICATION               │
│               │                               │ passed ✓   run ver_…       │
│               │ SNAPSHOTS & AUTOSAVES         │                            │
│               │ snapshot  7c3a9f1…            │ INTEGRITY  healthy ✓       │
│               │ autosave  auto_…_001          │                            │
│               │                               │ REVIEW ACTIONS             │
│               │                               │ [Policy check][Verify][fsck]│
│               │                               │ Accept (CLI) …             │
└───────────────┴───────────────────────────────┴───────────────────────────┘
```

Panels:

- **Timeline** — session_started, autosave_created, snapshot_created, verification_run,
  accepted, rollback (color-coded dots). Makes AI work auditable. Autosaves appear here as
  events only; the UI never fetches autosave *content*.
- **Packet** — recommended next action, commit message, file/line stats, risks, secret
  findings.
- **Diff (rename-aware)** — renames shown as `old → new  similarity NN% · kind`, plus
  added/deleted/modified files and a colorized unified hunk view (conflict markers
  highlighted). Directory renames summarized.
- **Snapshots & autosaves** — with the tier glossary (autosave = recovery, snapshot =
  intermediate, accepted snapshot = official history).
- **Policy decision** — allow/deny/warn, matched rules, reasons, required actions, and the
  override CLI when available.
- **Signatures & trust** — signed/unsigned, signer id + type (human/agent/ci/machine/
  service), trusted / untrusted / unknown / revoked, verification status, fingerprint.
- **Verification** — overall pass/fail, run id, count.
- **Integrity** — live fsck result for the repo.
- **Review actions** — working **Policy check / Verify signatures / fsck** buttons.
  Accept/reject/rollback are **client-side** operations (the server only applies verified
  ref updates), so they are shown **disabled with the exact CLI command** to run.

## Other pages

- **Dashboard** (`/repos`) — hosted repos + server id/version.
- **Repo** — branches, recent sessions, integrity summary, policy + signature/trust summary,
  object stats.
- **Refs / Policy / Identities / Integrity / Audit** — direct views of the corresponding
  API data (policy includes the decision audit trail; identities shows trust + fingerprints,
  public keys only).

## Design

Clean, technical, high-trust. No flashy dashboards. Priorities: readable diffs, obvious
policy failures, obvious signature/trust status, obvious next action, strong audit trail.

## Known limitations

- Vanilla JS, no component framework or virtual DOM (fine at this scale; swap later).
- Diff viewer renders the API's unified text; no inline side-by-side editor.
- Accept/reject/rollback are CLI-only (server has no such endpoints by design).
- Token in localStorage is dev-grade; production needs short-lived tokens + TLS.
- No realtime updates (manual refresh); no comments/review threads (out of scope).
