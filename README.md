# Checkpoint

**AI-native version control for human and AI software teams.**

> **Git stores commits. Checkpoint records the full work session** — the prompt, the
> autosaves, the snapshots, the verification, the policy, and the signatures — and promotes
> only reviewed, signed, policy-approved work into clean history.

![status: v1.0-preview](https://img.shields.io/badge/status-v1.0--preview-blue)
![python: 3.8+](https://img.shields.io/badge/python-3.8%2B-3776ab)
![no git required](https://img.shields.io/badge/core-no%20Git%20required-success)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

```bash
pip install -e .          # checkpoint-core · checkpoint-server · checkpoint
checkpoint-core init
checkpoint-core identity create --name "You" --type human
checkpoint-core start "make a change"   # … edit …
checkpoint-core snapshot -m "wip"  &&  checkpoint-core verify  &&  checkpoint-core accept -m "done"
checkpoint-core history
bash examples/demo_all.sh               # see everything in 6 demos
```

**5-minute quickstart → [`docs/quickstart.md`](docs/quickstart.md).** Concepts →
[`docs/concepts.md`](docs/concepts.md). FAQ → [`docs/faq.md`](docs/faq.md).

The vocabulary (full glossary in [`docs/concepts.md`](docs/concepts.md)):

- **Session** — the whole work episode (instruction, actor/agent, autosaves, snapshots,
  verification, policy, signatures).
- **Autosave** — continuous, recovery-only state. *You are never unsaved.*
- **Snapshot** — a marked meaningful intermediate state.
- **Accepted Snapshot** — official, sealed, signed history (the commit equivalent).
- **Policy Decision** — whether an operation is allowed (deterministic, audited).
- **Signature** — Ed25519 proof of *who approved this*. **Remote** — another store you sync
  with. **Hosted Server** — HTTP API + **Web Review UI** for reviewing sessions.

> **The simple test:** *If Git disappeared, would Checkpoint still work?* **Yes** — the core
> is its own content-addressed store; the entire VCS is tested in directories that are not
> Git repos. The `checkpoint` Git **adapter** is an adoption wedge, not the foundation.

---

## Two layers in this repo

This repository contains **two** things. Don't confuse them.

| | What it is | Source of truth | Use it when |
|---|---|---|---|
| **`checkpoint-core`** | The real protocol: a Git-replacement VCS with native objects. | **Checkpoint** | You want the AI-native VCS. New projects, or projects you import from Git. |
| **`checkpoint`** | The **Git adapter** — a thin control layer on top of an existing Git repo. A wedge for adoption. | **Git** | You have an existing Git repo and want session/verify/accept ergonomics without migrating. |

If you only read one spec, read [`docs/checkpoint-core-protocol.md`](docs/checkpoint-core-protocol.md).
The adapter is documented in [`docs/checkpoint-protocol.md`](docs/checkpoint-protocol.md).

```
Checkpoint Core Protocol      <- source of truth (native objects)
        |
   checkpoint-core CLI
        |
   Checkpoint Service (future)

Optional bridges:  git-import / git-export    sync / bundles    editor & agent integrations
```

---

## Why a new protocol (and not just Git)

AI agents change a lot of code, fast. Between two commits an agent runs a whole *work
session*: a prompt, a plan, edits, tests, retries, partial failures, fixes, verification,
then a human accept or reject. Git can only see the before and after — the prompt, the
intermediate states, and the verification status are all lost.

**In Git, the core object is the commit. In Checkpoint, the core object is the session.**
History is a chain of *accepted snapshots*, and every accepted snapshot points back to the
full session that produced it. Walk the history and, at each step, recover the
instruction, the agent/model, the intermediate snapshots, and the verification record.

Checkpoint answers, for any unit of work:

1. What did the human or AI try to do, and what prompt caused it?
2. What files changed, and what changed between each meaningful state?
3. What checks passed or failed? What was the last known-good state?
4. What was accepted into history? What was rejected or rolled back?
5. Can the session be replayed, audited, exported, or recovered?

---

## Core philosophy

- The human never loses work, and never loses control.
- History stays clean: only accepted, human-approved work becomes permanent.
- AI work is fully traceable: prompt → edits → verification → accept, all native.
- Every meaningful change is recoverable. Rejected work stays auditable without polluting
  history.
- **Checkpoint is the foundation. Git compatibility is a feature, not the foundation.**

---

## Install

Requires Python 3.8+. The **core needs no Git**; only the Git bridge does.

```bash
# Run from the repo without installing:
export PATH="$PWD/bin:$PATH"
checkpoint-core --version

# Or install (provides both entry points):
pip install -e .
```

Or call the modules directly: `python -m checkpoint_core <command>` /
`python -m checkpoint <command>`.

---

## Quick start (Checkpoint Core — the real thing)

```bash
mkdir my-project && cd my-project          # NOT a git repo — that's the point

checkpoint-core init --name "You" --email you@example.com
checkpoint-core start "scaffold the API and add health check"

# ... you or an AI agent create/edit files ...

checkpoint-core snapshot -m "first pass"
checkpoint-core diff
checkpoint-core verify
checkpoint-core packet
checkpoint-core accept -m "scaffold API"

checkpoint-core history          # native history — no Git anywhere
checkpoint-core verify-history   # recompute the SHA-256 seals on accepted snapshots
```

Branch, merge, and sync — all native:

```bash
checkpoint-core branch feature && checkpoint-core checkout feature
# ... work, accept ...
checkpoint-core checkout main && checkpoint-core merge feature

checkpoint-core remote add origin --type filesystem --path /shared/origin-store
checkpoint-core push origin main
checkpoint-core pull origin main
checkpoint-core bundle create --out main.tar.gz        # portable, server-free
```

Interop with the Git world when you want it (bridge only):

```bash
checkpoint-core git-export ./mirror      # replay accepted history into a Git repo
checkpoint-core git-import ./legacy-repo # import a Git repo; Checkpoint becomes truth
```

---

## Command reference (`checkpoint-core`)

| Command | What it does |
|---|---|
| `init` | Initialize a native Checkpoint repo (no Git). Creates `.checkpoint/` object store, refs, HEAD, identity. |
| `identity [--name --email]` | Show or set the author identity that stamps sessions and seals. |
| `start "<instruction>"` | Start a session; baseline = current branch head. Flags: `--tag`, `--agent`, `--model`, `--tool`, `--actor`. |
| `status` | Active session, changed files vs head, last autosave/snapshot, verification. |
| `snapshot [-m]` | Capture a meaningful intermediate snapshot (a native object). |
| `diff [--summary --files --from --to --no-renames]` | Rename-aware native diff (tree + unified content diff), no Git. |
| `verify` | Run configured verification commands; store the record. |
| `packet [--json]` | Generate a Change Packet (diff, snapshots, verification, risks, recommendation). |
| `accept [-m --no-verify --force]` | Create an **accepted snapshot**, advance the branch, seal it. Native history. |
| `reject [--reason]` | Close the session without writing history (auditable). |
| `rollback [--to-snapshot --hard --keep-files --yes]` | Safe restore; preview by default; auto pre-rollback snapshot. |
| `log [--status]` | Session history (active/accepted/rejected/rolled_back). |
| `history` | Accepted-snapshot history — the commit-log equivalent. |
| `show <session-id>` | Full session detail: snapshots, verification, ledger. |
| `watch` | **Background autosave daemon** for the active session: continuous, debounced, crash-safe. *You are never unsaved.* |
| `autosave list / show <id> [--diff] / restore <id> / gc` | Inspect and restore autosaves; garbage-collect old ones. |
| `timeline [<session-id>]` | The full story of a session: start, autosaves, snapshots, verification, accept, rollback. |
| `recover [--restore [--to <id>] --yes]` | Detect an interrupted session and restore its latest (or a chosen) autosave. |
| `branch [<name>]` / `checkout <name>` / `merge <name>` | Native branching and line-level (diff3) three-way merge: disjoint edits auto-merge, overlapping edits conflict. |
| `remote add\|list\|show\|remove` | Manage filesystem **and HTTP** remotes (`remote add origin http://host/owner/repo --token …`). |
| `fetch` / `pull` / `push` / `clone` | Hardened sync (filesystem or HTTP): verify before refs move; fetch→tracking refs, FF-only pull, safe push (`--force-with-lease`). |
| `sync status <remote>` | Ahead/behind/diverged + missing-object counts. |
| `bundle create\|verify\|import` | Portable `.tar.gz` transport; import verifies path-safety, hashes, seals, signatures, and rejects private keys. |
| `git-export <dir>` / `git-import <dir>` | The Git bridge (the only Git-touching code). |
| `verify-history` | Recompute SHA-256 seals across accepted history; flags tampering. |
| `identity create\|list\|show\|trust\|untrust\|revoke\|import\|export\|current\|use` | Manage Ed25519 signing identities and local trust. |
| `sign <snapshot>` / `verify-signatures` / `trust-status` | Sign history, verify all signatures, summarize trust. |
| `policy init\|show\|check\|explain\|validate\|test\|audit` | Opt-in policy engine: enforce who/what may change history; audit every decision. |
| `fsck [--strict --json --verify-signatures --require-signatures --policy]` | Read-only integrity check: hashes, seals, refs, trees, parents, sessions, renames, signatures, policy. |
| `gc [--dry-run --aggressive --force]` | Safely collect unreachable, past-grace objects (fsck-gated, quarantined). |
| `objects stats / list [--reachable\|--unreachable\|--type] / show <id>` | Inspect the object store. |
| `doctor` | Diagnose the installation. |

---

## You are never unsaved (the autosave daemon)

Git's model is *remember to commit*. Checkpoint's model is *you are never unsaved.* During
an active session, `checkpoint-core watch` continuously preserves your work — and an AI
agent's work — without polluting history.

```bash
checkpoint-core start "refactor the planner"
checkpoint-core watch &          # daemon: continuous, debounced, crash-safe autosaves
# ... you or an agent edit for an hour: prompts, edits, retries, partial failures ...

checkpoint-core autosave list    # every quiet point was captured
checkpoint-core recover --restore --yes   # after a crash, get the work back
checkpoint-core timeline         # the whole story: starts, autosaves, snapshots, accepts
checkpoint-core accept -m "refactor planner"   # only this becomes sealed history
```

Three tiers, never conflated:

| Tier | Purpose | Becomes history? | Moves a branch? |
|------|---------|------------------|-----------------|
| **Autosave** | Continuous, invisible safety net for recovery | No | No |
| **Snapshot** | A marked meaningful point for comparison | No | No |
| **Accepted snapshot** | Official sealed history (the commit equivalent) | **Yes** | **Yes** |

The daemon is **debounced** (a burst of edits collapses into one sensible autosave),
**deduplicated**, **crash-safe** (flushed to disk immediately; survives editor/agent/machine
failure), **ignore-aware**, and fully **isolated** — it never creates accepted history,
never moves a branch, never touches the Git bridge, and works with Git uninstalled. See
§12 of the spec.

## Renames survive (refactor-friendly review)

AI agents move files, split modules, rename components, and reorganize folders constantly.
Without rename detection that all reads as `delete + add` and review quality collapses.
Checkpoint detects renames natively — in diff, merge, and packets — so an AI refactor
reviews as clean logical change.

```bash
mv lib/parser.py core/tokenizer.py     # move + rename
checkpoint-core diff --summary
#  R  lib/parser.py -> core/tokenizer.py (100%)
#  dir  lib -> core (3 files)
```

- **Exact** (identical content, text or binary), **rename + edit** (similarity ≥ threshold,
  shown as a rename *with* its content diff), and **directory renames** (a consistent prefix
  move) — all deterministic, all configurable, none calling Git.
- **Rename-aware merge**: if one branch renames a file and another edits it, the edits land
  on the renamed file. Both-rename-to-different-paths and rename/delete are reported as
  conflicts without losing work.
- Bounded for large changesets (`max_candidates`), and toggleable (`diff --no-renames` or
  `rename_detection.enabled: false`). Content identity stays content-addressed — rename
  metadata never changes ids or seals. See §4.1 / §5.1 of the spec.

## Storage you can trust (fsck + gc)

A real VCS needs storage hygiene and integrity, not just features. Checkpoint can prove
its store is healthy and reclaim garbage without ever risking history.

```bash
checkpoint-core fsck            # is the store healthy? (read-only)
checkpoint-core objects stats   # counts + bytes by type
checkpoint-core gc --dry-run    # what WOULD be collected
checkpoint-core gc              # collect unreachable, past-grace objects (safely)
```

- **fsck** walks `refs → snapshots → trees → blobs` and verifies content hashes, accepted
  seals, tree/blob/parent references, branch/tag heads, sessions, timeline, and rename
  records. `--strict` fails on dangling objects; `--json` is machine-readable. It is
  **read-only** and returns a nonzero exit on corruption.
- **gc** deletes **only** unreachable objects older than the grace period. It **never**
  touches accepted history, branch heads, tagged snapshots, active-session objects, or
  retained autosaves. It runs fsck first and **refuses to delete on a corrupt store**,
  moves objects to a **quarantine** before permanent deletion (crash-safe), records a
  ledger event, and reports bytes reclaimed. `--dry-run` changes nothing; `--aggressive`
  shortens the grace period and drops past-retention rejected sessions.
- **Reachability** is rebuilt from objects + refs + sessions every run — no authoritative
  index, so a stale index can never cause data loss. See §13 of the spec.

## Authorship you can prove (signed identity & trust)

Integrity (Phase 4) answers *"is the store intact?"* Signing answers *"who created this
work, who approved it, and can that be verified?"* — the foundation for audit-grade and
defense-grade AI development.

```bash
checkpoint-core identity create --name "Jack" --type human   # Ed25519 keypair
checkpoint-core start "fix exposure" && ... && checkpoint-core accept -m "fix exposure"
#   signed: yes by id_human_4893dc9f88ea34dc
checkpoint-core verify-signatures      # every signature, cryptographically checked
checkpoint-core trust-status           # signed vs unsigned history, trusted vs not
```

- **Ed25519 signatures** (RFC 8032). `accept` and `merge` sign automatically when an
  identity is active; the signature is bound to the snapshot's tree, parents, session,
  message, and verification summary. Change any of them and verification fails — change
  Git-bridge provenance and it stays valid (provenance is excluded from the payload).
- **Signatures are independent of the integrity seal**: the seal proves the object is
  intact; the signature proves who accepted it.
- **Trust is local.** You create trusted identities; **imported identities start
  untrusted**. Revocation is local. **Trust policy** can require signed/trusted accepts and
  forbid an **agent** from self-accepting — a human or CI must approve.
- **Keys never leak.** Private keys live in `.checkpoint/keys/` (0600) and are never
  exported, never bundled, never autosaved, never touched by gc/fsck. Bundles carry the
  **public** identities + signatures so another machine can verify the trust chain.
- Vendored pure-Python Ed25519 fallback means signing/verification work even without the
  `cryptography` package — and with Git uninstalled. See §14 of the spec.

## Move between machines without trusting the remote

Phase 6 makes it safe to push, pull, clone, and exchange bundles between machines. The
rule is simple: **verify everything before any ref moves.**

```bash
checkpoint-core remote add origin --type filesystem --path ../origin
checkpoint-core push origin main           # sends only missing objects, atomic ref update
checkpoint-core clone ../origin team-copy  # verifies the whole graph before refs move
checkpoint-core fetch origin               # writes refs/remotes/origin/* (not your branch)
checkpoint-core pull origin main           # fast-forwards after verification (refuses if diverged)
checkpoint-core sync status origin         # ahead / behind / diverged
```

- **Never trust the remote.** Received objects are content-verified (`sha256 == id`); the
  closure's seals, parent chains, tree/blob references, and (optionally) signatures are
  checked **before** the ref updates. A bad object, a ref to a non-snapshot, a broken
  parent chain, or a failed seal/signature → the ref does not move.
- **fetch ≠ merge.** `fetch` writes remote-tracking refs only; `pull` fast-forwards or
  refuses divergence and tells you to `merge`. `push` is fast-forward-by-default; override
  with `--force-with-lease`, which only succeeds if the remote is where you think it is.
- **Atomic refs** (temp → fsync → rename). **`--dry-run`** on fetch/pull/push changes
  nothing.
- **Hardened bundles.** `bundle verify`/`import` reject **path traversal**, **absolute
  paths**, **escaping symlinks**, **private-key material**, **malformed manifests**, and
  **content-hash mismatches** — extracting to a temp area and verifying before touching
  your store.
- **Private keys never transfer** (push/pull/clone/bundle). Public identities + signatures
  do, so another machine can verify the trust chain; imported identities arrive untrusted.
  Autosaves don't transfer unless you explicitly enable it. See §15 of the spec.

## Enforce what's allowed, not just record what happened (policy engine)

A trusted store records change. A **controlled system of record** enforces *who or what is
allowed to make it.* The opt-in policy engine evaluates sensitive operations **before** they
happen and records every decision in the ledger.

```bash
checkpoint-core policy init                 # starter policy; enforcement now active
checkpoint-core policy check --operation accept
checkpoint-core accept -m "fix"             # ALLOW/DENY decided by policy, then recorded
checkpoint-core policy audit                # every decision + overrides
```

- **Who may accept?** `actor_rules` gate capabilities by identity type — by default an **AI
  agent may not self-accept**; a human or CI must approve.
- **Path & branch rules.** `src/safety/**` can require a **trusted human acceptor**, a
  **signed accept**, and named **verification** (e.g. `safety_tests`); `main`/`release/*`
  can require **signed merges** and **fast-forward only**. When multiple rules match, the
  **strictest wins**.
- **Required signatures & verification** are enforced globally; **remote rules** govern
  force-push and unsigned remote history; **bundle import** can reject unsigned history.
- **Reasoned, audited overrides.** A trusted human can override a denial with
  `--override --reason "..."` — recorded in the ledger; agents can't.
- **Deterministic & local-first.** Same input → same decision (`--json` for automation).
  `fsck --policy` evaluates accepted history against the current policy. Opt-in: with no
  policy configured, nothing is enforced. See §16 of the spec.

## Host it over HTTP (the service API)

The hosted service exposes Checkpoint repos over HTTP **without weakening the protocol** —
the server verifies before refs move, and neither side trusts the other.

```bash
checkpoint-server init-store .checkpoint-server
checkpoint-server token create --store .checkpoint-server --name dev --scopes repo:read,repo:write
checkpoint-server start --port 8800

checkpoint-core remote add origin http://localhost:8800/acme/app --token <TOKEN>
checkpoint-core push origin main      # uploads only missing objects; gets a signed receipt
checkpoint-core clone http://localhost:8800/acme/app ./local --token <TOKEN>
```

- **API tokens with scopes** (`repo:read`/`repo:write`/…/`admin`), each optionally pinned to
  one `owner/repo`. A read token can't write refs.
- **Object-level transfer**: `sync/plan` → upload only missing → `sync/push`. The server
  **verifies the closure, evaluates policy, enforces fast-forward / force-with-lease**, then
  updates the ref **atomically under a per-repo lock** and returns a **ServerReceipt** the
  client records in its ledger.
- **Never trust either side**: the server rejects hash mismatches, refs to non-snapshots,
  broken parent chains, invalid seals/signatures, policy violations, non-fast-forward
  pushes, and path-traversal / private-key material in bundles; the client re-verifies
  every object it downloads. **Private keys never cross the wire.**
- **Read APIs for a future UI**: repos, refs, sessions, timelines, packets, rename-aware
  diff, non-mutating merge-preview, signatures, policy decisions, fsck, gc, audit.
- Built on the standard library; **works with Git uninstalled.** Full reference:
  [`docs/checkpoint-hosted-api.md`](docs/checkpoint-hosted-api.md).

## Review work sessions in the browser (web UI)

GitHub reviews commits. **Checkpoint reviews work sessions.** The web UI shows what GitHub
can't: session → prompt → autosaves → snapshots → verification → policy → signatures →
accept. It's a **no-build vanilla-JS app served by `checkpoint-server`** (zero toolchain,
consistent with the project's zero-dependency ethos).

```bash
checkpoint-server start --port 8800
open http://127.0.0.1:8800/        # paste an API token to log in
```

**Two UIs ship with Checkpoint:** the **embedded** zero-build vanilla-JS app at `/` (no Node,
works offline), and a richer **Next.js** review app in [`frontend/`](frontend/) (`pnpm dev`)
that talks to the server's `/ui/*` backend-for-frontend adapter (CORS enabled) and falls back
to mock data offline.

The **session review page** puts the whole work episode on one screen — instruction,
agent/model/tool, timeline, rename-aware diff, packet, policy decision (allow/deny + reasons
+ required actions), signatures & trust (signer identity/type, trusted/untrusted/unknown/
revoked), verification, and live integrity — with Policy-check / Verify-signatures / fsck
actions. Accept/reject/rollback are shown as the exact CLI commands (they run client-side).
401 returns to login; 403 shows a clear permission error; private keys are never displayed.
Full reference: [`docs/checkpoint-web-ui.md`](docs/checkpoint-web-ui.md); walkthrough:
[`examples/web_review_demo.md`](examples/web_review_demo.md).

## How it works (native objects, no Git)

- **Blob** — raw file bytes, addressed by `sha256(bytes)`.
- **Tree** — a sorted path→blob map (a directory snapshot), addressed by the SHA-256 of
  its canonical JSON.
- **Snapshot** — a tree + provenance: `parents`, the producing `session`, `kind`
  (`accepted` / `snapshot` / `autosave`), message, author, verification ref, and a
  **SHA-256 content seal**. Merges and Git-bridge provenance attach as metadata without
  affecting the seal.
- **Session** — the central object: instruction, actor/agent, base, intermediate
  snapshots, verification runs, and the accept/reject result.
- **Refs / HEAD** — `refs/heads/<branch>` points at an accepted snapshot; history is the
  parent-chain of accepted snapshots.

Working-tree state is captured by scanning files into a tree (respecting
`.checkpointignore`); rollback and checkout materialize a tree back to disk. Diffs use
Python's `difflib`. **None of this imports Git** — the bridge is the only component that
shells out to `git`, and it is loaded lazily.

### Identity & integrity

Each accepted snapshot carries a `sha256-seal` binding its tree, parents, session,
message, author, and timestamp. `checkpoint-core verify-history` recomputes the seals and
reports any break. On top of this integrity seal, accepted snapshots can also be
cryptographically **signed with Ed25519** by an identity — see
[Authorship you can prove](#authorship-you-can-prove-signed-identity--trust).

---

## The Git adapter (`checkpoint`) — the wedge

For teams that already live in Git and aren't ready to switch, the adapter gives the same
session / snapshot / verify / accept / rollback ergonomics **on top of an existing Git
repo**. There, Git stays the source of truth and `accept` creates a normal Git commit.

```bash
cd existing-git-repo
checkpoint init
checkpoint start "fix the bug"
# ... edit ...
checkpoint accept -m "fix the bug"   # -> a clean Git commit
```

It is a bridge for adoption, not the protocol. See
[`docs/checkpoint-protocol.md`](docs/checkpoint-protocol.md) and the
[adapter quick reference](#adapter-quick-reference) below.

---

## Specs

- [`docs/checkpoint-core-protocol.md`](docs/checkpoint-core-protocol.md) — **the real
  protocol**: native object model, history, branch/merge, identity/seals, sync, the Git
  bridge, store layout, and conformance (incl. the "works with Git uninstalled" rule).
- [`docs/checkpoint-protocol.md`](docs/checkpoint-protocol.md) — the Git-adapter spec.

## Roadmap

1. **Phase 1 (done):** Checkpoint Core protocol + CLI, plus the Git adapter wedge.
2. **Phase 2 (done):** background autosave daemon, timeline, and recovery.
3. **Phase 3 (done):** native rename detection in diff, merge, history, and packets.
4. **Phase 4 (done):** object GC + `fsck` — integrity checking and safe garbage collection.
5. **Phase 5 (done):** signed identity & trust (Ed25519) — provable authorship and approval.
6. **Phase 6 (done):** hardened remote sync — fetch/pull/push/clone/bundles, verify before
   refs move, never trust the remote.
7. **Phase 7 (done):** policy engine — enforce who/what may change history, with audit and
   reasoned overrides.
8. **Phase 8 (done):** hosted service API — host repos over HTTP with token auth, verified
   transfer, server-side policy, and audit; the protocol foundation for hosted Checkpoint.
9. **Phase 9 (done):** web review UI — review work sessions (prompt → diff → policy →
   signatures → accept) in the browser, served by the API.
10. **Next:** agent integrations (Cursor, Claude Code, Codex, Copilot); public developer
    preview (v1.0).
4. **Phase 4:** hosted Checkpoint service (same object model and sync verbs over HTTP).
5. **Phase 5:** web UI for sessions, diffs, prompts, verification, approvals, rollback.
6. **Phase 6:** team workflow, policy engine, compliance, audit, enterprise controls.

## Development

```bash
pip install -e . pytest pyyaml
python -m pytest -q        # core tests run in non-git dirs by design
```

The core suite proves the protocol's independence from Git; the adapter suite proves the
Git-bridge behavior.

---

## Adapter quick reference

| Command | Effect (on an existing Git repo) |
|---|---|
| `checkpoint init` | Add `.checkpoint/`, gitignore it. |
| `checkpoint start "<intent>"` | Begin a session at current HEAD. |
| `checkpoint snapshot / diff / verify / packet` | Capture and review work (via Git plumbing). |
| `checkpoint accept -m "..."` | Create one clean Git commit of the session delta. |
| `checkpoint rollback [--hard]` | Restore the working tree; safe by default. |
| `checkpoint log / show / export` | Audit and export sessions. |

## License

MIT.
