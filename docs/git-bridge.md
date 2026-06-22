# Git Bridge & Safe Trial

Checkpoint Core is the source of truth. Git is supported **only** as an import/export bridge
— the only component that touches Git, loaded lazily, never imported by the core.

## Import an existing Git repo (read-only on Git)
    cd your-git-repo
    checkpoint-core init                 # creates .checkpoint/ ; Git is untouched
    checkpoint-core git-import .         # replay Git history into Checkpoint accepted snapshots
    checkpoint-core history              # now native Checkpoint history
Git history and your files are **not modified**. Checkpoint becomes the source of truth only
when you choose it.

## Export Checkpoint history to Git
    checkpoint-core git-export ./mirror  # replay accepted snapshots into a Git repo

## Safe-trial guidance
    checkpoint-core init --safe-git-adapter   # prints the safe steps when inside a Git repo

## The Git ADAPTER (`checkpoint`) — adoption wedge, not the foundation
A separate, thin layer that records sessions on top of an existing Git repo, where **Git
stays the source of truth** and `accept` creates a normal Git commit. Use it to try
Checkpoint ergonomics without migrating. Spec: [checkpoint-protocol.md](checkpoint-protocol.md).
The real protocol is **Checkpoint Core** (`checkpoint-core`).
