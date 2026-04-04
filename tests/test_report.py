"""Tests for token_monitor.report module."""
from __future__ import annotations

from token_monitor.parser import SessionStats, TurnUsage
from token_monitor.report import append_to_log, project_report, session_report


# ---------------------------------------------------------------------------
# Helpers to build test data
# ---------------------------------------------------------------------------

def _turn(
    turn_number: int,
    input_tokens: int = 100,
    cache_creation_tokens: int = 50,
    cache_read_tokens: int = 50,
    output_tokens: int = 200,
    model: str = "claude-sonnet-4-20250514",
    timestamp: str = "2026-04-01T12:00:00Z",
) -> TurnUsage:
    return TurnUsage(
        turn_number=turn_number,
        input_tokens=input_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        output_tokens=output_tokens,
        model=model,
        timestamp=timestamp,
    )


def _session(
    session_id: str = "abc12345-6789-0000-1111-222233334444",
    jsonl_path: str = "/fake/path/session.jsonl",
    turns: list[TurnUsage] | None = None,
    date: str = "2026-04-01",
) -> SessionStats:
    return SessionStats(
        session_id=session_id,
        jsonl_path=jsonl_path,
        turns=turns if turns is not None else [],
        date=date,
    )


# ---------------------------------------------------------------------------
# session_report tests
# ---------------------------------------------------------------------------

class TestSessionReport:
    """Tests for session_report()."""

    def test_basic_fields_present(self):
        """Report contains session ID, date, turns, peak context, output."""
        turns = [
            _turn(1, input_tokens=1000, cache_creation_tokens=500,
                  cache_read_tokens=200, output_tokens=300),
            _turn(2, input_tokens=2000, cache_creation_tokens=800,
                  cache_read_tokens=400, output_tokens=500),
        ]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "abc12345-6789-0000-1111-222233334444" in report
        assert "2026-04-01" in report
        assert "Turns:   2" in report
        # Peak = max(1000+500+200, 2000+800+400) = 3200
        assert "3,200" in report
        # Total output = 300 + 500 = 800
        assert "Output:  800 tokens" in report

    def test_model_breakdown(self):
        """Report shows model counts when multiple models are used."""
        turns = [
            _turn(1, model="claude-sonnet-4-20250514"),
            _turn(2, model="claude-sonnet-4-20250514"),
            _turn(3, model="claude-opus-4-20250514"),
        ]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Models:" in report
        assert "opus: 1" in report
        assert "sonnet: 2" in report

    def test_context_growth_bars(self):
        """Report contains context growth section with bar characters."""
        turns = [
            _turn(1, input_tokens=100, cache_creation_tokens=0,
                  cache_read_tokens=0),
            _turn(2, input_tokens=500, cache_creation_tokens=0,
                  cache_read_tokens=0),
        ]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Context growth:" in report
        # Bar character (full block) should appear
        assert "\u2588" in report

    def test_context_growth_sampling_many_turns(self):
        """When >40 turns, context growth is sampled but last turn included."""
        turns = [_turn(i, input_tokens=i * 10) for i in range(1, 60)]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Context growth:" in report
        # Last turn number (59) should always appear
        assert "59" in report

    def test_context_jumps_present(self):
        """Report shows biggest context jumps section."""
        turns = [
            _turn(1, input_tokens=100, cache_creation_tokens=0,
                  cache_read_tokens=0),
            _turn(2, input_tokens=5000, cache_creation_tokens=0,
                  cache_read_tokens=0),
            _turn(3, input_tokens=5100, cache_creation_tokens=0,
                  cache_read_tokens=0),
        ]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Biggest context jumps:" in report
        # Jump from turn 1->2 is 4900
        assert "4,900" in report

    def test_no_context_jumps_when_single_turn(self):
        """No 'Biggest context jumps' section with only one turn."""
        turns = [_turn(1)]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Biggest context jumps:" not in report

    def test_no_turns_minimal_report(self):
        """Report with zero turns still includes session header."""
        stats = _session(turns=[])
        report = session_report(stats, show_subagents=False)

        assert "Session: abc12345" in report
        assert "Turns:   0" in report
        assert "Peak:    0 tokens" in report

    def test_unknown_date(self):
        """Date shows 'unknown' when not set."""
        stats = _session(date="", turns=[_turn(1)])
        report = session_report(stats, show_subagents=False)

        assert "Date:    unknown" in report

    def test_subagent_summary_shown(self, tmp_path):
        """When subagent JSONL files exist, their summary is included."""
        # Create a session JSONL
        session_file = tmp_path / "test-session.jsonl"
        session_file.write_text("")

        # Create subagent directory and a subagent JSONL file
        subagent_dir = tmp_path / "test-session" / "subagents"
        subagent_dir.mkdir(parents=True)
        sa_line = (
            '{"type":"assistant","message":{"usage":'
            '{"input_tokens":100,"cache_creation_input_tokens":0,'
            '"cache_read_input_tokens":0,"output_tokens":50},'
            '"model":"claude-sonnet-4-20250514"},"timestamp":"2026-04-01T12:00:00Z"}\n'
        )
        (subagent_dir / "agent-001.jsonl").write_text(sa_line)
        (subagent_dir / "agent-002.jsonl").write_text(sa_line)

        turns = [_turn(1)]
        stats = _session(
            jsonl_path=str(session_file),
            turns=turns,
        )
        report = session_report(stats, show_subagents=True)

        assert "Subagents: 2" in report
        assert "Total subagent output:" in report
        assert "Max subagent peak ctx:" in report

    def test_subagent_summary_hidden_when_disabled(self):
        """show_subagents=False suppresses subagent section."""
        turns = [_turn(1)]
        stats = _session(turns=turns)
        report = session_report(stats, show_subagents=False)

        assert "Subagents:" not in report

    def test_no_subagent_dir_no_section(self, tmp_path):
        """When no subagent directory exists, no subagent section appears."""
        session_file = tmp_path / "test-session.jsonl"
        session_file.write_text("")

        turns = [_turn(1)]
        stats = _session(jsonl_path=str(session_file), turns=turns)
        report = session_report(stats, show_subagents=True)

        assert "Subagents:" not in report

    def test_model_section_absent_when_no_turns(self):
        """No 'Models:' section when there are no turns."""
        stats = _session(turns=[])
        report = session_report(stats, show_subagents=False)

        assert "Models:" not in report


