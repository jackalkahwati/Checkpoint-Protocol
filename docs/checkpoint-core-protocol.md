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

- `kind` is `accepted` (canonical history) or `snapshot` (meaningful intermediate).
  (Autosaves are a separate, lighter record type — see §12 — not snapshot objects. Their
  trees are still ordinary content-addressed tree objects, so storage dedupes across all
  three tiers.)
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

### 4.1 Rename detection

A naive diff reports a moved file as `deleted old` + `added new`. AI agents move, split,
and reorganize files constantly, so Checkpoint detects renames natively (no Git) and
reports them as a single change. Detection is **deterministic** and **configurable**.

The rename-aware **DiffResult** is:

```json
{
  "added":    ["..."],
  "deleted":  ["..."],
  "modified": ["..."],
  "renamed":  [ RenameRecord, ... ],
  "directory_renames": [ { "old_dir": "lib", "new_dir": "core", "count": 3 } ],
  "stats": { "files_changed": N, "insertions": I, "deletions": D }
}
```

A **RenameRecord** is:

```json
{
  "old_path": "lib/parser.py",
  "new_path": "core/tokenizer.py",
  "similarity": 1.0,
  "old_blob_id": "<sha256>",
  "new_blob_id": "<sha256>",
  "kind": "exact",          // exact | similar | rename_edit | directory
  "confidence": 1.0,
  "detected_at": "..."
}
```

**Algorithm** (over the raw added/deleted sets):

1. **Exact** — match a deleted path to an added path with the **same blob id**
   (`similarity = 1.0`). Works for text *and* binary. Greedy, deterministic tie-break by
   path.
2. **Similar / rename+edit** (text only) — for the remaining text files, compute a
   deterministic line-similarity with `difflib.SequenceMatcher.ratio()` (gated by the
   cheap `real_quick_ratio`/`quick_ratio` prefilters). Pairs scoring ≥
   `similarity_threshold` are matched best-first (greedy, deterministic tie-break). A
   matched pair with content changes is `rename_edit`; the unified diff shows the content
   change. **Binary files are never similarity-matched** (`binary_exact_only`).
3. **Directory rename** — from the matches found, learn `old_dir → new_dir` prefix moves
   that recur (≥ 2 files); reclassify those records as `directory`, and sweep any remaining
   same-basename files under a trusted mapping (covers files too edited to pass the
   content threshold).

**Bounding cost**: if `|deleted| × |added| > max_candidates`, the O(n·m) similarity pass is
skipped (exact + directory detection still run), so large changesets never explode.
Rename detection is disabled with `rename_detection.enabled: false` (or `diff --no-renames`).

```yaml
rename_detection:
  enabled: true
  similarity_threshold: 0.60
  max_candidates: 10000
  detect_directory_renames: true
  binary_exact_only: true
```

Rename detection improves review and merge; **content identity remains content-addressed**
(it never changes blob/tree/snapshot ids or seals).

---

## 5. Branch and merge

- **branch `<name>`** creates `refs/heads/<name>` at the current head.
- **checkout `<name>`** materializes the branch head's tree into the working directory and
  attaches HEAD.
- **merge `<name>`** performs a **line-level three-way (diff3) merge** between the current
  head (`ours`), the named branch head (`theirs`), and their **merge base** (lowest common
  ancestor in the accepted-snapshot DAG). Per path:
  - changed on only one side → take that side;
  - both sides identical, or both made the same change → take it;
  - both sides changed the same **text** file → run **diff3**:
    - **disjoint** line regions → **auto-merge** (no conflict); the merged content becomes
      a new blob in the merged tree;
    - **overlapping** line regions → **conflict** only around the overlapping hunk, written
      with standard markers (`<<<<<<< ours` / `=======` / `>>>>>>> theirs`); surrounding
      unchanged lines are preserved;
  - **binary** file changed on both sides → conflict (cannot line-merge);
  - one side **deletes** while the other **modifies** → conflict.
  - A clean merge (including auto-merged files) creates an accepted snapshot with
    `parents=[ours, theirs]`. If any path conflicts, conflicted files are written to the
    working tree with markers and **no** merge snapshot is created until resolved (resolve,
    then `start` + `accept` records the merge).

  diff3 synchronizes on lines common to all three versions (base ∩ ours ∩ theirs) and
  classifies the regions between those anchors. Semantic / AST-aware merge is intentionally
  out of scope for this version.

