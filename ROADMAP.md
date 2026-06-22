# Roadmap

Shipped (tagged):
- v0.1 core VCS · v0.2 autosave/recovery · v0.3 rename-aware merge · v0.4 integrity+GC
- v0.5 signed identity & trust · v0.6 remote sync · v0.7 policy engine
- v0.8 hosted API · v0.9 web review UI · **v1.0-preview public developer preview**

Next (post-preview, not committed):
- Agent integrations: first-class adapters for Claude Code, Codex, Cursor, OpenClaw/Hermes.
- Server hardening: TLS guidance, rate limiting, multi-process locking, optional DB backend.
- Identity/trust: at-rest key encryption, key rotation, signed audit/receipts, optional PKI.
- Scale: object batching/streaming, packfiles, incremental fsck, large-repo tuning.
- Merge: optional line-merge upgrades; rename + content conflict ergonomics.
- Product: comments/review threads, org accounts, hosted cloud — explicitly later.

Principle: do not expand the core until the preview is easy to install, demo, and explain.