# ---------------------------------------------------------------------------
# project_report tests
# ---------------------------------------------------------------------------

class TestProjectReport:
    """Tests for project_report()."""

    def test_empty_sessions(self):
        """Returns simple message for empty list."""
        report = project_report([])
        assert report == "No sessions found."

    def test_single_session(self):
        """Report with one session shows counts and table."""
        turns = [
            _turn(1, input_tokens=1000, cache_creation_tokens=200,
                  cache_read_tokens=100, output_tokens=400),
        ]
        sessions = [_session(turns=turns)]
        report = project_report(sessions)

        assert "Sessions: 1" in report
        assert "2026-04-01" in report
        # Peak = 1000+200+100 = 1300
        assert "1,300" in report
        # Table header
        assert "Sessions by peak context:" in report

    def test_multiple_sessions(self):
        """Report with multiple sessions shows stats and ranked table."""
        s1 = _session(
            session_id="session-aaa",
            turns=[_turn(1, input_tokens=500, cache_creation_tokens=0,
                         cache_read_tokens=0, output_tokens=100)],
            date="2026-04-01",
        )
        s2 = _session(
            session_id="session-bbb",
            turns=[
                _turn(1, input_tokens=1000, cache_creation_tokens=0,
                      cache_read_tokens=0, output_tokens=200),
                _turn(2, input_tokens=3000, cache_creation_tokens=0,
                      cache_read_tokens=0, output_tokens=300),
            ],
            date="2026-04-02",
        )
        s3 = _session(
            session_id="session-ccc",
            turns=[_turn(1, input_tokens=2000, cache_creation_tokens=0,
                         cache_read_tokens=0, output_tokens=150)],
            date="2026-04-03",
        )
        report = project_report([s1, s2, s3])

        assert "Sessions: 3" in report
        assert "Range:    2026-04-01 to 2026-04-03" in report

        # Check average and median peak context
        # Peaks: s1=500, s2=3000, s3=2000
        # avg = (500+3000+2000)//3 = 1833
        # median = 2000
        assert "avg: 1,833" in report
        assert "median: 2,000" in report
        assert "max: 3,000" in report

        # Average total output
        # Outputs: s1=100, s2=500, s3=150
        # avg = (100+500+150)//3 = 250
        assert "avg: 250" in report

        # Table ranked by peak context, so session-bbb should be first
        lines = report.split("\n")
        table_lines = [line for line in lines if "session-" in line]
        assert len(table_lines) == 3
        # First table entry should be session-bbb (peak=3000)
        assert "session-bb" in table_lines[0]

    def test_date_range_with_missing_dates(self):
        """Date range only considers sessions that have dates."""
        s1 = _session(
            session_id="s1",
            turns=[_turn(1)],
            date="2026-04-01",
        )
        s2 = _session(
            session_id="s2",
            turns=[_turn(1)],
            date="",
        )
        report = project_report([s1, s2])

        assert "Range:    2026-04-01 to 2026-04-01" in report

    def test_no_dates_at_all(self):
        """When no sessions have dates, Range line is absent."""
        s = _session(session_id="s1", turns=[_turn(1)], date="")
        report = project_report([s])

        assert "Range:" not in report

    def test_sessions_with_no_turns(self):
        """Sessions with no turns still appear in table but don't affect stats."""
        s_empty = _session(session_id="empty-sess", turns=[], date="2026-04-01")
        s_real = _session(
            session_id="real-sess0",
            turns=[_turn(1, input_tokens=1000, cache_creation_tokens=0,
                         cache_read_tokens=0, output_tokens=200)],
            date="2026-04-02",
        )
        report = project_report([s_empty, s_real])

        assert "Sessions: 2" in report
        # Stats computed only from sessions with turns
        assert "avg: 1,000" in report
        # Both appear in the ranked table
        assert "empty-sess" in report
        assert "real-sess0" in report

    def test_dominant_model_in_table(self):
        """Dominant model appears in the ranked session table."""
        turns = [
            _turn(1, model="claude-opus-4-20250514"),
            _turn(2, model="claude-opus-4-20250514"),
            _turn(3, model="claude-sonnet-4-20250514"),
        ]
        s = _session(session_id="model-test0", turns=turns)
        report = project_report([s])

        # dominant_model should be opus (2 vs 1)
        lines = [line for line in report.split("\n") if "model-test" in line]
        assert len(lines) == 1
        assert "opus" in lines[0]