### 5.1 Rename-aware merge

Merge is **identity-based**: each file that existed in the merge base is tracked by its
**base path** even if one or both sides renamed it. The merge detects renames on each side
(base→ours, base→theirs, §4.1), resolves the file's final path, then performs a line-level
content merge of the base/ours/theirs contents at that identity. **MergeResult** is
`{ merged_tree_id, conflicts, rename_records, auto_merged }`.

| Case | Result |
|------|--------|
| ours renames, theirs unchanged | file at ours' new path |
| ours unchanged, theirs renames | file at theirs' new path |
| ours renames, theirs edits original | renamed file with theirs' edits applied (line-level merge at the new path) |
| both rename to the **same** path | one file at that path; contents line-merged if both edited |
| both rename the same origin to **different** paths | **rename conflict** — both versions materialized at their respective paths; no merge snapshot |
| ours deletes, theirs renames (or vice-versa) | **rename/delete conflict** — surviving content preserved on disk |
| directory rename on one side, file edits on the other | files land at the moved paths with edits applied where the line merge succeeds |

**Conflict layout**: content conflicts use inline diff3 markers (§5). Path conflicts
(rename/rename to different paths, rename/delete) are reported structurally and the
involved file versions are materialized at their natural paths so no work is lost; the
merge produces no accepted snapshot until the user resolves and accepts. Rename detection
in merge is bounded and configurable exactly as in §4.1, and never alters accepted-snapshot
seals (the merge snapshot is sealed normally over its merged tree).

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
  (`kind: "accepted"`) with matching trees, **cleaned** messages, authors, and parent
  links, plus a synthetic import session. After import, the Checkpoint store is the source
  of truth and Git is no longer required.

### Trailer discipline (bridge metadata is not history)

Git trailers are **bridge metadata**, never Checkpoint history text. The bridge enforces:

- **On export**, the commit message is the snapshot's clean message plus exactly **one**
  trailer block built from the snapshot's own fields:
  `Checkpoint-Session: <id>` and `Checkpoint-Snapshot: <sha>`. Any stray `Checkpoint-*`
  lines already in the message are stripped first, so trailers can never accumulate.
- **On import**, all `Checkpoint-*` trailer lines are stripped from the commit message.
  The snapshot's `message` is the clean human text; the stripped values and the source
  Git commit are recorded under the snapshot's optional `bridge` field, e.g.:

  ```json
  "bridge": {
    "source": "git-import",
    "git_commit": "<sha1>",
    "origin_session": "cs_...",
    "original_trailers": { "Session": ["cs_..."], "Snapshot": ["<sha256>"] }
  }
  ```

  The `bridge` field is **excluded from the content seal** (§6), so provenance never
  affects snapshot identity or seal validity.
- **Idempotency**: `core → git → core → git → …` neither compounds trailers nor mutates
  the human message. Repeated round-trips are stable.

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
    tags/<tag>           # -> accepted snapshot sha (protected root)
    remotes/<remote>/<branch>
  objects/
    <ab>/<sha256>        # blobs and structured objects (content-addressed)
  identities/<id>.json   # public IdentityRecords (§14)
  keys/<id>.key          # PRIVATE Ed25519 seeds, 0600 — never exported/captured/collected
  signatures/<object-id>/<signature-id>.json   # external SignatureRecords (§14)
  current_identity       # active signing identity id
  quarantine/<stamp>/    # gc holding area before permanent deletion (§13)
    <ab>/<sha256>
    manifest.json
  sessions/
    <session-id>/
      session.json       # the session object (mutable while active)
      instruction.txt
      packet.json
      verification/<id>.json
      timeline.jsonl     # per-session chronological event log (§12)
      autosaves/
        <autosave-id>/
          autosave.json  # autosave record (§12)
          tree.json      # copy of the captured tree object (inspection/recovery)
          diff.patch     # unified diff base_snapshot -> autosave tree
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

