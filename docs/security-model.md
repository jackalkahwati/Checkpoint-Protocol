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

## Owner Agent (personal autopilot) invariants

The Owner Agent is **deterministic** (rule-based, not an LLM) and bounded by your config +
the policy engine. Enforced: the Owner Agent is a **separate identity** from the Builder
(the Builder never self-approves); it **cannot override or loosen policy** (policy denial
always escalates); it **cannot trust identities**; it auto-accepts/auto-merges only when the
config allow-list **and** policy both permit; it cannot auto-merge failed tests, unresolved
comments, conflicts, or unsigned/untrusted history when policy requires signatures. Auto-accept
and auto-merge are ledgered and signed where possible. Backups never include private keys. See
[owner-agent.md](owner-agent.md).
