# Checkpoint Core Protocol Specification

Version: 0.1 (MVP)
Status: Draft
Store directory: `.checkpoint`
Object hash: SHA-256 (hex)

---

## 0. What this is (and how it differs from the Git adapter)

Git was built for human-written code. Checkpoint Core is a **version-control protocol
built for human + AI-generated code**, where Git is *not* the source of truth.

The simple test:

> If Git disappeared, would Checkpoint still work?

For Checkpoint Core: **yes.** Sessions, snapshots, diffs, prompts, verification, accepted
states, branches, merges, and sync are **native protocol objects** stored in Checkpoint's
own content-addressed object store. Git is supported only as an **import/export and
mirroring bridge**, never as the foundation.

This is the opposite of the Checkpoint *Git adapter* (`checkpoint`, see
`docs/checkpoint-protocol.md`), which layers on top of an existing Git repo. The adapter
remains useful as a wedge for existing repos. Checkpoint Core is the real protocol.

```
Checkpoint Core Protocol   <- source of truth
        |
   Checkpoint CLI (checkpoint-core)
        |
   Checkpoint Service (future)

Optional bridges:  Git import/export   GitHub sync   editor/agent integrations
```

### The core object is the SESSION

In Git, the core object is the **commit**. In Checkpoint, the core object is the
**session**, because AI does not just make commits — it runs a *work session*: a prompt,
a plan, edits, tests, retries, partial failures, fixes, verification, then a human accept
or reject. History is a chain of **accepted snapshots**, and every accepted snapshot
points back to the full session that produced it. You can walk history and, at each step,
recover the instruction, the agent/model, the intermediate snapshots, and the
verification record — none of which Git can represent.

---

## 1. Object model

All objects are content-addressed by the SHA-256 of their canonical serialization.

- **Blobs** are raw file bytes. `id = sha256(bytes)`.
- **Structured objects** (tree, snapshot) are serialized as **canonical JSON**:
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded
  UTF-8. `id = sha256(canonical_json_bytes)`.

Objects are immutable. The object store deduplicates by id.

### 1.1 Blob

Raw file contents. No header. Referenced by trees.

### 1.2 Tree

A flat snapshot of a directory state: a sorted list of path → blob entries.

```json
{
  "type": "tree",
  "entries": [
    { "path": "src/app.py", "blob": "<sha256>", "mode": "100644" },
    { "path": "README.md",  "blob": "<sha256>", "mode": "100644" }
  ]
}
```

Paths are repo-relative, POSIX-separated, sorted ascending. `mode` is `100644` (file) or
`100755` (executable). A flat path map (rather than nested trees) is used in the MVP for
simplicity; nested trees are a compatible future optimization.

### 1.3 Snapshot

A point-in-time state plus provenance. This is the unit of history.

```json
{
  "type": "snapshot",
  "tree": "<tree sha256>",
  "parents": ["<snapshot sha256>"],
  "session": "<session-id>",
  "kind": "accepted",
  "message": "fix camera exposure defaults",
  "author": { "id": "jack", "name": "Jack", "email": "jack@example.com" },
  "timestamp": "2026-06-21T14:36:00+00:00",
  "verification": "<verification record id or null>",
  "signature": { "algo": "sha256-seal", "author": "jack", "seal": "<sha256>" }
}
```

- `kind` is `accepted` (canonical history), `snapshot` (meaningful intermediate), or
  `autosave` (recovery only).
- `parents` is a list (one parent normally; two for a merge; empty for the first).
- `session` links back to the producing session object (the core object).
- `signature` is the SHA-256 content seal (§6).

Only `kind: "accepted"` snapshots are referenced by branches and form history. Snapshots
and autosaves are reachable through their session for audit/recovery but are not history.

### 1.4 Session (the core object)

A session is a mutable aggregate while active, then sealed by an accept/reject. It is the
protocol's central object.

```json
{
  "schema_version": 1,
  "session_id": "cs_20260621_143012_fix_camera_exposure",
  "instruction": "fix camera exposure defaults without changing autonomy behavior",
  "status": "active",
  "created_at": "...", "updated_at": "...",
  "actor": { "type": "agent", "id": "claude-code", "name": "Claude Code" },
  "agent": { "name": "claude-code", "model": "opus-4.8", "tool": "Edit",
             "prompt": "...", "response_summary": null,
             "files_touched": [], "commands_run": [] },
  "base": { "branch": "main", "head": "<snapshot sha or null>", "tree": "<tree sha>" },
  "risk_tags": ["hardware"],
  "snapshots": ["<snapshot sha>", ...],
  "autosaves": ["<snapshot sha>", ...],
  "verifications": ["<verification id>", ...],
  "result": { "kind": "accepted", "snapshot": "<accepted snapshot sha>" },
  "packet": "packet.json"
}
```