## 12. Autosaves, the daemon, timeline, and recovery (Phase 2)

The product promise: **you are never unsaved.** Git's model is "remember to commit";
Checkpoint continuously preserves in-progress work during an active session, without ever
polluting accepted history.

### Three tiers (do not conflate)

| Tier | Purpose | Becomes history? | Moves a branch? |
|------|---------|------------------|-----------------|
| **Autosave** | Continuous, invisible safety net for recovery | No | No |
| **Snapshot** | User/agent-marked meaningful point for comparison | No | No |
| **Accepted snapshot** | Official sealed history (commit equivalent) | **Yes** | **Yes** |

### Autosave record schema (`autosaves/<autosave-id>/autosave.json`)

```json
{
  "autosave_id": "auto_20260622_001144_002",
  "session_id": "cs_...",
  "parent_autosave_id": "auto_20260622_001144_001",
  "timestamp": "2026-06-22T00:11:44+00:00",
  "reason": "edit",
  "changed_paths": ["notes.txt"],
  "tree_id": "<tree sha256>",
  "base_snapshot_id": "<accepted snapshot sha | null>",
  "content_seal": "<sha256 over the fields above>",
  "daemon_version": "0.1"
}
```

The `content_seal` is a SHA-256 over `{autosave_id, session_id, parent_autosave_id,
timestamp, tree_id, base_snapshot_id, changed_paths}`. It is **independent** of the
accepted-history seal (§6); tampering with an autosave never affects `verify-history`.
The captured `tree_id` (and its blobs) are ordinary content-addressed objects, so an
autosave fully reconstructs the working tree and dedupes against everything else.

### The daemon (`checkpoint-core watch`)

A foreground file watcher for the active session:

- **Polling-based** by design (reliable everywhere); native file events may be used
  opportunistically when available. `polling_interval_ms` controls the cadence.
- **Debounced**: an autosave is written only after the working tree has been quiet for
  `debounce_ms`, so a burst of rapid edits collapses into one sensible autosave instead of
  one object per keystroke.
- **Deduplicated**: if the captured tree equals the previous autosave's tree, nothing is
  written.
- **Crash-safe**: each autosave is flushed to disk immediately; the watcher also writes a
  final autosave on stop. After an editor/agent/machine failure the autosaves on disk are
  intact.
- **Isolated**: never creates accepted history, never moves a branch ref, never touches the
  Git bridge, never changes snapshot seals. Works with Git uninstalled.
- **Ignore-aware**: respects `.checkpointignore`/`.checkpoint`. Files larger than
  `ignore_large_files_mb` are skipped to stay cheap (and are protected from deletion on
  restore).

### Timeline (`checkpoint-core timeline`)

Each session has an append-only `timeline.jsonl` recording the session's story:
`session_started`, `autosave_created`, `snapshot_created`, `verification_run`,
`accepted`, `rollback`, `recover_invoked`. Each event is
`{ "type", "timestamp", "payload" }`.

### Recovery (`checkpoint-core recover`)

Detects an interrupted session (one left active) and reports its latest autosave and
whether the working tree has diverged from it. `--restore [--to <autosave-id>] [--yes]`
materializes that autosave back into the working tree (protecting large skipped files).

### Garbage collection

Autosaves are garbage-collectable. GC removes autosave **records** beyond `gc.keep_last`
that are also older than `gc.keep_for_days`. It never removes object-store entries or
accepted snapshots, so history is always safe. (Unreferenced blob/tree objects can be
swept by a separate object GC — out of scope here.)

### Configuration

```yaml
autosave:
  enabled: true
  debounce_ms: 1000
  max_autosaves_per_session: 500
  ignore_large_files_mb: 50
  polling_interval_ms: 2000
  gc:
    keep_last: 100
    keep_for_days: 14
```

---

## 13. Integrity (fsck) and garbage collection (Phase 4)

Storage hygiene and trust. Two separate systems: **fsck** (read-only integrity) and
**gc** (safe deletion of only what is provably unreachable). Both work with Git
uninstalled and never call Git.

### Reachability model

A **reachability walker** marks every object reachable from a **protected root**:

