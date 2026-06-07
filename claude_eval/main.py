"""CLI entry point for the Claude Code eval framework."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import Analyzer
from .config import load_config
from .models import RunResult
from .reporter import Reporter
from .runner import ClaudeRunner


def cmd_run(args: argparse.Namespace) -> None:
    """Run an evaluation: execute sessions and generate report."""
    config = load_config(args.config)

    runner = ClaudeRunner()
    results_dir = Path(args.output) / "results"
    results = runner.run_all(
        config=config,
        output_dir=results_dir,
        mode_filter=args.mode,
    )

    # Analyze and report
    analyzer = Analyzer()
    report = analyzer.analyze(
        results=results,
        tracked_tools=config.tracked_tools,
        config_name=config.name,
        config_description=config.description,
        model=config.model,
        runs_per_mode=config.runs_per_mode,
    )

    reporter = Reporter(analyzer=analyzer)
    report_path = Path(args.output) / f"{config.name}-report.md"
    reporter.generate(report, report_path)

    print(f"\n[DONE] Report saved to: {report_path}")


def cmd_report(args: argparse.Namespace) -> None:
    """Generate a report from existing result JSON files."""
    results_dir = Path(args.results)
    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}")
        sys.exit(1)

    # Load config if available
    config = None
    if args.config:
        config = load_config(args.config)

    # Load all result JSON files
    results: list[RunResult] = []
    for json_file in sorted(results_dir.glob("*.json")):
        try:
            results.append(RunResult.load(json_file))
        except Exception as e:
            print(f"Warning: Failed to load {json_file}: {e}")

    if not results:
        print("No result files found.")
        sys.exit(1)

    tracked_tools = config.tracked_tools if config else _infer_tracked_tools(results)
    name = config.name if config else "Eval"
    description = config.description if config else ""
    model = config.model if config else ""
    runs_per_mode = config.runs_per_mode if config else 1

    analyzer = Analyzer()
    report = analyzer.analyze(
        results=results,
        tracked_tools=tracked_tools,
        config_name=name,
        config_description=description,
        model=model,
        runs_per_mode=runs_per_mode,
    )

    reporter = Reporter(analyzer=analyzer)
    output = args.output or f"{name}-report.md"
    report_path = reporter.generate(report, Path(output))
    print(f"[DONE] Report saved to: {report_path}")


def _infer_tracked_tools(results: list[RunResult]) -> list[str]:
    """Infer tracked tools from result data when no config is available."""
    tools: set[str] = set()
    for r in results:
        for t in r.turns:
            for c in t.tool_calls:
                tools.add(c.tool_name)
    return sorted(tools)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-eval",
        description="Claude Code evaluation framework — transcript-based tool usage analysis.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run subcommand
    run_parser = sub.add_parser("run", help="Run evaluation sessions and generate report")
    run_parser.add_argument(
        "-c", "--config",
        required=True,
        help="Path to YAML eval configuration",
    )
    run_parser.add_argument(
        "-o", "--output",
        default="./output",
        help="Output directory for results and report (default: ./output)",
    )
    run_parser.add_argument(
        "-m", "--mode",
        default=None,
        help="Only run this specific mode (e.g. 'skill')",
    )

    # report subcommand
    report_parser = sub.add_parser("report", help="Generate report from existing results")
    report_parser.add_argument(
        "-r", "--results",
        required=True,
        help="Directory containing result JSON files",
    )
    report_parser.add_argument(
        "-c", "--config",
        default=None,
        help="Optional YAML config for tracked_tools and metadata",
    )
    report_parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output path for the report (default: <name>-report.md)",
    )

    return parser


def cli() -> None:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    cli()
