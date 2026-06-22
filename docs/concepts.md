# Concepts

Checkpoint's mental model in plain English. The deep spec is
[checkpoint-core-protocol.md](checkpoint-core-protocol.md).

**The one-line distinction:** *Git stores commits. Checkpoint records the full work
session.* In Git the core object is the commit; in Checkpoint the core object is the
**session**.

| Term | What it is |
|------|------------|
| **Session** | The full work episode: the instruction/prompt, the actor (human or AI agent + model + tool), autosaves, snapshots, verification runs, the policy decision, and signatures. History links back to it. |
| **Autosave** | Continuous, invisible **recovery-only** state captured while you (or an agent) work. Never history; never moves a branch. *You are never unsaved.* |
| **Snapshot** | A **meaningful intermediate** state you (or an agent) mark for comparison. Not history. |
| **Accepted Snapshot** | The **official, sealed history** state created when a reviewed session is accepted — the commit equivalent. It carries a SHA-256 integrity seal and (optionally) an Ed25519 signature, and links to its session. |
| **Policy Decision** | Whether an operation (accept/merge/push/…) is **allowed**, by a deterministic, opt-in policy engine. Recorded in the ledger; supports reasoned, signed overrides. |
| **Signature** | An Ed25519 signature by an **identity** (human / agent / ci / machine / service) binding the snapshot's tree, parents, session, message, and verification. Proves *who approved this*. |
| **Trust** | A **local** decision about which identities you trust. Created identities are trusted; imported ones start untrusted; identities can be revoked. |
| **Remote** | Another Checkpoint store (filesystem path or HTTP URL) you sync with. Sync verifies everything before refs move; private keys never transfer. |
| **Hosted Server** | An HTTP service that hosts repos, enforces policy and signatures, and serves the web UI — without weakening the protocol. |
| **Web Review UI** | The browser surface for reviewing a **session**, not just a diff. |

## The lifecycle

```
start "<instruction>"            → a session begins (baseline = branch head)
   … edit (autosaves happen) …
snapshot -m "…"                  → mark a meaningful state (optional)
verify                           → run configured checks
packet                           → the proposed change + recommendation
accept -m "…"                    → policy + signatures + verification → one sealed,
                                   signed accepted snapshot; the branch advances
   (or) reject / rollback        → close or restore safely; nothing lost
```

## Why autosaves are not commits
Commits are precious, reviewed, signed history. Autosaves are a safety net for the messy
middle. Conflating them is how Git histories become noise. Checkpoint keeps the messy
middle recoverable **and** keeps history clean.

## Why this helps with AI agents
An agent's work is a *session*, not a single commit: a prompt, many edits, retries, partial
failures, tests. Checkpoint captures that whole episode, lets a human review it as one unit,
and enforces that **a human (or CI) — not the agent — signs off**. If an agent makes a mess,
`rollback` restores the last good state and the autosaves are still there.
