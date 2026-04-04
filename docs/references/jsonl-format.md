# JSONL Log Format (Claude Code)

Each assistant message contains `message.usage`:
- `input_tokens` — new/uncached input
- `cache_creation_input_tokens` — newly cached
- `cache_read_input_tokens` — read from cache
- `output_tokens` — generated output
- Total context per turn = sum of the three input fields

Session logs live at: `~/.claude/projects/<project-slug>/<session-uuid>.jsonl`
Subagent logs: `~/.claude/projects/<project-slug>/<session-uuid>/subagents/agent-*.jsonl`
