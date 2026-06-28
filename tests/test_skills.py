"""Tests for the skills system."""

from pathlib import Path

import pytest

from corecoder.skills import (
    Skill,
    discover_skills,
    format_skills_directory,
    format_skill_invocation,
    find_skill_by_name,
    load_skill,
    _parse_frontmatter,
    _find_skills_dir,
)
from corecoder.prompt import system_prompt
from corecoder.tools import ALL_TOOLS


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nname: foo\ndescription: bar\n---\nBody here."
        meta, body = _parse_frontmatter(text)
        assert meta == {"name": "foo", "description": "bar"}
        assert body == "Body here."

    def test_without_frontmatter(self):
        text = "Just a body, no frontmatter."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\nBody."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Body."

    def test_comment_lines_ignored(self):
        text = "---\n# comment\nname: hello\n---\nBody."
        meta, body = _parse_frontmatter(text)
        assert meta == {"name": "hello"}
        assert body == "Body."

    def test_colon_in_value(self):
        text = "---\ndescription: key: val\n---\nBody."
        meta, body = _parse_frontmatter(text)
        assert meta["description"] == "key: val"


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------

class TestLoadSkill:
    def test_with_frontmatter(self, tmp_path):
        md = tmp_path / "python-expert.md"
        md.write_text(
            "---\nname: python-expert\ndescription: Python patterns\n---\n"
            "Use type hints.\n"
        )
        skill = load_skill(md)
        assert skill.name == "python-expert"
        assert skill.description == "Python patterns"
        assert skill.content == "Use type hints."
        assert skill.source_path == md

    def test_without_frontmatter(self, tmp_path):
        md = tmp_path / "general.md"
        md.write_text("Just some instructions.\n")
        skill = load_skill(md)
        assert skill.name == "general"
        assert skill.description == ""
        assert skill.content == "Just some instructions."

    def test_name_defaults_to_filename(self, tmp_path):
        md = tmp_path / "my-skill.md"
        md.write_text("---\n---\nContent.\n")
        skill = load_skill(md)
        assert skill.name == "my-skill"


# ---------------------------------------------------------------------------
# discover_skills
# ---------------------------------------------------------------------------

class TestDiscoverSkills:
    def test_empty_when_no_dir(self, tmp_path):
        skills = discover_skills(cwd=tmp_path)
        assert skills == []

    def test_finds_md_files(self, tmp_path):
        skills_dir = tmp_path / ".corecoder" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "a.md").write_text("---\nname: a\n---\nAAA")
        (skills_dir / "b.md").write_text("---\nname: b\n---\nBBB")
        (skills_dir / "ignore.txt").write_text("not a skill")

        skills = discover_skills(cwd=tmp_path)
        assert len(skills) == 2
        assert {s.name for s in skills} == {"a", "b"}

    def test_walk_up_finds_parent(self, tmp_path):
        skills_dir = tmp_path / ".corecoder" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "parent.md").write_text("---\n---\nFrom parent")

        child = tmp_path / "subdir"
        child.mkdir()
        skills = discover_skills(cwd=child)
        assert len(skills) == 1
        assert skills[0].name == "parent"

    def test_closest_wins(self, tmp_path):
        # parent has a skill
        parent_dir = tmp_path / ".corecoder" / "skills"
        parent_dir.mkdir(parents=True)
        (parent_dir / "parent.md").write_text("---\n---\nParent")

        # child has a different skill
        child = tmp_path / "child"
        child_dir = child / ".corecoder" / "skills"
        child_dir.mkdir(parents=True)
        (child_dir / "child.md").write_text("---\n---\nChild")

        skills = discover_skills(cwd=child)
        assert len(skills) == 1
        assert skills[0].name == "child"


# ---------------------------------------------------------------------------
# format_skills_directory (lightweight — only name + description)
# ---------------------------------------------------------------------------

class TestFormatSkillsDirectory:
    def test_empty(self):
        assert format_skills_directory([]) == ""

    def test_single_skill_with_description(self):
        skill = Skill(name="python", description="Python expert", content="Use type hints.")
        result = format_skills_directory([skill])
        assert "## python" not in result  # no content headers
        assert "python" in result
        assert "Python expert" in result
        # Full content should NOT appear in the directory
        assert "Use type hints." not in result

    def test_multiple_skills(self):
        s1 = Skill(name="a", description="Desc A", content="AAA")
        s2 = Skill(name="b", description="Desc B", content="BBB")
        result = format_skills_directory([s1, s2])
        assert "**a**" in result
        assert "**b**" in result
        assert "Desc A" in result
        assert "Desc B" in result
        # Content should not appear
        assert "AAA" not in result
        assert "BBB" not in result

    def test_no_description_no_colon(self):
        skill = Skill(name="minimal", description="", content="Do stuff.")
        result = format_skills_directory([skill])
        assert "- **minimal**" in result
        # Should not have a trailing colon for empty description
        assert "minimal**:" not in result

    def test_directory_is_compact(self):
        """Directory should be much shorter than full content injection."""
        skill = Skill(
            name="big-skill",
            description="A very long skill",
            content="Line 1\n" * 100,
        )
        directory = format_skills_directory([skill])
        invocation = format_skill_invocation(skill)
        assert len(directory) < len(invocation) / 3


# ---------------------------------------------------------------------------
# format_skill_invocation (full content — for on-demand injection)
# ---------------------------------------------------------------------------

class TestFormatSkillInvocation:
    def test_includes_skill_name(self):
        skill = Skill(name="python", description="", content="Use type hints.")
        result = format_skill_invocation(skill)
        assert "[Skill: python]" in result

    def test_includes_full_content(self):
        skill = Skill(name="python", description="Python expert", content="Use type hints.\nPrefer dataclasses.")
        result = format_skill_invocation(skill)
        assert "Use type hints." in result
        assert "Prefer dataclasses." in result
        # Description is NOT in the invocation — it's in the directory already
        assert "Python expert" not in result


# ---------------------------------------------------------------------------
# find_skill_by_name
# ---------------------------------------------------------------------------

class TestFindSkillByName:
    def test_exact_match(self):
        skills = [Skill(name="python-expert", description="", content="x")]
        assert find_skill_by_name(skills, "python-expert") is skills[0]

    def test_case_insensitive(self):
        skills = [Skill(name="Python-Expert", description="", content="x")]
        assert find_skill_by_name(skills, "python-expert") is skills[0]

    def test_not_found(self):
        skills = [Skill(name="python-expert", description="", content="x")]
        assert find_skill_by_name(skills, "unknown") is None

    def test_empty_list(self):
        assert find_skill_by_name([], "anything") is None


# ---------------------------------------------------------------------------
# Integration: system_prompt with skills
# ---------------------------------------------------------------------------

class TestSystemPromptWithSkills:
    def test_no_skills(self):
        prompt = system_prompt(ALL_TOOLS)
        assert "# Skills" not in prompt

    def test_directory_only_in_system_prompt(self):
        """System prompt should contain only the directory, not full content."""
        skills = [
            Skill(name="python", description="Python expert", content="Use type hints. Prefer dataclasses."),
        ]
        prompt = system_prompt(ALL_TOOLS, skills=skills)
        assert "# Skills" in prompt
        assert "python" in prompt
        assert "Python expert" in prompt
        # Full content should NOT be in the system prompt
        assert "Use type hints." not in prompt
        assert "Prefer dataclasses." not in prompt

    def test_existing_sections_preserved(self):
        skills = [Skill(name="x", description="", content="Content")]
        prompt = system_prompt(ALL_TOOLS, skills=skills)
        assert "# Tools" in prompt
        assert "# Rules" in prompt
