# Checkpoint Git-Adapter Specification

Version: 0.1 (MVP)
Status: Draft
Local metadata directory: `.checkpoint`

> **This document specifies the Git ADAPTER**, the adoption wedge that layers on top of an
> existing Git repository (here, Git is the source of truth). It is **not** the main
> protocol. The source-of-truth, Git-replacement protocol is **Checkpoint Core**, specified
> in [`checkpoint-core-protocol.md`](checkpoint-core-protocol.md). Read that first.

---

## 1. Purpose

The Checkpoint Protocol is an AI-native change-control layer built on top of Git.
It does **not** replace Git. Git remains the storage, branching, commit, merge, and
diff engine. Checkpoint controls the work that happens **between** commits, especially
when AI agents are modifying a codebase.

Git stores commits. Checkpoint Protocol controls the work that happens between commits.

The protocol must be able to answer, for any unit of work:

1. What did the human or AI try to do?
2. What prompt or instruction caused the work?
3. What files changed?
4. What changed between each meaningful state?
5. What checks passed or failed?
6. What state was last known good?
7. What work was accepted into Git history?
8. What work was rejected or rolled back?
9. Can the session be replayed, audited, exported, or recovered?

### Design principles

- **Local-first.** The first implementation works with no cloud service.
- **Git is the foundation.** Snapshots, diffs, and rollback are implemented with Git
  plumbing (tree objects, `diff`, `checkout-index`) rather than a re-implemented VCS.
- **Messy work is preserved continuously; only clean, human-approved work is promoted
  into Git history.** Autosaves and snapshots never become Git commits. `accept` is the
  only path that writes Git history.
- **Safe by default.** Destructive operations preview their effect and require explicit
  intent. Work is auto-snapshotted before any destructive rollback.
- **Append-only ledger.** Every state transition is recorded and never mutated in place.

---

## 2. Terminology

| Term | Definition |
|------|------------|
| **Repo** | The Git repository being managed. |
| **Session** | A unit of work started by a human or AI agent. |
| **Instruction** | The user's intent for the session (human-readable). |
| **Autosave** | A continuously captured file state used for recovery only. |
| **Snapshot** | A meaningful intermediate state used for comparison or rollback. |
| **Verification** | Tests, lint, type checks, builds, safety checks, or custom commands. |
| **Change Packet** | The final proposed change from a session: instruction, summary, diff, touched files, snapshots, verification results, risks, and a recommended commit message. |
| **Accept** | Promote the selected work into clean Git history (one Git commit). |
| **Rollback** | Return the repo to the session start, a prior snapshot, or the last accepted state. |
| **Ledger** | Append-only record of sessions, snapshots, checks, accepts, rejects, and rollbacks. |
| **Tree** | A Git tree object capturing the full non-ignored working-tree state at a point in time. |

---

## 3. Lifecycle

```
checkpoint init
        |
        v
checkpoint start "<instruction>"   --> session: active, base_tree captured
        |
        |  (human / AI edits files; optional autosaves)
        v
checkpoint snapshot --message "..." --> snapshot: tree + diff + file hashes
        |
checkpoint diff                     --> review changes
        |
checkpoint verify                   --> verification run stored
        |
checkpoint packet                   --> Change Packet generated
        |
        +--> checkpoint accept   --> Git commit, session: accepted, session closed
        |
        +--> checkpoint rollback --> restore working tree, session: rolled_back
        |
        +--> checkpoint reject   --> session: rejected (no Git write, auditable)
```

A session is **active**, then terminal: **accepted**, **rejected**, or **rolled_back**.
Only one session is active at a time in the MVP.

### State capture model (Git plumbing)

Checkpoint captures the working tree as a **Git tree object** using a temporary index
so the user's real index is never disturbed:

```
GIT_INDEX_FILE=.checkpoint/tmp/index git read-tree HEAD      # seed (if HEAD exists)
GIT_INDEX_FILE=.checkpoint/tmp/index git add -A -- . ':(exclude).checkpoint' <excludes>
GIT_INDEX_FILE=.checkpoint/tmp/index git write-tree          # -> tree SHA
```

The resulting tree SHA captures the full non-ignored working tree (including
uncommitted and untracked files, minus ignored paths). Diffs are `git diff <treeA> <treeB>`.
Rollback restores a tree with `read-tree` + `checkout-index`. These objects live in the
repo's normal Git object store as dangling objects; they never appear in history unless
referenced by an accepted commit.