`base.head` is the branch head at session start; `base.tree` is the working tree captured
at start (the baseline all diffs are measured against).

### 1.5 Verification record

```json
{
  "verification_id": "ver_...",
  "session_id": "cs_...",
  "tree": "<tree sha>",
  "created_at": "...",
  "overall": "passed",
  "results": [
    { "name": "tests", "command": "pytest -q", "exit_code": 0, "status": "passed",
      "duration_seconds": 12.4, "stdout_summary": "...", "stderr_summary": "",
      "started_at": "...", "finished_at": "..." }
  ]
}
```

---

## 2. References, HEAD, branches

- **Branch**: `refs/heads/<name>` — a file containing the SHA of the branch's head
  **accepted snapshot**.
- **HEAD**: `HEAD` — either `ref: refs/heads/<name>` (attached) or a raw SHA (detached).
- **Tags** (future): `refs/tags/<name>`.

History is the parent-chain of accepted snapshots reachable from a branch head. There is
no separate "commit" object — an accepted snapshot *is* the history node, and it carries
its session link.

---

## 3. Lifecycle and state machine

```
checkpoint-core init
checkpoint-core identity --name ... --email ...
        |
        v
start "<instruction>"      session: active   (base.tree captured from working dir)
        |
   edit files
        |
   autosave (opportunistic, recovery)    snapshot (meaningful, --message)
        |
   diff / verify / packet
        |
   +--> accept   -> new accepted snapshot, branch head advances, session: accepted
   +--> reject   -> session: rejected (no history written, fully auditable)
   +--> rollback -> working dir restored to base/snapshot (pre-rollback snapshot taken)
```

Session status: `active` → terminal `accepted` | `rejected` | `rolled_back`.
One active session per working tree in the MVP.

### Accept flow

1. Resolve the active session and the current branch head `H`.
2. Run verification (forced if a risk rule requires it); secret-scan the diff.
3. Capture the working tree → tree `T`.
4. Create an **accepted snapshot** with `tree=T`, `parents=[H]` (or `[]` if unborn),
   `session=<id>`, `kind="accepted"`, message, author, verification ref, and a SHA-256
   seal (§6).
5. Advance the current branch ref to the new snapshot id.
6. Append an `accept` ledger event; set session `result` and status `accepted`.

No Git is involved. History grows in Checkpoint's own store.

### Rollback flow

Identical intent to the adapter: preview by default, auto pre-rollback snapshot, then
restore the working directory by materializing the target tree and deleting files added
since the target (unless `--keep-files`). Targets: session base (default) or a snapshot.

---

## 4. Native diff format

Checkpoint does not depend on `git diff`. Diffs are computed natively:

- **Tree diff** compares two trees' path→blob maps and yields, per path, a status of
  `added` / `modified` / `deleted` (and `renamed` when a deleted+added pair shares a blob
  id). Output:

  ```json
  { "files": [ { "path": "src/app.py", "status": "modified",
                 "old_blob": "<sha|null>", "new_blob": "<sha|null>" } ],
    "stats": { "files_changed": 1, "insertions": 4, "deletions": 2 } }
  ```

- **Content diff** is a standard unified diff produced from blob contents (Python
  `difflib.unified_diff`), independent of Git. The pair (structured tree diff + unified
  content diff) is the native diff format. It is human-readable and tool-parseable, and
  can be rendered to Git's patch format by the bridge if needed.

---

## 5. Branch and merge

- **branch `<name>`** creates `refs/heads/<name>` at the current head.
- **checkout `<name>`** materializes the branch head's tree into the working directory and
  attaches HEAD.
- **merge `<name>`** performs a **file-level three-way merge** between the current head
  (`ours`), the named branch head (`theirs`), and their **merge base** (lowest common
  ancestor in the accepted-snapshot DAG):
  - file changed on only one side → take that side;
  - both sides identical → take it;
  - both sides changed differently → **conflict**: the file is written with standard
    conflict markers (`<<<<<<< ours` / `=======` / `>>>>>>> theirs`) and the merge is
    reported as conflicted (no merge snapshot is created until resolved).
  - A clean merge creates an accepted snapshot with `parents=[ours, theirs]`.

  Line-level (diff3) merging is a documented future upgrade; file-level is the MVP
  contract.

---

## 6. Identity and signatures

- **Identity** lives in `.checkpoint/identity.json`: `{ id, name, email }`. It stamps the
  `author` of sessions and accepted snapshots.
