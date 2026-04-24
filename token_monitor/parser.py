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

    # Claude Code slug: replace / with - (leading / becomes the - prefix)
    slug = cwd.replace("/", "-")
    log_dir = os.path.expanduser(f"~/.claude/projects/{slug}")

    if os.path.isdir(log_dir):
        return log_dir

    # Fallback: resolve git worktree to main repo
    main_root = _resolve_worktree_main_repo(cwd)
    if main_root and main_root != cwd:
        slug = main_root.replace("/", "-")
        log_dir = os.path.expanduser(f"~/.claude/projects/{slug}")
        if os.path.isdir(log_dir):
            return log_dir

    return None


def _resolve_worktree_main_repo(cwd: str) -> str | None:
    """If cwd is inside a git worktree, return the main repo root.

    Walks up from cwd looking for a .git entry. If .git is a file
    (worktree indicator), reads the gitdir pointer and commondir to
    resolve the main repository root. Returns None for regular repos
    or if resolution fails.
    """
    path = cwd
    while path != os.path.dirname(path):  # stop at filesystem root
        git_path = os.path.join(path, ".git")
        if os.path.isfile(git_path):
            # Worktree: .git is a file containing a gitdir pointer
            try:
                with open(git_path) as f:
                    line = f.readline().strip()
            except OSError:
                return None
            if not line.startswith("gitdir:"):
                return None
            gitdir = line[len("gitdir:"):].strip()
            if not os.path.isabs(gitdir):
                gitdir = os.path.normpath(os.path.join(path, gitdir))
            # Read commondir to find the main .git directory
            commondir_file = os.path.join(gitdir, "commondir")
            if not os.path.isfile(commondir_file):
                return None
            try:
                with open(commondir_file) as f:
                    commondir = f.readline().strip()
            except OSError:
                return None
            main_git_dir = os.path.normpath(os.path.join(gitdir, commondir))
            # Main repo root is parent of the .git directory
            return os.path.dirname(main_git_dir)
        elif os.path.isdir(git_path):
            # Regular repo, not a worktree — no fallback needed
            return None
        path = os.path.dirname(path)
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


@dataclass
class LastTurnUsage:
    """Usage snapshot from the most recent assistant turn in a session."""
    total_context: int
    input_tokens: int
    cache_creation: int
    cache_read: int
    output_tokens: int
    model: str


_TAIL_CHUNK = 65536


def parse_last_turn(jsonl_path: str) -> LastTurnUsage:
    """Extract usage data from the last assistant turn in a JSONL file.

    Reads only the tail of the file — the last assistant turn is
    virtually always within the final few KB, and scanning the whole
    file (which can be multi-MB) to hit the bottom is wasted work.
    Returns zero usage if the tail contains no assistant turn.
    """
    last_usage: dict = {}
    last_model = "unknown"
    try:
        size = os.path.getsize(jsonl_path)
    except OSError:
        size = 0
    if size > 0:
        with open(jsonl_path, "rb") as f:
            if size > _TAIL_CHUNK:
                f.seek(size - _TAIL_CHUNK)
                f.readline()  # discard possibly-partial first line
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message", {})
            usage = msg.get("usage")
            if not usage:
                continue
            last_usage = usage
            last_model = msg.get("model", "unknown")
            break

    input_tok = last_usage.get("input_tokens", 0)
    cache_create = last_usage.get("cache_creation_input_tokens", 0)
    cache_read = last_usage.get("cache_read_input_tokens", 0)
    output_tok = last_usage.get("output_tokens", 0)

    return LastTurnUsage(
        total_context=input_tok + cache_create + cache_read,
        input_tokens=input_tok,
        cache_creation=cache_create,
        cache_read=cache_read,
        output_tokens=output_tok,
        model=last_model,
    )


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