---

## 4. Directory structure

```
.checkpoint/
  config.yaml                       # configuration
  ledger.jsonl                      # append-only event log (JSONL)
  state.json                        # pointer: active session id, schema version
  sessions/
    <session-id>/
      session.json                  # session metadata
      instruction.txt               # raw instruction / prompt
      snapshots/
        <snapshot-id>/
          snapshot.json             # snapshot metadata + file manifest
          diff.patch                # diff base_tree -> snapshot tree
          files/                    # (reserved) per-snapshot materialized files
      autosaves/
        <autosave-id>.json          # lightweight recovery records
      verification/
        <verification-run-id>.json  # verification run results
      packet.json                   # generated Change Packet
  objects/                          # content-addressed file blobs (sha256)
    <ab>/<full-sha256>              # deduplicated file contents for export/recovery
  cache/                            # derived/cacheable data
  tmp/                              # temporary git index files, scratch
```

`.checkpoint/` is added to `.gitignore` at `init` so internal state is never committed.

---

## 5. Schemas

All timestamps are ISO 8601 with timezone (UTC), e.g. `2026-06-21T14:30:12.123456+00:00`.
All IDs are stable, readable, and unique.

### 5.1 Identifiers

- **Session ID**: `cp_<YYYYMMDD>_<HHMMSS>_<slug>` where `slug` is a lowercased,
  underscore-joined, truncated form of the instruction.
  Example: `cp_20260621_143012_fix_camera_exposure`.
- **Snapshot ID**: `snap_<YYYYMMDD>_<HHMMSS>_<seq>` (seq is a 3-digit counter per session).
- **Autosave ID**: `auto_<YYYYMMDD>_<HHMMSS>_<seq>`.
- **Verification run ID**: `ver_<YYYYMMDD>_<HHMMSS>_<seq>`.
- **Event ID**: `evt_<YYYYMMDD>_<HHMMSS>_<6-hex>`.

### 5.2 Ledger event schema (`ledger.jsonl`, one JSON object per line)

```json
{
  "event_id": "evt_20260621_143012_a1b2c3",
  "event_type": "session_start",
  "session_id": "cp_20260621_143012_fix_camera_exposure",
  "timestamp": "2026-06-21T14:30:12.123456+00:00",
  "actor": { "type": "human", "name": "jack" },
  "git_branch": "main",
  "git_head": "9f1c2e7...",
  "payload": { }
}
```

`event_type` is one of:
`init`, `session_start`, `snapshot`, `autosave`, `verification`, `packet`,
`accept`, `reject`, `rollback`.

The ledger is **append-only**. Events are never edited or deleted. Correction is done by
appending a new event.

### 5.3 Session schema (`session.json`)

```json
{
  "schema_version": 1,
  "session_id": "cp_20260621_143012_fix_camera_exposure",
  "instruction": "fix camera exposure defaults without changing autonomy behavior",
  "status": "active",
  "created_at": "2026-06-21T14:30:12+00:00",
  "updated_at": "2026-06-21T14:35:00+00:00",
  "actor": { "type": "human", "name": "jack" },
  "agent": {
    "name": null, "model": null, "tool": null,
    "prompt": null, "response_summary": null,
    "files_touched": [], "commands_run": []
  },
  "git": {
    "base_branch": "main",
    "base_head": "9f1c2e7...",
    "base_tree": "4b825dc...",
    "base_clean": true,
    "accept_head": null
  },
  "risk_tags": ["hardware", "safety-critical"],
  "snapshots": ["snap_20260621_143300_001"],
  "autosaves": ["auto_20260621_143100_001"],
  "verifications": ["ver_20260621_143400_001"],
  "packet": "packet.json"
}
```

`actor.type` is `human` or `agent`. The `agent` block holds optional AI-agent metadata and
is present for both human and AI sessions (fields null when not applicable).

### 5.4 Snapshot schema (`snapshot.json`)