- `refs/heads/*` and `refs/tags/*` → accepted snapshots → parent chains → trees → blobs;
- the active-session pointer, and every session record's `base.tree`, `base.head`,
  `snapshots[]`, and `result.snapshot`;
- each session's **verification-record trees** and **packet trees**;
- **autosave trees** within the retention window (`keep_autosaves_days`; an active session
  retains all of its autosaves).

Truth is rebuilt from objects + refs + sessions on every run — there is no authoritative
index, so a stale index can never cause data loss. Object **type is intrinsic to content**
(a structured object is JSON with `type ∈ {tree, snapshot}`; everything else is a blob).

Definitions:
- **Reachable** — referenced from a protected root.
- **Unreachable** — not reachable from any protected root.
- **Dangling** — unreachable but still within the grace period (kept).
- **Garbage** — unreachable and older than the grace period (collectible).
- **Corrupt** — an object whose content hash, schema, tree/blob/parent references, or seal
  does not validate.

### fsck behavior

Read-only. Walks `refs → snapshots → trees → blobs` and verifies:
content-addressed id == `sha256(bytes)`; accepted-snapshot **seals**; trees' blobs exist;
snapshots' trees exist and are trees; parent chains resolve to snapshots; branch/tag heads
point to valid **accepted** snapshots; sessions reference valid baselines/snapshots/
autosave trees; timeline events are parseable; packet **rename records** reference existing
blobs; no conflicting-type ids; no unknown structured types. Reports:
`objects_scanned, refs_scanned, sessions_scanned, reachable, dangling, corrupt, missing,
warnings, errors, result ∈ {healthy, warnings, corrupt}`. `--strict` promotes warnings
(incl. dangling objects) to a failing result; `--json` emits the report. Exit code: `0`
healthy, `1` warnings-in-strict, `2` corrupt. fsck never modifies the store (repair is out
of scope for this phase).

### gc behavior

Deletes only **garbage**. It must never delete anything reachable: accepted history,
branch heads, tagged snapshots, active-session objects, or retained autosaves. Steps:

1. Run fsck first (unless `--force`); **abort if the store is corrupt**.
2. Purge expired quarantine batches (`quarantine_days`).
3. Compute reachability; `candidates = on-disk − reachable`, filtered to those older than
   `grace_period_days`.
4. Move candidates into `quarantine/<stamp>/` (crash-safe two-stage delete) with a
   `manifest.json`; a later run purges the quarantine.
5. Record a `gc` ledger event and return a report:
   `objects_scanned, reachable, candidates, quarantined, deleted, bytes_reclaimed,
   skipped{reason:count}`.

`--dry-run` computes and reports without touching anything. `--aggressive` uses a zero
grace period and drops protection for **rejected/rolled-back** sessions older than
`keep_rejected_sessions_days`. Accepted history is guaranteed byte-identical across gc.

```yaml
gc:
  enabled: true
  grace_period_days: 14
  keep_autosaves_days: 14
  keep_rejected_sessions_days: 30
  quarantine: true
  quarantine_days: 7
  require_fsck_before_delete: true
fsck:
  strict: false
  verify_seals: true
  verify_object_hashes: true
  verify_reachability: true
  verify_timeline: true
  verify_renames: true
```

### Object inspection

`objects stats` (counts + bytes by type), `objects list [--reachable|--unreachable|--type]`,
and `objects show <id>` (type, size, references, reachability, seal status) expose the store
for operators.

---

## 14. Signed identity and trust (Phase 5)

Phase 4 answers "is the object store intact?" Phase 5 answers **"who created this work, who
approved it, and can that authorship be verified?"** — turning Checkpoint into an
audit-grade AI development protocol. Signatures use **Ed25519** (RFC 8032).

### Identities and keys

An **identity** is a human, AI agent, CI runner, machine, or service that can sign protocol
events. Public **IdentityRecords** live in `.checkpoint/identities/<id>.json`:

```json
{
  "identity_id": "id_human_4893dc9f88ea34dc",
  "name": "Jack", "type": "human",
  "public_key": "<hex 32 bytes>", "key_algorithm": "ed25519",
  "fingerprint": "SHA256:<hex>", "created_at": "...",
  "labels": [], "capabilities": ["sign", "accept", "merge", "tag"],
  "revoked": false, "revoked_at": null,
  "trusted": true, "metadata": {"email": "..."}
}
```

