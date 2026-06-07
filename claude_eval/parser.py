"""Transcript JSONL parser — extracts tool calls from Claude Code transcripts.

Transcript format (one JSON object per line):
  - type: "user" (userType: "external", content: string)  → user prompt (turn boundary)
  - type: "user" (content: [{type: "tool_result", ...}])   → tool result
  - type: "assistant" (content: [{type: "tool_use", ...}]) → tool call
  - type: "attachment" | "permission-mode" | ...          → metadata (skipped)
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import ToolCall, TurnResult


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank/invalid lines."""
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [parser] Skipping invalid line {line_no}: {e}")
    return entries


def _is_user_prompt(entry: dict) -> bool:
    """Check if an entry is a user prompt (turn boundary).

    User prompts have type "user", userType "external", and content is a plain string.
    Tool results also have type "user" but content is a list of tool_result objects.
    """
    if entry.get("type") != "user":
        return False
    content = entry.get("message", {}).get("content", "")
    return isinstance(content, str) and len(content) > 0


def _is_tool_result_entry(entry: dict) -> bool:
    """Check if an entry is a tool result (not a user prompt).

    Tool result entries have type "user" with content as a list of tool_result blocks,
    and typically have a sourceToolAssistantUUID field.
    """
    if entry.get("type") != "user":
        return False
    if _is_user_prompt(entry):
        return False
    content = entry.get("message", {}).get("content", [])
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
    return False


def _extract_tool_uses(entry: dict) -> list[ToolCall]:
    """Extract tool_use blocks from an assistant message."""
    calls = []
    content = entry.get("message", {}).get("content", [])
    timestamp = entry.get("timestamp", "")
    if not isinstance(content, list):
        return calls

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            calls.append(ToolCall(
                tool_name=block.get("name", "unknown"),
                tool_use_id=block.get("id", ""),
                input=block.get("input", {}),
                output="",
                timestamp=timestamp,
            ))
    return calls


def _extract_tool_result(entry: dict) -> tuple[str, str, bool, int, str]:
    """Extract tool result data from a user tool_result message.

    Returns: (tool_use_id, output_text, is_error, duration_ms, timestamp)
    """
    content = entry.get("message", {}).get("content", [])
    timestamp = entry.get("timestamp", "")
    tool_use_result = entry.get("toolUseResult")
    if not isinstance(tool_use_result, dict):
        tool_use_result = {}

    tool_use_id = ""
    output_text = ""
    is_error = False
    duration_ms = 0

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                output_text = block.get("content", "")
                is_error = block.get("is_error", False)
                break

    # Prefer explicit durationMs from toolUseResult metadata
    duration_ms = tool_use_result.get("durationMs", 0)

    return tool_use_id, output_text, is_error, duration_ms, timestamp


class TranscriptParser:
    """Parses Claude Code transcript JSONL files to extract tool usage data."""

    def parse_session(self, transcript_path: Path, turn_count: int | None = None) -> list[TurnResult]:
        """Parse a complete transcript and group by turn.

        Args:
            transcript_path: Path to the transcript.jsonl file.
            turn_count: Number of business turns to return (last N turns).
                        If None, returns all turns.

        Returns:
            List of TurnResult, one per user prompt turn.
        """
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {transcript_path}")

        entries = _read_jsonl(transcript_path)
        if not entries:
            return []

        # Group entries by turn (separated by user prompts)
        turns_raw = self._split_by_turn(entries)
        turn_results = [self._build_turn(idx, entries) for idx, entries in enumerate(turns_raw)]

        # Filter to last turn_count turns if specified
        if turn_count is not None:
            turn_results = turn_results[-turn_count:]

        return turn_results

    def _split_by_turn(self, entries: list[dict]) -> list[list[dict]]:
        """Split transcript entries into turns, each starting with a user prompt.

        Returns list of turn entry lists. Metadata-only entries before the first
        prompt are discarded.
        """
        turns: list[list[dict]] = []
        current_turn: list[dict] = []
        first_prompt_found = False

        for entry in entries:
            if _is_user_prompt(entry):
                if first_prompt_found and current_turn:
                    turns.append(current_turn)
                first_prompt_found = True
                current_turn = [entry]
            elif first_prompt_found:
                current_turn.append(entry)

        if current_turn:
            turns.append(current_turn)

        return turns

    def _build_turn(self, index: int, turn_entries: list[dict]) -> TurnResult:
        """Build a TurnResult from a list of entries belonging to one turn."""
        # First entry should be the user prompt
        prompt = ""
        turn_timestamp = ""
        for entry in turn_entries:
            if _is_user_prompt(entry):
                prompt = entry.get("message", {}).get("content", "")
                turn_timestamp = entry.get("timestamp", "")
                break

        # Collect tool calls and match with results
        tool_uses: dict[str, ToolCall] = {}  # tool_use_id -> ToolCall
        for entry in turn_entries:
            if entry.get("type") == "assistant":
                for call in _extract_tool_uses(entry):
                    tool_uses[call.tool_use_id] = call

        # Match results back to tool calls
        for entry in turn_entries:
            if not _is_tool_result_entry(entry):
                continue
            tool_use_id, output, is_error, duration_ms, result_ts = _extract_tool_result(entry)
            if tool_use_id in tool_uses:
                tool_uses[tool_use_id].output = output
                tool_uses[tool_use_id].is_error = is_error
                # Use explicit durationMs if available, otherwise estimate from timestamps
                if duration_ms > 0:
                    tool_uses[tool_use_id].duration_ms = duration_ms
                elif tool_uses[tool_use_id].timestamp and result_ts:
                    try:
                        from datetime import datetime
                        t1 = datetime.fromisoformat(tool_uses[tool_use_id].timestamp.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(result_ts.replace("Z", "+00:00"))
                        ms = int((t2 - t1).total_seconds() * 1000)
                        tool_uses[tool_use_id].duration_ms = max(0, ms)
                    except (ValueError, TypeError):
                        pass

        # Sort by timestamp for consistent ordering
        tool_calls = sorted(tool_uses.values(), key=lambda c: c.timestamp)

        return TurnResult(
            turn_index=index,
            prompt=prompt,
            tool_calls=tool_calls,
            timestamp=turn_timestamp,
        )