```json
{
  "snapshot_id": "snap_20260621_143300_001",
  "session_id": "cp_20260621_143012_fix_camera_exposure",
  "created_at": "2026-06-21T14:33:00+00:00",
  "message": "camera config updated",
  "git_branch": "main",
  "base_tree": "4b825dc...",
  "tree": "7c3a9f1...",
  "diff_path": "diff.patch",
  "changed_files": [
    { "path": "config/camera.yaml", "status": "M",
      "sha256": "e3b0c4...", "size": 1284, "object": "objects/e3/e3b0c4..." }
  ],
  "stats": { "files_changed": 1, "insertions": 4, "deletions": 2 }
}
```

`status` uses Git name-status codes: `A` added, `M` modified, `D` deleted, `R` renamed.
`sha256` is the content hash of the new file version (null for deletions). `object` is the
content-addressed path under `.checkpoint/objects/` (deduplicated).

### 5.5 Verification schema (`<verification-run-id>.json`)

```json
{
  "verification_run_id": "ver_20260621_143400_001",
  "session_id": "cp_20260621_143012_fix_camera_exposure",
  "created_at": "2026-06-21T14:34:00+00:00",
  "tree": "7c3a9f1...",
  "overall": "passed",
  "results": [
    {
      "name": "tests",
      "command": "pytest -q",
      "exit_code": 0,
      "status": "passed",
      "duration_seconds": 12.4,
      "stdout_summary": "... last lines ...",
      "stderr_summary": "",
      "started_at": "2026-06-21T14:34:00+00:00",
      "finished_at": "2026-06-21T14:34:12+00:00"
    }
  ]
}
```

`overall` is `passed` if all commands exit 0, otherwise `failed`. A run with no configured
commands is `skipped`. Per-result `status` is `passed`, `failed`, or `error` (could not run).

### 5.6 Change Packet schema (`packet.json`)

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-21T14:36:00+00:00",
  "session_id": "cp_20260621_143012_fix_camera_exposure",
  "instruction": "fix camera exposure defaults without changing autonomy behavior",
  "actor": { "type": "human", "name": "jack" },
  "agent": { "name": null, "model": null, "tool": null },
  "branch": "main",
  "base_commit": "9f1c2e7...",
  "current_commit": null,
  "base_tree": "4b825dc...",
  "current_tree": "7c3a9f1...",
  "changed_files": [ { "path": "config/camera.yaml", "status": "M" } ],
  "summary": "1 file changed, 4 insertions(+), 2 deletions(-)",
  "diff_ref": "sessions/<id>/snapshots/.../diff.patch | git diff <base_tree> <current_tree>",
  "snapshots": [ { "snapshot_id": "...", "message": "...", "created_at": "..." } ],
  "verification": { "overall": "passed", "runs": ["ver_..."] },
  "risks": ["safety-critical", "secrets-detected:0"],
  "recommended_commit_message": "fix camera exposure defaults",
  "recommended_next_action": "accept",
  "secret_findings": []
}
```

The packet never contains secret values. If secrets are detected, the packet records the
finding location and type only, and `recommended_next_action` becomes `review-secrets`.

---

## 6. Accept flow

1. Resolve the active session.
2. Run verification (unless `--no-verify` or `accept.require_verification: false`).
   - If any risk rule sets `require_verification: true`, verification is forced.
   - If verification fails and not overridden with `--force`, abort.
3. Secret scan the pending diff. If secrets are found and not `--force`, abort with the
   findings (values redacted).
4. Stage and commit the user-facing changes with Git:
   `git add -A` (`.checkpoint/` is gitignored) then `git commit -m <message>`.
   Use `--message` if provided, otherwise the packet's recommended commit message,
   otherwise the instruction.
   - Internal Checkpoint autosaves are **never** committed.
   - At most **one** commit is created per accept. Autosaves never produce commits.
5. Record the new `git_head` as `accept_head` in the session.
6. Append an `accept` ledger event.
7. Mark the session `accepted` and clear the active pointer.

If there is nothing to commit, accept aborts and reports that the working tree is clean.

---

## 7. Rollback flow

Targets: `--to-start` (default), `--to-snapshot <id>`, (future) `--to-accepted`.

1. Resolve the active session and the target tree
   (`base_tree` for start, snapshot `tree` for a snapshot).
2. Take an automatic **pre-rollback snapshot** so no work is ever lost.
3. Compute the change set (target tree vs current working tree).
4. **Preview by default.** Show files that would be restored, deleted, or kept.
   - Without `--hard` or `--yes`, stop here (dry run). Nothing is modified.
   - With `--yes`, restore tracked/modified/deleted files to the target; keep files added
     since the target unless `--hard`.
   - With `--hard`, restore the target tree exactly: restore modified/deleted files **and**
     delete files added since the target. No prompt.
   - With `--keep-files`, never delete added files (overrides the delete step).
5. Restore using Git plumbing:
   `read-tree <target>` into a temp index, then `checkout-index -a -f`; delete added files
   as required by the flags.
6. Append a `rollback` ledger event and mark the session `rolled_back`.

Because a pre-rollback snapshot is always taken, a rollback can itself be undone by
restoring that snapshot's tree.

---

## 8. Security model

Checkpoint must avoid recording or exporting secrets.

- **Ignore rules.** Ignored files are never captured. Capture respects `.gitignore`
  (via Git) and `.checkpointignore` (extra exclude pathspecs). `.checkpoint/` is always
  excluded and is added to `.gitignore` at init.
- **Secret scanning.** Before writing a packet or an export bundle, Checkpoint scans the
  pending diff and changed files for obvious secret patterns:
  - private keys (`-----BEGIN ... PRIVATE KEY-----`), SSH keys
  - `.env` files and `KEY=VALUE` secret-looking assignments
  - cloud credentials (AWS access key IDs `AKIA...`, `aws_secret_access_key`)
  - generic API keys / tokens / bearer tokens
  - high-entropy strings in credential-looking contexts
- **Redaction.** In **export** and **packet** artifacts, detected secret values are
  redacted (`***REDACTED***`) and the finding is recorded as `{file, line, type}` with no
  value. The user is warned. Detection is best-effort and never a guarantee.
- **No secrets in IDs or events.** Event payloads carry references (paths, hashes, ids),
  not file contents.

### Threat boundaries (MVP)

Checkpoint is a local trust domain: anyone with read access to `.checkpoint/` can read
captured file contents in `objects/`. Treat `.checkpoint/` like the working tree itself.
Secret redaction applies to **shareable** artifacts (export, packet), not to the local
recovery store.

---

## 9. Configuration (`config.yaml`)

```yaml
schema_version: 1
project: "my-repo"
actor:
  default_type: human          # human | agent
  default_name: jack
