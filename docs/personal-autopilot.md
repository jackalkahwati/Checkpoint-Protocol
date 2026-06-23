# Personal Autopilot

Checkpoint can run a **personal AI-owned development loop**:

> Claude writes code. The **Owner Agent** reviews it from your perspective. **Policy** decides
> what the AI may accept. **Low-risk** changes auto-accept. **Risky** changes escalate to you.
> History stays clean, signed, recoverable, and synced.

This is for one power user replacing GitHub in daily AI-assisted development — not an
enterprise system. It is conservative by default: only low-risk docs/tests/examples/markdown
changes auto-accept; everything else recommends or escalates until you loosen it.

## Quickstart

```bash
checkpoint-core personal init
checkpoint-core claude "Update the README" --autopilot
checkpoint-core personal daily
checkpoint-core backup run
```

## The autopilot command

```bash
checkpoint-core claude "<task>" --autopilot      # or: checkpoint-core autopilot claude "<task>"
```

It: starts a tracked session → launches Claude Code (safe default invocation) → autosaves →
runs verification → builds the packet → runs **policy check** → runs the **Owner Agent
review** → **auto-accepts** if low-risk and policy allows, else **escalates** → runs
`fsck` + `verify-signatures` + backup + push after acceptance → shows one final screen.

Low-risk result:

```
  Claude changed 1 file(s) (+3 -0).

  Tests:        passed
  Policy:       allowed
  Owner Agent:  approved
  Risk:         low
  Action:       auto-accepted
  History:      signed + sealed
  Backup:       synced

  Accepted Snapshot: 0e9aca045f6e
```

Risky result:

```
  Claude changed 1 file(s) (+1 -0).

  Tests:        passed
  Policy:       human required
  Owner Agent:  escalate
  Risk:         high
  Reason:       touched protected path(s): checkpoint_core/policy/engine.py

  [a] accept manually   [r] rollback   [d] diff   [p] packet   [q] quit
```

Non-interactive modes: `--decision auto` (let policy decide), `--decision escalate` (never
auto-accept, only review), `--decision rollback-on-fail` (roll back if verification fails),
`--json` (machine-readable summary).

## Commands

```
checkpoint-core personal init|status|daily
checkpoint-core autopilot claude "<task>" | review | status | config
checkpoint-core backup init <dir> | run | status | restore
```

See [owner-agent.md](owner-agent.md), [backup.md](backup.md),
[daily-workflow.md](daily-workflow.md).

## Honest limits

- The **Owner Agent is deterministic** (rule-based, bounded by your config + the policy
  engine) — not an LLM. That's a feature: it can't be prompt-injected, can't loosen policy,
  can't trust identities, can't approve the builder's own work.
- Merge is **line-level** (diff3), not semantic.
- The server is **single-process/local** (no TLS, no accounts). Autopilot is for one power
  user. See [../ROADMAP.md](../ROADMAP.md).
