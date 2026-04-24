"""Tests for token_monitor.parser module."""
from __future__ import annotations

import json
import os
import unittest.mock
from pathlib import Path

import pytest

from token_monitor.parser import (
    SessionStats,
    TurnUsage,
    _resolve_worktree_main_repo,
    _short_model_name,
    find_all_sessions,
    find_latest_session,
    find_project_log_dir,
    parse_last_turn,
    parse_session,
    parse_subagents,
)


# ---------------------------------------------------------------------------
# Helpers — JSONL fixture builders
# ---------------------------------------------------------------------------


def _assistant_line(
    *,
    input_tokens: int = 100,
    cache_creation: int = 200,
    cache_read: int = 300,
    output_tokens: int = 50,
    model: str = "claude-sonnet-4-20250514",
    timestamp: str = "2026-04-04T10:00:00Z",
) -> str:
    """Build a single assistant JSONL line with realistic structure."""
    obj = {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            },
        },
    }
    return json.dumps(obj)


def _human_line(timestamp: str = "2026-04-04T09:59:00Z") -> str:
    """Build a human/user JSONL line."""
    return json.dumps({"type": "human", "timestamp": timestamp, "message": {"text": "hello"}})


def _system_line() -> str:
    """Build a system JSONL line."""
    return json.dumps({"type": "system", "message": {"text": "init"}})


def _write_jsonl(path: Path, lines: list[str]) -> None:
    """Write multiple JSON lines to a file."""
    path.write_text("\n".join(lines) + "\n")


def _make_session_file(tmp_path: Path, name: str = "abc-123.jsonl", lines: list[str] | None = None) -> Path:
    """Create a JSONL session file with default realistic data."""
    if lines is None:
        lines = [
            _human_line(),
            _assistant_line(input_tokens=100, cache_creation=200, cache_read=300, output_tokens=50),
            _human_line(timestamp="2026-04-04T10:01:00Z"),
            _assistant_line(
                input_tokens=150,
                cache_creation=250,
                cache_read=400,
                output_tokens=80,
                timestamp="2026-04-04T10:02:00Z",
            ),
        ]
    p = tmp_path / name
    _write_jsonl(p, lines)
    return p


# ---------------------------------------------------------------------------
# TurnUsage dataclass
# ---------------------------------------------------------------------------


class TestTurnUsage:
    def test_total_context_sums_three_input_fields(self):
        t = TurnUsage(
            turn_number=1,
            input_tokens=100,
            cache_creation_tokens=200,
            cache_read_tokens=300,
            output_tokens=50,
            model="claude-sonnet-4-20250514",
        )
        assert t.total_context == 600


# ---------------------------------------------------------------------------
# SessionStats properties
# ---------------------------------------------------------------------------


class TestSessionStats:
    def _make_stats(self, turns: list[TurnUsage] | None = None) -> SessionStats:
        if turns is None:
            turns = [
                TurnUsage(1, 100, 200, 300, 50, "claude-sonnet-4-20250514"),
                TurnUsage(2, 150, 250, 400, 80, "claude-sonnet-4-20250514"),
                TurnUsage(3, 500, 1000, 2000, 120, "claude-opus-4-20250514"),
            ]
        return SessionStats(session_id="test", jsonl_path="/tmp/test.jsonl", turns=turns)

    def test_peak_context(self):
        stats = self._make_stats()
        # Turn 3: 500 + 1000 + 2000 = 3500
        assert stats.peak_context == 3500

    def test_model_counts(self):
        stats = self._make_stats()
        counts = stats.model_counts
        assert counts == {"sonnet": 2, "opus": 1}

    def test_dominant_model_tie_is_deterministic(self):
        """When models are tied, max() picks the first one found — just verify no crash."""
        turns = [
            TurnUsage(1, 100, 0, 0, 50, "claude-sonnet-4-20250514"),
            TurnUsage(2, 100, 0, 0, 50, "claude-opus-4-20250514"),
        ]
        stats = self._make_stats(turns=turns)
        assert stats.dominant_model in ("sonnet", "opus")

    def test_context_jumps_sorted_desc(self):
        turns = [
            TurnUsage(1, 100, 0, 0, 10, "m"),   # context = 100
            TurnUsage(2, 300, 0, 0, 10, "m"),   # context = 300, jump = 200
            TurnUsage(3, 250, 0, 0, 10, "m"),   # context = 250, jump = -50 (negative, excluded)
            TurnUsage(4, 1000, 0, 0, 10, "m"),  # context = 1000, jump = 750
        ]
        stats = self._make_stats(turns=turns)
        jumps = stats.context_jumps
        assert jumps == [(4, 750), (2, 200)]

    def test_context_jumps_max_five(self):
        """Only top 5 jumps are returned."""
        turns = [TurnUsage(i, i * 100, 0, 0, 10, "m") for i in range(1, 9)]
        stats = self._make_stats(turns=turns)
        assert len(stats.context_jumps) == 5

    def test_context_jumps_no_positive_deltas(self):
        """All decreasing context means no jumps."""
        turns = [
            TurnUsage(1, 1000, 0, 0, 10, "m"),
            TurnUsage(2, 500, 0, 0, 10, "m"),
            TurnUsage(3, 200, 0, 0, 10, "m"),
        ]
        stats = self._make_stats(turns=turns)
        assert stats.context_jumps == []


