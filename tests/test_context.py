"""Tests for token_monitor.context module."""
from __future__ import annotations

from pathlib import Path

from token_monitor.context import (
    ComponentGroup,
    ContextSnapshot,
    FileEntry,
    _scan_skill_descriptions,
    analyze_context,
    context_report,
    estimate_tokens,
    model_limit_for,
)
from token_monitor.parser import LastTurnUsage


def _usage(
    total_context: int = 50000,
    input_tokens: int = 1000,
    cache_creation: int = 2000,
    cache_read: int = 47000,
    output_tokens: int = 500,
    model: str = "claude-opus-4-6",
    turns: int = 10,
) -> LastTurnUsage:
    return LastTurnUsage(
        total_context=total_context, input_tokens=input_tokens,
        cache_creation=cache_creation, cache_read=cache_read,
        output_tokens=output_tokens, model=model, turns=turns,
    )


class TestEstimateTokens:
    def test_estimates_from_file_size(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("x" * 350)  # 350 chars / 3.5 = 100 tokens
        assert estimate_tokens(f) == 100

    def test_nonexistent_returns_zero(self, tmp_path: Path) -> None:
        assert estimate_tokens(tmp_path / "nope.md") == 0


class TestModelLimitFor:
    def test_opus(self) -> None:
        assert model_limit_for("claude-opus-4-6") == 200_000

    def test_sonnet(self) -> None:
        assert model_limit_for("claude-sonnet-4-6") == 200_000

    def test_unknown_defaults_to_opus(self) -> None:
        assert model_limit_for("gpt-4-turbo") == 200_000


class TestScanSkillDescriptions:
    def test_truncates_to_300_chars(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("x" * 500)

        entries = _scan_skill_descriptions(tmp_path)

        assert len(entries) == 1
        assert entries[0].name == "my-skill"
        # 300 chars (capped) / 3.5 = 85 tokens
        assert entries[0].tokens == 85

    def test_skips_dirs_without_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "has-skill").mkdir()
        (tmp_path / "has-skill" / "SKILL.md").write_text("content")
        (tmp_path / "no-skill").mkdir()
        (tmp_path / "no-skill" / "README.md").write_text("not a skill")

        entries = _scan_skill_descriptions(tmp_path)

        assert len(entries) == 1
        assert entries[0].name == "has-skill"

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _scan_skill_descriptions(tmp_path / "nope") == []


class TestAnalyzeContext:
    def test_finds_project_claude_md(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("x" * 350)
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        labels = [c.label for c in snapshot.components]
        assert "Project CLAUDE.md" in labels

    def test_finds_memory_index(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "proj"
        mem_dir = proj_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("- [foo](foo.md) — desc")

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        labels = [c.label for c in snapshot.components]
        assert "Memory index (MEMORY.md)" in labels

    def test_memory_files_exclude_index(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "proj"
        mem_dir = proj_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("index")
        (mem_dir / "state.md").write_text("state data")

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        mem_names = [f.name for f in snapshot.memory_files]
        assert "MEMORY.md" not in mem_names
        assert "state.md" in mem_names

    def test_large_memory_flagged(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "proj"
        mem_dir = proj_dir / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("idx")
        (mem_dir / "big.md").write_text("x" * 3000)
        (mem_dir / "small.md").write_text("x" * 500)

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        large_names = [f.name for f in snapshot.large_memory_files]
        assert "big.md" in large_names
        assert "small.md" not in large_names

    def test_finds_project_rules(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "dev.md").write_text("rule content")
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        labels = [c.label for c in snapshot.components]
        assert "Project rules" in labels

    def test_finds_skill_descriptions(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".claude" / "skills"
        skill_a = skills_dir / "my-skill"
        skill_a.mkdir(parents=True)
        (skill_a / "SKILL.md").write_text("x" * 400)
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        snapshot = analyze_context(_usage(), str(proj_dir), cwd=str(tmp_path))

        labels = [c.label for c in snapshot.components]
        assert "Skill descriptions" in labels

    def test_snapshot_properties(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        usage = _usage(total_context=100_000)

        snapshot = analyze_context(usage, str(proj_dir), cwd=str(tmp_path))

        assert snapshot.free == 100_000
        assert snapshot.pct_used == 50.0
        assert snapshot.autocompact_headroom == 100_000 - snapshot.autocompact_buffer


class TestContextReport:
    def _snapshot(self, pct_used: float = 25.0) -> ContextSnapshot:
        total = int(200_000 * pct_used / 100)
        return ContextSnapshot(
            usage=_usage(total_context=total),
            model_limit=200_000,
            autocompact_buffer=21_000,
            components=[
                ComponentGroup("Project CLAUDE.md", [FileEntry("CLAUDE.md", 1400, 5000)]),
                ComponentGroup("Memory index (MEMORY.md)", [FileEntry("MEMORY.md", 220, 770)]),
            ],
            memory_files=[
                FileEntry("state.md", 1200, 4200),
                FileEntry("prefs.md", 500, 1750),
            ],
            large_memory_files=[FileEntry("state.md", 1200, 4200)],
            large_rule_files=[],
        )

    def test_contains_header(self) -> None:
        report = context_report(self._snapshot())
        assert "CONTEXT ANALYSIS" in report

    def test_contains_usage_bar(self) -> None:
        report = context_report(self._snapshot())
        assert "Context:  [" in report
        assert "25.0%" in report

    def test_contains_autocompact_info(self) -> None:
        report = context_report(self._snapshot())
        assert "Autocompact buffer:" in report
        assert "Until autocompact:" in report

    def test_autocompact_zone_warning(self) -> None:
        report = context_report(self._snapshot(pct_used=95.0))
        assert "Autocompact zone:" in report

    def test_contains_trimmable_components(self) -> None:
        report = context_report(self._snapshot())
        assert "TRIMMABLE COMPONENTS" in report
        assert "Project CLAUDE.md" in report
        assert "Memory index" in report

    def test_contains_memory_files_section(self) -> None:
        report = context_report(self._snapshot())
        assert "MEMORY FILES" in report
        assert "state.md" in report
        assert "!" in report  # large file flag

    def test_contains_recommendations(self) -> None:
        report = context_report(self._snapshot())
        assert "RECOMMENDATIONS" in report

    def test_healthy_recommendation(self) -> None:
        snap = self._snapshot(pct_used=25.0)
        # Clear large files so no trimming recommendations are generated
        snap.large_memory_files = []
        report = context_report(snap)
        assert "healthy" in report

    def test_high_usage_warning(self) -> None:
        report = context_report(self._snapshot(pct_used=85.0))
        assert "over 80%" in report

    def test_large_memory_recommendation(self) -> None:
        report = context_report(self._snapshot())
        assert "state.md" in report
        assert "consider trimming" in report
