"""Context window analysis for Claude Code sessions.

Measures trimmable context components (CLAUDE.md, memory index, rules,
skill descriptions) and combines with JSONL usage data to produce an
actionable context report.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from token_monitor.parser import LastTurnUsage

# Model context window sizes (tokens)
MODEL_LIMITS = {
    "opus": 200_000,
    "sonnet": 200_000,
    "haiku": 200_000,
}

CHARS_PER_TOKEN = 3.5  # conservative estimate for mixed code/text
AUTOCOMPACT_BUFFER_PCT = 10.5  # reserved for autocompact


@dataclass
class FileEntry:
    """A single file's token estimate."""
    name: str
    tokens: int
    size_bytes: int


@dataclass
class ComponentGroup:
    """A group of context-contributing files."""
    label: str
    files: list[FileEntry] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files)


@dataclass
class ContextSnapshot:
    """Complete context analysis result."""
    usage: LastTurnUsage
    model_limit: int
    autocompact_buffer: int
    components: list[ComponentGroup] = field(default_factory=list)
    memory_files: list[FileEntry] = field(default_factory=list)
    large_memory_files: list[FileEntry] = field(default_factory=list)
    large_rule_files: list[FileEntry] = field(default_factory=list)

    @property
    def free(self) -> int:
        return self.model_limit - self.usage.total_context

    @property
    def pct_used(self) -> float:
        return (self.usage.total_context / self.model_limit) * 100

    @property
    def autocompact_headroom(self) -> int:
        return self.model_limit - self.autocompact_buffer - self.usage.total_context

    @property
    def trimmable_total(self) -> int:
        return sum(c.total_tokens for c in self.components)


def estimate_tokens(path: Path) -> int:
    """Estimate token count from file size."""
    if not path.exists():
        return 0
    return int(path.stat().st_size / CHARS_PER_TOKEN)


def _measure_file(path: Path) -> FileEntry | None:
    """Measure a single file, return None if it doesn't exist."""
    if not path.is_file():
        return None
    size = path.stat().st_size
    return FileEntry(name=path.name, tokens=int(size / CHARS_PER_TOKEN), size_bytes=size)


def _measure_dir(dir_path: Path, glob_pattern: str = "*.md") -> list[FileEntry]:
    """Measure all matching files in a directory."""
    if not dir_path.is_dir():
        return []
    entries = []
    for f in sorted(dir_path.glob(glob_pattern)):
        if f.is_file():
            size = f.stat().st_size
            entries.append(FileEntry(name=f.name, tokens=int(size / CHARS_PER_TOKEN), size_bytes=size))
    return entries


def _scan_skill_descriptions(skills_dir: Path) -> list[FileEntry]:
    """Estimate tokens for skill description stubs (always loaded).

    Only the description line of each SKILL.md is loaded into context,
    not the full file. Estimate from first ~300 chars.
    """
    if not skills_dir.is_dir():
        return []
    entries = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        with open(skill_file) as f:
            header = f.read(500)
        tokens = int(min(len(header), 300) / CHARS_PER_TOKEN)
        entries.append(FileEntry(name=skill_dir.name, tokens=tokens, size_bytes=len(header)))
    return entries


def model_limit_for(model_name: str) -> int:
    """Return the context window size for a model name."""
    for key, limit in MODEL_LIMITS.items():
        if key in model_name:
            return limit
    return MODEL_LIMITS["opus"]  # default


