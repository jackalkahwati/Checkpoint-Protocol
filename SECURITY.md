# Security Policy

## Reporting
Email the maintainer or open a private security advisory on GitHub. Include
`checkpoint-core version --json` and, if safe, a `checkpoint-core bug-report` bundle
(it redacts secrets and excludes private keys/tokens by design).

## Preview security model (read this)
This is a **developer preview**. The hosted server is intended for **local / trusted-network
use behind your own TLS-terminating proxy.**

- **No TLS** in the bundled server. Do not expose it directly to the internet; front it with
  HTTPS (nginx/caddy) if you must.
- **API tokens** are bearer tokens stored **hashed (SHA-256)** server-side. The web UI stores
  the token in **browser localStorage** on the user's device (a warning is shown). Use scoped,
  short-lived tokens; log out to clear.
- **Private keys** (Ed25519 seeds) live only in `.checkpoint/keys/` at `0600`. They are
  **never** exported, bundled, transferred, autosaved, garbage-collected, or included in
  bug-reports. `identity show` / fsck warn on unsafe key-file permissions.
- **Never trust the remote / never trust the client.** Both sides verify object hashes,
  schemas, seals, parent chains, signatures, and policy before refs move. Bundle import
  rejects path traversal, absolute paths, escaping symlinks, and private-key material.
- **Secret scanning** runs before packets/exports/bug-reports; obvious secrets are redacted
  (best-effort, not a guarantee — don't commit secrets).
- **Trust is local** (no PKI). Imported identities arrive untrusted.

## Not yet in scope
OAuth, accounts/orgs, RBAC beyond token scopes, signed audit transport, at-rest key
encryption, rate limiting. These are planned post-preview.