# ---------------------------------------------------------------------------
# parse_session()
# ---------------------------------------------------------------------------


class TestParseSession:
    def test_parses_valid_assistant_messages(self, tmp_path: Path):
        p = _make_session_file(tmp_path)
        stats = parse_session(str(p))
        assert stats.num_turns == 2
        assert stats.session_id == "abc-123"

    def test_skips_non_assistant_messages(self, tmp_path: Path):
        lines = [
            _human_line(),
            _system_line(),
            _assistant_line(),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.num_turns == 1

    def test_skips_malformed_json_lines(self, tmp_path: Path):
        lines = [
            "this is not json {{{",
            _assistant_line(),
            "{broken",
            _assistant_line(output_tokens=99),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.num_turns == 2

    def test_missing_usage_field_skips_line(self, tmp_path: Path):
        """Assistant line without message.usage is skipped."""
        no_usage = json.dumps({"type": "assistant", "message": {"model": "m"}})
        lines = [no_usage, _assistant_line()]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.num_turns == 1

    def test_missing_message_field_skips_line(self, tmp_path: Path):
        """Assistant line without message key is skipped."""
        no_msg = json.dumps({"type": "assistant"})
        lines = [no_msg, _assistant_line()]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.num_turns == 1

    def test_missing_individual_usage_fields_default_to_zero(self, tmp_path: Path):
        """Usage dict with some fields missing — missing ones default to 0."""
        partial_usage = json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-20250514",
                "usage": {"output_tokens": 42},
            },
        })
        p = _make_session_file(tmp_path, lines=[partial_usage])
        stats = parse_session(str(p))
        assert stats.num_turns == 1
        t = stats.turns[0]
        assert t.input_tokens == 0
        assert t.cache_creation_tokens == 0
        assert t.cache_read_tokens == 0
        assert t.output_tokens == 42

    def test_missing_model_defaults_to_unknown(self, tmp_path: Path):
        no_model = json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": 10}},
        })
        p = _make_session_file(tmp_path, lines=[no_model])
        stats = parse_session(str(p))
        assert stats.turns[0].model == "unknown"

    def test_timestamp_extraction(self, tmp_path: Path):
        lines = [
            _assistant_line(timestamp="2026-04-04T10:00:00Z"),
            _assistant_line(timestamp="2026-04-04T11:00:00Z"),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.turns[0].timestamp == "2026-04-04T10:00:00Z"
        assert stats.turns[1].timestamp == "2026-04-04T11:00:00Z"

    def test_date_extracted_from_first_turn_timestamp(self, tmp_path: Path):
        lines = [
            _assistant_line(timestamp="2026-04-04T10:00:00Z"),
            _assistant_line(timestamp="2026-04-05T10:00:00Z"),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        assert stats.date == "2026-04-04"

    def test_date_empty_when_no_timestamp(self, tmp_path: Path):
        no_ts = json.dumps({
            "type": "assistant",
            "message": {"model": "m", "usage": {"input_tokens": 1}},
        })
        p = _make_session_file(tmp_path, lines=[no_ts])
        stats = parse_session(str(p))
        assert stats.date == ""

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        stats = parse_session(str(p))
        assert stats.num_turns == 0
        assert stats.session_id == "empty"

    def test_token_values_parsed_correctly(self, tmp_path: Path):
        lines = [
            _assistant_line(input_tokens=111, cache_creation=222, cache_read=333, output_tokens=444),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        stats = parse_session(str(p))
        t = stats.turns[0]
        assert t.input_tokens == 111
        assert t.cache_creation_tokens == 222
        assert t.cache_read_tokens == 333
        assert t.output_tokens == 444
        assert t.total_context == 666  # 111 + 222 + 333


# ---------------------------------------------------------------------------
# parse_subagents()
# ---------------------------------------------------------------------------


class TestParseSubagents:
    def test_with_subagent_directory(self, tmp_path: Path):
        """Subagent files are parsed when the directory exists."""
        # Main session file: tmp_path/session-1.jsonl
        main_file = _make_session_file(tmp_path, name="session-1.jsonl")

        # Subagent dir: tmp_path/session-1/subagents/
        sa_dir = tmp_path / "session-1" / "subagents"
        sa_dir.mkdir(parents=True)

        # Two subagent files
        _write_jsonl(sa_dir / "agent-a.jsonl", [_assistant_line(output_tokens=10)])
        _write_jsonl(sa_dir / "agent-b.jsonl", [_assistant_line(output_tokens=20)])

        results = parse_subagents(str(main_file))
        assert len(results) == 2
        # Sorted by filename
        assert results[0].session_id == "agent-a"
        assert results[1].session_id == "agent-b"
        assert results[0].turns[0].output_tokens == 10
        assert results[1].turns[0].output_tokens == 20

    def test_without_subagent_directory(self, tmp_path: Path):
        """Returns empty list when no subagent directory exists."""
        main_file = _make_session_file(tmp_path, name="session-1.jsonl")
        results = parse_subagents(str(main_file))
        assert results == []

    def test_empty_subagent_directory(self, tmp_path: Path):
        """Returns empty list when subagent directory exists but has no JSONL files."""
        main_file = _make_session_file(tmp_path, name="session-1.jsonl")
        sa_dir = tmp_path / "session-1" / "subagents"
        sa_dir.mkdir(parents=True)
        results = parse_subagents(str(main_file))
        assert results == []

    def test_subagent_non_jsonl_files_ignored(self, tmp_path: Path):
        """Non-.jsonl files in subagent directory are ignored."""
        main_file = _make_session_file(tmp_path, name="session-1.jsonl")
        sa_dir = tmp_path / "session-1" / "subagents"
        sa_dir.mkdir(parents=True)
        (sa_dir / "notes.txt").write_text("not a jsonl file")
        _write_jsonl(sa_dir / "agent-x.jsonl", [_assistant_line()])
        results = parse_subagents(str(main_file))
        assert len(results) == 1
        assert results[0].session_id == "agent-x"


# ---------------------------------------------------------------------------
# find_project_log_dir()
# ---------------------------------------------------------------------------


class TestFindProjectLogDir:
    def test_valid_cwd_returns_path(self, tmp_path: Path):
        """Returns log dir when the slug-based directory exists."""
        # Simulate CWD = /foo/bar → slug = -foo-bar
        fake_cwd = "/foo/bar"
        slug = fake_cwd.replace("/", "-")  # "-foo-bar"
        log_dir = tmp_path / ".claude" / "projects" / slug
        log_dir.mkdir(parents=True)

        # Patch expanduser to use tmp_path
        original = os.path.expanduser

        def fake_expanduser(p: str) -> str:
            if p.startswith("~"):
                return str(tmp_path) + p[1:]
            return original(p)

        with unittest.mock.patch("os.path.expanduser", side_effect=fake_expanduser):
            result = find_project_log_dir(fake_cwd)

        assert result is not None
        assert result == str(log_dir)

    def test_invalid_cwd_returns_none(self, tmp_path: Path):
        """Returns None when the slug-based directory does not exist."""
        original = os.path.expanduser

        def fake_expanduser(p: str) -> str:
            if p.startswith("~"):
                return str(tmp_path) + p[1:]
            return original(p)

        with unittest.mock.patch("os.path.expanduser", side_effect=fake_expanduser):
            result = find_project_log_dir("/nonexistent/project/path")

        assert result is None

    def test_worktree_cwd_falls_back_to_main_repo_slug(self, tmp_path: Path):
        """When direct slug lookup fails, resolves worktree to main repo slug."""
        # Layout:
        #   tmp_path/main-repo/          <- main repo root
        #   tmp_path/main-repo/.git/     <- real git dir
        #   tmp_path/main-repo/.git/worktrees/feat/  <- worktree gitdir
        #   tmp_path/worktree-checkout/  <- worktree working dir
        #   tmp_path/worktree-checkout/.git  <- file pointing to gitdir

        main_repo = tmp_path / "main-repo"
        main_git = main_repo / ".git"
        wt_gitdir = main_git / "worktrees" / "feat"
        wt_gitdir.mkdir(parents=True)

        # commondir in worktree gitdir points back to main .git
        (wt_gitdir / "commondir").write_text("../..\n")

        # Worktree checkout with .git file
        wt_checkout = tmp_path / "worktree-checkout"
        wt_checkout.mkdir()
        (wt_checkout / ".git").write_text(f"gitdir: {wt_gitdir}\n")

        # Create the Claude project dir for the MAIN repo slug (not the worktree)
        main_slug = str(main_repo).replace("/", "-")
        log_dir = tmp_path / ".claude" / "projects" / main_slug
        log_dir.mkdir(parents=True)

        original = os.path.expanduser

        def fake_expanduser(p: str) -> str:
            if p.startswith("~"):
                return str(tmp_path) + p[1:]
            return original(p)

        with unittest.mock.patch("os.path.expanduser", side_effect=fake_expanduser):
            result = find_project_log_dir(str(wt_checkout))

        assert result == str(log_dir)


# ---------------------------------------------------------------------------
# _resolve_worktree_main_repo()
# ---------------------------------------------------------------------------


class TestResolveWorktreeMainRepo:
    def test_regular_git_repo_returns_none(self, tmp_path: Path):
        """A .git directory (not file) means regular repo — no fallback."""
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)

        result = _resolve_worktree_main_repo(str(repo))
        assert result is None

    def test_malformed_git_file_missing_gitdir_prefix(self, tmp_path: Path):
        """A .git file without 'gitdir:' prefix returns None."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("not a gitdir pointer\n")

        result = _resolve_worktree_main_repo(str(wt))
        assert result is None

    def test_malformed_git_file_missing_commondir(self, tmp_path: Path):
        """A .git file with valid gitdir but no commondir file returns None."""
        wt = tmp_path / "wt"
        wt.mkdir()

        # Create a gitdir target without commondir
        gitdir = tmp_path / "fake-gitdir"
        gitdir.mkdir()

        (wt / ".git").write_text(f"gitdir: {gitdir}\n")

        result = _resolve_worktree_main_repo(str(wt))
        assert result is None

    def test_happy_path_resolves_main_repo(self, tmp_path: Path):
        """A proper worktree .git file resolves to the main repo root."""
        # Set up main repo structure
        main_repo = tmp_path / "main-repo"
        worktree_gitdir = main_repo / ".git" / "worktrees" / "feat"
        worktree_gitdir.mkdir(parents=True)
        (worktree_gitdir / "commondir").write_text("../..\n")

        # Set up worktree with .git file pointing to the gitdir
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {worktree_gitdir}\n")

        result = _resolve_worktree_main_repo(str(wt))
        assert result == str(main_repo)

    def test_walk_up_from_subdirectory_inside_worktree(self, tmp_path: Path):
        """Passing a subdirectory inside the worktree still resolves to main repo."""
        # Set up main repo structure
        main_repo = tmp_path / "main-repo"
        worktree_gitdir = main_repo / ".git" / "worktrees" / "feat"
        worktree_gitdir.mkdir(parents=True)
        (worktree_gitdir / "commondir").write_text("../..\n")

        # Set up worktree with .git file pointing to the gitdir
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {worktree_gitdir}\n")

        # Create a nested subdirectory inside the worktree
        subdir = wt / "src" / "components"
        subdir.mkdir(parents=True)

        result = _resolve_worktree_main_repo(str(subdir))
        assert result == str(main_repo)


# ---------------------------------------------------------------------------
# find_latest_session()
# ---------------------------------------------------------------------------


class TestFindLatestSession:
    def test_picks_most_recent_by_mtime(self, tmp_path: Path):
        # Create three files with different mtimes
        old = tmp_path / "old.jsonl"
        mid = tmp_path / "mid.jsonl"
        new = tmp_path / "new.jsonl"

        old.write_text("{}")
        mid.write_text("{}")
        new.write_text("{}")

        # Set mtimes: old < mid < new
        os.utime(str(old), (1000, 1000))
        os.utime(str(mid), (2000, 2000))
        os.utime(str(new), (3000, 3000))

        result = find_latest_session(str(tmp_path))
        assert result == str(new)

    def test_returns_none_for_empty_directory(self, tmp_path: Path):
        result = find_latest_session(str(tmp_path))
        assert result is None

    def test_ignores_non_jsonl_files(self, tmp_path: Path):
        (tmp_path / "notes.txt").write_text("hi")
        (tmp_path / "data.json").write_text("{}")
        result = find_latest_session(str(tmp_path))
        assert result is None

    def test_single_file(self, tmp_path: Path):
        only = tmp_path / "only.jsonl"
        only.write_text("{}")
        result = find_latest_session(str(tmp_path))
        assert result == str(only)


# ---------------------------------------------------------------------------
# find_all_sessions()
# ---------------------------------------------------------------------------


class TestFindAllSessions:
    def test_returns_sorted_by_mtime(self, tmp_path: Path):
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        c = tmp_path / "c.jsonl"

        a.write_text("{}")
        b.write_text("{}")
        c.write_text("{}")

        os.utime(str(a), (3000, 3000))
        os.utime(str(b), (1000, 1000))
        os.utime(str(c), (2000, 2000))

        result = find_all_sessions(str(tmp_path))
        assert result == [str(b), str(c), str(a)]

    def test_empty_directory(self, tmp_path: Path):
        result = find_all_sessions(str(tmp_path))
        assert result == []

    def test_ignores_non_jsonl(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("hi")
        (tmp_path / "session.jsonl").write_text("{}")
        result = find_all_sessions(str(tmp_path))
        assert len(result) == 1
        assert result[0].endswith("session.jsonl")


# ---------------------------------------------------------------------------
# _short_model_name()
# ---------------------------------------------------------------------------


class TestShortModelName:
    @pytest.mark.parametrize("model,expected", [
        ("claude-opus-4-20250514", "opus"),
        ("claude-sonnet-4-20250514", "sonnet"),
        ("claude-haiku-3.5-20250514", "haiku"),
    ])
    def test_known_models(self, model, expected):
        assert _short_model_name(model) == expected

    def test_synthetic(self):
        assert _short_model_name("<synthetic>") == "synthetic"

    def test_unknown_passthrough(self):
        assert _short_model_name("gpt-4-turbo") == "gpt-4-turbo"


# ---------------------------------------------------------------------------
# parse_last_turn()
# ---------------------------------------------------------------------------


class TestParseLastTurn:
    def test_returns_last_turn_usage(self, tmp_path):
        lines = [
            _assistant_line(input_tokens=100, cache_creation=200, cache_read=300, output_tokens=50),
            _assistant_line(input_tokens=500, cache_creation=100, cache_read=400, output_tokens=80),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        result = parse_last_turn(str(p))

        assert result.input_tokens == 500
        assert result.cache_creation == 100
        assert result.cache_read == 400
        assert result.output_tokens == 80
        assert result.total_context == 1000  # 500+100+400

    def test_empty_file_returns_zeros(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        result = parse_last_turn(str(p))

        assert result.total_context == 0
        assert result.model == "unknown"

    def test_skips_non_assistant_and_malformed(self, tmp_path):
        lines = [
            _human_line(),
            "not json {{{",
            _assistant_line(input_tokens=42, cache_creation=0, cache_read=0, output_tokens=10),
        ]
        p = _make_session_file(tmp_path, lines=lines)
        result = parse_last_turn(str(p))

        assert result.input_tokens == 42

    def test_extracts_model(self, tmp_path):
        lines = [_assistant_line(model="claude-opus-4-20250514")]
        p = _make_session_file(tmp_path, lines=lines)
        result = parse_last_turn(str(p))

        assert result.model == "claude-opus-4-20250514"