Private keys are raw 32-byte Ed25519 seeds stored under `.checkpoint/keys/<id>.key` with
`0600` permissions. They are **never** exported, **never** placed in bundles, **never**
captured by autosave (the whole `.checkpoint/` store is excluded from the working-tree
scan), and **never** seen by gc/fsck reachability (they are not objects). Secret scanning
flags private keys accidentally added to the working tree; `identity show`/fsck warn on
unsafe key-file permissions.

### Signatures (stored externally)

Signatures are **not** embedded in the immutable content-addressed object (that would
change its id and prevent post-hoc signing). They live under
`.checkpoint/signatures/<object_id>/<signature_id>.json` as **SignatureRecords**:

```json
{
  "signature_id": "sig_...", "signer_identity_id": "id_...",
  "signer_fingerprint": "SHA256:...", "algorithm": "ed25519",
  "signed_at": "...", "signed_object_type": "snapshot",
  "signed_object_id": "<sha256>", "canonicalization_version": 1,
  "protocol_version": "0.5", "signature": "<hex 64 bytes>",
  "public_key_hint": "<hex public key>"
}
```

### Canonicalization

The signed payload is a deterministic, canonical-JSON subset (sorted keys, UTF-8) of
**identity-affecting** fields only. It **excludes** bridge provenance, local paths, caches,
mtimes, and transient fsck/gc reports. For an accepted/merge snapshot:

```
{ canonicalization_version, protocol_version, signed_object_type:"snapshot",
  snapshot_id, tree_id, parent_ids, session_id, message,
  author_identity_id, acceptor_identity_id, verification, timestamp, seal_algorithm }
```

Verification **rebuilds** this payload from the current object and checks the signature, so
any change to message, tree, parents, session, or verification summary invalidates it —
while a change to `bridge` provenance does **not** (it is excluded). The integrity
**seal** (§6) and the Ed25519 **signature** are independent: the seal proves the object is
intact, the signature proves who accepted it.

### Trust store and policy

Trust is **local**: each IdentityRecord carries a `trusted` flag. Locally-created
identities are trusted; **imported identities start untrusted** (importing never implies
trust). Revocation is represented locally (`revoked`). Trust policy (`trust:` config) gates
acceptance:

```yaml
trust:
  require_signed_accepts: false      # accept must be signed
  require_trusted_acceptor: false    # acceptor must be locally trusted
  require_signed_merges: false
  require_signed_tags: true
  allow_unsigned_sessions: true
  allowed_acceptor_types: [human, ci]
  allowed_agent_accept: false        # agents cannot self-accept
  sign_snapshots: false              # also sign manual snapshots
```

### Default behavior and integration

- Signing is **available but not mandatory** by default. If a signing identity is active,
  `accept` and `merge` sign automatically; `--no-sign` opts out, `snapshot --sign` signs a
  manual snapshot. `start` records the active signing identity on the session.
- `verify-signatures` verifies every SignatureRecord; `trust-status` summarizes unsigned
  accepted snapshots and signatures by trusted/untrusted/unknown/revoked signers.
- `fsck --verify-signatures` includes signature findings; `fsck --require-signatures`
  **fails** on unsigned, invalid, or revoked-signer accepted snapshots; `--json` includes
  the findings.
- `packet` includes identity + signature metadata. **Bundles** carry the public identity
  records and signatures needed to verify the exported history — **never private keys** —
  and imported identities arrive untrusted.

Commands: `identity create|list|show|trust|untrust|revoke|import|export|current|use|set`,
`sign <snapshot>`, `verify-signatures`, `trust-status`.

---

## 15. Remote sync (Phase 6)

Checkpoint repositories exchange state between machines **without trusting the remote**. A
remote may advertise refs and object ids, but the receiver verifies object hashes, schemas,
seals, parent chains, reachability, and (optionally) signatures **before any ref moves**.
Remote types in this version are **filesystem** (a directory holding a Checkpoint store)
and **bundle** (a portable `.tar.gz`); the model is designed so HTTP remotes can be added
later. No Git is involved.

