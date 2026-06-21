"""Configuration for a Checkpoint Core repo."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

import yaml


def default_config(project: str = "") -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "default_branch": "main",
        "verification": {
            "run_on_accept": True,
            "commands": [],
        },
        "risk_rules": {
            "safety-critical": {
                "require_verification": True,
                "require_human_accept": True,
            },
        },
        "secrets": {"scan": True},
        "remotes": {},  # name -> {type: path|bundle, location: ...}
    }


_HEADER = """\
# Checkpoint Core configuration
# Docs: docs/checkpoint-core-protocol.md
#
# verification:
#   run_on_accept: true
#   commands:
#     - name: tests
#       run: pytest -q
# remotes:
#   origin:
#     type: path
#     location: /path/to/other/checkpoint/repo
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
        return cls(_deep_merge(default_config(), data), path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(_HEADER)
            fh.write(yaml.safe_dump(self.data, sort_keys=False, default_flow_style=False))

    # accessors
    def verification_commands(self) -> List[Dict[str, str]]:
        return [c for c in self.data.get("verification", {}).get("commands", []) or [] if c.get("run")]

    def run_on_accept(self) -> bool:
        return bool(self.data.get("verification", {}).get("run_on_accept", True))

    def secrets_scan(self) -> bool:
        return bool(self.data.get("secrets", {}).get("scan", True))

    def default_branch(self) -> str:
        return self.data.get("default_branch", "main")

    def remotes(self) -> Dict[str, Any]:
        return self.data.get("remotes", {}) or {}

    def risk_rules_for(self, tags: List[str]) -> Dict[str, Any]:
        rules = self.data.get("risk_rules", {}) or {}
        eff: Dict[str, Any] = {}
        for tag in tags or []:
            for k, v in (rules.get(tag, {}) or {}).items():
                eff[k] = eff.get(k, False) or v
        return eff


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
