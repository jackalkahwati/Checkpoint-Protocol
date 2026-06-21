# Checkpoint Protocol

**A local-first, Git-compatible, AI-native change-control layer.**
Checkpoint continuously captures coding sessions, prompts, diffs, snapshots, and
verification results, then promotes only human-approved work into clean Git commits.

Git stores commits. **Checkpoint controls the work that happens between commits** —
especially when AI agents are modifying your codebase.

![status: MVP](https://img.shields.io/badge/status-MVP-blue)
![python: 3.8+](https://img.shields.io/badge/python-3.8%2B-3776ab)
![built on: Git](https://img.shields.io/badge/built%20on-Git-f05032)
![license: MIT](https://img.shields.io/badge/license-MIT-green)

```text
checkpoint init → start "<intent>" → (edit) → snapshot → diff → verify → packet
                                                                            │
                                                          ┌─────────────────┼─────────────────┐
                                                       accept             rollback           reject
                                                  (clean Git commit)  (safe restore)     (auditable, no commit)
```

## Contents

- [What Checkpoint is](#what-checkpoint-is)
- [Why it exists](#why-it-exists)
- [Core philosophy](#core-philosophy)
- [How it relates to Git](#how-it-relates-to-git)
- [Install](#install)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [How sessions work](#how-sessions-work)
- [Configuring verification commands](#configuring-verification-commands)
- [How to ignore files](#how-to-ignore-files)
- [Secrets](#secrets)
- [Directory layout](#directory-layout)
- [The protocol](#the-protocol)
- [Roadmap](#roadmap)

---

## What Checkpoint is

Checkpoint is a CLI and protocol that sits on top of Git. It records the messy,
in-progress reality of a coding session (what was attempted, what prompt drove it,
what files changed, what checks passed) and gives you one clean decision at the end:
**accept** the work into Git history, or **roll it back** safely.

It is **not** a new version-control system. It does not replace Git, GitHub, branching,
merging, or diffing. It does not turn every keystroke into a commit. Git remains the
foundation; Checkpoint is the control layer for AI-generated change.

## Why it exists

AI agents change a lot of code, fast. Between two commits an agent might rewrite ten
files, run three commands, and leave you unsure what actually happened or whether it's
safe to keep. Traditional Git only sees the before and after — the messy middle, the
prompt that caused it, and the verification status are all lost.

Checkpoint answers, for any unit of work:

1. What did the human or AI try to do?
2. What prompt or instruction caused the work?
3. What files changed, and what changed between each meaningful state?
4. What checks passed or failed?
5. What state was last known good?
6. What work was accepted into Git history? What was rejected or rolled back?
7. Can the session be replayed, audited, exported, or recovered?

## Core philosophy

- The human should never lose work.
- The human should never lose control.
- The repo history should stay clean.
- AI work should be traceable.
- Every meaningful change should be recoverable.
- Accepted work becomes normal Git history. Rejected work stays auditable without
  polluting the repo.
- Git remains the foundation. Checkpoint is the control layer for AI-generated change.

---

## How it relates to Git

| Concern | Owned by |
|---|---|
| Storage, branching, merging, diffing, commits | **Git** |
| The work between commits: sessions, prompts, intermediate states, verification, accept/rollback decisions | **Checkpoint** |

Checkpoint captures working-tree states as **Git tree objects** (using a temporary
index so your real index is never touched) and computes all diffs with Git itself. It
never re-implements Git logic. Internal Checkpoint state lives in `.checkpoint/`, which
is added to `.gitignore` at init so it never enters your history.

### Why autosaves are not commits

- **Autosaves** are continuous, for recovery only. They never enter Git history.
- **Snapshots** are meaningful intermediate states, for comparison and rollback. Also
  never Git commits.
- **Commits** are official history, created only by `checkpoint accept` — at most one
  commit per accept, never one-per-autosave, never garbage commits.

---

## Install

Requires Python 3.8+ and Git.

```bash
# Option A: run from the repo (no install)
export PATH="$PWD/bin:$PATH"        # makes `checkpoint` available
checkpoint --version

# Option B: pip install (provides the `checkpoint` entry point)
pip install -e .
```

Or call the module directly: `python -m checkpoint <command>`.

---

## Quick start

```bash
cd your-git-repo
checkpoint init

checkpoint start "fix camera exposure defaults without changing autonomy behavior"

# ... you or an AI agent edit files ...

checkpoint snapshot --message "camera config updated"
checkpoint diff
checkpoint verify
checkpoint packet
checkpoint accept --message "fix camera exposure defaults"
```

If the work was bad instead:

```bash
checkpoint rollback          # preview what would change (safe, non-destructive)
checkpoint rollback --hard   # restore the repo to session start
```

---

## Command reference

| Command | What it does |
|---|---|
| `checkpoint init` | Initialize Checkpoint in the current Git repo (creates `.checkpoint/`, config, ignore rules, gitignore entry). |
| `checkpoint start "<instruction>"` | Start a session; records branch, HEAD, and a baseline working-tree tree. Flags: `--tag`, `--agent`, `--model`, `--tool`, `--actor`, `--prompt-file`. |
| `checkpoint status` | Show the active session, changed files, last autosave/snapshot, verification status, and worktree state. |
| `checkpoint snapshot [-m MSG]` | Capture a meaningful intermediate state (tree + diff + per-file hashes). |
| `checkpoint diff` | Diff session start → now. Flags: `--summary`, `--files`, `--from <snap>`, `--to <snap>`. |
| `checkpoint verify` | Run configured verification commands; store exit codes, durations, output summaries. |
| `checkpoint packet [--json]` | Generate the Change Packet (instruction, diff, snapshots, verification, risks, recommended commit message + next action). |
| `checkpoint accept [-m MSG]` | Verify + secret-scan, then create **one clean Git commit** of the session delta. Flags: `--no-verify`, `--force`. |
| `checkpoint rollback` | Preview by default. `--yes` restores, `--hard` restores to start and deletes added files, `--keep-files`, `--to-snapshot <id>`. |
| `checkpoint reject [--reason ...]` | Close a session without committing; stays auditable. |
| `checkpoint log [--status S]` | List sessions: `active*`, `accepted`, `rejected`, `rolled_back`. |
| `checkpoint show <session-id>` | Full session detail: snapshots, verification runs, ledger events. |
| `checkpoint export <session-id>` | Portable, secret-redacted `.tar.gz` bundle. Flag: `--out`. |
| `checkpoint doctor` | Diagnose the installation (Git, config, ignore rules, permissions, session state). |

---

## How sessions work

A **session** is one unit of work with a human-readable **instruction**. Starting a
session records the current branch, the current Git HEAD, and a baseline tree of your
working directory. From then on, every snapshot and diff is measured against that
baseline. A session ends when you **accept**, **reject**, or **roll back**. Only one
session is active at a time.

Session IDs are stable and readable, e.g.
`cp_20260621_143012_fix_camera_exposure`.

### Starting a session

```bash
checkpoint start "<instruction>"
checkpoint start "<instruction>" --tag safety-critical --tag hardware
# AI agent session with metadata:
checkpoint start "refactor planner" --agent claude-code --model opus-4.8 --tool Edit
```

Risk tags (`docs`, `tests`, `refactor`, `UI`, `backend`, `database`, `security`,
`hardware`, `autonomy`, `safety-critical`) drive extra accept-time rules (see config).

### Reviewing changes

```bash
checkpoint status                 # active session, changed files, last autosave/snapshot, verify status
checkpoint diff                   # full diff from session start to now
checkpoint diff --summary         # diffstat only
checkpoint diff --files           # changed file names only
checkpoint diff --from <snap> --to <snap>
checkpoint snapshot -m "message"  # capture a meaningful intermediate state
```

### Verifying changes

Configure commands in `.checkpoint/config.yaml`, then:

```bash
checkpoint verify
```

Results (exit code, duration, stdout/stderr summary, timestamps) are stored per run and
referenced by the Change Packet. Verification runs automatically before `accept` unless
disabled.

### Accepting changes

```bash
checkpoint accept                         # uses recommended commit message
checkpoint accept --message "my message"  # explicit message
checkpoint accept --no-verify             # skip verification (unless a risk rule forces it)
checkpoint accept --force                 # override verify/secret/risk gates
```

Accept runs verification, scans for secrets, then creates **one clean Git commit**
containing exactly the session's changes (pre-existing unrelated dirty files are left
alone). The session is marked `accepted` and closed.

### Rolling back bad AI work

```bash
checkpoint rollback                       # PREVIEW only — shows what would change
checkpoint rollback --yes                 # restore modified/deleted files; keep new files
checkpoint rollback --hard                # restore exactly to session start (also deletes new files)
checkpoint rollback --keep-files          # never delete files added during the session
checkpoint rollback --to-snapshot <id> --hard
```

Rollback is **safe by default**: with no flags it only previews. Before any destructive
restore it takes an automatic **pre-rollback snapshot**, so a rollback can itself be
undone (`checkpoint show <session>` lists the snapshot to recover from).

### History, inspection, export

```bash
checkpoint log                    # all sessions: active*, accepted, rejected, rolled_back
checkpoint log --status accepted
checkpoint show <session-id>      # full detail: snapshots, verification runs, ledger events
checkpoint export <session-id>    # portable, secret-redacted .tar.gz bundle
checkpoint reject --reason "..."  # close session without committing (stays auditable)
checkpoint doctor                 # diagnose the installation
```

---

## Configuring verification commands

Edit `.checkpoint/config.yaml`:

```yaml
verification:
  run_on_accept: true
  commands:
    - name: tests
      run: pytest -q
    - name: lint
      run: ruff check .
    - name: typecheck
      run: mypy .
```

Any shell command works (`npm test`, `cargo test`, `go test ./...`, `make test`, ...).

### Risk rules

```yaml
risk_rules:
  safety-critical:
    require_verification: true     # force verify before accept
    require_human_accept: true     # an agent actor cannot self-accept
    require_clean_worktree: true   # no merge conflicts allowed at accept
```

Tag a session with `--tag safety-critical` to activate the matching rule.

---

## How to ignore files

- Checkpoint respects your **`.gitignore`** automatically (capture uses Git).
- Add a **`.checkpointignore`** (gitignore-style globs) for paths Checkpoint should
  never capture even if Git would track them:

  ```
  *.log
  tmp/
  build/
  ```

- `.checkpoint/` itself is always excluded and is added to `.gitignore` at init.

## Secrets

Before writing a **packet** or an **export** bundle, Checkpoint scans for obvious secret
patterns (private keys, SSH keys, `.env` files, AWS/Google/Slack/GitHub tokens, JWTs,
`KEY=value` secret assignments). `accept` refuses to commit when secrets are detected
(override with `--force`). Export bundles have detected secret **values redacted**;
findings are recorded as `{file, line, type}` with no value. Detection is best-effort,
not a guarantee.

---

## How to export a session

```bash
checkpoint export cp_20260621_143012_fix_camera_exposure --out session.tar.gz
```

The bundle contains session metadata, instruction, snapshots and their diffs,
verification results, the packet, this session's ledger events, and the referenced
content-addressed file blobs — all secret-redacted, with a `manifest.json`.

---

## Directory layout

```
.checkpoint/
  config.yaml            # configuration
  ledger.jsonl           # append-only event log
  state.json             # active-session pointer
  sessions/<id>/
    session.json         # session metadata
    instruction.txt      # raw instruction / prompt
    snapshots/<id>/      # snapshot.json + diff.patch
    autosaves/           # lightweight recovery records
    verification/        # per-run results
    packet.json          # generated Change Packet
  objects/               # content-addressed file blobs (dedup by sha256)
  cache/  tmp/
```

---

## The protocol

The full specification is in [`docs/checkpoint-protocol.md`](docs/checkpoint-protocol.md):
purpose, terminology, lifecycle, event/session/snapshot/verification/packet schemas,
accept and rollback flows, the security model, and the future cloud-sync model. It is
written to be implementable by an independent client.

## Roadmap

1. **Phase 1 (this MVP):** local CLI + protocol spec.
2. **Phase 2:** background autosave daemon (the protocol is already designed for it).
3. **Phase 3:** agent integrations (Cursor, Claude Code, Codex, Copilot, local agents).
4. **Phase 4:** hosted Checkpoint service.
5. **Phase 5:** web UI for sessions, diffs, prompts, verification, approvals, rollback.
6. **Phase 6:** team workflow, policy engine, compliance, audit, enterprise controls.

## Development

```bash
pip install -e . pytest pyyaml
python -m pytest -q
```

## License

MIT.
