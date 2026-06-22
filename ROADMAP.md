# Roadmap

**Checkpoint is an AI-native VCS where work happens in signed, reviewable *sessions* —**
**with autosave, policy, approvals, inline comments, and merge requests built around**
**AI-generated code.**

Shipped (tagged): v0.1 core · v0.2 autosave/recovery · v0.3 rename-aware merge ·
v0.4 integrity+GC · v0.5 signed identity & trust · v0.6 remote sync · v0.7 policy engine ·
v0.8 hosted API · v0.9 web review UI.

Principle: ship a credible **developer preview** and a credible **self-hosted** product.
Do not build a fake "production cloud." Larger efforts (semantic merge, multi-process/TLS)
are real and kept as their own milestones — not rushed.

---

## v1.0-preview — ship now (public developer preview)

The product has crossed from "protocol prototype" to "usable AI-native VCS preview."

- Install · 5-minute quickstart · runnable demo scripts
- Agent-integration docs · `doctor` / `bug-report` diagnostics · release checklist
- Polished README · honest known-limitations
- Self-hosted local server + web review UI
- **Merge requests with approvals + comments** (the review loop)

## v1.1 — review-workflow polish

Now that MRs exist, tighten the core review loop (more valuable right now than semantic merge):

- MR list page polish · review status badges
- approval-requirements summary · comment-resolution summary
- reviewer checklist · better conflict display
- server-signed merge receipts
- CLI: `checkpoint-core mr create|list|show|approve|comment|merge`

## v1.2 — production self-hosting hardening

Credible self-hosting (this is where multi-process/TLS belongs):

- file-locks or SQLite/Postgres-backed locks
- documented reverse-proxy TLS deployment
- server config profiles: local / dev / self-hosted
- rate limiting · token rotation · signed server receipts
- backup/restore docs · load/concurrency tests

## v1.3 — agent integrations (likely the real adoption wedge)

- Claude Code / Codex / Cursor workflows · generic agent wrapper
- `checkpoint-core agent begin|status|packet` (expand)
- auto-snapshot hooks · agent-generated MR creation

## v1.4 — AI-assisted conflict resolution

The safer step before semantic merge:

- explain the conflict · show ours / theirs / base
- suggest a resolution · never auto-merge without human approval
- store the suggested resolution as a review artifact

## v1.5 — semantic merge *preview* (flagged, one language)

Honest naming — a *preview*, not "solved":

- Python only · AST parse check · function/class move detection
- import-aware preview · human approval required · fallback to line diff3

## v2.0 — hosted multi-tenant service

accounts · orgs · teams · billing · OAuth · real DB · object storage ·
multi-worker API · audit/compliance · enterprise policy distribution.

---

Semantic merge and multi-process/TLS remain real, separate efforts — deliberately **not**
the immediate next step. The immediate order is: ship v1.0-preview → v1.1 review polish →
v1.2 self-hosting → v1.3 agents → v1.4 AI-assisted conflicts → v1.5 semantic-merge preview →
v2.0 hosted product.