def analyze_context(
    usage: LastTurnUsage,
    project_dir: str,
    cwd: str | None = None,
    brief: bool = False,
) -> ContextSnapshot:
    """Build a complete context analysis.

    Args:
        usage: Token usage from the latest JSONL turn.
        project_dir: Claude Code project log directory
            (e.g. ~/.claude/projects/-home-user-myproject/).
        cwd: Working directory of the project (default: os.getcwd()).
        brief: If True, skip work only the verbose report consumes
            (per-memory-file enumeration, large-file scans, skill
            descriptions). Saves 2-3 dir walks + 20-50 file opens per
            hot-path invocation.
    """
    if cwd is None:
        cwd = os.getcwd()

    cwd_path = Path(cwd)
    home = Path.home()
    proj_dir = Path(project_dir)
    memory_dir = proj_dir / "memory"

    limit = model_limit_for(usage.model)
    autocompact_buffer = int(limit * AUTOCOMPACT_BUFFER_PCT / 100)

    components: list[ComponentGroup] = []

    # CLAUDE.md files (always loaded)
    for label, path in [
        ("Project CLAUDE.md", cwd_path / "CLAUDE.md"),
        ("Global CLAUDE.md", home / ".claude" / "CLAUDE.md"),
    ]:
        entry = _measure_file(path)
        if entry:
            components.append(ComponentGroup(label=label, files=[entry]))

    # Memory index only (MEMORY.md is always loaded; individual files on-demand)
    memory_index = memory_dir / "MEMORY.md"
    entry = _measure_file(memory_index)
    if entry:
        components.append(ComponentGroup(label="Memory index (MEMORY.md)", files=[entry]))

    # Rules (loaded when matching files are touched). Capture entries for reuse
    # by the large-rules filter below — avoids a second stat walk per dir.
    rule_dirs = [
        ("Project rules", cwd_path / ".claude" / "rules"),
        ("Global rules", home / ".claude" / "rules"),
    ]
    rule_entries_by_dir: list[list[FileEntry]] = []
    for label, dir_path in rule_dirs:
        entries = _measure_dir(dir_path)
        rule_entries_by_dir.append(entries)
        if entries:
            components.append(ComponentGroup(label=label, files=entries))

    if brief:
        # Per-file cap (~85 tokens at 300-char cap / 3.5) means no skill
        # can ever cross the 5% peak-trimmable threshold — skip the scan.
        return ContextSnapshot(
            usage=usage,
            model_limit=limit,
            autocompact_buffer=autocompact_buffer,
            components=components,
        )

    # Skill descriptions
    skills_dir = home / ".claude" / "skills"
    skill_entries = _scan_skill_descriptions(skills_dir)
    if skill_entries:
        components.append(ComponentGroup(label="Skill descriptions", files=skill_entries))

    # Memory files detail (on-demand, for trimming recommendations)
    mem_files = _measure_dir(memory_dir)
    mem_files = [f for f in mem_files if f.name != "MEMORY.md"]
    mem_files.sort(key=lambda f: f.size_bytes, reverse=True)

    large_mem = [f for f in mem_files if f.size_bytes > 2000]
    large_rules: list[FileEntry] = [
        e
        for entries in rule_entries_by_dir
        for e in entries
        if e.size_bytes > 3000
    ]

    return ContextSnapshot(
        usage=usage,
        model_limit=limit,
        autocompact_buffer=autocompact_buffer,
        components=components,
        memory_files=mem_files,
        large_memory_files=large_mem,
        large_rule_files=large_rules,
    )


def _format_k(tokens: int) -> str:
    """Format a token count compactly as e.g. '21k' or '1.2k'."""
    if tokens < 1000:
        return str(tokens)
    k = tokens / 1000
    return f"{k:.1f}k" if k < 10 else f"{int(round(k))}k"


def _brief_report(snapshot: ContextSnapshot) -> str:
    """Compact ~5-line context report suitable for embedding."""
    limit = snapshot.model_limit
    total = snapshot.usage.total_context
    pct = snapshot.pct_used
    headroom = snapshot.autocompact_headroom

    lines: list[str] = []
    lines.append(f"Model: {snapshot.usage.model} ({_format_k(limit)} window)")
    lines.append(
        f"Context: {pct:.1f}% "
        f"({_format_k(total)} used / {_format_k(snapshot.free)} free)"
    )
    compact_line = (
        f"Autocompact buffer: ~{_format_k(snapshot.autocompact_buffer)} "
        f"({AUTOCOMPACT_BUFFER_PCT}%)"
    )
    if headroom > 0:
        compact_line += f" | Until autocompact: ~{_format_k(headroom)}"
    else:
        compact_line += f" | ! {_format_k(-headroom)} past trigger"
    lines.append(compact_line)

    # Peak trimmable category, only if any single file exceeds 5% of window.
    threshold = limit * 0.05
    peak: tuple[str, FileEntry] | None = None
    for component in snapshot.components:
        for f in component.files:
            if f.tokens >= threshold and (peak is None or f.tokens > peak[1].tokens):
                peak = (component.label, f)
    if peak is not None:
        label, f = peak
        file_pct = f.tokens / limit * 100
        lines.append(
            f"Peak trimmable: {label} / {f.name} "
            f"~{_format_k(f.tokens)} ({file_pct:.1f}%)"
        )

    # Recommendations (only ! warnings, verbatim).
    if headroom <= 0:
        lines.append("! AUTOCOMPACT ACTIVE — context is being compressed")
    elif pct > 80:
        lines.append("! Context over 80% — autocompact will trigger soon")

    return "\n".join(lines)


