# Hosted Server

Run Checkpoint repos over HTTP without weakening the protocol.

    checkpoint-server init-store .checkpoint-server
    checkpoint-server token create --store .checkpoint-server --name dev --scopes repo:read,repo:write
    checkpoint-server start --host 127.0.0.1 --port 8800
    checkpoint-server doctor --json
    checkpoint-server version

Full endpoint reference, auth model, transfer protocol, and security guarantees:
**[checkpoint-hosted-api.md](checkpoint-hosted-api.md)**.

The server is stdlib-only (no framework), serves the web UI at `/`, and works with Git
uninstalled. It is a developer-preview server: **no TLS** (front it with an HTTPS proxy),
local API-token auth only. See [security-model.md](security-model.md).
