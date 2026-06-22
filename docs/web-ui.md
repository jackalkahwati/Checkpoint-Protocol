# Web Review UI

GitHub reviews commits. Checkpoint reviews **work sessions**. The UI is served by
`checkpoint-server` at `/` — open it and paste an API token.

    checkpoint-server start --port 8800
    open http://127.0.0.1:8800/

Layout, panels (timeline, rename-aware diff, policy, signatures/trust, verification,
integrity), routes, and design notes: **[checkpoint-web-ui.md](checkpoint-web-ui.md)**.
Walkthrough: [../examples/web_review_demo.md](../examples/web_review_demo.md).

## Two UIs ship with Checkpoint

1. **Embedded UI** (at `/`) — a zero-build, dependency-free vanilla-JS SPA served by
   `checkpoint-server`. No Node toolchain; works offline. Best for quick/local review.
2. **Next.js review UI** (`../frontend/`) — a richer React 19 + Tailwind app (`pnpm dev`,
   :3000). It talks to the server's **`/ui/*` backend-for-frontend adapter** (CORS enabled)
   and falls back to mock data when offline. See `../frontend/README.md`.

Both consume the same hosted API; the `/ui/*` adapter returns the exact types the Next app
expects, so the protocol-shaped endpoints used by the CLI stay unchanged.