### Core rule: verify before refs move

- **Object transfer is content-addressed and verified.** Every received object's
  `sha256(bytes)` must equal its id, or it is skipped; the ref is not updated unless the
  full received closure verifies.
- **Local refs never move on receive until verification completes**; **remote refs never
  move until object transfer completes**. Ref writes are **atomic** (temp file → fsync →
  rename).
- A receiver rejects: objects whose id≠content, refs to missing/non-snapshot objects,
  broken parent chains, invalid seals, failed signatures (when required), private-key
  material, path traversal, and malformed manifests.

### Refs and tracking

- `fetch` copies objects and writes **remote-tracking refs** `refs/remotes/<remote>/<branch>`
  — it never changes local branch heads. Remote-tracking refs are part of gc reachability,
  so fetched-but-unmerged data is never collected.
- `pull` = fetch + verify, then **fast-forward** the local branch if safe, else refuse and
  instruct the user to `merge`. A ref update is **fast-forward** iff the old target is an
  ancestor of the new target through accepted-snapshot parent chains.
- `push` computes the objects the remote is missing, sends only those (verified), then
  atomically updates the remote ref. Non-fast-forward is **rejected by default**;
  `--force-with-lease[=<expected>]` succeeds only if the remote head still equals the
  expected value (the local remote-tracking ref by default).

### What transfers

Accepted history (snapshots/trees/blobs), the objects sessions reference (base trees,
intermediate snapshots, verification/packet trees), **signatures**, **public identities**
(imported **untrusted**), and selected session artifacts. **Never** transferred: private
keys (always), and **autosaves** unless explicitly enabled (`sync.transfer_autosaves` or a
flag). Bridge provenance remains non-identity-affecting and never invalidates signatures.

### Bundles

`bundle create` writes a portable archive (manifest, objects, refs, tags, sessions,
signatures, public identities, ledger subset) with a `manifest_hash`. `bundle verify`
extracts to a temp area and checks **path safety** (no absolute paths, no `..`, no escaping
symlinks), rejects **private-key material** (`keys/`, `*.key`, PEM private-key content),
parses the manifest, verifies object hashes, and verifies that refs/tags resolve to valid
accepted snapshots (and signatures when requested) — **before** anything is moved into the
store. `bundle import` runs that verification first and only then copies objects and writes
refs. `clone` accepts either a filesystem store or a bundle.

### Config

```yaml
remotes:
  origin: { type: filesystem, path: ../remote-repo, require_signed_snapshots: false }
sync:
  verify_before_ref_update: true
  require_fast_forward: true
  allow_force_push: false
  transfer_sessions: true
  transfer_autosaves: false
  transfer_verification_records: true
  transfer_packets: true
  transfer_public_identities: true
  max_bundle_size_mb: 500
```

Commands: `remote add|list|show|remove`, `fetch`, `pull`, `push`, `clone`,
`sync status`, `bundle create|verify|import`. `--dry-run` (fetch/pull/push) changes
nothing; `--json` is available on fetch/push/sync status/bundle verify. Sync events are
recorded in the ledger.

---

## 16. Policy engine (Phase 7)

Checkpoint should not just record what happened — it should **enforce what is allowed to
happen**. A deterministic policy engine runs before sensitive operations and records every
decision in the ledger. Policy is **opt-in**: with no policy configured
(`.checkpoint/policy.yaml` absent and no `policy:` config block) the engine is disabled and
nothing is enforced.

### Sensitive operations

`accept`, `merge`, `push` (incl. force / force-with-lease), `pull`, `bundle import`,
`tag`, `trust`/`revoke`, and `override`. The engine is also queryable read-only via
`policy check`/`explain` and run over history by `fsck --policy`.

### PolicyInput → PolicyDecision

The engine is a pure function of a **PolicyInput** (operation, actor identity + type,
branch, changed paths, risk tags, verification results, trust status, ref-update type,
remote/bundle metadata, override reason) and the policy. It returns a **PolicyDecision**:
`decision_id, timestamp, operation, effect ∈ {allow, deny, warn}, actor_identity_id,
rules_evaluated, rules_matched, reasons, required_actions, override_available,
override_used`. Evaluation is **deterministic** and **read-only**; callers record the
decision in the ledger (`policy` event).