# ---------------------------------------------------------------------------
# append_to_log tests
# ---------------------------------------------------------------------------

class TestAppendToLog:
    """Tests for append_to_log()."""

    def test_creates_file_with_header(self, tmp_path):
        """First call creates the file with a markdown table header."""
        log_file = tmp_path / "token-usage-log.md"
        stats = _session(
            turns=[_turn(1, input_tokens=1000, cache_creation_tokens=200,
                         cache_read_tokens=100, output_tokens=400)],
        )

        result_path = append_to_log(stats, log_path=str(log_file))

        assert result_path == str(log_file)
        content = log_file.read_text()
        assert "# Token Usage Log" in content
        assert "| Date | Project | Session | Turns | Peak Ctx | Total Out | Model |" in content
        assert "|------|---------|---------|-------|----------|-----------|-------|" in content

    def test_appends_data_line(self, tmp_path):
        """Data line is appended after the header."""
        log_file = tmp_path / "token-usage-log.md"
        turns = [
            _turn(1, input_tokens=1000, cache_creation_tokens=200,
                  cache_read_tokens=100, output_tokens=400),
        ]
        stats = _session(turns=turns)

        append_to_log(stats, log_path=str(log_file))
        content = log_file.read_text()

        # Check data line has expected fields
        lines = content.strip().split("\n")
        data_line = lines[-1]
        assert data_line.startswith("| 2026-04-01")
        assert "| abc12345 |" in data_line  # session short ID (first 8 chars)
        assert "| 1 |" in data_line  # 1 turn
        assert "| 1,300 |" in data_line  # peak context
        assert "| 400 |" in data_line  # total output
        assert "| sonnet |" in data_line  # dominant model

    def test_subsequent_appends(self, tmp_path):
        """Second call appends without duplicating the header."""
        log_file = tmp_path / "token-usage-log.md"

        s1 = _session(
            session_id="first-session-id-0000",
            turns=[_turn(1, output_tokens=100)],
            date="2026-04-01",
        )
        s2 = _session(
            session_id="second-session-id-000",
            turns=[_turn(1, output_tokens=200)],
            date="2026-04-02",
        )

        append_to_log(s1, log_path=str(log_file))
        append_to_log(s2, log_path=str(log_file))

        content = log_file.read_text()

        # Header appears only once
        assert content.count("# Token Usage Log") == 1
        assert content.count("|------|") == 1

        # Both data rows present
        assert "first-se" in content  # first 8 chars
        assert "second-s" in content

    def test_project_name_derivation(self, tmp_path):
        """Project name is derived from the parent directory of the JSONL path."""
        log_file = tmp_path / "token-usage-log.md"
        jsonl_path = "/home/user/.claude/projects/-home-user-projects-myapp/session.jsonl"

        stats = _session(jsonl_path=jsonl_path, turns=[_turn(1)])
        append_to_log(stats, log_path=str(log_file))

        content = log_file.read_text()
        # Parent name is "-home-user-projects-myapp", lstrip("-") gives
        # "home-user-projects-myapp"
        assert "home-user-projects-myapp" in content

    def test_creates_parent_directories(self, tmp_path):
        """append_to_log creates parent directories if they don't exist."""
        log_file = tmp_path / "deep" / "nested" / "dir" / "log.md"
        stats = _session(turns=[_turn(1)])

        append_to_log(stats, log_path=str(log_file))

        assert log_file.exists()

    def test_date_fallback_when_missing(self, tmp_path):
        """When session has no date, current date is used."""
        log_file = tmp_path / "token-usage-log.md"
        stats = _session(date="", turns=[_turn(1)])

        append_to_log(stats, log_path=str(log_file))

        content = log_file.read_text()
        lines = content.strip().split("\n")
        data_line = lines[-1]
        # Should contain a date in YYYY-MM-DD format
        import re
        assert re.search(r"\| 20\d\d-\d\d-\d\d ", data_line)

    def test_no_turns_session_logged(self, tmp_path):
        """A session with no turns can still be logged (peak=0, output=0)."""
        log_file = tmp_path / "token-usage-log.md"
        stats = _session(turns=[])

        append_to_log(stats, log_path=str(log_file))

        content = log_file.read_text()
        lines = content.strip().split("\n")
        data_line = lines[-1]
        assert "| 0 |" in data_line  # 0 turns
        assert "| unknown |" in data_line  # no dominant model
