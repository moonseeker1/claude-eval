"""Configuration loading and validation for eval tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

import yaml


@dataclass
class ModeConfig:
    """Configuration for a single evaluation mode."""

    name: str
    description: str = ""
    setup: list[str] = field(default_factory=list)
    turns: list[str] = field(default_factory=list)

    @property
    def total_turns(self) -> int:
        return len(self.setup) + len(self.turns)


@dataclass
class EvalConfig:
    """Top-level evaluation configuration."""

    name: str = "Untitled Eval"
    description: str = ""
    tracked_tools: list[str] = field(default_factory=list)
    modes: list[ModeConfig] = field(default_factory=list)
    runs_per_mode: int = 1
    claude_args: dict = field(default_factory=dict)

    @property
    def model(self) -> str:
        return self.claude_args.get("model", "")

    @property
    def max_turns(self) -> int | None:
        return self.claude_args.get("max_turns")

    def get_mode(self, name: str) -> ModeConfig | None:
        for mode in self.modes:
            if mode.name == name:
                return mode
        return None

    @property
    def total_runs(self) -> int:
        return len(self.modes) * self.runs_per_mode


def tool_matches_pattern(tool_name: str, pattern: str) -> bool:
    """Check if a tool name matches a glob pattern (e.g. 'mcp__kb__*')."""
    return fnmatch(tool_name, pattern)


def is_tool_tracked(tool_name: str, tracked_tools: list[str]) -> bool:
    """Check if a tool name matches any tracked tool pattern."""
    return any(fnmatch(tool_name, pattern) for pattern in tracked_tools)


def load_config(path: Path | str) -> EvalConfig:
    """Load and validate an eval configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping, got {type(raw).__name__}")

    modes = []
    for m in raw.get("modes", []):
        if not isinstance(m, dict):
            raise ValueError("Each mode must be a mapping")
        if "name" not in m:
            raise ValueError("Each mode must have a 'name' field")
        modes.append(ModeConfig(
            name=m["name"],
            description=m.get("description", ""),
            setup=m.get("setup", []),
            turns=m.get("turns", []),
        ))

    # Validate: all modes should have the same turn count
    turn_counts = {mode.name: len(mode.turns) for mode in modes}
    if len(set(turn_counts.values())) > 1:
        raise ValueError(
            f"Modes have different turn counts: {turn_counts}. "
            "All modes should have the same number of business turns."
        )

    tracked = raw.get("tracked_tools", [])
    if not tracked:
        raise ValueError("'tracked_tools' must not be empty — define at least one tool pattern to track")

    config = EvalConfig(
        name=raw.get("name", "Untitled Eval"),
        description=raw.get("description", ""),
        tracked_tools=tracked,
        modes=modes,
        runs_per_mode=raw.get("runs_per_mode", 1),
        claude_args=raw.get("claude_args", {}),
    )

    return config
