# Web Review UI

GitHub reviews commits. Checkpoint reviews **work sessions**. The UI is served by
`checkpoint-server` at `/` — open it and paste an API token.

    checkpoint-server start --port 8800
    open http://127.0.0.1:8800/

Layout, panels (timeline, rename-aware diff, policy, signatures/trust, verification,
integrity), routes, and design notes: **[checkpoint-web-ui.md](checkpoint-web-ui.md)**.
Walkthrough: [../examples/web_review_demo.md](../examples/web_review_demo.md).
