# The /checkpoint concierge

`/checkpoint` is the simplest way to work: call it in any repo, it inspects the state, tells
you where things stand, and recommends the next move — and you can always type your own.

Backed by `checkpoint-core next` (the skill calls `checkpoint-core next --json`).

## New repo

```
/checkpoint
```
- Not initialized → it offers to set up Checkpoint (local first).
- Never pushed → *"This repo has not been pushed or backed up yet. Set up the first
  push/backup now?"* — **only with your yes**. If yes, it configures a remote or a local
  backup (`~/CheckpointBackups/<repo>`), pushes accepted history (no private keys, no
  autosaves), verifies, and records `first_push_done`.

After that it won't ask about first push again (unless the remote goes missing).

## Daily

```
/checkpoint
```
shows a short summary and the best next move:

```
Checkpoint Summary
  Repo: checkpoint-protocol   Branch: main   Status: clean
  Last accepted: v1.1 MR CLI
  Open sessions: 0   Open MRs: 1
  Policy: active   Signatures: valid   Backup: current   Integrity: healthy

Suggested next directions:
  1. Resume the open session     2. Start a new Claude task
  3. Review open merge request   4. Daily status
  5. Back up / sync now          6. Open web review UI
  7. Type my own direction
```

It prioritizes: **resume** an open session → **review** a waiting MR (clean repo) → **backup**
if behind → otherwise **start a new task**. Dirty work with no session is surfaced, not hidden.

## Commands behind it

```
checkpoint-core next [--json]      # state + recommended action (the concierge brain)
checkpoint-core first-push [--yes] [--status]   # one-time push/backup setup
checkpoint-core web                # print/open the web review UI URL
checkpoint-core claude --continue  # resume the open session with Claude
checkpoint-core personal daily     # today's activity
```

Guarantees: never pushes without confirmation; first push excludes private keys and autosaves;
backup is verified after push and before restore; you can always choose local-only.
