# Backup

Personal, filesystem-based backup of your accepted history — built on the existing verified
sync machinery. **Never transfers private keys.** Autosaves are not backed up by default.

```bash
checkpoint-core backup init <dir>     # initialize + register a filesystem backup remote
checkpoint-core backup run            # push accepted history + sessions + signatures +
                                      # public identities + tags to the backup (verified)
checkpoint-core backup status         # last sync, ahead/behind, fsck, signatures
checkpoint-core backup restore        # preview; re-run with --yes to fast-forward from backup
```

- **No private keys** ever leave the machine (only public identities transfer).
- Backup **verifies** object hashes, seals, parents, and signatures before accepting data
  (same as any remote sync — never trust the remote).
- `restore` previews first and only mutates with `--yes`; it fast-forwards (refuses on
  divergence). `fsck` passes after a restore.
- Point the backup at an external drive, a synced folder, or another machine path.

`checkpoint-core personal init --backup-path <dir>` configures this in one step.
