# token-monitor

Visibility into where Claude Code session tokens are spent — so you optimize the right things.

## Why

Optimization without visibility risks fixing the wrong things. Claude Code's JSONL session logs already contain rich per-turn token data (input, cache, output, model), but there's no built-in way to review it. This project provides that visibility through four components:

1. **Analysis CLI** (`token-usage`) — parses JSONL logs into per-session and cross-project reports
2. **Persistent log** (`~/.claude/token-usage-log.md`) — append-only markdown table of every analyzed session
3. **Retro skill integration** (`~/.claude/skills/retro/SKILL.md`) — runs `token-usage session` automatically at end-of-session retrospectives, so usage is always logged
4. **Token efficiency rules** (`~/.claude/CLAUDE.md`) — a small set of high-confidence rules that reduce unnecessary token consumption (targeted reads, quiet test runs, specific search patterns)

The CLI is the centerpiece, but the global configs are what make it a system — usage gets logged automatically and Claude follows efficiency rules without being reminded.

## Install

```bash
uv venv && uv pip install -e ".[dev]"
```

Requires Python 3.10+. No external dependencies beyond pytest for tests.

## Usage

### Analyze a session

```bash
# Most recent session in current project
token-usage session

# Specific JSONL file
token-usage session ~/.claude/projects/-home-user-myproject/abc123.jsonl

# Skip appending to the persistent log
token-usage session --no-log
```

Output includes:
- Total turns, peak context, total output tokens
- Model breakdown (opus/sonnet/haiku turn counts)
- Context growth curve (text bar chart)
- Top 5 biggest context jumps between turns
- Subagent token summary (if any)

### Summarize a project

```bash
# All sessions in current project
token-usage project

# Specific project directory
token-usage project ~/.claude/projects/-home-user-myproject/
```

Output includes:
- Session count and date range
- Average, median, and max peak context
- All sessions ranked by peak context

### Persistent log

The `session` command appends a summary row to `~/.claude/token-usage-log.md` (created on first run). Use `--no-log` to skip.

```
| Date | Project | Session | Turns | Peak Ctx | Total Out | Model |
|------|---------|---------|-------|----------|-----------|-------|
| 2026-04-04 | home-user-myproject | f2818d38 | 173 | 154,875 | 40,718 | opus |
```

## Session discovery

The tool finds sessions by deriving a project slug from CWD using the same algorithm as Claude Code: `~/.claude/projects/<slug>/` where the slug is the absolute path with `/` replaced by `-`.

## Development

```bash
pytest tests/ -q        # run all 107 tests
pytest tests/ -v        # verbose output for debugging
```

Architecture details are in [CLAUDE.md](CLAUDE.md).
