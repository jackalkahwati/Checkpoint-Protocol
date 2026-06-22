# FAQ

**Is this replacing Git?**
Checkpoint Core is a *Git-replacement protocol* — its own content-addressed object store
and history, designed for human + AI work. You don't have to switch: import a Git repo,
try it alongside, or use the thin Git *adapter*. But the core is the source of truth and
doesn't need Git.

**Does it work without Git?**
Yes — that's a hard guarantee, tested in CI. The core never imports Git; only the
`git-import`/`git-export` bridge touches it. Run `bash scripts/release_check.sh` to see the
no-Git subset pass.

**Can I use it with GitHub?**
Yes. `checkpoint-core git-import .` pulls a Git repo's history into Checkpoint (read-only on
Git); `checkpoint-core git-export ./mirror` writes Checkpoint history back to a Git repo you
can push to GitHub. See [git-bridge.md](git-bridge.md).

**Why are autosaves not commits?**
Commits should be reviewed, signed, meaningful history. Autosaves are a continuous safety
net for the messy middle. Keeping them separate is how Checkpoint stays recoverable *and*
keeps history clean. See [concepts.md](concepts.md).

**How does this help with AI agents?**
An agent's output is a *work session* (prompt → many edits → tests → retries), not one
commit. Checkpoint records the whole session, lets a human review it as a unit, and enforces
that a human/CI — not the agent — signs the accept. See [agent-integration.md](agent-integration.md).

**What happens if an agent makes a mess?**
`checkpoint-core rollback --hard` restores the last accepted state; the autosaves remain for
recovery; and the policy engine likely blocked the bad accept in the first place.

**How do signatures work?**
Identities are Ed25519 keypairs (`identity create`). `accept`/`merge` sign the snapshot,
binding its tree/parents/session/message/verification. `verify-signatures` checks them;
`trust-status` summarizes trusted/untrusted/unknown/revoked. Private keys never leave your
machine. See [security-model.md](security-model.md).

**Is this production-ready?**
It's a **public developer preview**. The protocol and tooling are complete and tested
end-to-end. The *hosted server* is for local/trusted-network use (no TLS, local token auth);
front it with HTTPS before exposing it. See `RELEASE_NOTES.md` for honest limitations.

**What data leaves my machine?**
Nothing, unless you push to a remote or run the server. Sync transfers verified objects +
public identities + signatures — **never private keys**, and autosaves only if you opt in.
`bug-report` redacts secrets and excludes keys/tokens.

**Can I self-host it?**
Yes — `checkpoint-server start` runs the API + web UI from the standard library. See
[server.md](server.md). There's no required cloud service.
