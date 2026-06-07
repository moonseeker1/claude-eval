"""Statistics analyzer — aggregates tool usage metrics across runs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .config import is_tool_tracked
from .models import (
    AnalysisReport,
    ModeStats,
    RunResult,
    ToolCall,
    ToolStats,
)


class Analyzer:
    """Computes aggregate statistics from RunResults."""

    def analyze(
        self,
        results: list[RunResult],
        tracked_tools: list[str],
        config_name: str = "",
        config_description: str = "",
        model: str = "",
        runs_per_mode: int = 0,
    ) -> AnalysisReport:
        """Build a full analysis report from raw results.

        Groups results by mode, then computes per-tool statistics
        filtered to tracked_tools patterns.
        """
        mode_groups: dict[str, list[RunResult]] = defaultdict(list)
        for r in results:
            mode_groups[r.mode].append(r)

        mode_stats: dict[str, ModeStats] = {}
        for mode_name, mode_results in sorted(mode_groups.items()):
            mode_stats[mode_name] = self._analyze_mode(mode_name, mode_results, tracked_tools)

        return AnalysisReport(
            config_name=config_name,
            config_description=config_description,
            model=model,
            runs_per_mode=runs_per_mode,
            tracked_tools=tracked_tools,
            mode_stats=mode_stats,
            raw_results=results,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _analyze_mode(
        self,
        mode_name: str,
        results: list[RunResult],
        tracked_tools: list[str],
    ) -> ModeStats:
        """Compute statistics for one mode across all its runs."""
        stats = ModeStats(mode_name=mode_name, runs_count=len(results))

        for result in results:
            stats.total_session_duration_ms += result.total_duration_ms
            for turn in result.turns:
                for call in turn.tool_calls:
                    if is_tool_tracked(call.tool_name, tracked_tools):
                        # Group by base tool name (strip parameterized suffixes)
                        tool_key = self._normalize_tool_name(call.tool_name)
                        if tool_key not in stats.tool_stats:
                            stats.tool_stats[tool_key] = ToolStats(tool_name=tool_key)
                        stats.tool_stats[tool_key].add_call(call)

        return stats

    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        """Normalize tool name for grouping.

        E.g. "mcp__knowledge-base__search" → "mcp__knowledge-base__search"
             "Bash" → "Bash"
        """
        return name

    def per_turn_summary(
        self,
        results: list[RunResult],
        tracked_tools: list[str],
    ) -> dict[str, list[dict]]:
        """Compute per-turn tool call counts grouped by mode.

        Returns: {mode_name: [{turn_index, prompt, tool_counts: {tool_name: count}}, ...]}
        """
        mode_groups: dict[str, list[RunResult]] = defaultdict(list)
        for r in results:
            mode_groups[r.mode].append(r)

        summary: dict[str, list[dict]] = {}
        for mode_name, mode_results in sorted(mode_groups.items()):
            # Collect all turns across runs, aligning by turn_index
            max_turns = max((len(r.turns) for r in mode_results), default=0)
            turn_summaries: list[dict] = []

            for turn_idx in range(max_turns):
                prompt = ""
                tool_counts: dict[str, list[int]] = defaultdict(list)

                for result in mode_results:
                    if turn_idx < len(result.turns):
                        turn = result.turns[turn_idx]
                        prompt = turn.prompt
                        for call in turn.tool_calls:
                            if is_tool_tracked(call.tool_name, tracked_tools):
                                tool_key = call.tool_name
                                tool_counts[tool_key].append(1)

                # Aggregate counts per tool
                agg_counts: dict[str, int] = {
                    k: sum(v) for k, v in tool_counts.items()
                }

                turn_summaries.append({
                    "turn_index": turn_idx,
                    "prompt": prompt,
                    "tool_counts": agg_counts,
                    "total_calls": sum(agg_counts.values()),
                })

            summary[mode_name] = turn_summaries

        return summary
