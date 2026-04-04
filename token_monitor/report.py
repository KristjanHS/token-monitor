"""Output formatting for token usage reports."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from statistics import median

from token_monitor.parser import SessionStats, parse_subagents


def session_report(stats: SessionStats, show_subagents: bool = True) -> str:
    """Generate a detailed text report for a single session."""
    lines: list[str] = []

    lines.append(f"Session: {stats.session_id}")
    lines.append(f"Date:    {stats.date or 'unknown'}")
    lines.append(f"Turns:   {stats.num_turns}")
    lines.append(f"Peak:    {stats.peak_context:,} tokens")
    lines.append(f"Output:  {stats.total_output:,} tokens")
    lines.append("")

    # Model breakdown
    counts = stats.model_counts
    if counts:
        parts = [f"{name}: {count}" for name, count in sorted(counts.items())]
        lines.append(f"Models:  {', '.join(parts)}")
        lines.append("")

    # Context growth curve
    lines.append("Context growth:")
    if stats.turns:
        max_ctx = stats.peak_context or 1
        bar_width = 50
        # Sample turns if there are too many for display
        turns_to_show = stats.turns
        step = 1
        if len(stats.turns) > 40:
            step = len(stats.turns) // 40
            turns_to_show = stats.turns[::step]
            # Always include the last turn
            if turns_to_show[-1] is not stats.turns[-1]:
                turns_to_show.append(stats.turns[-1])

        for turn in turns_to_show:
            bar_len = int(turn.total_context / max_ctx * bar_width)
            bar = "\u2588" * bar_len
            lines.append(
                f"  {turn.turn_number:>4d}  {turn.total_context:>9,}  {bar}"
            )
    lines.append("")

    # Top 5 context jumps
    jumps = stats.context_jumps
    if jumps:
        lines.append("Biggest context jumps:")
        for turn_num, delta in jumps:
            lines.append(f"  Turn {turn_num:>4d}:  +{delta:>8,} tokens")
        lines.append("")

    # Subagent summary
    if show_subagents:
        subagents = parse_subagents(stats.jsonl_path)
        if subagents:
            lines.append(f"Subagents: {len(subagents)}")
            total_sa_output = sum(sa.total_output for sa in subagents)
            max_sa_peak = max(sa.peak_context for sa in subagents)
            lines.append(f"  Total subagent output: {total_sa_output:,} tokens")
            lines.append(f"  Max subagent peak ctx: {max_sa_peak:,} tokens")
            lines.append("")

    return "\n".join(lines)


def project_report(sessions: list[SessionStats]) -> str:
    """Generate a summary report for all sessions in a project."""
    lines: list[str] = []

    if not sessions:
        return "No sessions found."

    lines.append(f"Sessions: {len(sessions)}")

    # Date range
    dates = [s.date for s in sessions if s.date]
    if dates:
        lines.append(f"Range:    {min(dates)} to {max(dates)}")
    lines.append("")

    # Stats
    peaks = [s.peak_context for s in sessions if s.turns]
    if peaks:
        avg_peak = sum(peaks) // len(peaks)
        med_peak = int(median(peaks))
        lines.append(f"Peak context  — avg: {avg_peak:,}  median: {med_peak:,}  max: {max(peaks):,}")

    outputs = [s.total_output for s in sessions if s.turns]
    if outputs:
        avg_out = sum(outputs) // len(outputs)
        lines.append(f"Total output  — avg: {avg_out:,}  max: {max(outputs):,}")
    lines.append("")

    # Ranked by peak context
    lines.append("Sessions by peak context:")
    lines.append(f"  {'Session':>10s}  {'Date':>10s}  {'Turns':>5s}  {'Peak Ctx':>10s}  {'Output':>10s}  {'Model':>8s}")
    ranked = sorted(sessions, key=lambda s: s.peak_context, reverse=True)
    for s in ranked:
        lines.append(
            f"  {s.session_id[:10]:>10s}  {s.date or 'n/a':>10s}  {s.num_turns:>5d}"
            f"  {s.peak_context:>10,}  {s.total_output:>10,}  {s.dominant_model:>8s}"
        )
    lines.append("")

    return "\n".join(lines)


def append_to_log(stats: SessionStats, log_path: str | None = None) -> str:
    """Append a summary line to the token usage log. Returns the log path used."""
    if log_path is None:
        log_path = os.path.expanduser("~/.claude/token-usage-log.md")

    # Derive project name from the JSONL path
    # Path: ~/.claude/projects/-home-user-projects-foo/session.jsonl
    parent_name = Path(stats.jsonl_path).parent.name
    project_display = parent_name.lstrip("-")

    header = (
        "# Token Usage Log\n\n"
        "| Date | Project | Session | Turns | Peak Ctx | Total Out | Model |\n"
        "|------|---------|---------|-------|----------|-----------|-------|\n"
    )

    # Create file with header if it doesn't exist
    if not os.path.exists(log_path):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write(header)

    date = stats.date or datetime.now().strftime("%Y-%m-%d")
    session_short = stats.session_id[:8]

    line = (
        f"| {date} "
        f"| {project_display} "
        f"| {session_short} "
        f"| {stats.num_turns} "
        f"| {stats.peak_context:,} "
        f"| {stats.total_output:,} "
        f"| {stats.dominant_model} |\n"
    )

    with open(log_path, "a") as f:
        f.write(line)

    return log_path