### Rule model

- **actor_rules** gate capabilities per actor type (`can_accept`, `can_merge`, `can_push`,
  `can_override`, …). By default agents may start sessions and snapshot but **not
  self-accept**.
- **path_rules** (glob: `dir/`, `**`, `*.ext`) attach requirements to changed paths:
  `trusted_human_acceptor`, `signed_accept`, `verification: [...]`,
  `forbid_agent_self_accept`, `min_approvals`, `verification_optional`.
- **branch_rules** (glob, e.g. `release/*`) attach `signed_merge`, `fast_forward_only`,
  `trusted_acceptor`, `no_unsigned_history`, `verification`.
- **required_signatures** (accepts/merges/tags/remote_ref_updates) and
  **required_verification** (default + commands) apply globally.
- **remote_rules** govern push/pull (`require_fast_forward`, `allow_force_push`,
  `allow_force_with_lease`, `require_signed_snapshots`, `reject_unsigned_remote_history`).
- **override_rules** (`allow_override`, `require_reason`, `require_signature`,
  `allowed_identity_types`).

**Strictest wins**: when several rules match, their requirements are **unioned** (any
`True` wins, verification lists merge), so the most restrictive constraint applies. Path
globbing is deterministic. `default_effect: deny` means an operation with no permitting
actor rule is denied.

### Override

A denied operation may be overridden only if `override_rules.allow_override` is set, the
actor type is allowed (humans by default), a **reason** is supplied (`--override --reason`),
and — when an identity is active — the override is signed. The override and its reason are
recorded in the ledger (`override_used: true`).

### Integration

`accept` evaluates after verification (so results are known) and before the commit;
`merge` enforces protected-branch and signed-merge rules; `push` enforces fast-forward and
force policy; `pull` can refuse unsigned remote history; `bundle import` can reject unsigned
bundles; `trust`/`revoke` record a decision. The simple Phase-5 `trust:` acceptor gate is
**superseded by the policy engine** when a policy is present. `fsck --policy` evaluates
accepted history against the current policy and reports **policy violations separately**
from object corruption (they do not mark the store corrupt). Everything works with Git
uninstalled; the engine never imports Git.

Commands: `policy show | check [--operation] | explain [<decision-id>] | validate |
test <fixture> | init | audit`.

---

## 17. Conformance

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
8. Provides continuous, debounced, crash-safe autosaves that never become accepted
   history and never move a branch, with timeline and recovery (§12).
9. Detects renames natively and deterministically (exact, similar/rename+edit, directory)
   in diff, merge, and packets, bounded and configurable, without calling Git, and without
   altering content-addressed ids or seals (§4.1, §5.1).
10. Provides read-only **fsck** integrity checking and **gc** that deletes only unreachable,
    past-grace objects, never touching reachable/accepted history, runs fsck first, and
    quarantines before permanent deletion (§13).
11. Supports **Ed25519 signed identities and trust** (§14): signs accepts/merges with the
    active identity, verifies signatures by rebuilding a canonical payload that excludes
    bridge provenance, keeps private keys out of exports/autosave/gc, imports identities as
    untrusted, and enforces trust policy. Signatures are independent of integrity seals.
12. Performs **hardened remote sync** (§15) that never trusts the remote: content-verified
    transfer, fetch into remote-tracking refs, fast-forward-by-default pull, safe push with
    `--force-with-lease`, atomic ref updates, and bundle verification (path-safety,
    private-key rejection, manifest/seal/signature checks) — verifying everything before
    refs move and never transferring private keys.
13. Provides a deterministic, opt-in **policy engine** (§16) that enforces who/what may
    accept, merge, push, pull, tag, trust, and override — before the operation — records
    every decision in the ledger, supports reasoned signed overrides, and integrates with
    fsck; superseding the simple Phase-5 trust gate when configured.
14. Passes the test: **with Git uninstalled, all of the above — including the autosave
    daemon, timeline, recovery, rename detection, fsck, gc, signing/verification, remote
    sync, and the policy engine — still work.**