- **Signature** (MVP): a **SHA-256 content seal** over the accepted snapshot's defining
  fields:

  ```
  seal = sha256( canonical_json({ tree, parents, session, message, author, timestamp }) )
  signature = { "algo": "sha256-seal", "author": <id>, "seal": <seal> }
  ```

  This is tamper-evident: any change to a sealed field invalidates the seal. It binds the
  snapshot to an author identity but is not asymmetric crypto. The `algo` field makes the
  scheme pluggable; **ed25519** signing (via an optional `cryptography` dependency) is the
  intended production upgrade and can coexist by emitting `algo: "ed25519"`.

`checkpoint-core verify-history` recomputes seals along a branch and reports any break.

---

## 7. Sync protocol

Sync is content-addressed and idempotent, so it works between any two stores without a
central server.

- A **remote** is named in `.checkpoint/config.yaml` and resolves to either another
  Checkpoint Core store directory (a local path / shared volume) or a portable **bundle**.
- **push**: copy missing objects (by id), then fast-forward the remote's ref. Objects are
  immutable and deduplicated, so re-pushing is a no-op.
- **pull**: copy missing objects from the remote, then fast-forward the local ref (or
  report a divergence requiring `merge`).
- **bundle export/import**: serialize the objects reachable from a ref + the ref value +
  relevant ledger events into a `.tar.gz`, and import them into another store. This is the
  transport when there is no shared filesystem.

A future hosted service implements the same verbs over HTTP; the object model and
idempotency guarantees do not change.

---

## 8. Git bridge (compatibility only)

The bridge is the **only** component that touches Git. Core never imports Git.

- **git-export**: replay the accepted-snapshot chain into a Git repository — for each
  accepted snapshot from root to head, materialize its tree and create a Git commit with
  the snapshot's message, author, and timestamp. The result is a normal Git history that
  mirrors Checkpoint history. Session/prompt/verification provenance is preserved in the
  Git commit trailer/notes (best-effort) but lives canonically in Checkpoint.
- **git-import**: walk a Git repository's commits and create accepted snapshots
  (`kind: "accepted"`) with matching trees, messages, authors, and parent links, plus a
  synthetic import session per commit. After import, the Checkpoint store is the source of
  truth and Git is no longer required.

Round-trip identity is preserved at the tree level (file contents are byte-identical);
commit/snapshot ids differ because the object formats differ by design.

---

## 9. Store layout

```
.checkpoint/
  config.yaml            # config (verification, risk rules, secrets, remotes)
  identity.json          # author identity
  HEAD                   # "ref: refs/heads/main" or a raw sha (detached)
  refs/
    heads/<branch>       # -> accepted snapshot sha
    remotes/<remote>/<branch>
  objects/
    <ab>/<sha256>        # blobs and structured objects (content-addressed)
  sessions/
    <session-id>/
      session.json       # the session object (mutable while active)
      instruction.txt
      packet.json
      verification/<id>.json
  ledger.jsonl           # append-only event log
  tmp/ cache/
```

`.checkpoint/` is the **source of truth**. There is no Git directory required. A working
directory alongside `.checkpoint/` holds the materialized files.

---

## 10. Ledger event schema

Append-only JSONL; events are never edited. Mirrors the adapter's ledger.

```json
{ "event_id": "evt_...", "event_type": "accept", "session_id": "cs_...",
  "timestamp": "...", "actor": { "type": "agent", "id": "claude-code" },
  "branch": "main", "head": "<sha>", "payload": { } }
```

`event_type` ∈ { init, identity, session_start, snapshot, autosave, verification, packet,
accept, reject, rollback, branch, checkout, merge, push, pull, git_import, git_export }.

---

## 11. Conformance

An implementation conforms to Checkpoint Core Protocol 0.1 if it:

1. Stores content-addressed blobs/trees/snapshots under `.checkpoint/objects` keyed by
   SHA-256 of canonical serialization (§1).
2. Represents history as a parent-chain of `accepted` snapshots referenced by
   `refs/heads/*`, with each snapshot linking to its producing session (§1.3–§2).
3. Implements the session state machine and accept/reject/rollback flows **without Git**
   (§3).
4. Computes diffs natively (§4) and merges at least at file level with conflict markers
   (§5).
5. Stamps an author identity and a verifiable SHA-256 content seal on accepted snapshots
   (§6).
6. Supports content-addressed push/pull/bundle sync (§7).
7. Provides Git import/export as an isolated bridge that the core never depends on (§8).
8. Passes the test: **with Git uninstalled, all of the above still work.**
