"""Tests for the token_monitor.cli module."""
from __future__ import annotations

import json
import os

import pytest

from token_monitor.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jsonl(path, turns: list[dict] | None = None) -> str:
    """Write a minimal JSONL session file and return its string path.

    *turns* is a list of dicts with optional keys:
        input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
        output_tokens, model, timestamp.
    If omitted, a single reasonable turn is written.
    """
    if turns is None:
        turns = [
            {
                "input_tokens": 100,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 200,
                "output_tokens": 80,
                "model": "claude-sonnet-4-20250514",
                "timestamp": "2026-04-04T12:00:00Z",
            }
        ]

    with open(path, "w") as f:
        for t in turns:
            obj = {
                "type": "assistant",
                "timestamp": t.get("timestamp", "2026-04-04T12:00:00Z"),
                "message": {
                    "model": t.get("model", "claude-sonnet-4-20250514"),
                    "usage": {
                        "input_tokens": t.get("input_tokens", 100),
                        "cache_creation_input_tokens": t.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cache_read_input_tokens": t.get(
                            "cache_read_input_tokens", 0
                        ),
                        "output_tokens": t.get("output_tokens", 50),
                    },
                },
            }
            f.write(json.dumps(obj) + "\n")

    return str(path)


# ---------------------------------------------------------------------------
# session subcommand — explicit path
# ---------------------------------------------------------------------------


