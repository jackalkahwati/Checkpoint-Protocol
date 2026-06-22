# Contributing to Checkpoint

Thanks for trying the preview. Contributions and bug reports are welcome.

## Dev setup
    python3 -m venv .venv && . .venv/bin/activate    # optional
    pip install -e ".[dev]"        # or just: pip install pytest pyyaml
    python -m pytest -q            # run the full suite

The core has **no required third-party dependencies** beyond PyYAML; `cryptography` is an
optional speed-up for Ed25519 (a pure-Python fallback ships in-tree). Please keep it that
way — the project's promise is *local-first, works with Git uninstalled*.

## Ground rules
- **Never import Git from the core.** Only `checkpoint_core/gitbridge.py` may shell out to git.
- **Never weaken protocol guarantees**: content-address everything; verify before refs move;
  never leak private keys.
- Add tests for new behavior; keep the no-Git tests passing.
- Run `bash scripts/release_check.sh` before opening a PR.

## Reporting bugs
Run `checkpoint-core bug-report --out report.tar.gz` and attach it (it redacts secrets and
**never** includes private keys or tokens). Include `checkpoint-core version --json` output.

## Code style
Match the surrounding code. Standard library first. Clear over clever.
