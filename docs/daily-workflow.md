# Daily Workflow

The terminal-native, AI-owned loop for one power user:

```bash
checkpoint-core personal init                       # once
checkpoint-core claude "Fix the bug" --autopilot    # AI writes -> Owner Agent reviews -> accept or escalate
checkpoint-core personal daily                       # what happened today
checkpoint-core backup run                            # back up accepted history
```

`checkpoint-core personal daily` shows today's:

```
Today (2026-06-23)
  Sessions started: 5
  Accepted:         3  (auto-accepted: 1)
  Escalated:        1
  Rolled back:      1
  Open sessions:    2
  Backup:           configured
  Integrity:        healthy
  Signatures:       valid
  Latest accepted:  0e9aca045f6e
  Branch:           main
```

For team review of a branch, use merge requests ([reviews.md](reviews.md)):
`checkpoint-core mr create --from <branch>` → `checkpoint-core mr review <id>`.

Plain English: Claude writes code, the Owner Agent reviews it, policy decides if the AI can
accept it, low-risk changes auto-accept, risky changes escalate to you, history stays clean,
and Checkpoint syncs/backs up and can recover from mistakes.