class TestSessionExplicitPath:
    """main(["session", <path>]) with an explicit JSONL file."""

    def test_session_with_explicit_path(self, tmp_path, capsys):
        """Basic happy-path: parse a JSONL file and print report."""
        jsonl = _make_jsonl(tmp_path / "abc123.jsonl")
        main(["session", jsonl, "--no-log"])
        out = capsys.readouterr().out

        assert "Session: abc123" in out
        assert "Turns:   1" in out
        # Peak = input(100) + cache_creation(50) + cache_read(200) = 350
        assert "350" in out

    def test_session_multiple_turns(self, tmp_path, capsys):
        """Session report with multiple turns shows correct metrics."""
        turns = [
            {
                "input_tokens": 100,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 50,
                "timestamp": "2026-04-04T10:00:00Z",
            },
            {
                "input_tokens": 300,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200,
                "output_tokens": 120,
                "timestamp": "2026-04-04T10:05:00Z",
            },
        ]
        jsonl = _make_jsonl(tmp_path / "multi.jsonl", turns)
        main(["session", jsonl, "--no-log"])
        out = capsys.readouterr().out

        assert "Turns:   2" in out
        # Peak = max(100, 600) = 600
        assert "600" in out
        assert "Date:    2026-04-04" in out

    def test_session_empty_file_zero_turns(self, tmp_path, capsys):
        """An empty JSONL file produces zero-turn report."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        main(["session", str(empty), "--no-log"])
        out = capsys.readouterr().out

        assert "Session: empty" in out
        assert "Turns:   0" in out

    def test_session_non_assistant_lines_skipped(self, tmp_path, capsys):
        """Lines with type != assistant are ignored."""
        path = tmp_path / "mixed.jsonl"
        with open(path, "w") as f:
            # user line — should be skipped
            f.write(json.dumps({"type": "user", "message": {"text": "hi"}}) + "\n")
            # assistant line — should be counted
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-04-04T12:00:00Z",
                        "message": {
                            "model": "claude-sonnet-4-20250514",
                            "usage": {
                                "input_tokens": 100,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0,
                                "output_tokens": 40,
                            },
                        },
                    }
                )
                + "\n"
            )
            # malformed JSON line — should be skipped without error
            f.write("not valid json\n")

        main(["session", str(path), "--no-log"])
        out = capsys.readouterr().out

        assert "Turns:   1" in out


# ---------------------------------------------------------------------------
# session subcommand — default path discovery via CWD
# ---------------------------------------------------------------------------


class TestSessionDefaultPath:
    """main(["session"]) without an explicit path — discovers via CWD."""

    def test_session_default_discovers_latest(self, tmp_path, capsys, monkeypatch):
        """When no path given, finds the latest JSONL in the project log dir."""
        log_dir = tmp_path / "log_dir"
        log_dir.mkdir()

        # Create two JSONL files; make the second one newer
        older = _make_jsonl(log_dir / "older.jsonl")
        newer = _make_jsonl(
            log_dir / "newer.jsonl",
            [
                {
                    "input_tokens": 999,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 10,
                    "timestamp": "2026-04-04T14:00:00Z",
                }
            ],
        )
        # Touch the older file first, newer file second to ensure mtime order
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))

        monkeypatch.setattr(
            "token_monitor.cli.find_project_log_dir", lambda: str(log_dir)
        )
        main(["session", "--no-log"])
        out = capsys.readouterr().out

        assert "Session: newer" in out
        assert "999" in out

    def test_session_default_no_log_dir_exits(self, capsys, monkeypatch):
        """Exit with error when project log dir cannot be found."""
        monkeypatch.setattr(
            "token_monitor.cli.find_project_log_dir", lambda: None
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["session"])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "could not find project log directory" in err

    def test_session_default_no_jsonl_exits(self, tmp_path, capsys, monkeypatch):
        """Exit with error when the log dir exists but has no JSONL files."""
        log_dir = tmp_path / "empty_log_dir"
        log_dir.mkdir()

        monkeypatch.setattr(
            "token_monitor.cli.find_project_log_dir", lambda: str(log_dir)
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["session"])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "no JSONL files found" in err


# ---------------------------------------------------------------------------
# session subcommand — --no-log flag
# ---------------------------------------------------------------------------


class TestSessionNoLogFlag:
    """Verify --no-log suppresses appending to the usage log."""

    def test_no_log_flag_skips_append(self, tmp_path, capsys, monkeypatch):
        """With --no-log, append_to_log should NOT be called."""
        jsonl = _make_jsonl(tmp_path / "sess.jsonl")
        called = []

        monkeypatch.setattr(
            "token_monitor.cli.append_to_log",
            lambda stats: called.append(True) or "fake_path",
        )
        main(["session", jsonl, "--no-log"])

        assert called == [], "append_to_log was called despite --no-log"

    def test_without_no_log_flag_appends(self, tmp_path, capsys, monkeypatch):
        """Without --no-log, append_to_log IS called and path is printed."""
        jsonl = _make_jsonl(tmp_path / "sess.jsonl")
        log_file = tmp_path / "token-usage-log.md"

        monkeypatch.setattr(
            "token_monitor.cli.append_to_log",
            lambda stats: str(log_file),
        )
        main(["session", jsonl])
        out = capsys.readouterr().out

        assert f"Logged to {log_file}" in out


# ---------------------------------------------------------------------------
# project subcommand — explicit path
# ---------------------------------------------------------------------------


class TestProjectExplicitPath:
    """main(["project", <path>]) with an explicit directory."""

    def test_project_with_sessions(self, tmp_path, capsys):
        """Project report shows stats for all sessions."""
        log_dir = tmp_path / "proj"
        log_dir.mkdir()

        _make_jsonl(
            log_dir / "session1.jsonl",
            [
                {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 50,
                    "timestamp": "2026-04-01T10:00:00Z",
                }
            ],
        )
        _make_jsonl(
            log_dir / "session2.jsonl",
            [
                {
                    "input_tokens": 500,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 200,
                    "output_tokens": 150,
                    "timestamp": "2026-04-03T10:00:00Z",
                }
            ],
        )

        main(["project", str(log_dir)])
        out = capsys.readouterr().out

        assert "Sessions: 2" in out
        assert "session1" in out
        assert "session2" in out

    def test_project_no_sessions_prints_message(self, tmp_path, capsys):
        """Empty project dir prints 'No sessions found', does NOT exit(1)."""
        empty_dir = tmp_path / "empty_proj"
        empty_dir.mkdir()

        # Should return normally, not raise SystemExit
        main(["project", str(empty_dir)])
        out = capsys.readouterr().out

        assert "No sessions found" in out

    def test_project_date_range(self, tmp_path, capsys):
        """Project report shows correct date range."""
        log_dir = tmp_path / "proj_dates"
        log_dir.mkdir()

        _make_jsonl(
            log_dir / "s1.jsonl",
            [{"timestamp": "2026-03-15T10:00:00Z", "input_tokens": 50, "output_tokens": 20}],
        )
        _make_jsonl(
            log_dir / "s2.jsonl",
            [{"timestamp": "2026-04-02T10:00:00Z", "input_tokens": 50, "output_tokens": 20}],
        )

        main(["project", str(log_dir)])
        out = capsys.readouterr().out

        assert "2026-03-15" in out
        assert "2026-04-02" in out


# ---------------------------------------------------------------------------
# project subcommand — default path discovery
# ---------------------------------------------------------------------------


class TestProjectDefaultPath:
    """main(["project"]) without an explicit path."""

    def test_project_default_discovers_dir(self, tmp_path, capsys, monkeypatch):
        """Discovers log dir from CWD when no path given."""
        log_dir = tmp_path / "auto_proj"
        log_dir.mkdir()
        _make_jsonl(
            log_dir / "s1.jsonl",
            [{"input_tokens": 50, "output_tokens": 20, "timestamp": "2026-04-04T10:00:00Z"}],
        )

        monkeypatch.setattr(
            "token_monitor.cli.find_project_log_dir", lambda: str(log_dir)
        )
        main(["project"])
        out = capsys.readouterr().out

        assert "Sessions: 1" in out

    def test_project_default_no_log_dir_exits(self, capsys, monkeypatch):
        """Exit with error when project log dir cannot be found."""
        monkeypatch.setattr(
            "token_monitor.cli.find_project_log_dir", lambda: None
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["project"])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "could not find project log directory" in err


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Additional error handling paths in cli.py."""

    def test_no_subcommand_exits(self):
        """Calling main with no subcommand should cause argparse to exit."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        # argparse exits with code 2 for usage errors
        assert exc_info.value.code == 2

    def test_unknown_subcommand_exits(self):
        """Unknown subcommand triggers argparse error exit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["unknown"])
        assert exc_info.value.code == 2

    def test_project_filters_empty_sessions(self, tmp_path, capsys):
        """Sessions with no turns are filtered out in project command."""
        log_dir = tmp_path / "proj_mixed"
        log_dir.mkdir()

        # One empty file (0 turns), one with data
        empty = log_dir / "empty_session.jsonl"
        empty.write_text("")

        _make_jsonl(
            log_dir / "real_session.jsonl",
            [{"input_tokens": 100, "output_tokens": 50, "timestamp": "2026-04-04T10:00:00Z"}],
        )

        main(["project", str(log_dir)])
        out = capsys.readouterr().out

        # Project report should include the non-empty session
        assert "real_ses" in out
        # The header says 1 session (after filtering)
        # Actually project_report receives filtered list of 1
        # But find_all_sessions returns 2 — filtering happens in _cmd_project
        assert "Sessions: 1" in out


