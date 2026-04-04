# token-monitor

CLI tool for analyzing Claude Code token usage from JSONL session logs.

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

## Integration with retro skill

The `retro` skill (`~/.claude/skills/retro/SKILL.md`) includes a token usage step (Step 6) that runs `token-usage session` at the end of each session retrospective, ensuring usage is logged automatically.

## Global CLAUDE.md rules

A `Token Efficiency` section in `~/.claude/CLAUDE.md` provides four rules to reduce unnecessary token consumption:
- Prefer targeted file reads over full-file reads
- Run `pytest tests/ -q` by default
- Use Glob/Grep with specific patterns
- Avoid re-reading files already in context

## Development

```bash
pytest tests/ -q        # run all 107 tests
pytest tests/ -v        # verbose output for debugging
```

Architecture details are in [CLAUDE.md](CLAUDE.md).
