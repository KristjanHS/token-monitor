# Token Usage Monitoring & Optimization — Design
*Date: 2026-04-04 | Status: Approved*

## Goals

1. Gain visibility into where Claude Code session tokens are spent
2. Build a persistent log of token usage across sessions and projects
3. Reduce unnecessary token consumption through targeted CLAUDE.md rules

## Chosen Approach: Lean Monitoring + Auto-Logging

Observation-first strategy: build a monitoring script, log usage automatically via the `retro` skill, and add a small set of high-confidence efficiency rules to CLAUDE.md. No hooks, no complex infrastructure.

**Why this approach:** The brainstorm analysis identified that optimization without visibility risks fixing the wrong things. The JSONL logs already contain rich per-turn token data (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `model`). A parsing script is straightforward.

---

## Component 1: Analysis CLI (`token-usage`)

**Package:** `token_monitor` (installable via `uv pip install -e .`)
**Entry point:** `token-usage` CLI command, also runnable as `python -m token_monitor`
**Language:** Python, stdlib only (`json`, `os`, `glob`, `argparse`)

### Mode 1: `token-usage session [path]`

Analyzes a single session JSONL file. Default: most recent JSONL by mtime in the current project's log dir.

**Output:**
- Total assistant turns
- Peak context (max of `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` across turns)
- Total output tokens (sum across turns)
- Model breakdown (opus/sonnet/haiku turn counts)
- Context growth curve (text-based bar chart, one line per turn)
- Top 5 biggest context jumps between consecutive turns (identifies which tool call / message caused the spike)
- Subagent token usage summary (if `subagents/` directory exists alongside the session JSONL)

### Mode 2: `token-usage project [path]`

Analyzes all sessions in a project's log directory. Default: current project's log dir (`~/.claude/projects/<project-slug>/`).

**Output:**
- All sessions ranked by peak context
- All sessions ranked by total output tokens
- Average and median peak context
- Session count and date range

### Session JSONL Discovery

The script finds the current session's JSONL by:
1. Accept explicit path to a JSONL file
2. Default: derive the project slug from CWD (same algorithm Claude Code uses: `~/.claude/projects/-<path-with-dashes>/`), then pick the most recent JSONL by mtime in that directory

### Append to Log

The `session` mode appends a summary line to `~/.claude/token-usage-log.md` (created on first run). The `project` mode does not append (read-only summary).

---

## Component 2: Token Usage Log

**Location:** `~/.claude/token-usage-log.md`

**Format:**
```markdown
# Token Usage Log

| Date | Project | Session | Turns | Peak Ctx | Total Out | Model |
|------|---------|---------|-------|----------|-----------|-------|
| 2026-04-04 | edf-budget-planner | f2818d38 | 173 | 154,875 | 40,718 | opus |
```

- Session ID is truncated to first 8 chars for readability
- Project name is derived from the project directory slug
- Created automatically on first run if it doesn't exist
- Append-only; no automatic pruning

---

## Component 3: Retro Skill Update

**Location:** `~/.claude/skills/retro/SKILL.md`

Add a new step (between current Step 5 and Step 6) that runs the token analysis:

```
## Step N: Token usage

Run `token-usage session` to analyze the current session's token usage. Include the key numbers (turns, peak context, total output) in the retrospective report.
```

This ensures token usage is logged every time a session retrospective is performed — the natural end-of-session checkpoint.

---

## Component 4: CLAUDE.md Token Efficiency Rules

**Location:** `~/.claude/CLAUDE.md` (global)

Add the following section:

```markdown
## Token Efficiency

- Prefer targeted file reads (specific line ranges) over full-file reads.
- Run `pytest tests/ -q` by default. Use `-v` only when investigating failures.
- Use Glob/Grep with specific patterns — avoid broad exploratory searches.
- Don't re-read files already in context.
```

---

## Out of Scope

- Real-time hooks or warnings during sessions (add later if needed)
- Hard token budgets or enforcement mechanisms
- Session splitting rules (learn cadence from data first)
- Automatic session management or context pruning
- Plan document loading optimization (already handled by CLAUDE.md progressive disclosure)

---

## Implementation Tasks

### Task 1: Implement `token_monitor` package
**Files:** `token_monitor/__init__.py`, `cli.py`, `parser.py`, `report.py`, `__main__.py`
**Details:** Implement both `session` and `project` modes. Include `--help` output. Write tests.

### Task 2: Update `retro` skill
**Files:** `~/.claude/skills/retro/SKILL.md`
**Details:** Add token usage step between Step 5 and Step 6. Renumber Step 6 -> Step 7.

### Task 3: Add token efficiency rules to global CLAUDE.md
**Files:** `~/.claude/CLAUDE.md`
**Details:** Add the four-rule `## Token Efficiency` section.

### Dependency Graph

```
Task 1 (package) ─┐
                   ├─> all independent, can run in parallel
Task 2 (retro)   ─┤
Task 3 (CLAUDE)  ─┘
```

All three tasks are independent — no shared files, no ordering dependencies.
