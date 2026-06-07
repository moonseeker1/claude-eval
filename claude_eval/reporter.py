"""Markdown report generator for evaluation results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .analyzer import Analyzer
from .models import AnalysisReport


class Reporter:
    """Generates Markdown evaluation reports from AnalysisReport."""

    def __init__(self, analyzer: Analyzer | None = None):
        self.analyzer = analyzer or Analyzer()

    def generate(self, report: AnalysisReport, output_path: Path) -> Path:
        """Generate a Markdown report and write to file.

        Returns the path to the generated report.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sections = [
            self._header(report),
            self._overview_table(report),
            self._tracked_tool_detail(report),
            self._per_turn_table(report),
            self._other_tools_table(report),
        ]

        md = "\n\n".join(sections) + "\n"
        output_path.write_text(md, encoding="utf-8")
        return output_path

    def _header(self, report: AnalysisReport) -> str:
        """Report title and metadata."""
        model_line = f" | 模型: `{report.model}`" if report.model else ""
        lines = [
            f"# {report.config_name} — 评估报告",
            "",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 配置: `{report.config_description}`{model_line}",
            f"> 重复次数: {report.runs_per_mode} × {len(report.all_mode_names())} 模式",
            f"> 追踪工具: {', '.join('`' + t + '`' for t in report.tracked_tools)}",
        ]
        return "\n".join(lines)

    def _overview_table(self, report: AnalysisReport) -> str:
        """Overview comparison table: mode × key metrics."""
        modes = report.all_mode_names()
        if not modes:
            return "## 概览\n\n暂无数据。"

        # Header
        header = "| 指标 | " + " | ".join(modes) + " |"
        sep = "|------|" + "|".join(["------" for _ in modes]) + "|"

        # Determine tracked tool pattern prefix (for overview)
        kb_pattern = ""
        for t in report.tracked_tools:
            if "mcp" in t or "knowledge" in t:
                kb_pattern = t
                break

        rows: list[str] = []
        for label, extractor in self._overview_metrics(report, kb_pattern):
            values = []
            for mode_name in modes:
                ms = report.mode_stats.get(mode_name)
                values.append(extractor(ms))
            rows.append(f"| {label} | " + " | ".join(values) + " |")

        return "## 概览\n\n" + "\n".join([header, sep] + rows)

    @staticmethod
    def _overview_metrics(report: AnalysisReport, kb_pattern: str):
        """Define the rows for the overview table.

        Yields (label, extractor_fn) tuples where extractor takes a ModeStats.
        """
        # Total tracked tool calls
        yield "追踪工具总调用次数", lambda ms: (
            str(sum(ts.total_calls for ts in ms.tool_stats.values())) if ms else "-"
        )
        # Success rate
        yield "调用成功率", lambda ms: (
            _pct(_overall_success_rate(ms)) if ms else "-"
        )
        # Average duration
        yield "平均耗时(ms)", lambda ms: (
            f"{_overall_avg_duration(ms)}" if ms else "-"
        )
        # Total session duration
        yield "总会话耗时(s)", lambda ms: (
            f"{ms.avg_session_duration_s:.1f}" if ms else "-"
        )
        # Total tool calls (all)
        yield "总工具调用数", lambda ms: (
            str(sum(r.total_tool_calls for r in report.raw_results if r.mode == ms.mode_name))
            if ms else "-"
        )

    def _tracked_tool_detail(self, report: AnalysisReport) -> str:
        """Per-tool detailed statistics table."""
        modes = report.all_mode_names()
        all_tools = self._collect_tracked_tools(report)

        if not all_tools:
            return ""

        lines = ["## 追踪工具详细统计", ""]

        for tool_name in all_tools:
            header = f"| 模式 | 调用次数 | 成功 | 失败 | 成功率 | 平均耗时(ms) | 最小(ms) | 最大(ms) |"
            sep = "|------|---------|------|------|--------|-------------|---------|---------|"
            rows: list[str] = []

            for mode_name in modes:
                ms = report.mode_stats.get(mode_name)
                if ms and tool_name in ms.tool_stats:
                    ts = ms.tool_stats[tool_name]
                    rows.append(
                        f"| {mode_name} | {ts.total_calls} | {ts.success_count} "
                        f"| {ts.error_count} | {ts.success_rate:.0%} "
                        f"| {ts.avg_duration_ms:.0f} | {ts.min_duration_ms} "
                        f"| {ts.max_duration_ms} |"
                    )
                else:
                    rows.append(f"| {mode_name} | 0 | - | - | - | - | - | - |")

            lines.append(f"### `{tool_name}`")
            lines.append("")
            lines.append(header)
            lines.append(sep)
            lines.extend(rows)
            lines.append("")

        return "\n".join(lines)

    def _per_turn_table(self, report: AnalysisReport) -> str:
        """Per-turn tool call count table."""
        per_turn = self.analyzer.per_turn_summary(report.raw_results, report.tracked_tools)
        modes = report.all_mode_names()

        if not modes:
            return ""

        # Collect all turn indices
        all_turns: list[int] = []
        for mode_name in modes:
            for ts in per_turn.get(mode_name, []):
                if ts["turn_index"] not in all_turns:
                    all_turns.append(ts["turn_index"])
        all_turns.sort()

        if not all_turns:
            return ""

        lines = ["## 每轮对话工具调用明细", ""]
        header = "| 轮次 | " + " | ".join(modes) + " |"
        sep = "|------|" + "|".join(["------" for _ in modes]) + "|"

        rows: list[str] = []
        for turn_idx in all_turns:
            prompt = ""
            cells: list[str] = []
            for mode_name in modes:
                turn_data = per_turn.get(mode_name, [])
                if turn_idx < len(turn_data):
                    td = turn_data[turn_idx]
                    prompt = td["prompt"]
                    if td["total_calls"] > 0:
                        details = " ".join(f"{k}:{v}" for k, v in td["tool_counts"].items())
                        cells.append(f"✅ {td['total_calls']}次 ({details})")
                    else:
                        cells.append("❌ 0次")
                else:
                    cells.append("-")
            rows.append(f"| 第{turn_idx + 1}轮: \"{prompt[:30]}\" | " + " | ".join(cells) + " |")

        return "\n".join([lines[0], lines[1], header, sep] + rows)

    def _other_tools_table(self, report: AnalysisReport) -> str:
        """Statistics for non-tracked tools (auxiliary context)."""
        modes = report.all_mode_names()

        # Collect all non-tracked tool names
        other_tools: set[str] = set()
        for result in report.raw_results:
            for turn in result.turns:
                for call in turn.tool_calls:
                    if not any(call.tool_name.startswith(t.replace("*", "")) for t in report.tracked_tools if "*" in t) \
                       and call.tool_name not in report.tracked_tools:
                        other_tools.add(call.tool_name)

        if not other_tools:
            return ""

        # Count per mode
        counts: dict[str, dict[str, int]] = {m: {} for m in modes}
        for result in report.raw_results:
            for turn in result.turns:
                for call in turn.tool_calls:
                    if call.tool_name in other_tools:
                        counts[result.mode][call.tool_name] = counts[result.mode].get(call.tool_name, 0) + 1

        sorted_tools = sorted(other_tools)
        header = "| 工具 | " + " | ".join(modes) + " |"
        sep = "|------|" + "|".join(["------" for _ in modes]) + "|"
        rows: list[str] = []
        for tool in sorted_tools:
            cells = [str(counts[m].get(tool, 0)) for m in modes]
            rows.append(f"| {tool} | " + " | ".join(cells) + " |")

        return "## 其他工具调用统计\n\n" + "\n".join([header, sep] + rows)

    @staticmethod
    def _collect_tracked_tools(report: AnalysisReport) -> list[str]:
        """Collect all tool names that appear in tracked results, deduplicated."""
        tools: set[str] = set()
        for ms in report.mode_stats.values():
            tools.update(ms.tool_stats.keys())
        return sorted(tools)


def _overall_success_rate(ms) -> float:
    """Overall success rate across all tracked tools in a mode."""
    total_success = sum(ts.success_count for ts in ms.tool_stats.values())
    total_calls = sum(ts.total_calls for ts in ms.tool_stats.values())
    return (total_success / total_calls * 100) if total_calls else 0


def _pct(value: float) -> str:
    """Format a percentage value to a readable string."""
    return f"{value:.1f}%"


def _overall_avg_duration(ms) -> str:
    """Overall average duration across all tracked tools in a mode."""
    total_dur = sum(ts.total_duration_ms for ts in ms.tool_stats.values())
    total_calls = sum(ts.total_calls for ts in ms.tool_stats.values())
    if not total_calls:
        return "-"
    avg = total_dur / total_calls
    if avg >= 60000:
        return f"{avg / 1000:.1f}s ({avg:.0f}ms)"
    return f"{avg:.0f}"