verification:
  run_on_accept: true
  commands:
    - name: tests
      run: npm test
    - name: lint
      run: npm run lint
    - name: typecheck
      run: npm run typecheck
risk_rules:
  safety-critical:
    require_verification: true
    require_human_accept: true
    require_clean_worktree: true
autosave:
  enabled: true                # captured opportunistically on command invocation in MVP
accept:
  commit_internal: false       # never commit .checkpoint internals
  require_verification: false  # global default; risk rules can force true
secrets:
  scan: true
```

Risk tags supported by convention: `docs`, `tests`, `refactor`, `UI`, `backend`,
`database`, `security`, `hardware`, `autonomy`, `safety-critical`.

---

## 10. Future cloud sync model (non-normative)

The local protocol is the source of truth. A future hosted service syncs by:

1. **Push.** Upload `ledger.jsonl` events (append-only, idempotent by `event_id`),
   session metadata, packets, and content-addressed `objects/` blobs (dedup by sha256).
2. **Pull.** Mirror remote sessions read-only for review/approval dashboards.
3. **Policy engine.** Server-side risk rules and required approvals enforced before an
   accept is permitted to write Git history.
4. **Audit.** The append-only ledger is the audit log; objects are content-addressed and
   verifiable.

Sync is layered on top; it does not change local semantics. The MVP implements none of
this — it only keeps the schemas stable and content-addressed so sync is possible later.

---

## 11. Conformance

An implementation conforms to Checkpoint Protocol 0.1 if it:

1. Stores state under `.checkpoint/` with the directory layout in §4.
2. Maintains an append-only JSONL ledger with the event schema in §5.2.
3. Produces sessions, snapshots, verification runs, and packets matching §5.3–§5.6.
4. Captures working-tree state as Git tree objects and computes diffs with Git.
5. Implements the accept flow (§6): at most one Git commit per accept; never commits
   `.checkpoint/` internals; never turns autosaves into commits.
6. Implements the rollback flow (§7): preview by default, auto pre-rollback snapshot.
7. Respects `.gitignore` and `.checkpointignore` (§8).
8. Scans for and redacts secrets in export and packet artifacts (§8).
