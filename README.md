# Checkpoint Protocol

**A new version-control protocol built for human + AI-generated code.**

Git was built for human-written code. Checkpoint is built for what comes next: where
every human and AI coding session is continuously captured, verified, reversible, and
promotable into clean accepted history. **Checkpoint Core is the source of truth. Git is
supported only as an import/export and mirroring bridge, not as the foundation.**

![status: MVP](https://img.shields.io/badge/status-MVP-blue)
![python: 3.8+](https://img.shields.io/badge/python-3.8%2B-3776ab)
![no git required](https://img.shields.io/badge/core-no%20Git%20required-success)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

> **The simple test:** *If Git disappeared, would Checkpoint still work?*
> For **Checkpoint Core: yes.** Sessions, snapshots, diffs, prompts, verification,
> accepted states, branches, merges, and sync are native protocol objects in
> Checkpoint's own content-addressed store. (Proven by the test suite, which runs the
> entire VCS in directories that are not Git repos.)

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

checkpoint-core remote add origin --location /shared/origin-store
checkpoint-core push origin main
checkpoint-core pull origin main
checkpoint-core bundle export main --out main.tar.gz   # portable, server-free
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
| `remote add <name> --location <dir>` / `push` / `pull` | Content-addressed sync between stores (server-free). |
| `bundle export\|import` | Portable `.tar.gz` transport for offline sync. |
| `git-export <dir>` / `git-import <dir>` | The Git bridge (the only Git-touching code). |
| `verify-history` | Recompute SHA-256 seals across accepted history; flags tampering. |
| `identity create\|list\|show\|trust\|untrust\|revoke\|import\|export\|current\|use` | Manage Ed25519 signing identities and local trust. |
| `sign <snapshot>` / `verify-signatures` / `trust-status` | Sign history, verify all signatures, summarize trust. |
| `fsck [--strict --json --verify-signatures --require-signatures]` | Read-only integrity check: hashes, seals, refs, trees, parents, sessions, renames, signatures. |
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
6. **Phase 6:** remote protocol hardening; hosted Checkpoint service; agent integrations
   (Cursor, Claude Code, Codex, Copilot); web UI; team policy/compliance.
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
