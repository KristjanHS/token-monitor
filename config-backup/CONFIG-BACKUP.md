# Config Backup

Global Claude Code config changes made to support token monitoring.
These files are backed up here for git tracking — the originals live in `~/.claude/`.

## Files

### `skills/retro/SKILL.md`
**Source:** `~/.claude/skills/retro/SKILL.md`
**Change:** Added Step 6 (Token usage) which runs `token-usage session` at end of each retro.
Step 7 (Report) was renumbered from the original Step 6.

**Note:** The retro *command* at `~/.claude/commands/retro.md` is a separate copy that
was NOT updated with Step 6. Sync it manually if needed.

### `global-claude-md-section.md`
**Source:** `~/.claude/CLAUDE.md` (the `## Token Efficiency` section)
**Change:** Added four rules to reduce unnecessary token consumption.
This is only the relevant section — the full global CLAUDE.md contains other unrelated config.

## Restoring

```bash
# Copy retro skill
cp config-backup/skills/retro/SKILL.md ~/.claude/skills/retro/SKILL.md

# Append token efficiency section to global CLAUDE.md (if not already present)
grep -q "## Token Efficiency" ~/.claude/CLAUDE.md || cat config-backup/global-claude-md-section.md >> ~/.claude/CLAUDE.md
```
