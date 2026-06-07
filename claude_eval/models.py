"""Data models for the Claude Code eval framework."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ToolCall:
    """A single tool invocation extracted from transcript."""

    tool_name: str
    tool_use_id: str
    input: dict
    output: str
    duration_ms: int = 0
    is_error: bool = False
    timestamp: str = ""

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "input": self.input,
            "output": self.output[:500],  # truncate for readability
            "duration_ms": self.duration_ms,
            "is_error": self.is_error,
            "timestamp": self.timestamp,
        }


@dataclass
class TurnResult:
    """Results from a single conversation turn."""

    turn_index: int
    prompt: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    timestamp: str = ""

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    def calls_by_tool(self, tool_name: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.tool_name == tool_name]

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "prompt": self.prompt,
            "tool_call_count": self.tool_call_count,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
        }


@dataclass
class RunResult:
    """Results from a single evaluation run (one mode × one repetition)."""

    mode: str
    run_index: int
    session_id: str = ""
    turns: list[TurnResult] = field(default_factory=list)
    total_duration_ms: int = 0
    started_at: str = ""
    finished_at: str = ""

    @property
    def total_tool_calls(self) -> int:
        return sum(t.tool_call_count for t in self.turns)

    @property
    def duration_s(self) -> float:
        return self.total_duration_ms / 1000.0

    def calls_by_tool(self, tool_name: str) -> list[ToolCall]:
        return [c for t in self.turns for c in t.tool_calls if c.tool_name == tool_name]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "run_index": self.run_index,
            "session_id": self.session_id,
            "total_duration_ms": self.total_duration_ms,
            "total_tool_calls": self.total_tool_calls,
            "turns": [t.to_dict() for t in self.turns],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> RunResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = []
        for td in data["turns"]:
            calls = []
            for cd in td["tool_calls"]:
                calls.append(ToolCall(
                    tool_name=cd["tool_name"],
                    tool_use_id=cd["tool_use_id"],
                    input=cd["input"],
                    output=cd.get("output", ""),
                    duration_ms=cd.get("duration_ms", 0),
                    is_error=cd.get("is_error", False),
                    timestamp=cd.get("timestamp", ""),
                ))
            turns.append(TurnResult(
                turn_index=td["turn_index"],
                prompt=td["prompt"],
                tool_calls=calls,
            ))
        return cls(
            mode=data["mode"],
            run_index=data["run_index"],
            session_id=data.get("session_id", ""),
            turns=turns,
            total_duration_ms=data.get("total_duration_ms", 0),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
        )


@dataclass
class ToolStats:
    """Aggregated statistics for a single tool across runs."""

    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration_ms: int = 0
    min_duration_ms: int = 0
    max_duration_ms: int = 0
    durations: list[int] = field(default_factory=list)

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total_calls if self.total_calls else 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_calls if self.total_calls else 0

    def add_call(self, call: ToolCall) -> None:
        self.total_calls += 1
        if call.is_error:
            self.error_count += 1
        else:
            self.success_count += 1
        self.total_duration_ms += call.duration_ms
        self.durations.append(call.duration_ms)
        if not self.min_duration_ms or call.duration_ms < self.min_duration_ms:
            self.min_duration_ms = call.duration_ms
        if not self.max_duration_ms or call.duration_ms > self.max_duration_ms:
            self.max_duration_ms = call.duration_ms


@dataclass
class ModeStats:
    """Aggregated statistics for a single mode across runs."""

    mode_name: str
    runs_count: int = 0
    tool_stats: dict[str, ToolStats] = field(default_factory=dict)
    total_session_duration_ms: int = 0

    @property
    def avg_session_duration_s(self) -> float:
        return (self.total_session_duration_ms / self.runs_count / 1000) if self.runs_count else 0


@dataclass
class AnalysisReport:
    """Full analysis report containing per-mode statistics."""

    config_name: str = ""
    config_description: str = ""
    model: str = ""
    runs_per_mode: int = 0
    tracked_tools: list[str] = field(default_factory=list)
    tracked_bash_patterns: list[str] = field(default_factory=list)
    # {mode_name: {pattern: ToolStats}}
    bash_pattern_stats: dict[str, dict[str, ToolStats]] = field(default_factory=dict)
    mode_stats: dict[str, ModeStats] = field(default_factory=dict)
    raw_results: list[RunResult] = field(default_factory=list)
    generated_at: str = ""

    def all_mode_names(self) -> list[str]:
        return list(self.mode_stats.keys())

    def all_tool_names(self) -> list[str]:
        names: set[str] = set()
        for ms in self.mode_stats.values():
            names.update(ms.tool_stats.keys())
        return sorted(names)
