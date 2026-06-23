# Merge Requests & Review

GitHub reviews commits; Checkpoint reviews **work sessions** — and merge requests are how a
team reviews and lands that work without stepping on each other.

A **merge request (MR)** proposes merging a session's accepted snapshot into a target branch.
It carries a diff, a mergeability check, a review thread (comments, optionally pinned to a
file/line), approvals, and a policy decision. Merging is **server-side, signed, and atomic**.

## The loop

1. **Open** an MR from a reviewed session (Repo → **Merge requests** → *New merge request* →
   pick an accepted session + target branch).
2. **Review** — read the rename-aware diff; leave **inline comments** (hover a line → `+`) or
   file/general comments; resolve threads.
3. **Approve** — reviewers approve; the policy engine can require N approvals
   (`min_approvals`) before a merge is allowed.
4. **Merge** — when there are no conflicts and policy allows, click **Merge**. The server
   creates a signed merge snapshot (by a per-repo *reviewer* identity; its key never leaves
   the server) and advances the target ref atomically under a per-repo lock — the same
   verify-before-move discipline as push. Conflicts are reported (the target is never moved);
   resolve locally with `checkpoint-core merge` and push, then refresh.

## Guarantees

- **No clobbering.** Merges are atomic, fast-forward-aware, and rejected on conflict — two
  reviewers can't destroy each other's work.
- **Signed history.** The merge snapshot is Ed25519-signed and SHA-256 sealed like any
  accepted snapshot.
- **Governed.** Policy is evaluated with the *source work's* actor type — human-authored,
  trusted, signed work can be one-click merged; agent-authored work is gated exactly as the
  policy says. `min_approvals` is enforced on merge.

## API (under the hosted server's `/ui/*` adapter)

```
GET  /ui/repos/{o}/{r}/reviews                      list MRs
POST /ui/repos/{o}/{r}/reviews                      create {title, source_session|source_snapshot, target_branch}
GET  /ui/repos/{o}/{r}/reviews/{id}                 detail: diff + mergeability + policy + signatures + comments + approvals
POST /ui/repos/{o}/{r}/reviews/{id}/comments        {body, path?, line?}
POST /ui/repos/{o}/{r}/reviews/{id}/comments/{cid}/resolve   {resolved}
POST /ui/repos/{o}/{r}/reviews/{id}/approve         {approve}
POST /ui/repos/{o}/{r}/reviews/{id}/merge           -> merged | conflicts(409) | policy-denied(403)
POST /ui/repos/{o}/{r}/reviews/{id}/close
```

## CLI (scriptable — for agents and terminals)

The whole loop is available from the CLI (talks to your `checkpoint`/`origin` http remote):

```bash
checkpoint-core mr create --title "Fix sync" --from agent/fix-sync --to main
checkpoint-core mr list
checkpoint-core mr review mr_1        # one-screen: source/target, files, policy, approvals, conflicts, signatures
                                      # [a] approve  [m] merge  [d] diff  [c] comment  [q] quit
checkpoint-core mr approve mr_1
checkpoint-core mr comment mr_1 --file app.py --line 12 --body "rename this"
checkpoint-core mr merge mr_1         # server-signed, conflict-aware, atomic
```

For agents/automation, every step has a non-interactive command (and `mr review --decision
merge`), so the Owner Agent / policy pipeline can drive review and merge without the web UI.

## Limits (preview)

- Comments anchor to a file/line; merge is **line-level** (diff3), not semantic.
- The server is single-process (per-repo locks make concurrent merges safe; not horizontally
  scaled). See [`../ROADMAP.md`](../ROADMAP.md).
