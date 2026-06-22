# Checkpoint — Web Review UI

A high-trust web frontend for **Checkpoint**, an AI-native Git-replacement version-control system.

> GitHub reviews commits. **Checkpoint reviews work sessions** — the full work episode:
> prompt, edits, autosaves, snapshots, verification, policy decisions, signatures, and accepted history.

The primary object is a **Session**, not a commit. The flagship screen is the three-column
**Session Review** page (`/repos/:owner/:repo/sessions/:sessionId`).

## Core concepts

- **Session** — the full work episode: prompt, edits, autosaves, snapshots, verification, policy, signatures.
- **Accepted Snapshot** — the official history state created from a reviewed session.
- **Snapshot** — a meaningful intermediate state.
- **Autosave** — recovery-only state, *not* accepted history.
- **Policy Decision** — whether an operation is allowed (`allow` / `warn` / `deny`).
- **Signature** — proof of who accepted or signed the work, plus signer trust.

## Pages

| Route | Purpose |
| --- | --- |
| `/login` | API-token login (stores token + base URL in `localStorage`). |
| `/repos` | Repos dashboard with health badges and an attention/alert strip. |
| `/repos/:owner/:repo` | Repo overview with tabs: Sessions, Branches, Policy, Identities, Integrity, Audit. |
| `/repos/:owner/:repo/sessions/:sessionId` | **Session Review** — timeline, packet, diff viewer, and stacked review panels. |
| `/repos/:owner/:repo/policy` | Policy config and decisions. |
| `/repos/:owner/:repo/identities` | Trusted / untrusted / revoked identities. |
| `/repos/:owner/:repo/integrity` | fsck status, object stats, GC summary. |
| `/repos/:owner/:repo/audit` | Audit log. |

## API client & mock mode

All data flows through `lib/checkpoint/api-client.ts`, which talks to the Checkpoint
Hosted API (default `http://localhost:8080`) using a Bearer token.

- `401` → clears the session and redirects to `/login`
- `403` / `404` / `5xx` → surfaced as readable error states
- **Network/timeout/CORS** → falls back to realistic **mock data**, with a visible
  **"Mock data"** badge so it is never mistaken for live data.

This means the UI is fully demoable with no backend running.

## How to run (against the real Checkpoint server)

This frontend talks to the Checkpoint server's **`/ui/*` adapter** — a backend-for-frontend
that returns exactly these TypeScript types. CORS is enabled on the server, so the Next dev
server (:3000) can call the API (:8800) directly.

1. **Start the Checkpoint server** (API + `/ui/*` adapter + CORS):
   ```bash
   checkpoint-server init-store .checkpoint-server
   checkpoint-server token create --store .checkpoint-server --name dev \
       --scopes repo:read,repo:write,admin
   checkpoint-server start --port 8800
   ```
   Then create a repo and push a session — see `examples/web_review_demo.md` in the repo root.
2. **Start the frontend dev server**:
   ```bash
   pnpm install
   pnpm dev                         # http://localhost:3000
   ```
3. **Log in**: open `/login`, keep the default API base URL `http://localhost:8800`
   (or point it at your server), and enter your **API token** (stored in `localStorage`).
   > Local MVP token storage — do not use production credentials.
4. **Review a session**: **Repos → owner/repo → a session** opens the Session Review page.
   If the API is unreachable, the app falls back to **mock mode** (shown with a badge) so you
   can still explore the full experience with no backend.

> **Two UIs ship with Checkpoint.** This Next.js app is the rich review UI. The server also
> serves a zero-build, dependency-free vanilla-JS UI at `http://localhost:8800/` for
> offline / no-Node environments. Both consume the same hosted API.

**API wiring:** all calls go through `lib/checkpoint/api-client.ts`, which targets
`${baseUrl}/ui${path}` (`UI_PREFIX`). The adapter returns frontend types directly, so the
client is a thin pass-through with a mock fallback on network/CORS error.

## Design

Dark, high-contrast, monospace for hashes/diffs/object IDs, and heavy use of state badges:

- **Green** — healthy / allowed / passed
- **Yellow** — warning / untrusted
- **Red** — denied / failed / corrupt
- **Blue/purple** — AI / session metadata

Hashes are truncated but copyable, diff files are collapsible, timeline items are clickable,
and denied policy decisions always show **Required actions** in plain English.

## Notes / scope

- No browser-based code editing, comments, billing, teams, or OAuth.
- Private keys are never requested or rendered.
