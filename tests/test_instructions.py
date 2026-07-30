"""Tests for layered project instructions."""

from corecoder.instructions import (
    find_project_root,
    format_project_instructions,
    load_project_instructions,
)


def test_loads_root_to_cwd_with_override_precedence(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("root rules")
    child = tmp_path / "services" / "api"
    child.mkdir(parents=True)
    (tmp_path / "services" / "AGENTS.md").write_text("service rules")
    (child / "AGENTS.md").write_text("ignored child rules")
    (child / "AGENTS.override.md").write_text("child override")

    sources = load_project_instructions(child)

    assert [source.path.name for source in sources] == [
        "AGENTS.md", "AGENTS.md", "AGENTS.override.md",
    ]
    assert [source.content for source in sources] == [
        "root rules", "service rules", "child override",
    ]
    assert not any(source.truncated for source in sources)
    rendered = format_project_instructions(sources)
    assert rendered.index("root rules") < rendered.index("child override")


def test_root_claude_file_is_compatibility_fallback(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.md").write_text("legacy rules")
    assert load_project_instructions(tmp_path)[0].content == "legacy rules"

    (tmp_path / "AGENTS.md").write_text("standard rules")
    sources = load_project_instructions(tmp_path)
    assert len(sources) == 1
    assert sources[0].content == "standard rules"


def test_instruction_budget_is_enforced(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("x" * 100)
    sources = load_project_instructions(tmp_path, max_bytes=12)
    assert len(sources[0].content.encode()) <= 12
    assert sources[0].truncated


def test_find_project_root_falls_back_to_cwd(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    assert find_project_root(child) == child
