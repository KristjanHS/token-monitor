"""Parse Claude Code JSONL session logs and extract token usage data."""
from __future__ import annotations

import json
import glob
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TurnUsage:
    """Token usage for a single assistant turn."""
    turn_number: int
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    model: str
    timestamp: str = ""

    @property
    def total_context(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens


@dataclass
class SessionStats:
    """Aggregated stats for a single session."""
    session_id: str
    jsonl_path: str
    turns: list[TurnUsage] = field(default_factory=list)
    date: str = ""

    @property
    def num_turns(self) -> int:
        return len(self.turns)

    @property
    def peak_context(self) -> int:
        return max((t.total_context for t in self.turns), default=0)

    @property
    def total_output(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def model_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.turns:
            model = _short_model_name(t.model)
            counts[model] = counts.get(model, 0) + 1
        return counts

    @property
    def dominant_model(self) -> str:
        counts = self.model_counts
        if not counts:
            return "unknown"
        return max(counts, key=counts.get)  # type: ignore[arg-type]

    @property
    def context_jumps(self) -> list[tuple[int, int]]:
        """Top 5 biggest context jumps between consecutive turns.

        Returns list of (turn_number, jump_size) sorted by jump_size desc.
        """
        jumps: list[tuple[int, int]] = []
        for i in range(1, len(self.turns)):
            delta = self.turns[i].total_context - self.turns[i - 1].total_context
            if delta > 0:
                jumps.append((self.turns[i].turn_number, delta))
        jumps.sort(key=lambda x: x[1], reverse=True)
        return jumps[:5]


def parse_session(jsonl_path: str) -> SessionStats:
    """Parse a single JSONL session file into SessionStats."""
    session_id = Path(jsonl_path).stem
    stats = SessionStats(session_id=session_id, jsonl_path=jsonl_path)
    turn_num = 0

    with open(jsonl_path) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "assistant":
                continue

            msg = obj.get("message")
            if not msg or "usage" not in msg:
                continue

            usage = msg["usage"]
            turn_num += 1

            turn = TurnUsage(
                turn_number=turn_num,
                input_tokens=usage.get("input_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                model=msg.get("model", "unknown"),
                timestamp=obj.get("timestamp", ""),
            )
            stats.turns.append(turn)

            if not stats.date and turn.timestamp:
                stats.date = turn.timestamp[:10]

    return stats


def parse_subagents(session_jsonl_path: str) -> list[SessionStats]:
    """Parse subagent JSONL files for a session, if any exist."""
    session_dir = Path(session_jsonl_path).stem
    parent = Path(session_jsonl_path).parent
    subagent_dir = parent / session_dir / "subagents"

    if not subagent_dir.is_dir():
        return []

    results = []
    for sa_file in sorted(subagent_dir.glob("*.jsonl")):
        results.append(parse_session(str(sa_file)))
    return results


def find_project_log_dir(cwd: str | None = None) -> str | None:
    """Derive the Claude Code project log directory from CWD."""
    if cwd is None:
        cwd = os.getcwd()

    # Claude Code slug: replace / with -, prepend -
    slug = "-" + cwd.replace("/", "-")
    log_dir = os.path.expanduser(f"~/.claude/projects/{slug}")

    if os.path.isdir(log_dir):
        return log_dir
    return None


def find_latest_session(log_dir: str) -> str | None:
    """Find the most recent JSONL file by mtime in a project log directory."""
    jsonl_files = glob.glob(os.path.join(log_dir, "*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=os.path.getmtime)


def find_all_sessions(log_dir: str) -> list[str]:
    """Find all JSONL session files in a project log directory."""
    return sorted(glob.glob(os.path.join(log_dir, "*.jsonl")), key=os.path.getmtime)


def _short_model_name(model: str) -> str:
    """Convert model ID to short display name."""
    if "opus" in model:
        return "opus"
    if "sonnet" in model:
        return "sonnet"
    if "haiku" in model:
        return "haiku"
    if model == "<synthetic>":
        return "synthetic"
    return model
