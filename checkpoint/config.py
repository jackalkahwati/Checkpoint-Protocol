"""Configuration: load/save .checkpoint/config.yaml with sane defaults."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

import yaml


def default_config(project: str = "") -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "actor": {
            "default_type": "human",
            "default_name": "",
        },
        "verification": {
            "run_on_accept": True,
            # Empty by default so the MVP does not assume a stack. Examples in docs.
            "commands": [],
        },
        "risk_rules": {
            "safety-critical": {
                "require_verification": True,
                "require_human_accept": True,
                "require_clean_worktree": True,
            },
        },
        "autosave": {
            "enabled": True,
        },
        "accept": {
            "commit_internal": False,
            "require_verification": False,
        },
        "secrets": {
            "scan": True,
        },
    }


_EXAMPLE_HEADER = """\
# Checkpoint Protocol configuration
# Docs: docs/checkpoint-protocol.md
#
# Add verification commands for your stack, for example:
#   verification:
#     run_on_accept: true
#     commands:
#       - name: tests
#         run: pytest -q
#       - name: lint
#         run: ruff check .
#       - name: typecheck
#         run: mypy .
"""


class Config:
    def __init__(self, data: Dict[str, Any], path: Path):
        self.data = data
        self.path = Path(path)

    @classmethod
    def load(cls, path: Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError("config not found: {}".format(path))
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        merged = _deep_merge(default_config(), data)
        return cls(merged, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump(self.data, sort_keys=False, default_flow_style=False)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(_EXAMPLE_HEADER)
            fh.write(body)

    # ------------------------------------------------------------- accessors
    def verification_commands(self) -> List[Dict[str, str]]:
        cmds = self.data.get("verification", {}).get("commands", []) or []
        return [c for c in cmds if c.get("run")]

    def run_on_accept(self) -> bool:
        return bool(self.data.get("verification", {}).get("run_on_accept", True))

    def secrets_scan(self) -> bool:
        return bool(self.data.get("secrets", {}).get("scan", True))

    def default_actor(self) -> Dict[str, str]:
        a = self.data.get("actor", {})
        return {
            "type": a.get("default_type", "human"),
            "name": a.get("default_name", ""),
        }

    def risk_rules_for(self, tags: List[str]) -> Dict[str, Any]:
        """Merge the rules of all matching risk tags into one effective rule set."""
        rules = self.data.get("risk_rules", {}) or {}
        effective: Dict[str, Any] = {}
        for tag in tags or []:
            for k, v in (rules.get(tag, {}) or {}).items():
                # any True wins for boolean gates
                effective[k] = effective.get(k, False) or v
        return effective


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
