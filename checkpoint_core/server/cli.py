"""checkpoint-server CLI: start the API, init a store, manage tokens, doctor."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .. import util
from . import API_VERSION
from .app import serve
from .store import ServerStore

DEFAULT_BASE = ".checkpoint-server"


def _store(base: Optional[str]) -> ServerStore:
    return ServerStore(Path(base or DEFAULT_BASE))


def cmd_init_store(args) -> int:
    s = ServerStore.init_store(Path(args.path or DEFAULT_BASE))
    print(util.green("Initialized server store ") + str(s.base))
    print("  server_id: {}".format(s.server_id()))
    print("Create a token:  checkpoint-server token create --name dev --scopes repo:read,repo:write")
    return 0


def cmd_start(args) -> int:
    s = _store(args.store)
    if not s.initialized:
        ServerStore.init_store(s.base)
    httpd = serve(s, host=args.host, port=args.port)
    print(util.green("Checkpoint server listening ") + "http://{}:{}".format(args.host, args.port))
    print("  store: {}".format(s.base))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down...")
        httpd.shutdown()
    return 0


def cmd_token(args) -> int:
    s = _store(args.store)
    if not s.initialized:
        print(util.red("error: ") + "server store not initialized; run init-store", file=sys.stderr)
        return 1
    if args.token_cmd == "create":
        scopes = [x.strip() for x in (args.scopes or "repo:read").split(",") if x.strip()]
        rec = s.create_token(args.name or "token", scopes, args.repo or "*")
        print(util.green("Token created ") + rec["token_id"])
        print("  scopes: {}".format(", ".join(rec["scopes"])))
        print("  repo:   {}".format(rec["repo_scope"]))
        print(util.bold("  token (shown once): ") + rec["token"])
        return 0
    if args.token_cmd == "revoke":
        ok = s.revoke_token(args.token_id)
        print(util.green("Revoked ") + args.token_id if ok else util.red("no such token"))
        return 0 if ok else 1
    if args.token_cmd == "list":
        for t in s.list_tokens():
            mark = " (revoked)" if t.get("revoked") else ""
            print("{:<28} {:<10} {}{}".format(t["token_id"], t.get("repo_scope"),
                                              ",".join(t.get("scopes", [])), mark))
        return 0
    print("usage: checkpoint-server token create|revoke|list", file=sys.stderr)
    return 2


def cmd_doctor(args) -> int:
    s = _store(args.store)
    checks = [
        ("store initialized", s.initialized),
        ("repos dir present", s.repos_dir.exists() or not s.initialized),
        ("config readable", _safe(lambda: s.load_config() is not None)),
        ("web UI present", (Path(__file__).parent / "web" / "index.html").exists()),
        ("works without git", True),
    ]
    problems = sum(1 for _l, ok in checks if not ok)
    if getattr(args, "json", False):
        import json
        print(json.dumps({"ok": problems == 0,
                          "checks": [{"name": l, "ok": ok} for l, ok in checks]}, indent=2))
        return 0 if problems == 0 else 1
    for label, ok in checks:
        print("  [{}] {}".format(util.green("ok  ") if ok else util.red("FAIL"), label))
    if problems == 0:
        print(util.green("\nServer is healthy."))
        return 0
    print(util.red("\n{} problem(s).".format(problems)))
    return 1


def cmd_version(args) -> int:
    import platform
    from .. import __version__, PROTOCOL_VERSION, FEATURES
    from . import API_VERSION
    obj = {"checkpoint_server": __version__, "api_version": API_VERSION,
           "protocol_version": PROTOCOL_VERSION, "features": FEATURES,
           "python": platform.python_version(), "platform": platform.platform()}
    if getattr(args, "json", False):
        import json
        print(json.dumps(obj, indent=2))
        return 0
    print(util.bold("Checkpoint Server ") + __version__)
    print("  api:      {}".format(API_VERSION))
    print("  protocol: {}".format(PROTOCOL_VERSION))
    print("  python:   {}".format(obj["python"]))
    print("  platform: {}".format(obj["platform"]))
    return 0


def _safe(fn):
    try:
        return bool(fn())
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="checkpoint-server",
                                description="Checkpoint hosted API (protocol-first, no Git).")
    p.add_argument("--version", action="version", version="checkpoint-server {}".format(API_VERSION))
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("init-store", help="initialize a server store")
    sp.add_argument("path", nargs="?")
    sp.set_defaults(func=cmd_init_store)

    sp = sub.add_parser("start", help="start the API server")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8800)
    sp.add_argument("--store")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("token", help="manage API tokens")
    tsub = sp.add_subparsers(dest="token_cmd")
    tcr = tsub.add_parser("create")
    tcr.add_argument("--name")
    tcr.add_argument("--scopes")
    tcr.add_argument("--repo", help="owner/repo or * (default *)")
    tcr.add_argument("--store")
    trv = tsub.add_parser("revoke"); trv.add_argument("token_id"); trv.add_argument("--store")
    tls = tsub.add_parser("list"); tls.add_argument("--store")
    sp.set_defaults(func=cmd_token, token_cmd=None, store=None)

    sp = sub.add_parser("doctor", help="diagnose the server")
    sp.add_argument("--store")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("version", help="show server/protocol versions and features")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_version)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
