# CLI Reference

Run any command with `--help` for full flags. Three entry points:
`checkpoint-core` (the VCS), `checkpoint-server` (hosted API + UI), `checkpoint` (Git adapter).

## checkpoint-core

### Lifecycle
| Command | Purpose |
|---|---|
| `init [--branch --name --email --safe-git-adapter]` | Initialize a repo (no Git). |
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