def context_report(snapshot: ContextSnapshot, brief: bool = False) -> str:
    """Format a context analysis snapshot as a text report."""
    if brief:
        return _brief_report(snapshot)
    lines: list[str] = []
    total = snapshot.usage.total_context
    limit = snapshot.model_limit

    # Header
    lines.append("=" * 60)
    lines.append("CONTEXT ANALYSIS")
    lines.append("=" * 60)
    lines.append(f"Model:    {snapshot.usage.model} ({limit:,} token window)")
    lines.append("")

    # Usage bar
    bar_width = 40
    pct = snapshot.pct_used
    filled = int(pct / 100 * bar_width)
    bar = "#" * filled + "." * (bar_width - filled)
    lines.append(f"Context:  [{bar}] {pct:.1f}%")
    lines.append(f"  Used:       {total:,} tokens")
    lines.append(f"  Free:       {snapshot.free:,} tokens")
    lines.append(f"  Cache:      {snapshot.usage.cache_read:,} read + {snapshot.usage.cache_creation:,} created")
    lines.append(f"  Autocompact buffer: ~{snapshot.autocompact_buffer:,} tokens ({AUTOCOMPACT_BUFFER_PCT}%)")
    headroom = snapshot.autocompact_headroom
    if headroom > 0:
        lines.append(f"  Until autocompact:  ~{headroom:,} tokens")
    else:
        lines.append(f"  ! Autocompact zone: {-headroom:,} tokens past trigger")
    lines.append("")

    # Trimmable components
    lines.append("-" * 60)
    lines.append("TRIMMABLE COMPONENTS (files you can edit to reduce context)")
    lines.append("-" * 60)

    for component in snapshot.components:
        tok = component.total_tokens
        component_pct = (tok / limit) * 100
        lines.append(f"{component.label}: ~{tok:,} tokens ({component_pct:.1f}%)")
        for f in component.files:
            lines.append(f"  {f.name}: ~{f.tokens:,} tokens ({f.size_bytes:,} bytes)")

    lines.append("")
    trimmable = snapshot.trimmable_total
    lines.append(f"Total trimmable: ~{trimmable:,} tokens ({trimmable / limit * 100:.1f}% of window)")
    overhead = total - trimmable
    if overhead > 0:
        lines.append(f"Non-trimmable (system prompt + tools + messages): ~{overhead:,} tokens ({overhead / limit * 100:.1f}%)")
    lines.append("")

    # Memory files (on-demand)
    if snapshot.memory_files:
        lines.append("-" * 60)
        lines.append("MEMORY FILES (loaded on-demand, not always in context)")
        lines.append("-" * 60)
        for f in snapshot.memory_files:
            flag = " !" if f.size_bytes > 2000 else ""
            lines.append(f"  {f.name}: ~{f.tokens:,} tokens ({f.size_bytes:,} bytes){flag}")
        lines.append("")

    # Recommendations
    lines.append("-" * 60)
    lines.append("RECOMMENDATIONS")
    lines.append("-" * 60)

    has_recs = False

    if headroom <= 0:
        lines.append("! AUTOCOMPACT ACTIVE — context is being compressed")
        has_recs = True
    elif pct > 80:
        lines.append("! Context over 80% — autocompact will trigger soon")
        has_recs = True
    elif pct > 60:
        lines.append("~ Context at 60-80% — watch for large file reads")
        has_recs = True

    for f in snapshot.large_memory_files:
        lines.append(f"~ {f.name} ({f.size_bytes:,} bytes) — consider trimming")
        has_recs = True

    for f in snapshot.large_rule_files:
        lines.append(f"~ {f.name} ({f.size_bytes:,} bytes) — consider trimming")
        has_recs = True

    if not has_recs:
        lines.append("  Context usage is healthy — no action needed")

    lines.append("")
    return "\n".join(lines)