# ---------------------------------------------------------------------------
# Integration: end-to-end with tmp JSONL
# ---------------------------------------------------------------------------


class TestIntegration:
    """Full integration: create temp JSONL, run main(), verify output."""

    def test_full_session_report(self, tmp_path, capsys, monkeypatch):
        """End-to-end: create a multi-turn JSONL, run session, check report."""
        turns = [
            {
                "input_tokens": 200,
                "cache_creation_input_tokens": 1000,
                "cache_read_input_tokens": 0,
                "output_tokens": 300,
                "model": "claude-opus-4-20250514",
                "timestamp": "2026-04-04T09:00:00Z",
            },
            {
                "input_tokens": 150,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1100,
                "output_tokens": 250,
                "model": "claude-opus-4-20250514",
                "timestamp": "2026-04-04T09:05:00Z",
            },
            {
                "input_tokens": 500,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 1200,
                "output_tokens": 400,
                "model": "claude-sonnet-4-20250514",
                "timestamp": "2026-04-04T09:10:00Z",
            },
        ]
        jsonl = _make_jsonl(tmp_path / "integration.jsonl", turns)
        main(["session", jsonl, "--no-log"])
        out = capsys.readouterr().out

        assert "Session: integration" in out
        assert "Turns:   3" in out
        assert "Date:    2026-04-04" in out
        # Peak context = max(1200, 1250, 1900) = 1900
        assert "1,900" in out
        # Total output = 300 + 250 + 400 = 950
        assert "950" in out
        # Models section
        assert "opus" in out
        assert "sonnet" in out
        # Context growth bars
        assert "Context growth:" in out

    def test_full_session_with_log_append(self, tmp_path, capsys):
        """End-to-end: session without --no-log appends to a log file."""
        log_file = tmp_path / "token-usage-log.md"
        jsonl = _make_jsonl(tmp_path / "logtest.jsonl")

        # Point append_to_log to our temp file by passing it directly
        # We'll use the real append_to_log via monkeypatch of the default path
        from token_monitor import report

        orig_append = report.append_to_log

        def patched_append(stats, log_path=None):
            return orig_append(stats, log_path=str(log_file))

        import token_monitor.cli as cli_mod

        # Monkeypatch at the cli module level
        old_ref = cli_mod.append_to_log
        cli_mod.append_to_log = patched_append
        try:
            main(["session", jsonl])
        finally:
            cli_mod.append_to_log = old_ref

        out = capsys.readouterr().out
        assert "Logged to" in out
        assert log_file.exists()
        content = log_file.read_text()
        assert "logtest" in content

    def test_full_project_report(self, tmp_path, capsys):
        """End-to-end: create multiple sessions, run project report."""
        log_dir = tmp_path / "full_proj"
        log_dir.mkdir()

        _make_jsonl(
            log_dir / "aaa.jsonl",
            [
                {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 50,
                    "model": "claude-sonnet-4-20250514",
                    "timestamp": "2026-04-01T10:00:00Z",
                },
                {
                    "input_tokens": 500,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 200,
                    "output_tokens": 200,
                    "model": "claude-sonnet-4-20250514",
                    "timestamp": "2026-04-01T10:30:00Z",
                },
            ],
        )
        _make_jsonl(
            log_dir / "bbb.jsonl",
            [
                {
                    "input_tokens": 2000,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": 600,
                    "model": "claude-opus-4-20250514",
                    "timestamp": "2026-04-03T15:00:00Z",
                },
            ],
        )

        main(["project", str(log_dir)])
        out = capsys.readouterr().out

        assert "Sessions: 2" in out
        assert "2026-04-01" in out
        assert "2026-04-03" in out
        assert "aaa" in out
        assert "bbb" in out
        # Peak context ranking — bbb has higher peak (3500 vs 800)
        assert "3,500" in out
        assert "Sessions by peak context:" in out
