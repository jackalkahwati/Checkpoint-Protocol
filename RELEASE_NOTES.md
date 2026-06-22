# Checkpoint v1.0.0-preview — Release Notes

**Checkpoint is AI-native version control.** Git stores commits; Checkpoint records the
whole work session — the prompt, autosaves, snapshots, verification, policy, and
signatures — and promotes only reviewed, signed, policy-approved work into clean history.

This is a **public developer preview**: the protocol and tooling are complete and tested
end-to-end, and the focus of this release is install/demo/docs quality, not new features.

## Install (5 minutes)

    pip install -e .
    checkpoint-core --help
    checkpoint-server --help

Or run from source with `export PATH="$PWD/bin:$PATH"`. See `docs/quickstart.md`.

## Try it

    bash examples/demo_all.sh        # six demos: core, autosave, rename-merge, policy, remote, hosted+UI

## Highlights since v0.1
core VCS → autosave/recovery → rename-aware merge → integrity+GC → signed trust →
remote sync → policy engine → hosted API → web review UI. **Works with Git uninstalled.**

## Known limitations (honest)
- Public preview, **not** a production cloud service.
- Hosted server is a local/stdlib HTTP server: **no TLS** (put it behind a TLS proxy),
  **local API-token auth only**, in-process per-repo locking (single-process).
- No OAuth / accounts / orgs; no comments / review threads.
- No semantic merge; merge is line-level (diff3) with file-level fallback.
- No large-repo optimization yet (object batches are JSON/base64; full rescans on fsck/gc).
- Trust is **local** (no PKI / global registry / web of trust).
- Web UI is a first-pass vanilla-JS app.
- The `checkpoint` Git **adapter** is a compatibility bridge, not the foundation; the
  foundation is **Checkpoint Core** (`checkpoint-core`).

## Security
See `SECURITY.md`. In short: private keys never leave the machine, never enter bundles/
exports/autosaves/bug-reports; the MVP server has no TLS and stores tokens hashed.
