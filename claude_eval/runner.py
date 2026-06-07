"""Claude Code session runner — drives multi-turn conversations via subprocess."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .config import EvalConfig, ModeConfig
from .models import RunResult
from .parser import TranscriptParser


class ClaudeRunner:
    """Drives Claude Code sessions for evaluation.

    Each mode × repetition creates one session with multiple turns.
    Uses `claude -p` with `--resume` for multi-turn conversations.
    """

    def __init__(self, parser: TranscriptParser | None = None):
        self.parser = parser or TranscriptParser()
        self.claude_bin = self._find_claude()

    @staticmethod
    def _find_claude() -> str:
        """Locate the claude CLI binary.

        On Windows, Claude Code is typically installed via npm as claude.cmd,
        and subprocess.run needs shell=True to resolve it.
        """
        found = shutil.which("claude")
        if found:
            return "claude"
        # Direct fallback for Windows npm global install
        win_path = Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd"
        if win_path.exists():
            return str(win_path)
        raise FileNotFoundError(
            "claude CLI not found. Ensure Claude Code is installed and on PATH.\n"
            "Install: npm install -g @anthropic-ai/claude-code"
        )

    def run_all(
        self,
        config: EvalConfig,
        output_dir: Path,
        mode_filter: str | None = None,
    ) -> list[RunResult]:
        """Run all evaluation sessions and save results.

        Args:
            config: Eval configuration.
            output_dir: Directory to save JSON results.
            mode_filter: If set, only run this specific mode.

        Returns:
            List of RunResult for all completed runs.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[RunResult] = []

        modes = [m for m in config.modes if not mode_filter or m.name == mode_filter]
        total = len(modes) * config.runs_per_mode
        completed = 0

        print(f"\n{'='*60}")
        print(f"Eval: {config.name}")
        print(f"Modes: {len(modes)} × {config.runs_per_mode} runs = {total} sessions")
        if config.model:
            print(f"Model: {config.model}")
        print(f"{'='*60}\n")

        for mode in modes:
            for run_idx in range(config.runs_per_mode):
                completed += 1
                print(f"[{completed}/{total}] Mode '{mode.name}' run {run_idx + 1}/{config.runs_per_mode} ...", flush=True)

                result = self.run_session(config, mode, run_idx)
                results.append(result)

                # Save individual result
                result_path = output_dir / f"{mode.name}_run{run_idx + 1}.json"
                result.save(result_path)

                # Print brief summary
                calls = result.total_tool_calls
                dur = result.duration_s
                tools_called = {c.tool_name: len(result.calls_by_tool(c.tool_name)) for c in result.turns[0].tool_calls if result.turns}
                tool_summary = ", ".join(f"{k}:{v}" for k, v in sorted(tools_called.items())) if tools_called else "no tool calls"
                print(f"  OK {len(result.turns)} turns, {calls} tool calls, {dur:.1f}s [{tool_summary}]")

        return results

    def run_session(self, config: EvalConfig, mode: ModeConfig, run_index: int) -> RunResult:
        """Drive a single Claude Code session with multiple turns.

        Turn flow:
          1. setup turns (if any) — establish context
          2. business turns — the turns we evaluate

        All turns share the same session (via --session-id + --resume).
        """
        session_id = str(uuid.uuid4())
        all_prompts = mode.setup + mode.turns
        start_time = time.time()

        # Build common claude args
        claude_base = [self.claude_bin, "-p"]
        if config.model:
            claude_base.extend(["--model", config.model])
        if config.max_turns:
            claude_base.extend(["--max-turns", str(config.max_turns)])

        use_shell = sys.platform == "win32"

        # Execute each turn
        # Turn 0: new session (no --session-id)
        # Turn 1+: resume the session created by turn 0
        for i, prompt in enumerate(all_prompts):
            cmd = [*claude_base, prompt]
            if i == 0:
                cmd.extend(["--session-id", session_id])
            else:
                cmd.extend(["--resume", str(session_id)])

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,  # 5 min per turn
                    cwd=str(Path.cwd()),
                    shell=use_shell,
                )
                if result.returncode != 0 and result.stderr:
                    print(f"  [WARN] Turn {i} exit {result.returncode}: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                print(f"  [WARN] Turn {i} timed out after 300s")
            except FileNotFoundError:
                print(f"  [ERROR] 'claude' command not found.")
                raise

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Find and parse the transcript
        transcript_path = self._find_transcript(session_id)
        if transcript_path:
            turn_count = len(mode.turns) if mode.turns else None
            turns = self.parser.parse_session(transcript_path, turn_count=turn_count)
            # Re-index turns to match business turn indices
            for i, turn in enumerate(turns):
                turn.turn_index = i
        else:
            print(f"  [WARN] Transcript not found for session {session_id[:12]}...")
            turns = []

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        return RunResult(
            mode=mode.name,
            run_index=run_index,
            session_id=session_id,
            turns=turns,
            total_duration_ms=elapsed_ms,
            started_at=now,
            finished_at=now,
        )

    def _find_transcript(self, session_id: str) -> Path | None:
        """Locate the transcript file for a given session ID.

        Claude Code stores transcripts at:
          ~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
        """
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None

        # Search all project directories for the session
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue
            transcript = project_dir / f"{session_id}.jsonl"
            if transcript.exists():
                return transcript

            # Also check subagents directory
            subagents = project_dir / session_id / "subagents"
            if subagents.exists():
                # The main transcript might be in the session subdirectory
                main_transcript = project_dir / session_id / "transcript.jsonl"
                if main_transcript.exists():
                    return main_transcript

        return None
