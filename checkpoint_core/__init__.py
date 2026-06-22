"""Checkpoint Core: a Git-replacement version-control protocol for human + AI-generated
code. Sessions, snapshots, diffs, verification, accepts, branches, merges, signing, remote
sync, and policy are native objects/operations. Git is only an import/export bridge.

If Git disappeared, Checkpoint Core would still work.
"""

__version__ = "1.0.0-preview"
PROTOCOL_VERSION = "1.0"
STORE_VERSION = 1
SCHEMA_VERSION = 1

# Capabilities advertised by `version` / the hosted API.
FEATURES = [
    "sessions", "autosave", "rename-aware-merge", "fsck", "gc",
    "signed-identity", "trust", "remote-sync", "policy", "hosted-api", "web-ui",
    "git-bridge", "no-git",
]
