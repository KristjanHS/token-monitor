Session retrospective — reflect on what was learned, update memories and project docs.

## Step 1: What did we learn?

List 3-6 concrete lessons from this session:
- What worked well?
- What broke or surprised you?
- What did the user correct?
- What would you do differently next time?

Focus on non-obvious insights. Skip things derivable from code or git history.

## Step 2: Capture corrections

For each user correction or confirmed approach:
1. Determine the best permanent home: `dev-workflow` skill (project-specific), `.claude/rules/*.md`, global `~/.claude/CLAUDE.md` (cross-project), or a memory file (personal context only).
2. Merge the rule into that target — don't create standalone `feedback_*.md` files. Feedback memories are a temporary inbox; rules graduate into skills/rules/CLAUDE.md where they're loaded in context.
3. If a rule is already covered elsewhere, skip it.

## Step 3: Update project memories

Update `project_state.md` with what was built:
- New modules, tables, endpoints, key decisions
- Test count changes
- Current status (committed? pushed? branch?)

Do NOT save ephemeral task details — only information useful in future sessions.

## Step 4: Reflect on CLAUDE.md and rules

Use the `reflect` skill to analyze the session for CLAUDE.md/rules improvements:

1. Scan conversation for repeated corrections, misunderstandings, or missing context that caused confusion
2. Check if any lesson belongs in a shared file (`./CLAUDE.md`, `.claude/rules/*.md`) vs personal memory
3. For each proposed change, present: **Issue → Proposal → Target file → Exact text**
4. Wait for user approval before writing

**Placement guide:**
| Type | Location | When |
|---|---|---|
| Team instructions | `./CLAUDE.md` | Affects all contributors |
| Topic-specific rules | `.claude/rules/*.md` | Modular, scoped to a domain |
| Personal preferences | `~/.claude/CLAUDE.md` | Cross-project personal style |
| Personal project prefs | `./CLAUDE.local.md` | Gitignored, project-specific |

**Anti-patterns to avoid:** hyperbolic language, vague instructions, historical comments, redundant information.

## Step 5: Consolidate instructions

Use the `writing-claude-directives` skill to audit all updated files for token efficiency:

1. Check for any remaining `feedback_*.md` files — merge into targets from Step 2, then delete
2. Review each updated skill/CLAUDE.md for: lines Claude already knows (cut), duplicates across files (pick one home), negative framing ("don't X" → say what TO do)
3. Verify skills stay under 500 lines, frequently-loaded files under 200 words

## Step 6: Token usage

Run `token-usage session` to analyze the current session's token usage. Include the key numbers (turns, peak context, total output) in the retrospective report.

## Step 7: Report

Present the lessons and all memory/doc updates to the user in a concise summary table.
