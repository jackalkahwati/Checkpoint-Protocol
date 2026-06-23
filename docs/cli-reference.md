# CLI Reference

Run any command with `--help` for full flags. Three entry points:
`checkpoint-core` (the VCS), `checkpoint-server` (hosted API + UI), `checkpoint` (Git adapter).

## checkpoint-core

### Lifecycle
| Command | Purpose |
|---|---|
| `init [--branch --name --email --safe-git-adapter]` | Initialize a repo (no Git). |
| `setup [--server --token --owner --name --remote-name --no-policy]` | One-shot: init + identity + `.checkpointignore` + server repo + remote + policy (idempotent). |
| `claude "<task>" [--model --no-tests --no-launch --decision --tag --autopilot --json --login]` | One-verb agent run: session → autosave → launch Claude → tests → packet → one summary → accept/rollback. `--autopilot` adds Owner Agent review + auto-accept/escalate. |

### Personal autopilot (v1.2)
`personal init|status|daily` · `autopilot claude "<task>"|review [mr_N --decision approve|merge]|explain|status|config` ·
`backup init <dir>|run|status|restore`. Owner Agent reviews AI work (sessions and MRs) and
auto-accepts low-risk changes or escalates; reviews are persisted/ledgered/signed and
`autopilot explain` shows the reasoning. See [personal-autopilot.md](personal-autopilot.md),
[owner-agent.md](owner-agent.md), [backup.md](backup.md), [daily-workflow.md](daily-workflow.md).
| `identity create\|list\|show\|trust\|untrust\|revoke\|import\|export\|current\|use\|set` | Ed25519 identities + local trust. |
| `start "<instruction>" [--actor --agent --model --tool --tag]` | Begin a session. |
| `status` | Active session: changes, last autosave/snapshot, verification. |
| `snapshot [-m --sign]` | Mark a meaningful snapshot. |
| `diff [--summary --files --from --to --no-renames]` | Rename-aware diff. |
| `verify` | Run configured verification commands. |
| `packet [--json]` | Generate the Change Packet. |
| `accept [-m --no-verify --no-sign --force --override --reason]` | Sealed, signed, policy-checked accept. |
| `reject [--reason --yes]` / `rollback [--to-snapshot --hard --keep-files --yes]` | Close / restore safely. |
| `log [--status]` / `history` / `show <session-id>` | Session list / accepted history / detail. |

### Autosave / recovery
`watch [--debounce-ms --poll-ms]` · `autosave list\|show\|restore\|gc` · `timeline [<sid>]` · `recover [--restore --to --yes]`

### Branches / merge
`branch [<name>]` · `checkout <name>` · `merge <name> [--override --reason]`

### Integrity / signing / policy
`fsck [--strict --json --verify-signatures --require-signatures --policy]` ·
`gc [--dry-run --aggressive --force]` ·
`objects stats\|list\|show` · `verify-history` ·
`sign <snapshot>` · `verify-signatures` · `trust-status` ·
`policy init\|show\|check\|explain\|validate\|test\|audit`

### Merge requests (scriptable review — talks to the hosted remote)
`mr create --title "…" --from <branch> [--to main] [--snapshot|--session]` ·
`mr list` · `mr show <id>` · `mr status <id>` · `mr diff <id>` ·
`mr comment <id> [--file --line] --body "…"` · `mr approve <id>` · `mr unapprove <id>` ·
`mr merge <id>` · `mr close <id>` ·
`mr review <id> [--decision approve|merge|diff|comment|quit]` (one-screen terminal review).
Uses the `checkpoint`/`origin` http remote (or `--remote <name>`).

### Remotes / sync
`remote add\|list\|show\|remove` (filesystem or `http://host/owner/repo --token`) ·
`fetch` · `pull` · `push [--force-with-lease]` · `clone <src> <dest> [--token]` ·
`sync status <remote>` · `bundle create\|verify\|import`

### Git bridge
`git-import <dir>` · `git-export <dir>`

### v1.0 ops
`version [--json]` · `doctor [--json]` · `bug-report [--out --include-objects]` ·
`migrate status\|plan\|apply` · `agent begin\|status\|packet`

## checkpoint-server

| Command | Purpose |
|---|---|
| `init-store [path]` | Initialize a server store. |
| `start [--host --port --store]` | Start the API + web UI. |
| `token create\|revoke\|list [--name --scopes --repo --store]` | Manage API tokens. |
| `doctor [--json --store]` / `version [--json]` | Diagnostics / versions. |

Endpoint reference: [checkpoint-hosted-api.md](checkpoint-hosted-api.md).

## checkpoint (Git adapter)
Thin session layer on top of an existing Git repo (Git stays the source of truth):
`init` · `start` · `snapshot` · `diff` · `verify` · `packet` · `accept` · `rollback` ·
`log` · `show` · `export` · `doctor`. See [checkpoint-protocol.md](checkpoint-protocol.md).
