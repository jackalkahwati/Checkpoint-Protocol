# Security Model

Authoritative policy: **[../SECURITY.md](../SECURITY.md)**.

Protocol-level guarantees (see [checkpoint-core-protocol.md](checkpoint-core-protocol.md)):

- **Integrity** (§6, §13): every object is content-addressed (SHA-256); accepted snapshots
  carry a tamper-evident seal; `fsck` verifies the whole graph.
- **Authorship** (§14): Ed25519 signatures bind tree/parents/session/message/verification to
  a signer; private keys never leave `.checkpoint/keys/` (never exported/bundled/autosaved/
  collected/bug-reported).
- **Never trust the remote / client** (§15, §17): both sides verify hashes, seals, parents,
  signatures, and policy before refs move; bundles reject path traversal and key material.
- **Governance** (§16): the policy engine enforces who/what may change history, with audit.

Preview caveats: no TLS in the bundled server, local token auth, local trust only. Front
the server with HTTPS and use scoped tokens.
