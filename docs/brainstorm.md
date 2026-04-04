# Claude Code Token Usage — Brainstorm Notes
*Date: 2026-04-04 | Status: Complete — design approved*

---

## Problem

Running out of Claude Code session tokens on the Max plan, even for seemingly small projects. The immediate trigger was the `edf-budget-planner` redesign session, which used a large plan doc (`2026-04-02-rebuild-redesign-design.md`) as a reference and involved broad codebase exploration plus heavy tool use.

---

## What We Know About the Session

- Plan document was referenced manually (not auto-loaded)
- `CLAUDE.md` is small — not a significant contributor
- Claude Code explored the repo broadly (not just the files relevant to the task)
- Heavy tool use: bash commands, file reads, possibly web search
- Session was long with back-and-forth conversation

---

## Root Cause Analysis

### The Mechanism (key insight)

Every tool call result — bash command output, file read, test run output, search result — is appended to the context window **verbosely and permanently** for the entire session duration. It is never pruned or summarized. This compounds multiplicatively:

- 1 `find . -type f` on a messy repo -> potentially thousands of tokens
- 1 failed test with a long stack trace -> thousands more
- 10-20 such tool calls -> the dominant token cost of the session

The plan document and conversation length are *visible* culprits but likely secondary to tool output accumulation.

---

## Challenged Assumptions

| Assumption | Reality |
|---|---|
| "The plan doc is the main drain" | A 500-line doc ~ 4-6k tokens. Tool results from 10-20 calls can be 10-20x that. |
| "Conversation length is the driver" | Accumulation within a session is the issue, not conversation length per se. |
| "I need to optimize my behavior" | Without visibility into what Claude Code is actually doing, optimization is blind. |
| "Max plan should cover any project" | Claude Code's agentic mode is designed to burn context fast. Broad exploration in one session can legitimately max out Max. |
| "Fix it after it happens" | Most effective interventions are *before* and *during* a session, not after. |

---

## Three Approaches Considered

### Approach 1 — Observe First, Fix Second

Pure monitoring before any optimization. Use `/cost`, parse JSONL logs, identify actual hotspots.

### Approach 2 — Constrain Upfront, Monitor Loosely

Scoped prompts, task slicing, tell Claude Code what not to explore.

### Approach 3 — Full System (Monitoring + Guardrails + Habits)

Combine monitoring infrastructure with structural prevention.

---

## Decision

**Approach B (Lean Monitoring + Auto-Logging):** Build a monitoring script with two modes, auto-log via the `retro` skill, and add a small set of high-confidence CLAUDE.md efficiency rules. See `docs/plans/2026-04-04-token-monitoring-design.md` for the full approved design.

---

## Validated Findings from Log Analysis

Analysis of 40 EDF project sessions confirmed the root cause hypothesis:

- Peak context in any session: **220,604 tokens**
- Largest session: 173 turns, peaked at 154K, **17.6M total input summed across all turns**
- Context grows monotonically — never shrinks within a session
- Total output across all sessions: ~1M tokens

JSONL format is rich and parseable. Each assistant turn has: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `model`.
