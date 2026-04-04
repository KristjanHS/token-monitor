# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A CLI tool for monitoring Claude Code token usage. Parses JSONL session logs to provide per-session and cross-project token usage analysis.

## Key Commands

```bash
# Set up dev environment
uv venv && uv pip install -e ".[dev]"

# Run the CLI (two equivalent entry points)
python -m token_monitor session                    # analyze most recent session
python -m token_monitor session <path-to-jsonl>    # analyze specific session
python -m token_monitor project                    # summarize all sessions in current project
python -m token_monitor project <path-to-dir>      # summarize specific project
token-usage session                                # installed entry point (same commands)

# Run tests
pytest tests/ -q

# Run a single test
pytest tests/test_parser.py::test_name -q
```

## Critical Rules

1. **Stdlib only** — no external dependencies. JSON parsing, file I/O, argparse only.
2. **After every change, run `pytest tests/ -q`** and verify all pass.
3. **JSONL log format is not ours to control** — be defensive about missing fields, never crash on unexpected data.

## Architecture & Data Flow

**CLI layer** (`cli.py`): argparse with two subcommands (`session`, `project`). Routes to `_cmd_session` or `_cmd_project`.

**Parser** (`parser.py`): Reads JSONL files line-by-line, extracts `message.usage` from `type: "assistant"` lines into `TurnUsage` dataclasses. Aggregates into `SessionStats` which computes derived metrics (peak context, model counts, context jumps) as properties. Also handles subagent discovery — looks for `<session-dir>/subagents/agent-*.jsonl` alongside the main session file.

**Report** (`report.py`): Pure formatting. `session_report()` produces a text report with context growth bars and subagent summary. `project_report()` ranks sessions by peak context. `append_to_log()` writes a markdown table row to `~/.claude/token-usage-log.md`.

**Key flow**: `find_project_log_dir(CWD)` → slug-based path lookup under `~/.claude/projects/` → `find_latest_session()` or `find_all_sessions()` → `parse_session()` → `session_report()`/`project_report()` → optional `append_to_log()`.

## JSONL Log Format (Claude Code)

Each assistant message contains `message.usage`:
- `input_tokens` — new/uncached input
- `cache_creation_input_tokens` — newly cached
- `cache_read_input_tokens` — read from cache
- `output_tokens` — generated output
- Total context per turn = sum of the three input fields

Session logs live at: `~/.claude/projects/<project-slug>/<session-uuid>.jsonl`
Subagent logs: `~/.claude/projects/<project-slug>/<session-uuid>/subagents/agent-*.jsonl`
